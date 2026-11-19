# Changelog

## 0.1.0 (unreleased)

First release.

- `check` blocks in Markdown notes: `symbolic` (random-point spot check, then sympy proof),
  `numeric` (explicit points) and `monte-carlo` (batch z-test with a fixed seed).
- Restricted expression language (AST whitelist, no `eval`), bounded powers, sizes and sample
  sizes; YAML without aliases; time limits (SIGALRM on Linux/macOS, a killable worker process
  on Windows or with `FORMULACHECK_ISOLATE=1`).
- Citation checks against Crossref and OpenAlex, with an on-disk cache and `--offline`.
- Terminal, HTML and JSON reports, with coverage of display equations.
- `python -m formulacheck`, a pre-commit hook and a GitHub Action.
