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
def generate_atscale_sml(model: Model, cache: Cache) -> Sequence[IPayload]:
    """Build SML from 050-AtScale zone."""
    resolver = MetadataResolver(model)
    payloads: list[IPayload] = []
    payloads.append(
        BasePayload(
            data={
                "catalog_name": AtScale().catalog_name,
                "catalog_label": AtScale().catalog_label,
            },
            output_path=Path(
                "atscale",
                zone_folder_name,
                "sml",
                *tuple(locator.folders[1:]),
                f"{locator.entityName or entity.name}.sml",
            ),
        )
   

    return payloads