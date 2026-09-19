"""Read-only MongoDB access for the API.

The Scrapy process writes (see crawler/mongo_store.py); the API only reads, so
this exposes lookups and nothing else. pymongo is blocking, so callers run these
in a threadpool rather than on the event loop.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.config import get_settings

logger = logging.getLogger(__name__)

SITES = "sites"
PAGES = "pages"
JOBS = "jobs"


class MongoReader:
    def __init__(self, url: str, database: str, *, enabled: bool = True) -> None:
        self.available = False
        self._client: MongoClient[dict[str, Any]] | None = None
        if not enabled:
            logger.info("Mongo disabled by configuration")
            return
        try:
            self._client = MongoClient(
                url, serverSelectionTimeoutMS=3000, appname="mt-scrapy-crawl-api"
            )
            self._client.admin.command("ping")
            self._db = self._client[database]
            self.available = True
        except PyMongoError as exc:
            logger.error("Mongo unavailable for the API: %s", exc)

    def find_site(self, domain: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            document = self._db[SITES].find_one({"_id": domain})
        except PyMongoError as exc:
            logger.error("Mongo find_site failed: %s", exc)
            return None
        if document is None:
            return None
        document["domain"] = document.pop("_id")
        return document

    def find_sites(self, domains: list[str]) -> dict[str, dict[str, Any]]:
        """Profile headline fields for several sites in one round trip."""
        return self._find_many(
            SITES, domains, {"name": 1, "description": 1}, "find_sites"
        )

    def find_jobs(self, job_ids: list[str]) -> dict[str, dict[str, Any]]:
        """The request parameters and timestamps recorded for several jobs."""
        return self._find_many(
            JOBS,
            job_ids,
            {"start_url": 1, "max_pages": 1, "use_js": 1, "started_at": 1, "finished_at": 1},
            "find_jobs",
        )

    def _find_many(
        self, collection: str, ids: list[str], projection: dict[str, int], label: str
    ) -> dict[str, dict[str, Any]]:
        if not self.available or not ids:
            return {}
        try:
            cursor = self._db[collection].find({"_id": {"$in": ids}}, projection)
            return {document["_id"]: document for document in cursor}
        except PyMongoError as exc:
            logger.error("Mongo %s failed: %s", label, exc)
            return {}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self.available = False


@lru_cache
def get_mongo() -> MongoReader:
    settings = get_settings()
    return MongoReader(
        settings.mongo_url, settings.mongo_db, enabled=settings.mongo_enabled
    )
