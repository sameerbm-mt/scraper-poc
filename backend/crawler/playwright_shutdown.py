"""Stop scrapy-playwright's loop thread without leaving tasks behind.

On Windows scrapy-playwright runs Playwright on its own event loop in a
background thread, for every crawl, JS or not. Its ``stop()`` schedules
``queue.join()`` and then stops that loop while ``_process_queue()`` is still
parked on ``queue.get()``. When the process exits Python reports two pending
tasks that were destroyed, then "RuntimeError: Event loop is closed" and "coroutine
'Queue.join' was never awaited".

It does no harm, but it prints on every crawl, and it fills the end of the log
that is kept when a job fails, burying the actual error.

``install()`` swaps in a ``stop()`` that cancels what is left on the loop before
stopping it. By the time the handler calls ``stop()`` it has already closed its
browser and contexts, so the only tasks left are those two idle ones.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_CLEANUP_TIMEOUT_SECONDS = 10


def install() -> bool:
    """Patch ``_ThreadedLoopAdapter.stop``. True when the patch was applied."""
    try:
        from scrapy_playwright._loop import _ThreadedLoopAdapter
    except ImportError:  # scrapy-playwright missing, or its layout changed
        return False
    if getattr(_ThreadedLoopAdapter.stop, "_quiet", False):
        return True

    def stop(cls: type[_ThreadedLoopAdapter], download_handler_id: int) -> None:
        cls._stop_events[download_handler_id].set()
        if not all(event.is_set() for event in cls._stop_events.values()):
            return  # another download handler is still using the loop

        async def cancel_leftovers() -> None:
            current = asyncio.current_task()
            leftovers = [task for task in asyncio.all_tasks() if task is not current]
            for task in leftovers:
                task.cancel()
            await asyncio.gather(*leftovers, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(cancel_leftovers(), cls._loop).result(
                timeout=_CLEANUP_TIMEOUT_SECONDS
            )
        except Exception:  # cleanup must never turn a finished crawl into a failure
            logger.debug("could not drain the Playwright loop", exc_info=True)
        cls._loop.call_soon_threadsafe(cls._loop.stop)
        cls._thread.join()

    stop._quiet = True  # type: ignore[attr-defined]
    _ThreadedLoopAdapter.stop = classmethod(stop)  # type: ignore[method-assign]
    return True
