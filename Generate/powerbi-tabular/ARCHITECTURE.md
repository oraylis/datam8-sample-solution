# Power BI Tabular Generator Architecture

## Purpose
This target generates TMDL artifacts for consumer entities:
- database metadata
- model metadata
- expressions/parameters
- relationships
- table definitions

## Generation Flow
1. `__modules/payload.py` collects and caches table metadata.
2. Relationship payloads resolve explicit mappings first, then infer fallbacks.
3. Jinja templates render files under `powerbi-tabular/`.

## Payload to Template Mapping
- `database_payload` -> `database.tmdl.jinja2`
- `model_payload` -> `model.tmdl.jinja2`
- `expressions_payload` -> `expressions.tmdl.jinja2`
- `relationships_payload` -> `relationships.tmdl.jinja2`
- `table_payloads` -> `table.tmdl.jinja2`

## Important Internal Contracts
- Consumer entities are filtered by `CONSUMER_FOLDER`.
- `_ensure_tables_cached` stores tables under cache key `("powerbi", "tables")`.
- Relationship resolution uses both:
  - explicit relationship metadata
  - source-based fallback inference

## Template Style
- TMDL templates remain explicit and close to emitted output structure.
- Prefer helper logic in payload code when deduplication is needed.

## Extension Points
1. Add attributes to `TableDefinition`/`RelationshipDefinition`.
2. Populate in collection helpers.
3. Render in TMDL templates while preserving syntax.

## Validation Checklist
1. Run lint: `ruff check Generate/powerbi-tabular/__modules`
2. Generate output and verify table/relationship names with spaces still quote correctly.
