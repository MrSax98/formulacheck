# formulacheck

**Verify the math in your notes.** `formulacheck` is a command-line linter for Markdown and
LaTeX study notes: it checks formulas (symbolically, numerically or by Monte Carlo simulation)
and verifies that cited papers exist. It is built for notes written or polished with ChatGPT,
Claude, Gemini and other LLMs, which produce fluent text with wrong formulas and invented
references.

[![CI](https://github.com/MrSax98/formulacheck/actions/workflows/ci.yml/badge.svg)](https://github.com/MrSax98/formulacheck/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Linux, macOS, Windows](https://img.shields.io/badge/os-linux%20%7C%20macos%20%7C%20windows-lightgrey.svg)

```
$ formulacheck examples/statistics_notes.md
examples/statistics_notes.md:17  PASS         bernoulli-variance (monte-carlo): statistically consistent: lhs~0.210074, rhs~0.21, z=0.19 ...
examples/statistics_notes.md:36  FAIL         exponential-variance-wrong (monte-carlo): statistically inconsistent: lhs~0.246405, rhs~0.5, z=-126.15 ...
examples/statistics_notes.md:52  PASS         square-of-sum (symbolic): proved: simplify(lhs - rhs) == 0
examples/statistics_notes.md:66  FAIL         square-of-sum-wrong (symbolic): lhs != rhs at a=2.06653, b=1.54773: lhs=13.06285747, rhs=6.666007889
examples/statistics_notes.md:80  PASS         gauss-sum (symbolic): proved: simplify(lhs - rhs) == 0
examples/statistics_notes.md:97  INCONCLUSIVE tan-double-angle (symbolic): numerically consistent at 8 random points, but not proved symbolically
examples/statistics_notes.md:109  UNCOVERED    equation has no check
examples/statistics_notes.md:117  VERIFIED     citation: matches Efron (1979), "Bootstrap Methods: Another Look at the Jackknife", ...
examples/statistics_notes.md:118  VERIFIED     citation: matches Tibshirani (1996), "Regression Shrinkage and Selection Via the Lasso", ...
examples/statistics_notes.md:119  NOT-FOUND    citation: 10.9999/fake.12345 not found in Crossref, OpenAlex or DataCite

checks: 2 fail, 1 inconclusive, 3 pass
citations: 1 not-found, 2 verified
coverage: 6/7 display equations have a check (86%)
```

## Why

Re-deriving every formula by hand is slow, and asking another chatbot to "double-check" gives
you a second opinion, not a verdict. `formulacheck` gives a verdict from computation:

* **No LLM inside, no API key.** The same input always gives the same result.
* **Never says "ok" when it cannot decide.** Undecided identities are `inconclusive`, never `pass`.
* **Safe on untrusted notes.** Expressions are parsed with a whitelist and never `eval`'d.
* **Shows what is not covered.** Every display equation without a check is listed.
* **Works with plain Markdown files** (`.md`): Obsidian vaults, MkDocs sites, notebooks
  exported to Markdown, anything with `$$...$$` or `\[...\]` math.
* **Runs on Linux, macOS and Windows**, offline if you want.

## Install

You need Python 3.11 or newer. The recommended way is [pipx](https://pipx.pypa.io) or
[uv](https://docs.astral.sh/uv/), which install command-line tools in their own environment:

```bash
pipx install git+https://github.com/MrSax98/formulacheck.git
```

```bash
uv tool install git+https://github.com/MrSax98/formulacheck.git
```

Or with plain pip, inside a virtual environment:

```bash
pip install git+https://github.com/MrSax98/formulacheck.git
```

Check that it works with `formulacheck --version` (or `python -m formulacheck --version`).

## Quick start

1. Put a `check` block right below a formula in your notes:

````markdown
$$ \operatorname{Var}(X) = p(1-p) \qquad X \sim \text{Bernoulli}(p) $$

```check
id: var-bernoulli
kind: monte-carlo
setup:
  X: bernoulli(p)
  p: 0.3
expect: variance(X) == p*(1-p)
```
````

2. Run it on a file or a whole folder (hidden folders such as `.obsidian` or `.venv` are skipped):

```bash
formulacheck notes/ --html report.html
```

3. Open `report.html`: each formula is shown next to its test, with the verdict.

There are three kinds of check:

| kind | use it for | example |
|---|---|---|
| `symbolic` | algebraic identities, sums, derivatives, integrals | `lhs: Sum(k, k, 1, n)` / `rhs: n*(n+1)/2` |
| `numeric` | values at specific points | `lhs: sin(x)` / `rhs: 1` at `x: pi/2` |
| `monte-carlo` | expectations, variances, probabilities of random variables | `expect: prob(X > 0) == 0.5` |

The full syntax, the functions and the distributions are in
[docs/block-syntax.md](docs/block-syntax.md). Try the bundled examples, in English and
Italian, which contain deliberate mistakes:

```bash
formulacheck examples --html report.html
```

## Having an LLM write the checks

The tool does not translate LaTeX into tests by itself; that is what keeps its verdicts
deterministic. You can ask an LLM to draft the blocks, and `formulacheck` then checks them:

> For each display equation in these notes, add a `check` block right below it, following
> https://github.com/MrSax98/formulacheck/blob/main/docs/block-syntax.md. Use `symbolic` for
> identities and `monte-carlo` for statements about distributions. Do not fix the formulas:
> test them as written.

A test can repeat the mistake of the formula it tests, so the report shows both side by side.
Read them together.

## Citations

Entries under a `References`, `Bibliography`, `Riferimenti` or `Bibliografia` heading (one
entry per line, ideally `Author, A. (Year). Title. Journal.`), and an optional
`--bib refs.bib`, are looked up in [Crossref](https://www.crossref.org),
[OpenAlex](https://openalex.org) and, for arXiv and repository DOIs,
[DataCite](https://datacite.org):

| verdict | meaning |
|---|---|
| `verified` | the work exists, and the first author, the year and the title all agree with your entry (an entry that is only a DOI is verified by existence) |
| `mismatch` | a work exists but something disagrees (other author, wrong year, different title) |
| `not-found` | every catalogue answered and none has such a work |
| `unparseable` | the entry has too little text, or the DOI is malformed |
| `unchecked` | offline, network error or rate limit; never reported as `not-found` |

DOIs and `arXiv:` ids written elsewhere in the text are checked for existence only.
Lookups are cached (`~/.cache/formulacheck`, or `--cache-dir` / `FORMULACHECK_CACHE_DIR`;
"not found" answers are re-checked after a week), and `--offline` uses the cache only. No email
address is sent unless you set `FORMULACHECK_MAILTO` (Crossref's optional "polite pool"
contact). A citation check does **not** tell you whether the source supports your claim.

## Options and exit codes

```
formulacheck PATH... [--html FILE] [--json FILE] [--bib FILE] [--no-citations]
                     [--offline] [--cache-dir DIR] [--strict]
```

| exit code | meaning |
|---|---|
| 0 | no failures |
| 1 | a check failed or was invalid, or a citation was `not-found` / `mismatch` (with `--strict`, also `inconclusive`, `unchecked` and `unparseable`) |
| 2 | usage error |

## Use it automatically

**pre-commit** (checks the Markdown files you commit, without network access):

```yaml
repos:
  - repo: https://github.com/MrSax98/formulacheck
    rev: v0.1.0
    hooks:
      - id: formulacheck
```

**GitHub Actions**:

```yaml
- uses: actions/checkout@v4
- uses: MrSax98/formulacheck@v0.1.0
  with:
    paths: notes
    args: --strict
```

## Limits

* A Monte Carlo `pass` is statistical evidence, not a proof; the report states the smallest
  difference the simulation could detect, and very rare events end as `inconclusive`.
* `symbolic` is limited by what sympy can prove; hard identities end as `inconclusive`.
* Only formulas with a check block are verified; the rest are reported as not covered.
* Books and lecture notes without a DOI may come back `not-found` or `unchecked`, and titles
  that are heavily abbreviated in your entry may come back `mismatch` (the message shows the
  title found, so you can judge).
* Display equations are found when `$$` or `\[` starts the line.

## Contributing

Bug reports with a minimal Markdown file that reproduces the problem are the most useful
contribution. For code:

```bash
git clone https://github.com/MrSax98/formulacheck.git && cd formulacheck
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

Tests use no network. The design notes (in Italian) are in [docs/spec-it.md](docs/spec-it.md),
the changes in [CHANGELOG.md](CHANGELOG.md). Planned next: auditing Anki cards against their
source pages, and `.tex` input.

## License

MIT, see [LICENSE](LICENSE).
