"""Symbolic and numeric formula checks (sympy backend)."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from typing import Any

import sympy

from ..expr import ExprError, evaluate, parse
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

CONSTANTS: dict[str, Any] = {"pi": sympy.pi, "oo": sympy.oo}

_KNOWN_ASSUMPTIONS = {
    "real",
    "positive",
    "negative",
    "nonnegative",
    "nonpositive",
    "integer",
    "natural",
}


def _sum(f: Any, v: Any, lo: Any, hi: Any) -> Any:
    return sympy.Sum(f, (v, lo, hi)).doit()


def _product(f: Any, v: Any, lo: Any, hi: Any) -> Any:
    return sympy.Product(f, (v, lo, hi)).doit()


def _integral(f: Any, v: Any, lo: Any, hi: Any) -> Any:
    return sympy.Integral(f, (v, lo, hi)).doit()


def _binomial(n: Any, k: Any) -> Any:
    _bounded(n)
    return sympy.binomial(n, k)


def _factorial(n: Any) -> Any:
    _bounded(n)
    return sympy.factorial(n)


def _bounded(value: Any) -> None:
    try:
        if abs(float(value)) > 5000:
            raise ExprError("argument too large (max 5000)")
    except TypeError:
        return  # symbolic argument


SYMBOLIC_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": sympy.sqrt,
    "exp": sympy.exp,
    "log": sympy.log,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "tan": sympy.tan,
    "asin": sympy.asin,
    "acos": sympy.acos,
    "atan": sympy.atan,
    "sinh": sympy.sinh,
    "cosh": sympy.cosh,
    "tanh": sympy.tanh,
    "abs": sympy.Abs,
    "min": sympy.Min,
    "max": sympy.Max,
    "factorial": _factorial,
    "binomial": _binomial,
    "Sum": _sum,
    "Product": _product,
    "Integral": _integral,
    "Derivative": lambda f, v: sympy.diff(f, v),
    "Limit": lambda f, v, p: sympy.limit(f, v, p),
}


def build_symbols(spec: Mapping[str, Any]) -> tuple[dict[str, sympy.Symbol], dict[str, set[str]]]:
    """Create sympy symbols from ``symbols`` (list or mapping) and optional ``assume``."""
    raw = spec.get("symbols", [])
    flags: dict[str, set[str]] = {}
    if isinstance(raw, list):
        for name in raw:
            flags[_symbol_name(name)] = set()
    elif isinstance(raw, dict):
        for name, assumption in raw.items():
            flags[_symbol_name(name)] = _parse_assumption(assumption)
    else:
        raise SpecError("'symbols' must be a list of names or a mapping name -> assumptions")
    extra = spec.get("assume", {})
    if not isinstance(extra, dict):
        raise SpecError("'assume' must be a mapping name -> assumptions")
    for name, assumption in extra.items():
        name = _symbol_name(name)
        if name not in flags:
            raise SpecError(f"'assume' refers to undeclared symbol '{name}'")
        flags[name] |= _parse_assumption(assumption)
    symbols = {n: sympy.Symbol(n, **_assumption_kwargs(f)) for n, f in flags.items()}
    return symbols, flags


def _symbol_name(name: Any) -> str:
    if not isinstance(name, str) or not name.isidentifier():
        raise SpecError(f"invalid symbol name {name!r}")
    if name in CONSTANTS or name in SYMBOLIC_FUNCS:
        raise SpecError(f"'{name}' is reserved and cannot be used as a symbol")
    return name


def _parse_assumption(value: Any) -> set[str]:
    items = [s.strip() for s in value.split(",")] if isinstance(value, str) else value
    if items is None:
        return set()
    if not isinstance(items, list):
        raise SpecError("assumptions must be a string like 'positive, integer' or a list")
    flags = {str(i).strip() for i in items if str(i).strip()}
    unknown = flags - _KNOWN_ASSUMPTIONS
    if unknown:
        raise SpecError(f"unknown assumption(s): {', '.join(sorted(unknown))}")
    return flags


def _assumption_kwargs(flags: set[str]) -> dict[str, bool]:
    kwargs = {f: True for f in flags if f != "natural"}
    if "natural" in flags:
        kwargs.update(integer=True, positive=True)
    return kwargs


def _to_sympy(value: Any) -> sympy.Basic:
    if isinstance(value, sympy.Basic):
        return value
    if isinstance(value, int | float):
        return sympy.sympify(value)
    raise ExprError(f"expression evaluated to a non-numeric value ({type(value).__name__})")


def _eval_sym(source: str, env: Mapping[str, Any]) -> sympy.Basic:
    try:
        return _to_sympy(evaluate(parse(source), env, SYMBOLIC_FUNCS))
    except (sympy.SympifyError, NotImplementedError, RecursionError) as exc:
        raise ExprError(f"sympy could not evaluate '{source}': {exc}") from exc


def _sample_value(rng: random.Random, flags: set[str]) -> sympy.Basic:
    positive = "positive" in flags or "natural" in flags
    if "integer" in flags or "natural" in flags:
        if positive:
            return sympy.Integer(rng.randint(1, 8))
        if "nonnegative" in flags:
            return sympy.Integer(rng.randint(0, 8))
        if "negative" in flags:
            return sympy.Integer(rng.randint(-8, -1))
        return sympy.Integer(rng.randint(-5, 5))
    if positive:
        return sympy.Float(rng.uniform(0.5, 3.0))
    if "nonnegative" in flags:
        return sympy.Float(rng.uniform(0.0, 3.0))
    if "negative" in flags:
        return sympy.Float(rng.uniform(-3.0, -0.5))
    if "nonpositive" in flags:
        return sympy.Float(rng.uniform(-3.0, 0.0))
    return sympy.Float(rng.uniform(-3.0, 3.0))


def _numeric_value(expr: sympy.Basic, point: Mapping[sympy.Symbol, Any]) -> complex | None:
    """Evaluate *expr* at *point*; None if undefined there (pole, branch, overflow)."""
    try:
        value = sympy.N(expr.subs(point).doit(), 15)
        result = complex(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError, AttributeError):
        return None
    if result != result or abs(result) == float("inf"):  # NaN or infinite
        return None
    return result


def _close(a: complex, b: complex, rtol: float, atol: float) -> bool:
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


def _fmt(value: complex) -> str:
    if abs(value.imag) < 1e-12:
        return f"{value.real:.10g}"
    return f"{value.real:.8g}{value.imag:+.8g}j"


def _fmt_point(point: Mapping[sympy.Symbol, Any]) -> str:
    return ", ".join(
        f"{k}={float(v):.6g}" for k, v in sorted(point.items(), key=lambda kv: str(kv[0]))
    )


def run_symbolic(spec: dict[str, Any]) -> Outcome:
    """Check ``lhs == rhs`` for all values of the declared symbols."""
    require_keys(
        spec,
        {"id", "kind", "lhs", "rhs"},
        {"claim", "symbols", "assume", "timeout", "rtol", "seed"},
    )
    symbols, flags = build_symbols(spec)
    env: dict[str, Any] = {**CONSTANTS, **symbols}
    lhs_src, rhs_src = get_str(spec, "lhs"), get_str(spec, "rhs")
    rtol = get_number(spec, "rtol", 1e-9, 0, 1)
    seed = int(get_number(spec, "seed", 0, 0, 2**31))
    timeout = get_timeout(spec)

    rng = random.Random(seed)
    valid = 0
    try:
        with time_limit(timeout):
            # Evaluation itself can be slow (Sum, Integral, Limit call doit()): keep it
            # inside the time limit.
            lhs = _eval_sym(lhs_src, env)
            rhs = _eval_sym(rhs_src, env)
            free = sorted((lhs.free_symbols | rhs.free_symbols), key=str)
            for _ in range(60):
                if valid >= 8:
                    break
                point = {s: _sample_value(rng, flags.get(str(s), set())) for s in free}
                a, b = _numeric_value(lhs, point), _numeric_value(rhs, point)
                if a is None or b is None:
                    continue
                valid += 1
                if not _close(a, b, rtol, 1e-12):
                    return Outcome(
                        Status.FAIL,
                        f"lhs != rhs at {_fmt_point(point)}: lhs={_fmt(a)}, rhs={_fmt(b)}",
                        {"counterexample": {str(k): float(v) for k, v in point.items()}},
                    )
            return _prove(lhs, rhs, valid)
    except CheckTimeout:
        if valid >= 3:
            return Outcome(
                Status.INCONCLUSIVE,
                f"consistent at {valid} random points, but the symbolic proof timed out "
                f"after {timeout:g}s",
                {"points": valid},
            )
        return Outcome(Status.ERROR, f"timed out after {timeout:g}s")


def _prove(lhs: sympy.Basic, rhs: sympy.Basic, valid: int) -> Outcome:
    difference = sympy.simplify(lhs - rhs)
    if difference == 0:
        return Outcome(Status.PASS, "proved: simplify(lhs - rhs) == 0", {"method": "simplify"})
    try:
        verdict = lhs.equals(rhs)
    except Exception:  # sympy may raise on hard expressions: treat as "undecided"
        verdict = None
    if verdict is True:
        return Outcome(Status.PASS, "proved: sympy equals() is True", {"method": "equals"})
    if valid < 3:
        return Outcome(
            Status.INCONCLUSIVE,
            f"could not prove it and only {valid} valid random point(s) were available",
        )
    return Outcome(
        Status.INCONCLUSIVE,
        f"numerically consistent at {valid} random points, but not proved symbolically",
        {"points": valid},
    )


def run_numeric(spec: dict[str, Any]) -> Outcome:
    """Check ``lhs == rhs`` at explicitly listed points."""
    require_keys(spec, {"id", "kind", "lhs", "rhs", "points"}, {"claim", "rtol", "atol", "timeout"})
    points = spec["points"]
    if not isinstance(points, list) or not points:
        raise SpecError("'points' must be a non-empty list of mappings name -> value")
    if len(points) > 1000:
        raise SpecError("at most 1000 points are allowed")
    rtol = get_number(spec, "rtol", 1e-9, 0, 1)
    atol = get_number(spec, "atol", 1e-12, 0, 1)
    lhs_src, rhs_src = get_str(spec, "lhs"), get_str(spec, "rhs")
    timeout = get_timeout(spec)

    try:
        with time_limit(timeout):
            for index, raw_point in enumerate(points, start=1):
                env = _point_env(raw_point)
                a = _complex(_eval_sym(lhs_src, env))
                b = _complex(_eval_sym(rhs_src, env))
                if not _close(a, b, rtol, atol):
                    where = ", ".join(f"{k}={v}" for k, v in raw_point.items())
                    return Outcome(
                        Status.FAIL,
                        f"lhs != rhs at point {index} ({where}): lhs={_fmt(a)}, rhs={_fmt(b)}",
                        {"point": index},
                    )
    except CheckTimeout:
        return Outcome(Status.ERROR, f"timed out after {timeout:g}s")
    return Outcome(
        Status.PASS, f"lhs == rhs at all {len(points)} point(s)", {"points": len(points)}
    )


def _point_env(raw_point: Any) -> dict[str, Any]:
    if not isinstance(raw_point, dict) or not raw_point:
        raise SpecError("each point must be a non-empty mapping name -> value")
    env: dict[str, Any] = dict(CONSTANTS)
    for name, value in raw_point.items():
        if not isinstance(name, str) or not name.isidentifier() or name in CONSTANTS:
            raise SpecError(f"invalid variable name {name!r} in points")
        if isinstance(value, str):
            env[name] = _eval_sym(value, CONSTANTS)
        elif isinstance(value, bool) or not isinstance(value, int | float):
            raise SpecError(f"value of '{name}' must be a number or a constant expression")
        elif isinstance(value, float):
            env[name] = sympy.Float(value, 30)
        else:
            env[name] = sympy.Integer(value)
    return env


def _complex(value: sympy.Basic) -> complex:
    try:
        result = complex(sympy.N(value.doit(), 15))
    except (TypeError, ValueError) as exc:
        raise ExprError("expression is not a finite number at this point") from exc
    if result != result or abs(result) == float("inf"):
        raise ExprError("expression is not a finite number at this point")
    return result
