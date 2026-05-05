# Template and Payload Development

This tutorial is for first-time DataM8 template and payload development. The goal
is to understand how a model becomes generated files, then make a small change
without putting model logic into Jinja templates.

## Mental Model

A generator target has three parts:

1. The solution file selects a target and defines `sourcePath` and `outputPath`.
2. Python payload builders in `Generate/<target>/__modules` prepare data.
3. Jinja2 templates in `Generate/<target>` render files from that prepared data.

The most important rule:

**Python interprets the model. Jinja formats the output.**

For the active Databricks target:

- `sourcePath`: `Generate/databricks`
- `outputPath`: `Output/databricks`
- payload entrypoint: `Generate/databricks/__modules/payload.py`
- templates: `Generate/databricks/**/*.jinja2`

## Payload Basics

Payload builders are registered with `@register_payload(...)`. The decorator
points to the template that will render the returned payloads.

```python
from pathlib import Path

from datam8.generate import BasePayload, register_payload


@register_payload("examples/hello.txt.jinja2")
def hello_payloads(model, cache):
    return [
        BasePayload(
            data={"message": "Hello DataM8"},
            output_path=Path("examples", "hello.txt"),
        )
    ]
```

Every payload must provide:

- `get_data()`: object exposed as `data` inside the template
- `get_output_path()`: output path relative to the target output folder

`BasePayload` is the standard implementation for simple dictionary payloads.

## How DataM8 Executes Payloads

DataM8 does not render payloads as one single sequential script:

- each registered payload function can be processed in a separate thread
- each returned payload instance can be rendered asynchronously
- `get_data()` is evaluated to provide `data` inside the Jinja template
- `get_output_path()` is evaluated to decide where the rendered file is written

Keep payload builders focused on collecting the objects that should be rendered.
Put calculations that belong to one rendered artifact on the payload object as
properties or methods. This keeps the builder small and makes template debugging
more local.

## Working with `__modules`

Payload code can be split across multiple Python files in the target's
`__modules` folder. The active Databricks target uses this pattern:

- `payload.py`: registers payload builders and coordinates artifact families
- `payload_common.py`: shared lookup, naming, source, and base payload helpers
- `ddl_payloads.py`: DDL-specific payload classes
- `dml_payloads.py`: DML-specific payload classes
- `jobs_payloads.py`: job planning payload helpers

Imports use module filenames from inside `__modules`, for example:

```python
from ddl_payloads import DdlPayload
from payload_common import get_model_entity_wrappers
```

Prefer returning dictionaries, lists, strings, numbers, or objects defined in the
target modules. That keeps errors close to the generator target and reduces
coupling to internal DataM8 model changes.

## Example 1: Add a Static Template

Create a template in the active target:

```text
Generate/databricks/examples/hello.txt.jinja2
```

Template content:

```jinja2
{{ data.message }}
```

Register the payload in `Generate/databricks/__modules/payload.py`:

```python
@register_payload("examples/hello.txt.jinja2")
def hello_payloads(model, cache):
    return [
        BasePayload(
            data={"message": "Hello DataM8"},
            output_path=Path("examples", "hello.txt"),
        )
    ]
```

After generation, the file is written to:

```text
Output/databricks/examples/hello.txt
```

## Example 2: Generate One File per Entity

Use payload code to traverse the model and keep the template simple.

```python
from pathlib import Path

from datam8.generate import BasePayload, register_payload

from payload_common import get_model_entity_wrappers


@register_payload("examples/entity-summary.md.jinja2")
def entity_summary_payloads(model, cache):
    payloads = []
    for wrapper in sorted(get_model_entity_wrappers(model), key=lambda item: str(item.locator)):
        entity = wrapper.entity
        payloads.append(
            BasePayload(
                data={
                    "name": entity.name,
                    "description": entity.description or "",
                    "attributes": [attribute.name for attribute in entity.attributes],
                },
                output_path=Path("examples", "entities", f"{entity.name}.md"),
            )
        )
    return payloads
```

Template:

```jinja2
# {{ data.name }}

{{ data.description }}

## Attributes
{% for attribute in data.attributes %}
- {{ attribute }}
{% endfor %}
```

This keeps folder lookup, entity traversal, sorting, and attribute shaping in
Python. The template only renders the already-prepared fields.

## Model Lookup Tips

Most model lookups return an entity wrapper. The actual JSON-backed metadata is
available through `wrapper.entity`.

When using locator-based lookup helpers:

- use `get()` when you already know the exact locator
- prefer `get()` over `get_where()` for exact lookups
- make prefixes for `get_many` or `get_many_where` end with `/`

Example:

```python
# Good: returns entities below the folder.
model.modelEntities.get_many("010-Stage/")

# Different: DataM8 may look for an entity with exactly this locator.
model.modelEntities.get_many("010-Stage")
```

The same rule applies to helper functions that wrap these APIs.

## Example 3: Extend an Existing Databricks Template

When adding a field to generated Databricks notebooks, add the field in the
payload class first and render it second.

Example payload property:

```python
class DdlPayload(ModelEntityPayload):
    @property
    def table_owner_comment(self) -> str:
        return self.wrapper_property("business_area", "unknown")
```

Example template usage:

```jinja2
# MAGIC Business area: {{ data.table_owner_comment }}
```

Do not look up `business_area` directly in Jinja. If fallback or inheritance
rules change later, only the payload code should need to change.

## Debugging Checklist

- Confirm the template path in `@register_payload(...)` exactly matches the file under the target.
- Confirm `output_path` is relative and does not point into `Generate/`.
- Keep payload output deterministic by sorting entities and generated lists.
- Use `cache` only for data shared across payload builders.
- Keep artifact-specific logic on the payload object as properties or methods.
- Prefer `match` statements when branching over known metadata shapes.
- Avoid model traversal, property inheritance, and target naming rules in Jinja.

## Validation

Run lint for the target modules:

```console
ruff check Generate/databricks/__modules
```

Then run generation and inspect the changed output. For broad generator changes,
compare previous and candidate output with:

```console
pwsh ./scripts/verify_generation_parity.ps1 -BaselineRoot ./Output/databricks -CandidateRoot <candidate-output>
```
