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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .model import CitationResult, CitationStatus
from .parser import code_fence_lines

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
DATACITE = "https://api.datacite.org/dois"
MAX_REFERENCES = 200
MAX_DOI_LENGTH = 300
NOT_FOUND_TTL = 7 * 24 * 3600  # re-check "not found" answers after a week
TITLE_MATCH = 0.8  # share of the found title's words that must appear in the entry
TITLE_CLOSE = 0.5

# A DOI runs until whitespace, a quote or a backtick; trailing punctuation and Markdown
# are removed afterwards (see _clean_doi), keeping balanced parentheses such as
# 10.1016/S0140-6736(20)30183-5.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'`]+", re.IGNORECASE)
_VALID_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s\x00-\x1f\x7f]+$")
_ARXIV_RE = re.compile(r"\barxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
# Only headings that are exactly a bibliography title start a reference section
# ("## Fonti di errore" does not).
_HEADING_RE = re.compile(
    r"^(#{1,6})\s*(?:riferimenti(?:\s+bibliografici)?|bibliografia|references|bibliography"
    r"|fonti(?:\s+bibliografiche)?|sources|works\s+cited|literature)\s*:?\s*$",
    re.IGNORECASE,
)
_ANY_HEADING_RE = re.compile(r"^(#{1,6})\s")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\[\d+\]\s*)")
_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
# APA-like entries: "Author, A. (1979). Title of the work. Journal..."
_TITLE_AFTER_YEAR_RE = re.compile(
    r"\(\s*(?:1[5-9]\d\d|20\d\d)[a-z]?\s*\)\s*[.,:]?\s*(?P<title>.+?)(?:[.?!](?:\s|$)|$)"
)
_DOI_SCAFFOLD_RE = re.compile(r"https?://(?:dx\.)?doi\.org/|\bdoi\s*:?", re.IGNORECASE)


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
    other_years: tuple[int, ...] = ()  # e.g. print vs online publication year

    @property
    def years(self) -> set[int]:
        return ({self.year} if self.year else set()) | set(self.other_years)


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
    return [doi for m in _DOI_RE.finditer(text) if (doi := _clean_doi(m.group(0)))]


def _clean_doi(raw: str) -> str:
    """Remove Markdown and punctuation around a DOI; keep balanced parentheses."""
    doi = raw.split("](", 1)[0]  # [text](url) links
    while doi:
        last = doi[-1]
        if last in ".,;:*_]}>" or (last == ")" and doi.count("(") < doi.count(")")):
            doi = doi[:-1]
        else:
            break
    return doi


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


def entry_title(entry_text: str) -> str | None:
    """The title of an APA-like entry ("Author (Year). Title. ..."), if it can be isolated."""
    match = _TITLE_AFTER_YEAR_RE.search(entry_text)
    if not match:
        return None
    title = match.group("title").strip()
    return title if len(_tokens(title)) >= 2 else None


def titles_agree(entry_title_text: str, work_title: str) -> bool:
    """Symmetric comparison, so a one-word title ("Introduction") cannot match a long one.

    A shortened title (the main title without its subtitle) is accepted when it has at
    least three words and covers at least half of the full title.
    """
    found, cited = set(_tokens(work_title)), set(_tokens(entry_title_text))
    if not found or not cited:
        return False
    overlap = len(found & cited)
    if overlap / max(len(found), len(cited)) >= 0.75:
        return True
    return cited <= found and len(cited) >= 3 and len(cited) / len(found) >= 0.5


def compare_work(entry_text: str, work: Work, *, require_title: bool = True) -> list[str]:
    """Return the disagreements between an entry and a work (empty: everything agrees).

    Author, year and title must all agree. With *require_title* False (the entry gives a
    DOI, which already identifies the work) a missing title is accepted, a different one is not.
    """
    problems: list[str] = []
    years = {int(y) for y in _YEAR_RE.findall(entry_text)}
    if work.years and years and not (work.years & years):
        shown = ", ".join(map(str, sorted(work.years)))
        problems.append(f"year is {shown}, the entry says {', '.join(map(str, sorted(years)))}")
    # Whole-word match: an author called "Li" must not be "found" inside "Linear".
    surname = _norm(work.first_author).strip()
    if surname and not re.search(
        rf"(?<![a-z0-9]){re.escape(surname)}(?![a-z0-9])", _norm(entry_text)
    ):
        problems.append(f"first author is '{work.first_author}', not found in the entry")
    cited_title = entry_title(entry_text)
    if cited_title is not None:
        if not titles_agree(cited_title, work.title):
            problems.append(f"the title is different: '{work.title}'")
    elif require_title and (
        len(_tokens(work.title)) < 3 or title_score(entry_text, work.title) < TITLE_MATCH
    ):
        problems.append(f"could not match the title '{work.title}' in the entry")
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
        cached = self._load(path)
        if cached is not None:
            return cached
        if self.offline:
            return Fetch("uncached")
        if self.delay:
            time.sleep(self.delay)
        try:
            response = self._client.get(url, params=params)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, UnicodeError):
            return Fetch("error")
        if response.status_code == 404:
            fetch = Fetch("notfound")
        elif response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                return Fetch("error")
            if not isinstance(data, dict):
                return Fetch("error")  # not what these APIs return: treat as an outage
            fetch = Fetch("ok", data)
        else:
            return Fetch("error")  # rate limits and server errors are not cached
        self._store(path, fetch)
        return fetch

    def _load(self, path: Path) -> Fetch | None:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fetch = Fetch(cached["status"], cached.get("data"))
            saved = float(cached.get("time", 0))
        except (OSError, ValueError, KeyError, TypeError):
            return None  # missing or corrupt cache entry: fetch again
        if fetch.status == "notfound" and time.time() - saved > NOT_FOUND_TTL:
            return None  # a DOI may have been registered since
        return fetch

    def _store(self, path: Path, fetch: Fetch) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {"status": fetch.status, "data": fetch.data, "time": time.time()}
            path.write_text(json.dumps(payload), "utf-8")
        except OSError:
            pass  # the cache is an optimisation only


def _first_year(parts: Any) -> int | None:
    try:
        year = parts["date-parts"][0][0]
    except (KeyError, IndexError, TypeError):
        return None
    return year if isinstance(year, int) else None


def _crossref_work(item: Any) -> Work | None:
    if not isinstance(item, dict):
        return None
    titles = item.get("title") or [""]
    authors = item.get("author") or [{}]
    first = authors[0] if isinstance(authors, list) and authors else {}
    years = [_first_year(item.get(k)) for k in ("issued", "published-print", "published-online")]
    found = [y for y in years if y]
    return Work(
        title=str(titles[0]) if isinstance(titles, list) and titles else "",
        first_author=str(first.get("family", "")) if isinstance(first, dict) else "",
        year=found[0] if found else None,
        doi=item.get("DOI"),
        source="Crossref",
        other_years=tuple(found[1:]),
    )


def _openalex_work(item: Any) -> Work | None:
    if not isinstance(item, dict):
        return None
    authorships = item.get("authorships") or []
    first = authorships[0] if isinstance(authorships, list) and authorships else {}
    author = first.get("author") if isinstance(first, dict) else None
    name = str(author.get("display_name") or "") if isinstance(author, dict) else ""
    doi = str(item.get("doi") or "")
    year = item.get("publication_year")
    return Work(
        title=str(item.get("display_name") or item.get("title") or ""),
        first_author=name.split()[-1] if name.split() else "",
        year=year if isinstance(year, int) else None,
        doi=doi.removeprefix("https://doi.org/") or None,
        source="OpenAlex",
    )


def _datacite_work(payload: Any) -> Work | None:
    attributes = payload.get("data", {}).get("attributes") if isinstance(payload, dict) else None
    if not isinstance(attributes, dict):
        return None
    titles = attributes.get("titles") or [{}]
    creators = attributes.get("creators") or [{}]
    first = creators[0] if isinstance(creators, list) and creators else {}
    family = ""
    if isinstance(first, dict):
        family = str(first.get("familyName") or str(first.get("name") or "").split(",")[0])
    year = attributes.get("publicationYear")
    title = (
        titles[0].get("title", "")
        if isinstance(titles, list) and isinstance(titles[0], dict)
        else ""
    )
    return Work(
        title=str(title),
        first_author=family.strip(),
        year=int(str(year)) if str(year).isdigit() else None,
        doi=attributes.get("doi"),
        source="DataCite",
    )


def _crossref_message(payload: Any) -> Work | None:
    return _crossref_work(payload.get("message")) if isinstance(payload, dict) else None


def fetch_by_doi(lookup: Lookup, doi: str) -> tuple[Work | None, bool]:
    """Return (work, definitive). *definitive* is True only if every source said "not found".

    Crossref holds most journal DOIs, OpenAlex adds many others, and DataCite holds arXiv,
    Zenodo and other repository DOIs.
    """
    statuses = []
    sources: list[tuple[str, Callable[[Any], Work | None]]] = [
        (f"{CROSSREF}/{doi}", _crossref_message),
        (f"{OPENALEX}/https://doi.org/{doi}", _openalex_work),
        (f"{DATACITE}/{doi}", _datacite_work),
    ]
    for url, parse in sources:
        fetch = lookup.get(url)
        if fetch.status == "ok":
            work = parse(fetch.data)
            if work is not None:
                return work, True
            fetch = Fetch("error")  # unexpected shape: treat as an outage
        statuses.append(fetch.status)
    return None, all(s == "notfound" for s in statuses)


def search_by_text(lookup: Lookup, text: str) -> tuple[list[Work], bool, bool]:
    """Search both catalogues. Returns (works, any source answered, every source answered)."""
    works: list[Work] = []
    answered = []
    crossref = lookup.get(
        CROSSREF,
        {
            "query.bibliographic": text[:300],
            "rows": "5",
            "select": "DOI,title,author,issued,published-print,published-online",
        },
    )
    items = crossref.data.get("message", {}).get("items") if crossref.status == "ok" else None
    answered.append(isinstance(items, list))
    if isinstance(items, list):
        works += [w for i in items if (w := _crossref_work(i))]
    openalex = lookup.get(OPENALEX, {"search": text[:300], "per-page": "5"})
    results = openalex.data.get("results") if openalex.status == "ok" else None
    answered.append(isinstance(results, list))
    if isinstance(results, list):
        works += [w for i in results if (w := _openalex_work(i))]
    return works, any(answered), all(answered)


# --------------------------------------------------------------------------- verification


def _valid_doi(doi: str) -> bool:
    return len(doi) <= MAX_DOI_LENGTH and _VALID_DOI_RE.match(doi) is not None


def normalize_doi(raw: str) -> str:
    """Accept DOIs as written in BibTeX or by hand: with a doi.org URL, a 'doi:' prefix,
    surrounding Markdown or trailing punctuation."""
    doi = raw.strip().strip("`*_<>\"'")
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", doi, flags=re.IGNORECASE)
    return _clean_doi(doi.strip())


def verify(path: str, ref: Reference, lookup: Lookup) -> CitationResult:
    """Verify one reference and return a result."""
    shown = ref.text if len(ref.text) <= 140 else ref.text[:137] + "..."

    def result(status: CitationStatus, message: str) -> CitationResult:
        return CitationResult(path, ref.line, shown, status, message, ref.identifier[:200])

    doi = normalize_doi(ref.doi) if ref.doi else None
    if doi is None and ref.arxiv:
        doi = f"10.48550/arXiv.{ref.arxiv}"
    if doi is not None:
        if not _valid_doi(doi):
            return result(CitationStatus.UNPARSEABLE, "not a valid DOI")
        work, definitive = fetch_by_doi(lookup, doi)
        if work is None:
            if definitive:
                return result(
                    CitationStatus.NOT_FOUND, f"{doi} not found in Crossref, OpenAlex or DataCite"
                )
            return result(CitationStatus.UNCHECKED, _unchecked_reason(lookup))
        if not ref.compare:
            return result(
                CitationStatus.VERIFIED, f"exists: {_describe(work)} (metadata not compared)"
            )
        entry = _DOI_SCAFFOLD_RE.sub(" ", ref.text.replace(ref.doi or doi, " ").replace(doi, " "))
        if len(_tokens(entry)) < 2:
            return result(CitationStatus.VERIFIED, f"exists: {_describe(work)}")
        problems = compare_work(entry, work, require_title=False)
        if problems:
            return result(CitationStatus.MISMATCH, "; ".join(problems) + f" -> {_describe(work)}")
        return result(CitationStatus.VERIFIED, f"matches {_describe(work)}")

    if len(_tokens(ref.text)) < 3:
        return result(CitationStatus.UNPARSEABLE, "too little text to identify a work")
    works, any_answer, all_answered = search_by_text(lookup, ref.text)
    if not any_answer:
        return result(CitationStatus.UNCHECKED, _unchecked_reason(lookup))
    scored = sorted(((title_score(ref.text, w.title), w) for w in works), key=lambda t: -t[0])
    best_score, best = scored[0] if scored else (0.0, None)
    if best is None or best_score < TITLE_MATCH:
        if not all_answered:
            return result(
                CitationStatus.UNCHECKED,
                "only some catalogues answered and none had a matching title; not checked",
            )
        if best is None or best_score < TITLE_CLOSE:
            return result(CitationStatus.NOT_FOUND, "no work with a matching title found")
        return result(
            CitationStatus.MISMATCH, f"closest work has a different title -> {_describe(best)}"
        )
    problems = compare_work(ref.text, best)
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
    return "could not reach the catalogues (network error or rate limit); not checked"
