"""Glue: analyse files and summarise the outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import citations
from .checks import run_block
from .checks.isolate import isolation_needed, run_block_isolated
from .model import CitationResult, CitationStatus, FileReport, Status
from .parser import parse_file

MARKDOWN_SUFFIXES = {".md", ".markdown"}
# Directory names never scanned when a folder is given (virtualenvs, dependencies, builds).
SKIP_DIRS = {"node_modules", "venv", "env", "site-packages", "__pycache__", "build", "dist"}


def collect_files(paths: list[Path]) -> list[Path]:
    """Expand directories to Markdown files (sorted); keep explicit files as given.

    Inside a directory, hidden folders (``.git``, ``.venv``, ...) and dependency or build
    folders are skipped.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            found = []
            for p in path.rglob("*"):
                parts = p.relative_to(path).parts[:-1]
                if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
                    continue
                if p.suffix.lower() in MARKDOWN_SUFFIXES and p.is_file():
                    found.append(p)
            files.extend(sorted(found))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(str(path))
    return files


def analyze_file(path: Path, lookup: citations.Lookup | None) -> FileReport:
    """Run every check block of *path* and, if *lookup* is given, verify its citations."""
    doc = parse_file(path)
    seen_ids: set[str] = set()
    run = run_block_isolated if isolation_needed() else run_block
    results = [run(doc.path, block, seen_ids) for block in doc.blocks]
    cites = []
    if lookup is not None:
        refs = citations.extract_references(doc.text)[: citations.MAX_REFERENCES]
        cites = [_verify_safely(doc.path, ref, lookup) for ref in refs]
    return FileReport(doc.path, doc.equations, results, cites)


def analyze_bib(path: Path, lookup: citations.Lookup) -> FileReport:
    """Verify the entries of a BibTeX file."""
    refs = citations.parse_bibtex(path.read_text(encoding="utf-8"))[: citations.MAX_REFERENCES]
    cites = [_verify_safely(str(path), ref, lookup) for ref in refs]
    return FileReport(str(path), [], [], cites)


def _verify_safely(path: str, ref: citations.Reference, lookup: citations.Lookup) -> CitationResult:
    """One odd reference or API answer must not stop the whole run."""
    try:
        return citations.verify(path, ref, lookup)
    except Exception as exc:
        return CitationResult(
            path,
            ref.line,
            ref.text[:140],
            CitationStatus.UNCHECKED,
            f"internal error while checking: {type(exc).__name__}: {exc}",
            ref.identifier[:200],
        )


@dataclass
class Summary:
    """Counts over all reports."""

    checks: dict[str, int] = field(default_factory=dict)
    citations: dict[str, int] = field(default_factory=dict)
    equations: int = 0
    covered: int = 0

    @property
    def coverage(self) -> float:
        return self.covered / self.equations if self.equations else 1.0

    def exit_code(self, strict: bool = False) -> int:
        """0 = clean; 1 = something failed (or, with *strict*, was inconclusive/unchecked)."""
        bad = (
            self.checks.get(Status.FAIL.value, 0)
            + self.checks.get(Status.ERROR.value, 0)
            + self.citations.get(CitationStatus.MISMATCH.value, 0)
            + self.citations.get(CitationStatus.NOT_FOUND.value, 0)
        )
        if strict:
            bad += (
                self.checks.get(Status.INCONCLUSIVE.value, 0)
                + self.citations.get(CitationStatus.UNCHECKED.value, 0)
                + self.citations.get(CitationStatus.UNPARSEABLE.value, 0)
            )
        return 1 if bad else 0


def summarize(reports: list[FileReport]) -> Summary:
    summary = Summary()
    for report in reports:
        summary.equations += len(report.equations)
        summary.covered += report.covered_equations
        for result in report.results:
            summary.checks[result.status.value] = summary.checks.get(result.status.value, 0) + 1
        for cite in report.citations:
            summary.citations[cite.status.value] = summary.citations.get(cite.status.value, 0) + 1
    return summary
