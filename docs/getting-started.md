# Local Getting Started

Use a complete copy of sample commit `68001a2dcaa0b2931ee341f3527b96266a6e46da`.
Base, Model, Plugins, Generate and supporting files must accompany the `.dm8s`.
Keep the original clone unchanged; generating with clean output can remove files.

## Backend selection

`pyproject.toml` pins DataM8 CLI beta.1. That pin has not been changed here and is
not proof of compatibility with current frontend/backend branches. For the local
CLI run verified on 2026-10-01, use backend commit
`85683fcaeaf13c4573bee3de9c4668b1ba3ab3b9` with its pinned schema
`f7dd5f519c5e17c5b595c5b99f600c51b9fe84ac`; follow
[backend setup](https://github.com/oraylis/datam8-cli/blob/feature/external_refresh/README.md). Record the runtime you actually use.

## First run

From your disposable sample directory, using the selected backend environment:

```sh
python -m datam8 validate --solution ./ORAYLISDatabricksSample.dm8s
python -m datam8 generate docs --solution ./ORAYLISDatabricksSample.dm8s
```

Check both exit codes and confirm a newly written `Output/docs/index.md` containing
Customer, entity pages and the generated relationship diagram. Remove a copied
pre-existing index before the run if you need proof of fresh output.
These commands were exercised against the exact baseline above on a temporary copy.
They do not connect to SQL or deploy cloud resources.

For UI exercises use the [central handbook](https://github.com/oraylis/datam8/blob/codex/documentation-v2/docs/user-guide/README.md).
Its screenshots refer to a separate sample snapshot and output-path layout.
Native desktop/sample compatibility remains a separate acceptance item.

## Next steps

Read [targets](reference/targets.md), [template development](template-development.md)
and, only when needed, [deployment preparation](quickstart.md).
