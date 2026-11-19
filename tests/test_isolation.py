"""The worker-process runner used on Windows (and with FORMULACHECK_ISOLATE=1)."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from _slow_target import sleep_forever
from formulacheck.checks import run_block
from formulacheck.checks.isolate import isolation_needed, run_block_isolated, shutdown
from formulacheck.cli import main
from formulacheck.model import CheckBlock, Status

BLOCKS = [
    "id: a\nkind: symbolic\nsymbols: [x]\nlhs: (x+1)**2\nrhs: x**2 + 2*x + 1\n",
    "id: b\nkind: symbolic\nsymbols: [x]\nlhs: (x+1)**2\nrhs: x**2 + 1\n",
    "id: c\nkind: monte-carlo\nsetup:\n  X: poisson(3)\nexpect: mean(X) == 3\n",
    "id: d\nkind: nope\n",
]


@pytest.fixture(autouse=True)
def _stop_worker() -> Iterator[None]:
    yield
    shutdown()


def test_worker_gives_the_same_results_as_in_process() -> None:
    for raw in BLOCKS:
        block = CheckBlock(line=1, raw=raw)
        here = run_block("t.md", block, set())
        there = run_block_isolated("t.md", block, set())
        assert (there.check_id, there.status, there.message) == (
            here.check_id,
            here.status,
            here.message,
        )


def test_stuck_worker_is_killed_and_replaced() -> None:
    block = CheckBlock(line=3, raw="id: slow\nkind: symbolic\ntimeout: 1\n")
    start = time.monotonic()
    result = run_block_isolated("t.md", block, set(), grace=1.0, target=sleep_forever)
    assert result.status is Status.ERROR and "timed out" in result.message
    assert result.check_id == "slow"
    assert time.monotonic() - start < 10
    # the next block gets a fresh worker
    ok = run_block_isolated("t.md", CheckBlock(line=9, raw=BLOCKS[0]), set())
    assert ok.status is Status.PASS


def test_duplicate_ids_are_detected_in_the_parent() -> None:
    seen: set[str] = set()
    block = CheckBlock(line=1, raw=BLOCKS[0])
    assert run_block_isolated("t.md", block, seen).status is Status.PASS
    assert run_block_isolated("t.md", block, seen).status is Status.ERROR


def test_environment_variable_forces_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FORMULACHECK_ISOLATE", "1")
    assert isolation_needed()
    f = tmp_path / "a.md"
    f.write_text("$$ (x+1)^2 $$\n\n```check\n" + BLOCKS[1] + "```\n")
    assert main([str(f), "--offline", "--no-citations"]) == 1
    assert "FAIL" in capsys.readouterr().out
