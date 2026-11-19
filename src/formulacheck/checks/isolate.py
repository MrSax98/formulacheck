"""Run check blocks in a worker process that can be killed.

On Linux and macOS the time limit uses SIGALRM inside the process (fast). Windows has no
SIGALRM, so there each block runs in a single reusable worker process instead; if a block
exceeds its time limit the worker is terminated and a new one is started for the next block.
Set ``FORMULACHECK_ISOLATE=1`` to use the worker on any platform.
"""

from __future__ import annotations

import atexit
import multiprocessing
import os
import signal
import threading
from collections.abc import Callable
from multiprocessing.pool import Pool
from typing import Any

from ..model import CheckBlock, CheckResult, Status
from . import _load_spec, run_block
from .base import DEFAULT_TIMEOUT, MAX_TIMEOUT, SpecError

STARTUP_GRACE = 15.0  # seconds allowed for the worker to start and import sympy/numpy

_pool: Pool | None = None


def isolation_needed() -> bool:
    """True when in-process time limits are unavailable, or isolation was requested."""
    if os.environ.get("FORMULACHECK_ISOLATE", "").strip() not in ("", "0"):
        return True
    no_alarm = not hasattr(signal, "SIGALRM")
    return no_alarm or threading.current_thread() is not threading.main_thread()


def shutdown() -> None:
    """Stop the worker process, if any."""
    global _pool
    if _pool is not None:
        _pool.terminate()
        _pool.join()
        _pool = None


atexit.register(shutdown)


def _worker() -> Pool:
    global _pool
    if _pool is None:
        _pool = multiprocessing.get_context("spawn").Pool(processes=1)
    return _pool


def _run_in_worker(path: str, block: CheckBlock) -> CheckResult:
    return run_block(path, block, set())


def _peek(raw: str) -> tuple[str | None, str, float]:
    """Read id, kind and timeout without running anything (for duplicate and timeout handling)."""
    try:
        spec = _load_spec(raw)
    except SpecError:
        return None, "?", DEFAULT_TIMEOUT
    timeout = spec.get("timeout", DEFAULT_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float):
        timeout = DEFAULT_TIMEOUT
    timeout = min(max(float(timeout), 1.0), MAX_TIMEOUT)
    check_id = str(spec["id"]) if "id" in spec else None
    return check_id, str(spec.get("kind", "?")), timeout


def run_block_isolated(
    path: str,
    block: CheckBlock,
    seen_ids: set[str],
    *,
    grace: float = STARTUP_GRACE,
    target: Callable[[str, CheckBlock], Any] = _run_in_worker,
) -> CheckResult:
    """Like :func:`run_block`, but in the worker process, killed after the time limit."""
    check_id, kind, timeout = _peek(block.raw)
    eq = block.equation
    if check_id is not None and check_id in seen_ids:
        return CheckResult(
            path,
            block.line,
            check_id,
            kind,
            Status.ERROR,
            f"duplicate id '{check_id}' in this file",
            equation=eq.tex if eq else None,
            equation_line=eq.line if eq else None,
        )
    pending = _worker().apply_async(target, (path, block))
    try:
        result: CheckResult = pending.get(timeout + grace)
    except multiprocessing.TimeoutError:
        shutdown()  # the worker may be stuck in C code: kill it
        result = CheckResult(
            path,
            block.line,
            check_id or f"check-L{block.line}",
            kind,
            Status.ERROR,
            f"timed out after {timeout:g}s (worker process stopped)",
            equation=eq.tex if eq else None,
            equation_line=eq.line if eq else None,
        )
    seen_ids.add(result.check_id)
    return result
