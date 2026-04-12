"""事件驱动图谱更新

监听业务事件，自动更新知识图谱：
- knowledge.document.processed -> 从新文档块中抽取实体/关系
- menu.dish_updated -> 更新菜品节点和食材关系
- supply.supplier_updated -> 更新供应商节点
"""
from __future__ import annotations

from typing import Any

import structlog

from .graph_extractor import GraphExtractor
from .pg_graph_repository import PgGraphRepository

logger = structlog.get_logger()


class GraphEventHandler:
    """事件驱动图谱维护"""

    @staticmethod
    async def on_document_processed(
        chunks: list[dict[str, Any]],
        tenant_id: str,
        db: Any,
    ) -> dict[str, int]:
        """文档处理完成后，从块中抽取实体/关系并写入图谱。

        Returns: {entities_created, relationships_created}
        """
        entities_created = 0
        relationships_created = 0

        extraction_results = await GraphExtractor.extract_from_document(
            chunks=chunks,
            tenant_id=tenant_id,
        )

        # 实体去重缓存（name:label -> node_id）
        entity_cache: dict[str, str] = {}

        for result in extraction_results:
            # 写入实体
            for entity in result.entities:
                cache_key = f"{entity.name}:{entity.label}"
                if cache_key not in entity_cache:
                    node_id = await PgGraphRepository.upsert_node(
                        tenant_id=tenant_id,
                        label=entity.label,
                        name=entity.name,
                        properties=entity.properties,
                        db=db,
                    )
                    if node_id:
                        entity_cache[cache_key] = node_id
                        entities_created += 1

            # 写入关系
            for rel in result.relationships:
                from_key = f"{rel.from_entity}:{rel.from_label}"
                to_key = f"{rel.to_entity}:{rel.to_label}"

                from_id = entity_cache.get(from_key)
                to_id = entity_cache.get(to_key)

                if from_id and to_id:
                    edge_id = await PgGraphRepository.upsert_edge(
                        tenant_id=tenant_id,
                        from_node_id=from_id,
                        to_node_id=to_id,
                        rel_type=rel.rel_type,
                        properties=rel.properties,
                        db=db,
                        source_chunk_id=result.chunk_id if len(result.chunk_id) == 36 else None,
                    )
                    if edge_id:
                        relationships_created += 1

        logger.info(
            "graph_event_document_processed",
            tenant_id=tenant_id,
            chunks_processed=len(chunks),
            entities_created=entities_created,
            relationships_created=relationships_created,
        )

        return {
            "entities_created": entities_created,
            "relationships_created": relationships_created,
        }

    @staticmethod
    async def on_dish_updated(
        dish_data: dict[str, Any],
        tenant_id: str,
        db: Any,
    ) -> None:
        """菜品更新时，同步更新图谱中的菜品节点和食材关系"""
        dish_name = dish_data.get("name", "")
        if not dish_name:
            return

        # 更新菜品节点
        dish_node_id = await PgGraphRepository.upsert_node(
            tenant_id=tenant_id,
            label="Dish",
            name=dish_name,
            properties={
                "price_fen": dish_data.get("price_fen"),
                "category": dish_data.get("category"),
            },
            db=db,
        )

        # 更新食材关系（如果有 BOM 数据）
        ingredients = dish_data.get("ingredients", [])
        for ing in ingredients:
            ing_name = ing.get("name", "")
            if not ing_name:
                continue

            ing_node_id = await PgGraphRepository.upsert_node(
                tenant_id=tenant_id,
                label="Ingredient",
                name=ing_name,
                properties={"unit": ing.get("unit", "g")},
                db=db,
            )

            if dish_node_id and ing_node_id:
                await PgGraphRepository.upsert_edge(
                    tenant_id=tenant_id,
                    from_node_id=dish_node_id,
                    to_node_id=ing_node_id,
                    rel_type="USES_INGREDIENT",
                    properties={
                        "quantity_g": ing.get("quantity_g"),
                        "yield_rate": ing.get("yield_rate"),
                    },
                    db=db,
                )

        logger.info("graph_event_dish_updated", dish=dish_name, ingredients=len(ingredients))

    @staticmethod
    async def on_supplier_changed(
        supplier_data: dict[str, Any],
        tenant_id: str,
        db: Any,
    ) -> None:
        """供应商变更时，更新图谱"""
        supplier_name = supplier_data.get("name", "")
        if not supplier_name:
            return

        await PgGraphRepository.upsert_node(
            tenant_id=tenant_id,
            label="Supplier",
            name=supplier_name,
            properties={
                "contact": supplier_data.get("contact"),
                "region": supplier_data.get("region"),
            },
            db=db,
        )

        logger.info("graph_event_supplier_changed", supplier=supplier_name)
