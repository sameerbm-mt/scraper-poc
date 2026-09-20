"""Item pipelines: extract -> dedupe -> write -> report progress."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, TextIO

from scrapy import Spider
from scrapy.exceptions import DropItem

from app.config import get_settings
from crawler.content import extract_content
from crawler.items import CSV_COLUMNS, PageItem
from crawler.seo import detect_language
from crawler.mongo_store import MongoStore
from crawler.progress import JobProgress
from crawler.site_profile import SiteProfileBuilder

logger = logging.getLogger(__name__)

# A strategy clearing this is treated as having found real content, so the
# extractor stops descending the fallback ladder.
GOOD_CONTENT_CHARS = 200
# Below this a "page" is a nav shell or a redirect stub, not content worth keeping.
MIN_MARKDOWN_CHARS = 80


_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
# Only the oversized indents HTML-to-text leaves behind; up to 4 spaces is kept
# so nested markdown lists survive.
_OVER_INDENT = re.compile(r"^[ \t]{5,}", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def normalise_markdown(text: str) -> str:
    """Strip the ragged indentation HTML-to-text extraction leaves behind.

    Hashing happens after this, so two pages that differ only in whitespace
    dedupe against each other.
    """
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = _TRAILING_WS.sub("", text)
    text = _OVER_INDENT.sub("", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip()


class ExtractPipeline:
    """Turn raw HTML into markdown; drop pages with no content.

    Extraction walks a fallback ladder (see crawler/content.py) because
    Trafilatura's algorithm returns nothing at all on some templates, even when
    the article is plainly in the HTML.
    """

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        text, strategy = extract_content(item.html, item.url, GOOD_CONTENT_CHARS)
        markdown = normalise_markdown(text)

        if len(markdown) < MIN_MARKDOWN_CHARS:
            raise DropItem(f"No extractable content: {item.url}")

        item.markdown = markdown
        item.word_count = len(markdown.split())
        item.content_hash = content_hash(markdown)
        item.extracted_by = strategy
        # Detection needs the extracted prose, which only exists here. The
        # page's own <html lang> wins when it has one.
        item.lang = detect_language(markdown, item.lang)
        item.html = ""  # free the raw HTML as soon as we are done with it
        return item


class ArchivePipeline:
    """Drop taxonomy and pagination listings.

    Their links are still followed — the spider has already queued them by the
    time an item reaches here — but a tag or /page/2/ listing is not a page of
    the website, and storing them buries the real content.
    """

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if item.page_type == "archive" and not get_settings().store_archive_pages:
            raise DropItem(f"Archive listing: {item.url}")
        return item


class DedupePipeline:
    """Drop pages whose markdown we have already stored in this job.

    On a resumed crawl the in-memory set starts empty but pages.jsonl does not,
    so the hashes already on disk are loaded first. Without this, resuming would
    re-emit every page the earlier run had queued but not yet finished, and the
    file would end up with duplicate URLs.
    """

    def __init__(self) -> None:
        self._hashes: set[str] = set()

    def open_spider(self, spider: Spider) -> None:
        path = get_settings().job_results_path(_site_of(spider), _job_of(spider))
        self._hashes = _hashes_on_disk(path)
        if self._hashes:
            logger.info(
                "Resuming: %s content hashes already in %s", len(self._hashes), path.name
            )

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if item.content_hash in self._hashes:
            raise DropItem(f"Duplicate content: {item.url}")
        self._hashes.add(item.content_hash)
        return item


def _count_records(path: Path) -> int:
    """Non-empty lines in pages.jsonl — how many pages a previous run stored."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _hashes_on_disk(path: Path) -> set[str]:
    """Content hashes already recorded in pages.jsonl, for a resumed crawl."""
    if not path.exists():
        return set()
    hashes: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A run killed mid-write leaves one ragged line; skip it.
                continue
            digest = record.get("content_hash")
            if digest:
                hashes.add(str(digest))
    return hashes


class JsonLinesPipeline:
    """Append each page to data/{job_id}/pages.jsonl, capped at max_pages.

    CLOSESPIDER_PAGECOUNT only stops the scheduler; requests already in flight
    still come back and would push the job past the cap the caller asked for.
    Enforcing it here is what makes max_pages a hard limit on stored pages.
    """

    def __init__(self) -> None:
        self._handle: TextIO | None = None
        self._written = 0
        self._max_pages = 0
        self.path: Path | None = None

    def open_spider(self, spider: Spider) -> None:
        job_id = getattr(spider, "job_id", None)
        if not job_id:
            raise ValueError("Spider must define job_id for JsonLinesPipeline")
        settings = get_settings()
        self._max_pages = int(getattr(spider, "max_pages", 0) or 0)
        self.path = settings.job_results_path(_site_of(spider), job_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Rows already on disk count towards the cap: a resumed crawl continues
        # towards max_pages rather than being granted a fresh allowance.
        self._written = _count_records(self.path)
        self._handle = self.path.open("a", encoding="utf-8")
        logger.info(
            "Writing results to %s (max_pages=%s, %s already written)",
            self.path,
            self._max_pages,
            self._written,
        )

    def close_spider(self, spider: Spider) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if self._handle is None:
            raise RuntimeError("JsonLinesPipeline used before open_spider")
        if self._max_pages and self._written >= self._max_pages:
            raise DropItem(f"max_pages={self._max_pages} reached: {item.url}")
        record: dict[str, Any] = item.to_record()
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Flush per item so the API can serve partial results while the job runs.
        self._handle.flush()
        self._written += 1
        return item


class ProgressPipeline:
    """Report pages_crawled back to Redis so the UI can show live progress."""

    def __init__(self) -> None:
        self._progress: JobProgress | None = None

    def open_spider(self, spider: Spider) -> None:
        job_id = getattr(spider, "job_id", None)
        if not job_id:
            raise ValueError("Spider must define job_id for ProgressPipeline")
        # Reuse the spider's client when there is one (the errback shares it).
        self._progress = getattr(spider, "progress", None) or JobProgress(job_id)

    def close_spider(self, spider: Spider) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if self._progress is not None:
            self._progress.incr_crawled()
        return item


def _site_of(spider: Spider) -> str:
    """The site folder for this crawl, set by the spider from its start URL."""
    site = getattr(spider, "site", "")
    if not site:
        raise ValueError("Spider must define site (see SiteSpider.__init__)")
    return site


def _job_of(spider: Spider) -> str:
    job_id = getattr(spider, "job_id", None)
    if not job_id:
        raise ValueError("Spider must define job_id")
    return str(job_id)


class CsvPipeline:
    """Write a flat pages.csv alongside pages.jsonl.

    Same rows as the JSONL, minus markdown — see CSV_COLUMNS for why.
    """

    def __init__(self) -> None:
        self._handle: TextIO | None = None
        self._writer: csv.DictWriter[str] | None = None
        self.path: Path | None = None

    def open_spider(self, spider: Spider) -> None:
        self.path = get_settings().job_csv_path(_site_of(spider), _job_of(spider))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self._handle = self.path.open("a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._handle, fieldnames=list(CSV_COLUMNS), extrasaction="ignore"
        )
        if is_new:
            self._writer.writeheader()
            self._handle.flush()
        logger.info("Writing CSV to %s", self.path)

    def close_spider(self, spider: Spider) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
            self._writer = None

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if self._writer is None or self._handle is None:
            raise RuntimeError("CsvPipeline used before open_spider")
        row = item.to_csv_row()
        # Newlines inside a cell are legal CSV but wreck naive readers.
        self._writer.writerow(
            {k: (" ".join(str(v).split()) if isinstance(v, str) else v) for k, v in row.items()}
        )
        self._handle.flush()
        return item


class MongoPipeline:
    """Persist every page to Mongo as it is scraped, then the site profile.

    Writes `pages` per item, and `jobs` + `sites` on open/close. A Mongo outage
    is logged and skipped: the file outputs are the source of truth.
    """

    def __init__(self) -> None:
        self._store: MongoStore | None = None
        self._profile: SiteProfileBuilder | None = None
        self._job_id = ""
        self._site = ""
        self._stored = 0

    def open_spider(self, spider: Spider) -> None:
        settings = get_settings()
        if not settings.mongo_enabled:
            logger.info("Mongo disabled by configuration")
            return

        self._job_id = _job_of(spider)
        self._site = _site_of(spider)
        self._store = MongoStore(settings.mongo_url, settings.mongo_db)
        self._profile = SiteProfileBuilder(
            self._site, str(getattr(spider, "start_url", ""))
        )
        if self._store.available:
            self._store.start_job(
                self._job_id,
                self._site,
                {
                    "start_url": getattr(spider, "start_url", ""),
                    "max_pages": getattr(spider, "max_pages", 0),
                    "use_js": getattr(spider, "use_js", False),
                },
            )

    def process_item(self, item: PageItem, spider: Spider) -> PageItem:
        if self._store is None or self._profile is None:
            return item

        record = item.to_record()
        self._profile.add_page(record, item.site_facts)
        if self._store.available:
            self._stored += self._store.upsert_pages(
                [{**record, "job_id": self._job_id, "site": self._site}]
            )
        return item

    def close_spider(self, spider: Spider) -> None:
        if self._store is None:
            return
        if self._store.available and self._profile is not None:
            profile = self._profile.build()
            self._store.upsert_site(self._site, profile)
            self._store.finish_job(
                self._job_id,
                "completed",
                {
                    "pages_stored": self._stored,
                    "page_count": profile["page_count"],
                    "services_count": profile["services_count"],
                    "team_count": profile["team_count"],
                    "pages_by_type": profile["pages_by_type"],
                },
            )
            logger.info(
                "Mongo: %s pages, %s services, %s team members for %s",
                self._stored,
                profile["services_count"],
                profile["team_count"],
                self._site,
            )
        self._store.close()
        self._store = None
