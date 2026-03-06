"""
Ontology layer (Palantir L2) — 本体层初始化
"""
import os

from .schema import NodeLabel, RelType  # no neo4j dependency

_repository = None


def get_ontology_repository():
    """返回 OntologyRepository 单例（懒初始化，首次调用时才连接 Neo4j）。

    依赖环境变量：
      NEO4J_URI      (默认 bolt://localhost:7687)
      NEO4J_USER     (默认 neo4j)
      NEO4J_PASSWORD (默认 neo4j)
    """
    global _repository
    if _repository is None:
        from .repository import OntologyRepository  # lazy import (requires neo4j pkg)
        _repository = OntologyRepository(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "neo4j"),
        )
    return _repository
