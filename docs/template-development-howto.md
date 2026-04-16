# DataM8 Template Development How-To

## Building generator targets for Databricks Lake, Power BI, and Docs

## Purpose

This guide explains how to build and maintain DataM8 generator targets that transform the DataM8 metadata model into platform-specific artifacts.

It is based on this sample solution and its concrete targets:
- `Generate/databricks-lake`
- `Generate/powerbi-tabular`
- `Generate/docs`

The central design rule is:

**Templates should format output, not interpret the model.**

All non-trivial interpretation belongs in Python payload builders and helper modules.

---

## 1. Generator architecture in one view

A DataM8 generator target has three layers:

1. **Solution target definition**
   - Declares template location (`sourcePath`)
   - Declares output location (`outputPath`)

2. **Python payload layer**
   - Traverses the model
   - Resolves properties, inheritance, relationships, naming, and mappings
   - Produces stable payload dictionaries/objects

3. **Jinja2 templates**
   - Render platform files from prepared payloads

---

## 2. Runtime flow

DataM8 generation (conceptually):

1. Resolve selected generator target from the solution.
2. Load Python modules from `target.sourcePath/__modules`.
3. Register payload builders via `@register_payload(...)`.
4. Execute payload builders and collect payload objects.
5. Render each payload with `template.render(data=data)`.
6. Write output under `target.outputPath`.

Core contracts:

### Contract A: Payload registration

```python
from datam8.generate import BasePayload, IPayload, register_payload

@register_payload("table.sql.jinja2")
def generate_tables(model, cache):
    payloads = []
    ...
    return payloads
```

### Contract B: Payload objects

A payload must provide:
- `get_data()`
- `get_output_path()`

`BasePayload` is the standard implementation.

---

## 3. Recommended target structure

```text
Generate/<target>/
  ARCHITECTURE.md
  README.md
  __modules/
    payload.py
    metadata_utils.py
    naming.py
    type_mapping.py
    planner.py
    payload_helpers.py
  artifact_a.ext.jinja2
  artifact_b.ext.jinja2
```

Responsibilities:
- `payload.py`: registrations + orchestration
- `metadata_utils.py`: model/property access + inheritance + folder/zone/source resolution
- `naming.py`: naming conventions + sanitization
- `type_mapping.py`: canonical-to-target mapping
- `planner.py`: dependency/job/artifact planning
- `payload_helpers.py`: stable template-facing shaping utilities

---

## 4. Registering targets in the solution

Targets are declared in [`ORAYLISDatabricksSample.dm8s`](../ORAYLISDatabricksSample.dm8s):

```json
{
  "name": "databricks",
  "isDefault": true,
  "sourcePath": "Generate/databricks-lake",
  "outputPath": "Output/databricks-lake/generated"
}
```

Meaning:
- `sourcePath`: templates and `__modules`
- `outputPath`: generated artifacts

Rule:
- Do not mix templates and generated output in the same folder.

---

## 5. Start with payload design, not template design

Define the payload contract first. Avoid model traversal logic in Jinja.

Good payload characteristics:
- explicit
- deterministic
- already resolved/normalized
- validated

Bad payloads force templates to implement:
- deep traversal
- fallback logic
- inheritance resolution
- type inference

---

## 6. Model/runtime capabilities to reuse

Prefer runtime/model capabilities over custom ad-hoc parsing:
- model entity lookup APIs (`get_model_entity_by_id`, `get_entity_by_locator`, ...)
- property resolution and inherited properties (`resolve_wrapper`, resolved `wrapper.properties`)
- `Locator` helpers for robust hierarchy handling
- shared `Cache` for expensive cross-entity computations

---

## 7. Recommended implementation process

1. Define output artifacts and folder layout.
2. Define payload contracts per template.
3. Build model access/resolver helpers.
4. Implement payload builders per artifact family.
5. Write templates last, keep them thin.

---

## 8. Python vs Jinja responsibilities

Put into Python:
- model traversal
- property/inheritance resolution
- naming and type mapping
- sorting/grouping/planning
- output path calculation
- validation/fallbacks

Put into Jinja:
- final syntax layout
- light loops and conditions

Avoid in Jinja:
- recursive traversal
- property inheritance logic
- cross-file planning

---

## 9. Determinism and maintainability

Generated output should be deterministic:
- stable sorting
- stable file/path naming
- explicit ordering

Each target should keep `ARCHITECTURE.md` current with:
- payload-to-template mapping
- contracts
- extension points
- validation checklist

---

## 10. Property-driven behavior by sample target

The detailed matrices are documented in:
- [`Generate/databricks-lake/ARCHITECTURE.md`](../Generate/databricks-lake/ARCHITECTURE.md)
- [`Generate/powerbi-tabular/ARCHITECTURE.md`](../Generate/powerbi-tabular/ARCHITECTURE.md)
- [`Generate/docs/ARCHITECTURE.md`](../Generate/docs/ARCHITECTURE.md)

Use these sections as source of truth when adding new properties.
