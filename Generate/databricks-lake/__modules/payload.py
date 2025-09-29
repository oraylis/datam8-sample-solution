from pathlib import Path
from collections.abc import Sequence

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Model, Locator
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache
# from helper import Helper

logger = start_logger(__name__)


@register_payload("data_sources.md.jinja2")
def test(model: Model, cache: Cache) -> Sequence[IPayload]:
    cache.set("test", True)
    logger.warning(f"test error {cache}")

    logger.debug("test")
    payloads = [
        BasePayload(
            data=ds,
            output_path=Path("zones", f"{ds.entity.name}.md"),
        )
        for ds in model.dataSources.values()
    ]

    return payloads


# the generator is build with an interface/protocol so any object implementing
# a `get_data()` and `get_output_path()` function will be good.
# Either a complete custom class or inherited from `BasePayload`.
class CustomPayload(BasePayload):
    locator: Locator
    name: str
    attributes: Sequence[object]
    parameters: Sequence[object]
    cached_value: bool

    def __init__(self, locator, name, attributes, parameters, cached_value=False):
        self.locator = locator
        self.name = name
        self.attributes = attributes
        self.parameters = parameters
        self.cached_value = cached_value

    def get_data(self) -> object:
        data_dict = {
            "locator": self.locator,
            "name": self.name,
            "attributes": self.attributes,
            "parameters": self.parameters,
            "cached_value": self.cached_value,
        }
        return data_dict

    def get_output_path(self) -> Path:
        parts = [
            "notebooks",
            *self.locator.folders,
            f"{self.locator.entityName}.py",
        ]
        return Path(*parts)


@register_payload("ddl_notebook.py.jinja2", order=2)
def model_entities(model: Model, cache: Cache) -> Sequence[IPayload]:
    entities = model.modelEntities
    # filter dynamically base on locator, e.g.
    # entities: list[EntityWrapper[ModelEntity]] = model.get_entities("modelEntities/010-stage")

    payloads = [
        CustomPayload(
            locator=locator,
            name=entity.entity.name,
            attributes=entity.entity.attributes,
            parameters=entity.entity.parameters,
            cached_value=cache.get("test"),
        )
        for locator, entity in entities.items()
    ]

    return payloads
