"""Synchronous Redis counters for the Scrapy process.

Scrapy runs in its own process (and on the Twisted reactor), so it uses the
blocking Redis client rather than the async ``JobStore``. The writes are single
INCRs against a local Redis; if Redis is unreachable the crawl still completes,
it just stops reporting progress.
"""

from __future__ import annotations

import logging

import redis

from app.config import get_settings
from app.job_store import F_PAGES_CRAWLED, F_PAGES_FAILED, job_key

logger = logging.getLogger(__name__)


class JobProgress:
    def __init__(self, job_id: str) -> None:
        self._key = job_key(job_id)
        self._client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2
        )

    def incr_crawled(self, amount: int = 1) -> None:
        self._incr(F_PAGES_CRAWLED, amount)

    def incr_failed(self, amount: int = 1) -> None:
        self._incr(F_PAGES_FAILED, amount)

    def _incr(self, field: str, amount: int) -> None:
        try:
            self._client.hincrby(self._key, field, amount)
        except redis.RedisError as exc:  # pragma: no cover - progress is best-effort
            logger.warning("Could not update %s for %s: %s", field, self._key, exc)

    def close(self) -> None:
        try:
            self._client.close()
        except redis.RedisError:  # pragma: no cover
            pass
