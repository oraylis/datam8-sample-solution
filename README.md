# DataM8 Sample Solution

This repository supplies a v2 metadata model, Python payloads and Jinja templates
for Databricks, Power BI and generated model documentation.

- [Local getting started](docs/getting-started.md)
- [Documentation index](docs/index.md)
- [Template and payload development](docs/template-development.md)
- [Configured targets and output paths](docs/reference/targets.md)
- [Optional deployment preparation](docs/quickstart.md)
- [Central illustrated handbook](https://github.com/oraylis/datam8/blob/codex/documentation-v2/docs/user-guide/README.md)

This documentation branch starts from main commit
`68001a2dcaa0b2931ee341f3527b96266a6e46da`, whose descriptor contains three targets.
The central screenshots use a different pinned four-target snapshot. Read
[compatibility](https://github.com/oraylis/datam8/blob/codex/documentation-v2/docs/compatibility.md) before mixing paths or versions.

Work on a complete disposable copy. Do not contact the sample cloud host for a
routine exercise. Keep secrets out of committed JSON and generated output.

## Checks

```sh
node scripts/check-docs.mjs
```

Node 24 runs the documentation check without a backend. For real generation,
use the setup and file assertions in [getting started](docs/getting-started.md).
The existing parity script compares two generated output directories; use
`scripts/verify_generation_parity.ps1` when preserving target output intentionally.

The existing Azure pipeline references superseded tooling and environment settings;
it is not a supported copy-and-run v2 recipe. Its replacement is a separate
[follow-up](docs/documentation-handoff.md), not part of documentation generation.
