"""Neo4j CRUD Operations — In-memory simulation for dev, real Neo4j for prod.

OntologyRepository provides a complete graph database interface.
In development mode, all data is stored in-memory dicts simulating
Neo4j's node/relationship storage with full query capability.
"""

import statistics
import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Optional

import structlog

from .models import (
    NeighborResult,
    NodeModel,
    RelationshipModel,
)
from .schema import (
    validate_node_label,
    validate_node_properties,
    validate_relationship_type,
)

logger = structlog.get_logger()


class OntologyRepository:
    """Neo4j CRUD operations — in-memory simulation for dev, real Neo4j for prod.

    Internal storage:
      _nodes: {node_id: NodeModel}
      _relationships: {rel_id: RelationshipModel}
      _adjacency_out: {node_id: [rel_id, ...]}  outgoing edges
      _adjacency_in:  {node_id: [rel_id, ...]}  incoming edges
      _label_index:   {label: {node_id, ...}}    label→node lookup
    """

    def __init__(self, mode: str = "memory") -> None:
        self.mode = mode
        self._nodes: dict[str, NodeModel] = {}
        self._relationships: dict[str, RelationshipModel] = {}
        self._adjacency_out: dict[str, list[str]] = defaultdict(list)
        self._adjacency_in: dict[str, list[str]] = defaultdict(list)
        self._label_index: dict[str, set[str]] = defaultdict(set)
        logger.info("ontology_repository_init", mode=mode)

    # ─── Node CRUD ───

    def create_node(self, label: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Create a new node with the given label and properties.

        Args:
            label: Node label (must be in NODE_LABELS)
            properties: Node properties dict

        Returns:
            Dict with ok, node_id, node keys

        Raises:
            ValueError: If label is invalid or required properties missing
        """
        if not validate_node_label(label):
            raise ValueError(f"Invalid node label: {label}. Must be one of NODE_LABELS.")

        missing = validate_node_properties(label, properties)
        if missing:
            raise ValueError(f"Missing required properties for {label}: {missing}")

        node_id = properties.get("id", str(uuid.uuid4()))
        now = datetime.now()

        node = NodeModel(
            id=node_id,
            label=label,
            properties=properties,
            created_at=now,
            updated_at=now,
        )

        self._nodes[node_id] = node
        self._label_index[label].add(node_id)

        logger.info("node_created", label=label, node_id=node_id)
        return {"ok": True, "node_id": node_id, "node": node.model_dump()}

    def get_node(self, label: str, node_id: str) -> dict[str, Any]:
        """Get a node by label and ID.

        Returns:
            Dict with ok, node keys. ok=False if not found.
        """
        node = self._nodes.get(node_id)
        if node is None or node.label != label:
            return {"ok": False, "error": f"{label} node {node_id} not found"}
        return {"ok": True, "node": node.model_dump()}

    def update_node(
        self, label: str, node_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        """Update a node's properties (merge, not replace).

        Returns:
            Dict with ok, node keys.
        """
        node = self._nodes.get(node_id)
        if node is None or node.label != label:
            return {"ok": False, "error": f"{label} node {node_id} not found"}

        node.properties.update(properties)
        node.updated_at = datetime.now()

        logger.info("node_updated", label=label, node_id=node_id)
        return {"ok": True, "node": node.model_dump()}

    def delete_node(self, label: str, node_id: str) -> dict[str, Any]:
        """Delete a node and all its relationships.

        Returns:
            Dict with ok, deleted_relationships count.
        """
        node = self._nodes.get(node_id)
        if node is None or node.label != label:
            return {"ok": False, "error": f"{label} node {node_id} not found"}

        # Remove all relationships
        deleted_rels = 0
        for rel_id in list(self._adjacency_out.get(node_id, [])):
            self._remove_relationship(rel_id)
            deleted_rels += 1
        for rel_id in list(self._adjacency_in.get(node_id, [])):
            self._remove_relationship(rel_id)
            deleted_rels += 1

        # Remove node
        del self._nodes[node_id]
        self._label_index[label].discard(node_id)
        self._adjacency_out.pop(node_id, None)
        self._adjacency_in.pop(node_id, None)

        logger.info("node_deleted", label=label, node_id=node_id, deleted_rels=deleted_rels)
        return {"ok": True, "deleted_relationships": deleted_rels}

    # ─── Relationship CRUD ───

    def create_relationship(
        self,
        from_label: str,
        from_id: str,
        rel_type: str,
        to_label: str,
        to_id: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a relationship between two existing nodes.

        Args:
            from_label: Source node label
            from_id: Source node ID
            rel_type: Relationship type (must be in RELATIONSHIP_TYPES)
            to_label: Target node label
            to_id: Target node ID
            properties: Optional relationship properties

        Returns:
            Dict with ok, rel_id, relationship keys

        Raises:
            ValueError: If rel_type is invalid or nodes don't exist
        """
        if not validate_relationship_type(rel_type):
            raise ValueError(f"Invalid relationship type: {rel_type}")

        from_node = self._nodes.get(from_id)
        if from_node is None or from_node.label != from_label:
            raise ValueError(f"Source node {from_label}:{from_id} not found")

        to_node = self._nodes.get(to_id)
        if to_node is None or to_node.label != to_label:
            raise ValueError(f"Target node {to_label}:{to_id} not found")

        rel_id = str(uuid.uuid4())
        rel = RelationshipModel(
            id=rel_id,
            rel_type=rel_type,
            from_node_id=from_id,
            from_label=from_label,
            to_node_id=to_id,
            to_label=to_label,
            properties=properties or {},
            created_at=datetime.now(),
        )

        self._relationships[rel_id] = rel
        self._adjacency_out[from_id].append(rel_id)
        self._adjacency_in[to_id].append(rel_id)

        logger.info(
            "relationship_created",
            rel_type=rel_type,
            from_node=f"{from_label}:{from_id}",
            to_node=f"{to_label}:{to_id}",
        )
        return {"ok": True, "rel_id": rel_id, "relationship": rel.model_dump()}

    def get_relationships(
        self,
        label: str,
        node_id: str,
        rel_type: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Get all relationships for a node, optionally filtered by type and direction.

        Args:
            label: Node label
            node_id: Node ID
            rel_type: Optional filter by relationship type
            direction: "out", "in", or "both"

        Returns:
            List of relationship dicts
        """
        node = self._nodes.get(node_id)
        if node is None or node.label != label:
            return []

        rel_ids: list[str] = []
        if direction in ("out", "both"):
            rel_ids.extend(self._adjacency_out.get(node_id, []))
        if direction in ("in", "both"):
            rel_ids.extend(self._adjacency_in.get(node_id, []))

        results = []
        seen = set()
        for rid in rel_ids:
            if rid in seen:
                continue
            seen.add(rid)
            rel = self._relationships.get(rid)
            if rel is None:
                continue
            if rel_type and rel.rel_type != rel_type:
                continue
            results.append(rel.model_dump())

        return results

    def delete_relationship(self, rel_id: str) -> dict[str, Any]:
        """Delete a relationship by ID."""
        rel = self._relationships.get(rel_id)
        if rel is None:
            return {"ok": False, "error": f"Relationship {rel_id} not found"}

        self._remove_relationship(rel_id)
        logger.info("relationship_deleted", rel_id=rel_id)
        return {"ok": True}

    def _remove_relationship(self, rel_id: str) -> None:
        """Internal: remove a relationship from all indexes."""
        rel = self._relationships.pop(rel_id, None)
        if rel is None:
            return
        out_list = self._adjacency_out.get(rel.from_node_id, [])
        if rel_id in out_list:
            out_list.remove(rel_id)
        in_list = self._adjacency_in.get(rel.to_node_id, [])
        if rel_id in in_list:
            in_list.remove(rel_id)

    # ─── Graph Queries ───

    def query_path(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        max_depth: int = 5,
    ) -> list[dict[str, Any]]:
        """Find shortest path between two nodes using BFS.

        Returns:
            List of dicts representing path steps, each with
            {node, relationship, depth}. Empty list if no path found.
        """
        start_node = self._nodes.get(start_id)
        end_node = self._nodes.get(end_id)

        if start_node is None or start_node.label != start_label:
            return []
        if end_node is None or end_node.label != end_label:
            return []
        if start_id == end_id:
            return [{"node": start_node.model_dump(), "relationship": None, "depth": 0}]

        # BFS
        visited: set[str] = {start_id}
        # Queue entries: (current_node_id, path_so_far)
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque()
        queue.append((start_id, [{"node": start_node.model_dump(), "relationship": None, "depth": 0}]))

        while queue:
            current_id, path = queue.popleft()
            current_depth = len(path) - 1

            if current_depth >= max_depth:
                continue

            # Explore all outgoing and incoming relationships
            neighbor_rels: list[str] = []
            neighbor_rels.extend(self._adjacency_out.get(current_id, []))
            neighbor_rels.extend(self._adjacency_in.get(current_id, []))

            for rel_id in neighbor_rels:
                rel = self._relationships.get(rel_id)
                if rel is None:
                    continue

                next_id = rel.to_node_id if rel.from_node_id == current_id else rel.from_node_id
                if next_id in visited:
                    continue

                visited.add(next_id)
                next_node = self._nodes.get(next_id)
                if next_node is None:
                    continue

                new_path = path + [
                    {
                        "node": next_node.model_dump(),
                        "relationship": rel.model_dump(),
                        "depth": current_depth + 1,
                    }
                ]

                if next_id == end_id:
                    return new_path

                queue.append((next_id, new_path))

        return []

    def query_neighbors(
        self, label: str, node_id: str, depth: int = 1
    ) -> dict[str, Any]:
        """Get all neighbors within N hops.

        Returns:
            NeighborResult as dict with center_node, neighbors, relationships.
        """
        center = self._nodes.get(node_id)
        if center is None or center.label != label:
            return NeighborResult(
                center_node=NodeModel(id="", label="", properties={}),
                depth=depth,
            ).model_dump()

        visited: set[str] = {node_id}
        neighbors: list[NodeModel] = []
        relationships: list[RelationshipModel] = []
        current_frontier: set[str] = {node_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in current_frontier:
                all_rels = self._adjacency_out.get(nid, []) + self._adjacency_in.get(nid, [])
                for rel_id in all_rels:
                    rel = self._relationships.get(rel_id)
                    if rel is None:
                        continue

                    other_id = rel.to_node_id if rel.from_node_id == nid else rel.from_node_id
                    if other_id in visited:
                        continue

                    visited.add(other_id)
                    other_node = self._nodes.get(other_id)
                    if other_node is not None:
                        neighbors.append(other_node)
                        relationships.append(rel)
                        next_frontier.add(other_id)

            current_frontier = next_frontier

        result = NeighborResult(
            center_node=center,
            neighbors=neighbors,
            relationships=relationships,
            depth=depth,
            total_count=len(neighbors),
        )
        return result.model_dump()

    # ─── Cypher-like Queries ───

    def find_nodes(
        self, label: str, filters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Find nodes by label and optional property filters.

        Args:
            label: Node label to search
            filters: Dict of property_name→value to match.
                     Supports exact match only.

        Returns:
            List of matching node dicts.
        """
        node_ids = self._label_index.get(label, set())
        results = []

        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is None:
                continue

            if filters:
                match = True
                for key, value in filters.items():
                    node_val = node.properties.get(key)
                    if node_val != value:
                        match = False
                        break
                if not match:
                    continue

            results.append(node.model_dump())

        return results

    def aggregate(
        self,
        label: str,
        group_by: str,
        metric: str,
        agg_func: str = "avg",
    ) -> list[dict[str, Any]]:
        """Aggregate node properties by group.

        Args:
            label: Node label
            group_by: Property name to group by
            metric: Property name to aggregate
            agg_func: One of "avg", "sum", "min", "max", "count"

        Returns:
            List of {group, value} dicts.
        """
        node_ids = self._label_index.get(label, set())
        groups: dict[Any, list[float]] = defaultdict(list)

        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is None:
                continue
            group_val = node.properties.get(group_by)
            metric_val = node.properties.get(metric)
            if group_val is not None and metric_val is not None:
                try:
                    groups[group_val].append(float(metric_val))
                except (TypeError, ValueError):
                    continue

        results = []
        for group_val, values in sorted(groups.items(), key=lambda x: str(x[0])):
            if agg_func == "avg":
                agg_value = statistics.mean(values) if values else 0.0
            elif agg_func == "sum":
                agg_value = sum(values)
            elif agg_func == "min":
                agg_value = min(values) if values else 0.0
            elif agg_func == "max":
                agg_value = max(values) if values else 0.0
            elif agg_func == "count":
                agg_value = float(len(values))
            else:
                agg_value = statistics.mean(values) if values else 0.0

            results.append({"group": group_val, "value": agg_value})

        return results

    # ─── Utility ───

    def node_count(self, label: Optional[str] = None) -> int:
        """Count nodes, optionally by label."""
        if label:
            return len(self._label_index.get(label, set()))
        return len(self._nodes)

    def relationship_count(self, rel_type: Optional[str] = None) -> int:
        """Count relationships, optionally by type."""
        if rel_type:
            return sum(
                1 for r in self._relationships.values() if r.rel_type == rel_type
            )
        return len(self._relationships)

    def clear(self) -> None:
        """Clear all data. Use for testing."""
        self._nodes.clear()
        self._relationships.clear()
        self._adjacency_out.clear()
        self._adjacency_in.clear()
        self._label_index.clear()
        logger.info("ontology_repository_cleared")

    def get_all_nodes_by_label(self, label: str) -> list[NodeModel]:
        """Get all NodeModel instances for a label."""
        node_ids = self._label_index.get(label, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_node_model(self, node_id: str) -> Optional[NodeModel]:
        """Get raw NodeModel by ID (any label)."""
        return self._nodes.get(node_id)
