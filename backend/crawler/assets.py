"""Links, images, videos and document links for one page.

The filtering here is the point. A modern page carries far more `<img>` tags
than it has images: tracking pixels, spacer GIFs, inline data: URIs and lazy
placeholders. Storing all of them buries the handful that are actually content,
so each collector applies the cheap signals available in the markup.
"""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from scrapy.http import Response

from app.urls import host_of

MAX_EXTERNAL_LINKS = 200
MAX_IMAGES = 100
MAX_VIDEOS = 25
MAX_DOCUMENTS = 100
_ANCHOR_CHARS = 200

_WS = re.compile(r"\s+")

# Document types worth downloading and extracting text from.
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({"pdf", "docx", "xlsx", "pptx"})

# Below this, an <img> with explicit dimensions is an icon, a spacer or a pixel.
MIN_IMAGE_PX = 100

# Filename/query markers of things that are not content images.
_PIXEL_HINTS = re.compile(
    r"(^|[/_\-.])(pixel|spacer|blank|tracking|beacon|1x1|transparent|clear)([/_\-.]|$)",
    re.IGNORECASE,
)


def _clean(value: str | None) -> str:
    return _WS.sub(" ", value).strip() if value else ""


def url_extension(url: str) -> str:
    """The lowercased extension of a URL's path, ignoring the query string."""
    path = urlparse(url).path.lower()
    _, dot, suffix = path.rpartition(".")
    if not dot or "/" in suffix:
        return ""
    return suffix


def _is_internal(url: str, allowed_domains: Iterable[str]) -> bool:
    host = host_of(url)
    if not host:
        return False
    return any(host == d or host.endswith(f".{d}") for d in allowed_domains)


# -- links -------------------------------------------------------------------


def collect_links(
    response: Response, allowed_domains: Iterable[str]
) -> tuple[int, list[dict[str, str]]]:
    """`(internal_count, [{url, anchor}])` — the count in, the externals listed.

    Internal links are only counted: they are already the crawl frontier, so
    listing them per page would duplicate the whole site map on every row.
    """
    domains = list(allowed_domains)
    internal = 0
    external: list[dict[str, str]] = []
    seen: set[str] = set()

    for node in response.css("a[href]"):
        href = _clean(node.attrib.get("href"))
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = response.urljoin(href)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue

        if _is_internal(absolute, domains):
            internal += 1
            continue
        if absolute in seen or len(external) >= MAX_EXTERNAL_LINKS:
            continue
        seen.add(absolute)
        anchor = _clean(" ".join(node.xpath(".//text()").getall()))
        external.append({"url": absolute, "anchor": anchor[:_ANCHOR_CHARS]})

    return internal, external


def collect_documents(
    response: Response, allowed_domains: Iterable[str] | None = None
) -> list[dict[str, str]]:
    """`[{url, ext}]` for linked pdf/docx/xlsx/pptx files."""
    documents: list[dict[str, str]] = []
    seen: set[str] = set()

    for href in response.css("a::attr(href)").getall():
        href = _clean(href)
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        absolute = response.urljoin(href).split("#")[0]
        extension = url_extension(absolute)
        if extension not in DOCUMENT_EXTENSIONS or absolute in seen:
            continue
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        seen.add(absolute)
        documents.append({"url": absolute, "ext": extension})
        if len(documents) >= MAX_DOCUMENTS:
            break
    return documents


# -- images ------------------------------------------------------------------


def _dimension(value: str | None) -> int | None:
    """`width="120"` -> 120. Percentages and `auto` carry no information."""
    text = _clean(value).removesuffix("px")
    return int(text) if text.isdigit() else None


def _is_tracking_pixel(src: str, node: Any) -> bool:
    if _PIXEL_HINTS.search(src):
        return True
    width, height = _dimension(node.attrib.get("width")), _dimension(
        node.attrib.get("height")
    )
    # Only reject on dimensions the markup states outright; an absent width
    # says nothing, and most content images omit it.
    return any(size is not None and size < MIN_IMAGE_PX for size in (width, height))


def collect_images(response: Response) -> list[dict[str, str]]:
    """`[{src, alt}]`, skipping data: URIs, tracking pixels and tiny icons."""
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    for node in response.css("img"):
        # Lazy-loaded images keep the real URL in data-src until JS runs.
        raw = ""
        for attribute in ("src", "data-src", "data-lazy-src", "data-original"):
            raw = _clean(node.attrib.get(attribute))
            if raw and not raw.startswith("data:"):
                break
        if not raw or raw.startswith("data:"):
            continue
        if _is_tracking_pixel(raw, node):
            continue

        absolute = response.urljoin(raw)
        if absolute in seen:
            continue
        seen.add(absolute)
        images.append({"src": absolute, "alt": _clean(node.attrib.get("alt"))})
        if len(images) >= MAX_IMAGES:
            break
    return images


# -- videos ------------------------------------------------------------------

_YOUTUBE_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtu.be")
_YOUTUBE_PATH_ID = re.compile(r"^/(?:embed|v|shorts|live)/([A-Za-z0-9_-]{6,})")
_VIMEO_ID = re.compile(r"/(?:video/)?(\d{6,})")


def _video_from_url(url: str) -> dict[str, str] | None:
    """Recognise a YouTube or Vimeo URL in any of its embed/share spellings."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().removeprefix("www.")

    if any(host == h or host.endswith(f".{h}") for h in _YOUTUBE_HOSTS):
        video_id = ""
        if host.endswith("youtu.be"):
            video_id = parsed.path.lstrip("/").split("/")[0]
        else:
            match = _YOUTUBE_PATH_ID.match(parsed.path)
            video_id = match.group(1) if match else ""
            if not video_id:
                # The plain watch?v=... share link.
                video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if video_id:
            return {"type": "youtube", "url": url, "video_id": video_id}
        return None

    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        match = _VIMEO_ID.search(parsed.path)
        if match:
            return {"type": "vimeo", "url": url, "video_id": match.group(1)}
    return None


def collect_videos(response: Response) -> list[dict[str, str]]:
    """`[{type, url, video_id}]` from iframes, <video> and bare share links."""
    videos: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(record: dict[str, str] | None) -> None:
        if not record:
            return
        key = f"{record['type']}:{record['video_id'] or record['url']}"
        if key in seen or len(videos) >= MAX_VIDEOS:
            return
        seen.add(key)
        videos.append(record)

    for src in response.css("iframe::attr(src), iframe::attr(data-src)").getall():
        src = _clean(src)
        if src:
            add(_video_from_url(response.urljoin(src)))

    # <video src> and <video><source src></video> are both common.
    for src in response.css("video::attr(src), video source::attr(src)").getall():
        src = _clean(src)
        if not src or src.startswith("data:"):
            continue
        absolute = response.urljoin(src)
        add({"type": "file", "url": absolute, "video_id": ""})

    # A YouTube link in the body, not embedded.
    for href in response.css("a::attr(href)").getall():
        href = _clean(href)
        if href and ("youtu" in href or "vimeo" in href):
            add(_video_from_url(response.urljoin(href)))

    return videos
