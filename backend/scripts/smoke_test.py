#!/usr/bin/env python
"""End-to-end smoke test: POST a crawl, poll it, assert the results hold up.

The API and the ARQ worker must already be running.

    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --url https://example.com --max-pages 20
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_TARGET = "https://elfsight.com"
MIN_EXPECTED_PAGES = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--url", default=DEFAULT_TARGET, help="site to crawl")
    parser.add_argument(
        "--max-pages", type=int, default=20, help="0 crawls the whole site"
    )
    parser.add_argument("--use-js", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600, help="seconds to wait")
    parser.add_argument(
        "--min-pages",
        type=int,
        default=MIN_EXPECTED_PAGES,
        help="fail if fewer pages than this were crawled",
    )
    return parser.parse_args()


class SmokeTestFailure(Exception):
    pass


def check(condition: bool, message: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {message}")
    if not condition:
        raise SmokeTestFailure(message)


def fetch_all_results(client: httpx.Client, api: str, job_id: str) -> list[dict[str, Any]]:
    """Page through GET /results until every summary is collected."""
    items: list[dict[str, Any]] = []
    page, size = 1, 20
    while True:
        response = client.get(
            f"{api}/api/jobs/{job_id}/results", params={"page": page, "size": size}
        )
        response.raise_for_status()
        body = response.json()
        items.extend(body["items"])
        if page >= body["total_pages"] or not body["items"]:
            return items
        page += 1


def print_summary_table(items: list[dict[str, Any]]) -> None:
    headers = ("#", "STATUS", "DEPTH", "WORDS", "HASH", "TITLE", "URL")
    rows = [
        (
            str(item["index"]),
            str(item["status_code"] or "-"),
            str(item["depth"]),
            str(item["word_count"]),
            item["content_hash"][:8],
            _truncate(item["title"], 34),
            _truncate(item["url"], 52),
        )
        for item in items
    ]
    widths = [
        max(len(headers[col]), *(len(row[col]) for row in rows)) if rows else len(headers[col])
        for col in range(len(headers))
    ]
    line = "  ".join("-" * width for width in widths)

    print()
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print(line)
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    print(line)


def _truncate(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def main() -> int:
    args = parse_args()
    api = args.api.rstrip("/")

    with httpx.Client(timeout=30.0) as client:
        print(f"→ API      {api}")
        try:
            client.get(f"{api}/health").raise_for_status()
        except httpx.HTTPError as exc:
            print(f"\nCannot reach the API at {api}: {exc}")
            print("Start it with: uv run uvicorn app.main:app --port 8000")
            return 2

        print(f"→ Target   {args.url}")
        limit = args.max_pages if args.max_pages > 0 else "whole site"
        print(f"→ Limits   max_pages={limit} use_js={args.use_js}")

        response = client.post(
            f"{api}/api/crawl",
            json={
                "url": args.url,
                "max_pages": args.max_pages,
                "use_js": args.use_js,
            },
        )
        response.raise_for_status()
        job_id = response.json()["job_id"]
        print(f"→ Job      {job_id}\n")

        state = poll(client, api, job_id, args.timeout)
        print()

        try:
            check(
                state["status"] == "completed",
                f"job completed (status={state['status']}"
                + (f", error={_truncate(state.get('error') or '', 200)}" if state.get("error") else "")
                + ")",
            )

            items = fetch_all_results(client, api, job_id)
            check(
                len(items) >= args.min_pages,
                f"crawled at least {args.min_pages} pages (got {len(items)})",
            )
            if args.max_pages > 0:
                check(
                    len(items) <= args.max_pages,
                    f"respected max_pages={args.max_pages} (got {len(items)})",
                )

            hashes = [item["content_hash"] for item in items]
            check(
                len(set(hashes)) == len(hashes),
                f"all {len(hashes)} content hashes are unique",
            )
            check(
                all(item["word_count"] > 0 for item in items),
                "every page has a non-zero word count",
            )
            # Markdown is only served by the detail route; check each page has it.
            empty: list[str] = []
            for item in items:
                detail = client.get(f"{api}/api/jobs/{job_id}/results/{item['index']}")
                detail.raise_for_status()
                if not detail.json().get("markdown", "").strip():
                    empty.append(item["url"])
            check(not empty, f"every page has non-empty markdown ({len(items)} checked)")

            export = client.get(f"{api}/api/jobs/{job_id}/export")
            check(
                export.status_code == 200 and len(export.content) > 0,
                f"export returns pages.jsonl ({len(export.content):,} bytes)",
            )
            check(
                len(export.text.strip().splitlines()) == len(items),
                "export line count matches the results count",
            )

            print_summary_table(items)

            words = sorted(item["word_count"] for item in items)
            print(
                f"\n{len(items)} pages | "
                f"{sum(words):,} words total | "
                f"median {words[len(words) // 2]:,} | "
                f"failed {state['pages_failed']}"
            )
            print("\nSMOKE TEST PASSED")
            return 0

        except SmokeTestFailure:
            print("\nSMOKE TEST FAILED")
            return 1


def poll(client: httpx.Client, api: str, job_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        response = client.get(f"{api}/api/jobs/{job_id}")
        response.raise_for_status()
        state = response.json()
        line = (
            f"  {state['status']:<10} "
            f"crawled={state['pages_crawled']:<4} failed={state['pages_failed']}"
        )
        if line != last:
            print(line)
            last = line
        if state["status"] in ("completed", "failed"):
            return state
        time.sleep(2)

    print(f"  timed out after {timeout}s")
    return client.get(f"{api}/api/jobs/{job_id}").json()


if __name__ == "__main__":
    raise SystemExit(main())
