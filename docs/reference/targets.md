# Configured Targets and Output Paths

The solution descriptor contains exactly three local generation targets.

| Target | Template source | Configured output root |
| --- | --- | --- |
| databricks | `generate/databricks-lake` | `output/databricks` |
| powerbi | `generate/powerbi-tabular` | `output/powerbi` |
| docs | `generate/docs` | `output/docs` |

Each target writes only inside its own output folder. The authored runtime
notebooks in `utils/` and the neutral bundle in `deployment/databricks/` survive
clean generation. Supply your own environment settings and follow the
[deployment guides](../quickstart.md) after reviewing generated artifacts.
