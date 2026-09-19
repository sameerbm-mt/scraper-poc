"""Accumulates per-page facts into one profile for the whole website.

Contacts, services and team members are scattered across the homepage, the
about page and the contact page, and each repeats what the others already said.
This merges them, keeps the first non-empty value for scalar fields, and counts
pages by type so the site document says what the crawl actually found.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


class SiteProfileBuilder:
    """Feed it every page's site_facts; ask for `build()` when the crawl ends."""

    def __init__(self, domain: str, start_url: str) -> None:
        self.domain = domain
        self.start_url = start_url

        self._identity: dict[str, str] = {}
        self._organisation: dict[str, str] = {}
        self._emails: set[str] = set()
        self._phones: set[str] = set()
        self._socials: dict[str, str] = {}
        self._services: dict[str, str] = {}
        self._team: dict[str, dict[str, str]] = {}

        self._page_types: Counter[str] = Counter()
        self._pages = 0
        self._words = 0
        self._key_pages: dict[str, str] = {}

    def add_page(self, record: dict[str, Any], facts: dict[str, Any]) -> None:
        self._pages += 1
        self._words += int(record.get("word_count") or 0)

        page_type = str(record.get("page_type") or "other")
        self._page_types[page_type] += 1
        # Remember where the about/contact/team page lives.
        if page_type in ("about", "contact", "team", "careers") and page_type not in self._key_pages:
            self._key_pages[page_type] = str(record.get("url") or "")

        if not facts:
            return

        self._merge_scalars(self._identity, facts.get("identity") or {})
        self._merge_scalars(self._organisation, facts.get("organisation") or {})

        contacts = facts.get("contacts") or {}
        self._emails.update(contacts.get("emails") or [])
        self._phones.update(contacts.get("phones") or [])
        for social in contacts.get("socials") or []:
            self._socials.setdefault(social["network"], social["url"])

        for service in facts.get("services") or []:
            self._services.setdefault(service["url"], service["name"])

        for person in facts.get("team") or []:
            key = person["name"].strip().lower()
            existing = self._team.get(key)
            # A later page may fill in a role the first one lacked.
            if existing is None or (not existing.get("role") and person.get("role")):
                self._team[key] = person

    @staticmethod
    def _merge_scalars(target: dict[str, str], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if value and not target.get(key):
                target[key] = str(value)

    def build(self) -> dict[str, Any]:
        name = (
            self._identity.get("name")
            or self._organisation.get("legal_name")
            or self.domain
        )
        return {
            "name": name,
            "start_url": self.start_url,
            "description": (
                self._identity.get("description")
                or self._organisation.get("description")
                or ""
            ),
            "logo": self._organisation.get("logo") or self._identity.get("og_image") or "",
            "favicon": self._identity.get("favicon", ""),
            "lang": self._identity.get("lang", ""),
            "address": self._organisation.get("address", ""),
            "founding_date": self._organisation.get("founding_date", ""),
            "emails": sorted(self._emails),
            "phones": sorted(self._phones),
            "socials": [
                {"network": k, "url": v} for k, v in sorted(self._socials.items())
            ],
            "services": [
                {"name": name, "url": url}
                for url, name in sorted(self._services.items(), key=lambda kv: kv[1].lower())
            ],
            "services_count": len(self._services),
            "team": list(self._team.values()),
            "team_count": len(self._team),
            "key_pages": self._key_pages,
            "page_count": self._pages,
            "total_words": self._words,
            "pages_by_type": dict(self._page_types),
        }
