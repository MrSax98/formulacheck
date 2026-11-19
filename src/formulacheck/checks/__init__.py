"""Dispatch ``check`` blocks to the right runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import yaml

from ..expr import ExprError
from ..model import CheckBlock, CheckResult, Status
from .base import Outcome, SpecError
from .montecarlo import run_monte_carlo
from .symbolic import run_numeric, run_symbolic

RUNNERS: dict[str, Callable[[dict[str, Any]], Outcome]] = {
    "symbolic": run_symbolic,
    "numeric": run_numeric,
    "monte-carlo": run_monte_carlo,
}
MAX_BLOCK_CHARS = 20_000


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader without anchors/aliases, which could expand into huge structures."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            line = self.peek_event().start_mark.line + 1  # type: ignore[no-untyped-call]
            raise yaml.YAMLError(f"YAML aliases (*name) are not allowed (line {line})")
        return super().compose_node(parent, index)


def run_block(path: str, block: CheckBlock, seen_ids: set[str]) -> CheckResult:
    """Run one block. Never raises: problems become ``Status.ERROR`` results."""
    eq = block.equation
    result = CheckResult(
        path=path,
        line=block.line,
        check_id=f"check-L{block.line}",
        kind="?",
        status=Status.ERROR,
        message="",
        equation=eq.tex if eq else None,
        equation_line=eq.line if eq else None,
    )
    try:
        spec = _load_spec(block.raw)
        result.check_id = str(spec.get("id", result.check_id))
        result.kind = str(spec.get("kind", "?"))
        result.claim = str(spec.get("claim", ""))
        result.expression = _expression_text(spec)
        if result.check_id in seen_ids:
            raise SpecError(f"duplicate id '{result.check_id}' in this file")
        seen_ids.add(result.check_id)
        if "kind" not in spec:
            raise SpecError(f"missing field: kind (use: {', '.join(RUNNERS)})")
        runner = RUNNERS.get(result.kind)
        if runner is None:
            raise SpecError(f"unknown kind '{result.kind}' (use: {', '.join(RUNNERS)})")
        outcome = runner(spec)
    except (SpecError, ExprError) as exc:
        outcome = Outcome(Status.ERROR, str(exc))
    except Exception as exc:  # last resort: one odd block must not stop the whole run
        outcome = Outcome(Status.ERROR, f"internal error: {type(exc).__name__}: {exc}")
    result.status = outcome.status
    result.message = outcome.message
    result.details = outcome.details
    return result


def _load_spec(raw: str) -> dict[str, Any]:
    if len(raw) > MAX_BLOCK_CHARS:
        raise SpecError(f"check block too large (max {MAX_BLOCK_CHARS} characters)")
    try:
        spec = yaml.load(raw, Loader=_NoAliasLoader)  # a SafeLoader subclass: no Python objects
    except yaml.YAMLError as exc:
        raise SpecError(f"invalid YAML: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("a check block must be a YAML mapping (key: value lines)")
    return {str(k): v for k, v in spec.items()}


def _expression_text(spec: dict[str, Any]) -> str:
    if "lhs" in spec and "rhs" in spec:
        return f"{spec['lhs']}  ==  {spec['rhs']}"
    if "expect" in spec:
        return str(spec["expect"])
    return ""
