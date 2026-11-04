# Solutions migration and sample cleanup

Branch: `feature/sample-solutions-cleanup`, based on the sample main revision.
The corresponding Solutions migration must be accepted before this cleanup merges.

Retained: the small AdventureWorks customer/address/order model, its linked Core/Curated entities, classic databricks-lake, Docs, Power BI and Generate-only.
Removed: Lakeflow target/bundle, live bundle bindings, cloud integration runner,
integration-only tests and workflows, and the obsolete Azure pipeline.
Pure graph/asset checks remain for local generation.

## Manual review boundary

No tests have been run for this branch. Before the user's explicit review,
Generate-only is dispatch-only and guarded by an approved exact commit setting.
The independent test model subsequently checks generation, links, source privacy
and the absence of imports of removed integration modules. PR/main triggers are
restored only after that approval. Both branches must be reviewed together.

## Prior public exposure

Previous main contained real workspace hosts, catalog names and principal IDs
in bundle.targets.yml, tests/integration/environments.json and deployment guides;
one bundle also contained a personal account. An unused system-properties module
contained infrastructure defaults. These are removed/neutralized in this branch.
Deleting them does not erase Git history, forks, caches or previous Actions logs
and artifacts. This is an inventory, not a completed historical credential audit.
No history rewrite, artifact deletion, credential rotation or cloud destruction
is implicitly performed. Any actual credential exposure requires separate handling.

The full imported model is preserved independently under databricks/ and fabric/ in Solutions. Solutions deployments read their own platform models; they do not fetch this reduced public model. The remaining metadata intentionally contains only
AdventureWorks and the Customer, Address, Order and Calendar dependency closure.
