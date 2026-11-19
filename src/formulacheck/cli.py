"""Command-line interface."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

from . import __version__
from .citations import Lookup
from .model import FileReport
from .report import render_html, render_json, render_terminal
from .runner import analyze_bib, analyze_file, collect_files, summarize

EXIT_USAGE = 2

EPILOG = """\
exit codes:
  0  no failures
  1  a check failed or was invalid, or a citation was not found / did not match
     (with --strict: also inconclusive checks and citations that could not be checked)
  2  usage error (bad arguments, missing file)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulacheck",
        description="Verify formulas and citations in Markdown math notes.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown files or directories")
    parser.add_argument("--html", type=Path, metavar="FILE", help="write an HTML report")
    parser.add_argument("--json", type=Path, metavar="FILE", help="write a JSON report")
    parser.add_argument("--bib", type=Path, metavar="FILE", help="also verify a BibTeX file")
    parser.add_argument("--no-citations", action="store_true", help="skip citation checks")
    parser.add_argument(
        "--offline", action="store_true", help="never use the network; use cached lookups only"
    )
    parser.add_argument("--cache-dir", type=Path, metavar="DIR", help="citation cache directory")
    parser.add_argument(
        "--strict", action="store_true", help="treat inconclusive and unchecked results as failures"
    )
    parser.add_argument("--version", action="version", version=f"formulacheck {__version__}")
    return parser


def _default_cache_dir() -> Path:
    env = os.environ.get("FORMULACHECK_CACHE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "formulacheck"


def _safe_output_encoding() -> None:
    """Never crash on characters the console cannot show (e.g. Windows code pages)."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _safe_output_encoding()
    try:
        files = collect_files(args.paths)
    except FileNotFoundError as exc:
        print(f"formulacheck: no such file or directory: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not files and not args.bib:
        print("formulacheck: no Markdown files found", file=sys.stderr)
        return EXIT_USAGE
    if args.bib and not args.bib.is_file():
        print(f"formulacheck: no such file: {args.bib}", file=sys.stderr)
        return EXIT_USAGE
    if args.bib and args.no_citations:
        print("formulacheck: --bib is ignored because of --no-citations", file=sys.stderr)

    lookup: Lookup | None = None
    if not args.no_citations:
        lookup = Lookup(
            args.cache_dir or _default_cache_dir(),
            offline=args.offline,
            mailto=os.environ.get("FORMULACHECK_MAILTO", ""),
        )
    reports: list[FileReport] = []
    try:
        for path in files:
            try:
                reports.append(analyze_file(path, lookup))
            except (OSError, UnicodeDecodeError) as exc:
                print(f"formulacheck: cannot read {path}: {exc}", file=sys.stderr)
                return EXIT_USAGE
        if args.bib and lookup is not None:
            reports.append(analyze_bib(args.bib, lookup))
    finally:
        if lookup is not None:
            lookup.close()

    summary = summarize(reports)
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    print(render_terminal(reports, summary, color=color))
    try:
        if args.html:
            args.html.write_text(render_html(reports, summary), encoding="utf-8")
            print(f"HTML report: {args.html}")
        if args.json:
            args.json.write_text(render_json(reports, summary), encoding="utf-8")
            print(f"JSON report: {args.json}")
    except OSError as exc:
        print(f"formulacheck: cannot write report: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return summary.exit_code(strict=args.strict)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
