"""Scrapy settings.

The spider is launched as a subprocess by the ARQ worker, which passes
CLOSESPIDER_PAGECOUNT with ``-s`` because Scrapy freezes its settings before the
spider instance exists. There is deliberately no DEPTH_LIMIT: a crawl follows
every internal link to the end of the site.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402

_settings = get_settings()

BOT_NAME = "crawler"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

USER_AGENT = _settings.user_agent
ROBOTSTXT_OBEY = True

CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 0.5
DOWNLOAD_TIMEOUT = 30

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

RETRY_ENABLED = True
RETRY_TIMES = 2

HTTPCACHE_ENABLED = _settings.httpcache_enabled
HTTPCACHE_EXPIRATION_SECS = 3600
HTTPCACHE_DIR = str(BACKEND_ROOT / ".scrapy" / "httpcache")

LOG_LEVEL = _settings.scrapy_log_level

ITEM_PIPELINES = {
    "crawler.pipelines.ExtractPipeline": 100,
    "crawler.pipelines.ArchivePipeline": 150,
    "crawler.pipelines.DedupePipeline": 200,
    # JsonLines enforces the max_pages cap, so every writer after it agrees.
    "crawler.pipelines.JsonLinesPipeline": 300,
    "crawler.pipelines.CsvPipeline": 350,
    "crawler.pipelines.MongoPipeline": 400,
    "crawler.pipelines.ProgressPipeline": 500,
}

# scrapy-playwright needs the asyncio reactor. Its download handler defers to the
# stock HTTP handler unless a request carries meta={"playwright": True}, so a
# non-JS crawl never launches a browser and works without one installed.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"
