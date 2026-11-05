# From Generated Files to Deployment

First [build your own solution](build-your-own-solution.md): fork or copy the
complete sample, keep its dependency pins, extend the model and its mappings,
then validate and generate the affected targets. This path needs no credentials
or cloud account.

Once those artifacts are ready, choose the next step:

| Task | Guide | Expected result |
| --- | --- | --- |
| Run the data platform in your own environment | [Databricks deployment](../generate/databricks-lake/DEPLOYMENT.md) | Personal dev bundle, created tables and ordered successful loads |
| Create and publish a report | [Power BI Desktop/PBIP integration](powerbi-deployment.md) | Authored report using the generated semantic model and your own connection parameters |
| Share model documentation | [Docs target](../generate/docs/README.md) | Local Markdown catalog and editable relationship diagram |

The neutral bundle lives under `deployment/databricks/`, authored runtime notebooks
under `utils/`, and disposable output under the [target folders](reference/targets.md).
No passwords, tokens or client secrets are supplied. Keep authentication local,
use secret references for source settings, and exclude local deployment state.

Databricks deploy/run and Power BI refresh/publish are explicit operator actions
against your own environment. They are not part of local generation or CI; review
prerequisites and generated diffs before running them. The sample contains no live
integration runner or XMLA publisher. Local checks do not establish cloud acceptance.
