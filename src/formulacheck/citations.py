"""Citation checks: does the reference exist, and do its metadata match the entry?

Sources of references:

* entries listed under a "References" / "Riferimenti" / "Bibliografia" heading
  (one entry per line);
* DOIs and arXiv ids written anywhere else in the text (existence check only);
* entries of an optional BibTeX file.

Lookups use Crossref first and OpenAlex as a fallback. This module cannot tell whether a
source *supports* a claim. It only catches references that do not exist or whose
author, year or title do not match.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .model import CitationResult, CitationStatus
from .parser import code_fence_lines

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
MAX_REFERENCES = 200
TITLE_MATCH = 0.8
TITLE_CLOSE = 0.5

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s<>\"'\)\]\},;]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\barxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_HEADING_RE = re.compile(
    r"^(#{1,6})\s*(riferimenti|bibliografia|references|bibliography|fonti|sources)\b",
    re.IGNORECASE,
)
_ANY_HEADING_RE = re.compile(r"^(#{1,6})\s")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\[\d+\]\s*)")
_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


@dataclass
class Reference:
    """One reference to verify."""

    line: int
    text: str
    doi: str | None = None
    arxiv: str | None = None
    compare: bool = True  # compare metadata with the entry text, not just existence

    @property
    def identifier(self) -> str:
        if self.doi:
            return f"doi:{self.doi}"
        if self.arxiv:
            return f"arXiv:{self.arxiv}"
        return ""


@dataclass
class Work:
    """Bibliographic metadata returned by an API."""

    title: str
    first_author: str  # family name
    year: int | None
    doi: str | None
    source: str


# --------------------------------------------------------------------------- extraction


def extract_references(text: str, bib_entries: list[Reference] | None = None) -> list[Reference]:
    """Find references in Markdown *text* (plus optional BibTeX-derived entries)."""
    lines = text.splitlines()
    in_code = code_fence_lines(lines)  # code samples are not references
    refs: list[Reference] = []
    in_section_lines: set[int] = set()
    i = 0
    while i < len(lines):
        match = None if i in in_code else _HEADING_RE.match(lines[i])
        if not match:
            i += 1
            continue
        level = len(match.group(1))
        i += 1
        while i < len(lines):
            heading = None if i in in_code else _ANY_HEADING_RE.match(lines[i])
            if heading and len(heading.group(1)) <= level:
                break
            entry = _LIST_MARKER_RE.sub("", lines[i]).strip()
            if entry and i not in in_code:
                refs.append(_reference_from_text(i + 1, entry, compare=True))
                in_section_lines.add(i)
            i += 1
    seen = {r.doi.lower() for r in refs if r.doi} | {r.arxiv for r in refs if r.arxiv}
    for idx, line in enumerate(lines):
        if idx in in_section_lines or idx in in_code:
            continue
        for doi in _find_dois(line):
            if doi.lower() not in seen:
                seen.add(doi.lower())
                refs.append(Reference(idx + 1, line.strip(), doi=doi, compare=False))
        for arxiv in _ARXIV_RE.findall(line):
            if arxiv not in seen:
                seen.add(arxiv)
                refs.append(Reference(idx + 1, line.strip(), arxiv=arxiv, compare=False))
    refs.extend(bib_entries or [])
    return refs


def _find_dois(text: str) -> list[str]:
    return [m.group(0).rstrip(".,;:") for m in _DOI_RE.finditer(text)]


def _reference_from_text(line: int, entry: str, *, compare: bool) -> Reference:
    dois = _find_dois(entry)
    arxiv = _ARXIV_RE.search(entry)
    return Reference(
        line,
        entry,
        doi=dois[0] if dois else None,
        arxiv=arxiv.group(1) if arxiv and not dois else None,
        compare=compare,
    )


def parse_bibtex(text: str) -> list[Reference]:
    """Very small BibTeX reader: author, title, year and doi fields only."""
    refs: list[Reference] = []
    for match in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        if match.group(1).lower() in {"comment", "string", "preamble"}:
            continue
        body, _ = _balanced(text, text.index("{", match.start()))
        fields = _bib_fields(body)
        line = text.count("\n", 0, match.start()) + 1
        authors = fields.get("author", "").replace(" and ", "; ")
        entry = f"{authors} ({fields.get('year', '')}). {fields.get('title', '')}".strip()
        refs.append(
            Reference(line, entry, doi=fields.get("doi") or None, compare=bool(fields.get("title")))
        )
    return refs


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Return (content, end) of the brace group whose opening brace precedes *start*+1."""
    depth = 1
    pos = start + 1
    while pos < len(text) and depth:
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
        pos += 1
    return text[start + 1 : pos - 1], pos


def _bib_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = 0
    pattern = re.compile(r"(\w+)\s*=\s*")
    while True:
        match = pattern.search(body, pos)
        if not match:
            return fields
        pos = match.end()
        if pos >= len(body):
            return fields
        if body[pos] == "{":
            value, pos = _balanced(body, pos)
        elif body[pos] == '"':
            end = body.find('"', pos + 1)
            end = len(body) if end < 0 else end
            value, pos = body[pos + 1 : end], end + 1
        else:
            end = body.find(",", pos)
            end = len(body) if end < 0 else end
            value, pos = body[pos:end], end
        fields[match.group(1).lower()] = re.sub(
            r"\s+", " ", value.replace("{", "").replace("}", "")
        ).strip()


# --------------------------------------------------------------------------- text helpers


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(text: str, min_len: int = 3) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _norm(text)) if len(t) >= min_len]


def title_score(entry_text: str, title: str) -> float:
    """Fraction of the work's title words that appear in the entry text."""
    words = _tokens(title)
    if not words:
        return 0.0
    present = set(_tokens(entry_text))
    return sum(1 for w in words if w in present) / len(words)


def compare_work(entry_text: str, work: Work, *, score: float | None = None) -> list[str]:
    """Return a list of problems (empty means the metadata are consistent)."""
    problems: list[str] = []
    years = {int(y) for y in _YEAR_RE.findall(entry_text)}
    if work.year and years and work.year not in years:
        problems.append(f"year is {work.year}, the entry says {', '.join(map(str, sorted(years)))}")
    title_ok = (score if score is not None else title_score(entry_text, work.title)) >= 0.6
    # Whole-word match: an author called "Li" must not be "found" inside "Linear".
    surname = _norm(work.first_author).strip()
    author_ok = bool(surname) and (
        re.search(rf"(?<![a-z0-9]){re.escape(surname)}(?![a-z0-9])", _norm(entry_text)) is not None
    )
    if work.first_author and not author_ok and not title_ok:
        problems.append(f"first author is '{work.first_author}', not found in the entry")
    return problems


# --------------------------------------------------------------------------- lookups


@dataclass
class Fetch:
    """Result of an HTTP lookup. status: ok | notfound | error | uncached."""

    status: str
    data: Any = None


class Lookup:
    """HTTP client with an on-disk cache and an offline mode."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        offline: bool = False,
        mailto: str = "",
        transport: httpx.BaseTransport | None = None,
        delay: float = 0.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self.mailto = mailto
        self.delay = delay
        agent = f"formulacheck/{__version__}" + (f" (mailto:{mailto})" if mailto else "")
        self._client = httpx.Client(
            timeout=15.0, headers={"User-Agent": agent}, transport=transport, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, params: dict[str, str] | None = None) -> Fetch:
        params = dict(params or {})
        if self.mailto:
            params["mailto"] = self.mailto
        key = hashlib.sha256(json.dumps([url, sorted(params.items())]).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                return Fetch(cached["status"], cached.get("data"))
            except (OSError, ValueError, KeyError):
                pass  # corrupt cache entry: fetch again
        if self.offline:
            return Fetch("uncached")
        if self.delay:
            time.sleep(self.delay)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError:
            return Fetch("error")
        if response.status_code == 404:
            fetch = Fetch("notfound")
        elif response.status_code == 200:
            try:
                fetch = Fetch("ok", response.json())
            except ValueError:
                return Fetch("error")
        else:
            return Fetch("error")  # rate limits and server errors are not cached
        self._store(path, fetch)
        return fetch

    def _store(self, path: Path, fetch: Fetch) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"status": fetch.status, "data": fetch.data}), "utf-8")
        except OSError:
            pass  # the cache is an optimisation only


def _crossref_work(item: dict[str, Any]) -> Work:
    titles = item.get("title") or [""]
    authors = item.get("author") or [{}]
    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    return Work(
        title=titles[0] if titles else "",
        first_author=str(authors[0].get("family", "")) if authors else "",
        year=year if isinstance(year, int) else None,
        doi=item.get("DOI"),
        source="Crossref",
    )


def _openalex_work(item: dict[str, Any]) -> Work:
    authorships = item.get("authorships") or []
    name = (authorships[0].get("author") or {}).get("display_name", "") if authorships else ""
    doi = item.get("doi") or ""
    return Work(
        title=item.get("display_name") or item.get("title") or "",
        first_author=name.split()[-1] if name else "",
        year=item.get("publication_year")
        if isinstance(item.get("publication_year"), int)
        else None,
        doi=doi.removeprefix("https://doi.org/") or None,
        source="OpenAlex",
    )


def fetch_by_doi(lookup: Lookup, doi: str) -> tuple[Work | None, bool]:
    """Return (work, definitive). *definitive* is True only if every source said "not found"."""
    crossref = lookup.get(f"{CROSSREF}/{doi}")
    if crossref.status == "ok":
        return _crossref_work(crossref.data.get("message", {})), True
    openalex = lookup.get(f"{OPENALEX}/https://doi.org/{doi}")
    if openalex.status == "ok":
        return _openalex_work(openalex.data), True
    return None, crossref.status == "notfound" and openalex.status == "notfound"


def search_by_text(lookup: Lookup, text: str) -> tuple[list[Work], bool]:
    works: list[Work] = []
    reached = False
    crossref = lookup.get(
        CROSSREF,
        {"query.bibliographic": text[:300], "rows": "5", "select": "DOI,title,author,issued"},
    )
    if crossref.status == "ok":
        reached = True
        works += [_crossref_work(i) for i in crossref.data.get("message", {}).get("items", [])]
    openalex = lookup.get(OPENALEX, {"search": text[:300], "per-page": "5"})
    if openalex.status == "ok":
        reached = True
        works += [_openalex_work(i) for i in openalex.data.get("results", [])]
    return works, reached


# --------------------------------------------------------------------------- verification


def verify(path: str, ref: Reference, lookup: Lookup) -> CitationResult:
    """Verify one reference and return a result."""
    shown = ref.text if len(ref.text) <= 140 else ref.text[:137] + "..."

    def result(status: CitationStatus, message: str) -> CitationResult:
        return CitationResult(path, ref.line, shown, status, message, ref.identifier)

    doi = ref.doi or (f"10.48550/arXiv.{ref.arxiv}" if ref.arxiv else None)
    if doi:
        work, reached = fetch_by_doi(lookup, doi)
        if work is None:
            if reached:
                return result(CitationStatus.NOT_FOUND, f"{doi} not found in Crossref or OpenAlex")
            return result(CitationStatus.UNCHECKED, _unchecked_reason(lookup))
        if not ref.compare:
            return result(
                CitationStatus.VERIFIED, f"exists: {_describe(work)} (metadata not compared)"
            )
        entry = ref.text.replace(doi, " ")
        if len(_tokens(entry)) < 2:
            return result(CitationStatus.VERIFIED, f"exists: {_describe(work)}")
        problems = compare_work(entry, work)
        if problems:
            return result(CitationStatus.MISMATCH, "; ".join(problems) + f" -> {_describe(work)}")
        return result(CitationStatus.VERIFIED, f"matches {_describe(work)}")

    if len(_tokens(ref.text)) < 3:
        return result(CitationStatus.UNPARSEABLE, "too little text to identify a work")
    works, reached = search_by_text(lookup, ref.text)
    if not reached:
        return result(CitationStatus.UNCHECKED, _unchecked_reason(lookup))
    scored = sorted(((title_score(ref.text, w.title), w) for w in works), key=lambda t: -t[0])
    if not scored or scored[0][0] < TITLE_CLOSE:
        return result(CitationStatus.NOT_FOUND, "no work with a matching title found")
    score, best = scored[0]
    if score < TITLE_MATCH:
        return result(
            CitationStatus.MISMATCH, f"closest work has a different title -> {_describe(best)}"
        )
    problems = compare_work(ref.text, best, score=score)
    if problems:
        return result(CitationStatus.MISMATCH, "; ".join(problems) + f" -> {_describe(best)}")
    return result(CitationStatus.VERIFIED, f"matches {_describe(best)}")


def _describe(work: Work) -> str:
    author = work.first_author or "?"
    year = work.year or "?"
    doi = f", doi:{work.doi}" if work.doi else ""
    return f'{author} ({year}), "{work.title}"{doi} [{work.source}]'


def _unchecked_reason(lookup: Lookup) -> str:
    if lookup.offline:
        return "offline mode and not in cache"
    return "could not reach Crossref/OpenAlex (network error or rate limit); not checked"
