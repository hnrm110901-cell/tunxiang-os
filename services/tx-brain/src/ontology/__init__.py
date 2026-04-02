"""Neo4j Ontology Layer — 11节点 + 15关系 知识图谱

从V1迁入，在V3架构上重建。
开发模式使用内存模拟，生产环境连接真实Neo4j。
"""

from .bootstrap import OntologyBootstrap
from .data_sync import PGToNeo4jSync
from .models import (
    AggregateResult,
    NeighborResult,
    NodeModel,
    PathResult,
    RelationshipModel,
)
from .reasoning import CausalReasoningEngine
from .repository import OntologyRepository
from .schema import NODE_LABELS, RELATIONSHIP_TYPES

__all__ = [
    "NODE_LABELS",
    "RELATIONSHIP_TYPES",
    "NodeModel",
    "RelationshipModel",
    "PathResult",
    "NeighborResult",
    "AggregateResult",
    "OntologyRepository",
    "PGToNeo4jSync",
    "CausalReasoningEngine",
    "OntologyBootstrap",
]
