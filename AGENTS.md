# Working in the DataM8 Public Sample

This repository owns the small AdventureWorks base/model example, business
functions and classic Databricks, Docs and Power BI generation references.
It supports local generation and a neutral, operator-configured Databricks bundle.
No live integration runner is included; cloud execution requires separate authorization.

- Start with [getting started](docs/getting-started.md) and the
  [local checks](docs/integration-tests.md). Read the affected target's reference
  before changing its templates or payloads.
- Preserve the model's dependency closure, saved type mappings and three targets.
  Schema and CLI APIs remain canonical upstream; do not patch them here.
- Use disposable complete copies for editing and generation. Output can be replaced.
  Use local fixtures for SQL metadata tests; do not contact a live source.
- Continue authorized local edits, dependency setup, tests and generation without
  a separate commit approval or mandatory model handoff.
- Never commit installed plugins, credentials or live workspace/source bindings.
  Public entry points and dependencies must work without private repository access.
- With Node 24 and the Python version in `pyproject.toml`, run:
  `uv sync --frozen`, `node --test scripts/check-docs.test.mjs`,
  `node scripts/check-docs.mjs`, `uv run python -m unittest discover -s tests`
  and `uv run python scripts/check_generation.py --target all`.
- Report passes, failures and skips separately. Local generation is not evidence
  of live source, app or cloud acceptance. Live work requires separate authorization.
- Keep unrelated changes intact and propose feature PRs; the maintainer merges manually.
