"""Line-based Markdown scanner: finds display equations and ``check`` blocks.

Only what formulacheck needs is parsed. Anything inside a fenced code block other
than ``check`` is ignored, so math inside code samples is not mistaken for notes.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import CheckBlock, Document, Equation

_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)")
MAX_BLOCK_LINES = 200


def parse_text(text: str, path: str = "<string>") -> Document:
    """Parse Markdown *text* into equations and check blocks."""
    doc = Document(path=path, text=text)
    lines = text.splitlines()
    i = 0
    last_eq: Equation | None = None
    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            marker, info = fence.group(1), fence.group(2).lower()
            start = i
            i += 1
            body: list[str] = []
            while i < len(lines) and not _closes_fence(lines[i], marker):
                body.append(lines[i])
                i += 1
            i += 1  # skip the closing fence (or run off the end)
            if info == "check":
                raw = "\n".join(body[:MAX_BLOCK_LINES])
                doc.blocks.append(CheckBlock(line=start + 1, raw=raw, equation=last_eq))
            continue
        eq, consumed = _read_display_math(lines, i)
        if eq is not None:
            doc.equations.append(eq)
            last_eq = eq
            i += consumed
            continue
        i += 1
    return doc


def code_fence_lines(lines: list[str]) -> set[int]:
    """Indices (0-based) of lines that are fences or inside fenced code blocks."""
    inside: set[int] = set()
    i = 0
    while i < len(lines):
        fence = _FENCE_RE.match(lines[i])
        if not fence:
            i += 1
            continue
        marker = fence.group(1)
        inside.add(i)
        i += 1
        while i < len(lines) and not _closes_fence(lines[i], marker):
            inside.add(i)
            i += 1
        inside.add(i)  # closing fence (harmless if past the end)
        i += 1
    return inside


def parse_file(path: Path) -> Document:
    """Read and parse a Markdown file."""
    return parse_text(path.read_text(encoding="utf-8"), str(path))


def _closes_fence(line: str, marker: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) == {marker[0]} and len(stripped) >= len(marker)


def _read_display_math(lines: list[str], i: int) -> tuple[Equation | None, int]:
    """Return (equation, number of lines consumed) if a display equation starts at *i*."""
    stripped = lines[i].strip()
    if stripped.startswith("$$"):
        rest = stripped[2:]
        if "$$" in rest:  # single line: $$ ... $$
            return Equation(i + 1, rest.split("$$", 1)[0].strip()), 1
        parts = [rest]
        j = i + 1
        while j < len(lines):
            if "$$" in lines[j]:
                parts.append(lines[j].split("$$", 1)[0])
                return Equation(i + 1, _clean(parts)), j - i + 1
            parts.append(lines[j])
            j += 1
        return None, 1  # unterminated: ignore
    if stripped.startswith("\\["):
        rest = stripped[2:]
        if "\\]" in rest:
            return Equation(i + 1, rest.split("\\]", 1)[0].strip()), 1
        parts = [rest]
        j = i + 1
        while j < len(lines):
            if "\\]" in lines[j]:
                parts.append(lines[j].split("\\]", 1)[0])
                return Equation(i + 1, _clean(parts)), j - i + 1
            parts.append(lines[j])
            j += 1
        return None, 1
    return None, 1


def _clean(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())
