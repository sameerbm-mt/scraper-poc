"""Stopping a Scrapy subprocess without losing its queue.

Pause has to be a *graceful* shutdown: Scrapy only writes its pending requests
to JOBDIR while closing down cleanly, so a hard kill loses the frontier and the
resume is no longer exact.

Platforms differ in how that is asked for:

* POSIX — SIGTERM. Scrapy installs a handler for it and closes the spider.
* Windows — there is no way to deliver SIGTERM to another process;
  ``Popen.terminate()`` maps to ``TerminateProcess``, which is the equivalent of
  SIGKILL and skips the flush entirely. The working equivalent is to start the
  child in its own process group and send it a console CTRL+BREAK, which arrives
  as SIGBREAK — a signal Scrapy registers alongside SIGTERM
  (``scrapy/utils/ossignal.py``). This is why the subprocess is created with
  CREATE_NEW_PROCESS_GROUP: without it the event would also hit the worker.

Either way a second, harder stop follows if the process ignores the first.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import struct
import subprocess
import sys
from typing import Any

logger = logging.getLogger("worker.control")

IS_WINDOWS = sys.platform == "win32"

# How long Scrapy gets to finish in-flight requests and flush JOBDIR before we
# stop being polite.
GRACE_SECONDS = 30.0


def creation_flags() -> dict[str, Any]:
    """Keyword arguments that put the child in its own signal group."""
    if IS_WINDOWS:
        # Required for CTRL_BREAK_EVENT to be deliverable to the child alone.
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    # A new session on POSIX keeps our signals off the worker.
    return {"start_new_session": True}


def request_graceful_stop(process: asyncio.subprocess.Process) -> bool:
    """Ask the crawl to shut down cleanly. True when the signal was delivered."""
    if process.returncode is not None:
        return False
    try:
        if IS_WINDOWS:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()  # SIGTERM
        return True
    except (ProcessLookupError, OSError) as exc:
        logger.warning("Could not signal pid %s: %s", process.pid, exc)
        return False


async def stop_gracefully(
    process: asyncio.subprocess.Process, grace: float = GRACE_SECONDS
) -> str:
    """Signal, wait up to `grace`, then kill. Returns how it ended.

    "graceful" means Scrapy exited on its own and JOBDIR is complete;
    "killed" means it overran the grace period and the frontier may be partial;
    "already-exited" means the crawl finished before we asked.
    """
    if process.returncode is not None:
        return "already-exited"

    if not request_graceful_stop(process):
        return "already-exited"

    try:
        await asyncio.wait_for(process.wait(), timeout=grace)
        logger.info("pid %s stopped gracefully", process.pid)
        return "graceful"
    except asyncio.TimeoutError:
        logger.warning(
            "pid %s ignored the shutdown signal after %.0fs; killing it",
            process.pid,
            grace,
        )

    try:
        process.kill()
        await asyncio.wait_for(process.wait(), timeout=10)
    except (ProcessLookupError, OSError, asyncio.TimeoutError) as exc:
        logger.error("Could not kill pid %s: %s", process.pid, exc)
    return "killed"


# queuelib's LifoDiskQueue keeps its length in a big-endian uint32 at the head
# of each priority file, rewritten when the queue closes. Scrapy's default
# SCHEDULER_DISK_QUEUE (PickleLifoDiskQueue) is one of these per priority band,
# under requests.queue/<domain>/<priority>.
_LIFO_HEADER = ">L"
_LIFO_HEADER_SIZE = struct.calcsize(_LIFO_HEADER)


def queued_requests(jobdir: Any) -> int:
    """How many requests JOBDIR still holds, for the "resuming from N" log.

    Best-effort and read-only: an unreadable or unfamiliar jobdir reports 0
    rather than raising, since this only feeds a log line.
    """
    import json
    from pathlib import Path

    root = Path(jobdir) / "requests.queue"
    if not root.exists():
        return 0

    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # A FIFO disk queue keeps its count in info.json instead.
        if path.name == "info.json":
            try:
                size = json.loads(path.read_text(encoding="utf-8")).get("size")
            except (OSError, ValueError):
                continue
            if isinstance(size, int):
                total += size
            continue
        if not path.name.lstrip("-").isdigit():
            continue
        try:
            with path.open("rb") as handle:
                header = handle.read(_LIFO_HEADER_SIZE)
            if len(header) == _LIFO_HEADER_SIZE:
                total += struct.unpack(_LIFO_HEADER, header)[0]
        except OSError:
            continue
    return total


def has_jobdir_state(jobdir: Any) -> bool:
    """True when a previous run left a resumable frontier behind."""
    from pathlib import Path

    root = Path(jobdir)
    if not root.is_dir():
        return False
    return any(root.iterdir())
