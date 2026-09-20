"""JSON-LD and friends, via extruct.

Real-world JSON-LD is frequently malformed: trailing commas, HTML inside text
nodes, `@graph` nesting three levels deep, `offers` that are sometimes an object
and sometimes a list. Nothing here raises — a page with broken markup yields an
empty result and the crawl carries on.

The interesting output is not the raw blobs but what we can name: `schema_types`
says what a page *is*, and FAQPage/Product are lifted into flat records because
those are the two shapes a chatbot can answer from directly.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

import extruct

logger = logging.getLogger(__name__)

# Bounds. A handful of sites embed their entire product catalogue in one blob;
# storing that per page would dwarf the actual content.
MAX_JSONLD_OBJECTS = 50
MAX_FAQS = 100
MAX_PRODUCTS = 50
MAX_ANSWER_CHARS = 4000

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(value: Any) -> str:
    """JSON-LD text nodes routinely carry HTML. Flatten to a single-line string."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_clean(entry) for entry in value if entry).strip()
    if isinstance(value, dict):
        # {"@value": "..."} and {"name": "..."} both appear in the wild.
        for key in ("@value", "name", "text", "description"):
            if key in value:
                return _clean(value[key])
        return ""
    text = _TAG.sub(" ", str(value))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS.sub(" ", text).strip()


def _types_of(node: dict[str, Any]) -> list[str]:
    """`@type` is a string or a list, and is sometimes a full schema.org URL."""
    raw = node.get("@type") or node.get("type")
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        name = value.rsplit("/", 1)[-1].rsplit("#", 1)[-1].strip()
        if name:
            out.append(name)
    return out


def flatten(nodes: Any, _depth: int = 0) -> Iterator[dict[str, Any]]:
    """Walk `@graph` and nested lists, yielding every typed object once.

    Depth-bounded: a self-referencing graph would otherwise recurse forever.
    """
    if _depth > 6:
        return
    if isinstance(nodes, list):
        for entry in nodes:
            yield from flatten(entry, _depth + 1)
        return
    if not isinstance(nodes, dict):
        return

    graph = nodes.get("@graph")
    if graph is not None:
        yield from flatten(graph, _depth + 1)

    if _types_of(nodes):
        yield nodes

    # Types worth surfacing hide inside these properties rather than in @graph.
    for key in ("mainEntity", "mainEntityOfPage", "itemListElement", "hasPart", "about"):
        nested = nodes.get(key)
        if isinstance(nested, (list, dict)):
            yield from flatten(nested, _depth + 1)


_LD_SCRIPT = re.compile(
    r'<script[^>]+type\s*=\s*["\']?application/ld\+json["\']?[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
# `{"a": 1,}` and `[1,2,,]` — by far the most common breakage, and safe to repair
# because a comma before a closing brace is never valid JSON.
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _salvage(html: str) -> list[Any]:
    """Parse each ld+json block on its own, so one broken blob costs only itself.

    extruct treats the page as all-or-nothing: with `errors="ignore"` a single
    malformed script makes it return no JSON-LD at all, which on a real site
    throws away perfectly good Product and FAQPage markup. This is the fallback
    for exactly that case.
    """
    found: list[Any] = []
    for raw in _LD_SCRIPT.findall(html):
        text = raw.strip()
        if not text:
            continue
        for candidate in (text, _TRAILING_COMMA.sub(r"\1", text)):
            try:
                found.append(json.loads(candidate))
                break
            except ValueError:
                continue
    return found


def extract_jsonld_objects(html: str, base_url: str) -> list[dict[str, Any]]:
    """Every JSON-LD object on the page, flattened. Never raises."""
    if not html:
        return []
    raw_nodes: list[Any] = []
    try:
        data = extruct.extract(
            html,
            base_url=base_url,
            syntaxes=["json-ld"],
            uniform=True,
            errors="ignore",
        )
        raw_nodes = list(data.get("json-ld") or [])
    except Exception as exc:  # noqa: BLE001 - malformed markup must not stop a crawl
        logger.debug("JSON-LD extraction failed for %s: %s", base_url, exc)

    if not raw_nodes:
        raw_nodes = _salvage(html)

    seen: set[int] = set()
    objects: list[dict[str, Any]] = []
    for node in flatten(raw_nodes):
        # Same object reached via two paths (e.g. @graph and mainEntity).
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        objects.append(node)
        if len(objects) >= MAX_JSONLD_OBJECTS:
            break
    return objects


def schema_types(objects: list[dict[str, Any]]) -> list[str]:
    """The distinct schema.org types on the page, in first-seen order."""
    out: list[str] = []
    for node in objects:
        for name in _types_of(node):
            if name not in out:
                out.append(name)
    return out


def _has_type(node: dict[str, Any], wanted: str) -> bool:
    return wanted in _types_of(node)


# -- FAQ ---------------------------------------------------------------------


def extract_faqs(objects: list[dict[str, Any]]) -> list[dict[str, str]]:
    """`[{question, answer}]` from FAQPage / QAPage blocks.

    Questions are also picked up when they appear loose in the graph rather than
    under a FAQPage's mainEntity, which several CMS plugins emit.
    """
    faqs: list[dict[str, str]] = []
    seen: set[str] = set()

    for node in objects:
        if not _has_type(node, "Question"):
            continue
        question = _clean(node.get("name") or node.get("text"))
        answer = _answer_text(node)
        if not question or not answer:
            continue
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        faqs.append({"question": question, "answer": answer[:MAX_ANSWER_CHARS]})
        if len(faqs) >= MAX_FAQS:
            break
    return faqs


def _answer_text(question: dict[str, Any]) -> str:
    answer = question.get("acceptedAnswer") or question.get("suggestedAnswer")
    if isinstance(answer, list):
        answer = answer[0] if answer else None
    if isinstance(answer, dict):
        return _clean(answer.get("text") or answer.get("name"))
    return _clean(answer)


# -- Product -----------------------------------------------------------------


def extract_products(objects: list[dict[str, Any]]) -> list[dict[str, str]]:
    """`[{name, sku, price, currency, availability}]` from Product blocks."""
    products: list[dict[str, str]] = []
    seen: set[str] = set()

    for node in objects:
        if not _has_type(node, "Product"):
            continue
        name = _clean(node.get("name"))
        if not name:
            continue
        offer = _first_offer(node.get("offers"))
        record = {
            "name": name,
            "sku": _clean(node.get("sku") or node.get("mpn") or node.get("productID")),
            "price": _clean(offer.get("price") or offer.get("lowPrice")),
            "currency": _clean(offer.get("priceCurrency")),
            # "https://schema.org/InStock" -> "InStock"
            "availability": _clean(offer.get("availability")).rsplit("/", 1)[-1],
        }
        key = f"{record['name']}|{record['sku']}".lower()
        if key in seen:
            continue
        seen.add(key)
        products.append(record)
        if len(products) >= MAX_PRODUCTS:
            break
    return products


def _first_offer(offers: Any) -> dict[str, Any]:
    """`offers` is an Offer, an AggregateOffer, or a list of either."""
    if isinstance(offers, list):
        for entry in offers:
            found = _first_offer(entry)
            if found:
                return found
        return {}
    if not isinstance(offers, dict):
        return {}
    # An AggregateOffer wraps the real offers and carries lowPrice itself.
    nested = offers.get("offers")
    if nested and not offers.get("price"):
        found = _first_offer(nested)
        if found:
            return {**offers, **found}
    return offers


# -- Addresses ---------------------------------------------------------------

_ADDRESS_PARTS = (
    "streetAddress",
    "addressLocality",
    "addressRegion",
    "postalCode",
    "addressCountry",
)


def extract_addresses(objects: list[dict[str, Any]]) -> list[str]:
    """Postal addresses, from JSON-LD PostalAddress only.

    Deliberately not regex over the page text: address-shaped regexes produce a
    stream of false positives, and this is personal data we would then be
    storing. A declared PostalAddress is the site telling us outright.
    """
    found: list[str] = []
    for node in objects:
        for address in _postal_nodes(node):
            parts = [_clean(address.get(part)) for part in _ADDRESS_PARTS]
            text = ", ".join(part for part in parts if part)
            if text and text not in found:
                found.append(text)
    return found


def _postal_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if _has_type(node, "PostalAddress"):
        yield node
    address = node.get("address")
    if isinstance(address, dict):
        yield address
    elif isinstance(address, list):
        for entry in address:
            if isinstance(entry, dict):
                yield entry


def summarise(html: str, base_url: str) -> dict[str, Any]:
    """Everything this module knows about one page, in one pass."""
    objects = extract_jsonld_objects(html, base_url)
    return {
        "jsonld": objects,
        "schema_types": schema_types(objects),
        "faqs": extract_faqs(objects),
        "products": extract_products(objects),
        "jsonld_addresses": extract_addresses(objects),
    }
