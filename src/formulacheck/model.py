"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """Outcome of a formula check."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class CitationStatus(StrEnum):
    """Outcome of a citation check."""

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_FOUND = "not-found"
    UNPARSEABLE = "unparseable"
    UNCHECKED = "unchecked"  # offline, not cached, or network error


@dataclass(frozen=True)
class Equation:
    """A display equation found in a Markdown file."""

    line: int
    tex: str


@dataclass
class CheckBlock:
    """A fenced ``check`` block, with the equation it is attached to (if any)."""

    line: int
    raw: str
    equation: Equation | None = None


@dataclass
class Document:
    """Parsed Markdown file."""

    path: str
    text: str
    equations: list[Equation] = field(default_factory=list)
    blocks: list[CheckBlock] = field(default_factory=list)


@dataclass
class CheckResult:
    """Result of running one ``check`` block."""

    path: str
    line: int
    check_id: str
    kind: str
    status: Status
    message: str
    claim: str = ""
    equation: str | None = None
    equation_line: int | None = None
    expression: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CitationResult:
    """Result of verifying one citation."""

    path: str
    line: int
    text: str
    status: CitationStatus
    message: str
    identifier: str = ""


@dataclass
class FileReport:
    """Everything found in one file."""

    path: str
    equations: list[Equation]
    results: list[CheckResult]
    citations: list[CitationResult]

    @property
    def covered_lines(self) -> set[int]:
        return {r.equation_line for r in self.results if r.equation_line is not None}

    @property
    def covered_equations(self) -> int:
        return len(self.covered_lines & {e.line for e in self.equations})

    @property
    def uncovered(self) -> list[Equation]:
        covered = self.covered_lines
        return [e for e in self.equations if e.line not in covered]
