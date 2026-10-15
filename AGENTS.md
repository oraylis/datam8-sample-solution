# Working in DataM8 Sample Solution

This repository owns concrete v2 metadata, target payloads/templates and deployment
examples. Backend execution semantics and schemas belong to their own repositories.

- Read [the index](docs/index.md), the descriptor and affected target architecture.
- Document the targets actually present in this checkout. Do not port Lakeflow
  or change metadata just to match screenshots from another revision.
- Run exercises on a disposable full copy; do not contact sample cloud services.
- Keep target shaping in Python and rendering in Jinja. Inspect generated files
  and use the parity script when output must stay unchanged.
- Documentation-only edits run `node scripts/check-docs.mjs`; target changes need
  real generation assertions with pinned backend/schema revisions.
- Preserve unrelated work and never commit plaintext secrets or temporary output.
- The user handbook lives centrally. The maintainer merges feature branches manually.
