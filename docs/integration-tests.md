# Local Generation Checks and Review

This repository checks the AdventureWorks model and local generation of
Databricks, documentation and Power BI artifacts. It has no cloud deployment or
integration runner. Generated files do not establish deployment acceptance.

## Review boundary

Follow [repository instructions](../AGENTS.md). Do not run tests or CI checks for
a changed sample until the user approves its exact commit. The manual workflow
and generation checker require that revision; do not set approval on the user's
behalf. Use an independently assigned test model when required by the review
handoff. Generating artifacts for source review remains separate.

## After review

On a disposable complete copy, install the locked public dependencies:

```powershell
uv sync --frozen
node --test scripts/check-docs.test.mjs
node scripts/check-docs.mjs
uv run python -m unittest discover -s tests
uv run python scripts/check_generation.py --target all
```

The approved exact-commit marker must already be supplied for the final command.
The suite covers model references, public source placeholders, SQL Server builtin
forms/metadata and generated reader compatibility. The generation checker validates
all targets, Python syntax, notebook cells, job graphs and required runtime assets.
It does not contact source systems or deploy generated artifacts.

Public-entrypoint acceptance uses a fresh copy with an empty Plugins folder and
no repository-access token. Validate and generate all targets; inspect newly
written output. SQL fixtures mock database I/O while using the real bundled
connector. Live SQL, native app behavior and cloud execution need separate
authorized acceptance.
