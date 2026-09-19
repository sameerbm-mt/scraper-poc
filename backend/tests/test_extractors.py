"""Tests for the structured extractors and the site profile builder."""

from __future__ import annotations

import pytest
from scrapy.http import HtmlResponse, Request

from crawler.extractors import (
    classify_page,
    extract_contacts,
    extract_jsonld,
    extract_organisation,
    extract_page_meta,
    extract_service_links,
    extract_team,
)
from crawler.site_profile import SiteProfileBuilder


@pytest.fixture
def team_response(fixture_html):
    body = fixture_html("team.html").encode("utf-8")
    url = "https://example.com/team/"
    return HtmlResponse(
        url=url, body=body, encoding="utf-8", request=Request(url),
        headers={"Content-Type": "text/html"},
    )


class TestClassifyPage:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://a.com/", "home"),
            ("https://a.com", "home"),
            ("https://a.com/about-us/", "about"),
            ("https://a.com/our-team/", "team"),
            ("https://a.com/contact-us/", "contact"),
            ("https://a.com/careers/", "careers"),
            ("https://a.com/blogs/a-post/", "blog"),
            ("https://a.com/portfolio/case/", "portfolio"),
            ("https://a.com/privacy-policy/", "legal"),
            ("https://a.com/pricing/", "pricing"),
            ("https://a.com/services/", "services"),
            ("https://a.com/ai-development-services/", "services"),
            ("https://a.com/hire-react-developers/", "services"),
            ("https://a.com/data-engineering-services/", "services"),
            ("https://a.com/something-else/", "other"),
        ],
    )
    def test_classifies_by_url(self, url, expected):
        assert classify_page(url) == expected

    def test_falls_back_to_headings(self):
        assert classify_page("https://a.com/x/", "Our Team", "") == "team"
        assert classify_page("https://a.com/x/", "", "About Us") == "about"

    def test_url_wins_over_heading(self):
        assert classify_page("https://a.com/blogs/p/", "Our Team") == "blog"


class TestExtractContacts:
    def test_finds_emails_phones_and_socials(self, team_response):
        contacts = extract_contacts(team_response)

        assert contacts["emails"] == ["hello@example.com"]
        assert contacts["phones"] == ["+441134960000"]
        assert {s["network"] for s in contacts["socials"]} == {"linkedin", "twitter"}

    def test_social_network_is_recorded_once(self, team_response):
        networks = [s["network"] for s in extract_contacts(team_response)["socials"]]
        assert len(networks) == len(set(networks))

    def test_rejects_implausible_phone_numbers(self):
        url = "https://a.com/"
        body = b'<a href="tel:123">x</a><a href="tel:+441134960000">y</a>'
        response = HtmlResponse(url=url, body=body, encoding="utf-8", request=Request(url))

        assert extract_contacts(response)["phones"] == ["+441134960000"]


class TestExtractServiceLinks:
    def test_keeps_internal_service_urls_with_anchor_text(self, team_response):
        services = extract_service_links(team_response, "example.com")

        assert {s["name"] for s in services} == {"AI Development", "React Developers"}

    def test_excludes_blog_and_external_links(self, team_response):
        urls = {s["url"] for s in extract_service_links(team_response, "example.com")}

        assert not any("/blogs/" in url for url in urls)
        assert all(url.startswith("https://example.com/") for url in urls)


class TestExtractTeam:
    def test_reads_person_from_jsonld(self, team_response):
        people = extract_team(team_response)
        priya = next(p for p in people if p["name"] == "Priya Raman")

        assert priya["role"] == "Chief Executive Officer"
        assert priya["source"] == "jsonld"

    def test_reads_person_cards_from_markup(self, team_response):
        people = {p["name"]: p for p in extract_team(team_response)}

        assert people["Anna Novak"]["role"] == "Head of Engineering"
        assert people["Tom Baker"]["role"] == "Lead Designer"

    def test_resolves_relative_member_images(self, team_response):
        anna = next(p for p in extract_team(team_response) if p["name"] == "Anna Novak")
        assert anna["image"] == "https://example.com/img/anna.jpg"

    def test_ignores_headings_that_are_not_names(self, team_response):
        names = [p["name"] for p in extract_team(team_response)]
        assert not any(len(name) > 60 for name in names)
        assert len(names) == 3

    def test_no_duplicate_people(self, team_response):
        names = [p["name"].lower() for p in extract_team(team_response)]
        assert len(names) == len(set(names))

    def test_empty_on_a_page_with_no_people(self, fixture_html):
        url = "https://example.com/hub"
        response = HtmlResponse(
            url=url, body=fixture_html("links.html").encode("utf-8"),
            encoding="utf-8", request=Request(url),
        )
        assert extract_team(response) == []


class TestExtractOrganisation:
    def test_reads_schema_org_organisation(self, team_response):
        org = extract_organisation(extract_jsonld(team_response))

        assert org["legal_name"] == "Example Ltd"
        assert org["address"] == "1 High St, Leeds, UK"
        assert org["founding_date"] == "2014"
        assert org["logo"] == "https://example.com/logo.png"

    def test_empty_without_an_organisation_block(self):
        assert extract_organisation([]) == {}


class TestExtractPageMeta:
    def test_reads_lang_and_description(self, team_response):
        meta = extract_page_meta(team_response)
        assert meta["lang"] == "en"

    def test_malformed_jsonld_is_skipped(self):
        url = "https://a.com/"
        body = b'<script type="application/ld+json">{not json}</script>'
        response = HtmlResponse(url=url, body=body, encoding="utf-8", request=Request(url))
        assert extract_jsonld(response) == []


class TestSiteProfileBuilder:
    def _facts(self, **overrides):
        base = {
            "contacts": {"emails": [], "phones": [], "socials": []},
            "services": [],
            "team": [],
            "organisation": {},
        }
        base.update(overrides)
        return base

    def test_counts_pages_words_and_types(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        builder.add_page({"page_type": "home", "word_count": 100, "url": "https://a.com/"}, {})
        builder.add_page({"page_type": "blog", "word_count": 50, "url": "https://a.com/b"}, {})
        profile = builder.build()

        assert profile["page_count"] == 2
        assert profile["total_words"] == 150
        assert profile["pages_by_type"] == {"home": 1, "blog": 1}

    def test_unions_contacts_across_pages(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        builder.add_page(
            {"page_type": "home", "word_count": 1, "url": "https://a.com/"},
            self._facts(contacts={"emails": ["a@a.com"], "phones": ["+1"], "socials": []}),
        )
        builder.add_page(
            {"page_type": "contact", "word_count": 1, "url": "https://a.com/contact-us/"},
            self._facts(contacts={"emails": ["b@a.com", "a@a.com"], "phones": [], "socials": []}),
        )
        profile = builder.build()

        assert profile["emails"] == ["a@a.com", "b@a.com"]

    def test_later_page_fills_in_a_missing_role(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        builder.add_page(
            {"page_type": "home", "word_count": 1, "url": "https://a.com/"},
            self._facts(team=[{"name": "Jane Doe", "role": "", "image": "", "source": "markup"}]),
        )
        builder.add_page(
            {"page_type": "team", "word_count": 1, "url": "https://a.com/team/"},
            self._facts(team=[{"name": "Jane Doe", "role": "CTO", "image": "", "source": "jsonld"}]),
        )
        profile = builder.build()

        assert profile["team_count"] == 1
        assert profile["team"][0]["role"] == "CTO"

    def test_records_where_key_pages_live(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        builder.add_page({"page_type": "about", "word_count": 1, "url": "https://a.com/about-us/"}, {})
        builder.add_page({"page_type": "contact", "word_count": 1, "url": "https://a.com/contact-us/"}, {})

        assert builder.build()["key_pages"] == {
            "about": "https://a.com/about-us/",
            "contact": "https://a.com/contact-us/",
        }

    def test_services_are_deduped_by_url(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        service = {"name": "AI", "url": "https://a.com/ai-services"}
        for _ in range(3):
            builder.add_page(
                {"page_type": "home", "word_count": 1, "url": "https://a.com/"},
                self._facts(services=[service]),
            )

        assert builder.build()["services_count"] == 1

    def test_falls_back_to_the_domain_for_a_name(self):
        assert SiteProfileBuilder("a.com", "https://a.com").build()["name"] == "a.com"

    def test_identity_name_wins_over_organisation(self):
        builder = SiteProfileBuilder("a.com", "https://a.com")
        builder.add_page(
            {"page_type": "home", "word_count": 1, "url": "https://a.com/"},
            {**self._facts(organisation={"legal_name": "A Ltd"}), "identity": {"name": "A"}},
        )
        assert builder.build()["name"] == "A"


class TestPhoneNormalisation:
    def test_same_number_with_and_without_plus_collapses(self):
        from crawler.extractors import _dedupe_phones

        assert _dedupe_phones({"+919737874367", "919737874367"}) == ["+919737874367"]

    def test_international_form_is_preferred(self):
        from crawler.extractors import _dedupe_phones

        assert _dedupe_phones({"919737874367", "+919737874367"})[0].startswith("+")

    def test_distinct_numbers_are_kept(self):
        from crawler.extractors import _dedupe_phones

        assert len(_dedupe_phones({"+919737874367", "+12242102056"})) == 2
