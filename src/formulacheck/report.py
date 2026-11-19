"""Terminal, HTML and JSON output."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from jinja2 import Environment, select_autoescape

from . import __version__
from .model import CitationStatus, FileReport, Status
from .runner import Summary

_CHECK_LABEL = {
    Status.PASS: "PASS",
    Status.FAIL: "FAIL",
    Status.INCONCLUSIVE: "INCONCLUSIVE",
    Status.ERROR: "ERROR",
}
_CHECK_COLOR = {Status.PASS: "32", Status.FAIL: "31", Status.INCONCLUSIVE: "33", Status.ERROR: "35"}
_CITE_COLOR = {
    CitationStatus.VERIFIED: "32",
    CitationStatus.MISMATCH: "31",
    CitationStatus.NOT_FOUND: "31",
    CitationStatus.UNPARSEABLE: "33",
    CitationStatus.UNCHECKED: "33",
}


def _paint(text: str, code: str, color: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if color else text


def render_terminal(reports: list[FileReport], summary: Summary, *, color: bool = False) -> str:
    """Plain-text summary, one line per check or citation."""
    out: list[str] = []
    for report in reports:
        rows: list[tuple[int, str]] = []
        for r in report.results:
            tag = _paint(f"{_CHECK_LABEL[r.status]:<12}", _CHECK_COLOR[r.status], color)
            rows.append((r.line, f"{tag} {r.check_id} ({r.kind}): {r.message}"))
        for c in report.citations:
            tag = _paint(f"{c.status.value.upper():<12}", _CITE_COLOR[c.status], color)
            rows.append((c.line, f"{tag} citation: {c.message}"))
        for eq in report.uncovered:
            rows.append((eq.line, f"{'UNCOVERED':<12} equation has no check"))
        if not rows:
            out.append(f"{report.path}: nothing to check")
        out.extend(
            f"{report.path}:{line}  {text}" for line, text in sorted(rows, key=lambda r: r[0])
        )
    checks = ", ".join(f"{n} {k}" for k, n in sorted(summary.checks.items())) or "none"
    cites = ", ".join(f"{n} {k}" for k, n in sorted(summary.citations.items())) or "none"
    out.append("")
    out.append(f"checks: {checks}")
    out.append(f"citations: {cites}")
    out.append(
        f"coverage: {summary.covered}/{summary.equations} display equations have a check "
        f"({summary.coverage:.0%})"
    )
    return "\n".join(out)


def render_json(reports: list[FileReport], summary: Summary) -> str:
    payload: dict[str, Any] = {
        "version": __version__,
        "summary": {
            "checks": summary.checks,
            "citations": summary.citations,
            "equations": summary.equations,
            "covered": summary.covered,
        },
        "files": [
            {
                "path": r.path,
                "equations": [dataclasses.asdict(e) for e in r.equations],
                "results": [dataclasses.asdict(x) for x in r.results],
                "citations": [dataclasses.asdict(c) for c in r.citations],
                "uncovered": [e.line for e in r.uncovered],
            }
            for r in reports
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>formulacheck report</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a64;--line:#dedbd2;--card:#fff;
--pass:#1f7a3d;--fail:#b3261e;--warn:#8a5a00;--err:#6a3a8a;--code:#f1efe8}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ece9e1;--muted:#a09d93;--line:#34332e;
--card:#1e1e1b;--pass:#6fcf8c;--fail:#ff8a80;--warn:#e6b450;--err:#c9a0e8;--code:#262622}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 Georgia,'Iowan Old Style',serif}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:1.7rem;margin:0 0 4px}h2{font-size:1.2rem;margin:36px 0 8px;word-break:break-all}
.sub{color:var(--muted);margin:0 0 24px;font-size:.9rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card b{display:block;font:600 1.6rem/1.2 system-ui,sans-serif}
.card span{color:var(--muted);font:.8rem system-ui,sans-serif}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line);
font-size:.92rem}
th{font:600 .75rem system-ui,sans-serif;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
code{background:var(--code);padding:1px 5px;border-radius:4px;font:.85rem ui-monospace,Menlo,monospace;
overflow-wrap:anywhere}
.id{white-space:nowrap}
.tag{display:inline-block;font:700 .72rem system-ui,sans-serif;padding:2px 7px;border-radius:999px;
border:1px solid currentColor;white-space:nowrap}
.pass,.verified{color:var(--pass)}.fail,.mismatch,.not-found{color:var(--fail)}
.inconclusive,.unchecked,.unparseable{color:var(--warn)}.error{color:var(--err)}
.msg{color:var(--muted)}
.note{margin-top:40px;padding:12px 14px;border-left:3px solid var(--line);color:var(--muted);
font-size:.88rem}
.wrap{overflow-x:auto}
.wrap table{min-width:720px}
</style>
</head>
<body>
<main>
<h1>formulacheck report</h1>
<p class="sub">formulacheck {{ version }} &middot; {{ files|length }} file(s)</p>
<div class="cards">
<div class="card"><b>{{ summary.checks.get('pass',0) }}</b><span>checks passed</span></div>
<div class="card"><b class="fail">{{ summary.checks.get('fail',0) }}</b><span>checks failed</span></div>
<div class="card"><b class="inconclusive">{{ summary.checks.get('inconclusive',0) }}</b><span>inconclusive</span></div>
<div class="card"><b class="error">{{ summary.checks.get('error',0) }}</b><span>invalid blocks</span></div>
<div class="card"><b>{{ summary.covered }}/{{ summary.equations }}</b><span>equations covered ({{ '%.0f'|format(summary.coverage*100) }}%)</span></div>
<div class="card"><b>{{ summary.citations.get('verified',0) }}/{{ total_cites }}</b><span>citations verified</span></div>
</div>
{% for r in files %}
<h2>{{ r.path }}</h2>
{% if r.results %}
<div class="wrap"><table>
<tr><th>Result</th><th>Check</th><th>Formula in the notes</th><th>Test</th><th>Detail</th></tr>
{% for x in r.results %}
<tr>
<td><span class="tag {{ x.status.value }}">{{ x.status.value|upper }}</span></td>
<td><code class="id">{{ x.check_id }}</code><br><span class="msg">{{ x.kind }} &middot; line {{ x.line }}</span></td>
<td>{% if x.equation %}<code>{{ x.equation }}</code><br><span class="msg">line {{ x.equation_line }}</span>{% else %}<span class="msg">no preceding equation</span>{% endif %}</td>
<td>{% if x.claim %}{{ x.claim }}<br>{% endif %}<code>{{ x.expression }}</code></td>
<td class="msg">{{ x.message }}</td>
</tr>
{% endfor %}
</table></div>
{% endif %}
{% if r.uncovered %}
<p><b>Equations without a check ({{ r.uncovered|length }}):</b></p>
<ul>{% for e in r.uncovered %}<li>line {{ e.line }}: <code>{{ e.tex }}</code></li>{% endfor %}</ul>
{% endif %}
{% if r.citations %}
<div class="wrap"><table>
<tr><th>Result</th><th>Line</th><th>Reference</th><th>Detail</th></tr>
{% for c in r.citations %}
<tr>
<td><span class="tag {{ c.status.value }}">{{ c.status.value|upper }}</span></td>
<td>{{ c.line }}</td><td>{{ c.text }}</td><td class="msg">{{ c.message }}</td>
</tr>
{% endfor %}
</table></div>
{% endif %}
{% if not r.results and not r.citations and not r.uncovered %}<p class="msg">Nothing to check in this file.</p>{% endif %}
{% endfor %}
<p class="note">How to read this. <b>PASS</b> on a Monte Carlo check is statistical evidence, not a proof.
A check block can contain the same mistake as the formula it tests, so compare the two columns.
<b>INCONCLUSIVE</b> means the tool could not decide; it is never a pass.
Citation checks show that a reference exists and its author, year and title agree with the entry;
they do not show that the source supports the claim.</p>
</main>
</body>
</html>
"""

_ENV = Environment(autoescape=select_autoescape(default=True), trim_blocks=False)


def render_html(reports: list[FileReport], summary: Summary) -> str:
    template = _ENV.from_string(_TEMPLATE)
    return template.render(
        version=__version__,
        files=reports,
        summary=summary,
        total_cites=sum(summary.citations.values()),
    )
