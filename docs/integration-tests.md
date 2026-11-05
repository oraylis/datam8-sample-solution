# Local Generation Checks and Review

This repository checks the AdventureWorks model and local generation of
Databricks, documentation and Power BI artifacts and the neutral deployment bundle. It has no live integration runner.
Generated files do not establish deployment acceptance.

## Local checks

Run these checks during implementation, without a separate commit approval or
mandatory model handoff. Follow [repository instructions](../AGENTS.md) and use
a disposable complete copy with Node 24 and the Python version in the project:

```powershell
uv sync --frozen
node --test scripts/check-docs.test.mjs
node scripts/check-docs.mjs
uv run python -m unittest discover -s tests
uv run python scripts/check_generation.py --target all
```

The suite covers model references, public source placeholders, SQL Server builtin
forms/metadata and generated reader compatibility. The generation checker validates
all targets, Python syntax, notebook cells, job graphs and runtime assets using
the actual bundle includes, variables and sync configuration. A temporary-copy
workflow test checks target-clean isolation and the documented SourceSystem extension.
It does not contact source systems or deploy generated artifacts.

The generation workflow runs on pull requests, pushes to main and manual dispatch.
It uses read-only repository permissions and public locked dependencies; no review
variable, source credential or repository-access token is needed.

## Public-entrypoint acceptance

Use a fresh copy with an empty `plugins` folder and no repository-access token.
Validate and generate all targets; inspect newly written output. SQL fixtures mock
database I/O while using the real bundled connector. Record passes, failures and
skips separately. Native app behavior, live SQL and cloud execution require their
own authorized acceptance; local checks do not establish those results.
