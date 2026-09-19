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
