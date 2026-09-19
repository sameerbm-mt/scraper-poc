"""Tests for ExtractPipeline and DedupePipeline."""

from __future__ import annotations

import json

import pytest
from scrapy.exceptions import DropItem

from crawler.items import PageItem
from crawler.pipelines import (
    DedupePipeline,
    ExtractPipeline,
    JsonLinesPipeline,
    content_hash,
    normalise_markdown,
)


def make_item(html: str = "", url: str = "https://example.com/page") -> PageItem:
    return PageItem(url=url, status_code=200, depth=0, html=html)


class TestExtractPipeline:
    def test_extracts_markdown_from_article(self, fixture_html, spider):
        item = ExtractPipeline().process_item(
            make_item(fixture_html("article.html")), spider
        )

        assert "Elfsight widgets" in item.markdown
        assert item.word_count > 40
        assert item.content_hash == content_hash(item.markdown)
        assert len(item.content_hash) == 64

    def test_strips_boilerplate(self, fixture_html, spider):
        item = ExtractPipeline().process_item(
            make_item(fixture_html("article.html")), spider
        )

        # Nav and footer chrome should not survive extraction.
        assert "Copyright 2026" not in item.markdown

    def test_clears_raw_html_after_extraction(self, fixture_html, spider):
        item = ExtractPipeline().process_item(
            make_item(fixture_html("article.html")), spider
        )

        assert item.html == ""
        assert "html" not in item.to_record()

    def test_drops_item_with_no_content(self, fixture_html, spider):
        with pytest.raises(DropItem):
            ExtractPipeline().process_item(make_item(fixture_html("empty.html")), spider)

    def test_drops_item_with_no_html(self, spider):
        with pytest.raises(DropItem):
            ExtractPipeline().process_item(make_item(""), spider)

    def test_word_count_matches_markdown(self, fixture_html, spider):
        item = ExtractPipeline().process_item(
            make_item(fixture_html("article.html")), spider
        )

        assert item.word_count == len(item.markdown.split())


class TestNormaliseMarkdown:
    def test_removes_extraction_indentation(self):
        assert normalise_markdown("# Title\n        indented body") == (
            "# Title\nindented body"
        )

    def test_keeps_nested_list_indentation(self):
        assert normalise_markdown("- a\n  - b") == "- a\n  - b"

    def test_collapses_blank_line_runs(self):
        assert normalise_markdown("a\n\n\n\n\nb") == "a\n\nb"

    def test_whitespace_only_differences_hash_the_same(self):
        a = normalise_markdown("# Title\n\n\n        Body text")
        b = normalise_markdown("# Title\n\nBody text   ")
        assert content_hash(a) == content_hash(b)


class TestDedupePipeline:
    def test_passes_distinct_content(self, spider):
        pipeline = DedupePipeline()
        first = make_item(url="https://example.com/a")
        first.content_hash = content_hash("one")
        second = make_item(url="https://example.com/b")
        second.content_hash = content_hash("two")

        assert pipeline.process_item(first, spider) is first
        assert pipeline.process_item(second, spider) is second

    def test_drops_repeated_hash(self, spider):
        pipeline = DedupePipeline()
        first = make_item(url="https://example.com/a")
        first.content_hash = content_hash("same body")
        duplicate = make_item(url="https://example.com/a?utm_source=x")
        duplicate.content_hash = content_hash("same body")

        pipeline.process_item(first, spider)
        with pytest.raises(DropItem, match="Duplicate"):
            pipeline.process_item(duplicate, spider)

    def test_dedupes_two_urls_serving_identical_html(self, fixture_html, spider):
        extract, dedupe = ExtractPipeline(), DedupePipeline()
        html = fixture_html("article.html")

        first = extract.process_item(make_item(html, "https://example.com/a"), spider)
        second = extract.process_item(make_item(html, "https://example.com/b"), spider)

        dedupe.process_item(first, spider)
        with pytest.raises(DropItem):
            dedupe.process_item(second, spider)

    def test_state_is_per_instance(self, spider):
        item = make_item()
        item.content_hash = content_hash("body")

        DedupePipeline().process_item(item, spider)
        # A fresh pipeline (i.e. a new job) must not remember the previous hash.
        assert DedupePipeline().process_item(item, spider) is item


class TestJsonLinesPipeline:
    @pytest.fixture
    def open_pipeline(self, tmp_path, monkeypatch):
        """A JsonLinesPipeline writing into tmp_path, already opened."""

        def _open(spider) -> tuple[JsonLinesPipeline, object]:
            monkeypatch.setattr(
                "crawler.pipelines.get_settings",
                lambda: type(
                    "S",
                    (),
                    {"job_results_path": lambda self, site, job_id: tmp_path / "p.jsonl"},
                )(),
            )
            pipeline = JsonLinesPipeline()
            pipeline.open_spider(spider)
            return pipeline, tmp_path / "p.jsonl"

        return _open

    def test_stops_writing_at_max_pages(self, open_pipeline, spider):
        spider.max_pages = 2
        pipeline, path = open_pipeline(spider)

        for n in range(2):
            item = make_item(url=f"https://example.com/{n}")
            item.markdown = f"body {n}"
            pipeline.process_item(item, spider)

        overflow = make_item(url="https://example.com/overflow")
        overflow.markdown = "body 3"
        with pytest.raises(DropItem, match="max_pages"):
            pipeline.process_item(overflow, spider)

        pipeline.close_spider(spider)
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    def test_no_cap_when_max_pages_is_zero(self, open_pipeline, spider):
        spider.max_pages = 0
        pipeline, path = open_pipeline(spider)

        for n in range(5):
            item = make_item(url=f"https://example.com/{n}")
            item.markdown = f"body {n}"
            pipeline.process_item(item, spider)

        pipeline.close_spider(spider)
        assert len(path.read_text(encoding="utf-8").splitlines()) == 5

    def test_writes_one_json_object_per_item(self, tmp_path, monkeypatch, spider):
        pipeline = JsonLinesPipeline()
        monkeypatch.setattr(
            "crawler.pipelines.get_settings",
            lambda: type(
                "S", (), {"job_results_path": lambda self, site, job_id: tmp_path / "p.jsonl"}
            )(),
        )
        pipeline.open_spider(spider)
        item = make_item(url="https://example.com/a")
        item.markdown = "# Hello"
        pipeline.process_item(item, spider)
        pipeline.close_spider(spider)

        lines = (tmp_path / "p.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["url"] == "https://example.com/a"
        assert record["markdown"] == "# Hello"
        assert "html" not in record


class TestCsvPipeline:
    @pytest.fixture
    def csv_pipeline(self, tmp_path, monkeypatch, spider):
        from crawler.pipelines import CsvPipeline

        monkeypatch.setattr(
            "crawler.pipelines.get_settings",
            lambda: type(
                "S", (), {"job_csv_path": lambda self, site, job_id: tmp_path / "p.csv"}
            )(),
        )
        pipeline = CsvPipeline()
        pipeline.open_spider(spider)
        return pipeline, tmp_path / "p.csv"

    def test_writes_header_then_one_row_per_item(self, csv_pipeline, spider):
        import csv as csv_module
        from crawler.items import CSV_COLUMNS

        pipeline, path = csv_pipeline
        item = make_item(url="https://example.com/a")
        item.title, item.word_count, item.page_type = "A page", 12, "services"
        pipeline.process_item(item, spider)
        pipeline.close_spider(spider)

        rows = list(csv_module.DictReader(path.open(encoding="utf-8")))
        assert list(rows[0]) == list(CSV_COLUMNS)
        assert rows[0]["url"] == "https://example.com/a"
        assert rows[0]["page_type"] == "services"
        assert rows[0]["word_count"] == "12"

    def test_markdown_is_not_a_column(self, csv_pipeline, spider):
        pipeline, path = csv_pipeline
        item = make_item(url="https://example.com/a")
        item.markdown = "# Heading\n\nBody"
        pipeline.process_item(item, spider)
        pipeline.close_spider(spider)

        assert "markdown" not in path.read_text(encoding="utf-8").splitlines()[0]

    def test_newlines_in_a_cell_are_flattened(self, csv_pipeline, spider):
        pipeline, path = csv_pipeline
        item = make_item(url="https://example.com/a")
        item.title = "Line one\nLine two"
        pipeline.process_item(item, spider)
        pipeline.close_spider(spider)

        # Header + exactly one data row, i.e. the embedded newline did not split it.
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


class TestArchivePipeline:
    @pytest.mark.parametrize(
        "url",
        [
            "https://a.com/blog/tag/startups/",
            "https://a.com/blog/category/ai/",
            "https://a.com/blog/author/someone/",
            "https://a.com/portfolio-category/erp-crm/",
            "https://a.com/blog/page/2/",
            "https://a.com/blog/author/someone/page/11/",
        ],
    )
    def test_drops_taxonomy_and_pagination_listings(self, url, spider):
        from crawler.extractors import classify_page
        from crawler.pipelines import ArchivePipeline

        item = make_item(url=url)
        item.page_type = classify_page(url)
        assert item.page_type == "archive"
        with pytest.raises(DropItem, match="Archive"):
            ArchivePipeline().process_item(item, spider)

    @pytest.mark.parametrize(
        "url",
        [
            "https://a.com/blog/a-real-post/",
            "https://a.com/about-us/",
            "https://a.com/case-studies/wisdom/",
            "https://a.com/ai-development/",
        ],
    )
    def test_keeps_real_content_pages(self, url, spider):
        from crawler.extractors import classify_page
        from crawler.pipelines import ArchivePipeline

        item = make_item(url=url)
        item.page_type = classify_page(url)
        assert item.page_type != "archive"
        assert ArchivePipeline().process_item(item, spider) is item

    def test_archives_kept_when_configured(self, spider, monkeypatch):
        from crawler.pipelines import ArchivePipeline

        monkeypatch.setattr(
            "crawler.pipelines.get_settings",
            lambda: type("S", (), {"store_archive_pages": True})(),
        )
        item = make_item(url="https://a.com/blog/tag/x/")
        item.page_type = "archive"
        assert ArchivePipeline().process_item(item, spider) is item
