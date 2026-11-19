import json
import shutil
from pathlib import Path

import pytest

from formulacheck.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

GOOD = """# Good

$$ (a+b)^2 = a^2 + 2ab + b^2 $$

```check
id: ok
kind: symbolic
symbols: [a, b]
lhs: (a+b)**2
rhs: a**2 + 2*a*b + b**2
```
"""
BAD = GOOD.replace("2*a*b + b**2", "b**2").replace("id: ok", "id: bad")
UNDECIDABLE = """$$ t $$

```check
id: tan
kind: symbolic
symbols: {x: real}
lhs: tan(2*x)
rhs: 2*tan(x)/(1-tan(x)**2)
```
"""


def run_cli(*args: str) -> int:
    return main([*args, "--offline", "--no-citations"])


def test_clean_file_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "a.md"
    f.write_text(GOOD)
    assert run_cli(str(f)) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "coverage: 1/1" in out


def test_failing_check_exits_one(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text(BAD)
    assert run_cli(str(f)) == 1


def test_inconclusive_is_ok_unless_strict(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text(UNDECIDABLE)
    assert run_cli(str(f)) == 0
    assert run_cli(str(f), "--strict") == 1


def test_directory_is_scanned_recursively(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text(GOOD)
    (tmp_path / "notes.txt").write_text(BAD)  # not Markdown: must be ignored
    assert run_cli(str(tmp_path)) == 0
    assert "a.md" in capsys.readouterr().out


def test_usage_errors_exit_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli(str(tmp_path / "missing.md")) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_cli(str(empty)) == 2
    assert "no Markdown files" in capsys.readouterr().err


def test_html_and_json_reports(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text(BAD + "\n$$ uncovered $$\n")
    html, js = tmp_path / "r.html", tmp_path / "r.json"
    assert run_cli(str(f), "--html", str(html), "--json", str(js)) == 1
    page = html.read_text()
    assert "FAIL" in page and "(a+b)^2" in page and "Equations without a check" in page
    data = json.loads(js.read_text())
    assert data["summary"]["checks"] == {"fail": 1}
    assert data["summary"]["equations"] == 2 and data["summary"]["covered"] == 1


def test_html_escapes_untrusted_text(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text(
        '$$ <script>alert(1)</script> $$\n\n```check\nid: "<img src=x onerror=alert(1)>"\nkind: nope\n```\n'
    )
    html = tmp_path / "r.html"
    run_cli(str(f), "--html", str(html))
    page = html.read_text()
    assert "<script>alert" not in page and "<img src=x" not in page
    assert "&lt;script&gt;" in page


def test_math_in_code_fences_is_not_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "a.md"
    f.write_text("```text\n$$ x $$\n```\n")
    assert run_cli(str(f)) == 0
    assert "0/0" in capsys.readouterr().out


def test_example_notes_give_the_documented_outcomes(tmp_path: Path) -> None:
    """The shipped examples have deliberate errors; the exact verdicts are part of the docs."""
    js = tmp_path / "r.json"
    assert run_cli(str(EXAMPLES), "--json", str(js)) == 1
    data = json.loads(js.read_text(encoding="utf-8"))
    results = {
        (Path(f["path"]).name, r["check_id"]): r["status"]
        for f in data["files"]
        for r in f["results"]
    }
    assert results == {
        ("appunti_statistica.md", "var-bernoulli"): "pass",
        ("appunti_statistica.md", "var-exp-sbagliata"): "fail",
        ("appunti_statistica.md", "quadrato-binomio"): "pass",
        ("appunti_statistica.md", "quadrato-binomio-sbagliato"): "fail",
        ("appunti_statistica.md", "somma-gauss"): "pass",
        ("appunti_statistica.md", "tangente-doppio-angolo"): "inconclusive",
        ("statistics_notes.md", "bernoulli-variance"): "pass",
        ("statistics_notes.md", "exponential-variance-wrong"): "fail",
        ("statistics_notes.md", "square-of-sum"): "pass",
        ("statistics_notes.md", "square-of-sum-wrong"): "fail",
        ("statistics_notes.md", "gauss-sum"): "pass",
        ("statistics_notes.md", "tan-double-angle"): "inconclusive",
    }
    assert data["summary"]["equations"] == 14 and data["summary"]["covered"] == 12


def test_documentation_examples_all_pass() -> None:
    """Every check block shown in the docs must itself pass."""
    root = EXAMPLES.parent
    assert run_cli(str(root / "docs"), str(root / "README.md")) == 0


def test_bib_file_is_checked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "a.md"
    f.write_text(GOOD)
    bib = tmp_path / "refs.bib"
    shutil.copy(EXAMPLES / "refs.bib", bib)
    code = main([str(f), "--bib", str(bib), "--offline", "--cache-dir", str(tmp_path / "c")])
    out = capsys.readouterr().out
    assert code == 0  # offline and uncached: reported as unchecked, not as a failure
    assert "UNCHECKED" in out
