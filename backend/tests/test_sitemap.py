"""Tests for crawler.sitemap: discovery, index handling and the fallback."""

from __future__ import annotations

import gzip

from crawler import sitemap

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://a.com/one</loc></url>
  <url><loc>https://a.com/two</loc></url>
  <url><loc>  https://a.com/three  </loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://a.com/sitemap-posts.xml</loc></sitemap>
  <sitemap><loc>https://a.com/sitemap-pages.xml</loc></sitemap>
</sitemapindex>"""


class TestDiscovery:
    def test_candidates_are_rooted_at_the_host(self):
        candidates = sitemap.candidate_urls("https://a.com/some/deep/page?x=1")

        assert candidates[0] == "https://a.com/sitemap.xml"
        assert "https://a.com/sitemap_index.xml" in candidates

    def test_a_url_without_a_host_has_no_candidates(self):
        assert sitemap.candidate_urls("not-a-url") == []

    def test_robots_url_is_derived_from_the_start_url(self):
        assert sitemap.robots_url("https://a.com/deep/page") == "https://a.com/robots.txt"

    def test_sitemap_directives_are_read_from_robots(self):
        body = b"User-agent: *\nAllow: /\nSitemap: https://a.com/sitemap-index.xml\n"

        assert sitemap.sitemaps_from_robots(body) == ["https://a.com/sitemap-index.xml"]

    def test_robots_without_a_sitemap_yields_nothing(self):
        assert sitemap.sitemaps_from_robots(b"User-agent: *\nDisallow:\n") == []

    def test_a_str_body_is_accepted(self):
        assert sitemap.sitemaps_from_robots("Sitemap: https://a.com/s.xml") == [
            "https://a.com/s.xml"
        ]


class TestParsing:
    def test_a_urlset_yields_its_page_urls(self):
        kind, locs = sitemap.parse(URLSET)

        assert kind == "urlset"
        assert locs == ["https://a.com/one", "https://a.com/two", "https://a.com/three"]

    def test_an_index_yields_its_child_sitemaps(self):
        kind, locs = sitemap.parse(INDEX)

        assert kind == "sitemapindex"
        assert locs == [
            "https://a.com/sitemap-posts.xml",
            "https://a.com/sitemap-pages.xml",
        ]

    def test_a_gzipped_sitemap_is_read(self):
        kind, locs = sitemap.parse(gzip.compress(URLSET))

        assert kind == "urlset" and len(locs) == 3

    def test_truncated_xml_does_not_raise(self):
        """lxml recovers what it can; the salvage is filtered downstream."""
        kind, locs = sitemap.parse(b"<urlset><url><loc>broken")

        assert kind in ("", "urlset")
        # Whatever it salvaged is not a crawlable URL.
        assert sitemap.keep_crawlable(locs, lambda u: u.startswith("http")) == []

    def test_an_empty_body_is_empty(self):
        assert sitemap.parse(b"") == ("", [])

    def test_html_served_instead_of_xml_is_empty(self):
        assert sitemap.parse(b"<html><body>404</body></html>") == ("", [])


class TestFiltering:
    def test_only_crawlable_urls_survive_and_order_is_kept(self):
        urls = ["https://a.com/b", "https://a.com/a.pdf", "https://a.com/c"]

        kept = sitemap.keep_crawlable(urls, lambda u: not u.endswith(".pdf"))

        assert kept == ["https://a.com/b", "https://a.com/c"]

    def test_repeats_are_dropped(self):
        urls = ["https://a.com/x", "https://a.com/x", "https://a.com/y"]

        assert sitemap.keep_crawlable(urls, lambda u: True) == [
            "https://a.com/x",
            "https://a.com/y",
        ]


def test_url_count_is_bounded():
    many = b"".join(
        b"<url><loc>https://a.com/%d</loc></url>" % i for i in range(sitemap.MAX_URLS + 50)
    )
    body = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + many + b"</urlset>"

    _, locs = sitemap.parse(body)

    assert len(locs) == sitemap.MAX_URLS
