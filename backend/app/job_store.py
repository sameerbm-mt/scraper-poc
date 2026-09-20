"""Redis-backed job records.

Jobs live in a single hash per job. The API and the ARQ worker talk to it through
``JobStore`` (async); the Scrapy pipelines run in a separate process and use the
key/field helpers below with a synchronous Redis client.

Pause/resume adds a second key per job, ``job:{id}:control``. The API writes a
request into it and the worker — which is the only process holding the Scrapy
subprocess handle — reads it and acts. The API never signals the process itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

from redis.asyncio import Redis

from app.config import get_settings
from app.schemas import JobState, JobStatus
from app.urls import site_slug

KEY_PREFIX: Final = "crawl:job:"
CONTROL_PREFIX: Final = "job:"
CONTROL_SUFFIX: Final = ":control"

# Control requests the worker understands.
CONTROL_PAUSE: Final = "pause"
CONTROL_CANCEL: Final = "cancel"

# Hash field names, shared with crawler/pipelines.py so there is one source of truth.
F_STATUS: Final = "status"
F_URL: Final = "url"
F_MAX_PAGES: Final = "max_pages"
F_USE_JS: Final = "use_js"
F_USE_SITEMAP: Final = "use_sitemap"
F_DOWNLOAD_FILES: Final = "download_files"
F_EXTRACT_CONTACTS: Final = "extract_contacts"
F_PAGES_CRAWLED: Final = "pages_crawled"
F_PAGES_FAILED: Final = "pages_failed"
F_DOCUMENTS: Final = "documents_downloaded"
F_CREATED_AT: Final = "created_at"
F_STARTED_AT: Final = "started_at"
F_FINISHED_AT: Final = "finished_at"
F_ERROR: Final = "error"
F_SITE: Final = "site"
F_PID: Final = "pid"
F_PAUSED_AT: Final = "paused_at"
F_RESUMED_AT: Final = "resumed_at"
F_RESUME_COUNT: Final = "resume_count"
F_JOBDIR: Final = "jobdir_path"


def job_key(job_id: str) -> str:
    return f"{KEY_PREFIX}{job_id}"


def control_key(job_id: str) -> str:
    return f"{CONTROL_PREFIX}{job_id}{CONTROL_SUFFIX}"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Async view over the job hashes. Used by the API and the ARQ worker."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._ttl = get_settings().job_ttl_seconds

    async def create(
        self,
        job_id: str,
        *,
        url: str,
        max_pages: int,
        use_js: bool,
        use_sitemap: bool = False,
        download_files: bool = False,
        extract_contacts: bool = False,
    ) -> None:
        key = job_key(job_id)
        await self._redis.hset(  # type: ignore[misc]
            key,
            mapping={
                F_STATUS: JobStatus.queued.value,
                F_URL: url,
                F_SITE: site_slug(url),
                F_MAX_PAGES: str(max_pages),
                F_USE_JS: _flag(use_js),
                F_USE_SITEMAP: _flag(use_sitemap),
                F_DOWNLOAD_FILES: _flag(download_files),
                F_EXTRACT_CONTACTS: _flag(extract_contacts),
                F_PAGES_CRAWLED: "0",
                F_PAGES_FAILED: "0",
                F_DOCUMENTS: "0",
                F_RESUME_COUNT: "0",
                F_CREATED_AT: utcnow_iso(),
            },
        )
        await self._redis.expire(key, self._ttl)

    async def exists(self, job_id: str) -> bool:
        return bool(await self._redis.exists(job_key(job_id)))

    async def _set(self, job_id: str, **fields: str) -> None:
        await self._redis.hset(job_key(job_id), mapping=fields)  # type: ignore[misc]

    async def mark_running(self, job_id: str, jobdir: str = "") -> None:
        fields = {F_STATUS: JobStatus.running.value, F_STARTED_AT: utcnow_iso()}
        if jobdir:
            fields[F_JOBDIR] = jobdir
        await self._set(job_id, **fields)

    async def mark_completed(self, job_id: str) -> None:
        await self._set(
            job_id, **{F_STATUS: JobStatus.completed.value, F_FINISHED_AT: utcnow_iso()}
        )

    async def mark_failed(self, job_id: str, error: str) -> None:
        await self._set(
            job_id,
            **{
                F_STATUS: JobStatus.failed.value,
                F_FINISHED_AT: utcnow_iso(),
                # Bounded so one runaway traceback can't bloat Redis. Keep the
                # start: the worker leads with the cause and puts the log last.
                F_ERROR: error[:4000],
            },
        )

    # -- pause / resume / cancel -------------------------------------------

    async def mark_pausing(self, job_id: str) -> None:
        await self._set(job_id, **{F_STATUS: JobStatus.pausing.value})

    async def mark_paused(self, job_id: str) -> None:
        await self._set(
            job_id, **{F_STATUS: JobStatus.paused.value, F_PAUSED_AT: utcnow_iso()}
        )

    async def mark_resuming(self, job_id: str) -> None:
        """Count the resume up front: the UI badge should show it immediately."""
        await self._redis.hincrby(job_key(job_id), F_RESUME_COUNT, 1)  # type: ignore[misc]
        await self._set(
            job_id,
            **{F_STATUS: JobStatus.resuming.value, F_RESUMED_AT: utcnow_iso()},
        )

    async def mark_cancelled(self, job_id: str) -> None:
        await self._set(
            job_id,
            **{F_STATUS: JobStatus.cancelled.value, F_FINISHED_AT: utcnow_iso()},
        )

    async def set_pid(self, job_id: str, pid: int | None) -> None:
        await self._set(job_id, **{F_PID: str(pid) if pid else ""})

    async def request_control(self, job_id: str, action: str) -> None:
        """Ask the worker to pause or cancel. Expires with the job record."""
        key = control_key(job_id)
        await self._redis.set(key, action, ex=self._ttl)

    async def read_control(self, job_id: str) -> str:
        raw = await self._redis.get(control_key(job_id))
        return _s(raw) if raw else ""

    async def clear_control(self, job_id: str) -> None:
        await self._redis.delete(control_key(job_id))

    async def get(self, job_id: str) -> JobState | None:
        raw = await self._redis.hgetall(job_key(job_id))  # type: ignore[misc]
        if not raw:
            return None
        return _to_state(job_id, {_s(k): _s(v) for k, v in raw.items()})


def _flag(value: bool) -> str:
    return "1" if value else "0"


def _s(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _to_state(job_id: str, raw: dict[str, str]) -> JobState:
    pid = _int(raw.get(F_PID), 0)
    return JobState(
        job_id=job_id,
        status=JobStatus(raw.get(F_STATUS, JobStatus.queued.value)),
        url=raw.get(F_URL, ""),
        site=raw.get(F_SITE, "") or site_slug(raw.get(F_URL, "")),
        max_pages=_int(raw.get(F_MAX_PAGES)),
        use_js=raw.get(F_USE_JS) == "1",
        use_sitemap=raw.get(F_USE_SITEMAP) == "1",
        download_files=raw.get(F_DOWNLOAD_FILES) == "1",
        extract_contacts=raw.get(F_EXTRACT_CONTACTS) == "1",
        pages_crawled=_int(raw.get(F_PAGES_CRAWLED)),
        pages_failed=_int(raw.get(F_PAGES_FAILED)),
        documents_downloaded=_int(raw.get(F_DOCUMENTS)),
        created_at=_dt(raw.get(F_CREATED_AT)),
        started_at=_dt(raw.get(F_STARTED_AT)),
        finished_at=_dt(raw.get(F_FINISHED_AT)),
        error=raw.get(F_ERROR) or None,
        pid=pid or None,
        paused_at=_dt(raw.get(F_PAUSED_AT)),
        resumed_at=_dt(raw.get(F_RESUMED_AT)),
        resume_count=_int(raw.get(F_RESUME_COUNT)),
        jobdir_path=raw.get(F_JOBDIR, ""),
    )


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
