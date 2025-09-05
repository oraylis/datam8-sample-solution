from pathlib import Path
from collections.abc import Sequence

from dm8gen.generate import Payload, register_payload
from dm8gen.model import Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache
from helper import Helper

logger = start_logger(__name__)


@register_payload("data_sources.md.jinja2")
def test(model: Model, cache: Cache) -> Sequence[Payload]:
    cache.set("test", True)
    logger.warning(f"test error {cache}")

    logger.debug("test")
    payloads = [
        Payload(
            data=ds,
            output_path=Path("zones", f"{ds.entity.name}.md"),
        )
        for ds in model.dataSources.values()
    ]

    return payloads


@register_payload("ddl_notebook.py.jinja2", order=2)
def model_entities(model: Model, cache: Cache) -> Sequence[Payload]:
    entities = model.modelEntities
    # filter dynamically base on locator, e.g.
    # entities: list[EntityWrapper[ModelEntity]] = model.get_entities("modelEntities/010-stage")

    payloads = [
        Payload(
            data={
                "locator": locator,
                "name": entity.entity.name,
                "attributes": entity.entity.attributes,
                "parameters": entity.entity.parameters,
                "cached_value": cache.get("test"),
            },
            output_path=Path("notebooks", *entity.locator.folders, f"{entity.locator.entityName}.py"),
        )
        for locator, entity in entities.items()
    ]

    return payloads
