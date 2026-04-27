"""Neo4j Ontology Schema — 16 Node Labels + 24 Relationship Types

定义屯象OS知识图谱的完整本体结构。
所有实体和关系的枚举、属性要求、约束规则。
Phase 3 新增：Regulation / Procedure / Allergen / Certification / Season 节点，
以及 9 种新关系类型用于食安合规、季节菜品、过敏原预警等场景。
"""

from typing import Any

# ─── 16 Node Labels ───

NODE_LABELS = [
    "Store",
    "Brand",
    "Dish",
    "Ingredient",
    "Supplier",
    "Employee",
    "Customer",
    "Order",
    "Category",
    "Region",
    "Equipment",
    # Phase 3 — LightRAG 知识图谱扩展
    "Regulation",
    "Procedure",
    "Allergen",
    "Certification",
    "Season",
]

# ─── 24 Relationship Types ───

RELATIONSHIP_TYPES = [
    "BELONGS_TO",  # Store→Brand, Brand→Region
    "SERVES",  # Store→Dish
    "USES_INGREDIENT",  # Dish→Ingredient (with BOM quantity)
    "SUPPLIED_BY",  # Ingredient→Supplier
    "WORKS_AT",  # Employee→Store (with role, since)
    "HAS_SKILL",  # Employee→Skill
    "ORDERED",  # Customer→Order
    "CONTAINS",  # Order→Dish (with quantity, price)
    "VISITED",  # Customer→Store (with date, spend)
    "LOCATED_IN",  # Store→Region
    "COMPETES_WITH",  # Brand→Brand
    "SIMILAR_TO",  # Store→Store (similarity score)
    "CAUSES",  # Event→Event (causal chain)
    "DECIDED_BY",  # Decision→Agent
    "RESULTED_IN",  # Decision→Outcome
    # Phase 3 — LightRAG 知识图谱扩展
    "ALLERGEN_WARNING",  # Dish/Ingredient→Allergen（过敏原预警）
    "SEASONAL_AVAILABLE",  # Dish/Ingredient→Season（季节供应）
    "SUBSTITUTABLE_BY",  # Ingredient→Ingredient（可替代关系）
    "REQUIRES_CERTIFICATION",  # Store/Employee→Certification（资质要求）
    "INSPECTION_COVERS",  # Regulation→Store/Equipment（检查覆盖）
    "PAIRS_WITH",  # Dish→Dish（搭配推荐）
    "UPSELL_WITH",  # Dish→Dish（加售推荐）
    "REGULATED_BY",  # Dish/Ingredient/Store→Regulation（受监管）
    "PROCEDURE_FOR",  # Procedure→Equipment/Dish（操作规程）
]

# ─── Node Required Properties ───

NODE_REQUIRED_PROPERTIES: dict[str, list[str]] = {
    "Store": ["name", "tenant_id"],
    "Brand": ["name", "tenant_id"],
    "Dish": ["name", "tenant_id", "price_fen"],
    "Ingredient": ["name", "tenant_id", "unit"],
    "Supplier": ["name", "tenant_id"],
    "Employee": ["name", "tenant_id", "role"],
    "Customer": ["tenant_id"],
    "Order": ["tenant_id", "store_id", "total_fen"],
    "Category": ["name", "tenant_id"],
    "Region": ["name"],
    "Equipment": ["name", "tenant_id", "equipment_type"],
    # Phase 3 — LightRAG 知识图谱扩展
    "Regulation": ["name", "tenant_id", "authority", "effective_date"],
    "Procedure": ["name", "tenant_id", "category"],
    "Allergen": ["name"],
    "Certification": ["name", "tenant_id", "issuing_body"],
    "Season": ["name", "start_month", "end_month"],
}

# ─── Relationship Properties ───

RELATIONSHIP_PROPERTIES: dict[str, list[str]] = {
    "USES_INGREDIENT": ["quantity_g", "unit"],
    "WORKS_AT": ["role", "since"],
    "CONTAINS": ["quantity", "price_fen"],
    "VISITED": ["date", "spend_fen"],
    "SIMILAR_TO": ["score"],
    "CAUSES": ["confidence", "evidence"],
    "RESULTED_IN": ["outcome_type", "measured_at"],
    # Phase 3 — LightRAG 知识图谱扩展
    "ALLERGEN_WARNING": ["severity"],
    "SEASONAL_AVAILABLE": ["peak_flag"],
    "SUBSTITUTABLE_BY": ["ratio", "note"],
    "REQUIRES_CERTIFICATION": ["valid_until"],
    "INSPECTION_COVERS": ["frequency"],
}

# ─── Uniqueness Constraints ───

UNIQUE_CONSTRAINTS: dict[str, str] = {
    "Store": "id",
    "Brand": "id",
    "Dish": "id",
    "Ingredient": "id",
    "Supplier": "id",
    "Employee": "id",
    "Customer": "id",
    "Order": "id",
    "Category": "id",
    "Region": "id",
    "Equipment": "id",
    # Phase 3 — LightRAG 知识图谱扩展
    "Regulation": "id",
    "Procedure": "id",
    "Allergen": "id",
    "Certification": "id",
    "Season": "id",
}

# ─── Index Definitions ───

INDEX_DEFINITIONS: list[dict[str, Any]] = [
    {"label": "Store", "properties": ["tenant_id"]},
    {"label": "Store", "properties": ["name"]},
    {"label": "Dish", "properties": ["tenant_id"]},
    {"label": "Dish", "properties": ["name"]},
    {"label": "Ingredient", "properties": ["tenant_id"]},
    {"label": "Ingredient", "properties": ["name"]},
    {"label": "Order", "properties": ["tenant_id", "store_id"]},
    {"label": "Customer", "properties": ["tenant_id"]},
    {"label": "Employee", "properties": ["tenant_id"]},
    # Phase 3 — LightRAG 知识图谱扩展
    {"label": "Regulation", "properties": ["tenant_id"]},
    {"label": "Regulation", "properties": ["name"]},
    {"label": "Procedure", "properties": ["tenant_id"]},
    {"label": "Allergen", "properties": ["name"]},
    {"label": "Certification", "properties": ["tenant_id"]},
    {"label": "Season", "properties": ["name"]},
]


def validate_node_properties(label: str, properties: dict[str, Any]) -> list[str]:
    """Validate that a node has all required properties.

    Returns list of missing property names (empty if valid).
    """
    required = NODE_REQUIRED_PROPERTIES.get(label, [])
    missing = [prop for prop in required if prop not in properties]
    return missing


def validate_relationship_type(rel_type: str) -> bool:
    """Check if relationship type is valid."""
    return rel_type in RELATIONSHIP_TYPES


def validate_node_label(label: str) -> bool:
    """Check if node label is valid."""
    return label in NODE_LABELS
