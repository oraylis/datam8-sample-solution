# DataM8 Sample Solution - Essential Commands

## Core Commands

### Validate/Refresh Index
```bash
dm8gen -a validate_index -s ORAYLISDatabricksSample.dm8s
```
**Purpose**: Validates entity definitions and rebuilds the entity index (`index.json`). This discovers all entities across zones and builds cross-references.

**When to use**:
- After adding/modifying entity definitions
- When entity relationships change
- Before generating templates to ensure index is current

### Generate Templates
```bash
dm8gen -a generate_template -s ORAYLISDatabricksSample.dm8s -src Generate/databricks-lake/ -dest Output/
```
**Purpose**: Generates code from Jinja2 templates using entity definitions and zone configuration.

**Parameters**:
- `-s`: Solution file (`.dm8s`)
- `-src`: Template source directory
- `-dest`: Output directory for generated code

**When to use**:
- After making schema changes
- When updating templates
- For production deployments

### Full Refresh & Generate
```bash
dm8gen -a refresh_generate -s ORAYLISDatabricksSample.dm8s -src Generate/databricks-lake/ -dest Output/
```
**Purpose**: Combines index validation and template generation in one command.

**When to use**:
- For complete refresh after major changes
- CI/CD pipeline automation
- Clean rebuilds

## Project Structure

```
datam8-sample-solution/
├── ORAYLISDatabricksSample.dm8s  # Solution configuration
├── Base/                         # Foundation definitions
│   ├── Zones.json               # Zone configuration (dynamic)
│   ├── DataSources.json         # Data source definitions
│   └── AttributeTypes.json      # Semantic attribute types
├── Model/                       # Entity definitions by zone
│   ├── 010-Stage/            # Bronze layer entities
│   ├── 020-Core/               # Silver layer entities  
│   └── 030-Curated/            # Gold layer entities
├── Generate/                    # Jinja2 templates
│   └── databricks-lake/        # Databricks-specific templates
├── Output/                      # Generated code
└── index.json                  # Auto-generated entity index
```

## Zone Configuration

This project uses **dynamic zones** defined in `Base/Zones.json`:
- **raw** → `000-Raw` (derived from stage)
- **stage** → `010-Stage` (bronze layer)
- **core** → `020-Core` (silver layer)  
- **curated** → `030-Curated` (gold layer)

## Quick Workflow

1. **Modify entities** in `Model/` directories
2. **Refresh index**: `dm8gen -a validate_index -s ORAYLISDatabricksSample.dm8s`
3. **Generate code**: `dm8gen -a generate_template -s ORAYLISDatabricksSample.dm8s -src Generate/databricks-lake/ -dest Output/`
4. **Review output** in `Output/` directory

## Notes

- Index validation automatically discovers entities using dynamic zone configuration
- Template generation supports any zones defined in `Zones.json`
- Raw entities are derived from stage entities with system sources
- All paths and zone mappings are dynamic - no hard-coded limitations