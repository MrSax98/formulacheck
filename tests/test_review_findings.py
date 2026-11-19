"""Regression tests for the findings of the independent review (one test per finding).

Each test states the correct behaviour; they were written to fail on the code that was
reviewed, which is how the findings were confirmed before fixing them.
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from formulacheck.checks import _load_spec, run_block
from formulacheck.checks.isolate import _peek
from formulacheck.citations import (
    Lookup,
    Reference,
    Work,
    compare_work,
    extract_references,
    verify,
)
from formulacheck.expr import ExprError, evaluate, parse
from formulacheck.model import CheckBlock, CheckResult, CitationStatus, FileReport, Status
from formulacheck.parser import parse_text
from formulacheck.report import render_terminal
from formulacheck.runner import summarize


def run(body: str) -> CheckResult:
    return run_block("t.md", CheckBlock(line=1, raw=body), set())


def sym(lhs: str, rhs: str, symbols: str = "[x]") -> CheckResult:
    return run(f"id: s\nkind: symbolic\nsymbols: {symbols}\nlhs: {lhs}\nrhs: {rhs}\n")


def mc(setup: str, expect: str, extra: str = "") -> CheckResult:
    return run(f"id: m\nkind: monte-carlo\nsetup:\n{setup}\nexpect: {expect}\n{extra}")


# --- 1. Limit was one-sided ----------------------------------------------------------------


def test_limit_is_two_sided() -> None:
    assert sym("Limit(abs(x)/x, x, 0)", "1", "{x: real}").status is not Status.PASS
    assert sym("Limit(1/x, x, 0)", "oo").status is not Status.PASS
    assert sym("Limit(sin(x)/x, x, 0)", "1").status is Status.PASS
    assert sym("Limit(1/x, x, oo)", "0").status is Status.PASS


def test_one_sided_limits_are_explicit() -> None:
    assert sym("LimitRight(abs(x)/x, x, 0)", "1", "{x: real}").status is Status.PASS
    assert sym("LimitLeft(abs(x)/x, x, 0)", "-1", "{x: real}").status is Status.PASS


# --- 2. Monte Carlo used biased per-batch estimates and ddof=1 -----------------------------


def test_extreme_quantile_uses_the_full_sample() -> None:
    setup = "  X: normal(0, 1)"
    assert mc(setup, "quantile(X, 0.9999) == 3.55").status is Status.FAIL
    assert mc(setup, "quantile(X, 0.9999) == 3.719").status is Status.PASS


def test_moment_identities_hold_on_the_sample() -> None:
    setup = "  X: normal(1, 2)\n  Y: normal(0, 1)"
    assert mc(setup, "variance(X) == mean(X**2) - mean(X)**2").status is Status.PASS
    assert mc(setup, "cov(X, Y) == mean(X*Y) - mean(X)*mean(Y)").status is Status.PASS


# --- 3. author ignored when the title matched; one-word titles matched anything ------------

EFRON = {
    "DOI": "10.1214/aos/1176344552",
    "title": ["Bootstrap Methods: Another Look at the Jackknife"],
    "author": [{"family": "Efron"}],
    "issued": {"date-parts": [[1979]]},
}


def api(routes: dict[str, Any]) -> httpx.MockTransport:
    """Answer by URL prefix; values are (status, json) or an exception to raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, answer in routes.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


SEARCH_EFRON = {
    "https://api.crossref.org/works?": (200, {"message": {"items": [EFRON]}}),
    "https://api.openalex.org/works?": (200, {"results": []}),
    "https://api.crossref.org/works/10.1214": (200, {"message": EFRON}),
}


def check(tmp_path: Path, ref: Reference, routes: dict[str, Any]) -> CitationStatus:
    lookup = Lookup(tmp_path / "cache", transport=api(routes))
    return verify("f.md", ref, lookup).status


def test_wrong_author_with_right_title_is_a_mismatch(tmp_path: Path) -> None:
    text = "Rossi, M. (1979). Bootstrap methods: another look at the jackknife."
    assert check(tmp_path, Reference(1, text), SEARCH_EFRON) is CitationStatus.MISMATCH
    with_doi = Reference(1, text + " doi:10.1214/aos/1176344552", doi="10.1214/aos/1176344552")
    assert check(tmp_path / "b", with_doi, SEARCH_EFRON) is CitationStatus.MISMATCH


def test_generic_one_word_title_does_not_verify_an_invented_paper(tmp_path: Path) -> None:
    intro = {
        "DOI": "10.1/intro",
        "title": ["Introduction"],
        "author": [{"family": "Bianchi"}],
        "issued": {"date-parts": [[2019]]},
    }
    routes = {
        "https://api.crossref.org/works?": (200, {"message": {"items": [intro]}}),
        "https://api.openalex.org/works?": (200, {"results": []}),
    }
    text = "Bianchi, L. (2019). Introduction to a nonexistent theory of variance."
    assert check(tmp_path, Reference(1, text), routes) is not CitationStatus.VERIFIED


def test_real_entry_still_verifies(tmp_path: Path) -> None:
    text = "Efron, B. (1979). Bootstrap methods: another look at the jackknife. Ann. Statist."
    assert check(tmp_path, Reference(1, text), SEARCH_EFRON) is CitationStatus.VERIFIED


# --- 4. DOI extraction broke on parentheses and Markdown -----------------------------------


@pytest.mark.parametrize(
    ("text", "doi"),
    [
        ("Lancet. doi:10.1016/S0140-6736(20)30183-5", "10.1016/S0140-6736(20)30183-5"),
        ("DOI `10.1214/aos/1176344552`", "10.1214/aos/1176344552"),
        ("**10.1214/aos/1176344552**", "10.1214/aos/1176344552"),
        ("[paper](https://doi.org/10.1214/aos/1176344552)", "10.1214/aos/1176344552"),
        ("(see doi:10.1214/aos/1176344552).", "10.1214/aos/1176344552"),
        ("<https://doi.org/10.1214/aos/1176344552>", "10.1214/aos/1176344552"),
    ],
)
def test_doi_extraction(text: str, doi: str) -> None:
    refs = extract_references(text)
    assert [r.doi for r in refs] == [doi]


# --- 5. default atol made tiny values equal ------------------------------------------------


def test_numeric_tiny_values_are_compared_relatively() -> None:
    wrong = (
        "id: n\nkind: numeric\nlhs: binomial(n, n)*p**n\nrhs: p**(n-1)\npoints: [{n: 20, p: 0.1}]\n"
    )
    assert run(wrong).status is Status.FAIL
    cancel = "id: n\nkind: numeric\nlhs: sin(x)**2 + cos(x)**2 - 1\nrhs: 0\npoints: [{x: 0.7}]\n"
    assert run(cancel).status is Status.PASS


# --- 6. degenerate Monte Carlo cases --------------------------------------------------------


def test_rare_event_is_not_reported_as_a_pass() -> None:
    result = mc("  X: binomial(10, 0.2)", "prob(X >= 10) == 0")
    assert result.status is Status.INCONCLUSIVE


def test_tiny_scale_claims_are_tested_relatively() -> None:
    setup = "  X: normal(0, 0.000001)"
    assert mc(setup, "variance(X) == 0.000000000002").status is Status.FAIL
    assert mc(setup, "variance(X) == 0.000000000001").status is Status.PASS


def test_statistics_computed_in_setup_keep_their_uncertainty() -> None:
    result = mc("  X: normal(0, 2)\n  s2: variance(X)", "s2 == 4")
    assert result.status is Status.PASS, result.message


def test_overflow_is_an_error_and_keeps_json_valid() -> None:
    result = mc("  X: normal(0, 1e305)", "mean(X) == 1e306")
    assert result.status is Status.ERROR
    json.dumps(result.details, allow_nan=False)


# --- 7. blocks were silently truncated to 200 lines ----------------------------------------


def test_long_blocks_are_not_silently_truncated() -> None:
    points = "\n".join(f"  - {{x: {i}}}" for i in range(299))
    text = f"```check\nid: n\nkind: numeric\nlhs: min(x, 250)\nrhs: x\npoints:\n{points}\n```\n"
    (block,) = parse_text(text).blocks
    assert run_block("t.md", block, set()).status is Status.FAIL


# --- 8. a DOI URL alone was compared as if it were metadata -------------------------------


def test_doi_url_entry_is_verified_by_existence(tmp_path: Path) -> None:
    ref = Reference(1, "https://doi.org/10.1214/aos/1176344552", doi="10.1214/aos/1176344552")
    assert check(tmp_path, ref, SEARCH_EFRON) is CitationStatus.VERIFIED


# --- 9. a partial outage became not-found ---------------------------------------------------


def test_partial_outage_is_unchecked(tmp_path: Path) -> None:
    routes = {
        "https://api.crossref.org/works?": (429, {}),
        "https://api.openalex.org/works?": (200, {"results": []}),
    }
    text = "Efron, B. (1979). Bootstrap methods: another look at the jackknife."
    assert check(tmp_path, Reference(1, text), routes) is CitationStatus.UNCHECKED


# --- 10. crashes ------------------------------------------------------------------------------


@pytest.mark.parametrize("doi", ["10.1234/abc\x01def", "10.1234/" + "a" * 70_000])
def test_invalid_dois_do_not_crash(tmp_path: Path, doi: str) -> None:
    status = check(tmp_path, Reference(1, "x", doi=doi), SEARCH_EFRON)
    assert status in (CitationStatus.UNPARSEABLE, CitationStatus.UNCHECKED)


def test_malformed_api_response_does_not_crash(tmp_path: Path) -> None:
    routes = {"https://api.crossref.org/works/10.1214": (200, [])}
    ref = Reference(1, "Efron (1979)", doi="10.1214/aos/1176344552")
    assert check(tmp_path, ref, routes) is CitationStatus.UNCHECKED


def test_deeply_nested_yaml_does_not_crash() -> None:
    raw = "id: a\nkind: symbolic\nclaim: " + "[" * 3000 + "\n"
    assert _peek(raw)[0] is None
    assert run(raw).status is Status.ERROR
    with pytest.raises(Exception, match="nested"):
        _load_spec(raw)


# --- 11. no total memory budget for Monte Carlo ---------------------------------------------


def test_monte_carlo_memory_budget() -> None:
    derived = "\n".join(f"  a{k}: X + {k}" for k in range(60))
    start = time.monotonic()
    result = mc(f"  X: normal(0, 1)\n{derived}", "mean(a1) == 1", "n: 5000000\n")
    assert result.status is Status.ERROR and "budget" in result.message
    assert time.monotonic() - start < 5


# --- 12. quadratic parsing of unterminated math ---------------------------------------------


def test_unterminated_display_math_is_parsed_in_linear_time() -> None:
    text = "\\[ x\n" * 20_000
    start = time.monotonic()
    parse_text(text)
    assert time.monotonic() - start < 3


# --- 13. integer + nonpositive sampled positive integers ------------------------------------


def test_integer_nonpositive_sampling() -> None:
    result = sym("min(x**3, x)", "x**3", '{x: "integer, nonpositive"}')
    assert result.status is not Status.FAIL, result.message


# --- 14. equals() False ignored; undefined values passed ------------------------------------


def test_divergent_values_fail() -> None:
    assert sym("Integral(1/x**2, x, -1, 1)", "-2").status is Status.FAIL
    assert sym("Sum(k, k, 1, oo)", "-1/12", "{k: natural}").status is Status.FAIL
    assert sym("Sum(1/k, k, 1, oo)", "oo", "{k: natural}").status is Status.PASS


def test_undefined_values_are_errors() -> None:
    assert sym("0*oo", "oo - oo").status is Status.ERROR
    assert sym("Limit(sin(x), x, oo)", "Limit(cos(x), x, oo)").status is Status.ERROR


# --- 15. terminal escape sequences ------------------------------------------------------------


def test_terminal_output_has_no_control_characters() -> None:
    bad = CheckResult("t.md", 1, "\r\x1b[2K\x1b[32mPASS", "symbolic", Status.FAIL, "m\x07")
    report = FileReport("t.md", [], [bad], [])
    out = render_terminal([report], summarize([report]), color=False)
    assert "\x1b" not in out and "\r" not in out and "\x07" not in out
    assert "FAIL" in out


# --- 16. headings and power limits ------------------------------------------------------------


def test_only_reference_headings_start_a_reference_section() -> None:
    assert extract_references("## Fonti di errore\n- Rounding in floating point arithmetic\n") == []
    assert len(extract_references("## Fonti\n- Efron, B. (1979). Bootstrap methods.\n")) == 1
    assert len(extract_references("## Riferimenti bibliografici\n- Efron (1979). X y z.\n")) == 1


def test_huge_integer_power_is_rejected() -> None:
    with pytest.raises(ExprError):
        evaluate(parse("(10**400)**10000"), {}, {})


# --- documentation mismatches -------------------------------------------------------------------


def test_numbers_written_in_exponent_notation_are_accepted() -> None:
    body = "id: n\nkind: numeric\nlhs: x\nrhs: x\npoints: [{x: 1}]\nrtol: 1e-6\n"
    assert run(body).status is Status.PASS


def test_fractions_are_exact_in_symbolic_checks() -> None:
    assert sym("x**(1/2)*x**(1/2)", "x").status is Status.PASS


def test_print_year_also_matches() -> None:
    work = Work(
        "Bootstrap methods: another look at the jackknife", "Efron", 1978, None, "x", (1979,)
    )
    assert (
        compare_work("Efron, B. (1979). Bootstrap methods: another look at the jackknife.", work)
        == []
    )


@pytest.mark.parametrize(
    "raw",
    [
        "https://doi.org/10.1214/aos/1176344552",
        "doi:10.1214/aos/1176344552",
        "10.1214/aos/1176344552`",
        "http://dx.doi.org/10.1214/aos/1176344552.",
    ],
)
def test_dois_written_with_prefixes_are_normalised(tmp_path: Path, raw: str) -> None:
    """BibTeX doi fields often hold a doi.org URL; that must not become a false not-found."""
    ref = Reference(
        1, "Efron, B. (1979). Bootstrap methods: another look at the jackknife.", doi=raw
    )
    assert check(tmp_path, ref, SEARCH_EFRON) is CitationStatus.VERIFIED


def test_bibtex_doi_url_is_verified(tmp_path: Path) -> None:
    from formulacheck.citations import parse_bibtex

    (entry,) = parse_bibtex(
        "@article{e, author={Efron, Bradley}, year={1979},"
        " title={Bootstrap methods: another look at the jackknife},"
        " doi={https://doi.org/10.1214/aos/1176344552}}"
    )
    lookup = Lookup(tmp_path / "c", transport=api(SEARCH_EFRON))
    assert verify("r.bib", entry, lookup).status is CitationStatus.VERIFIED
