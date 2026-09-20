"""The scrapy-playwright loop thread must shut down without leaving noise behind.

Each case runs in a fresh interpreter: the loop adapter keeps its state on the
class, and the noise this guards against is printed as the process exits.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
NOISE_MARKERS = ("Task was destroyed", "Event loop is closed", "was never awaited")

SCRIPT = """
import sys
sys.path.insert(0, {root!r})
{install}
from scrapy_playwright._loop import _ThreadedLoopAdapter
_ThreadedLoopAdapter.start(1)
_ThreadedLoopAdapter.stop(1)
print("stopped")
"""


def run_script(*, patched: bool) -> subprocess.CompletedProcess[str]:
    install = "from crawler import playwright_shutdown; assert playwright_shutdown.install()"
    source = SCRIPT.format(root=str(BACKEND_ROOT), install=install if patched else "")
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=BACKEND_ROOT,
    )


def noise_in(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [marker for marker in NOISE_MARKERS if marker in result.stderr]


def test_the_patched_shutdown_is_silent():
    result = run_script(patched=True)

    assert result.returncode == 0, result.stderr
    assert "stopped" in result.stdout
    assert noise_in(result) == [], result.stderr


def test_the_upstream_shutdown_is_noisy_which_is_why_the_patch_exists():
    result = run_script(patched=False)

    assert result.returncode == 0, result.stderr
    if not noise_in(result):
        pytest.skip("scrapy-playwright no longer prints this noise; the patch can go")


def test_installing_twice_is_harmless():
    from crawler import playwright_shutdown

    assert playwright_shutdown.install() is True
    assert playwright_shutdown.install() is True
