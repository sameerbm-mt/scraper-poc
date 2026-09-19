"""Structured extraction on top of the raw page.

Trafilatura gives us the prose; this module pulls out the facts a site profile
needs — what the company is, how to contact it, what it sells, who works there.
Everything here is best-effort heuristics over real-world markup, so each
function degrades to an empty result rather than raising.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse

from scrapy.http import Response

from app.urls import host_of

# -- page classification ----------------------------------------------------

PageType = str

# Taxonomy and pagination listings. These are not pages of the site in any
# sense a person means: they repeat the same post excerpts over and over, and
# on a WordPress blog they outnumber the real content several times over.
# They are still followed (they surface posts) but not stored.
_ARCHIVE_RE = re.compile(
    r"/(tag|category|author|archives?|topics?|label)/"
    r"|/[a-z0-9-]*-category/"
    r"|/page/\d+/"
    r"|/(feed|amp)/$"
)

# Checked in order; the first pattern that matches the URL path wins.
_PAGE_TYPE_PATTERNS: tuple[tuple[PageType, re.Pattern[str]], ...] = (
    ("archive", _ARCHIVE_RE),
    ("contact", re.compile(r"/(contact|contact-us|get-in-touch|reach-us)\b")),
    ("team", re.compile(r"/(team|our-team|leadership|management|people|staff)\b")),
    ("careers", re.compile(r"/(careers?|jobs?|hiring|work-with-us|vacancies)\b")),
    ("about", re.compile(r"/(about|about-us|who-we-are|company|our-story)\b")),
    ("blog", re.compile(r"/(blogs?|news|articles?|insights|press|resources)\b")),
    ("portfolio", re.compile(r"/(portfolio|case-stud(y|ies)|our-work|projects|clients)\b")),
    ("legal", re.compile(r"/(privacy|terms|cookie|gdpr|disclaimer|refund)\b")),
    ("pricing", re.compile(r"/(pricing|plans|packages)\b")),
    (
        "services",
        re.compile(
            r"/(services?|solutions?|hire-|consulting|"
            r"[a-z0-9-]*-(development|services|solutions|consulting)"
            r"|development-[a-z0-9-]*)"
        ),
    ),
)


def classify_page(url: str, title: str = "", h1: str = "") -> PageType:
    """Bucket a page by its URL, falling back to its headings."""
    path = (urlparse(url).path or "/").lower().rstrip("/")
    if path in ("", "/index.html", "/home"):
        return "home"

    for page_type, pattern in _PAGE_TYPE_PATTERNS:
        if pattern.search(f"{path}/"):
            return page_type

    heading = f"{title} {h1}".lower()
    for page_type, keyword in (
        ("team", "our team"),
        ("about", "about us"),
        ("contact", "contact us"),
        ("services", "our services"),
    ):
        if keyword in heading:
            return page_type
    return "other"


# -- page metadata ----------------------------------------------------------


def _meta(response: Response, *selectors: str) -> str:
    for selector in selectors:
        value = response.css(selector).get()
        if value and value.strip():
            return value.strip()
    return ""


def extract_page_meta(response: Response) -> dict[str, Any]:
    """Open Graph / Twitter / canonical metadata for a single page."""
    return {
        "canonical_url": _meta(response, 'link[rel="canonical"]::attr(href)'),
        "lang": _meta(response, "html::attr(lang)"),
        "og_title": _meta(response, 'meta[property="og:title"]::attr(content)'),
        "og_description": _meta(
            response, 'meta[property="og:description"]::attr(content)'
        ),
        "og_image": _meta(response, 'meta[property="og:image"]::attr(content)'),
        "og_type": _meta(response, 'meta[property="og:type"]::attr(content)'),
        "og_site_name": _meta(response, 'meta[property="og:site_name"]::attr(content)'),
        "twitter_card": _meta(response, 'meta[name="twitter:card"]::attr(content)'),
        "robots": _meta(response, 'meta[name="robots"]::attr(content)'),
        "favicon": _meta(
            response,
            'link[rel="icon"]::attr(href)',
            'link[rel="shortcut icon"]::attr(href)',
            'link[rel="apple-touch-icon"]::attr(href)',
        ),
    }


def extract_jsonld(response: Response) -> list[dict[str, Any]]:
    """Every schema.org block on the page, flattened out of @graph wrappers."""
    blocks: list[dict[str, Any]] = []
    for raw in response.css('script[type="application/ld+json"]::text').getall():
        try:
            parsed = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for entry in parsed if isinstance(parsed, list) else [parsed]:
            if not isinstance(entry, dict):
                continue
            graph = entry.get("@graph")
            if isinstance(graph, list):
                blocks.extend(node for node in graph if isinstance(node, dict))
            else:
                blocks.append(entry)
    return blocks


# -- contacts ---------------------------------------------------------------

_SOCIAL_HOSTS: dict[str, str] = {
    "facebook.com": "facebook",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "linkedin.com": "linkedin",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "github.com": "github",
    "dribbble.com": "dribbble",
    "behance.net": "behance",
    "pinterest.com": "pinterest",
    "medium.com": "medium",
    "t.me": "telegram",
    "wa.me": "whatsapp",
}

# Trailing-dot and length guards keep tracking-pixel noise out.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]{1,64}@[a-zA-Z0-9.-]{1,180}\.[a-zA-Z]{2,12}")
_PHONE_CLEAN_RE = re.compile(r"[^\d+]")


def _normalise_phone(value: str) -> str:
    cleaned = _PHONE_CLEAN_RE.sub("", value)
    if cleaned.count("+") > 1:
        cleaned = "+" + cleaned.replace("+", "")
    digits = cleaned.lstrip("+")
    return cleaned if 7 <= len(digits) <= 15 else ""


def _dedupe_phones(phones: set[str]) -> list[str]:
    """Collapse the same number written with and without its "+".

    A site that links both tel:+919737874367 and tel:919737874367 means one
    phone, not two; the international form wins.
    """
    best: dict[str, str] = {}
    for phone in phones:
        digits = phone.lstrip("+")
        if digits not in best or phone.startswith("+"):
            best[digits] = phone
    return sorted(best.values())


def extract_contacts(response: Response) -> dict[str, list[str]]:
    """Emails, phones and social profiles, from hrefs first then page text."""
    emails: set[str] = set()
    phones: set[str] = set()
    socials: dict[str, str] = {}

    for href in response.css("a::attr(href)").getall():
        href = (href or "").strip()
        lowered = href.lower()
        if lowered.startswith("mailto:"):
            address = href[7:].split("?")[0].strip().lower()
            if _EMAIL_RE.fullmatch(address):
                emails.add(address)
        elif lowered.startswith("tel:"):
            phone = _normalise_phone(href[4:])
            if phone:
                phones.add(phone)
        elif lowered.startswith(("http://", "https://")):
            host = host_of(href)
            host = host[4:] if host.startswith("www.") else host
            network = _SOCIAL_HOSTS.get(host)
            # Keep the first profile per network and skip bare share links.
            if network and network not in socials and len(urlparse(href).path) > 1:
                socials[network] = href.split("?")[0]

    # Addresses written as plain text in the footer never appear in an href.
    for match in _EMAIL_RE.findall(" ".join(response.css("body *::text").getall())):
        candidate = match.lower()
        if not candidate.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            emails.add(candidate)

    return {
        "emails": sorted(emails),
        "phones": _dedupe_phones(phones),
        "socials": [{"network": k, "url": v} for k, v in sorted(socials.items())],
    }


# -- services ---------------------------------------------------------------

_SERVICE_STOPWORDS = frozenset(
    {
        "read more", "learn more", "view more", "see all", "know more",
        "get started", "contact us", "click here", "explore", "view all",
    }
)


def extract_service_links(response: Response, domain: str) -> list[dict[str, str]]:
    """Internal links whose URL looks like a service or solution page.

    Anchor text is the service name; the nav and footer repeat these links, so
    the first readable label for a URL wins.
    """
    services: dict[str, str] = {}
    for anchor in response.css("a"):
        href = (anchor.attrib.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = response.urljoin(href).split("#")[0]
        host = host_of(url)
        if not (host == domain or host.endswith(f".{domain}")):
            continue
        if classify_page(url) != "services":
            continue

        label = " ".join(" ".join(anchor.css("::text").getall()).split())
        if not label or label.lower() in _SERVICE_STOPWORDS or len(label) > 90:
            continue
        services.setdefault(url.rstrip("/"), label)

    return [{"name": name, "url": url} for url, name in sorted(services.items())]


# -- team -------------------------------------------------------------------

# Two to four capitalised words: "Jane Doe", "Jan van Dijk", "Mary-Ann O'Neil".
_NAME_RE = re.compile(
    r"^[A-Z][a-z'’\-]{1,20}(?: (?:van|von|de|del|da|di|bin|al)?\s?[A-Z][a-z'’\-]{1,20}){1,3}$"
)
_ROLE_HINTS = (
    "ceo", "cto", "coo", "cfo", "founder", "co-founder", "director", "president",
    "head", "lead", "manager", "engineer", "developer", "designer", "architect",
    "officer", "vp", "vice president", "partner", "consultant", "analyst",
    "specialist", "strategist", "marketer", "chief",
)
_TEAM_CONTAINER_RE = re.compile(
    r"(team|member|founder|leader|staff|people|employee|profile|person|bio)", re.I
)


def _looks_like_name(value: str) -> bool:
    value = " ".join(value.split())
    return bool(value) and len(value) <= 60 and bool(_NAME_RE.match(value))


def _looks_like_role(value: str) -> bool:
    lowered = " ".join(value.split()).lower()
    return bool(lowered) and len(lowered) <= 80 and any(h in lowered for h in _ROLE_HINTS)


def _team_from_jsonld(blocks: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    for node in blocks:
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Person" not in [t for t in types if isinstance(t, str)]:
            continue
        name = str(node.get("name") or "").strip()
        if not name:
            continue
        image = node.get("image")
        if isinstance(image, dict):
            image = image.get("url")
        people.append(
            {
                "name": name,
                "role": str(node.get("jobTitle") or "").strip(),
                "image": str(image or "").strip(),
                "source": "jsonld",
            }
        )
    return people


def _team_from_markup(response: Response) -> list[dict[str, str]]:
    """Look for repeated person cards: a name heading plus a role line."""
    people: list[dict[str, str]] = []
    for container in response.css(
        '[class*="team"], [class*="member"], [class*="founder"], '
        '[class*="leader"], [class*="staff"], [class*="people"]'
    ):
        class_attr = container.attrib.get("class", "")
        if not _TEAM_CONTAINER_RE.search(class_attr):
            continue

        texts = [
            " ".join(t.split())
            for t in container.css("h2::text, h3::text, h4::text, h5::text, h6::text, "
                                   "strong::text, b::text, span::text, p::text, a::text").getall()
            if t and t.strip()
        ]
        name = next((t for t in texts if _looks_like_name(t)), "")
        if not name:
            continue
        # The role usually sits directly after the name in document order.
        after = texts[texts.index(name) + 1 :]
        role = next((t for t in after if _looks_like_role(t)), "")
        image = container.css("img::attr(src), img::attr(data-src)").get() or ""
        people.append(
            {
                "name": name,
                "role": role,
                "image": response.urljoin(image) if image else "",
                "source": "markup",
            }
        )
    return people


def extract_team(response: Response, jsonld: Iterable[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Team members on this page. JSON-LD is trusted over markup heuristics."""
    people = _team_from_jsonld(jsonld if jsonld is not None else extract_jsonld(response))
    people.extend(_team_from_markup(response))

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for person in people:
        key = person["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(person)
    return unique


# -- organisation -----------------------------------------------------------


def extract_organisation(jsonld: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Company facts from a schema.org Organization / LocalBusiness block."""
    for node in jsonld:
        types = node.get("@type")
        types = [t for t in (types if isinstance(types, list) else [types]) if isinstance(t, str)]
        if not any(t in ("Organization", "LocalBusiness", "Corporation") for t in types):
            continue

        address = node.get("address")
        if isinstance(address, dict):
            address = ", ".join(
                str(address[k])
                for k in (
                    "streetAddress", "addressLocality", "addressRegion",
                    "postalCode", "addressCountry",
                )
                if address.get(k)
            )
        logo = node.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")

        return {
            "legal_name": str(node.get("name") or "").strip(),
            "description": str(node.get("description") or "").strip(),
            "logo": str(logo or "").strip(),
            "address": str(address or "").strip(),
            "founding_date": str(node.get("foundingDate") or "").strip(),
        }
    return {}
