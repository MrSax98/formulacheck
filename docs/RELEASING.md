# Releasing

Releases are published to PyPI by `.github/workflows/release.yml` when a GitHub release is
published. It uses PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no
API token is stored in the repository or in GitHub secrets.

## One-time setup (maintainer)

1. Sign in to <https://pypi.org> (create an account and enable two-factor authentication if needed).
2. Go to *Your account > Publishing > Add a new pending publisher* and fill in:
   * PyPI project name: `formulacheck`
   * Owner: the GitHub user or organisation that owns the repository
   * Repository name: `formulacheck`
   * Workflow name: `release.yml`
   * Environment name: `pypi`
3. In the GitHub repository, *Settings > Environments > New environment*, create `pypi`
   (optionally require a reviewer, so every upload needs a click).

## Each release

1. Update `version` in `pyproject.toml` and `__version__` in `src/formulacheck/__init__.py`,
   and add the changes to `CHANGELOG.md`.
2. Merge to `main` and wait for CI to pass.
3. Create a GitHub release with a tag `vX.Y.Z` matching the version (the workflow refuses a
   mismatch). Publishing the release builds the package, checks it with `twine`, and uploads it.
4. After the first upload, replace the `git+https://...` install lines in the README with
   `pipx install formulacheck` / `uv tool install formulacheck`.

The GitHub Action (`action.yml`) and the pre-commit hook (`.pre-commit-hooks.yaml`) are used
directly from the repository at a tag, so they work as soon as the tag exists. To list the
action in the GitHub Marketplace, tick "Publish this Action to the GitHub Marketplace" when
creating the release.
