"""Restricted expression language.

Expressions found in ``check`` blocks come from Markdown files that may have been
written by an LLM, so they are never passed to ``eval``. Instead the source is parsed
with :mod:`ast` and only a small whitelist of node types is walked. Names are looked up
in an explicit environment, calls go through an explicit function table, and there is
no attribute access, no subscript, no comprehension and no import.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from typing import Any

MAX_SOURCE_CHARS = 1000
MAX_NODES = 300
MAX_EXPONENT = 10_000
MAX_POW_BITS = 1_000_000


class ExprError(ValueError):
    """Raised when an expression is invalid, unsafe or cannot be evaluated."""


_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_BIT_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
}
_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def parse(source: str) -> ast.expr:
    """Parse and statically validate *source*; return the expression node."""
    if not isinstance(source, str):
        raise ExprError(f"expression must be a string, got {type(source).__name__}")
    source = source.strip()
    if not source:
        raise ExprError("empty expression")
    if len(source) > MAX_SOURCE_CHARS:
        raise ExprError(f"expression longer than {MAX_SOURCE_CHARS} characters")
    if "^" in source:
        raise ExprError("'^' is not allowed; use '**' for powers")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"syntax error: {exc.msg}") from exc
    count = sum(1 for _ in ast.walk(tree))
    if count > MAX_NODES:
        raise ExprError(f"expression too complex ({count} nodes, max {MAX_NODES})")
    return tree.body


def names_in(node: ast.expr) -> set[str]:
    """Names used as variables (not as called functions) in *node*."""
    called = {
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} - called


def evaluate(
    node: ast.expr,
    env: Mapping[str, Any],
    funcs: Mapping[str, Callable[..., Any]],
    *,
    allow_compare: bool = False,
    allow_bitwise: bool = False,
    number: Callable[[int | float], Any] | None = None,
) -> Any:
    """Evaluate a validated AST node against *env* (variables) and *funcs* (calls).

    *number* converts numeric literals (e.g. to exact sympy rationals, so that ``1/2``
    stays one half instead of becoming the float 0.5).
    """
    return _Evaluator(env, funcs, allow_compare, allow_bitwise, number).visit(node)


class _Evaluator:
    def __init__(
        self,
        env: Mapping[str, Any],
        funcs: Mapping[str, Callable[..., Any]],
        allow_compare: bool,
        allow_bitwise: bool,
        number: Callable[[int | float], Any] | None,
    ) -> None:
        self.env = env
        self.funcs = funcs
        self.allow_compare = allow_compare
        self.allow_bitwise = allow_bitwise
        self.number = number

    def visit(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, int | float):
                raise ExprError(f"only numbers are allowed as literals, got {node.value!r}")
            return self.number(node.value) if self.number else node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise ExprError(f"unknown name '{node.id}'")
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self.visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +self.visit(node.operand)
            raise ExprError("unsupported unary operator")
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ExprError(f"{type(node).__name__} is not allowed in expressions")

    def _binop(self, node: ast.BinOp) -> Any:
        left, right = self.visit(node.left), self.visit(node.right)
        op = type(node.op)
        if op is ast.Pow:
            _check_power(left, right)
            func: Callable[[Any, Any], Any] = operator.pow
        elif op in _BIN_OPS:
            func = _BIN_OPS[op]
        elif op in _BIT_OPS and self.allow_bitwise:
            func = _BIT_OPS[op]
        else:
            raise ExprError(f"operator {op.__name__} is not allowed")
        try:
            return func(left, right)
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ExprError(f"operator {op.__name__} failed: {exc}") from exc

    def _compare(self, node: ast.Compare) -> Any:
        if not self.allow_compare:
            raise ExprError("comparisons are not allowed here")
        if len(node.ops) != 1:
            raise ExprError("chained comparisons are not allowed (use parentheses with & and |)")
        op = type(node.ops[0])
        if op not in _CMP_OPS:
            raise ExprError("only <, <=, >, >= are allowed inside expressions")
        left, right = self.visit(node.left), self.visit(node.comparators[0])
        try:
            return _CMP_OPS[op](left, right)
        except (TypeError, ValueError) as exc:
            raise ExprError(f"comparison failed: {exc}") from exc

    def _call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ExprError("only plain function names can be called")
        if node.keywords:
            raise ExprError("keyword arguments are not allowed")
        name = node.func.id
        if name not in self.funcs:
            raise ExprError(f"unknown function '{name}'")
        args = [self.visit(a) for a in node.args]
        try:
            return self.funcs[name](*args)
        except ExprError:
            raise
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ExprError(f"{name}(...) failed: {exc}") from exc


def _check_power(base: Any, exponent: Any) -> None:
    """Reject powers that could exhaust CPU or memory (e.g. 9**9**9)."""
    try:
        exp_val = float(exponent)
    except (TypeError, ValueError):
        return  # symbolic or array exponent: nothing to bound here
    if abs(exp_val) > MAX_EXPONENT:
        raise ExprError(f"exponent {exp_val:g} is too large (max {MAX_EXPONENT})")
    try:
        # int() keeps huge integers exact (float() would overflow and skip the check).
        bits = abs(int(base)).bit_length()
    except (TypeError, ValueError):
        return  # symbolic or array base
    except OverflowError:
        return  # base is infinite: the result is inf, no big integer is built
    if bits * abs(exp_val) > MAX_POW_BITS:
        raise ExprError("power would produce an enormous number")
