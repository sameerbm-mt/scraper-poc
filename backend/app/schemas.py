"""Pydantic v2 request/response models shared by the API and the smoke test."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings

_settings = get_settings()


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class CrawlRequest(BaseModel):
    """Body of POST /api/crawl."""

    url: str
    # 0 crawls the entire site; any positive value caps it.
    max_pages: Annotated[int, Field(ge=0, le=_settings.crawl_page_ceiling)] = (
        _settings.default_max_pages
    )
    use_js: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("URL is required")
        # Be forgiving about a missing scheme; the UI lets people type "example.com".
        if "://" not in value:
            value = f"https://{value}"
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https")
        if not parsed.netloc:
            raise ValueError("URL must include a host, e.g. https://example.com")
        return value


class CrawlResponse(BaseModel):
    job_id: str


class JobState(BaseModel):
    """Body of GET /api/jobs/{job_id}."""

    job_id: str
    status: JobStatus
    url: str
    site: str = ""
    max_pages: int
    use_js: bool
    pages_crawled: int = 0
    pages_failed: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class PageSummary(BaseModel):
    """A crawled page without its markdown body (list view)."""

    index: int
    url: str
    status_code: int | None = None
    depth: int = 0
    title: str = ""
    word_count: int = 0
    content_hash: str = ""
    crawled_at: str = ""


class PageDetail(PageSummary):
    """A crawled page including its markdown body (detail view)."""

    meta_description: str = ""
    h1: str = ""
    markdown: str = ""


class ResultsPage(BaseModel):
    """Body of GET /api/jobs/{job_id}/results."""

    items: list[PageSummary]
    page: int
    size: int
    total: int
    total_pages: int


class SocialLink(BaseModel):
    network: str
    url: str


class Service(BaseModel):
    name: str
    url: str


class TeamMember(BaseModel):
    name: str
    role: str = ""
    image: str = ""
    source: str = ""


class SiteProfile(BaseModel):
    """The `sites` document: everything the crawl learned about one website."""

    domain: str
    name: str = ""
    start_url: str = ""
    description: str = ""
    logo: str = ""
    favicon: str = ""
    lang: str = ""
    address: str = ""
    founding_date: str = ""
    emails: list[str] = []
    phones: list[str] = []
    socials: list[SocialLink] = []
    services: list[Service] = []
    services_count: int = 0
    team: list[TeamMember] = []
    team_count: int = 0
    key_pages: dict[str, str] = {}
    page_count: int = 0
    total_words: int = 0
    pages_by_type: dict[str, int] = {}
    first_seen_at: datetime | None = None
    last_crawled_at: datetime | None = None
