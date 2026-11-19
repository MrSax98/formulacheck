import subprocess
import sys
from pathlib import Path

from formulacheck.runner import collect_files


def test_directory_scan_skips_hidden_and_dependency_folders(tmp_path: Path) -> None:
    for rel in [
        "notes/a.md",
        "notes/sub/b.markdown",
        ".venv/lib/pkg/README.md",
        ".git/x.md",
        "node_modules/pkg/README.md",
        "venv/lib/README.md",
        "build/lib/doc.md",
        "notes/c.txt",
    ]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    found = [p.relative_to(tmp_path).as_posix() for p in collect_files([tmp_path])]
    assert found == ["notes/a.md", "notes/sub/b.markdown"]


def test_explicit_files_are_always_used(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden" / "a.md"
    hidden.parent.mkdir()
    hidden.write_text("x")
    assert collect_files([hidden]) == [hidden]


def test_python_dash_m_entry_point() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "formulacheck", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.startswith("formulacheck ")
