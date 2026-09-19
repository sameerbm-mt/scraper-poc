"""MongoDB writes for the Scrapy process.

Three collections in `mt-scrapy-crawl`:

  pages  one document per crawled page per job
  sites  one document per website, rebuilt from the site facts of each crawl
  jobs   one document per crawl run, with its parameters and final counts

Scrapy runs synchronously on the Twisted reactor, so this uses the blocking
driver. Mongo being unreachable degrades the crawl to file-only output rather
than failing it — the JSONL and CSV are still written.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient, UpdateOne
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

PAGES = "pages"
SITES = "sites"
JOBS = "jobs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MongoStore:
    """Thin wrapper that never lets a Mongo failure break a crawl."""

    def __init__(self, url: str, database: str, *, timeout_ms: int = 5000) -> None:
        self.available = False
        self._client: MongoClient[dict[str, Any]] | None = None
        try:
            self._client = MongoClient(
                url,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                appname="mt-scrapy-crawl",
            )
            self._client.admin.command("ping")
            self._db = self._client[database]
            self._ensure_indexes()
            self.available = True
            logger.info("Mongo connected: %s/%s", url, database)
        except PyMongoError as exc:
            logger.error("Mongo unavailable (%s) — writing files only", exc)

    def _ensure_indexes(self) -> None:
        self._db[PAGES].create_index(
            [("job_id", ASCENDING), ("url", ASCENDING)], unique=True, name="job_url"
        )
        self._db[PAGES].create_index([("site", ASCENDING)], name="site")
        self._db[PAGES].create_index([("content_hash", ASCENDING)], name="content_hash")
        self._db[PAGES].create_index([("page_type", ASCENDING)], name="page_type")
        self._db[JOBS].create_index([("site", ASCENDING)], name="site")

    # -- writes ------------------------------------------------------------

    def start_job(self, job_id: str, site: str, params: dict[str, Any]) -> None:
        self._safe(
            lambda: self._db[JOBS].update_one(
                {"_id": job_id},
                {
                    "$set": {"site": site, "status": "running", "started_at": _now(), **params},
                    "$setOnInsert": {"created_at": _now()},
                },
                upsert=True,
            ),
            "start_job",
        )

    def finish_job(self, job_id: str, status: str, stats: dict[str, Any]) -> None:
        self._safe(
            lambda: self._db[JOBS].update_one(
                {"_id": job_id},
                {"$set": {"status": status, "finished_at": _now(), **stats}},
            ),
            "finish_job",
        )

    def upsert_pages(self, documents: list[dict[str, Any]]) -> int:
        """Upsert a batch of pages, keyed on (job_id, url)."""
        if not documents:
            return 0
        operations = [
            UpdateOne(
                {"job_id": doc["job_id"], "url": doc["url"]},
                {"$set": doc, "$setOnInsert": {"first_seen_at": _now()}},
                upsert=True,
            )
            for doc in documents
        ]
        result = self._safe(
            lambda: self._db[PAGES].bulk_write(operations, ordered=False), "upsert_pages"
        )
        return (result.upserted_count + result.modified_count) if result else 0

    def upsert_site(self, site: str, profile: dict[str, Any]) -> None:
        self._safe(
            lambda: self._db[SITES].update_one(
                {"_id": site},
                {
                    "$set": {**profile, "domain": site, "last_crawled_at": _now()},
                    "$setOnInsert": {"first_seen_at": _now()},
                },
                upsert=True,
            ),
            "upsert_site",
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self.available = False

    def _safe(self, operation, label: str):  # type: ignore[no-untyped-def]
        if not self.available:
            return None
        try:
            return operation()
        except PyMongoError as exc:
            logger.error("Mongo %s failed: %s", label, exc)
            return None
