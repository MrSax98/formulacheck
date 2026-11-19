"""Shared helpers for the check runners: outcome type, spec validation, time limits."""

from __future__ import annotations

import contextlib
import signal
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..model import Status


class SpecError(ValueError):
    """Raised when a ``check`` block is malformed."""


class CheckTimeout(BaseException):
    """Raised when a check exceeds its time limit.

    Derives from BaseException (like KeyboardInterrupt) so that library code with a
    broad ``except Exception`` cannot swallow it.
    """


@dataclass
class Outcome:
    """What a runner returns; the dispatcher turns it into a CheckResult."""

    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)


DEFAULT_TIMEOUT = 20.0
MAX_TIMEOUT = 120.0


@contextlib.contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    """Raise :class:`CheckTimeout` after *seconds* (Unix main thread only; no-op elsewhere).

    Windows has no SIGALRM; there the runner uses a killable worker process instead
    (see ``checks/isolate.py``).
    """
    if sys.platform == "win32":  # written this way so mypy skips the Unix-only code below
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handler(signum: int, frame: Any) -> None:
        raise CheckTimeout

    previous = signal.signal(signal.SIGALRM, _handler)
    # Re-fire every 0.5 s after the deadline in case the first signal is swallowed.
    signal.setitimer(signal.ITIMER_REAL, seconds, 0.5)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def require_keys(spec: dict[str, Any], required: set[str], optional: set[str]) -> None:
    """Validate that *spec* has all *required* keys and no unknown ones."""
    missing = required - spec.keys()
    if missing:
        raise SpecError(f"missing field(s): {', '.join(sorted(missing))}")
    unknown = spec.keys() - required - optional
    if unknown:
        raise SpecError(f"unknown field(s): {', '.join(sorted(unknown))}")


def get_str(spec: dict[str, Any], key: str) -> str:
    value = spec[key]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)  # YAML reads `rhs: 1` as a number
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"'{key}' must be a non-empty string")
    return value


def get_number(spec: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"'{key}' must be a number")
    if not low <= value <= high:
        raise SpecError(f"'{key}' must be between {low:g} and {high:g}")
    return float(value)


def get_timeout(spec: dict[str, Any]) -> float:
    return get_number(spec, "timeout", DEFAULT_TIMEOUT, 1, MAX_TIMEOUT)
