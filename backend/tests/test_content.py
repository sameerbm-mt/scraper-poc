"""Tests for the extraction fallback ladder."""

from __future__ import annotations

import pytest

from crawler.content import (
    STRATEGIES,
    _main_container_text,
    _whole_page_text,
    extract_content,
)

GOOD = 200


class TestExtractContent:
    def test_uses_trafilatura_for_a_normal_article(self, fixture_html):
        text, strategy = extract_content(
            fixture_html("article.html"), "https://example.com/a", GOOD
        )

        assert "Elfsight widgets" in text
        assert strategy == "trafilatura-markdown"

    def test_falls_back_when_trafilatura_returns_nothing(
        self, fixture_html, blind_trafilatura
    ):
        """The real failure mode: Trafilatura yields nothing on some templates.

        Observed on myratechnolabs.com, where `trafilatura.extract` returned
        None for a 110KB post whose article was plainly in the HTML.
        """
        html = fixture_html("trafilatura_blind.html")
        text, strategy = extract_content(html, "https://example.com/post/", GOOD)

        assert strategy == "main-container"
        assert len(text) > GOOD
        assert "offshore team gives access" in text.lower()

    def test_fallback_keeps_the_article_and_drops_chrome(self, fixture_html):
        html = fixture_html("trafilatura_blind.html")
        text = _main_container_text(html, "https://example.com/post/")

        assert "Reality Facing Businesses" in text
        assert "var x = 1" not in text
        assert "Across the globe" not in text  # footer boilerplate

    def test_empty_html_yields_nothing(self):
        assert extract_content("", "https://example.com/", GOOD) == ("", "none")

    def test_malformed_html_does_not_raise(self):
        text, strategy = extract_content("<<<not html", "https://example.com/", GOOD)
        assert isinstance(text, str) and isinstance(strategy, str)

    def test_returns_the_longest_result_when_none_clear_the_bar(self):
        html = "<html><body><p>Short.</p></body></html>"
        text, _ = extract_content(html, "https://example.com/", GOOD)
        assert "Short." in text

    def test_strategies_are_ordered_best_first(self):
        assert [name for name, _ in STRATEGIES] == [
            "trafilatura-markdown",
            "trafilatura-text",
            "main-container",
            "whole-page",
        ]

    def test_whole_page_text_recovers_the_article(self, fixture_html):
        """The floor of the ladder: no heuristics, but it does return the text."""
        text = _whole_page_text(fixture_html("trafilatura_blind.html"), "")

        assert "Reality Facing Businesses" in text
        # It also sweeps in nav links, which is why it ranks last.
        assert "Home" in text


class TestExtractPipelineWithFallback:
    def test_page_trafilatura_cannot_read_is_still_stored(
        self, fixture_html, spider, blind_trafilatura
    ):
        from crawler.items import PageItem
        from crawler.pipelines import ExtractPipeline

        item = PageItem(
            url="https://example.com/post/",
            status_code=200,
            depth=0,
            html=fixture_html("trafilatura_blind.html"),
        )
        result = ExtractPipeline().process_item(item, spider)

        assert result.word_count > 80
        assert result.extracted_by == "main-container"
        assert result.content_hash

    def test_two_such_pages_do_not_collide_on_boilerplate(
        self, fixture_html, spider, blind_trafilatura
    ):
        """The bug this guards: distinct pages collapsing onto shared chrome."""
        from crawler.items import PageItem
        from crawler.pipelines import DedupePipeline, ExtractPipeline

        html = fixture_html("trafilatura_blind.html")
        other = html.replace(
            "Software development costs are rising continuously across North America.",
            "Entirely different opening sentence about something else altogether.",
        )
        extract, dedupe = ExtractPipeline(), DedupePipeline()

        a = extract.process_item(
            PageItem(url="https://example.com/a/", status_code=200, depth=0, html=html),
            spider,
        )
        b = extract.process_item(
            PageItem(url="https://example.com/b/", status_code=200, depth=0, html=other),
            spider,
        )

        assert a.content_hash != b.content_hash
        assert dedupe.process_item(a, spider) is a
        assert dedupe.process_item(b, spider) is b
