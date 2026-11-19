from pathlib import Path
from typing import Any

import httpx
import pytest

from formulacheck.citations import (
    Lookup,
    Reference,
    extract_references,
    parse_bibtex,
    title_score,
    verify,
)
from formulacheck.model import CitationStatus

EFRON = {
    "DOI": "10.1214/aos/1176344552",
    "title": ["Bootstrap Methods: Another Look at the Jackknife"],
    "author": [{"family": "Efron", "given": "B."}],
    "issued": {"date-parts": [[1979]]},
}


class FakeApi:
    """Records requests and answers like Crossref/OpenAlex for a tiny catalogue."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("network down")
        url = str(request.url)
        if url.startswith("https://api.crossref.org/works/10.1214"):
            return httpx.Response(200, json={"message": EFRON})
        if url.startswith("https://api.crossref.org/works?"):
            return httpx.Response(200, json={"message": {"items": [EFRON]}})
        if url.startswith("https://api.crossref.org/works/"):
            return httpx.Response(404, text="Resource not found.")
        if url.startswith("https://api.openalex.org/works?"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404, json={})


def lookup(tmp_path: Path, api: FakeApi, **kw: Any) -> Lookup:
    return Lookup(tmp_path / "cache", transport=httpx.MockTransport(api), **kw)


def ref(text: str, doi: str | None = None, compare: bool = True) -> Reference:
    return Reference(1, text, doi=doi, compare=compare)


def test_doi_matching_the_entry_is_verified(tmp_path: Path) -> None:
    text = "Efron, B. (1979). Bootstrap methods: another look at the jackknife. doi:10.1214/aos/1176344552"
    result = verify("f.md", ref(text, "10.1214/aos/1176344552"), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.VERIFIED


def test_wrong_year_is_a_mismatch(tmp_path: Path) -> None:
    text = "Efron, B. (1989). Bootstrap methods: another look at the jackknife."
    result = verify("f.md", ref(text, "10.1214/aos/1176344552"), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.MISMATCH and "1979" in result.message


def test_wrong_author_and_title_is_a_mismatch(tmp_path: Path) -> None:
    text = "Rossi, M. (1979). Teoria generale dei processi stocastici."
    result = verify("f.md", ref(text, "10.1214/aos/1176344552"), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.MISMATCH


def test_unknown_doi_is_not_found(tmp_path: Path) -> None:
    result = verify("f.md", ref("Fake (2021). doi", "10.9999/fake"), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.NOT_FOUND


def test_free_text_entry_is_found_by_title(tmp_path: Path) -> None:
    text = "Efron, B. (1979). Bootstrap methods: another look at the jackknife. Ann. Statist."
    result = verify("f.md", ref(text), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.VERIFIED


def test_free_text_with_unknown_title_is_not_found(tmp_path: Path) -> None:
    text = "Bianchi, L. (2020). Una teoria inesistente delle varianze campionarie."
    result = verify("f.md", ref(text), lookup(tmp_path, FakeApi()))
    assert result.status is CitationStatus.NOT_FOUND


def test_too_short_entry_is_unparseable(tmp_path: Path) -> None:
    assert verify("f.md", ref("ibid."), lookup(tmp_path, FakeApi())).status is (
        CitationStatus.UNPARSEABLE
    )


def test_network_failure_is_unchecked_never_not_found(tmp_path: Path) -> None:
    api = FakeApi(fail=True)
    for r in (ref("x (2000). Some title here", "10.1/abc"), ref("Efron (1979). Bootstrap methods")):
        assert verify("f.md", r, lookup(tmp_path, api)).status is CitationStatus.UNCHECKED


def test_cache_avoids_repeated_requests_and_offline_uses_it(tmp_path: Path) -> None:
    api = FakeApi()
    r = ref(
        "Efron (1979). Bootstrap methods: another look at the jackknife", "10.1214/aos/1176344552"
    )
    first = verify("f.md", r, lookup(tmp_path, api))
    calls = api.calls
    second = verify("f.md", r, lookup(tmp_path, api))
    assert first.status is second.status is CitationStatus.VERIFIED
    assert api.calls == calls
    offline = Lookup(
        tmp_path / "cache", offline=True, transport=httpx.MockTransport(FakeApi(fail=True))
    )
    assert verify("f.md", r, offline).status is CitationStatus.VERIFIED


def test_offline_without_cache_is_unchecked(tmp_path: Path) -> None:
    offline = Lookup(tmp_path / "empty", offline=True, transport=httpx.MockTransport(FakeApi()))
    assert verify("f.md", ref("x", "10.1/abc"), offline).status is CitationStatus.UNCHECKED


def test_mailto_is_sent_only_when_configured(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url) + request.headers["user-agent"])
        return httpx.Response(404)

    for mail in ("", "me@example.org"):
        lk = Lookup(
            tmp_path / mail.replace("@", "_"), mailto=mail, transport=httpx.MockTransport(handler)
        )
        lk.get("https://api.crossref.org/works/10.1/x")
    assert "me@example.org" not in seen[0] and "mailto" not in seen[0]
    assert "me@example.org" in seen[1]


# --- extraction -----------------------------------------------------------------------


def test_extracts_reference_section_entries_and_inline_ids() -> None:
    text = (
        "See doi 10.1000/inline.1, and arXiv:1706.03762v2.\n\n"
        "## Riferimenti\n\n"
        "- Efron, B. (1979). Bootstrap methods. doi:10.1214/aos/1176344552.\n"
        "1. Tibshirani, R. (1996). Regression shrinkage and selection via the lasso.\n\n"
        "## Altro\n"
        "not a reference 10.1000/after.section\n"
    )
    refs = extract_references(text)
    by_id = {r.identifier or r.text: r for r in refs}
    assert "doi:10.1214/aos/1176344552" in by_id  # trailing '.' stripped
    assert by_id["doi:10.1214/aos/1176344552"].compare is True
    assert by_id["doi:10.1000/inline.1"].compare is False
    assert "arXiv:1706.03762" in by_id
    assert any(r.text.startswith("Tibshirani") for r in refs)
    assert "doi:10.1000/after.section" in by_id  # inline id outside the section is still seen


def test_parse_bibtex_reads_basic_fields() -> None:
    bib = """
    @article{efron79,
      author = {Efron, Bradley and Other, A.},
      title = {Bootstrap {M}ethods: another look at the jackknife},
      year = 1979,
      doi = {10.1214/aos/1176344552}
    }
    @comment{ignored}
    """
    (entry,) = parse_bibtex(bib)
    assert entry.doi == "10.1214/aos/1176344552"
    assert "Efron" in entry.text and "1979" in entry.text and "Methods" in entry.text


def test_title_score() -> None:
    assert (
        title_score(
            "Efron 1979 Bootstrap methods: another look at the jackknife",
            "Bootstrap Methods: Another Look at the Jackknife",
        )
        == 1.0
    )
    assert title_score("something else entirely", "Bootstrap Methods") == 0.0


@pytest.mark.parametrize("text", ["", "no references here", "## Riferimenti\n\n"])
def test_no_references(text: str) -> None:
    assert extract_references(text) == []
