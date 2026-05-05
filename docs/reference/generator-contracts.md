# Generator Contracts

This reference describes the conventions shared by all active generator targets.

## Target Structure

```text
Generate/<target>/
  ARCHITECTURE.md
  README.md
  __modules/
    payload.py
    ...
  template.ext.jinja2
```

Responsibilities:

- `payload.py`: registers payload builders and orchestrates artifact families.
- helper modules: resolve metadata, naming, grouping, target-specific mappings, and reusable payload fields.
- templates: render prepared payload data to the final file format.
- `ARCHITECTURE.md`: documents target-specific contracts, properties, extension points, and validation steps.

## Runtime Flow

1. DataM8 loads `ORAYLISDatabricksSample.dm8s`.
2. The selected target determines `sourcePath` and `outputPath`.
3. Python modules are loaded from `sourcePath/__modules`.
4. Functions registered with `@register_payload(...)` are executed.
5. Each returned payload is rendered by the registered Jinja2 template.
6. The rendered file is written below the target `outputPath`.

Runtime notes:

- payload functions can be processed in separate threads
- payload instances can be rendered asynchronously
- payload code can be split across Python files inside `__modules`
- `cache` can share computed values between payload builders

## Payload Registration

```python
from datam8.generate import BasePayload, register_payload


@register_payload("folder/file.ext.jinja2")
def build_payloads(model, cache):
    return [
        BasePayload(
            data={"name": "example"},
            output_path=Path("folder", "file.ext"),
        )
    ]
```

The registered template path is relative to the target `sourcePath`.

The output path is relative to the target `outputPath`.

## Payload Objects

Payload objects must expose:

- `get_data()`: returns the object available as `data` in Jinja.
- `get_output_path()`: returns the output path for the rendered file.

Use `BasePayload` when a dictionary or list is enough. Use a custom class when
properties, methods, or lazy calculations make the template-facing contract clearer.

## Model Lookup Rules

Most model lookups return wrappers. The JSON-backed model object is available as
`wrapper.entity`.

When using locator helpers:

- use exact `get()` lookups when the locator is known
- prefer exact locator lookup over filter-based `get_where()` where practical
- terminate folder prefixes for `get_many` and `get_many_where` with `/`

Example: use `010-Stage/` to search below a folder. Without the trailing slash,
DataM8 may look for an entity with the exact locator `010-Stage`.

## Python vs. Jinja

Put this in Python:

- model traversal
- property resolution and inheritance
- output path calculation
- naming and type mapping
- sorting, grouping, and dependency planning
- validation and fallbacks
- payload properties and methods for artifact-specific calculations

Keep this in Jinja:

- final syntax and formatting
- simple loops over prepared lists
- simple conditions over prepared booleans

## Validation

Run target-module linting after changing payload code:

```console
ruff check Generate/databricks/__modules
ruff check Generate/powerbi-tabular/__modules
ruff check Generate/docs/__modules
```

For changes that should preserve generated output, compare output directories:

```console
pwsh ./scripts/verify_generation_parity.ps1 -BaselineRoot <baseline> -CandidateRoot <candidate>
```
