"""HTTP routes for the crawl POC."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Annotated, Any, Iterator

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.job_store import JobStore
from app.mongo import get_mongo
from app.schemas import (
    CrawlRequest,
    CrawlResponse,
    JobState,
    PageDetail,
    PageSummary,
    ResultsPage,
    SiteProfile,
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
    )
    await queue.enqueue_job(
        "run_crawl",
        job_id,
        payload.url,
        payload.max_pages,
        payload.use_js,
        _job_id=f"crawl:{job_id}",
    )
    return CrawlResponse(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobState)
async def get_job(job_id: str, store: JobStoreDep) -> JobState:
    state = await store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return state


@router.get("/jobs/{job_id}/results", response_model=ResultsPage)
async def get_results(
    job_id: str,
    store: JobStoreDep,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ResultsPage:
    """Paginated page list. Markdown is omitted here — see the detail route."""
    job = await _require_job(job_id, store)
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
    job = await _require_job(job_id, store)
    if index < 0:
        raise HTTPException(status_code=404, detail="Result not found")

    for current, record in _iter_records(settings.job_results_path(job.site, job_id)):
        if current == index:
            return PageDetail(
                **_to_summary(current, record).model_dump(),
                meta_description=str(record.get("meta_description") or ""),
                h1=str(record.get("h1") or ""),
                markdown=str(record.get("markdown") or ""),
            )
    raise HTTPException(status_code=404, detail="Result not found")


@router.get("/jobs/{job_id}/export")
async def export_results(
    job_id: str,
    store: JobStoreDep,
    settings: SettingsDep,
    format: Annotated[str, Query(pattern="^(jsonl|csv)$")] = "jsonl",
) -> FileResponse:
    """Download this job's pages.jsonl (full) or pages.csv (flat, no markdown)."""
    job = await _require_job(job_id, store)
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
async def get_job_site(job_id: str, store: JobStoreDep) -> SiteProfile:
    """The website profile Mongo holds for this job's site."""
    job = await _require_job(job_id, store)
    return await _site_profile(job.site)


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


async def _require_job(job_id: str, store: JobStore) -> JobState:
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
