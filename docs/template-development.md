# Template and Payload Development

Start from the selected target's [architecture](reference/targets.md). Python
payload builders interpret model objects and properties; Jinja renders prepared
data. Put complex joins, ordering and target decisions in Python rather than templates.

## Documentation target example

Read [payload.py](../Generate/docs/__modules/payload.py) and
[the architecture](../Generate/docs/ARCHITECTURE.md). The target builds one cached
documentation snapshot, then registers payloads for index, entity pages and a diagram.
The existing index payload uses this shape:

```python
@register_payload("index.md.jinja2", order=1)
def documentation_index(model, cache):
    documentation = _get_documentation(model, cache)
    return [BasePayload(data={"doc": documentation}, output_path=Path("index.md"))]
```

This excerpt belongs inside the existing module with its imports and builder;
it is not a complete standalone plugin. Inspect the backend's
[generate implementation](https://github.com/oraylis/datam8-cli/blob/feature/external_refresh/src/datam8/generate.py) for engine behavior.

## Change and verify

1. Work on a complete sample copy using DataM8 app 2.0.0 or CLI 2.0.0.
2. Add/shape a field in Python and update its Jinja consumer.
3. Generate that target in the app or with the [CLI](getting-started.md).
4. Assert new output content, links, ordering and paths; compare unchanged output
   with the parity script when required.
5. Update the affected target architecture and central user chapter if behavior changes.

Generation prepares files. Deployment credentials, resource creation and target
execution belong to a separate [deployment workflow](quickstart.md).
