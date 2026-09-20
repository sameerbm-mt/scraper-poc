"""Tests for pause/resume/cancel: the API transitions and the resume bookkeeping."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.config import Settings, get_settings
from app.job_store import CONTROL_CANCEL, CONTROL_PAUSE
from app.schemas import JobState, JobStatus
from crawler.pipelines import _count_records, _hashes_on_disk

JOB = "a" * 32


class FakeStore:
    """The slice of JobStore the control routes use."""

    def __init__(self, state: JobState) -> None:
        self.state = state
        self.control: str = ""
        self.calls: list[str] = []

    async def get(self, job_id: str) -> JobState | None:
        return self.state if job_id == self.state.job_id else None

    async def request_control(self, job_id: str, action: str) -> None:
        self.control = action

    async def clear_control(self, job_id: str) -> None:
        self.control = ""

    async def mark_pausing(self, job_id: str) -> None:
        self.calls.append("pausing")
        self.state = self.state.model_copy(update={"status": JobStatus.pausing})

    async def mark_resuming(self, job_id: str) -> None:
        self.calls.append("resuming")
        self.state = self.state.model_copy(
            update={
                "status": JobStatus.resuming,
                "resume_count": self.state.resume_count + 1,
            }
        )

    async def mark_cancelled(self, job_id: str) -> None:
        self.calls.append("cancelled")
        self.state = self.state.model_copy(update={"status": JobStatus.cancelled})


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, *args, **kwargs):
        self.enqueued.append((args, kwargs))


def job(status: JobStatus, **overrides) -> JobState:
    return JobState(
        **{
            "job_id": JOB,
            "status": status,
            "url": "https://example.com/",
            "site": "example.com",
            "max_pages": 40,
            "use_js": True,
            "pages_crawled": 12,
            "created_at": datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc),
            **overrides,
        }
    )


@pytest.fixture
def client(tmp_path):
    """An app whose store and queue are fakes, so transitions are observable."""
    store = FakeStore(job(JobStatus.running))
    queue = FakeQueue()
    settings = Settings(data_dir=tmp_path)

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[routes.get_job_store] = lambda: store
    app.dependency_overrides[routes.get_queue] = lambda: queue

    with TestClient(app) as http:
        yield http, store, queue


class TestPause:
    def test_a_running_job_moves_to_pausing_and_records_the_request(self, client):
        http, store, _ = client

        response = http.post(f"/api/jobs/{JOB}/pause")

        assert response.status_code == 200
        assert response.json()["status"] == "pausing"
        # The API only asks; the worker owns the subprocess.
        assert store.control == CONTROL_PAUSE

    @pytest.mark.parametrize(
        "status", [JobStatus.paused, JobStatus.completed, JobStatus.failed, JobStatus.queued]
    )
    def test_pausing_anything_but_a_running_job_is_a_conflict(self, client, status):
        http, store, _ = client
        store.state = job(status)

        response = http.post(f"/api/jobs/{JOB}/pause")

        assert response.status_code == 409
        assert status.value in response.json()["detail"]
        assert store.control == ""

    def test_an_unknown_job_is_not_found(self, client):
        http, _, _ = client

        assert http.post("/api/jobs/deadbeef/pause").status_code == 404


class TestResume:
    def test_a_paused_job_is_re_enqueued_with_its_flags(self, client):
        http, store, queue = client
        store.state = job(JobStatus.paused, use_sitemap=True, download_files=True)

        response = http.post(f"/api/jobs/{JOB}/resume")

        assert response.status_code == 200
        assert response.json()["status"] == "resuming"
        (args, kwargs) = queue.enqueued[0]
        assert args[0] == "run_crawl"
        assert args[1] == JOB
        # url, max_pages, use_js, use_sitemap, download_files, extract_contacts
        assert args[3:] == (40, True, True, True, False)

    def test_the_arq_job_id_changes_per_attempt(self, client):
        """ARQ silently drops a job whose id it already knows, so a resume
        reusing `crawl:{job_id}` would never run."""
        http, store, queue = client
        store.state = job(JobStatus.paused, resume_count=2)

        http.post(f"/api/jobs/{JOB}/resume")

        assert queue.enqueued[0][1]["_job_id"] == f"crawl:{JOB}:3"

    def test_resume_increments_the_count(self, client):
        http, store, _ = client
        store.state = job(JobStatus.paused, resume_count=0)

        assert http.post(f"/api/jobs/{JOB}/resume").json()["resume_count"] == 1

    @pytest.mark.parametrize("status", [JobStatus.running, JobStatus.completed, JobStatus.cancelled])
    def test_resuming_anything_but_a_paused_job_is_a_conflict(self, client, status):
        http, store, queue = client
        store.state = job(status)

        assert http.post(f"/api/jobs/{JOB}/resume").status_code == 409
        assert queue.enqueued == []


class TestCancel:
    def test_a_running_job_is_handed_to_the_worker(self, client):
        http, store, _ = client

        response = http.post(f"/api/jobs/{JOB}/cancel")

        assert response.status_code == 200
        assert store.control == CONTROL_CANCEL
        # The worker marks it cancelled once the process is down.
        assert "cancelled" not in store.calls

    def test_a_paused_job_is_closed_out_directly(self, client):
        """There is no process left to signal, so the API finishes the job."""
        http, store, _ = client
        store.state = job(JobStatus.paused)

        response = http.post(f"/api/jobs/{JOB}/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert "cancelled" in store.calls

    def test_cancelling_a_paused_job_removes_its_jobdir(self, client, tmp_path):
        http, store, _ = client
        store.state = job(JobStatus.paused)
        jobdir = tmp_path / "example.com" / JOB / "jobdir"
        jobdir.mkdir(parents=True)
        (jobdir / "requests.seen").write_text("x", encoding="utf-8")

        http.post(f"/api/jobs/{JOB}/cancel")

        assert not jobdir.exists()

    @pytest.mark.parametrize("status", [JobStatus.completed, JobStatus.failed, JobStatus.cancelled])
    def test_cancelling_a_finished_job_is_a_conflict(self, client, status):
        http, store, _ = client
        store.state = job(status)

        assert http.post(f"/api/jobs/{JOB}/cancel").status_code == 409


class TestConflictMessage:
    def test_it_names_the_current_state_and_the_allowed_ones(self, client):
        http, store, _ = client
        store.state = job(JobStatus.completed)

        detail = http.post(f"/api/jobs/{JOB}/cancel").json()["detail"]

        assert detail == (
            "Job is completed; only a running, pausing or paused job can be cancelled."
        )


class TestResumeDoesNotDuplicate:
    """The pipeline-side half of resume: pages.jsonl is appended, never restarted."""

    def _write(self, path, records):
        path.write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
        )

    def test_existing_hashes_are_loaded_so_a_resumed_page_is_dropped(self, tmp_path):
        path = tmp_path / "pages.jsonl"
        self._write(path, [{"url": "https://a.com/1", "content_hash": "h1"}])

        assert _hashes_on_disk(path) == {"h1"}

    def test_existing_rows_count_towards_the_page_cap(self, tmp_path):
        path = tmp_path / "pages.jsonl"
        self._write(path, [{"url": f"https://a.com/{i}", "content_hash": f"h{i}"} for i in range(7)])

        assert _count_records(path) == 7

    def test_a_ragged_line_from_a_killed_run_is_skipped(self, tmp_path):
        path = tmp_path / "pages.jsonl"
        path.write_text(
            json.dumps({"url": "https://a.com/1", "content_hash": "h1"}) + '\n{"url": "htt',
            encoding="utf-8",
        )

        assert _hashes_on_disk(path) == {"h1"}

    def test_no_file_yet_means_a_fresh_crawl(self, tmp_path):
        assert _hashes_on_disk(tmp_path / "absent.jsonl") == set()
        assert _count_records(tmp_path / "absent.jsonl") == 0
