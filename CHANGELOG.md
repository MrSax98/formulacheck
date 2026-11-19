# Changelog

## 0.1.0

First release.

- `check` blocks in Markdown notes: `symbolic` (random-point spot check at 30 digits, then a
  sympy proof), `numeric` (explicit points) and `monte-carlo` (whole-sample estimate with a
  batch-means standard error, fixed seed).
- Restricted expression language (AST whitelist, no `eval`), exact rational literals in symbolic
  checks, bounded powers, sizes, sample sizes and memory; YAML without aliases; time limits
  (SIGALRM on Linux/macOS, a killable worker process on Windows or with `FORMULACHECK_ISOLATE=1`).
- Citation checks against Crossref, OpenAlex and DataCite: `verified` requires the first author,
  the year and the title to agree; on-disk cache and `--offline`.
- Terminal, HTML and JSON reports, with coverage of display equations.
- `python -m formulacheck`, a pre-commit hook and a GitHub Action.

### Fixed before release (independent review)

- `Limit` computed a one-sided limit; it is now two-sided (`LimitLeft`/`LimitRight` added).
- Monte Carlo verdicts used per-batch estimates (biased for quantiles) and `ddof=1`; statistics
  defined in `setup` hid their uncertainty; rare events and tiny scales could pass wrongly.
- Citations: the author was ignored when the title matched; one-word titles matched anything;
  DOIs with parentheses or Markdown around them were cut; a partial outage became `not-found`.
- Numeric checks treated any two values below 1e-12 as equal; long blocks were silently cut to
  200 lines; divergent sums/integrals and undefined values ended `inconclusive` or `pass`.
- Crashes on malformed DOIs, unexpected API answers and deeply nested YAML; quadratic parsing of
  unterminated `\[`; terminal escape sequences from untrusted text.
