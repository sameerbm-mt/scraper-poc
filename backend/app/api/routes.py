"""HTTP routes for the crawl POC."""

from __future__ import annotations

import json
import math
import shutil
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Iterator, get_origin

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app import catalog
from app.config import Settings, get_settings
from app.job_store import CONTROL_CANCEL, CONTROL_PAUSE, JobStore
from app.mongo import get_mongo
from app.schemas import (
    TERMINAL_STATUSES,
    CrawlRequest,
    CrawlResponse,
    DocumentRecord,
    JobState,
    JobStats,
    JobStatus,
    PageDetail,
    PageSummary,
    ResultsPage,
    SiteProfile,
    SiteSummary,
)

router = APIRouter(prefix="/api", tags=["crawl"])


def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def get_queue(request: Request) -> ArqRedis:
    return request.app.state.queue


SettingsDep = Annotated[Settings, Depends(get_settings)]
JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
QueueDep = Annotated[ArqRedis, Depends(get_queue)]


@router.post("/crawl", response_model=CrawlResponse, status_code=202)
async def start_crawl(
    payload: CrawlRequest,
    store: JobStoreDep,
    queue: QueueDep,
) -> CrawlResponse:
    """Register a job in Redis and hand it to the ARQ worker."""
    job_id = uuid.uuid4().hex
    await store.create(
        job_id,
        url=payload.url,
        max_pages=payload.max_pages,
        use_js=payload.use_js,
        use_sitemap=payload.use_sitemap,
        download_files=payload.download_files,
        extract_contacts=payload.extract_contacts,
    )
    await _enqueue_crawl(queue, job_id, payload.url, payload, attempt=0)
    return CrawlResponse(job_id=job_id)


async def _enqueue_crawl(
    queue: ArqRedis,
    job_id: str,
    url: str,
    options: CrawlRequest | JobState,
    attempt: int,
) -> None:
    """Hand the crawl to the worker.

    `attempt` disambiguates the ARQ job id. ARQ refuses a second job with an id
    it already knows, and it remembers finished ones for `keep_result`, so a
    resume enqueued as `crawl:{job_id}` would be silently dropped.
    """
    await queue.enqueue_job(
        "run_crawl",
        job_id,
        url,
        options.max_pages,
        options.use_js,
        options.use_sitemap,
        options.download_files,
        options.extract_contacts,
        _job_id=f"crawl:{job_id}:{attempt}",
    )


@router.get("/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: str, store: JobStoreDep, settings: SettingsDep) -> JobState:
    return await _require_job(job_id, store, settings)


@router.post("/jobs/{job_id}/pause", response_model=JobState)
async def pause_job(
    job_id: str, store: JobStoreDep, settings: SettingsDep
) -> JobState:
    """Ask a running crawl to stop gracefully, keeping its place.

    The API only records the request; the worker owns the subprocess and is what
    actually signals it. The job moves to `pausing` here and reaches `paused`
    once Scrapy has flushed its queue to JOBDIR.
    """
    job = await _require_job(job_id, store, settings)
    _require_status(job, {JobStatus.running}, "paused")
    await store.request_control(job_id, CONTROL_PAUSE)
    await store.mark_pausing(job_id)
    return await _require_job(job_id, store, settings)


@router.post("/jobs/{job_id}/resume", response_model=JobState)
async def resume_job(
    job_id: str, store: JobStoreDep, settings: SettingsDep, queue: QueueDep
) -> JobState:
    """Re-queue a paused crawl against the same JOBDIR.

    The jobdir is deliberately left untouched: it holds the frontier the paused
    run stopped on, and the new task picks up from exactly there.
    """
    job = await _require_job(job_id, store, settings)
    _require_status(job, {JobStatus.paused}, "resumed")

    await store.clear_control(job_id)
    await store.mark_resuming(job_id)
    refreshed = await _require_job(job_id, store, settings)
    # resume_count has just been incremented, so it doubles as the attempt
    # number that keeps each ARQ job id distinct.
    await _enqueue_crawl(queue, job_id, job.url, job, attempt=refreshed.resume_count)
    return refreshed


@router.post("/jobs/{job_id}/cancel", response_model=JobState)
async def cancel_job(
    job_id: str, store: JobStoreDep, settings: SettingsDep
) -> JobState:
    """Stop a crawl for good, keeping whatever it has already written.

    A running job is cancelled by the worker; a paused one has no process left,
    so it is closed out here. Either way the partial pages.jsonl stays readable
    and only the resume state is discarded.
    """
    job = await _require_job(job_id, store, settings)
    _require_status(job, {JobStatus.running, JobStatus.paused, JobStatus.pausing}, "cancelled")

    if job.status == JobStatus.paused:
        await store.clear_control(job_id)
        _drop_jobdir(settings, job.site, job_id)
        await store.mark_cancelled(job_id)
    else:
        await store.request_control(job_id, CONTROL_CANCEL)
    return await _require_job(job_id, store, settings)


# The order states are listed in when a transition is refused. Lifecycle order
# reads better than alphabetical: "running, pausing or paused".
_STATUS_ORDER: tuple[JobStatus, ...] = (
    JobStatus.queued,
    JobStatus.running,
    JobStatus.pausing,
    JobStatus.paused,
    JobStatus.resuming,
    JobStatus.completed,
    JobStatus.failed,
    JobStatus.cancelled,
)


def _require_status(job: JobState, allowed: set[JobStatus], action: str) -> None:
    """409 on an invalid transition, naming the state the job is actually in."""
    if job.status in allowed:
        return
    names = [status.value for status in _STATUS_ORDER if status in allowed]
    allowed_text = (
        names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"
    )
    raise HTTPException(
        status_code=409,
        detail=f"Job is {job.status.value}; only a {allowed_text} job can be {action}.",
    )


def _drop_jobdir(settings: Settings, site: str, job_id: str) -> None:
    shutil.rmtree(settings.job_jobdir_path(site, job_id), ignore_errors=True)


@router.get("/jobs/{job_id}/stats", response_model=JobStats)
async def get_stats(
    job_id: str, store: JobStoreDep, settings: SettingsDep
) -> JobStats:
    """Aggregates over this job's stored pages, for the UI's stats card."""
    job = await _require_job(job_id, store, settings)
    return await run_in_threadpool(
        _aggregate,
        settings.job_results_path(job.site, job_id),
        settings.job_documents_path(job.site, job_id),
        job,
    )


def _aggregate(results: Path, documents: Path, job: JobState) -> JobStats:
    schema_counts: dict[str, int] = {}
    pages = words = faqs = products = 0
    response_times: list[int] = []

    for _, record in _iter_records(results):
        pages += 1
        words += int(record.get("word_count") or 0)
        faqs += len(record.get("faqs") or [])
        products += len(record.get("products") or [])
        elapsed = int(record.get("response_time_ms") or 0)
        if elapsed > 0:
            response_times.append(elapsed)
        for name in record.get("schema_types") or []:
            schema_counts[str(name)] = schema_counts.get(str(name), 0) + 1

    return JobStats(
        pages_crawled=pages or job.pages_crawled,
        pages_failed=job.pages_failed,
        documents_downloaded=sum(1 for _ in _iter_records(documents)),
        # Most-seen first: that is the order the UI lists them in.
        schema_types=dict(
            sorted(schema_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        avg_response_time_ms=(
            round(sum(response_times) / len(response_times)) if response_times else 0
        ),
        total_words=words,
        faqs_found=faqs,
        products_found=products,
    )


@router.get("/jobs/{job_id}/documents", response_model=list[DocumentRecord])
async def get_documents(
    job_id: str,
    store: JobStoreDep,
    settings: SettingsDep,
    include_text: Annotated[bool, Query()] = False,
) -> list[DocumentRecord]:
    """Documents downloaded for this job. Extracted text is opt-in: it is large."""
    job = await _require_job(job_id, store, settings)
    path = settings.job_documents_path(job.site, job_id)

    records: list[DocumentRecord] = []
    for _, record in _iter_records(path):
        if not include_text:
            record = {**record, "markdown": ""}
        records.append(DocumentRecord.model_validate(_readable(record, DocumentRecord)))
    return records


@router.get("/jobs/{job_id}/results", response_model=ResultsPage)
async def get_results(
    job_id: str,
    store: JobStoreDep,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ResultsPage:
    """Paginated page list. Markdown is omitted here — see the detail route."""
    job = await _require_job(job_id, store, settings)
    path = settings.job_results_path(job.site, job_id)

    total = 0
    start, end = (page - 1) * size, (page - 1) * size + size
    items: list[PageSummary] = []
    for index, record in _iter_records(path):
        total += 1
        if start <= index < end:
            items.append(_to_summary(index, record))

    return ResultsPage(
        items=items,
        page=page,
        size=size,
        total=total,
        total_pages=max(1, math.ceil(total / size)) if total else 0,
    )


@router.get("/jobs/{job_id}/results/{index}", response_model=PageDetail)
async def get_result(
    job_id: str,
    index: int,
    store: JobStoreDep,
    settings: SettingsDep,
) -> PageDetail:
    """A single crawled page, including its markdown body."""
    job = await _require_job(job_id, store, settings)
    if index < 0:
        raise HTTPException(status_code=404, detail="Result not found")

    for current, record in _iter_records(settings.job_results_path(job.site, job_id)):
        if current == index:
            return _to_detail(current, record)
    raise HTTPException(status_code=404, detail="Result not found")


@lru_cache(maxsize=8)
def _container_fields(model: type[BaseModel]) -> frozenset[str]:
    """Names of `model` fields whose value has to be a list or a dict."""
    return frozenset(
        name
        for name, field in model.model_fields.items()
        if (get_origin(field.annotation) or field.annotation) in (list, dict)
    )


def _readable(record: dict[str, Any], model: type[BaseModel]) -> dict[str, Any]:
    """Drop values a stored record can no longer be read with.

    Files on disk outlive the schema, and two kinds of drift show up in them: a
    stored `null` where the field is non-optional, and a scalar where the field
    has since become a list — `images` held an image *count* before it held the
    images themselves. Dropping either lets the field fall back to its default,
    which is what an absent key would do, instead of failing the whole request.
    """
    containers = _container_fields(model)
    return {
        key: value
        for key, value in record.items()
        if value is not None
        and not (key in containers and not isinstance(value, (list, dict)))
    }


def _to_detail(index: int, record: dict[str, Any]) -> PageDetail:
    """Validate a stored record into PageDetail, tolerating older rows."""
    return PageDetail.model_validate({**_readable(record, PageDetail), "index": index})


@router.get("/jobs/{job_id}/export")
async def export_results(
    job_id: str,
    store: JobStoreDep,
    settings: SettingsDep,
    format: Annotated[str, Query(pattern="^(jsonl|csv)$")] = "jsonl",
) -> FileResponse:
    """Download this job's pages.jsonl (full) or pages.csv (flat, no markdown)."""
    job = await _require_job(job_id, store, settings)
    if format == "csv":
        path = settings.job_csv_path(job.site, job_id)
        media_type = "text/csv"
    else:
        path = settings.job_results_path(job.site, job_id)
        media_type = "application/x-ndjson"

    if not path.exists():
        raise HTTPException(status_code=404, detail="No results for this job yet")
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"{job.site}-{job_id}.{format}",
    )


@router.get("/jobs/{job_id}/site", response_model=SiteProfile)
async def get_job_site(
    job_id: str, store: JobStoreDep, settings: SettingsDep
) -> SiteProfile:
    """The website profile Mongo holds for this job's site."""
    job = await _require_job(job_id, store, settings)
    return await _site_profile(job.site)


@router.get("/sites", response_model=list[SiteSummary])
async def list_sites(store: JobStoreDep, settings: SettingsDep) -> list[SiteSummary]:
    """Every crawled website, most recently crawled first."""
    by_site = await run_in_threadpool(catalog.scan, settings.data_dir)
    ordered = sorted(by_site.items(), key=lambda item: item[1][0].activity, reverse=True)
    headlines = await run_in_threadpool(_site_headlines, [site for site, _ in ordered])
    states = await _job_states([crawls[0] for _, crawls in ordered], store)

    return [
        SiteSummary(
            domain=site,
            name=str(headlines.get(site, {}).get("name") or ""),
            job_count=len(crawls),
            latest_job_id=state.job_id,
            latest_status=state.status,
            pages=state.pages_crawled,
            last_crawled_at=crawls[0].activity,
        )
        for (site, crawls), state in zip(ordered, states)
    ]


@router.get("/sites/{domain}/jobs", response_model=list[JobState])
async def list_site_jobs(
    domain: str, store: JobStoreDep, settings: SettingsDep
) -> list[JobState]:
    """Every crawl of one website, newest first."""
    crawls = await run_in_threadpool(catalog.scan_site, settings.data_dir, domain.lower())
    if not crawls:
        raise HTTPException(status_code=404, detail=f"No crawls stored for {domain}")
    return await _job_states(crawls, store)


@router.get("/sites/{domain}", response_model=SiteProfile)
async def get_site(domain: str) -> SiteProfile:
    """The website profile by domain, independent of any single job."""
    return await _site_profile(domain)


async def _site_profile(domain: str) -> SiteProfile:
    mongo = get_mongo()
    if not mongo.available:
        raise HTTPException(status_code=503, detail="MongoDB is not reachable")
    # pymongo is blocking; keep it off the event loop.
    document = await run_in_threadpool(mongo.find_site, domain)
    if document is None:
        raise HTTPException(status_code=404, detail=f"No profile stored for {domain}")
    return SiteProfile.model_validate(document)


async def _require_job(job_id: str, store: JobStore, settings: Settings) -> JobState:
    job = await store.get(job_id)
    if job is None:
        # Redis forgets a job after its TTL; the files (and so the results) remain.
        crawl = await run_in_threadpool(catalog.find, settings.data_dir, job_id)
        if crawl is not None:
            recorded = await run_in_threadpool(_recorded_jobs, [job_id])
            job = catalog.state_from_disk(crawl, recorded.get(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _job_states(crawls: list[catalog.Crawl], store: JobStore) -> list[JobState]:
    """Redis is authoritative for a job it still remembers; the files cover the rest."""
    remembered = [await store.get(crawl.files.job_id) for crawl in crawls]
    forgotten = [
        crawl.files.job_id
        for crawl, state in zip(crawls, remembered)
        if state is None
    ]
    recorded = await run_in_threadpool(_recorded_jobs, forgotten)
    return [
        state
        if state is not None
        else catalog.state_from_disk(crawl, recorded.get(crawl.files.job_id))
        for crawl, state in zip(crawls, remembered)
    ]


def _recorded_jobs(job_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Mongo's `jobs` documents, when Mongo is up. Blocking, so run in a thread."""
    return get_mongo().find_jobs(job_ids) if job_ids else {}


def _site_headlines(domains: list[str]) -> dict[str, dict[str, Any]]:
    return get_mongo().find_sites(domains) if domains else {}


def _iter_records(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (index, record) for each line. A partially written last line is skipped."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        index = 0
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield index, record
            index += 1


def _to_summary(index: int, record: dict[str, Any]) -> PageSummary:
    status_code = record.get("status_code")
    return PageSummary(
        index=index,
        url=str(record.get("url") or ""),
        status_code=int(status_code) if status_code is not None else None,
        depth=int(record.get("depth") or 0),
        title=str(record.get("title") or ""),
        word_count=int(record.get("word_count") or 0),
        content_hash=str(record.get("content_hash") or ""),
        crawled_at=str(record.get("crawled_at") or ""),
    )
