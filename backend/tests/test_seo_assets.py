"""Tests for crawler.seo and crawler.assets: headings, meta, links and media."""

from __future__ import annotations

import pytest
from scrapy.http import HtmlResponse

from crawler import assets, seo

PAGE = """<html lang="en-GB"><head>
<link rel="alternate" hreflang="fr" href="/fr/">
<link rel="alternate" hreflang="en" href="https://a.com/">
<link rel="alternate" hreflang="fr" href="/fr-dup/">
<meta property="og:title" content="OG Title">
<meta property="og:description" content="OG Desc">
<meta property="og:image" content="/img/hero.png">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="TW Title">
<meta name="robots" content="index, follow">
</head><body>
<h1>Hire <b>Django</b> Devs</h1><h2>Why us</h2><h3>Deep</h3><h2>Pricing</h2>
<a href="/about">About</a>
<a href="https://ext.com/x">Ext</a>
<a href="https://ext.com/x">Dup</a>
<a href="#top">Anchor</a>
<a href="mailto:a@b.com">Mail</a>
<a href="/files/spec.pdf">Spec</a>
<a href="/d/report.docx?v=2">Report</a>
<a href="/sheet.xlsx">Sheet</a>
<a href="/deck.pptx">Deck</a>
<a href="/nope.zip">Zip</a>
<img src="/img/real.jpg" alt="Real">
<img src="/img/tracking-pixel.gif" alt="">
<img src="/img/icon.png" width="24" height="24">
<img src="data:image/gif;base64,R0lGOD" alt="inline">
<img data-src="/img/lazy.jpg" alt="Lazy">
<img src="/img/wide.jpg" width="800" height="600" alt="Wide">
<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0"></iframe>
<iframe src="https://player.vimeo.com/video/123456789"></iframe>
<video><source src="/media/clip.mp4"></video>
<a href="https://youtu.be/abc123XYZ">Watch</a>
<a href="https://www.youtube.com/watch?v=shareID123">Share</a>
</body></html>"""


@pytest.fixture
def response() -> HtmlResponse:
    return HtmlResponse(url="https://a.com/p", body=PAGE.encode(), encoding="utf-8")


class TestHeadings:
    def test_h1_to_h3_are_returned_in_document_order(self, response):
        assert seo.extract_headings(response) == [
            {"level": 1, "text": "Hire Django Devs"},
            {"level": 2, "text": "Why us"},
            {"level": 3, "text": "Deep"},
            {"level": 2, "text": "Pricing"},
        ]

    def test_nested_markup_inside_a_heading_is_kept(self, response):
        assert seo.extract_headings(response)[0]["text"] == "Hire Django Devs"

    def test_headings_are_capped(self):
        body = "".join(f"<h2>H{i}</h2>" for i in range(200))
        response = HtmlResponse(
            url="https://a.com/", body=f"<html><body>{body}</body></html>".encode(),
            encoding="utf-8",
        )

        assert len(seo.extract_headings(response)) == seo.MAX_HEADINGS

    def test_an_empty_heading_is_skipped(self):
        response = HtmlResponse(
            url="https://a.com/", body=b"<html><body><h1>  </h1><h2>Real</h2></body></html>",
            encoding="utf-8",
        )

        assert seo.extract_headings(response) == [{"level": 2, "text": "Real"}]


class TestMeta:
    def test_hreflang_is_absolute_and_deduplicated_by_lang(self, response):
        assert seo.extract_hreflang(response) == [
            {"lang": "fr", "url": "https://a.com/fr/"},
            {"lang": "en", "url": "https://a.com/"},
        ]

    def test_open_graph_image_is_made_absolute(self, response):
        assert seo.extract_open_graph(response) == {
            "title": "OG Title",
            "description": "OG Desc",
            "image": "https://a.com/img/hero.png",
            "type": "website",
        }

    def test_twitter_tags_are_read(self, response):
        card = seo.extract_twitter(response)

        assert card["card"] == "summary_large_image"
        assert card["title"] == "TW Title"

    def test_twitter_tags_spelled_with_property_are_also_read(self):
        response = HtmlResponse(
            url="https://a.com/",
            body=b'<html><head><meta property="twitter:card" content="summary"></head></html>',
            encoding="utf-8",
        )

        assert seo.extract_twitter(response)["card"] == "summary"


class TestLanguage:
    def test_a_declared_lang_wins_and_is_reduced_to_two_letters(self):
        assert seo.detect_language("whatever text here", "en-GB") == "en"
        assert seo.detect_language("whatever text here", "pt_BR") == "pt"

    def test_language_is_detected_when_none_is_declared(self):
        spanish = (
            "Este es un texto en espanol que deberia ser detectado "
            "correctamente por el clasificador de idiomas."
        )

        assert seo.detect_language(spanish, "") == "es"

    def test_too_little_text_is_not_guessed_at(self):
        assert seo.detect_language("hi", "") == ""

    def test_empty_input_is_safe(self):
        assert seo.detect_language("", "") == ""


class TestLinks:
    def test_internal_links_are_counted_and_externals_listed(self, response):
        internal, external = assets.collect_links(response, ["a.com"])

        assert internal > 0
        assert {"url": "https://ext.com/x", "anchor": "Ext"} in external

    def test_an_external_link_is_listed_once(self, response):
        _, external = assets.collect_links(response, ["a.com"])

        assert [e["url"] for e in external].count("https://ext.com/x") == 1

    def test_anchors_and_mailto_are_ignored(self, response):
        _, external = assets.collect_links(response, ["a.com"])

        assert not any("mailto" in e["url"] for e in external)


class TestDocuments:
    def test_only_document_extensions_are_collected(self, response):
        found = {d["ext"] for d in assets.collect_documents(response)}

        assert found == {"pdf", "docx", "xlsx", "pptx"}

    def test_a_query_string_does_not_hide_the_extension(self, response):
        urls = [d["url"] for d in assets.collect_documents(response)]

        assert "https://a.com/d/report.docx?v=2" in urls

    def test_archives_are_not_documents(self, response):
        assert not any(".zip" in d["url"] for d in assets.collect_documents(response))


class TestImages:
    def test_content_images_are_kept_with_their_alt_text(self, response):
        srcs = {i["src"] for i in assets.collect_images(response)}

        assert "https://a.com/img/real.jpg" in srcs
        assert "https://a.com/img/wide.jpg" in srcs

    def test_tracking_pixels_and_tiny_icons_are_dropped(self, response):
        srcs = {i["src"] for i in assets.collect_images(response)}

        assert "https://a.com/img/tracking-pixel.gif" not in srcs
        assert "https://a.com/img/icon.png" not in srcs

    def test_inline_data_uris_are_dropped(self, response):
        assert not any(i["src"].startswith("data:") for i in assets.collect_images(response))

    def test_a_lazy_loaded_image_is_found_via_data_src(self, response):
        srcs = {i["src"] for i in assets.collect_images(response)}

        assert "https://a.com/img/lazy.jpg" in srcs


class TestVideos:
    def test_youtube_and_vimeo_embeds_are_identified(self, response):
        found = {(v["type"], v["video_id"]) for v in assets.collect_videos(response)}

        assert ("youtube", "dQw4w9WgXcQ") in found
        assert ("vimeo", "123456789") in found

    def test_a_short_link_and_a_watch_link_are_both_recognised(self, response):
        found = {(v["type"], v["video_id"]) for v in assets.collect_videos(response)}

        assert ("youtube", "abc123XYZ") in found
        assert ("youtube", "shareID123") in found

    def test_a_video_file_is_recorded_without_an_id(self, response):
        files = [v for v in assets.collect_videos(response) if v["type"] == "file"]

        assert files[0]["url"] == "https://a.com/media/clip.mp4"

    def test_the_same_video_embedded_twice_is_listed_once(self):
        body = (
            '<html><body>'
            '<iframe src="https://www.youtube.com/embed/SAMEID12345"></iframe>'
            '<a href="https://youtu.be/SAMEID12345">same</a>'
            "</body></html>"
        )
        response = HtmlResponse(url="https://a.com/", body=body.encode(), encoding="utf-8")

        assert len(assets.collect_videos(response)) == 1


def test_url_extension_ignores_the_query_and_missing_dots():
    assert assets.url_extension("https://a.com/f/report.DOCX?v=2") == "docx"
    assert assets.url_extension("https://a.com/no-extension") == ""
    assert assets.url_extension("https://a.com/dir.v2/page") == ""
