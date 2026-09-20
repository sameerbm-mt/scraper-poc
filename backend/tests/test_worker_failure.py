"""Tests for how a failed crawl is reported: worker.failure and worker.run_crawl."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.job_store import F_ERROR, JobStore
from app.schemas import JobState, JobStatus
from worker import failure, worker
from worker.failure import BROWSER_NOT_INSTALLED, describe_failure, explain, failed_requests

JOB_ID = "a" * 32
BROWSER_PATH = (
    r"C:\Users\Vishal\AppData\Local\ms-playwright\chromium_headless_shell-1234"
    r"\chrome-headless-shell-win64\chrome-headless-shell.exe"
)

# What Scrapy wrote for the crawl that started this: a Render JS crawl on a
# machine where `playwright install` was never run.
MISSING_BROWSER_LOG = (
    "2026-09-21 02:17:11 [scrapy.core.engine] INFO: Spider opened\n"
    "2026-09-21 02:17:13 [site] WARNING: Request failed: https://www.bacancytechnology.com/ "
    f"(BrowserType.launch: Executable doesn't exist at {BROWSER_PATH}\n"
    "+------------------------------------------------------------+\n"
    "| Looks like Playwright was just installed or updated.       |\n"
    "| Please run the following command to download new browsers: |\n"
    "|                                                            |\n"
    "|     playwright install                                     |\n"
    "|                                                            |\n"
    "| <3 Playwright Team                                         |\n"
    "+------------------------------------------------------------+)\n"
    "2026-09-21 02:17:13 [scrapy.core.engine] INFO: Closing spider (finished)\n"
)

# Shutdown chatter that used to fill the end of every log.
NOISE = (
    "2026-09-21 02:17:14 [asyncio] ERROR: Task was destroyed but it is pending!\n"
    "task: <Task pending name='Task-3' coro=<_ThreadedLoopAdapter._process_queue()>>\n"
    "RuntimeError: Event loop is closed\n"
) * 40


# -- explain / failed_requests ------------------------------------------------


def test_a_missing_playwright_browser_is_recognised_with_its_path():
    cause = explain(MISSING_BROWSER_LOG)

    assert cause is not None
    assert cause.splitlines()[0] == BROWSER_NOT_INSTALLED
    assert BROWSER_PATH in cause


def test_the_install_banner_alone_is_enough_to_recognise_it():
    assert explain("... Please run: playwright install ...") == BROWSER_NOT_INSTALLED


def test_an_ordinary_log_has_no_known_cause():
    assert explain("2026-09-21 [scrapy.core.engine] INFO: Spider closed (finished)") is None


def test_failed_requests_are_deduplicated_by_reason_and_capped():
    log = "\n".join(
        [
            "[site] WARNING: Request failed: https://a.com/1 (DNS lookup failed)",
            "[site] WARNING: Request failed: https://a.com/2 (DNS lookup failed)",
            "[site] WARNING: Request failed: https://a.com/3 (TCP connection timed out)",
            "[site] WARNING: Request failed: https://a.com/4 (Connection refused)",
            "[site] WARNING: Request failed: https://a.com/5 (Something else)",
        ]
    )

    assert failed_requests(log) == [
        "https://a.com/1: DNS lookup failed",
        "https://a.com/3: TCP connection timed out",
        "https://a.com/4: Connection refused",
    ]


# -- describe_failure ---------------------------------------------------------


def test_a_known_cause_leads_the_message_and_survives_the_noise():
    message = describe_failure("Crawl produced no pages.", MISSING_BROWSER_LOG + NOISE)

    lines = message.splitlines()
    assert lines[0] == BROWSER_NOT_INSTALLED
    assert len(lines[0]) < 250  # short enough for a toast
    assert "uv run playwright install chromium" in lines[0]
    assert f"Expected at: {BROWSER_PATH}" in lines
    assert "Crawl produced no pages." in lines
    # The whole message must fit what the job record keeps, head first.
    assert len(message) <= 4000


def test_an_unknown_failure_lists_the_first_failed_requests_before_the_log():
    log = "[site] WARNING: Request failed: https://a.com/ (DNS lookup failed)\n" + NOISE

    message = describe_failure("Crawl produced no pages.", log)

    lines = message.splitlines()
    assert lines[0] == "Crawl produced no pages."
    assert "First failed requests:" in lines
    assert "  https://a.com/: DNS lookup failed" in lines
    assert lines.index("First failed requests:") < lines.index("End of the crawl log:")


def test_the_log_tail_is_bounded_however_long_the_log_is():
    message = describe_failure("scrapy exited with 1", "x" * 500_000)

    assert message.splitlines()[0] == "scrapy exited with 1"
    assert len(message) < 4000
    assert message.endswith("x" * failure.TAIL_CHARS)


def test_an_empty_log_reports_just_the_headline():
    assert describe_failure("Crawl produced no pages.", "") == "Crawl produced no pages."


# -- the stored error keeps its head ------------------------------------------


class RecordingRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)


def test_mark_failed_keeps_the_start_of_a_long_error():
    redis = RecordingRedis()
    error = "HEADLINE\n" + "x" * 10_000

    asyncio.run(JobStore(redis).mark_failed(JOB_ID, error))

    stored = next(iter(redis.hashes.values()))[F_ERROR]
    assert stored.startswith("HEADLINE\n")
    assert len(stored) == 4000


# -- run_crawl ----------------------------------------------------------------


class FakeStore:
    """Enough of JobStore for run_crawl, recording what it was told."""

    def __init__(self, pages_crawled: int, control: str = "") -> None:
        self.pages_crawled = pages_crawled
        self.failed: list[str] = []
        self.completed = False
        self.paused = False
        self.cancelled = False
        self.status = JobStatus.running
        self.pids: list[int | None] = []
        self.control = control

    async def mark_running(self, job_id, jobdir=""):
        self.jobdir = jobdir

    async def mark_failed(self, job_id, error):
        self.failed.append(error)

    async def mark_completed(self, job_id):
        self.completed = True

    async def mark_pausing(self, job_id):
        self.status = JobStatus.pausing

    async def mark_paused(self, job_id):
        self.paused = True
        self.status = JobStatus.paused

    async def mark_cancelled(self, job_id):
        self.cancelled = True
        self.status = JobStatus.cancelled

    async def set_pid(self, job_id, pid):
        self.pids.append(pid)

    async def read_control(self, job_id):
        return self.control

    async def clear_control(self, job_id):
        self.control = ""

    async def get(self, job_id):
        return JobState(
            job_id=job_id,
            status=self.status,
            url="https://example.com/",
            max_pages=0,
            use_js=False,
            pages_crawled=self.pages_crawled,
            created_at=datetime.now(timezone.utc),
        )


class FakeStderr:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self):
        return self._data


class FakeProcess:
    """A Scrapy subprocess that has already finished by the time we look."""

    def __init__(self, stderr: str, returncode: int) -> None:
        self.stderr = FakeStderr(stderr.encode())
        self.returncode = returncode
        self.pid = 4242
        self.killed = False

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True

    def terminate(self):
        pass


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Run `run_crawl` with a fake Scrapy subprocess and a fake job store."""
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(data_dir=tmp_path))

    def _run(*, stderr: str, returncode: int, pages_crawled: int, use_js: bool = True):
        async def fake_exec(*command, **kwargs):
            return FakeProcess(stderr, returncode)

        monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", fake_exec)
        store = FakeStore(pages_crawled)
        result = asyncio.run(
            worker.run_crawl({"job_store": store}, JOB_ID, "https://example.com/", 0, use_js)
        )
        return store, result

    return _run


def test_a_render_js_crawl_without_a_browser_fails_with_the_fix_in_the_first_line(run):
    store, result = run(stderr=MISSING_BROWSER_LOG + NOISE, returncode=0, pages_crawled=0)

    assert result["pages_crawled"] == 0
    assert len(store.failed) == 1
    first_line = store.failed[0].splitlines()[0]
    assert "playwright install chromium" in first_line


def test_a_scrapy_crash_is_reported_with_its_exit_code(run):
    store, result = run(stderr="Traceback ...\nValueError: boom\n", returncode=2, pages_crawled=0)

    assert result["returncode"] == 2
    assert store.failed[0].splitlines()[0] == "scrapy exited with 2"
    assert "ValueError: boom" in store.failed[0]


def test_a_crawl_that_stored_pages_completes(run):
    store, result = run(stderr=NOISE, returncode=0, pages_crawled=12)

    assert store.completed
    assert store.failed == []
    assert result["pages_crawled"] == 12
