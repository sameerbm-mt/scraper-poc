"""The `site` spider: breadth-first crawl of a single site."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import urldefrag, urlparse

import scrapy
from scrapy.http import Response
from scrapy.linkextractors import LinkExtractor
from twisted.python.failure import Failure
from w3lib.url import canonicalize_url

from app.urls import domain_of, host_of, site_slug
from crawler.extractors import (
    classify_page,
    extract_contacts,
    extract_jsonld,
    extract_organisation,
    extract_page_meta,
    extract_service_links,
    extract_team,
)
from crawler.items import PageItem
from crawler.progress import JobProgress

# Anything we cannot turn into text. Scrapy would download these before we could
# reject them on content-type, so they are filtered at link-extraction time.
SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        # documents / archives
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "rtf",
        "zip", "gz", "tgz", "bz2", "7z", "rar", "tar", "dmg", "exe", "pkg",
        # images
        "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp", "tif", "tiff", "avif",
        # media
        "mp3", "mp4", "avi", "mov", "wmv", "flv", "webm", "ogg", "wav", "m4a",
        # assets / feeds
        "css", "js", "mjs", "json", "xml", "rss", "atom",
        "woff", "woff2", "ttf", "eot", "map",
    }
)

SKIP_SCHEMES: frozenset[str] = frozenset(
    {"mailto", "tel", "javascript", "data", "ftp", "sms", "file"}
)


def normalise_url(url: str) -> str:
    """Drop the fragment and canonicalise, so /a?b=1#x and /a?b=1 are one URL."""
    defragged, _ = urldefrag(url.strip())
    return canonicalize_url(defragged)


# Site-level facts (contacts, services, team) only live on these page types;
# running the full extraction on every blog post would be wasted work.
SITE_FACT_PAGE_TYPES: frozenset[str] = frozenset(
    {"home", "about", "contact", "team", "careers", "services"}
)

# Scrapy serves higher-priority requests first. Without this a page cap gets
# spent on whichever links appear first — usually blog posts — and the pages
# that actually carry the company profile are never reached.
PAGE_TYPE_PRIORITY: dict[str, int] = {
    "team": 100,
    "about": 90,
    "contact": 90,
    "services": 70,
    "careers": 50,
    "portfolio": 30,
    "pricing": 30,
    "other": 0,
    "legal": -20,
    "blog": -50,
    # Followed only to discover the posts they link to.
    "archive": -80,
}


def is_internal(url: str, allowed_domains: Iterable[str]) -> bool:
    host = host_of(url)
    if not host:
        return False
    return any(
        host == domain or host.endswith(f".{domain}") for domain in allowed_domains
    )


def has_skipped_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    _, _, suffix = path.rpartition(".")
    return bool(suffix) and suffix != path and suffix in SKIP_EXTENSIONS


def should_follow(url: str, allowed_domains: Iterable[str]) -> bool:
    """True when `url` is an internal, crawlable HTML page."""
    if not url:
        return False
    scheme = urlparse(url).scheme.lower()
    if scheme in SKIP_SCHEMES:
        return False
    if scheme not in ("http", "https"):
        return False
    if not is_internal(url, allowed_domains):
        return False
    return not has_skipped_extension(url)


class SiteSpider(scrapy.Spider):
    """Crawls one site and emits a PageItem per HTML page.

    Invoked by the worker as::

        scrapy crawl site -a job_id=... -a start_url=... -a max_pages=0 -a use_js=false

    Every internal link is followed to the end of the site; `depth` is recorded
    on each item as information, not as a limit.
    """

    name = "site"

    def __init__(
        self,
        job_id: str = "",
        start_url: str = "",
        max_pages: str | int = 0,
        use_js: str | bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not job_id:
            raise ValueError("job_id is required (-a job_id=...)")
        if not start_url:
            raise ValueError("start_url is required (-a start_url=...)")

        self.job_id = job_id
        self.start_url = normalise_url(start_url)
        # Read by JsonLinesPipeline, which makes this a hard cap on stored pages.
        # There is no depth limit: the crawl follows internal links until the
        # site runs out of them.
        self.max_pages = int(max_pages)
        # Scrapy passes -a values as strings.
        self.use_js = str(use_js).strip().lower() in ("1", "true", "yes", "on")

        domain = domain_of(self.start_url)
        if not domain:
            raise ValueError(f"Could not derive a domain from {start_url!r}")
        self.allowed_domains = [domain]
        # Folder name on disk and _id in the Mongo `sites` collection.
        self.site = site_slug(self.start_url)

        self._link_extractor = LinkExtractor(
            allow_domains=self.allowed_domains,
            deny_extensions=sorted(SKIP_EXTENSIONS),
            canonicalize=True,
            unique=True,
        )
        self._seen: set[str] = {self.start_url}
        self.progress = JobProgress(job_id)

    # -- requests ---------------------------------------------------------

    def _meta(self) -> dict[str, Any]:
        return {"playwright": True} if self.use_js else {}

    def start_requests(self) -> Iterator[scrapy.Request]:
        yield scrapy.Request(
            self.start_url,
            callback=self.parse,
            errback=self.on_error,
            meta=self._meta(),
            dont_filter=True,
        )

    # Scrapy >= 2.13 prefers the async `start()`; keep both so either version works.
    async def start(self):  # type: ignore[override]
        for request in self.start_requests():
            yield request

    # -- callbacks --------------------------------------------------------

    def parse(self, response: Response) -> Iterator[PageItem | scrapy.Request]:
        content_type = response.headers.get("Content-Type", b"").decode(errors="ignore")
        if content_type and "html" not in content_type.lower():
            self.logger.debug("Skipping non-HTML %s (%s)", response.url, content_type)
            return

        depth = int(response.meta.get("depth", 0))
        title = _first_text(response, "title::text")
        h1 = _first_text(response, "h1::text")
        page_type = classify_page(response.url, title, h1)
        meta = extract_page_meta(response)
        internal, external, images = self._count_links(response)

        yield PageItem(
            url=response.url,
            status_code=response.status,
            depth=depth,
            title=title,
            meta_description=(
                response.css('meta[name="description"]::attr(content)').get()
                or meta["og_description"]
                or ""
            ).strip(),
            h1=h1,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            page_type=page_type,
            canonical_url=meta["canonical_url"],
            lang=meta["lang"],
            og_image=meta["og_image"],
            links_internal=internal,
            links_external=external,
            images=images,
            site_facts=self._site_facts(response, page_type, meta),
            html=response.text,
        )

        # Mark this page seen before extracting: a bare "#anchor" link resolves
        # back to it, and a redirect may have landed us on a URL we never queued.
        self._seen.add(normalise_url(response.url))

        for link in self._link_extractor.extract_links(response):
            url = normalise_url(link.url)
            if url in self._seen or not should_follow(url, self.allowed_domains):
                continue
            self._seen.add(url)
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.on_error,
                meta=self._meta(),
                priority=PAGE_TYPE_PRIORITY.get(classify_page(url, link.text), 0),
            )

    # -- structured extraction --------------------------------------------

    def _count_links(self, response: Response) -> tuple[int, int, int]:
        internal = external = 0
        for href in response.css("a::attr(href)").getall():
            href = (href or "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if is_internal(response.urljoin(href), self.allowed_domains):
                internal += 1
            else:
                external += 1
        return internal, external, len(response.css("img").getall())

    def _site_facts(
        self, response: Response, page_type: str, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Company-level signals, aggregated into the `sites` document later.

        Only gathered on pages that plausibly carry them — see
        SITE_FACT_PAGE_TYPES — because the text sweep is expensive.
        """
        if page_type not in SITE_FACT_PAGE_TYPES:
            return {}

        jsonld = extract_jsonld(response)
        facts: dict[str, Any] = {
            "contacts": extract_contacts(response),
            "services": extract_service_links(response, self.allowed_domains[0]),
            "team": extract_team(response, jsonld),
            "organisation": extract_organisation(jsonld),
        }
        if page_type == "home":
            # The homepage defines the site's own identity.
            facts["identity"] = {
                "name": meta["og_site_name"] or self._brand_from_title(response),
                "description": meta["og_description"],
                "og_image": meta["og_image"],
                "favicon": response.urljoin(meta["favicon"]) if meta["favicon"] else "",
                "lang": meta["lang"],
            }
        return facts

    @staticmethod
    def _brand_from_title(response: Response) -> str:
        """Fall back to the trailing brand in "Page Title | Brand"."""
        title = _first_text(response, "title::text")
        for separator in ("|", "-", "—", "–", "::"):
            if separator in title:
                return title.rsplit(separator, 1)[-1].strip()
        return title.strip()

    def on_error(self, failure: Failure) -> None:
        """Count anything that never reached `parse` — DNS, timeouts, 4xx/5xx."""
        request = getattr(failure, "request", None)
        url = getattr(request, "url", "<unknown>")
        self.logger.warning("Request failed: %s (%s)", url, failure.value)
        self.progress.incr_failed()


def _first_text(response: Response, selector: str) -> str:
    value = response.css(selector).get()
    return value.strip() if value else ""
