"""ARQ worker: runs each crawl as a Scrapy subprocess.

Scrapy is *not* run in-process. The Twisted reactor cannot be restarted, so a
second job in the same worker would fail; a subprocess also keeps a crashing
crawl from taking the worker down with it.

The worker is the only place holding the subprocess handle, so it is also the
only place that can stop it. Pause and cancel therefore arrive indirectly: the
API writes a request into ``job:{id}:control`` and the loop below picks it up.

Run with::

    uv run arq worker.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.job_store import CONTROL_CANCEL, CONTROL_PAUSE, JobStore  # noqa: E402
from app.urls import site_slug  # noqa: E402
from worker import control  # noqa: E402
from worker.failure import describe_failure  # noqa: E402

logger = logging.getLogger("worker")

# How often the control key is checked while a crawl runs. A pause should feel
# immediate without hammering Redis.
CONTROL_POLL_SECONDS = 1.0


async def run_crawl(
    ctx: dict[str, Any],
    job_id: str,
    url: str,
    max_pages: int,
    use_js: bool,
    use_sitemap: bool = False,
    download_files: bool = False,
    extract_contacts: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    store: JobStore = ctx["job_store"]

    site = site_slug(url)
    job_dir = settings.job_data_dir(site, job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    jobdir = settings.job_jobdir_path(site, job_id)
    files_store = settings.job_files_dir(site, job_id)

    # A jobdir left by an earlier run is what makes this a resume rather than a
    # fresh crawl. It is never cleared here: clearing it would discard exactly
    # the frontier we are trying to continue from.
    resuming = control.has_jobdir_state(jobdir)
    if resuming:
        pending = control.queued_requests(jobdir)
        logger.info("job %s: resuming from %s queued requests", job_id, pending)
    else:
        jobdir.mkdir(parents=True, exist_ok=True)

    # Any control request left over from the previous run would stop this one
    # the moment it starts.
    await store.clear_control(job_id)
    await store.mark_running(job_id, jobdir=str(jobdir))

    # 0 means "crawl the whole site"; the ceiling still applies as a backstop.
    page_cap = max_pages if max_pages > 0 else settings.crawl_page_ceiling

    command = [
        sys.executable,
        "-m",
        "scrapy",
        "crawl",
        "site",
        "-a", f"job_id={job_id}",
        "-a", f"start_url={url}",
        "-a", f"max_pages={page_cap}",
        "-a", f"use_js={'true' if use_js else 'false'}",
        "-a", f"use_sitemap={'true' if use_sitemap else 'false'}",
        "-a", f"download_files={'true' if download_files else 'false'}",
        "-a", f"extract_contacts={'true' if extract_contacts else 'false'}",
        # Settings are frozen before the spider is built, so these have to
        # arrive as settings overrides rather than spider arguments. There is no
        # DEPTH_LIMIT: the crawl follows internal links to the end of the site.
        "-s", f"CLOSESPIDER_PAGECOUNT={page_cap}",
        # The persisted scheduler queue. This is what makes pause/resume exact.
        "-s", f"JOBDIR={jobdir}",
        "-s", f"FILES_STORE={files_store}",
    ]
    logger.info("job %s: %s", job_id, " ".join(command))

    if download_files:
        files_store.mkdir(parents=True, exist_ok=True)

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BACKEND_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Own signal group, so a pause reaches the crawl and not the worker.
            **control.creation_flags(),
        )
    except OSError as exc:
        await store.mark_failed(job_id, f"Could not start Scrapy: {exc}")
        raise

    await store.set_pid(job_id, process.pid)
    logger.info("job %s: scrapy pid %s", job_id, process.pid)

    # Playwright shutdown is far slower than a plain HTTP crawl, and being
    # killed mid-shutdown is what loses the frontier.
    grace = (
        settings.pause_grace_seconds_js if use_js else settings.pause_grace_seconds
    )

    try:
        outcome, log = await _supervise(process, job_id, store, grace)
    except asyncio.CancelledError:
        # ARQ timeout or worker shutdown: stop the child before we go.
        await control.stop_gracefully(process, grace)
        await store.set_pid(job_id, None)
        await store.mark_failed(job_id, "Crawl cancelled or timed out")
        raise
    finally:
        await store.set_pid(job_id, None)

    if outcome == CONTROL_PAUSE:
        await store.clear_control(job_id)
        await store.mark_paused(job_id)
        state = await store.get(job_id)
        pages = state.pages_crawled if state else 0
        logger.info("job %s: paused at %s pages", job_id, pages)
        # A clean return, not a raised error: a paused job has not failed.
        return {"job_id": job_id, "status": "paused", "pages_crawled": pages}

    if outcome == CONTROL_CANCEL:
        await store.clear_control(job_id)
        # Partial output stays; only the resume state goes.
        _remove_jobdir(jobdir)
        await store.mark_cancelled(job_id)
        state = await store.get(job_id)
        pages = state.pages_crawled if state else 0
        logger.info("job %s: cancelled at %s pages", job_id, pages)
        return {"job_id": job_id, "status": "cancelled", "pages_crawled": pages}

    returncode = process.returncode

    if returncode != 0:
        logger.error("job %s: scrapy exited %s", job_id, returncode)
        await store.mark_failed(
            job_id, describe_failure(f"scrapy exited with {returncode}", log)
        )
        return {"job_id": job_id, "returncode": returncode}

    state = await store.get(job_id)
    pages = state.pages_crawled if state else 0
    if pages == 0:
        # Exit code 0 with nothing stored means the site blocked us, robots.txt
        # disallowed the start URL, every page extracted empty, or (for a Render
        # JS crawl) the browser is missing; describe_failure tells these apart.
        await store.mark_failed(
            job_id, describe_failure("Crawl produced no pages.", log)
        )
        return {"job_id": job_id, "returncode": returncode, "pages_crawled": 0}

    # The crawl ran to the end, so the frontier is spent and worth nothing.
    _remove_jobdir(jobdir)
    await store.mark_completed(job_id)
    logger.info("job %s: completed with %s pages", job_id, pages)
    return {"job_id": job_id, "returncode": returncode, "pages_crawled": pages}


async def _supervise(
    process: asyncio.subprocess.Process,
    job_id: str,
    store: JobStore,
    grace: float = control.GRACE_SECONDS,
) -> tuple[str, str]:
    """Run the crawl to completion, or until a pause/cancel arrives.

    Returns `(outcome, log)` where outcome is "", "pause" or "cancel".

    stderr is drained on its own task throughout: Scrapy is chatty, and a full
    pipe buffer would deadlock the subprocess long before the crawl finished.
    """
    stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else _nothing())
    wait_task = asyncio.create_task(process.wait())
    outcome = ""

    try:
        while True:
            done, _ = await asyncio.wait(
                {wait_task}, timeout=CONTROL_POLL_SECONDS
            )
            if wait_task in done:
                break

            requested = await store.read_control(job_id)
            if requested in (CONTROL_PAUSE, CONTROL_CANCEL):
                logger.info("job %s: %s requested", job_id, requested)
                if requested == CONTROL_PAUSE:
                    await store.mark_pausing(job_id)
                outcome = requested
                # Graceful either way: on cancel the flush is wasted, but a
                # clean close still lets the pipelines finish their last write.
                how = await control.stop_gracefully(process, grace)
                if how == "killed" and requested == CONTROL_PAUSE:
                    # Scrapy writes the queue count into JOBDIR only while
                    # closing, so a killed pause leaves a frontier that reads
                    # back as empty: the resume would quietly restart instead.
                    logger.warning(
                        "job %s: pause overran its %.0fs grace and was killed; "
                        "the saved frontier may be incomplete",
                        job_id,
                        grace,
                    )
                else:
                    logger.info("job %s: stop was %s", job_id, how)
                break
    finally:
        if not wait_task.done():
            await wait_task

    log = ""
    try:
        raw = await asyncio.wait_for(stderr_task, timeout=30)
        log = raw.decode("utf-8", errors="replace") if raw else ""
    except (asyncio.TimeoutError, asyncio.CancelledError):
        stderr_task.cancel()

    return outcome, log


async def _nothing() -> bytes:
    return b""


def _remove_jobdir(jobdir: Path) -> None:
    """Drop the persisted frontier. Only ever called on a finished job."""
    try:
        shutil.rmtree(jobdir, ignore_errors=True)
    except OSError as exc:  # pragma: no cover - best effort
        logger.warning("Could not remove %s: %s", jobdir, exc)


def _configure_logging() -> None:
    """Make this module's logs visible.

    ARQ installs a handler for its own logger only, so without this the
    worker's own lines — which crawl started, where a resume picked up, why a
    pause was not graceful — go nowhere.
    """
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    # Only "worker" carries the handler; "worker.control" is a child and
    # propagates into it, so attaching one there too would log every line twice.
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


async def startup(ctx: dict[str, Any]) -> None:
    _configure_logging()
    ctx["job_store"] = JobStore(ctx["redis"])
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)


class WorkerSettings:
    functions = [run_crawl]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = get_settings().job_timeout_seconds
    max_jobs = 2
    keep_result = 3600
    max_tries = 1  # a failed crawl is recorded, not retried
