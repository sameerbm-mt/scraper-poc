"""Application configuration, loaded from the environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.urls import site_slug

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration. Every value can be overridden via the environment."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://localhost:6379/0"

    # MongoDB holds the structured crawl output: pages, sites, jobs.
    mongo_url: str = "mongodb://192.168.0.102:27017/"
    mongo_db: str = "mt-scrapy-crawl"
    mongo_enabled: bool = True

    # Where each job writes its pages.jsonl.
    data_dir: Path = BACKEND_ROOT / "data"

    # Origins allowed to call this API (the Next.js dev server by default).
    cors_origins: list[str] = ["http://localhost:3000"]

    # Crawls follow every internal link to the end of the site. max_pages is an
    # optional cap the caller can set; 0 means "the whole site".
    default_max_pages: int = 0
    # Absolute ceiling, enforced even when max_pages is 0, so a crawl trap
    # (faceted search, an endless calendar) cannot run forever. Raise it for a
    # genuinely larger site.
    crawl_page_ceiling: int = 10_000
    # Tag/category/author/pagination listings are followed for discovery but
    # not stored. Set true to keep them.
    store_archive_pages: bool = False

    # How long a paused crawl gets to shut down cleanly before it is killed.
    # This matters more than it looks: Scrapy only writes the queue count into
    # JOBDIR while closing, so a crawl that overruns its grace loses the
    # frontier and the "resume" silently becomes a restart.
    pause_grace_seconds: float = 30.0
    # Render JS needs far longer. Playwright closes every browser context before
    # Scrapy can finish, which on a real crawl does not fit in 30s.
    pause_grace_seconds_js: float = 180.0

    # ARQ / Scrapy. A whole-site crawl takes far longer than a capped one.
    job_timeout_seconds: int = 3600
    job_ttl_seconds: int = 60 * 60 * 24 * 7
    scrapy_log_level: str = "INFO"
    # Scrapy's local HTTP cache speeds up repeat crawls; keep it off outside dev.
    httpcache_enabled: bool = False

    user_agent: str = (
        "MyraCrawlPOC/0.1 (+https://github.com/myra/scraper-poc; "
        "website ingestion proof of concept)"
    )

    def job_data_dir(self, site: str, job_id: str) -> Path:
        """data/{site}/{job_id} — one folder per website, then per job."""
        return self.data_dir / site / job_id

    def job_results_path(self, site: str, job_id: str) -> Path:
        return self.job_data_dir(site, job_id) / "pages.jsonl"

    def job_csv_path(self, site: str, job_id: str) -> Path:
        return self.job_data_dir(site, job_id) / "pages.csv"

    def job_jobdir_path(self, site: str, job_id: str) -> Path:
        """Scrapy's JOBDIR: the persisted request queue that makes resume exact.

        Scrapy writes its pending requests and seen-URL set here on a graceful
        shutdown, and reads them back when the same spider is relaunched with
        the same directory.
        """
        return self.job_data_dir(site, job_id) / "jobdir"

    def job_files_dir(self, site: str, job_id: str) -> Path:
        """FILES_STORE for this job's downloaded documents."""
        return self.job_data_dir(site, job_id) / "files"

    def job_documents_path(self, site: str, job_id: str) -> Path:
        return self.job_data_dir(site, job_id) / "documents.jsonl"

    def job_paths_for_url(self, url: str, job_id: str) -> tuple[Path, Path]:
        """(jsonl, csv) for a job, with the site folder derived from its URL."""
        site = site_slug(url)
        return self.job_results_path(site, job_id), self.job_csv_path(site, job_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
