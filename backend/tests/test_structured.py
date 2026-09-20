"""Tests for crawler.structured: JSON-LD, schema types, FAQs, products, addresses."""

from __future__ import annotations

import json

from crawler import structured

BASE = "https://example.com/p"


def page(*blocks: str) -> str:
    scripts = "\n".join(
        f'<script type="application/ld+json">{block}</script>' for block in blocks
    )
    return f"<html><head>{scripts}</head><body>x</body></html>"


def ld(payload: dict | list) -> str:
    return json.dumps(payload)


FAQ_GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "What is it?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": "<p>A <b>POC</b>&nbsp;crawler.</p>",
                    },
                },
                {
                    "@type": "Question",
                    "name": "Cost?",
                    "acceptedAnswer": {"@type": "Answer", "text": "Free"},
                },
            ],
        }
    ],
}


class TestJsonLd:
    def test_objects_are_flattened_out_of_graph_and_main_entity(self):
        objects = structured.extract_jsonld_objects(page(ld(FAQ_GRAPH)), BASE)
        types = structured.schema_types(objects)

        assert "FAQPage" in types
        assert "Question" in types

    def test_a_type_given_as_a_url_is_reduced_to_its_name(self):
        html = page(ld({"@type": "https://schema.org/Product", "name": "W"}))

        assert structured.schema_types(
            structured.extract_jsonld_objects(html, BASE)
        ) == ["Product"]

    def test_a_list_valued_type_yields_every_name(self):
        html = page(ld({"@type": ["Product", "Offer"], "name": "W"}))

        assert structured.schema_types(
            structured.extract_jsonld_objects(html, BASE)
        ) == ["Product", "Offer"]

    def test_objects_are_capped(self):
        many = [{"@type": "Thing", "name": str(i)} for i in range(200)]

        objects = structured.extract_jsonld_objects(page(ld(many)), BASE)

        assert len(objects) == structured.MAX_JSONLD_OBJECTS

    def test_a_self_referencing_graph_terminates(self):
        node: dict = {"@type": "Thing", "name": "loop"}
        node["mainEntity"] = node  # cycle

        # Depth-bounded rather than raising RecursionError.
        assert list(structured.flatten(node))


class TestMalformedMarkup:
    def test_no_json_ld_at_all_is_empty(self):
        assert structured.extract_jsonld_objects("<html><body>hi</body></html>", BASE) == []

    def test_empty_html_is_empty(self):
        assert structured.extract_jsonld_objects("", BASE) == []

    def test_unparseable_json_is_empty_rather_than_raising(self):
        assert structured.extract_jsonld_objects(page("{{{ not json"), BASE) == []

    def test_a_malformed_block_does_not_discard_the_valid_ones(self):
        """extruct treats the page as all-or-nothing; the salvage path must not.

        This is the case that matters in the wild: one broken analytics blob
        alongside perfectly good Product markup.
        """
        html = page(ld(FAQ_GRAPH), "{ broken json ,,, }")

        types = structured.schema_types(structured.extract_jsonld_objects(html, BASE))

        assert "FAQPage" in types

    def test_a_trailing_comma_is_repaired(self):
        html = page('{"@type": "Product", "name": "Widget",}', "{oops")

        products = structured.extract_products(
            structured.extract_jsonld_objects(html, BASE)
        )

        assert [p["name"] for p in products] == ["Widget"]


class TestFaqs:
    def test_question_and_answer_are_extracted_without_markup(self):
        faqs = structured.extract_faqs(
            structured.extract_jsonld_objects(page(ld(FAQ_GRAPH)), BASE)
        )

        assert faqs == [
            {"question": "What is it?", "answer": "A POC crawler."},
            {"question": "Cost?", "answer": "Free"},
        ]

    def test_a_question_without_an_answer_is_skipped(self):
        html = page(ld({"@type": "Question", "name": "Unanswered?"}))

        assert structured.extract_faqs(structured.extract_jsonld_objects(html, BASE)) == []

    def test_repeated_questions_are_deduplicated(self):
        one = {
            "@type": "Question",
            "name": "Same?",
            "acceptedAnswer": {"@type": "Answer", "text": "Yes"},
        }
        html = page(ld([one, dict(one)]))

        assert len(structured.extract_faqs(structured.extract_jsonld_objects(html, BASE))) == 1

    def test_a_long_answer_is_bounded(self):
        html = page(
            ld(
                {
                    "@type": "Question",
                    "name": "Long?",
                    "acceptedAnswer": {"@type": "Answer", "text": "x" * 50_000},
                }
            )
        )

        faqs = structured.extract_faqs(structured.extract_jsonld_objects(html, BASE))

        assert len(faqs[0]["answer"]) == structured.MAX_ANSWER_CHARS


class TestProducts:
    def test_offer_fields_are_flattened(self):
        html = page(
            ld(
                {
                    "@type": "Product",
                    "name": "Widget",
                    "sku": "W1",
                    "offers": {
                        "@type": "Offer",
                        "price": "9.99",
                        "priceCurrency": "USD",
                        "availability": "https://schema.org/InStock",
                    },
                }
            )
        )

        assert structured.extract_products(
            structured.extract_jsonld_objects(html, BASE)
        ) == [
            {
                "name": "Widget",
                "sku": "W1",
                "price": "9.99",
                "currency": "USD",
                "availability": "InStock",
            }
        ]

    def test_an_aggregate_offer_uses_its_low_price(self):
        html = page(
            ld(
                {
                    "@type": "Product",
                    "name": "Bundle",
                    "offers": {
                        "@type": "AggregateOffer",
                        "lowPrice": "5.00",
                        "priceCurrency": "EUR",
                    },
                }
            )
        )

        product = structured.extract_products(
            structured.extract_jsonld_objects(html, BASE)
        )[0]

        assert (product["price"], product["currency"]) == ("5.00", "EUR")

    def test_a_list_of_offers_takes_the_first(self):
        html = page(
            ld(
                {
                    "@type": "Product",
                    "name": "Multi",
                    "offers": [
                        {"@type": "Offer", "price": "1.00", "priceCurrency": "GBP"},
                        {"@type": "Offer", "price": "2.00", "priceCurrency": "GBP"},
                    ],
                }
            )
        )

        assert structured.extract_products(
            structured.extract_jsonld_objects(html, BASE)
        )[0]["price"] == "1.00"

    def test_a_product_without_a_name_is_skipped(self):
        html = page(ld({"@type": "Product", "sku": "X"}))

        assert structured.extract_products(structured.extract_jsonld_objects(html, BASE)) == []


class TestAddresses:
    def test_a_postal_address_is_joined_in_order(self):
        html = page(
            ld(
                {
                    "@type": "Organization",
                    "name": "Acme",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "1 Main St",
                        "addressLocality": "Pune",
                        "postalCode": "411001",
                        "addressCountry": "IN",
                    },
                }
            )
        )

        assert structured.extract_addresses(
            structured.extract_jsonld_objects(html, BASE)
        ) == ["1 Main St, Pune, 411001, IN"]

    def test_the_same_address_is_reported_once(self):
        address = {
            "@type": "PostalAddress",
            "streetAddress": "1 Main St",
            "addressLocality": "Pune",
        }
        html = page(
            ld(
                [
                    {"@type": "Organization", "name": "A", "address": dict(address)},
                    {"@type": "LocalBusiness", "name": "B", "address": dict(address)},
                ]
            )
        )

        assert len(structured.extract_addresses(structured.extract_jsonld_objects(html, BASE))) == 1

    def test_prose_that_looks_like_an_address_is_not_picked_up(self):
        """Addresses come from declared PostalAddress only — never regex."""
        html = "<html><body>Visit us at 1 Main St, Pune 411001, India.</body></html>"

        assert structured.summarise(html, BASE)["jsonld_addresses"] == []


def test_summarise_returns_every_section():
    result = structured.summarise(page(ld(FAQ_GRAPH)), BASE)

    assert set(result) == {"jsonld", "schema_types", "faqs", "products", "jsonld_addresses"}
    assert result["faqs"]
