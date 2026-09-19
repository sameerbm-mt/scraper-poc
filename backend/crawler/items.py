"""Scrapy items. Dataclasses keep the fields typed and json-serialisable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Populated by the spider, consumed by the pipelines, never exported.
TRANSIENT_FIELDS = frozenset({"html", "site_facts"})

# Column order for pages.csv. Markdown is deliberately absent: multi-KB cells
# make a CSV unusable in a spreadsheet, and pages.jsonl already carries it.
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
    "links_internal",
    "links_external",
    "images",
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

    # Structured extras, filled in by the spider via crawler.extractors.
    page_type: str = ""
    canonical_url: str = ""
    lang: str = ""
    og_image: str = ""
    links_internal: int = 0
    links_external: int = 0
    images: int = 0
    # Which extraction strategy produced the markdown — see crawler/content.py.
    extracted_by: str = ""

    # Transient: dropped before the item is written anywhere.
    html: str = field(default="", repr=False)
    site_facts: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_record(self) -> dict[str, Any]:
        """The shape written to pages.jsonl, Mongo and the API."""
        return {k: v for k, v in asdict(self).items() if k not in TRANSIENT_FIELDS}

    def to_csv_row(self) -> dict[str, Any]:
        record = self.to_record()
        return {column: record.get(column, "") for column in CSV_COLUMNS}
