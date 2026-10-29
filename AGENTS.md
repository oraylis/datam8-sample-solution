# Working in DataM8 Sample Solution

This repository owns concrete v2 metadata, target payloads/templates and deployment
examples. Backend execution semantics and schemas belong to their own repositories.

- Read [the index](docs/index.md), the descriptor and affected target architecture.
- Document the targets actually present in this checkout. Do not add targets
  or change metadata just to match screenshots from another revision.
- Work in the current checkout; do not create a disposable solution copy unless
  the task explicitly requires one.
- Cloud deployment and job or pipeline runs are allowed for verification in the
  integration environments explicitly configured under `tests/integration/`.
  Use only the selected target's bundle and its designated workspace/catalog;
  do not modify unrelated workspaces or resources. When target behavior changes,
  validate and deploy the existing bundle, then run the affected jobs or
  pipelines and inspect their task results and data. Prefer running only work
  that has not yet succeeded for the current revision.
- Keep credentials in the configured local authentication session or secret
  store. Never write secret values to the solution, generated assets, or reports.
- Keep target shaping in Python and rendering in Jinja. Inspect generated files
  and use the parity script when output must stay unchanged.
- Documentation-only edits run `node scripts/check-docs.mjs`; target changes need
  real generation assertions with pinned backend/schema revisions.
- Preserve unrelated work and never commit plaintext secrets or temporary output.
- The user handbook lives centrally. The maintainer merges feature branches manually.
