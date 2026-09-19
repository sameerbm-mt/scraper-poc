"""Shared test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    """Read a fixture HTML file by name."""

    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def spider():
    """A minimal stand-in for the spider argument pipelines receive."""

    class _Spider:
        name = "site"
        job_id = "test-job"
        site = "example.com"
        start_url = "https://example.com/"
        max_pages = 0
        use_js = False

    return _Spider()


@pytest.fixture
def blind_trafilatura(monkeypatch):
    """Force both Trafilatura strategies to return nothing.

    Reproduces the observed failure where `trafilatura.extract` returns None on
    a page whose article is plainly in the HTML, without depending on the exact
    markup that trips it.
    """
    import crawler.content as content

    blinded = tuple(
        (name, (lambda html, url: "") if name.startswith("trafilatura") else fn)
        for name, fn in content.STRATEGIES
    )
    monkeypatch.setattr(content, "STRATEGIES", blinded)


@pytest.fixture
def make_crawl(tmp_path):
    """Lay out ``tmp_path/{site}/{job_id}`` the way the pipelines write it.

    ``pages`` is a list of ``(url, crawled_at)``. Returns the job folder.
    """
    import csv
    import json

    def _make(site, job_id, pages, *, with_csv=True):
        folder = tmp_path / site / job_id
        folder.mkdir(parents=True)
        records = [
            {
                "url": url,
                "status_code": 200,
                "depth": index,
                "title": f"Page {index}",
                "word_count": 100 + index,
                "content_hash": f"hash{index}",
                "crawled_at": crawled_at,
                "markdown": f"# Page {index}\n\nBody text {index}.",
            }
            for index, (url, crawled_at) in enumerate(pages)
        ]
        with (folder / "pages.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        if with_csv:
            with (folder / "pages.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["url", "depth", "crawled_at"], extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(records)
        return folder

    return _make
