"""Scrapy items. Dataclasses keep the fields typed and json-serialisable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Populated by the spider, consumed by the pipelines, never exported.
# `file_urls`/`files` are Scrapy's FilesPipeline plumbing and carry no meaning
# once the download has happened.
TRANSIENT_FIELDS = frozenset({"html", "site_facts", "file_urls", "files"})

# Column order for pages.csv. Markdown is deliberately absent: multi-KB cells
# make a CSV unusable in a spreadsheet, and pages.jsonl already carries it.
# The list/dict fields are summarised as counts here for the same reason; the
# full values live in the JSONL.
CSV_COLUMNS: tuple[str, ...] = (
    "url",
    "status_code",
    "depth",
    "page_type",
    "title",
    "meta_description",
    "h1",
    "word_count",
    "content_hash",
    "lang",
    "canonical_url",
    "internal_links_count",
    "external_links_count",
    "images_count",
    "videos_count",
    "documents_count",
    "schema_types_joined",
    "faqs_count",
    "products_count",
    "response_time_ms",
    "page_size_bytes",
    "extracted_by",
    "crawled_at",
)


@dataclass
class PageItem:
    url: str
    status_code: int
    depth: int
    title: str = ""
    meta_description: str = ""
    h1: str = ""
    markdown: str = ""
    word_count: int = 0
    content_hash: str = ""
    crawled_at: str = ""

    # -- content structure
    headings: list[dict[str, Any]] = field(default_factory=list)
    lang: str = ""

    # -- SEO / meta
    meta_robots: str = ""
    canonical_url: str = ""
    og: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    hreflang: list[dict[str, str]] = field(default_factory=list)

    # -- structured data
    jsonld: list[dict[str, Any]] = field(default_factory=list)
    schema_types: list[str] = field(default_factory=list)
    faqs: list[dict[str, str]] = field(default_factory=list)
    products: list[dict[str, str]] = field(default_factory=list)

    # -- links & media
    internal_links_count: int = 0
    external_links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    videos: list[dict[str, str]] = field(default_factory=list)
    document_links: list[dict[str, str]] = field(default_factory=list)
    documents_downloaded: int = 0

    # -- contacts (only populated when the job sets extract_contacts)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    social_links: list[dict[str, str]] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)

    # -- technical
    redirect_chain: list[str] = field(default_factory=list)
    response_time_ms: int = 0
    content_type: str = ""
    page_size_bytes: int = 0

    # -- classification / provenance
    page_type: str = ""
    og_image: str = ""
    # Which extraction strategy produced the markdown — see crawler/content.py.
    extracted_by: str = ""

    # Transient: dropped before the item is written anywhere.
    html: str = field(default="", repr=False)
    site_facts: dict[str, Any] = field(default_factory=dict, repr=False)
    file_urls: list[str] = field(default_factory=list, repr=False)
    files: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_record(self) -> dict[str, Any]:
        """The shape written to pages.jsonl, Mongo and the API."""
        return {k: v for k, v in asdict(self).items() if k not in TRANSIENT_FIELDS}

    def to_csv_row(self) -> dict[str, Any]:
        record = self.to_record()
        # Counts and a joined string stand in for the collections, so the CSV
        # stays one flat row per page.
        record["external_links_count"] = len(self.external_links)
        record["images_count"] = len(self.images)
        record["videos_count"] = len(self.videos)
        record["documents_count"] = len(self.document_links)
        record["schema_types_joined"] = ",".join(self.schema_types)
        record["faqs_count"] = len(self.faqs)
        record["products_count"] = len(self.products)
        return {column: record.get(column, "") for column in CSV_COLUMNS}
