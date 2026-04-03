"""PG→Neo4j CDC Sync — 监听PG变更→同步到图数据库

V1模式：PG LISTEN/NOTIFY → Redis Stream → Neo4j Sync Worker
延迟目标：<5秒

In dev mode, simulates the sync pipeline in-memory.
In prod, connects to real PG notifications and Redis Streams.
"""

import uuid
from collections import deque
from datetime import datetime
from typing import Any, Optional

import structlog

from .models import SyncEvent, SyncStatus
from .repository import OntologyRepository

logger = structlog.get_logger()


class TableSyncConfig:
    """Configuration for syncing a PG table to a Neo4j node label."""

    def __init__(
        self,
        table_name: str,
        node_label: str,
        field_mapping: dict[str, str],
        id_field: str = "id",
        relationship_mappings: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.table_name = table_name
        self.node_label = node_label
        self.field_mapping = field_mapping
        self.id_field = id_field
        self.relationship_mappings = relationship_mappings or []


class PGToNeo4jSync:
    """PG→Neo4j CDC同步 — 监听PG变更→同步到图数据库

    Dev模式：直接调用process_change模拟CDC事件
    Prod模式：连接PG LISTEN/NOTIFY + Redis Stream
    """

    def __init__(self, repository: OntologyRepository, mode: str = "memory") -> None:
        self.repo = repository
        self.mode = mode
        self._table_configs: dict[str, TableSyncConfig] = {}
        self._event_queue: deque[SyncEvent] = deque()
        self._synced_events: list[SyncEvent] = []
        self._failed_events: list[SyncEvent] = []
        self._last_sync_at: Optional[datetime] = None
        self._started_at: datetime = datetime.now()
        logger.info("pg_neo4j_sync_init", mode=mode)

    def register_table_sync(
        self,
        table_name: str,
        node_label: str,
        field_mapping: dict[str, str],
        id_field: str = "id",
        relationship_mappings: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Register a PG table to sync to a Neo4j node label.

        Args:
            table_name: PG table name (e.g., "dishes")
            node_label: Neo4j node label (e.g., "Dish")
            field_mapping: {pg_column: neo4j_property} mapping
            id_field: PG column used as node ID
            relationship_mappings: List of relationship creation rules

        Returns:
            Dict with ok, table_name, node_label
        """
        config = TableSyncConfig(
            table_name=table_name,
            node_label=node_label,
            field_mapping=field_mapping,
            id_field=id_field,
            relationship_mappings=relationship_mappings,
        )
        self._table_configs[table_name] = config

        logger.info(
            "table_sync_registered",
            table=table_name,
            label=node_label,
            fields=list(field_mapping.keys()),
        )
        return {"ok": True, "table_name": table_name, "node_label": node_label}

    def process_change(
        self,
        table: str,
        operation: str,
        old_data: Optional[dict[str, Any]],
        new_data: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Process a single PG change event.

        Args:
            table: PG table name
            operation: INSERT, UPDATE, or DELETE
            old_data: Old row data (for UPDATE/DELETE)
            new_data: New row data (for INSERT/UPDATE)

        Returns:
            Dict with ok, event_id, operation, status
        """
        config = self._table_configs.get(table)
        if config is None:
            return {"ok": False, "error": f"Table {table} not registered for sync"}

        event = SyncEvent(
            table=table,
            operation=operation.upper(),
            node_label=config.node_label,
            old_data=old_data,
            new_data=new_data,
            status="pending",
        )

        try:
            result = self._apply_change(config, event)
            event.status = "synced"
            event.synced_at = datetime.now()
            self._synced_events.append(event)
            self._last_sync_at = event.synced_at

            logger.info(
                "change_synced",
                table=table,
                operation=operation,
                node_label=config.node_label,
            )
            return {
                "ok": True,
                "event_id": str(uuid.uuid4()),
                "operation": operation,
                "status": "synced",
                "result": result,
            }
        except (ValueError, KeyError, TypeError) as e:
            event.status = "failed"
            event.error = str(e)
            self._failed_events.append(event)
            logger.error("change_sync_failed", table=table, error=str(e))
            return {"ok": False, "error": str(e), "status": "failed"}

    def _apply_change(
        self, config: TableSyncConfig, event: SyncEvent
    ) -> dict[str, Any]:
        """Apply a change event to the graph repository."""
        if event.operation == "INSERT":
            return self._apply_insert(config, event)
        elif event.operation == "UPDATE":
            return self._apply_update(config, event)
        elif event.operation == "DELETE":
            return self._apply_delete(config, event)
        else:
            raise ValueError(f"Unknown operation: {event.operation}")

    def _apply_insert(
        self, config: TableSyncConfig, event: SyncEvent
    ) -> dict[str, Any]:
        """Apply INSERT: create a new node."""
        if event.new_data is None:
            raise ValueError("INSERT event requires new_data")

        properties = self._map_fields(config, event.new_data)
        node_id = str(event.new_data.get(config.id_field, uuid.uuid4()))
        properties["id"] = node_id

        result = self.repo.create_node(config.node_label, properties)

        # Process relationship mappings
        self._apply_relationship_mappings(config, node_id, event.new_data)

        return result

    def _apply_update(
        self, config: TableSyncConfig, event: SyncEvent
    ) -> dict[str, Any]:
        """Apply UPDATE: update node properties."""
        if event.new_data is None:
            raise ValueError("UPDATE event requires new_data")

        node_id = str(event.new_data.get(config.id_field, ""))
        if not node_id:
            raise ValueError("UPDATE event requires id in new_data")

        properties = self._map_fields(config, event.new_data)
        result = self.repo.update_node(config.node_label, node_id, properties)

        if not result["ok"]:
            # Node doesn't exist yet, create it
            properties["id"] = node_id
            result = self.repo.create_node(config.node_label, properties)
            self._apply_relationship_mappings(config, node_id, event.new_data)

        return result

    def _apply_delete(
        self, config: TableSyncConfig, event: SyncEvent
    ) -> dict[str, Any]:
        """Apply DELETE: remove node and its relationships."""
        data = event.old_data or event.new_data
        if data is None:
            raise ValueError("DELETE event requires old_data or new_data")

        node_id = str(data.get(config.id_field, ""))
        if not node_id:
            raise ValueError("DELETE event requires id")

        return self.repo.delete_node(config.node_label, node_id)

    def _map_fields(
        self, config: TableSyncConfig, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Map PG column names to Neo4j property names."""
        properties: dict[str, Any] = {}
        for pg_col, neo4j_prop in config.field_mapping.items():
            if pg_col in data:
                properties[neo4j_prop] = data[pg_col]
        return properties

    def _apply_relationship_mappings(
        self,
        config: TableSyncConfig,
        node_id: str,
        data: dict[str, Any],
    ) -> None:
        """Create relationships based on configured mappings."""
        for rel_map in config.relationship_mappings:
            foreign_key = rel_map.get("foreign_key", "")
            target_label = rel_map.get("target_label", "")
            rel_type = rel_map.get("rel_type", "")
            direction = rel_map.get("direction", "out")

            if not foreign_key or not target_label or not rel_type:
                continue

            target_id = data.get(foreign_key)
            if target_id is None:
                continue
            target_id = str(target_id)

            # Verify target node exists
            target_node = self.repo.get_node(target_label, target_id)
            if not target_node.get("ok"):
                continue

            rel_props = {}
            for prop_key in rel_map.get("properties", []):
                if prop_key in data:
                    rel_props[prop_key] = data[prop_key]

            try:
                if direction == "out":
                    self.repo.create_relationship(
                        config.node_label, node_id, rel_type,
                        target_label, target_id, rel_props,
                    )
                else:
                    self.repo.create_relationship(
                        target_label, target_id, rel_type,
                        config.node_label, node_id, rel_props,
                    )
            except ValueError as e:
                logger.warning("relationship_mapping_failed", error=str(e))

    def sync_batch(self, changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Process a batch of change events.

        Args:
            changes: List of {table, operation, old_data, new_data} dicts

        Returns:
            Dict with ok, total, synced, failed counts
        """
        synced = 0
        failed = 0

        for change in changes:
            result = self.process_change(
                table=change["table"],
                operation=change["operation"],
                old_data=change.get("old_data"),
                new_data=change.get("new_data"),
            )
            if result.get("ok"):
                synced += 1
            else:
                failed += 1

        return {
            "ok": True,
            "total": len(changes),
            "synced": synced,
            "failed": failed,
        }

    def get_sync_status(self) -> dict[str, Any]:
        """Get current sync status."""
        status = SyncStatus(
            total_synced=len(self._synced_events),
            total_pending=len(self._event_queue),
            total_failed=len(self._failed_events),
            last_sync_at=self._last_sync_at,
            lag_seconds=self._calculate_lag(),
            registered_tables=list(self._table_configs.keys()),
        )
        return status.model_dump()

    def get_sync_lag(self) -> dict[str, Any]:
        """Get current sync lag in seconds."""
        lag = self._calculate_lag()
        return {
            "ok": True,
            "lag_seconds": lag,
            "within_target": lag < 5.0,
            "target_seconds": 5.0,
        }

    def _calculate_lag(self) -> float:
        """Calculate current sync lag."""
        if self._last_sync_at is None:
            return 0.0
        delta = datetime.now() - self._last_sync_at
        return delta.total_seconds()

    def rebuild_full(self, table_name: str) -> dict[str, Any]:
        """Trigger a full re-sync for a table.

        In dev mode, this is a no-op since data is already in memory.
        In prod, this would read all rows from PG and sync to Neo4j.
        """
        config = self._table_configs.get(table_name)
        if config is None:
            return {"ok": False, "error": f"Table {table_name} not registered"}

        logger.info("rebuild_full_triggered", table=table_name, label=config.node_label)
        return {
            "ok": True,
            "table_name": table_name,
            "node_label": config.node_label,
            "status": "rebuild_complete" if self.mode == "memory" else "rebuild_started",
        }
