"""Tests for crawler.documents: file text extraction and the resume bookkeeping.

The crawl target used during development links no PDFs at all, so the round
trips here are what actually prove the extraction works: a real PDF and a real
DOCX are written to disk and read back.
"""

from __future__ import annotations

import json

import pytest

from crawler import documents

PDF_BODY = "Quarterly report for Acme Ltd. Revenue grew by 12 percent."


@pytest.fixture
def pdf_file(tmp_path):
    """A genuine two-page PDF, written with PyMuPDF."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "report.pdf"

    doc = pymupdf.open()
    for page_text in (PDF_BODY, "Appendix A: methodology."):
        page = doc.new_page()
        page.insert_text((72, 72), page_text)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def docx_file(tmp_path):
    """A genuine .docx with a heading, a paragraph and a table."""
    docx = pytest.importorskip("docx")
    path = tmp_path / "brief.docx"

    document = docx.Document()
    document.add_heading("Project Brief", level=1)
    document.add_paragraph("We need a crawler that extracts documents.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Phase"
    table.rows[0].cells[1].text = "Owner"
    document.save(path)
    return path


class TestPdf:
    def test_text_and_page_count_come_back(self, pdf_file):
        markdown, pages = documents.extract_pdf(pdf_file)

        assert pages == 2
        assert "Revenue grew by 12 percent" in markdown
        assert "Appendix A" in markdown

    def test_a_corrupt_pdf_yields_nothing_rather_than_raising(self, tmp_path):
        broken = tmp_path / "broken.pdf"
        broken.write_bytes(b"%PDF-1.4 this is not really a pdf")

        assert documents.extract_pdf(broken) == ("", 0)

    def test_a_missing_file_yields_nothing(self, tmp_path):
        assert documents.extract_pdf(tmp_path / "absent.pdf") == ("", 0)


class TestDocx:
    def test_headings_become_markdown_and_tables_become_rows(self, docx_file):
        markdown, pages = documents.extract_docx(docx_file)

        assert "# Project Brief" in markdown
        assert "We need a crawler" in markdown
        assert "Phase | Owner" in markdown
        # Word has no fixed pagination to report.
        assert pages == 0

    def test_a_corrupt_docx_yields_nothing_rather_than_raising(self, tmp_path):
        broken = tmp_path / "broken.docx"
        broken.write_bytes(b"not a zip archive at all")

        assert documents.extract_docx(broken) == ("", 0)


class TestDispatch:
    def test_the_extension_picks_the_extractor(self, pdf_file):
        markdown, pages = documents.extract_document(pdf_file, "pdf")

        assert pages == 2 and markdown

    def test_an_unsupported_type_is_recorded_without_text(self, tmp_path):
        sheet = tmp_path / "data.xlsx"
        sheet.write_bytes(b"PK\x03\x04")

        # xlsx/pptx are downloaded and listed, but no text is claimed for them.
        assert documents.extract_document(sheet, "xlsx") == ("", 0)

    def test_the_extension_is_matched_case_insensitively(self, pdf_file):
        assert documents.extract_document(pdf_file, "PDF")[1] == 2


class TestResumeBookkeeping:
    def test_source_urls_already_recorded_are_read_back(self, tmp_path):
        path = tmp_path / "documents.jsonl"
        path.write_text(
            json.dumps({"source_url": "https://a.com/one.pdf", "filename": "one.pdf"})
            + "\n"
            + json.dumps({"source_url": "https://a.com/two.pdf", "filename": "two.pdf"})
            + "\n",
            encoding="utf-8",
        )

        assert documents._existing_sources(path) == {
            "https://a.com/one.pdf",
            "https://a.com/two.pdf",
        }

    def test_a_ragged_final_line_is_skipped(self, tmp_path):
        path = tmp_path / "documents.jsonl"
        path.write_text(
            json.dumps({"source_url": "https://a.com/one.pdf"}) + "\n{\"partial\":",
            encoding="utf-8",
        )

        assert documents._existing_sources(path) == {"https://a.com/one.pdf"}

    def test_a_missing_file_is_an_empty_set(self, tmp_path):
        assert documents._existing_sources(tmp_path / "nope.jsonl") == set()


def test_extracted_text_is_bounded(monkeypatch, pdf_file):
    monkeypatch.setattr(documents, "MAX_DOCUMENT_CHARS", 20)

    markdown, _ = documents.extract_pdf(pdf_file)

    assert len(markdown) <= 20


def test_content_hash_is_stable():
    assert documents.content_hash("abc") == documents.content_hash("abc")
    assert documents.content_hash("abc") != documents.content_hash("abd")
