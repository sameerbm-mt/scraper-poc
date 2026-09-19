"""Tests for the on-disk crawl catalog."""

from __future__ import annotations

from datetime import datetime, timezone

from app import catalog
from app.schemas import JobStatus

JOB_A = "a" * 32
JOB_B = "b" * 32
JOB_C = "c" * 32


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_scan_groups_crawls_by_site_newest_first(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [("https://example.com/", "2026-09-01T10:00:00+00:00")])
    make_crawl(
        "example.com",
        JOB_B,
        [
            ("https://example.com/", "2026-09-02T10:00:00+00:00"),
            ("https://example.com/about", "2026-09-02T10:05:00+00:00"),
        ],
    )
    make_crawl("other.org", JOB_C, [("https://other.org/", "2026-09-03T08:00:00+00:00")])

    sites = catalog.scan(tmp_path)

    assert set(sites) == {"example.com", "other.org"}
    assert [c.files.job_id for c in sites["example.com"]] == [JOB_B, JOB_A]
    newest = sites["example.com"][0]
    assert newest.stats.pages == 2
    assert newest.stats.start_url == "https://example.com/"
    assert newest.stats.first_at == utc(2026, 9, 2, 10, 0)
    assert newest.stats.last_at == utc(2026, 9, 2, 10, 5)
    assert newest.activity == utc(2026, 9, 2, 10, 5)


def test_scan_skips_anything_that_is_not_a_crawl(tmp_path, make_crawl):
    make_crawl("good.com", JOB_A, [("https://good.com/", "2026-09-01T10:00:00+00:00")])
    (tmp_path / "Not A Site").mkdir()  # unsafe site name
    (tmp_path / "stray.txt").write_text("x")  # a file, not a folder
    (tmp_path / "good.com" / "not-a-job-id").mkdir()  # wrong id shape
    (tmp_path / "good.com" / JOB_B).mkdir()  # no pages.jsonl yet
    (tmp_path / "empty.com").mkdir()  # a site with no crawls at all

    sites = catalog.scan(tmp_path)

    assert list(sites) == ["good.com"]
    assert [c.files.job_id for c in sites["good.com"]] == [JOB_A]


def test_scan_of_a_missing_data_dir_is_empty(tmp_path):
    assert catalog.scan(tmp_path / "nope") == {}


def test_scan_site_rejects_names_that_could_escape_the_data_dir(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [("https://example.com/", "2026-09-01T10:00:00+00:00")])

    assert len(catalog.scan_site(tmp_path, "example.com")) == 1
    for bad in ("..", "../example.com", "a/b", ".hidden", "", "EXAMPLE.COM"):
        assert catalog.scan_site(tmp_path, bad) == []
    assert catalog.scan_site(tmp_path, "unknown.com") == []


def test_find_locates_a_crawl_without_knowing_its_site(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [("https://example.com/", "2026-09-01T10:00:00+00:00")])
    make_crawl("other.org", JOB_B, [("https://other.org/", "2026-09-01T11:00:00+00:00")])

    crawl = catalog.find(tmp_path, JOB_B)

    assert crawl is not None
    assert crawl.files.site == "other.org"
    assert catalog.find(tmp_path, JOB_C) is None
    assert catalog.find(tmp_path, "../../etc") is None
    assert catalog.find(tmp_path, "short") is None


def test_stats_fall_back_to_the_jsonl_when_the_csv_is_missing(tmp_path, make_crawl):
    folder = make_crawl(
        "example.com",
        JOB_A,
        [
            ("https://example.com/", "2026-09-01T10:00:00+00:00"),
            ("https://example.com/x", "2026-09-01T10:01:00+00:00"),
        ],
        with_csv=False,
    )
    # A crawl still writing leaves a truncated last line behind.
    with (folder / "pages.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"url": "https://example.com/y", "crawled_a')

    stats = catalog.scan(tmp_path)["example.com"][0].stats

    assert stats.pages == 2
    assert stats.last_at == utc(2026, 9, 1, 10, 1)


def test_stats_are_recomputed_when_the_file_grows(tmp_path, make_crawl):
    folder = make_crawl(
        "example.com", JOB_A, [("https://example.com/", "2026-09-01T10:00:00+00:00")]
    )
    assert catalog.scan(tmp_path)["example.com"][0].stats.pages == 1

    with (folder / "pages.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("https://example.com/more,1,2026-09-01T10:02:00+00:00\n")

    stats = catalog.scan(tmp_path)["example.com"][0].stats
    assert stats.pages == 2
    assert stats.last_at == utc(2026, 9, 1, 10, 2)


def test_a_crawl_with_no_timestamps_is_dated_by_its_file(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [])

    crawl = catalog.scan(tmp_path)["example.com"][0]

    assert crawl.stats.pages == 0
    assert crawl.stats.last_at is None
    assert crawl.activity.tzinfo is not None


def test_state_from_disk_for_a_crawl_that_stored_pages(tmp_path, make_crawl):
    make_crawl(
        "example.com",
        JOB_A,
        [
            ("https://example.com/", "2026-09-01T10:00:00+00:00"),
            ("https://example.com/x", "2026-09-01T10:03:00+00:00"),
        ],
    )
    crawl = catalog.find(tmp_path, JOB_A)

    state = catalog.state_from_disk(crawl)

    assert state.status is JobStatus.completed
    assert state.site == "example.com"
    assert state.url == "https://example.com/"
    assert state.pages_crawled == 2
    assert state.started_at == utc(2026, 9, 1, 10, 0)
    assert state.finished_at == utc(2026, 9, 1, 10, 3)
    assert state.max_pages == 0
    assert state.error is None


def test_state_from_disk_for_an_empty_crawl_is_failed(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [])

    state = catalog.state_from_disk(catalog.find(tmp_path, JOB_A))

    assert state.status is JobStatus.failed
    assert state.error


def test_recorded_job_parameters_win_and_naive_datetimes_become_utc(tmp_path, make_crawl):
    make_crawl("example.com", JOB_A, [("https://example.com/", "2026-09-01T10:00:00+00:00")])
    recorded = {
        "start_url": "https://www.example.com/start",
        "max_pages": 50,
        "use_js": True,
        # pymongo returns naive datetimes that are in fact UTC.
        "started_at": datetime(2026, 9, 1, 9, 59, 30),
        "finished_at": datetime(2026, 9, 1, 10, 4, 0),
    }

    state = catalog.state_from_disk(catalog.find(tmp_path, JOB_A), recorded)

    assert state.url == "https://www.example.com/start"
    assert state.max_pages == 50
    assert state.use_js is True
    assert state.started_at == utc(2026, 9, 1, 9, 59, 30)
    assert state.finished_at == utc(2026, 9, 1, 10, 4, 0)
