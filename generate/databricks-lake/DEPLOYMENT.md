# Classic Target: Generation Only

This target renders notebooks and resource definitions. It contains no
environment-bound bundle entrypoint or cloud execution workflow. Configure your
own deployment process after reviewing platform, source and identity prerequisites;
generated files are not deployment evidence.

The utilities retained under `utils` are neutral runtime
source assets required by generated references, not deployment configuration.
Keep them separate from cleaned output. See [local generation](../../docs/getting-started.md)
and [deployment boundaries](../../docs/quickstart.md).
