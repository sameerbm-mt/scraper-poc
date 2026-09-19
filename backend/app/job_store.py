"""Redis-backed job records.

Jobs live in a single hash per job. The API and the ARQ worker talk to it through
``JobStore`` (async); the Scrapy pipelines run in a separate process and use the
key/field helpers below with a synchronous Redis client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

from redis.asyncio import Redis

from app.config import get_settings
from app.schemas import JobState, JobStatus
from app.urls import site_slug

KEY_PREFIX: Final = "crawl:job:"

# Hash field names, shared with crawler/pipelines.py so there is one source of truth.
F_STATUS: Final = "status"
F_URL: Final = "url"
F_MAX_PAGES: Final = "max_pages"
F_USE_JS: Final = "use_js"
F_PAGES_CRAWLED: Final = "pages_crawled"
F_PAGES_FAILED: Final = "pages_failed"
F_CREATED_AT: Final = "created_at"
F_STARTED_AT: Final = "started_at"
F_FINISHED_AT: Final = "finished_at"
F_ERROR: Final = "error"
F_SITE: Final = "site"


def job_key(job_id: str) -> str:
    return f"{KEY_PREFIX}{job_id}"


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
    ) -> None:
        key = job_key(job_id)
        await self._redis.hset(  # type: ignore[misc]
            key,
            mapping={
                F_STATUS: JobStatus.queued.value,
                F_URL: url,
                F_SITE: site_slug(url),
                F_MAX_PAGES: str(max_pages),
                F_USE_JS: "1" if use_js else "0",
                F_PAGES_CRAWLED: "0",
                F_PAGES_FAILED: "0",
                F_CREATED_AT: utcnow_iso(),
            },
        )
        await self._redis.expire(key, self._ttl)

    async def exists(self, job_id: str) -> bool:
        return bool(await self._redis.exists(job_key(job_id)))

    async def mark_running(self, job_id: str) -> None:
        await self._redis.hset(  # type: ignore[misc]
            job_key(job_id),
            mapping={F_STATUS: JobStatus.running.value, F_STARTED_AT: utcnow_iso()},
        )

    async def mark_completed(self, job_id: str) -> None:
        await self._redis.hset(  # type: ignore[misc]
            job_key(job_id),
            mapping={F_STATUS: JobStatus.completed.value, F_FINISHED_AT: utcnow_iso()},
        )

    async def mark_failed(self, job_id: str, error: str) -> None:
        await self._redis.hset(  # type: ignore[misc]
            job_key(job_id),
            mapping={
                F_STATUS: JobStatus.failed.value,
                F_FINISHED_AT: utcnow_iso(),
                # Keep the tail bounded so one runaway traceback can't bloat Redis.
                F_ERROR: error[-4000:],
            },
        )

    async def get(self, job_id: str) -> JobState | None:
        raw = await self._redis.hgetall(job_key(job_id))  # type: ignore[misc]
        if not raw:
            return None
        return _to_state(job_id, {_s(k): _s(v) for k, v in raw.items()})


def _s(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _to_state(job_id: str, raw: dict[str, str]) -> JobState:
    return JobState(
        job_id=job_id,
        status=JobStatus(raw.get(F_STATUS, JobStatus.queued.value)),
        url=raw.get(F_URL, ""),
        site=raw.get(F_SITE, "") or site_slug(raw.get(F_URL, "")),
        max_pages=int(raw.get(F_MAX_PAGES, 0)),
        use_js=raw.get(F_USE_JS) == "1",
        pages_crawled=int(raw.get(F_PAGES_CRAWLED, 0)),
        pages_failed=int(raw.get(F_PAGES_FAILED, 0)),
        created_at=_dt(raw.get(F_CREATED_AT)),
        started_at=_dt(raw.get(F_STARTED_AT)),
        finished_at=_dt(raw.get(F_FINISHED_AT)),
        error=raw.get(F_ERROR) or None,
    )


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
