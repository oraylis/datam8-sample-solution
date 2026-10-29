"""Small metadata helpers for the native Lakeflow dataset plan."""
from typing import Any
from datam8.model import EntityWrapper, Model
from datam8_model.model import ModelEntity
from datam8_model.property import PropertyReference

TARGET = "databricks"
TYPE_ALIASES = {"integer": "int", "bigint": "long", "boolean": "bit", "timestamp": "datetime"}


def target_data_type(model: Model, data_type: Any) -> str:
    name = TYPE_ALIASES.get(data_type.type.lower(), data_type.type)
    definition = get_one(model.dataTypes, name).entity
    result = definition.targets[TARGET]
    if result.lower() == "decimal" and data_type.precision is not None:
        result += f"({data_type.precision}"
        if data_type.scale is not None:
            result += f", {data_type.scale}"
        result += ")"
    return result


def _locator_path(locator: Any) -> str:
    """Convert a DataM8 locator object into a simple slash-separated path."""
    folders = list(getattr(locator, "folders", []) or [])
    entity_name = getattr(locator, "entityName", None)
    return "/".join([*folders, entity_name] if entity_name else folders)


def get_one(collection: Any, locator_path: str) -> Any:
    """Return exactly one wrapper by locator path.

    The helper works with both DataM8 collections and fallback dictionaries.
    """
    path = locator_path.strip("/")
    for locator, wrapper in collection.items():
        if _locator_path(locator) == path:
            return wrapper
    raise KeyError(locator_path)


def get_property_refs(model: Model, wrapper: EntityWrapper[ModelEntity]) -> list[PropertyReference]:
    """Return properties directly on an entity plus properties inherited from folders."""
    refs = list(wrapper.entity.properties or [])
    folders = list(wrapper.locator.folders)
    for index in range(len(folders), 0, -1):
        try:
            folder = get_one(model.folders, "/".join(folders[:index]))
        except KeyError:
            continue
        refs.extend(folder.entity.properties or [])
    return refs


def display_names(model: Model, property_name: str) -> dict[str, str]:
    """Resolve model-authored display names for a property-value family."""
    result = {}
    for wrapper in model.propertyValues.values():
        value = wrapper.entity
        if getattr(value, "property", None) == property_name and getattr(value, "name", None):
            result[value.name] = getattr(value, "displayName", None) or value.name
    return result


def zone_display_names(model: Model) -> dict[str, str]:
    """Resolve model-authored display names for zones."""
    return {
        wrapper.entity.name: getattr(wrapper.entity, "displayName", None) or wrapper.entity.name
        for wrapper in model.zones.values()
    }
