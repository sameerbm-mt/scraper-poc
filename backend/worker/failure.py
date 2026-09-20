"""Turn a failed crawl's log into a message a person can act on.

Scrapy writes everything to stderr, so the line that says *why* a crawl failed is
rarely among the last few lines. This reads the whole log instead of a raw tail:
it recognises the failures that have a known fix, and otherwise lists the first
requests that failed. The first line of the result is always the headline; the
job page shows it in the "Crawl failed" toast.
"""

from __future__ import annotations

import re

# Bounded so the whole message fits the 4000 characters the job record keeps.
TAIL_CHARS = 2500
MAX_FAILURES_SHOWN = 3
_WHY_CHARS = 200

# Playwright's message when its browser was never downloaded, e.g.
#   BrowserType.launch: Executable doesn't exist at C:\...\chrome-headless-shell.exe
_MISSING_BROWSER = re.compile(r"Executable doesn't exist at (?P<path>[^\r\n]+)")
_INSTALL_HINT = "playwright install"

# SiteSpider.on_error logs: Request failed: <url> (<reason>)
_REQUEST_FAILED = re.compile(r"Request failed: (?P<url>\S+) \((?P<why>[^\r\n]*)")

BROWSER_NOT_INSTALLED = (
    "Render JS needs Playwright's Chromium browser, which is not installed on the "
    "machine running the worker. Run `uv run playwright install chromium` in "
    "backend/, then start the crawl again."
)


def explain(log: str) -> str | None:
    """A specific, fixable cause found in `log`, or None."""
    missing = _MISSING_BROWSER.search(log)
    if missing or _INSTALL_HINT in log:
        # The path goes on its own line so the first line stays short enough for a toast.
        where = f"\nExpected at: {missing['path'].strip()}" if missing else ""
        return BROWSER_NOT_INSTALLED + where
    return None


def failed_requests(log: str, limit: int = MAX_FAILURES_SHOWN) -> list[str]:
    """The first distinct request failures, as `url: reason` lines."""
    seen: set[str] = set()
    found: list[str] = []
    for match in _REQUEST_FAILED.finditer(log):
        why = match["why"].strip().removesuffix(")")[:_WHY_CHARS]
        if why in seen:
            continue
        seen.add(why)
        found.append(f"{match['url']}: {why}")
        if len(found) == limit:
            break
    return found


def describe_failure(headline: str, log: str) -> str:
    """The message stored on a failed job.

    `headline` says what happened ("Crawl produced no pages."); `log` is the
    crawl's full stderr. A known cause replaces the headline as the first line.
    """
    cause = explain(log)
    lines = [cause or headline]
    if cause:
        lines.append(headline)

    failures = failed_requests(log)
    if failures and not cause:
        lines += ["", "First failed requests:", *(f"  {entry}" for entry in failures)]

    tail = log.strip()[-TAIL_CHARS:]
    if tail:
        lines += ["", "End of the crawl log:", tail]
    return "\n".join(lines)
