from __future__ import annotations

from collections.abc import Sequence, Iterable
from pathlib import Path
from typing import Any
import re

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache

from metadata_utils import (
    MetadataResolver,
    build_business_key_partitions,
    build_delta_table_properties,
    collect_column_tags,
    collect_imports,
    collect_refactored_columns,
    format_table_tag_values,
    merge_table_tags,
)


from system_properties import AtScale

logger = start_logger(__name__)







@register_payload("atscale/catalog.yml.jinja2")
def generate_atscale_catalog_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build SML from 050-AtScale zone."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    payloads.append(
        BasePayload(
            data={
                "atscale_prpoerties": AtScale()
            },
            output_path=Path(
                "atscale",
                f"catalog.yml",
            ),
        )
    )
    return payloads

@register_payload("atscale/connection.yml.jinja2")
def generate_atscale_connections_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build SML from 050-AtScale zone."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    payloads.append(
        BasePayload(
            data={
                "atscale_prpoerties": AtScale()
            },
            output_path=Path(
                "atscale",
                "connections",
                f"{AtScale().connection_filename}.yml",
            ),
        )
    )
    return payloads

@register_payload("atscale/dataset.yml.jinja2")
def generate_atscale_datasets_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-raw) entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name not in "atscale":
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

        # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        foreign_key_columns = resolver.foreign_key_columns(entity)
        modeled_columns = resolver.build_standard_columns(
            entity,
            foreign_key_columns=foreign_key_columns,
        )
        columns = modeled_columns
        
        imports = collect_imports(columns)
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        payloads.append(
            BasePayload(
                data={
                    "atscale_prpoerties": AtScale(),
                    "zone": zone_meta.name,
                    "zone_display": zone_meta.display_name,
                    "data_product": data_product_name,
                    "data_module": data_module_name,
                    "table_name": entity.name,
                    "table_label": entity.name,
                    "full_table_name": f"{data_product_name}_{data_module_name}_{entity.name}",
                    "table_comment": entity.description or "",
                    "columns": columns,
                    "imports": imports,
                    "partitions": partitions,
                    "table_tags_repr": repr(table_tags_output),
                    "table_properties": table_properties,
                    "column_tags": column_tags,
                    "refactored_columns": refactored_columns,
                },
                output_path=Path(
                    "atscale",
                    "datasets",
                    data_module_name,
                    f"{locator.entityName or entity.name}.yml",
                ),
            )
        )

    return payloads



@register_payload("atscale/dimension.yml.jinja2")
def generate_atscale_dimensions_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-raw) entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name not in "atscale":
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

        if not resolver.is_dimension_table(entity):
            logger.debug("Skipping other that dimensions: %s", locator)
            continue

        # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        foreign_key_columns = resolver.foreign_key_columns(entity)
        modeled_columns = resolver.build_standard_columns(
            entity,
            foreign_key_columns=foreign_key_columns,
        )
        hierarchies = resolver.build_hierarchies(entity);
        level_attributes = resolver.build_level_attributes(entity);
        
        
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        payloads.append(
            BasePayload(
                data={
                    "atscale_prpoerties": AtScale(),
                    "zone": zone_meta.name,
                    "zone_display": zone_meta.display_name,
                    "data_product": data_product_name,
                    "data_module": data_module_name,
                    "table_name": entity.name,
                    "dimension_name": f"dim_{entity.name}",
                    "dimension_label": f"dim_{entity.name}",
                    "dimension_description": entity.description,
                    "hierarchies": hierarchies,
                    "level_attributes": level_attributes,
                },
                output_path=Path(
                    "atscale",
                    "dimensions",
                    data_module_name,
                    f"{locator.entityName or entity.name}.yml",
                ),
            )
        )

    return payloads

@register_payload("atscale/metric.yml.jinja2")
def generate_atscale_metrics_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-raw) entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name not in "atscale":
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

          # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        foreign_key_columns = resolver.foreign_key_columns(entity)
        modeled_columns = resolver.build_standard_columns(
            entity,
            foreign_key_columns=foreign_key_columns,
        )

        
        
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)

        for a in entity.attributes:
            ap = resolver.get_property_by_name(a, "aggregation_hint")     
            if ap != None:       
                payloads.append(
                    BasePayload(
                        data={
                            "column_name": a.name,
                            "column_aggregation_hint": ap,
                            "column_dataset_name": entity.name
                        },
                        output_path=Path(
                            "atscale",
                            "metrics",
                            data_module_name,
                            f"{a.name}_{ap}.yml",
                        ),
                    )
                )

    return payloads

@register_payload("atscale/model.yml.jinja2")
def generate_atscale_model_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build DDL payloads for modeled (non-raw) entities."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []

    payloads.append(
        BasePayload(
            data={
                "atscale_prpoerties": AtScale(),
                "dimensions": get_dimensions(resolver, model),
                "metrics" : get_metrics(resolver, model),
                "relationships": get_relationships(resolver, model)
            },
            output_path=Path(
                "atscale",
                "models",
                f"model.yml",
            ),
        )
    )

    return payloads

def get_dimensions(resolver, model):
    ret = []
    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        if not locator.folders:
            logger.debug("Skipping entity without folder information: %s", locator)
            continue

        zone_meta = resolver.zone_from_folder(locator.folders[0])
        if zone_meta is None:
            logger.warning("Zone metadata missing for folder '%s'. Skipping entity %s.", locator.folders[0], locator)
            continue

        if zone_meta.name not in "atscale":
            logger.debug("Skipping unsupported zone '%s' for Databricks DDL: %s", zone_meta.name, locator)
            continue

        if not resolver.is_dimension_table(entity):
            logger.debug("Skipping other that dimensions: %s", locator)
            continue

        # Determine product/module metadata via folder properties.
        product_info = resolver.folder_info(tuple(locator.folders[:2])) if len(locator.folders) >= 2 else None
        module_info = resolver.folder_info(tuple(locator.folders[:3])) if len(locator.folders) >= 3 else None

        data_product_name = product_info.name if product_info else (locator.folders[1] if len(locator.folders) >= 2 else "UnknownProduct")
        data_module_name = module_info.name if module_info else (locator.folders[2] if len(locator.folders) >= 3 else "General")

        # Assemble shared metadata for the standard notebook.
        foreign_key_columns = resolver.foreign_key_columns(entity)
        modeled_columns = resolver.build_standard_columns(
            entity,
            foreign_key_columns=foreign_key_columns,
        )
        hierarchies = resolver.build_hierarchies(entity);
        level_attributes = resolver.build_level_attributes(entity);
        
        
        partitions = build_business_key_partitions(entity)
        table_tags = merge_table_tags(entity, product_info, module_info)
        table_properties = build_delta_table_properties(table_tags)
        table_tags_output = format_table_tag_values(table_tags)
        column_tags = collect_column_tags(entity)
        refactored_columns = collect_refactored_columns(entity)
        zone_folder_name = resolver.zone_folder_name(zone_meta)
        ret.append(
        {
            "atscale_prpoerties": AtScale(),
            "zone": zone_meta.name,
            "zone_display": zone_meta.display_name,
            "data_product": data_product_name,
            "data_module": data_module_name,
            "table_name": entity.name,
            "dimension_name": f"dim_{entity.name}",
            "dimension_label": f"dim_{entity.name}",
            "dimension_description": entity.description,
            "hierarchies": hierarchies,
            "level_attributes": level_attributes,
        })
    return ret       

def get_relationships(resolver, model):
    ret = []
    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity

        rels = resolver.getAttr(entity, "relationships")

        targetid = resolver.getAttr(rels, "targetLocation")

        targetEntity = get_entity_by_id(resolver, model, targetid)

        for rel_attr in rels.attributes:
            targetName = resolver.get_property_by_name(rel_attr, "targetName")
            sourceName = resolver.get_property_by_name(rel_attr, "sourceName")

            ret.append(
                {
                    "unique_name": f"{entity.name}_to_{targetEntity.name}",
                    "from_dataset": entity.name,
                    "from_column": sourceName,
                    "to_dimension": f"dim_{targetEntity.name}",
                    "to_column": targetName
                }
            )
    return ret


def get_entity_by_id(resolver, model, targetid) -> Any :
    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        if entity.id == targetid:
            return entity
    return None




def get_metrics(resolver, model):
    ret = []
    for locator, wrapper in model.modelEntities.items():
        entity = wrapper.entity
        for a in entity.attributes:
            ap = resolver.get_property_by_name(a, "aggregation_hint")     
            if ap != None:       
                ret.append(            
                    {
                        "column_name": a.name,
                        "column_aggregation_hint": ap,
                        "column_dataset_name": entity.name
                    }
                )
    return ret
