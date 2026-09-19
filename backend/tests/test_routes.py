"""Tests for the sites list, per-site jobs and the on-disk fallback for old jobs."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings, get_settings
from app.schemas import JobState, JobStatus

JOB_A = "a" * 32
JOB_B = "b" * 32
JOB_C = "c" * 32


class FakeStore:
    """The slice of JobStore the routes use: Redis's memory of live jobs."""

    def __init__(self, states: dict[str, JobState] | None = None) -> None:
        self.states = states or {}

    async def get(self, job_id: str) -> JobState | None:
        return self.states.get(job_id)


class FakeMongo:
    def __init__(self, sites=None, jobs=None) -> None:
        self.available = True
        self.sites = sites or {}
        self.jobs = jobs or {}

    def find_sites(self, domains):
        return {d: self.sites[d] for d in domains if d in self.sites}

    def find_jobs(self, job_ids):
        return {j: self.jobs[j] for j in job_ids if j in self.jobs}


def redis_state(job_id: str, site: str, **overrides) -> JobState:
    fields = dict(
        job_id=job_id,
        status=JobStatus.running,
        url=f"https://{site}/",
        site=site,
        max_pages=0,
        use_js=False,
        pages_crawled=7,
        pages_failed=2,
        created_at=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc),
    )
    return JobState(**{**fields, **overrides})


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Build a TestClient with the router, a fake Redis and a fake Mongo."""

    def _build(*, store=None, mongo=None) -> TestClient:
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_settings] = lambda: Settings(data_dir=tmp_path)
        app.dependency_overrides[routes.get_job_store] = lambda: store or FakeStore()
        monkeypatch.setattr(routes, "get_mongo", lambda: mongo or FakeMongo())
        return TestClient(app)

    return _build


# -- GET /api/sites ---------------------------------------------------------


def test_sites_list_is_empty_with_nothing_crawled(api):
    response = api().get("/api/sites")

    assert response.status_code == 200
    assert response.json() == []


def test_sites_list_is_ordered_newest_first_and_summarises_the_latest_crawl(api, make_crawl):
    make_crawl("old.com", JOB_A, [("https://old.com/", "2026-09-01T10:00:00+00:00")])
    make_crawl(
        "busy.com",
        JOB_B,
        [("https://busy.com/", "2026-09-03T10:00:00+00:00")],
    )
    make_crawl(
        "busy.com",
        JOB_C,
        [
            ("https://busy.com/", "2026-09-04T10:00:00+00:00"),
            ("https://busy.com/a", "2026-09-04T10:01:00+00:00"),
            ("https://busy.com/b", "2026-09-04T10:02:00+00:00"),
        ],
    )

    body = api(mongo=FakeMongo(sites={"busy.com": {"name": "Busy Inc"}})).get("/api/sites").json()

    assert [row["domain"] for row in body] == ["busy.com", "old.com"]
    busy, old = body
    assert busy["name"] == "Busy Inc"
    assert busy["job_count"] == 2
    assert busy["latest_job_id"] == JOB_C
    assert busy["pages"] == 3
    assert busy["latest_status"] == "completed"  # Redis has forgotten it: from disk
    assert old["name"] == ""  # no Mongo profile


def test_sites_list_prefers_redis_for_a_job_it_still_remembers(api, make_crawl):
    make_crawl("busy.com", JOB_A, [("https://busy.com/", "2026-09-04T10:00:00+00:00")])
    store = FakeStore({JOB_A: redis_state(JOB_A, "busy.com")})

    body = api(store=store).get("/api/sites").json()

    assert body[0]["latest_status"] == "running"
    assert body[0]["pages"] == 7


def test_sites_list_works_without_mongo(api, make_crawl):
    make_crawl("busy.com", JOB_A, [("https://busy.com/", "2026-09-04T10:00:00+00:00")])
    mongo = FakeMongo()
    mongo.available = False
    mongo.find_sites = lambda domains: {}
    mongo.find_jobs = lambda ids: {}

    response = api(mongo=mongo).get("/api/sites")

    assert response.status_code == 200
    assert response.json()[0]["name"] == ""


# -- GET /api/sites/{domain}/jobs -------------------------------------------


def test_site_jobs_lists_every_crawl_newest_first(api, make_crawl):
    make_crawl("busy.com", JOB_A, [("https://busy.com/", "2026-09-01T10:00:00+00:00")])
    make_crawl("busy.com", JOB_B, [("https://busy.com/", "2026-09-02T10:00:00+00:00")])
    store = FakeStore({JOB_B: redis_state(JOB_B, "busy.com", status=JobStatus.completed)})
    mongo = FakeMongo(jobs={JOB_A: {"max_pages": 25, "start_url": "https://busy.com/start"}})

    response = api(store=store, mongo=mongo).get("/api/sites/busy.com/jobs")

    assert response.status_code == 200
    jobs = response.json()
    assert [job["job_id"] for job in jobs] == [JOB_B, JOB_A]
    assert jobs[0]["pages_failed"] == 2  # from Redis
    assert jobs[1]["max_pages"] == 25  # from the Mongo job record
    assert jobs[1]["url"] == "https://busy.com/start"
    assert jobs[1]["status"] == "completed"


def test_site_jobs_is_case_insensitive_on_the_domain(api, make_crawl):
    make_crawl("busy.com", JOB_A, [("https://busy.com/", "2026-09-01T10:00:00+00:00")])

    assert api().get("/api/sites/Busy.COM/jobs").status_code == 200


def test_site_jobs_404s_for_an_unknown_site(api):
    response = api().get("/api/sites/never-crawled.com/jobs")

    assert response.status_code == 404


# -- jobs whose Redis record has expired ------------------------------------


def test_job_lookup_falls_back_to_the_files(api, make_crawl):
    make_crawl(
        "busy.com",
        JOB_A,
        [
            ("https://busy.com/", "2026-09-01T10:00:00+00:00"),
            ("https://busy.com/a", "2026-09-01T10:01:00+00:00"),
        ],
    )

    response = api().get(f"/api/jobs/{JOB_A}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["site"] == "busy.com"
    assert body["pages_crawled"] == 2


def test_results_and_export_still_work_after_redis_forgets_the_job(api, make_crawl):
    make_crawl(
        "busy.com",
        JOB_A,
        [(f"https://busy.com/{n}", f"2026-09-01T10:0{n}:00+00:00") for n in range(5)],
    )
    client = api()

    page = client.get(f"/api/jobs/{JOB_A}/results", params={"page": 2, "size": 2}).json()
    assert page["total"] == 5
    assert page["total_pages"] == 3
    assert [item["index"] for item in page["items"]] == [2, 3]

    detail = client.get(f"/api/jobs/{JOB_A}/results/4").json()
    assert detail["url"] == "https://busy.com/4"
    assert "Body text 4" in detail["markdown"]

    export = client.get(f"/api/jobs/{JOB_A}/export", params={"format": "csv"})
    assert export.status_code == 200
    assert export.text.splitlines()[0] == "url,depth,crawled_at"


def test_a_job_with_neither_redis_nor_files_is_a_404(api):
    client = api()

    assert client.get(f"/api/jobs/{JOB_A}").status_code == 404
    assert client.get("/api/jobs/not-a-job-id").status_code == 404
    assert client.get(f"/api/jobs/{JOB_A}/results").status_code == 404
