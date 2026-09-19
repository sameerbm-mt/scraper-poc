"""Tests for the spider's URL handling and link filtering."""

from __future__ import annotations

import pytest
from scrapy.http import HtmlResponse, Request

from crawler.items import PageItem
from crawler.spiders.site_spider import (
    SiteSpider,
    domain_of,
    has_skipped_extension,
    is_internal,
    normalise_url,
    should_follow,
)

ALLOWED = ["example.com"]


class TestDomainOf:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.com", "example.com"),
            ("https://www.example.com/path", "example.com"),
            ("http://example.com:8080/x", "example.com"),
            ("https://blog.example.com", "blog.example.com"),
            ("https://EXAMPLE.com", "example.com"),
        ],
    )
    def test_derives_domain(self, url, expected):
        assert domain_of(url) == expected


class TestNormaliseUrl:
    def test_drops_fragment(self):
        assert normalise_url("https://example.com/a#section") == "https://example.com/a"

    def test_page_and_its_anchor_normalise_together(self):
        assert normalise_url("https://example.com/a#one") == normalise_url(
            "https://example.com/a#two"
        )

    def test_keeps_query_string(self):
        assert "q=1" in normalise_url("https://example.com/a?q=1")

    def test_orders_query_parameters(self):
        assert normalise_url("https://example.com/a?b=2&a=1") == normalise_url(
            "https://example.com/a?a=1&b=2"
        )


class TestShouldFollow:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/pricing",
            "https://www.example.com/about",
            "https://blog.example.com/post",  # subdomains count as internal
            "http://example.com/plain-http",
            "https://example.com/docs/page.html",
            "https://example.com/path.with.dots/page",
        ],
    )
    def test_follows_internal_pages(self, url):
        assert should_follow(url, ALLOWED) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://other.com/page",
            "https://example.com.evil.com/page",  # suffix must be on a dot boundary
            "https://notexample.com/page",
        ],
    )
    def test_rejects_external_hosts(self, url):
        assert should_follow(url, ALLOWED) is False

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/whitepaper.pdf",
            "https://example.com/logo.png",
            "https://example.com/photo.JPG",  # extension check is case-insensitive
            "https://example.com/theme.css",
            "https://example.com/bundle.js",
            "https://example.com/archive.zip",
            "https://example.com/video.mp4",
            "https://example.com/font.woff2",
            "https://example.com/feed.xml",
        ],
    )
    def test_rejects_assets(self, url):
        assert should_follow(url, ALLOWED) is False

    @pytest.mark.parametrize(
        "url",
        [
            "mailto:hello@example.com",
            "tel:+15551234567",
            "javascript:void(0)",
            "data:text/html,<p>x</p>",
            "ftp://example.com/file",
            "",
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        assert should_follow(url, ALLOWED) is False

    def test_rejects_bare_fragment(self):
        assert should_follow(normalise_url("#section"), ALLOWED) is False


class TestHasSkippedExtension:
    def test_extensionless_path_is_allowed(self):
        assert has_skipped_extension("https://example.com/pricing") is False

    def test_dot_in_host_only_is_not_an_extension(self):
        assert has_skipped_extension("https://example.com") is False


class TestSpiderInit:
    def test_derives_allowed_domains_from_start_url(self):
        spider = SiteSpider(job_id="j1", start_url="https://www.example.com/start")
        assert spider.allowed_domains == ["example.com"]

    def test_normalises_start_url(self):
        spider = SiteSpider(job_id="j1", start_url="https://example.com/a#top")
        assert spider.start_url == "https://example.com/a"

    @pytest.mark.parametrize(
        "value,expected",
        [("true", True), ("True", True), ("1", True), ("false", False), ("0", False)],
    )
    def test_parses_use_js_string_argument(self, value, expected):
        spider = SiteSpider(job_id="j1", start_url="https://example.com", use_js=value)
        assert spider.use_js is expected

    def test_playwright_meta_only_when_use_js(self):
        assert SiteSpider(job_id="j", start_url="https://example.com")._meta() == {}
        js = SiteSpider(job_id="j", start_url="https://example.com", use_js="true")
        assert js._meta() == {"playwright": True}

    def test_requires_job_id_and_start_url(self):
        with pytest.raises(ValueError, match="job_id"):
            SiteSpider(start_url="https://example.com")
        with pytest.raises(ValueError, match="start_url"):
            SiteSpider(job_id="j1")


class TestParse:
    def _response(self, fixture_html, url="https://example.com/hub", depth=0):
        request = Request(url, meta={"depth": depth})
        return HtmlResponse(
            url=url,
            status=200,
            body=fixture_html("links.html").encode("utf-8"),
            encoding="utf-8",
            request=request,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    def _crawl(self, fixture_html, **kwargs):
        spider = SiteSpider(job_id="j1", start_url="https://example.com", **kwargs)
        return spider, list(spider.parse(self._response(fixture_html)))

    def test_yields_one_item_for_the_page(self, fixture_html):
        _, results = self._crawl(fixture_html)
        items = [r for r in results if isinstance(r, PageItem)]

        assert len(items) == 1
        assert items[0].url == "https://example.com/hub"
        assert items[0].title == "Link hub"
        assert items[0].h1 == "Link hub"
        assert items[0].status_code == 200
        assert items[0].html  # raw HTML is handed to ExtractPipeline

    def test_follows_only_internal_html_links(self, fixture_html):
        _, results = self._crawl(fixture_html)
        followed = {r.url for r in results if isinstance(r, Request)}

        assert "https://example.com/pricing" in followed
        assert "https://example.com/about" in followed
        assert "https://blog.example.com/post" in followed

    def test_skips_assets_external_and_non_http_links(self, fixture_html):
        _, results = self._crawl(fixture_html)
        followed = {r.url for r in results if isinstance(r, Request)}

        for rejected in (
            "https://other.com/page",
            "https://example.com/whitepaper.pdf",
            "https://example.com/logo.png",
            "https://example.com/bundle.js",
            "https://example.com/theme.css",
            "https://example.com/archive.zip",
        ):
            assert rejected not in followed
        assert not any(u.startswith(("mailto:", "tel:")) for u in followed)

    def test_fragment_link_does_not_re_request_the_current_page(self, fixture_html):
        _, results = self._crawl(fixture_html)
        followed = [r.url for r in results if isinstance(r, Request)]

        assert "https://example.com/hub" not in followed
        assert not any("#" in url for url in followed)

    def test_links_are_requested_once(self, fixture_html):
        _, results = self._crawl(fixture_html)
        followed = [r.url for r in results if isinstance(r, Request)]

        # /pricing appears twice in the fixture, once bare and once with #plans.
        assert followed.count("https://example.com/pricing") == 1
        assert len(followed) == len(set(followed))

    @pytest.mark.parametrize("depth", [0, 1, 5, 50])
    def test_keeps_following_links_at_any_depth(self, fixture_html, depth):
        """There is no depth limit — a deep page still yields its links."""
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        results = list(spider.parse(self._response(fixture_html, depth=depth)))

        assert [r for r in results if isinstance(r, PageItem)]
        assert [r for r in results if isinstance(r, Request)]

    def test_records_depth_on_the_item_as_information(self, fixture_html):
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        results = list(spider.parse(self._response(fixture_html, depth=7)))

        assert [r for r in results if isinstance(r, PageItem)][0].depth == 7

    def test_spider_has_no_depth_setting(self):
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        assert not hasattr(spider, "max_depth")

    def test_requests_carry_the_errback(self, fixture_html):
        spider, results = self._crawl(fixture_html)
        requests = [r for r in results if isinstance(r, Request)]

        assert requests and all(r.errback == spider.on_error for r in requests)

    def test_ignores_non_html_responses(self):
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        response = HtmlResponse(
            url="https://example.com/data",
            status=200,
            body=b'{"a": 1}',
            encoding="utf-8",
            request=Request("https://example.com/data"),
            headers={"Content-Type": "application/json"},
        )

        assert list(spider.parse(response)) == []


class TestIsInternal:
    def test_matches_on_dot_boundary(self):
        assert is_internal("https://a.example.com/x", ALLOWED) is True
        assert is_internal("https://fakeexample.com/x", ALLOWED) is False

    def test_ignores_port_and_credentials(self):
        assert is_internal("https://user:pw@example.com:8443/x", ALLOWED) is True


class TestLinkPriority:
    def test_profile_pages_outrank_blog_posts(self):
        from crawler.spiders.site_spider import PAGE_TYPE_PRIORITY

        assert PAGE_TYPE_PRIORITY["team"] > PAGE_TYPE_PRIORITY["services"]
        assert PAGE_TYPE_PRIORITY["about"] > PAGE_TYPE_PRIORITY["portfolio"]
        assert PAGE_TYPE_PRIORITY["services"] > PAGE_TYPE_PRIORITY["other"]
        assert PAGE_TYPE_PRIORITY["blog"] < PAGE_TYPE_PRIORITY["other"]

    def test_requests_are_emitted_with_a_priority(self, fixture_html):
        from crawler.spiders.site_spider import PAGE_TYPE_PRIORITY

        url = "https://example.com/hub"
        response = HtmlResponse(
            url=url, status=200, body=fixture_html("links.html").encode("utf-8"),
            encoding="utf-8", request=Request(url, meta={"depth": 0}),
            headers={"Content-Type": "text/html"},
        )
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        requests = [r for r in spider.parse(response) if isinstance(r, Request)]

        assert requests
        assert all(r.priority in PAGE_TYPE_PRIORITY.values() for r in requests)


class TestSpiderStructuredFields:
    def test_item_carries_page_type_and_link_counts(self, fixture_html):
        url = "https://example.com/about-us/"
        response = HtmlResponse(
            url=url, status=200, body=fixture_html("links.html").encode("utf-8"),
            encoding="utf-8", request=Request(url, meta={"depth": 0}),
            headers={"Content-Type": "text/html"},
        )
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        item = next(r for r in spider.parse(response) if isinstance(r, PageItem))

        assert item.page_type == "about"
        assert item.links_internal > 0
        assert item.links_external > 0

    def test_site_facts_only_gathered_on_profile_pages(self, fixture_html):
        spider = SiteSpider(job_id="j1", start_url="https://example.com")
        body = fixture_html("links.html").encode("utf-8")

        def item_for(url: str) -> PageItem:
            response = HtmlResponse(
                url=url, status=200, body=body, encoding="utf-8",
                request=Request(url, meta={"depth": 0}),
                headers={"Content-Type": "text/html"},
            )
            return next(r for r in spider.parse(response) if isinstance(r, PageItem))

        assert item_for("https://example.com/about-us/").site_facts != {}
        assert item_for("https://example.com/blogs/a-post/").site_facts == {}
