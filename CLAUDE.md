# DataM8 Sample Solution - Essential Commands

## Core Commands

### Validate Model
```bash
dm8gen validate -s ORAYLISDatabricksSample.dm8s
```
Purpose: validates all Base/Model entities using generator classes and schema validation.

When to use:
- After adding or changing model files
- Before generation in CI/CD

### Generate Templates
```bash
dm8gen generate databricks -s ORAYLISDatabricksSample.dm8s --clean-output
```
Purpose: generates Databricks artifacts from the configured target in the solution file.

When to use:
- After model or template changes
- For deployment preparation

### Generate All Default Targets
```bash
dm8gen generate -s ORAYLISDatabricksSample.dm8s --clean-output
```
Purpose: generates all default targets configured in the solution.

## Project Structure

```text
datam8-sample-solution/
|- ORAYLISDatabricksSample.dm8s
|- Base/
|- Model/
|- Generate/
|- Output/
`- scripts/
```

## Quick Workflow

1. Modify entities in `Model/`
2. Validate: `dm8gen validate -s ORAYLISDatabricksSample.dm8s`
3. Generate: `dm8gen generate databricks -s ORAYLISDatabricksSample.dm8s --clean-output`
4. Review output in `Output/`

## Notes

- The template workflow is index-free.
- Do not rely on or commit legacy index artifacts.
