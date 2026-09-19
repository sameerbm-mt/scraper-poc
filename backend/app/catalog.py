"""A read-only view of what has been crawled, built from ``backend/data``.

The job folders on disk are the source of truth for *which* crawls exist. Redis
job records expire after ``job_ttl_seconds`` and Mongo is optional, but the files
stay, so the sites list and the results of an old crawl are served from here.

Layout: ``data/{site}/{job_id}/pages.jsonl`` (+ ``pages.csv``). Counts and
timestamps come from the CSV — it has no markdown column, so it is cheap to scan
— and fall back to the JSONL when the CSV is missing.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from app.schemas import JobState, JobStatus

# Site folders are `site_slug()` output and job folders are uuid4 hex. Anything
# else is rejected before it can be joined onto the data directory.
_SITE_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*")
_JOB_ID_RE = re.compile(r"[0-9a-f]{32}")

RESULTS_FILE = "pages.jsonl"
CSV_FILE = "pages.csv"


def is_valid_site(site: str) -> bool:
    return _SITE_RE.fullmatch(site) is not None


def is_valid_job_id(job_id: str) -> bool:
    return _JOB_ID_RE.fullmatch(job_id) is not None


@dataclass(frozen=True)
class CrawlFiles:
    site: str
    job_id: str
    jsonl: Path
    csv: Path


@dataclass(frozen=True)
class CrawlStats:
    pages: int
    start_url: str
    first_at: datetime | None
    last_at: datetime | None


@dataclass(frozen=True)
class Crawl:
    files: CrawlFiles
    stats: CrawlStats
    # When the crawl last stored a page; orders crawls newest first.
    activity: datetime


def scan(data_dir: Path) -> dict[str, list[Crawl]]:
    """Every site that has at least one crawl, each with its crawls newest first."""
    sites: dict[str, list[Crawl]] = {}
    if not data_dir.is_dir():
        return sites
    for site_dir in data_dir.iterdir():
        if site_dir.is_dir() and is_valid_site(site_dir.name):
            crawls = _crawls_in(site_dir)
            if crawls:
                sites[site_dir.name] = crawls
    return sites


def scan_site(data_dir: Path, site: str) -> list[Crawl]:
    """The crawls of one site, newest first. Empty for an unknown or unsafe name."""
    if not is_valid_site(site):
        return []
    site_dir = data_dir / site
    return _crawls_in(site_dir) if site_dir.is_dir() else []


def find(data_dir: Path, job_id: str) -> Crawl | None:
    """Locate a crawl by job id without knowing its site."""
    if not is_valid_job_id(job_id) or not data_dir.is_dir():
        return None
    for site_dir in data_dir.iterdir():
        if not (site_dir.is_dir() and is_valid_site(site_dir.name)):
            continue
        crawl = _load(site_dir, site_dir / job_id)
        if crawl is not None:
            return crawl
    return None


def state_from_disk(crawl: Crawl, recorded: dict[str, Any] | None = None) -> JobState:
    """A JobState for a crawl whose Redis record is gone.

    ``recorded`` is the Mongo ``jobs`` document when there is one; it supplies the
    request parameters (URL, page cap, JS) that the files do not carry. Two things
    cannot be recovered: how many requests failed, and whether a crawl that stored
    pages was interrupted — it is reported as completed.
    """
    recorded = recorded or {}
    stats = crawl.stats
    started = _coerce_dt(recorded.get("started_at")) or stats.first_at
    finished = _coerce_dt(recorded.get("finished_at")) or stats.last_at
    return JobState(
        job_id=crawl.files.job_id,
        status=JobStatus.completed if stats.pages else JobStatus.failed,
        url=str(recorded.get("start_url") or stats.start_url),
        site=crawl.files.site,
        max_pages=int(recorded.get("max_pages") or 0),
        use_js=bool(recorded.get("use_js", False)),
        pages_crawled=stats.pages,
        pages_failed=0,
        created_at=started,
        started_at=started,
        finished_at=finished,
        error=None if stats.pages else "No pages were stored for this crawl.",
    )


def _crawls_in(site_dir: Path) -> list[Crawl]:
    crawls = [
        crawl
        for job_dir in site_dir.iterdir()
        if (crawl := _load(site_dir, job_dir)) is not None
    ]
    crawls.sort(key=lambda crawl: crawl.activity, reverse=True)
    return crawls


def _load(site_dir: Path, job_dir: Path) -> Crawl | None:
    jsonl = job_dir / RESULTS_FILE
    try:
        if not (is_valid_job_id(job_dir.name) and jsonl.is_file()):
            return None
        files = CrawlFiles(site_dir.name, job_dir.name, jsonl, job_dir / CSV_FILE)
        stats = crawl_stats(files)
        activity = stats.last_at or datetime.fromtimestamp(
            jsonl.stat().st_mtime, timezone.utc
        )
    except OSError:  # deleted while we were looking
        return None
    return Crawl(files, stats, activity)


def crawl_stats(files: CrawlFiles) -> CrawlStats:
    source = files.csv if files.csv.is_file() else files.jsonl
    info = source.stat()
    return _read_stats(str(source), info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=1024)
def _read_stats(path: str, mtime_ns: int, size: int) -> CrawlStats:
    # mtime_ns and size are not read: they key the cache, so a file that is still
    # being written (a running crawl) is re-scanned and a finished one is not.
    pages = 0
    start_url = ""
    first: datetime | None = None
    last: datetime | None = None
    for row in _rows(Path(path)):
        pages += 1
        start_url = start_url or str(row.get("url") or "")
        when = _coerce_dt(row.get("crawled_at"))
        if when is not None:
            first = when if first is None or when < first else first
            last = when if last is None or when > last else last
    return CrawlStats(pages=pages, start_url=start_url, first_at=first, last_at=last)


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        if path.suffix == ".csv":
            yield from csv.DictReader(handle)
            return
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:  # a partially written last line
                continue
            if isinstance(record, dict):
                yield record


def _coerce_dt(value: Any) -> datetime | None:
    """A timezone-aware datetime from an ISO string or a Mongo (naive UTC) datetime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
