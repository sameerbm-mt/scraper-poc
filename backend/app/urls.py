"""URL helpers shared by the API, the worker and the Scrapy process.

Defined once here because the site folder on disk, the Mongo `sites._id` and
the spider's allowed_domains all have to agree on what "the site" is.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_UNSAFE_PATH_CHARS = re.compile(r"[^a-z0-9.\-]+")


def host_of(url: str) -> str:
    """Bare lowercase hostname: no credentials, no port."""
    netloc = urlparse(url).netloc or ""
    return netloc.split("@")[-1].split(":")[0].lower()


def domain_of(url: str) -> str:
    """The allowed_domains entry for a start URL ("https://www.a.com/x" -> "a.com")."""
    host = host_of(url)
    return host[4:] if host.startswith("www.") else host


def site_slug(url: str) -> str:
    """Folder/collection-safe name for a site ("https://www.a.com" -> "a.com").

    Hostnames are already safe, but a malformed URL must not be able to escape
    the data directory, so anything unexpected is replaced.
    """
    domain = _UNSAFE_PATH_CHARS.sub("_", domain_of(url)).strip("._-")
    return domain or "unknown-site"
