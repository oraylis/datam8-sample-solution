# Documentation Target Architecture

## Purpose
This target produces model documentation artifacts:
- overview page (`index.md`)
- per-entity pages
- draw.io relationship diagram (`diagrams/entity-relationships.drawio`)

## Generation Flow
1. `__modules/payload.py` builds one cached `DocumentationResult`.
2. The snapshot is reused across all payload registrations:
   - `index.md.jinja2`
   - `entity.md.jinja2`
   - `er_diagram.drawio.jinja2`
3. `__modules/documentation.py` computes entity/source/relationship/diagram data.

Generated output paths are `index.md`, `entities/**/*.md`, and
`diagrams/entity-relationships.drawio` relative to the target output folder.

## Key Builder Responsibilities
- Resolve zone/product/module metadata from validated model entities.
- Normalize attribute/source/relationship structures into typed dataclasses.
- Build inbound relationship lists after outbound relationship collection.
- Build diagram nodes/edges with deterministic zone grouping and color mapping.

## Property-Driven Behavior

This target is mostly descriptive: it does not filter entities by custom properties.

| Property | Scope | Output impact |
|---|---|---|
| any entity/source/attribute property | model metadata | Rendered into documentation pages (entity properties, source properties, attribute properties). |
| `attribute_type=sk` | attribute properties | Marks attributes as surrogate keys in entity documentation tables. |
| zone `target` (zone metadata) | zone | Displayed as zone target information in docs; not used to include/exclude entities. |

## Template Style
- Documentation templates stay explicit and close to rendered Markdown.
- Keep Jinja indirection low; prefer Python-side shaping in `documentation.py`.

## Extension Points
1. Add new fields to `EntityDoc`/`DocumentationResult`.
2. Populate fields in `DocumentationBuilder`.
3. Render the new fields in templates.

## Validation Checklist
1. Run lint: `ruff check Generate/docs/__modules`
2. Generate docs and verify:
   - entity links are correct
   - diagram opens in draw.io
   - source/relationship counts remain stable
