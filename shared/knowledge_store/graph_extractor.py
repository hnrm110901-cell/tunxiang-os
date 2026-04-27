"""LightRAG 实体/关系抽取器

从文档块中提取餐饮领域的实体和关系三元组：
- 使用 Claude API 从文本中识别实体和关系
- 降级模式：基于规则的关键词抽取
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 15.0

# 餐饮领域实体类型
ENTITY_TYPES = [
    "Dish",
    "Ingredient",
    "Supplier",
    "Regulation",
    "Procedure",
    "Equipment",
    "Allergen",
    "Certification",
    "Season",
    "DishPairing",
]

# 关系类型
RELATIONSHIP_TYPES = [
    "USES_INGREDIENT",
    "SUPPLIED_BY",
    "ALLERGEN_WARNING",
    "SEASONAL_AVAILABLE",
    "SUBSTITUTABLE_BY",
    "REQUIRES_CERTIFICATION",
    "INSPECTION_COVERS",
    "PAIRS_WITH",
    "UPSELL_WITH",
    "REGULATED_BY",
    "PROCEDURE_FOR",
    "BELONGS_TO",
]


@dataclass
class ExtractedEntity:
    name: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedRelationship:
    from_entity: str
    from_label: str
    to_entity: str
    to_label: str
    rel_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    chunk_id: str


class GraphExtractor:
    """知识图谱实体/关系抽取器"""

    @staticmethod
    async def extract_from_chunk(
        chunk_text: str,
        chunk_id: str,
        tenant_id: str,
    ) -> ExtractionResult:
        """从单个文档块中抽取实体和关系。

        优先使用 Claude API，降级使用规则抽取。
        """
        if not chunk_text or not chunk_text.strip():
            return ExtractionResult(entities=[], relationships=[], chunk_id=chunk_id)

        if _ANTHROPIC_API_KEY:
            result = await _extract_with_llm(chunk_text, chunk_id)
            if result:
                return result

        # 降级：规则抽取
        return _extract_with_rules(chunk_text, chunk_id)

    @staticmethod
    async def extract_from_document(
        chunks: list[dict[str, Any]],
        tenant_id: str,
        batch_size: int = 5,
    ) -> list[ExtractionResult]:
        """从文档的所有块中批量抽取。"""
        results = []
        for chunk in chunks:
            result = await GraphExtractor.extract_from_chunk(
                chunk_text=chunk.get("text", ""),
                chunk_id=chunk.get("chunk_id", chunk.get("doc_id", "")),
                tenant_id=tenant_id,
            )
            results.append(result)
        return results


async def _extract_with_llm(chunk_text: str, chunk_id: str) -> ExtractionResult | None:
    """使用 Claude 抽取实体和关系"""
    try:
        prompt = f"""从以下餐饮行业文本中提取实体和关系。

实体类型：{", ".join(ENTITY_TYPES)}
关系类型：{", ".join(RELATIONSHIP_TYPES)}

文本：
{chunk_text[:2000]}

请以JSON格式返回：
{{
  "entities": [{{"name": "实体名", "label": "类型", "properties": {{}}}}],
  "relationships": [{{"from": "实体1", "from_label": "类型", "to": "实体2", "to_label": "类型", "rel_type": "关系类型"}}]
}}

只返回JSON，不要其他文字。如果没有发现实体或关系，返回空列表。"""

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _API_URL,
                json={
                    "model": _MODEL,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "x-api-key": _ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code != 200:
                return None

            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "")

            # 解析 JSON
            import json

            # 提取 JSON 块
            json_match = re.search(r"\{[\s\S]*\}", text)
            if not json_match:
                return None

            parsed = json.loads(json_match.group())

            entities = [
                ExtractedEntity(
                    name=e.get("name", ""),
                    label=e.get("label", ""),
                    properties=e.get("properties", {}),
                )
                for e in parsed.get("entities", [])
                if e.get("name") and e.get("label") in ENTITY_TYPES
            ]

            relationships = [
                ExtractedRelationship(
                    from_entity=r.get("from", ""),
                    from_label=r.get("from_label", ""),
                    to_entity=r.get("to", ""),
                    to_label=r.get("to_label", ""),
                    rel_type=r.get("rel_type", ""),
                )
                for r in parsed.get("relationships", [])
                if r.get("from") and r.get("to") and r.get("rel_type") in RELATIONSHIP_TYPES
            ]

            logger.info(
                "graph_extract_llm_ok", chunk_id=chunk_id, entities=len(entities), relationships=len(relationships)
            )
            return ExtractionResult(entities=entities, relationships=relationships, chunk_id=chunk_id)

    except Exception as exc:
        logger.warning("graph_extract_llm_failed", error=str(exc), exc_info=True)
        return None


def _extract_with_rules(chunk_text: str, chunk_id: str) -> ExtractionResult:
    """基于规则的实体抽取（降级模式）"""
    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []

    # 菜品名称模式（中文菜名通常2-6个字）
    dish_patterns = [
        r"([\u4e00-\u9fff]{2,6}(?:鱼|肉|虾|蟹|鸡|鸭|鹅|菜|饭|面|汤|粥|饼|包|饺|糕))",
    ]
    for pattern in dish_patterns:
        for match in re.finditer(pattern, chunk_text):
            name = match.group(1)
            if name not in [e.name for e in entities]:
                entities.append(ExtractedEntity(name=name, label="Dish"))

    # 食材模式
    ingredient_patterns = [
        r"([\u4e00-\u9fff]{1,4}(?:粉|油|盐|酱|醋|糖|椒|姜|蒜|葱|料))",
    ]
    for pattern in ingredient_patterns:
        for match in re.finditer(pattern, chunk_text):
            name = match.group(1)
            if name not in [e.name for e in entities] and len(name) >= 2:
                entities.append(ExtractedEntity(name=name, label="Ingredient"))

    # 法规/标准模式
    regulation_patterns = [
        r"(《[\u4e00-\u9fff\w]+》)",
        r"(GB\s*\d+[-.\d]*)",
    ]
    for pattern in regulation_patterns:
        for match in re.finditer(pattern, chunk_text):
            name = match.group(1)
            entities.append(ExtractedEntity(name=name, label="Regulation"))

    return ExtractionResult(entities=entities, relationships=relationships, chunk_id=chunk_id)
