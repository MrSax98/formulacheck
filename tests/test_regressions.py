"""Regression tests for problems found while reviewing the first implementation."""

import json
import signal
import time
import warnings
from pathlib import Path

import pytest

from formulacheck.checks import run_block
from formulacheck.checks import symbolic as symbolic_module
from formulacheck.citations import extract_references
from formulacheck.cli import main
from formulacheck.model import CheckBlock, Status


def run(body: str):  # type: ignore[no-untyped-def]
    return run_block("t.md", CheckBlock(line=1, raw=body), set())


@pytest.mark.skipif(
    not hasattr(signal, "SIGALRM"), reason="in-process limit is Unix-only; see test_isolation"
)
def test_slow_expression_evaluation_is_bounded_by_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sum/Integral/Limit evaluate eagerly; that evaluation must be inside the time limit."""

    def slow(x: object) -> object:
        while True:
            pass

    monkeypatch.setitem(symbolic_module.SYMBOLIC_FUNCS, "slow", slow)
    start = time.monotonic()
    result = run("id: s\nkind: symbolic\nsymbols: [x]\nlhs: slow(x)\nrhs: x\ntimeout: 1\n")
    assert result.status is Status.ERROR and "timed out" in result.message
    assert time.monotonic() - start < 5


def test_unexpected_library_exception_becomes_an_error_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(x: object) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setitem(symbolic_module.SYMBOLIC_FUNCS, "boom", boom)
    result = run("id: s\nkind: symbolic\nsymbols: [x]\nlhs: boom(x)\nrhs: x\n")
    assert result.status is Status.ERROR and "internal error" in result.message


def test_yaml_aliases_are_rejected() -> None:
    """Aliases allow 'billion laughs' structures that explode when turned into text."""
    body = (
        "id: a\nkind: symbolic\n"
        'x0: &a0 ["lol", "lol", "lol", "lol", "lol", "lol", "lol", "lol", "lol"]\n'
        "x1: &a1 [*a0, *a0, *a0, *a0, *a0, *a0, *a0, *a0, *a0]\n"
        "claim: *a1\n"
    )
    result = run(body)
    assert result.status is Status.ERROR and "aliases" in result.message


def test_oversized_block_is_rejected() -> None:
    result = run("id: a\nkind: symbolic\nclaim: " + "x" * 30_000 + "\n")
    assert result.status is Status.ERROR and "too large" in result.message


def test_missing_kind_has_a_clear_message() -> None:
    result = run("id: a\nlhs: 1\nrhs: 1\n")
    assert result.status is Status.ERROR and "missing field: kind" in result.message


def test_bitwise_on_non_boolean_values_is_an_error_not_a_crash() -> None:
    setup = "setup:\n  X: bernoulli(0.3)\n  Y: bernoulli(0.3)\n"
    wrong = run(f"id: m\nkind: monte-carlo\n{setup}expect: prob(X & Y) == 0.09\n")
    assert wrong.status is Status.ERROR and "BitAnd" in wrong.message
    right = run(f"id: m\nkind: monte-carlo\n{setup}expect: prob((X > 0.5) & (Y > 0.5)) == 0.09\n")
    assert right.status is Status.PASS, right.message


def test_unparenthesised_event_combination_explains_the_fix() -> None:
    body = (
        "id: m\nkind: monte-carlo\nsetup:\n  X: normal(0, 1)\nexpect: prob(X > 0 & X < 1) == 0.34\n"
    )
    result = run(body)
    assert result.status is Status.ERROR and "parentheses" in result.message


def test_tol_accepts_a_plain_number() -> None:
    body = "id: m\nkind: monte-carlo\nsetup:\n  X: poisson(3)\nexpect: mean(X) == 3\ntol: 4\n"
    assert run(body).status is Status.PASS


def test_non_finite_monte_carlo_values_are_errors_without_numpy_warnings() -> None:
    body = "id: m\nkind: monte-carlo\nsetup:\n  X: uniform(0, 1)\nexpect: mean(log(X - 1)) == 0\n"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = run(body)
    assert result.status is Status.ERROR and "not finite" in result.message
    assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]


def test_deterministic_mismatch_keeps_details_json_serialisable() -> None:
    body = "id: m\nkind: monte-carlo\nsetup:\n  X: 1\nexpect: mean(X) == 2\n"
    result = run(body)
    assert result.status is Status.FAIL
    json.dumps(result.details, allow_nan=False)  # would raise on inf/nan


def test_references_inside_code_fences_are_ignored() -> None:
    text = (
        "```text\n## References\n- Fake (2000). Not a reference. doi:10.5555/in.code\n```\n\n"
        "## References\n\n"
        "```markdown\n- Example entry inside a code sample\n```\n"
        "- Efron, B. (1979). Bootstrap methods: another look at the jackknife.\n"
    )
    refs = extract_references(text)
    assert [r.text[:5] for r in refs] == ["Efron"]


def test_terminal_lists_uncovered_equations_of_files_without_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "a.md"
    f.write_text("intro\n\n$$ E[X] = \\mu $$\n")
    assert main([str(f), "--offline", "--no-citations"]) == 0
    out = capsys.readouterr().out
    assert "a.md:3  UNCOVERED" in out and "nothing to check" not in out


def test_bib_with_no_citations_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "a.md"
    f.write_text("text\n")
    bib = tmp_path / "r.bib"
    bib.write_text("@article{a, title={T}, year={2000}}\n")
    main([str(f), "--bib", str(bib), "--no-citations"])
    assert "--bib is ignored" in capsys.readouterr().err


def test_author_must_match_as_a_whole_word() -> None:
    """A real DOI by 'Li' cited as someone else's 'Linear models' paper is a mismatch."""
    from formulacheck.citations import Work, compare_work

    work = Work("Deep residual graphs", "Li", 2000, "10.1/x", "Crossref")
    assert compare_work("Smith, J. (2000). Linear models for data.", work)
    assert not compare_work("Li, W. (2000). Linear models for data.", work)
    assert not compare_work("Smith (2000). Deep residual graphs.", work)  # title matches
