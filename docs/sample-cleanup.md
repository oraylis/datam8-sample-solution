# Sample Cleanup Handoff

This historical handoff records the reduction to a public, generate-only sample.
Its branch-state and review statements describe that cleanup. Current local
verification follows [local checks](integration-tests.md); the historical test
hold below is no longer the working policy.

Retained: the small AdventureWorks customer/address/order model, its linked Core/Curated entities, classic databricks-lake, Docs, Power BI and Generate-only.
Removed: Lakeflow target/bundle, live bundle bindings, cloud integration runner,
integration-only tests and workflows, and the obsolete Azure pipeline.
Pure graph/asset checks remain for local generation.

## Historical manual review boundary

At the original cleanup handoff, no tests had been run for that branch. Before the user's explicit review,
Generate-only is dispatch-only and guarded by an approved exact commit setting.
The independent test model subsequently checks generation, links, source privacy
and the absence of imports of removed integration modules. PR/main triggers are
restored only after that approval. This section records the former migration process.

## Prior public exposure

Previous main contained real workspace hosts, catalog names and principal IDs
in bundle.targets.yml, tests/integration/environments.json and deployment guides;
one bundle also contained a personal account. An unused system-properties module
contained infrastructure defaults. These are removed/neutralized in this branch.
Deleting them does not erase Git history, forks, caches or previous Actions logs
and artifacts. This is an inventory, not a completed historical credential audit.
No history rewrite, artifact deletion, credential rotation or cloud destruction
is implicitly performed. Any actual credential exposure requires separate handling.

The retained metadata intentionally contains only AdventureWorks and the Customer,
Address, Order and Calendar dependency closure. The target reference documents
the three local generation targets.
