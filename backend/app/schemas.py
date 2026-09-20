"""Pydantic v2 request/response models shared by the API and the smoke test."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings

_settings = get_settings()


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    # `pausing`/`resuming` are the in-between states: the API has accepted the
    # request and the worker has not finished acting on it yet.
    pausing = "pausing"
    paused = "paused"
    resuming = "resuming"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# A job in one of these is finished: nothing more will happen to it, and the UI
# stops polling.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}
)


class CrawlRequest(BaseModel):
    """Body of POST /api/crawl."""

    url: str
    # 0 crawls the entire site; any positive value caps it.
    max_pages: Annotated[int, Field(ge=0, le=_settings.crawl_page_ceiling)] = (
        _settings.default_max_pages
    )
    use_js: bool = False
    # Seed the frontier from the site's own sitemap instead of following links.
    use_sitemap: bool = False
    # Download linked pdf/docx/xlsx/pptx and extract their text.
    download_files: bool = False
    # Collect emails, phones, socials and postal addresses. Off by default:
    # this is personal data (see the GDPR/DPDP note in the README).
    extract_contacts: bool = False

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
    use_sitemap: bool = False
    download_files: bool = False
    extract_contacts: bool = False
    pages_crawled: int = 0
    pages_failed: int = 0
    documents_downloaded: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    # -- pause / resume
    # OS pid of the Scrapy subprocess, so the worker can signal it.
    pid: int | None = None
    paused_at: datetime | None = None
    resumed_at: datetime | None = None
    resume_count: int = 0
    # Scrapy's JOBDIR: the persisted request queue that makes resume exact.
    jobdir_path: str = ""


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


class Heading(BaseModel):
    level: int
    text: str


class PageDetail(PageSummary):
    """A crawled page including its markdown body (detail view)."""

    meta_description: str = ""
    h1: str = ""
    markdown: str = ""

    # -- content structure
    headings: list[Heading] = []
    lang: str = ""

    # -- SEO / meta
    meta_robots: str = ""
    canonical_url: str = ""
    og: dict[str, str] = {}
    twitter: dict[str, str] = {}
    hreflang: list[dict[str, str]] = []

    # -- structured data
    jsonld: list[dict[str, Any]] = []
    schema_types: list[str] = []
    faqs: list[dict[str, str]] = []
    products: list[dict[str, str]] = []

    # -- links & media
    internal_links_count: int = 0
    external_links: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    document_links: list[dict[str, str]] = []

    # -- contacts (empty unless the job set extract_contacts)
    emails: list[str] = []
    phones: list[str] = []
    social_links: list[dict[str, str]] = []
    addresses: list[str] = []

    # -- technical
    redirect_chain: list[str] = []
    response_time_ms: int = 0
    content_type: str = ""
    page_size_bytes: int = 0
    page_type: str = ""


class DocumentRecord(BaseModel):
    """One row of documents.jsonl: a downloaded file and its extracted text."""

    source_url: str
    filename: str
    page_count: int = 0
    markdown: str = ""
    content_hash: str = ""
    size_bytes: int = 0
    ext: str = ""


class JobStats(BaseModel):
    """Body of GET /api/jobs/{job_id}/stats — the numbers the UI card shows."""

    pages_crawled: int = 0
    pages_failed: int = 0
    documents_downloaded: int = 0
    schema_types: dict[str, int] = {}
    avg_response_time_ms: int = 0
    total_words: int = 0
    faqs_found: int = 0
    products_found: int = 0


class ResultsPage(BaseModel):
    """Body of GET /api/jobs/{job_id}/results."""

    items: list[PageSummary]
    page: int
    size: int
    total: int
    total_pages: int


class SiteSummary(BaseModel):
    """One row of GET /api/sites: a crawled website and its most recent crawl."""

    domain: str
    # From the Mongo site profile when there is one; empty otherwise.
    name: str = ""
    job_count: int
    latest_job_id: str
    latest_status: JobStatus
    pages: int = 0
    last_crawled_at: datetime | None = None


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
