import os
import signal
import time
from pathlib import Path

import pytest

from formulacheck.checks import run_block
from formulacheck.checks.base import CheckTimeout, time_limit
from formulacheck.model import CheckBlock, Status


def run(body: str, seen: set[str] | None = None):  # type: ignore[no-untyped-def]
    return run_block("t.md", CheckBlock(line=1, raw=body), seen if seen is not None else set())


def symbolic(lhs: str, rhs: str, symbols: str = "[x]") -> str:
    return f"id: s\nkind: symbolic\nsymbols: {symbols}\nlhs: {lhs}\nrhs: {rhs}\n"


# --- symbolic -------------------------------------------------------------------------

TRUE_IDENTITIES = [
    ("(x+1)**2", "x**2 + 2*x + 1", "[x]"),
    ("sin(x)**2 + cos(x)**2", "1", "[x]"),
    ("exp(x)*exp(2)", "exp(x+2)", "[x]"),
    ("Sum(k, k, 1, n)", "n*(n+1)/2", "{n: natural, k: natural}"),
    ("Sum(2*k - 1, k, 1, n)", "n**2", "{n: natural, k: natural}"),
    ("Derivative(x**3, x)", "3*x**2", "[x]"),
    ("binomial(n, 2)", "n*(n-1)/2", "{n: natural}"),
    ("log(x*y)", "log(x) + log(y)", "{x: positive, y: positive}"),
]


@pytest.mark.parametrize(("lhs", "rhs", "symbols"), TRUE_IDENTITIES)
def test_true_identities_pass(lhs: str, rhs: str, symbols: str) -> None:
    result = run(symbolic(lhs, rhs, symbols))
    assert result.status is Status.PASS, result.message


# Each wrong claim is a deliberate mutation of a true identity: it must be caught.
MUTATIONS = [
    ("(x+1)**2", "x**2 + x + 1", "[x]"),
    ("sin(x)**2 + cos(x)**2", "2", "[x]"),
    ("exp(x)*exp(2)", "exp(x)+exp(2)", "[x]"),
    ("Sum(k, k, 1, n)", "n*(n-1)/2", "{n: natural, k: natural}"),
    ("Sum(2*k - 1, k, 1, n)", "n**2 + 1", "{n: natural, k: natural}"),
    ("Derivative(x**3, x)", "2*x**2", "[x]"),
    ("binomial(n, 2)", "n*(n+1)/2", "{n: natural}"),
    ("log(x*y)", "log(x)*log(y)", "{x: positive, y: positive}"),
]


@pytest.mark.parametrize(("lhs", "rhs", "symbols"), MUTATIONS)
def test_mutated_identities_fail(lhs: str, rhs: str, symbols: str) -> None:
    result = run(symbolic(lhs, rhs, symbols))
    assert result.status is Status.FAIL, result.message
    assert "counterexample" in result.details


def test_numerically_consistent_but_unproved_is_inconclusive_not_pass() -> None:
    result = run(symbolic("tan(2*x)", "2*tan(x)/(1-tan(x)**2)", "{x: real}"))
    assert result.status is Status.INCONCLUSIVE


def test_numeric_literal_on_one_side() -> None:
    assert run(symbolic("sin(x)**2 + cos(x)**2", "1")).status is Status.PASS


def test_symbolic_uses_assumptions() -> None:
    # sqrt(x**2) == x only holds for non-negative x
    assert run(symbolic("sqrt(x**2)", "x", "{x: positive}")).status is Status.PASS
    assert run(symbolic("sqrt(x**2)", "x", "{x: real}")).status is Status.FAIL


# --- numeric --------------------------------------------------------------------------


def test_numeric_pass_and_fail() -> None:
    ok = "id: n\nkind: numeric\nlhs: sqrt(x)**2\nrhs: x\npoints: [{x: 4}, {x: 2.5}]\n"
    bad = "id: n\nkind: numeric\nlhs: x**2\nrhs: 2*x\npoints: [{x: 2}, {x: 3}]\n"
    assert run(ok).status is Status.PASS
    result = run(bad)
    assert result.status is Status.FAIL and result.details["point"] == 2


def test_numeric_accepts_constants_in_points() -> None:
    body = "id: n\nkind: numeric\nlhs: sin(x)\nrhs: 1\npoints: [{x: pi/2}]\n"
    assert run(body).status is Status.PASS


def test_numeric_undefined_point_is_error() -> None:
    body = "id: n\nkind: numeric\nlhs: 1/x\nrhs: 1\npoints: [{x: 0}]\n"
    assert run(body).status is Status.ERROR


# --- monte carlo ----------------------------------------------------------------------


def mc(setup: str, expect: str, extra: str = "") -> str:
    return f"id: m\nkind: monte-carlo\nsetup:\n{setup}\nexpect: {expect}\n{extra}"


MC_TRUE = [
    ("  X: bernoulli(p)\n  p: 0.3", "variance(X) == p*(1-p)"),
    ("  X: poisson(4)", "mean(X) == 4"),
    ("  X: poisson(4)", "variance(X) == 4"),
    ("  X: exponential(2)", "mean(X) == 1/2"),
    ("  X: exponential(2)", "variance(X) == 1/4"),
    ("  X: normal(1, 2)\n  Y: normal(0, 1)\n  S: X + Y", "variance(S) == 5"),
    ("  X: normal(0, 1)", "prob(X > 0) == 0.5"),
    ("  X: uniform(0, 1)", "variance(X) == 1/12"),
    ("  X: binomial(10, 0.4)", "mean(X) == 4"),
    ("  X: geometric(0.25)", "mean(X) == 4"),
    ("  X: chi2(3)", "mean(X) == 3"),
]
MC_WRONG = [
    ("  X: bernoulli(p)\n  p: 0.3", "variance(X) == p"),
    ("  X: poisson(4)", "variance(X) == 2"),
    ("  X: exponential(2)", "variance(X) == 1/2"),
    ("  X: normal(1, 2)\n  Y: normal(0, 1)\n  S: X + Y", "variance(S) == 3"),
    ("  X: normal(0, 1)", "prob(X > 0) == 0.6"),
    ("  X: uniform(0, 1)", "variance(X) == 1/6"),
    ("  X: binomial(10, 0.4)", "mean(X) == 5"),
    ("  X: geometric(0.25)", "mean(X) == 3"),
    ("  X: chi2(3)", "mean(X) == 2"),
]


@pytest.mark.parametrize(("setup", "expect"), MC_TRUE)
def test_true_probability_claims_pass(setup: str, expect: str) -> None:
    result = run(mc(setup, expect))
    assert result.status is Status.PASS, result.message


@pytest.mark.parametrize(("setup", "expect"), MC_WRONG)
def test_wrong_probability_claims_fail(setup: str, expect: str) -> None:
    result = run(mc(setup, expect))
    assert result.status is Status.FAIL, result.message


def test_monte_carlo_is_repeatable() -> None:
    body = mc("  X: normal(0, 1)", "mean(X) == 0")
    assert run(body).message == run(body).message


def test_independent_variables_are_uncorrelated() -> None:
    body = mc("  X: normal(0, 1)\n  Y: normal(0, 1)", "corr(X, Y) == 0")
    assert run(body).status is Status.PASS


def test_dependent_variables_are_detected() -> None:
    body = mc("  X: normal(0, 1)\n  Z: normal(0, 1)\n  Y: X + Z", "corr(X, Y) == 0")
    assert run(body).status is Status.FAIL


def test_distribution_inside_expression_gives_a_helpful_error() -> None:
    result = run(mc("  X: normal(0, 1)\n  Y: X + normal(0, 1)", "corr(X, Y) == 0"))
    assert result.status is Status.ERROR and "own line" in result.message


def test_invalid_parameters_are_errors() -> None:
    assert run(mc("  X: bernoulli(1.5)", "mean(X) == 1")).status is Status.ERROR
    assert run(mc("  X: normal(0, -1)", "mean(X) == 0")).status is Status.ERROR


def test_expect_must_be_an_equality_of_numbers() -> None:
    assert run(mc("  X: normal(0, 1)", "mean(X) < 1")).status is Status.ERROR
    assert run(mc("  X: normal(0, 1)", "X == 0")).status is Status.ERROR


def test_circular_or_unknown_setup_names_are_errors() -> None:
    assert run(mc("  X: normal(a, 1)\n  a: X", "mean(X) == 0")).status is Status.ERROR


def test_sample_size_is_bounded() -> None:
    assert run(mc("  X: normal(0, 1)", "mean(X) == 0", "n: 100000000000\n")).status is Status.ERROR
    assert run(mc("  X: normal(0, 1)", "mean(X) == 0", "n: 10\n")).status is Status.ERROR


# --- block validation and safety -----------------------------------------------------


def test_malformed_blocks_are_errors_not_crashes() -> None:
    for body in [
        "",
        "just text",
        "- a\n- b",
        "id: x\nkind: nope",
        "id: x\nkind: symbolic",
        "id: x\nkind: symbolic\nlhs: 1\nrhs: 1\nbogus: 1",
        "a: [unclosed",
    ]:
        assert run(body).status is Status.ERROR


def test_duplicate_ids_are_reported() -> None:
    seen: set[str] = set()
    body = symbolic("x", "x")
    assert run(body, seen).status is Status.PASS
    assert run(body, seen).status is Status.ERROR


def test_malicious_blocks_cannot_execute_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = tmp_path / "pwned"
    payloads = [
        f"__import__('os').system('touch {sentinel}')",
        f"open('{sentinel}', 'w')",
        "().__class__.__bases__[0].__subclasses__()",
    ]
    for payload in payloads:
        for spec in (
            f'id: a\nkind: symbolic\nsymbols: [x]\nlhs: "{payload}"\nrhs: x\n',
            f'id: b\nkind: numeric\nlhs: "{payload}"\nrhs: 1\npoints: [{{x: 1}}]\n',
            f'id: c\nkind: monte-carlo\nsetup:\n  X: "{payload}"\nexpect: mean(X) == 0\n',
        ):
            assert run(spec).status is Status.ERROR
    assert not sentinel.exists()
    assert os.listdir(tmp_path) == []


def test_yaml_cannot_instantiate_python_objects(tmp_path: Path) -> None:
    sentinel = tmp_path / "yaml-pwned"
    body = f"id: y\nkind: !!python/object/apply:os.system ['touch {sentinel}']\n"
    assert run(body).status is Status.ERROR
    assert not sentinel.exists()


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM is Unix-only")
def test_time_limit_interrupts_long_computation() -> None:
    start = time.monotonic()
    with pytest.raises(CheckTimeout), time_limit(0.2):
        while True:
            pass
    assert time.monotonic() - start < 3
