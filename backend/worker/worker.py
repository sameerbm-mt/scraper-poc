"""ARQ worker: runs each crawl as a Scrapy subprocess.

Scrapy is *not* run in-process. The Twisted reactor cannot be restarted, so a
second job in the same worker would fail; a subprocess also keeps a crashing
crawl from taking the worker down with it.

Run with::

    uv run arq worker.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.job_store import JobStore  # noqa: E402
from app.urls import site_slug  # noqa: E402

logger = logging.getLogger("worker")

# How much of Scrapy's stderr to keep when a crawl fails.
STDERR_TAIL_CHARS = 4000


async def run_crawl(
    ctx: dict[str, Any],
    job_id: str,
    url: str,
    max_pages: int,
    use_js: bool,
) -> dict[str, Any]:
    settings = get_settings()
    store: JobStore = ctx["job_store"]

    await store.mark_running(job_id)
    settings.job_data_dir(site_slug(url), job_id).mkdir(parents=True, exist_ok=True)

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
        # Settings are frozen before the spider is built, so this has to arrive
        # as a settings override rather than a spider argument. There is no
        # DEPTH_LIMIT: the crawl follows internal links to the end of the site.
        "-s", f"CLOSESPIDER_PAGECOUNT={page_cap}",
    ]
    logger.info("job %s: %s", job_id, " ".join(command))

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(BACKEND_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        returncode = process.returncode
    except asyncio.CancelledError:
        await store.mark_failed(job_id, "Crawl cancelled or timed out")
        raise
    except OSError as exc:
        await store.mark_failed(job_id, f"Could not start Scrapy: {exc}")
        raise

    log_tail = stderr.decode("utf-8", errors="replace")[-STDERR_TAIL_CHARS:]

    if returncode != 0:
        logger.error("job %s: scrapy exited %s", job_id, returncode)
        await store.mark_failed(job_id, f"scrapy exited with {returncode}\n{log_tail}")
        return {"job_id": job_id, "returncode": returncode}

    state = await store.get(job_id)
    pages = state.pages_crawled if state else 0
    if pages == 0:
        # Exit code 0 with nothing stored means the site blocked us, robots.txt
        # disallowed the start URL, or every page extracted empty.
        await store.mark_failed(job_id, f"Crawl produced no pages.\n{log_tail}")
        return {"job_id": job_id, "returncode": returncode, "pages_crawled": 0}

    await store.mark_completed(job_id)
    logger.info("job %s: completed with %s pages", job_id, pages)
    return {"job_id": job_id, "returncode": returncode, "pages_crawled": pages}


async def startup(ctx: dict[str, Any]) -> None:
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
