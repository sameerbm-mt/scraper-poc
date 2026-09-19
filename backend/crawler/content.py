"""HTML to markdown/text, with fallbacks for pages Trafilatura gives up on.

Trafilatura is excellent when it works, but on some templates its main
algorithm returns nothing at all even though the article is plainly in the
HTML. Left unhandled, those pages either get dropped as empty or collapse onto
whatever boilerplate the recall pass scrapes up — and then DedupePipeline
discards them as duplicates of each other. This module walks a ladder of
strategies and returns the first result that looks like real content.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

import lxml.html
import trafilatura
from lxml.etree import ParserError, XMLSyntaxError

logger = logging.getLogger(__name__)

# Elements that are never article content.
_STRIP_TAGS = (
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "svg", "template", "button",
)

# Containers that usually hold the main article, best guess first.
_CONTENT_XPATHS = (
    "//article",
    "//main",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' post-content ')]",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' entry-content ')]",
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' article-content ')]",
    "//*[contains(@class, 'post-content')]",
    "//*[contains(@class, 'entry-content')]",
    "//*[contains(@class, 'article-body')]",
    "//*[@id='content']",
    "//*[contains(@class, 'content')]",
)

_BLANK_RUN = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _trafilatura_markdown(html: str, url: str) -> str:
    return (
        trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            favor_precision=False,
            url=url,
        )
        or ""
    ).strip()


def _trafilatura_text(html: str, url: str) -> str:
    return (
        trafilatura.extract(
            html,
            output_format="txt",
            no_fallback=False,
            favor_recall=True,
            url=url,
        )
        or ""
    ).strip()


def _main_container_text(html: str, url: str) -> str:
    """Pull text from the page's main content container.

    Used when Trafilatura's algorithm bails. Picks whichever candidate
    container yields the most text, after stripping chrome.
    """
    try:
        tree = lxml.html.fromstring(html)
    except (ParserError, XMLSyntaxError, ValueError):
        return ""

    for element in tree.xpath("|".join(f"//{tag}" for tag in _STRIP_TAGS)):
        element.getparent() is not None and element.getparent().remove(element)

    best = ""
    for xpath in _CONTENT_XPATHS:
        for node in tree.xpath(xpath):
            candidate = _clean(node.text_content())
            if len(candidate) > len(best):
                best = candidate
        # A good hit on a specific container beats scanning the vaguer ones.
        if len(best) >= 500:
            break
    return best


def _whole_page_text(html: str, url: str) -> str:
    """Last resort: Trafilatura's raw HTML-to-text, which has no heuristics."""
    try:
        return _clean(trafilatura.html2txt(html) or "")
    except Exception:  # pragma: no cover - html2txt is defensive already
        return ""


# Ordered best-quality-first. The first strategy clearing the threshold wins.
STRATEGIES: tuple[tuple[str, Callable[[str, str], str]], ...] = (
    ("trafilatura-markdown", _trafilatura_markdown),
    ("trafilatura-text", _trafilatura_text),
    ("main-container", _main_container_text),
    ("whole-page", _whole_page_text),
)


def extract_content(html: str, url: str, min_chars: int) -> tuple[str, str]:
    """Return (text, strategy_name). Empty text means nothing usable was found.

    Falls through the ladder until a strategy produces at least `min_chars`;
    if none do, the longest result is returned so the caller can decide.
    """
    if not html:
        return "", "none"

    best_text, best_name = "", "none"
    for name, strategy in STRATEGIES:
        try:
            text = strategy(html, url)
        except Exception as exc:  # a bad page must not kill the crawl
            logger.debug("extract strategy %s failed on %s: %s", name, url, exc)
            continue
        if len(text) > len(best_text):
            best_text, best_name = text, name
        if len(text) >= min_chars:
            return text, name

    return best_text, best_name
