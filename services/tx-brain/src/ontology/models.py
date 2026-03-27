"""Pydantic models for Neo4j ontology nodes and relationships.

All graph entities are represented as Pydantic models for validation,
serialization, and API response formatting.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Base Models ───


class NodeModel(BaseModel):
    """Base model for all graph nodes."""

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def get_prop(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


class RelationshipModel(BaseModel):
    """Model for graph relationships."""

    id: str
    rel_type: str
    from_node_id: str
    from_label: str
    to_node_id: str
    to_label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


# ─── Query Result Models ───


class PathResult(BaseModel):
    """Result of a path query between two nodes."""

    start_node: NodeModel
    end_node: NodeModel
    path_nodes: list[NodeModel] = Field(default_factory=list)
    path_relationships: list[RelationshipModel] = Field(default_factory=list)
    total_depth: int = 0
    found: bool = False


class NeighborResult(BaseModel):
    """Result of a neighborhood query."""

    center_node: NodeModel
    neighbors: list[NodeModel] = Field(default_factory=list)
    relationships: list[RelationshipModel] = Field(default_factory=list)
    depth: int = 1
    total_count: int = 0


class AggregateResult(BaseModel):
    """Result of an aggregation query."""

    label: str
    group_by: str
    metric: str
    agg_func: str
    results: list[dict[str, Any]] = Field(default_factory=list)


# ─── Domain-Specific Models ───


class BOMEntry(BaseModel):
    """Bill of Materials entry: Dish→Ingredient with quantity."""

    ingredient_id: str
    ingredient_name: str
    quantity_g: float
    unit: str = "g"
    unit_price_fen: int = 0
    cost_fen: int = 0
    yield_rate: float = 1.0  # 1.0 = no loss, 0.7 = 30% loss


class DishCostBreakdown(BaseModel):
    """Full cost breakdown for a dish."""

    dish_id: str
    dish_name: str
    selling_price_fen: int
    bom_entries: list[BOMEntry] = Field(default_factory=list)
    total_material_cost_fen: int = 0
    processing_cost_fen: int = 0
    total_cost_fen: int = 0
    margin_rate: float = 0.0
    calculated_at: datetime = Field(default_factory=datetime.now)


class CausalLink(BaseModel):
    """A single link in a causal chain."""

    cause: str
    effect: str
    evidence: str
    confidence: float = 0.0
    depth: int = 0
    data_source: str = ""


class CausalChain(BaseModel):
    """Full causal chain from root cause to observed effect."""

    observed_effect: str
    root_cause: str
    chain: list[CausalLink] = Field(default_factory=list)
    total_confidence: float = 0.0
    analysis_time_ms: int = 0


class SyncEvent(BaseModel):
    """A PG→Neo4j sync event."""

    table: str
    operation: str  # INSERT, UPDATE, DELETE
    node_label: str
    old_data: Optional[dict[str, Any]] = None
    new_data: Optional[dict[str, Any]] = None
    synced_at: Optional[datetime] = None
    status: str = "pending"  # pending, synced, failed
    error: Optional[str] = None


class SyncStatus(BaseModel):
    """Overall sync status."""

    total_synced: int = 0
    total_pending: int = 0
    total_failed: int = 0
    last_sync_at: Optional[datetime] = None
    lag_seconds: float = 0.0
    registered_tables: list[str] = Field(default_factory=list)
