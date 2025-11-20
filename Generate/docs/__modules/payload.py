from __future__ import annotations

from pathlib import Path
from typing import Sequence

from dm8gen.generate import BasePayload, IPayload, register_payload
from dm8gen.model import Model
from dm8gen.utils import start_logger
from dm8gen.utils.cache import Cache

from documentation import DocumentationBuilder, DocumentationResult

logger = start_logger(__name__)
DOC_CACHE_KEY = "docs.documentation"


def _get_documentation(model: Model, cache: Cache) -> DocumentationResult:
    try:
        return cache.get(DOC_CACHE_KEY)
    except KeyError:
        builder = DocumentationBuilder(model)
        result = builder.build()
        cache.set(DOC_CACHE_KEY, result)
        logger.info("Built documentation snapshot with %d entities", len(result.entities))
        return result


@register_payload("index.md.jinja2", order=1)
def documentation_index(model: Model, cache: Cache) -> Sequence[IPayload]:
    documentation = _get_documentation(model, cache)
    return [
        BasePayload(
            data={
                "doc": documentation,
            },
            output_path=Path("index.md"),
        )
    ]


@register_payload("entity.md.jinja2", order=2)
def documentation_entities(model: Model, cache: Cache) -> Sequence[IPayload]:
    documentation = _get_documentation(model, cache)
    payloads: list[IPayload] = []
    for entity in documentation.entities:
        if not entity.slug_path:
            continue
        entity_path = Path("entities", *entity.slug_path[:-1], f"{entity.slug_path[-1]}.md")
        payloads.append(
            BasePayload(
                data={
                    "doc": documentation,
                    "entity": entity,
                },
                output_path=entity_path,
            )
        )
    return payloads


@register_payload("er_diagram.drawio.jinja2", order=3)
def documentation_diagram(model: Model, cache: Cache) -> Sequence[IPayload]:
    documentation = _get_documentation(model, cache)
    return [
        BasePayload(
            data={
                "doc": documentation,
                "diagram": documentation.diagram,
            },
            output_path=Path("diagrams", "entity-relationships.drawio"),
        )
    ]
