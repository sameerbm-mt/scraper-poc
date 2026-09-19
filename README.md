# Website scraping POC

Crawls a site, extracts every page as markdown, builds a profile of the company
behind it, and serves the results through an API and a small web UI. This is the
crawling slice of `myra-ai-engine` only — there are no embeddings, no Qdrant, no
RAG and no auth. The Next.js app talks to FastAPI directly.

```
Next.js (:3000)  ──HTTP──▶  FastAPI (:8000)  ──enqueue──▶  Redis  ──▶  ARQ worker
                                                                          │
                                                                    subprocess
                                                                          ▼
                                                                 scrapy crawl site
                                                                          │
        extract ▶ archive ▶ dedupe ▶ jsonl ▶ csv ▶ mongo ▶ progress
                                        │              │
                                        ▼              ▼
              backend/data/{site}/{job_id}/    MongoDB mt-scrapy-crawl
                  pages.jsonl + pages.csv      pages / sites / jobs
```

Scrapy runs as a **subprocess**, not inside the worker: the Twisted reactor is
not restartable, so a second in-process crawl would fail.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Node.js 20+
- Redis 7+, via Docker or locally
- MongoDB 7+ reachable at `MONGO_URL` (optional — see `MONGO_ENABLED`)

## Setup

### 1. Redis and MongoDB

```bash
cd scraper-poc
docker compose up -d
```

No Docker? Any local Redis works — `brew install redis && brew services start redis`.
Point `REDIS_URL` at whichever you use.

MongoDB is not in the compose file — it is expected to already exist at
`MONGO_URL`. Set `MONGO_ENABLED=false` to run without it.

### 2. Backend

```bash
cd backend
cp .env.example .env
uv sync
uv run playwright install chromium   # only needed for "Render JS" crawls
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
```

## Running

Three processes, one per terminal, all from `scraper-poc/`:

```bash
# API      → http://localhost:8000  (docs at /docs)
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Worker
cd backend && uv run arq worker.worker.WorkerSettings

# UI       → http://localhost:3000
cd frontend && npm run dev
```

Open <http://localhost:3000>, enter a URL, and start a crawl. The status card
polls every 2s; results stream into the table while the job runs. When it
finishes, a site profile card shows what the crawl learned about the company.
Click a row for the markdown preview, or use **JSONL** / **CSV** to download.

## Configuration

`backend/.env` (see `backend/.env.example`):

| Variable | Default | Notes |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | Job status and the ARQ queue |
| `MONGO_URL` | `mongodb://192.168.0.102:27017/` | Where pages/sites/jobs are stored |
| `MONGO_DB` | `mt-scrapy-crawl` | Database name |
| `MONGO_ENABLED` | `true` | `false` runs file-only, no database |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | JSON array of allowed origins |
| `DEFAULT_MAX_PAGES` | `0` | `0` crawls the whole site; a positive value caps it |
| `CRAWL_PAGE_CEILING` | `10000` | Backstop against crawl traps, applied even at `0` |
| `STORE_ARCHIVE_PAGES` | `false` | Keep tag/category/pagination listings |
| `JOB_TIMEOUT_SECONDS` | `3600` | ARQ job timeout — whole-site crawls are slow |
| `SCRAPY_LOG_LEVEL` | `INFO` | |
| `HTTPCACHE_ENABLED` | `false` | Turn on in dev to replay crawls from disk |
| `USER_AGENT` | `MyraCrawlPOC/0.1 …` | Sent on every request |

`frontend/.env.local` (see `frontend/.env.example`):

| Variable | Default |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` |

The crawl target is never hardcoded — it comes from the form, the API body, or
`--url` on the smoke test.

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/crawl` | `{url, max_pages?, use_js?}` → `{job_id}` (202). `max_pages` defaults to 0 = whole site |
| `GET` | `/api/jobs/{job_id}` | Status, counts, timestamps, error |
| `GET` | `/api/jobs/{job_id}/results?page=1&size=20` | Paginated summaries, no markdown |
| `GET` | `/api/jobs/{job_id}/results/{index}` | One page including markdown |
| `GET` | `/api/jobs/{job_id}/export?format=jsonl\|csv` | Downloads the JSONL or CSV |
| `GET` | `/api/jobs/{job_id}/site` | The site profile for this job's website |
| `GET` | `/api/sites/{domain}` | The site profile by domain |
| `GET` | `/health` | Liveness |

```bash
curl -X POST localhost:8000/api/crawl \
  -H 'content-type: application/json' \
  -d '{"url":"https://myratechnolabs.com/"}'

# then, once it finishes
curl localhost:8000/api/sites/myratechnolabs.com | jq '{name, services_count, emails, phones}'
```

## Where the data goes

Three destinations, written by the Scrapy pipelines in order.

### 1. `pages.jsonl` — one file per job, full fidelity

`backend/data/{site}/{job_id}/pages.jsonl`. The site folder comes from the start
URL's domain, so every crawl of a site collects under one folder:

```
backend/data/
└── multiqos.com/
    └── bea06cf36a8c4b0e8721ed0589713b88/
        ├── pages.jsonl
        └── pages.csv
```

One JSON object per line:

```json
{
  "url": "https://multiqos.com/",
  "status_code": 200,
  "depth": 0,
  "title": "Agentic AI, Data Engineering & Software Development | MultiQoS",
  "meta_description": "MultiQoS combines AI automation, modern data engineering…",
  "h1": "Upgrade Your Website Without Coding",
  "markdown": "# Agentic AI…",
  "word_count": 929,
  "content_hash": "49308700…",
  "crawled_at": "2026-09-19T12:38:10.114+00:00",
  "page_type": "home",
  "canonical_url": "https://multiqos.com/",
  "lang": "en",
  "og_image": "https://…/og-home.jpg",
  "links_internal": 207,
  "links_external": 8,
  "images": 82
}
```

### 2. `pages.csv` — same rows, spreadsheet-shaped

Alongside the JSONL, with the columns in `crawler/items.py::CSV_COLUMNS`.
**Markdown is deliberately not a column**: multi-KB cells make a CSV unusable in
a spreadsheet, and the JSONL already carries the full text. Newlines inside a
cell are flattened so naive readers do not mis-split rows.

### 3. MongoDB — queryable, cumulative across jobs

Database `mt-scrapy-crawl` (`MONGO_URL`, `MONGO_DB`), three collections:

| Collection | Key | Contents |
| --- | --- | --- |
| `pages` | `(job_id, url)` unique | Every crawled page, markdown included, one doc per page per job |
| `sites` | `_id` = domain | One profile per website, rebuilt on each crawl |
| `jobs` | `_id` = job id | Crawl parameters, status, final counts, page-type breakdown |

A `sites` document is what the crawl *learned about the company*, merged across
the homepage, about page and contact page:

```json
{
  "_id": "multiqos.com",
  "name": "MultiQoS",
  "description": "MultiQoS combines AI automation, modern data engineering…",
  "logo": "https://…/og-home.jpg",
  "favicon": "https://multiqos.com/favicon.ico",
  "lang": "en",
  "emails": ["biz@multiqos.com"],
  "phones": ["+12242102056", "+918866687330"],
  "socials": [{"network": "linkedin", "url": "https://www.linkedin.com/company/multiqos/"}],
  "services": [{"name": "AI Agent Development", "url": "https://multiqos.com/ai-agent-development-services"}],
  "services_count": 88,
  "team": [], "team_count": 0,
  "key_pages": {"about": "https://multiqos.com/about-us/", "contact": "https://multiqos.com/contact-us/"},
  "page_count": 20, "total_words": 23867,
  "pages_by_type": {"home": 1, "about": 1, "contact": 1, "services": 17}
}
```

Mongo being unreachable is **not** fatal: the crawl logs the error and finishes
with the JSONL and CSV intact. Set `MONGO_ENABLED=false` to skip it entirely.

## What gets extracted, and how

`crawler/extractors.py` runs heuristics over each page:

- **Page type** — `home`, `about`, `team`, `contact`, `careers`, `services`,
  `portfolio`, `blog`, `legal`, `pricing`, `other`, from the URL path first and
  the headings as a fallback.
- **Metadata** — canonical URL, `lang`, Open Graph and Twitter tags, favicon,
  robots directive.
- **Contacts** — emails and phones from `mailto:`/`tel:` links and page text,
  plus social profiles across 13 networks. Phone numbers are normalised and
  length-checked so tracking junk does not get through.
- **Services** — internal links whose URL looks like a service page
  (`/services/`, `/hire-…`, `…-development`, `…-solutions`), with the anchor
  text as the name.
- **Team** — schema.org `Person` blocks first, then repeated person cards in the
  markup (a name-shaped heading followed by a role-shaped line). A site that
  publishes no named people yields an empty list, which is the honest answer
  rather than noise.
- **Organisation** — `Organization`/`LocalBusiness` JSON-LD for legal name,
  address and founding date.

Site-level extraction only runs on pages that plausibly carry these facts
(`SITE_FACT_PAGE_TYPES`), so blog posts do not pay the cost.

### Crawl scope

**There is no depth limit.** Every internal link is followed until the site runs
out of them; `depth` is recorded on each page as information only. A crawl of
myratechnolabs.com reaches depth 6, and one of multiqos.com reaches depth 38.

`max_pages` defaults to `0`, meaning the whole site. `CRAWL_PAGE_CEILING`
(10,000) still applies as a backstop so a crawl trap cannot run forever.

**Archive listings are followed but not stored.** `/tag/…`, `/category/…`,
`/author/…`, `/page/2/` and friends exist to link to posts, not to be read. On
myratechnolabs.com they were 350 of 495 responses; storing them buried the real
content and, because they all render near-identical excerpt lists, they poisoned
the dedupe set. Set `STORE_ARCHIVE_PAGES=true` to keep them.

Links are queued with a priority derived from their page type
(`PAGE_TYPE_PRIORITY`): team and about/contact rank highest, services next, blog
posts low, archives lowest.

## How the crawl behaves

- **robots.txt is obeyed** (`ROBOTSTXT_OBEY=True`). Disallowed URLs count as
  failures, which is why `pages_failed` is usually non-zero on a real site.
- **Internal links only.** `allowed_domains` is derived from the start URL with
  `www.` stripped, so subdomains (`help.`, `de.`) are treated as internal —
  standard Scrapy semantics.
- **Assets are skipped** at link-extraction time (pdf, images, archives, css, js,
  fonts, feeds), along with `mailto:`, `tel:`, `javascript:` and bare fragments.
- **URLs are normalised** — fragment dropped, query parameters ordered — so
  `/a#one` and `/a#two` are one page.
- **`max_pages` is a hard cap.** `CLOSESPIDER_PAGECOUNT` only stops the
  scheduler, and requests already in flight still return, so the JSONL pipeline
  enforces the limit on what actually gets stored.
- **Duplicate content is dropped** by sha256 of the markdown, within a job.
- **Throttling**: `AUTOTHROTTLE_ENABLED`, 4 concurrent requests per domain,
  0.5s delay, 2 retries.

`use_js` routes requests through scrapy-playwright. The handler is registered
always but defers to the plain HTTP handler unless a request carries
`meta={"playwright": True}`, so non-JS crawls never launch a browser and work
fine without one installed.

## Tests

```bash
cd backend
uv run pytest                 # 147 tests
```

Covers the pipelines (`ExtractPipeline`, `ArchivePipeline`, `DedupePipeline`,
`CsvPipeline`, the `max_pages` cap, markdown normalisation), the extraction
fallback ladder, the spider (URL normalisation, link filtering, no depth limit,
crawl priority, structured fields) and the extractors (page classification,
contacts, phone normalisation, services, team from both JSON-LD and markup,
organisation, and the site profile merge).

### Smoke test

Needs the API and worker running.

```bash
cd backend
uv run python scripts/smoke_test.py --url https://myratechnolabs.com/ --max-pages 0
uv run python scripts/smoke_test.py --url https://example.com --max-pages 10
uv run python scripts/smoke_test.py --use-js                 # via Playwright
```

It posts a crawl, polls to completion, then asserts the page count, unique
hashes, non-empty markdown on every page, depth limits and the export, and
prints a summary table.

## Layout

```
scraper-poc/
├── docker-compose.yml          # redis only
├── backend/
│   ├── app/                    # FastAPI: main, api/routes, schemas, config,
│   │                           #   job_store (Redis), mongo (reads), urls
│   ├── worker/                 # ARQ: WorkerSettings, run_crawl
│   ├── crawler/                # Scrapy: spiders/site_spider, pipelines, items,
│   │                           #   content (extraction ladder), extractors,
│   │                           #   site_profile, mongo_store, settings
│   ├── scripts/smoke_test.py
│   ├── data/{site}/{job_id}/   # pages.jsonl + pages.csv
│   └── tests/
└── frontend/                   # Next.js App Router + shadcn/ui
    └── src/
        ├── app/page.tsx        # the single page
        ├── components/         # crawl-form, job-status-card, site-profile-card,
        │                       #   results-table, page-detail-sheet
        └── lib/api.ts          # typed API client
```

## Known limits

This is a POC, so a few things are deliberately simple:

- The API's results endpoints scan the JSONL file per request rather than
  querying Mongo. Fine for hundreds of pages, not for hundreds of thousands —
  the `pages` collection is already indexed for it when that matters.
- Job records live in Redis with a 7-day TTL; the files and Mongo documents are
  never cleaned up, so a job's Redis record can expire while its data remains.
- Team extraction is heuristic. It reads schema.org reliably and common card
  markup well, but an unusual layout will yield nothing rather than guess.
- A whole-site crawl of a large blog takes minutes and hits the site a few
  times a second. `AUTOTHROTTLE` and `DOWNLOAD_DELAY` keep it polite, but it is
  not a background task you should fire off casually at someone else's site.
- There is no auth, no rate limiting and no per-tenant isolation.
- Cancelling a running job is not implemented.
