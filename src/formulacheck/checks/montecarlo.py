"""Monte Carlo checks: simulate random variables and test a claim statistically.

The claim ``lhs == rhs`` is evaluated on K independent batches. The batch-to-batch
spread of ``lhs - rhs`` gives a standard error for any estimator (mean, variance,
probability, correlation, ...), so no per-statistic formula is needed. The check passes
when the mean difference is within ``tol`` standard errors of zero.

A pass is statistical evidence, not a proof. The seed is fixed, so results are repeatable.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable
from typing import Any

import numpy as np

from ..expr import MAX_SOURCE_CHARS, ExprError, evaluate, names_in, parse
from ..model import Status
from .base import (
    CheckTimeout,
    Outcome,
    SpecError,
    get_number,
    get_str,
    get_timeout,
    require_keys,
    time_limit,
)

BATCHES = 50
MIN_N = 5_000
MAX_N = 5_000_000
DEFAULT_N = 200_000
DEFAULT_SIGMA = 4.0
_TOL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*sigma\s*$", re.IGNORECASE)


def _scalar(value: Any, name: str) -> float:
    if np.ndim(value) != 0:
        raise ExprError(f"parameter of {name}(...) must be a number, not a random variable")
    return float(value)


def _distributions(rng: np.random.Generator, n: int) -> dict[str, Callable[..., Any]]:
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise ExprError(msg)

    def bernoulli(p: Any) -> Any:
        p = _scalar(p, "bernoulli")
        need(0 <= p <= 1, "bernoulli(p) needs 0 <= p <= 1")
        return (rng.random(n) < p).astype(float)

    def binomial(k: Any, p: Any) -> Any:
        k, p = _scalar(k, "binomial"), _scalar(p, "binomial")
        need(
            k >= 0 and k == int(k) and k <= 1_000_000, "binomial(n, p) needs integer 0 <= n <= 1e6"
        )
        need(0 <= p <= 1, "binomial(n, p) needs 0 <= p <= 1")
        return rng.binomial(int(k), p, n).astype(float)

    def poisson(lam: Any) -> Any:
        lam = _scalar(lam, "poisson")
        need(0 <= lam <= 1e7, "poisson(lam) needs 0 <= lam <= 1e7")
        return rng.poisson(lam, n).astype(float)

    def geometric(p: Any) -> Any:
        p = _scalar(p, "geometric")
        need(0 < p <= 1, "geometric(p) needs 0 < p <= 1 (support is 1, 2, 3, ...)")
        return rng.geometric(p, n).astype(float)

    def uniform(a: Any, b: Any) -> Any:
        a, b = _scalar(a, "uniform"), _scalar(b, "uniform")
        need(a < b, "uniform(a, b) needs a < b")
        return rng.uniform(a, b, n)

    def normal(mu: Any, sigma: Any) -> Any:
        mu, sigma = _scalar(mu, "normal"), _scalar(sigma, "normal")
        need(sigma > 0, "normal(mu, sigma) needs sigma > 0 (standard deviation, not variance)")
        return rng.normal(mu, sigma, n)

    def exponential(rate: Any) -> Any:
        rate = _scalar(rate, "exponential")
        need(rate > 0, "exponential(rate) needs rate > 0 (rate, not mean)")
        return rng.exponential(1.0 / rate, n)

    def gamma(shape: Any, rate: Any) -> Any:
        shape, rate = _scalar(shape, "gamma"), _scalar(rate, "gamma")
        need(shape > 0 and rate > 0, "gamma(shape, rate) needs shape > 0 and rate > 0")
        return rng.gamma(shape, 1.0 / rate, n)

    def beta(a: Any, b: Any) -> Any:
        a, b = _scalar(a, "beta"), _scalar(b, "beta")
        need(a > 0 and b > 0, "beta(a, b) needs a > 0 and b > 0")
        return rng.beta(a, b, n)

    def student_t(df: Any) -> Any:
        df = _scalar(df, "t")
        need(df > 0, "t(df) needs df > 0")
        return rng.standard_t(df, n)

    def chi2(df: Any) -> Any:
        df = _scalar(df, "chi2")
        need(df > 0, "chi2(df) needs df > 0")
        return rng.chisquare(df, n)

    return {
        "bernoulli": bernoulli,
        "binomial": binomial,
        "poisson": poisson,
        "geometric": geometric,
        "uniform": uniform,
        "normal": normal,
        "exponential": exponential,
        "gamma": gamma,
        "beta": beta,
        "t": student_t,
        "chi2": chi2,
    }


def _stat_funcs() -> dict[str, Callable[..., Any]]:
    def mean(a: Any) -> Any:
        return np.mean(a)

    def variance(a: Any) -> Any:
        return np.var(a, ddof=1) if np.size(a) > 1 else 0.0

    def std(a: Any) -> Any:
        return np.std(a, ddof=1) if np.size(a) > 1 else 0.0

    def cov(a: Any, b: Any) -> Any:
        return np.cov(a, b, ddof=1)[0, 1]

    def corr(a: Any, b: Any) -> Any:
        return np.corrcoef(a, b)[0, 1]

    def quantile(a: Any, q: Any) -> Any:
        if not 0 <= float(q) <= 1:
            raise ExprError("quantile(x, q) needs 0 <= q <= 1")
        return np.quantile(a, float(q))

    def prob(event: Any) -> Any:
        return np.mean(np.asarray(event, dtype=float))

    return {
        "mean": mean,
        "E": mean,
        "variance": variance,
        "var": variance,
        "std": std,
        "cov": cov,
        "corr": corr,
        "quantile": quantile,
        "prob": prob,
        "sqrt": np.sqrt,
        "exp": np.exp,
        "log": np.log,
        "abs": np.abs,
        "sin": np.sin,
        "cos": np.cos,
        "minimum": np.minimum,
        "maximum": np.maximum,
    }


def _parse_tol(spec: dict[str, Any]) -> float:
    raw = spec.get("tol", DEFAULT_SIGMA)
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        value = float(raw)  # `tol: 4` means 4 sigma
    else:
        match = _TOL_RE.match(str(raw))
        if not match:
            raise SpecError("'tol' must look like '4sigma'")
        value = float(match.group(1))
    if not 1 <= value <= 10:
        raise SpecError("'tol' must be between 1sigma and 10sigma")
    return value


def _split_claim(source: str) -> tuple[ast.expr, ast.expr]:
    """Split ``lhs == rhs`` into its two sides; the comparison itself is the claim."""
    try:
        if len(source) > 2 * MAX_SOURCE_CHARS:
            raise ExprError(f"'expect' is longer than {2 * MAX_SOURCE_CHARS} characters")
        tree = ast.parse(source.strip(), mode="eval").body
    except (SyntaxError, MemoryError, RecursionError) as exc:
        reason = exc.msg if isinstance(exc, SyntaxError) else "expression too deeply nested"
        raise ExprError(f"syntax error: {reason}") from exc
    if not (
        isinstance(tree, ast.Compare) and len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq)
    ):
        raise SpecError("'expect' must be a single equality: <expression> == <expression>")
    # Re-run the static validation (size, '^', ...) on each side separately.
    lhs = parse(ast.unparse(tree.left))
    rhs = parse(ast.unparse(tree.comparators[0]))
    return lhs, rhs


def run_monte_carlo(spec: dict[str, Any]) -> Outcome:
    require_keys(
        spec,
        {"id", "kind", "setup", "expect"},
        {"claim", "n", "tol", "seed", "timeout"},
    )
    setup = spec["setup"]
    if not isinstance(setup, dict) or not setup:
        raise SpecError("'setup' must be a non-empty mapping name -> distribution or value")
    n_total = int(get_number(spec, "n", DEFAULT_N, MIN_N, MAX_N))
    seed = int(get_number(spec, "seed", 1, 0, 2**31))
    sigma = _parse_tol(spec)
    timeout = get_timeout(spec)
    lhs_node, rhs_node = _split_claim(get_str(spec, "expect"))

    per_batch = n_total // BATCHES
    n = per_batch * BATCHES
    rng = np.random.default_rng(seed)
    dists = _distributions(rng, n)
    funcs = _stat_funcs()

    try:
        # Non-finite results (log(0), 1/0) are reported as errors by _side; silence numpy.
        with time_limit(timeout), np.errstate(all="ignore"):
            env = _build_env(setup, dists, funcs)
            diffs = np.empty(BATCHES)
            for b in range(BATCHES):
                sl = slice(b * per_batch, (b + 1) * per_batch)
                batch_env = {
                    k: (v[sl] if isinstance(v, np.ndarray) and v.shape == (n,) else v)
                    for k, v in env.items()
                }
                diffs[b] = _side(lhs_node, batch_env, funcs) - _side(rhs_node, batch_env, funcs)
            lhs_all = _side(lhs_node, env, funcs)
            rhs_all = _side(rhs_node, env, funcs)
    except CheckTimeout:
        return Outcome(Status.ERROR, f"timed out after {timeout:g}s")

    mean_diff = float(np.mean(diffs))
    se = float(np.std(diffs, ddof=1) / math.sqrt(BATCHES))
    details: dict[str, Any] = {
        "lhs": lhs_all,
        "rhs": rhs_all,
        "n": n,
        "se": se,
        "resolution": sigma * se,
    }
    if se < 1e-12:
        ok = abs(mean_diff) < 1e-9
        z = 0.0 if ok else math.inf
    else:
        z = mean_diff / se
        ok = abs(z) <= sigma
    details["z"] = z if math.isfinite(z) else None  # keep the JSON report valid
    summary = (
        f"lhs~{lhs_all:.6g}, rhs~{rhs_all:.6g}, z={z:.2f} (limit {sigma:g}, n={n}); "
        f"differences below ~{sigma * se:.2g} cannot be detected"
    )
    if ok:
        return Outcome(Status.PASS, "statistically consistent: " + summary, details)
    return Outcome(Status.FAIL, "statistically inconsistent: " + summary, details)


def _build_env(
    setup: dict[str, Any],
    dists: dict[str, Callable[..., Any]],
    funcs: dict[str, Callable[..., Any]],
) -> dict[str, Any]:
    """Resolve ``setup`` in dependency order (so ``X: bernoulli(p)`` may precede ``p: 0.3``)."""
    env: dict[str, Any] = {"pi": math.pi}
    pending: dict[str, ast.expr] = {}
    for name, value in setup.items():
        if not isinstance(name, str) or not name.isidentifier() or name == "pi":
            raise SpecError(f"invalid name {name!r} in setup")
        if name in funcs or name in dists:
            raise SpecError(f"'{name}' is reserved and cannot be used as a variable")
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise SpecError(f"setup value of '{name}' must be a number or an expression")
        if isinstance(value, int | float):
            env[name] = float(value)
        else:
            pending[name] = parse(value)
    while pending:
        ready = [n for n, node in pending.items() if names_in(node) <= env.keys()]
        if not ready:
            missing = sorted({m for node in pending.values() for m in names_in(node)} - env.keys())
            raise ExprError(f"unknown or circular name(s) in setup: {', '.join(missing)}")
        for name in ready:
            node = pending.pop(name)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in dists
            ):
                if node.keywords:
                    raise ExprError("keyword arguments are not allowed")
                args = [evaluate(a, env, funcs) for a in node.args]
                env[name] = dists[node.func.id](*args)
            else:
                try:
                    env[name] = evaluate(node, env, funcs, allow_compare=True, allow_bitwise=True)
                except ExprError as exc:
                    if any(f"'{d}'" in str(exc) for d in dists):
                        raise ExprError(
                            f"{exc}; declare each random variable on its own line in 'setup'"
                        ) from exc
                    raise
    return env


def _side(node: ast.expr, env: dict[str, Any], funcs: dict[str, Callable[..., Any]]) -> float:
    value = evaluate(node, env, funcs, allow_compare=True, allow_bitwise=True)
    if np.ndim(value) != 0:
        raise ExprError("each side of 'expect' must be a single number (use mean(...), prob(...))")
    result = float(value)
    if not math.isfinite(result):
        raise ExprError("expression is not finite")
    return result
