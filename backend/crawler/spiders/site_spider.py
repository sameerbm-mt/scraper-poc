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
from crawler import assets, seo, sitemap as sitemap_mod, structured
from crawler.extractors import (
    classify_page,
    extract_contacts as extract_contact_details,
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
# Documents are listed on the item and fetched by DocumentsPipeline instead.
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


def as_bool(value: str | bool) -> bool:
    """Scrapy passes every -a value through as a string."""
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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

        scrapy crawl site -a job_id=... -a start_url=... -a max_pages=0 \
            -a use_js=false -a use_sitemap=false -a download_files=false \
            -a extract_contacts=false

    Every internal link is followed to the end of the site; `depth` is recorded
    on each item as information, not as a limit. With `use_sitemap` the frontier
    comes from the site's own sitemap instead, falling back to link-following
    when there is no usable one.
    """

    name = "site"

    def __init__(
        self,
        job_id: str = "",
        start_url: str = "",
        max_pages: str | int = 0,
        use_js: str | bool = False,
        use_sitemap: str | bool = False,
        download_files: str | bool = False,
        extract_contacts: str | bool = False,
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
        self.use_js = as_bool(use_js)
        self.use_sitemap = as_bool(use_sitemap)
        # Read by DocumentsPipeline.
        self.download_files = as_bool(download_files)
        # Contacts are personal data, so they are only collected on request.
        self.extract_contacts = as_bool(extract_contacts)

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
        # Sitemap bookkeeping, only used when use_sitemap is on.
        self._sitemap_seeded = 0
        self._sitemaps_read = 0

    # -- requests ---------------------------------------------------------

    def _meta(self) -> dict[str, Any]:
        return {"playwright": True} if self.use_js else {}

    def _page_request(self, url: str, priority: int = 0) -> scrapy.Request:
        return scrapy.Request(
            url,
            callback=self.parse,
            errback=self.on_error,
            meta=self._meta(),
            priority=priority,
        )

    def start_requests(self) -> Iterator[scrapy.Request]:
        if self.use_sitemap:
            # robots.txt names the real sitemap location; the well-known paths
            # are the fallback when it does not.
            yield scrapy.Request(
                sitemap_mod.robots_url(self.start_url),
                callback=self.parse_robots,
                errback=self.on_robots_error,
                dont_filter=True,
                meta={"handle_httpstatus_all": True},
            )
            return
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

    # -- sitemap ----------------------------------------------------------

    def _sitemap_request(self, queue: list[str]) -> Iterator[scrapy.Request]:
        """Try the next candidate sitemap, carrying the rest along in meta."""
        while queue:
            url = queue.pop(0)
            if self._sitemaps_read >= sitemap_mod.MAX_SITEMAPS:
                self.logger.info("Sitemap limit reached; stopping discovery")
                break
            self._sitemaps_read += 1
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap,
                errback=self.on_sitemap_error,
                dont_filter=True,
                meta={"sitemap_queue": queue, "handle_httpstatus_all": True},
            )
            return
        # Nothing left to try.
        yield from self._sitemap_exhausted()

    def _sitemap_exhausted(self) -> Iterator[scrapy.Request]:
        """No sitemap produced URLs — fall back to ordinary link-following."""
        if self._sitemap_seeded:
            return
        self.logger.warning(
            "No usable sitemap for %s; falling back to link-following", self.start_url
        )
        self.use_sitemap = False
        yield scrapy.Request(
            self.start_url,
            callback=self.parse,
            errback=self.on_error,
            meta=self._meta(),
            dont_filter=True,
        )

    def parse_robots(self, response: Response) -> Iterator[scrapy.Request]:
        declared: list[str] = []
        if response.status == 200:
            declared = sitemap_mod.sitemaps_from_robots(response.body)
            if declared:
                self.logger.info("robots.txt declares %s sitemap(s)", len(declared))
        queue = declared + [
            url
            for url in sitemap_mod.candidate_urls(self.start_url)
            if url not in declared
        ]
        yield from self._sitemap_request(queue)

    def on_robots_error(self, failure: Failure) -> Iterator[scrapy.Request]:
        self.logger.info("robots.txt unreachable (%s); trying well-known paths", failure.value)
        yield from self._sitemap_request(sitemap_mod.candidate_urls(self.start_url))

    def parse_sitemap(self, response: Response) -> Iterator[scrapy.Request]:
        queue: list[str] = response.meta.get("sitemap_queue") or []

        if response.status != 200:
            yield from self._sitemap_request(queue)
            return

        kind, locs = sitemap_mod.parse(response.body)

        if kind == "sitemapindex":
            # Child sitemaps go to the front: they are known-good locations.
            self.logger.info("Sitemap index with %s child sitemap(s)", len(locs))
            yield from self._sitemap_request(locs + queue)
            return

        if kind == "urlset" and locs:
            crawlable = sitemap_mod.keep_crawlable(
                locs, lambda url: should_follow(url, self.allowed_domains)
            )
            fresh = [url for url in map(normalise_url, crawlable) if url not in self._seen]
            self.logger.info(
                "Sitemap %s: %s URLs, %s crawlable and new", response.url, len(locs), len(fresh)
            )
            for url in fresh:
                self._seen.add(url)
                self._sitemap_seeded += 1
                yield self._page_request(
                    url, priority=PAGE_TYPE_PRIORITY.get(classify_page(url), 0)
                )
            # Keep draining the queue: an index's children each add more URLs.
            if queue:
                yield from self._sitemap_request(queue)
            return

        yield from self._sitemap_request(queue)

    def on_sitemap_error(self, failure: Failure) -> Iterator[scrapy.Request]:
        request = getattr(failure, "request", None)
        self.logger.debug("Sitemap fetch failed: %s", getattr(request, "url", "?"))
        queue = (request.meta.get("sitemap_queue") if request else None) or []
        yield from self._sitemap_request(queue)

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

        internal_count, external_links = assets.collect_links(
            response, self.allowed_domains
        )
        document_links = assets.collect_documents(response)
        facts = structured.summarise(response.text, response.url)

        item = PageItem(
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
            headings=seo.extract_headings(response),
            # `lang` is finished in ExtractPipeline, which has the markdown that
            # detection needs; this is the page's own declaration.
            lang=meta["lang"],
            meta_robots=meta["robots"],
            canonical_url=meta["canonical_url"],
            og=seo.extract_open_graph(response),
            twitter=seo.extract_twitter(response),
            hreflang=seo.extract_hreflang(response),
            jsonld=facts["jsonld"],
            schema_types=facts["schema_types"],
            faqs=facts["faqs"],
            products=facts["products"],
            internal_links_count=internal_count,
            external_links=external_links,
            images=assets.collect_images(response),
            videos=assets.collect_videos(response),
            document_links=document_links,
            file_urls=[entry["url"] for entry in document_links],
            redirect_chain=_redirect_chain(response),
            response_time_ms=_response_time_ms(response),
            content_type=content_type,
            page_size_bytes=len(response.body),
            page_type=page_type,
            og_image=meta["og_image"],
            site_facts=self._site_facts(response, page_type, meta),
            html=response.text,
        )

        if self.extract_contacts:
            self._add_contacts(item, response, facts["jsonld_addresses"])

        yield item

        # Mark this page seen before extracting: a bare "#anchor" link resolves
        # back to it, and a redirect may have landed us on a URL we never queued.
        self._seen.add(normalise_url(response.url))

        # In sitemap mode the frontier is the sitemap, not the page's links.
        if self.use_sitemap and self._sitemap_seeded:
            return

        for link in self._link_extractor.extract_links(response):
            url = normalise_url(link.url)
            if url in self._seen or not should_follow(url, self.allowed_domains):
                continue
            self._seen.add(url)
            yield self._page_request(
                url, priority=PAGE_TYPE_PRIORITY.get(classify_page(url, link.text), 0)
            )

    # -- structured extraction --------------------------------------------

    def _add_contacts(
        self, item: PageItem, response: Response, jsonld_addresses: list[str]
    ) -> None:
        """Personal data, gathered only when the job asked for it.

        Addresses come from JSON-LD PostalAddress alone — see
        crawler.structured.extract_addresses for why there is no regex here.
        """
        contacts = extract_contact_details(response)
        item.emails = contacts["emails"]
        item.phones = contacts["phones"]
        item.social_links = [
            {"platform": entry["network"], "url": entry["url"]}
            for entry in contacts["socials"]
        ]
        item.addresses = jsonld_addresses

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
            "contacts": extract_contact_details(response),
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


def _redirect_chain(response: Response) -> list[str]:
    """Every URL walked through to reach this one, final URL last.

    Consecutive repeats are collapsed: a redirect that only changed the scheme
    or a trailing slash can leave the same string twice, which reads as a loop
    when it is not one.
    """
    hops = [*(str(url) for url in response.meta.get("redirect_urls") or []), response.url]
    chain: list[str] = []
    for url in hops:
        if not chain or chain[-1] != url:
            chain.append(url)
    # A single entry means nothing was redirected — just the page itself.
    return chain if len(chain) > 1 else []


def _response_time_ms(response: Response) -> int:
    """Scrapy records the download latency in seconds on the request meta."""
    latency = response.meta.get("download_latency")
    if latency is None:
        return 0
    try:
        return int(float(latency) * 1000)
    except (TypeError, ValueError):
        return 0


def _first_text(response: Response, selector: str) -> str:
    value = response.css(selector).get()
    return value.strip() if value else ""
