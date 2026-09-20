"""Headings, SEO metadata and language detection for one page.

`crawler.extractors.extract_page_meta` already returns the flat og/twitter/
canonical fields the site profile needs. This module covers what the per-page
record adds on top: the heading outline, og/twitter as nested objects, hreflang
alternates, and a detected language for when `<html lang>` is absent or lying.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import py3langid
from scrapy.http import Response

logger = logging.getLogger(__name__)

# A nav-heavy template can carry dozens of headings; the outline only needs the
# top of the document to be useful.
MAX_HEADINGS = 60
MAX_HREFLANG = 40
_HEADING_CHARS = 300

# Language detection needs a reasonable sample; below this it guesses wildly.
MIN_CHARS_FOR_LANG = 60
_LANG_SAMPLE_CHARS = 3000

_WS = re.compile(r"\s+")


def _text(value: str | None) -> str:
    return _WS.sub(" ", value).strip() if value else ""


def extract_headings(response: Response) -> list[dict[str, Any]]:
    """`[{level, text}]` for h1-h3, in document order.

    Uses one XPath over all three levels so ordering reflects the page rather
    than being grouped by level.
    """
    headings: list[dict[str, Any]] = []
    try:
        nodes = response.xpath("//h1|//h2|//h3")
    except (ValueError, AttributeError):  # non-HTML response
        return []

    for node in nodes:
        tag = node.root.tag if hasattr(node.root, "tag") else ""
        if not isinstance(tag, str) or tag[:1] != "h":
            continue
        # `.//text()` so <h2>Hire <b>Django</b></h2> keeps both halves.
        text = _text(" ".join(node.xpath(".//text()").getall()))
        if not text:
            continue
        headings.append({"level": int(tag[1]), "text": text[:_HEADING_CHARS]})
        if len(headings) >= MAX_HEADINGS:
            break
    return headings


def extract_hreflang(response: Response) -> list[dict[str, str]]:
    """`[{lang, url}]` from <link rel="alternate" hreflang>."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in response.css('link[rel="alternate"][hreflang]'):
        lang = _text(node.attrib.get("hreflang"))
        href = _text(node.attrib.get("href"))
        if not lang or not href or lang in seen:
            continue
        seen.add(lang)
        out.append({"lang": lang, "url": response.urljoin(href)})
        if len(out) >= MAX_HREFLANG:
            break
    return out


def _meta_content(response: Response, *selectors: str) -> str:
    for selector in selectors:
        value = response.css(selector).get()
        if value and value.strip():
            return _text(value)
    return ""


def extract_open_graph(response: Response) -> dict[str, str]:
    """`{title, description, image, type}` — the og fields worth keeping."""
    image = _meta_content(response, 'meta[property="og:image"]::attr(content)')
    return {
        "title": _meta_content(response, 'meta[property="og:title"]::attr(content)'),
        "description": _meta_content(
            response, 'meta[property="og:description"]::attr(content)'
        ),
        # Relative og:image is invalid but common; make it usable anyway.
        "image": response.urljoin(image) if image else "",
        "type": _meta_content(response, 'meta[property="og:type"]::attr(content)'),
    }


def extract_twitter(response: Response) -> dict[str, str]:
    """Twitter card tags, falling back to the `property=` spelling some CMSes emit."""

    def pick(name: str) -> str:
        return _meta_content(
            response,
            f'meta[name="twitter:{name}"]::attr(content)',
            f'meta[property="twitter:{name}"]::attr(content)',
        )

    image = pick("image")
    return {
        "card": pick("card"),
        "title": pick("title"),
        "description": pick("description"),
        "image": response.urljoin(image) if image else "",
        "site": pick("site"),
    }


def detect_language(markdown: str, declared: str = "") -> str:
    """The page's language as a two-letter code.

    `<html lang>` is trusted when present — it is the site's own declaration —
    and py3langid only fills the gap when it is missing. Returns "" rather than
    guessing from a couple of words.
    """
    if declared:
        # "en-GB" / "en_US" -> "en"
        code = declared.strip().replace("_", "-").split("-")[0].lower()
        if len(code) == 2 and code.isalpha():
            return code

    sample = (markdown or "").strip()
    if len(sample) < MIN_CHARS_FOR_LANG:
        return ""
    try:
        code, _score = py3langid.classify(sample[:_LANG_SAMPLE_CHARS])
    except Exception as exc:  # noqa: BLE001 - detection is best-effort
        logger.debug("Language detection failed: %s", exc)
        return ""
    return str(code).lower() if code else ""
