"""Sitemap discovery and parsing for sitemap-first crawling.

A sitemap is the site telling us its own URL list, which beats discovering the
same pages by following links: it reaches orphaned pages, skips the nav churn,
and gives the page cap something better to spend itself on.

Parsing leans on Scrapy's own ``Sitemap`` helper so gzipped and index sitemaps
work the same way they do in ``SitemapSpider``. Nothing here raises — a site
without a usable sitemap falls back to link-following.
"""

from __future__ import annotations

import logging
from typing import Iterable
from urllib.parse import urljoin, urlparse

from scrapy.utils.sitemap import Sitemap, sitemap_urls_from_robots

logger = logging.getLogger(__name__)

# Tried in order. The first two cover the overwhelming majority; the rest catch
# the common CMS spellings (Yoast, Rank Math, Shopify).
CANDIDATE_PATHS: tuple[str, ...] = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",
    "/sitemap1.xml",
)

# A sitemap index can point at hundreds of child sitemaps; bound the fan-out.
MAX_SITEMAPS = 50
MAX_URLS = 50_000


def candidate_urls(start_url: str) -> list[str]:
    """The sitemap URLs to try for a site, most likely first."""
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        return []
    root = f"{parsed.scheme}://{parsed.netloc}"
    return [urljoin(root, path) for path in CANDIDATE_PATHS]


def robots_url(start_url: str) -> str:
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def sitemaps_from_robots(body: bytes | str) -> list[str]:
    """`Sitemap:` directives in robots.txt — the authoritative location."""
    if isinstance(body, str):
        body = body.encode("utf-8", errors="replace")
    try:
        return list(sitemap_urls_from_robots(body))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read robots.txt sitemaps: %s", exc)
        return []


# The only two roots that mean anything to us. Anything else — most often an
# HTML 404 page served where a sitemap was expected — is treated as "no sitemap
# here" so the caller moves on to the next candidate.
KINDS: frozenset[str] = frozenset({"sitemapindex", "urlset"})

_GZIP_MAGIC = b"\x1f\x8b"


def _maybe_gunzip(body: bytes) -> bytes:
    """Sitemaps are commonly served as .xml.gz, which Sitemap() cannot read."""
    if not body.startswith(_GZIP_MAGIC):
        return body
    import gzip

    try:
        return gzip.decompress(body)
    except OSError as exc:
        logger.debug("Could not gunzip sitemap: %s", exc)
        return body


def parse(body: bytes) -> tuple[str, list[str]]:
    """`(kind, locs)` where kind is "sitemapindex", "urlset", or "" for neither.

    For an index the locs are child sitemaps to fetch; for a urlset they are
    page URLs to crawl.
    """
    if not body:
        return "", []
    try:
        sitemap = Sitemap(_maybe_gunzip(body))
        kind = sitemap.type or ""
        if kind not in KINDS:
            return "", []
        locs = [
            entry["loc"].strip()
            for entry in sitemap
            if entry.get("loc") and entry["loc"].strip()
        ]
    except Exception as exc:  # noqa: BLE001 - malformed XML is common
        logger.debug("Could not parse sitemap: %s", exc)
        return "", []
    return kind, locs[:MAX_URLS]


def keep_crawlable(urls: Iterable[str], is_crawlable) -> list[str]:
    """Filter sitemap URLs through the spider's own follow rules, preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen or not is_crawlable(url):
            continue
        seen.add(url)
        out.append(url)
    return out
