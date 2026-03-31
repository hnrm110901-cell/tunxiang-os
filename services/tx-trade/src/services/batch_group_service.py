"""批次累单服务 — 切配/打荷档口专用

将同一档口下多桌相同菜品合并为批次视图，方便厨师按批次操作。
核心场景：烤鸭×8份，base_quantity=2 → 显示"4批×2只"，余0只

数据流：
  kds_tasks (pending) + order_items + orders
  → 按 dish_id 分组
  → 计算 batch_count = total_qty // base_qty
  → 返回 BatchGroup 列表
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

import structlog
from sqlalchemy import select, update, and_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem
from ..models.kds_task import KDSTask
from ..models.production_dept import DishDeptMapping

logger = structlog.get_logger()


@dataclass
class BatchGroup:
    """单个菜品的批次合并结果"""
    dish_id: str
    dish_name: str
    total_qty: int          # 档口所有pending任务的总份数
    base_qty: int           # 基准批次份数（从 dish_dept_mappings.base_quantity 读取）
    batch_count: int        # 可凑成的完整批次数 = total_qty // base_qty
    remainder: int          # 剩余散单数 = total_qty % base_qty
    table_list: List[str] = field(default_factory=list)   # 涉及桌台列表
    task_ids: List[str] = field(default_factory=list)     # 涉及的 KDS task ID 列表


class BatchGroupService:
    """批次累单服务

    切配（prep）和打荷（assemble）岗位专用：
    - 查询档口 pending 工单，按 dish_id 合并
    - 基准批次份数支持每个档口独立配置
    """

    # ── 基准份数查询 ──────────────────────────────────────────

    @staticmethod
    async def get_dish_base_quantity(
        dish_id: str,
        dept_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> int:
        """读取菜品在指定档口的基准批次份数（默认1）

        从 dish_dept_mappings.base_quantity 读取，若无记录则返回1。
        SQL schema: ALTER TABLE dish_dept_mappings ADD COLUMN IF NOT EXISTS base_quantity INT NOT NULL DEFAULT 1;
        """
        try:
            result = await db.execute(
                text(
                    "SELECT base_quantity FROM dish_dept_mappings "
                    "WHERE dish_id = :dish_id "
                    "  AND production_dept_id = :dept_id "
                    "  AND tenant_id = :tenant_id "
                    "  AND is_deleted = false "
                    "LIMIT 1"
                ),
                {
                    "dish_id": dish_id,
                    "dept_id": dept_id,
                    "tenant_id": tenant_id,
                },
            )
            row = result.fetchone()
            if row is None:
                return 1
            base_qty = row[0]
            return base_qty if base_qty and base_qty > 0 else 1
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.warning(
                "batch_group.get_base_qty_failed",
                dish_id=dish_id,
                dept_id=dept_id,
                error=str(exc),
            )
            return 1

    @staticmethod
    async def set_base_quantity(
        dish_id: str,
        dept_id: str,
        quantity: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """设置菜品在指定档口的基准批次份数

        若 dish_dept_mappings 记录已存在则更新，否则插入（upsert）。
        quantity 必须 >= 1。
        """
        if quantity < 1:
            raise ValueError(f"base_quantity must be >= 1, got {quantity}")

        try:
            # 先尝试更新
            result = await db.execute(
                text(
                    "UPDATE dish_dept_mappings "
                    "SET base_quantity = :quantity, updated_at = NOW() "
                    "WHERE dish_id = :dish_id "
                    "  AND production_dept_id = :dept_id "
                    "  AND tenant_id = :tenant_id "
                    "  AND is_deleted = false"
                ),
                {
                    "quantity": quantity,
                    "dish_id": dish_id,
                    "dept_id": dept_id,
                    "tenant_id": tenant_id,
                },
            )
            if result.rowcount == 0:
                # 无映射记录，插入（含默认值）
                await db.execute(
                    text(
                        "INSERT INTO dish_dept_mappings "
                        "(id, tenant_id, dish_id, production_dept_id, base_quantity, sort_order, is_deleted, created_at, updated_at) "
                        "VALUES (:id, :tenant_id, :dish_id, :dept_id, :quantity, 0, false, NOW(), NOW()) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "dish_id": dish_id,
                        "dept_id": dept_id,
                        "quantity": quantity,
                    },
                )
            await db.commit()
            logger.info(
                "batch_group.set_base_quantity",
                dish_id=dish_id,
                dept_id=dept_id,
                quantity=quantity,
            )
        except ValueError:
            raise
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            await db.rollback()
            logger.error(
                "batch_group.set_base_quantity_failed",
                dish_id=dish_id,
                dept_id=dept_id,
                quantity=quantity,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to set base_quantity: {exc}") from exc

    # ── 累单队列查询 ──────────────────────────────────────────

    @staticmethod
    async def get_batched_queue(
        dept_id: str,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> List[BatchGroup]:
        """查询档口当前 pending 工单，按菜品合并为批次视图

        返回 BatchGroup 列表，每组包含：
        - 菜名、总份数、基准批次数、可凑批次数、余量
        - 涉及的桌台列表（去重排序）
        - 涉及的 KDS task ID 列表
        """
        try:
            # 查询档口所有 pending 任务，关联 order_items 获取菜名/份数/桌台
            rows = await db.execute(
                text(
                    """
                    SELECT
                        kt.id            AS task_id,
                        kt.order_item_id,
                        oi.dish_id,
                        oi.item_name     AS dish_name,
                        oi.quantity,
                        o.table_number   AS table_no
                    FROM kds_tasks kt
                    JOIN order_items oi ON oi.id = kt.order_item_id
                    JOIN orders o       ON o.id  = oi.order_id
                    WHERE kt.tenant_id = :tenant_id
                      AND kt.dept_id   = :dept_id
                      AND kt.status    = 'pending'
                      AND kt.is_deleted = false
                      AND oi.is_deleted = false
                      AND o.store_id   = :store_id
                    ORDER BY kt.created_at ASC
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "dept_id": dept_id,
                    "store_id": store_id,
                },
            )
            task_rows = rows.fetchall()
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.error(
                "batch_group.get_batched_queue_failed",
                dept_id=dept_id,
                store_id=store_id,
                error=str(exc),
            )
            raise RuntimeError(f"Failed to query batched queue: {exc}") from exc

        if not task_rows:
            return []

        # 按 dish_id 分组，累计份数/桌台/task_id
        groups: dict[str, dict] = {}
        for row in task_rows:
            dish_id = str(row.dish_id) if row.dish_id else f"item_{row.order_item_id}"
            if dish_id not in groups:
                groups[dish_id] = {
                    "dish_id": dish_id,
                    "dish_name": row.dish_name,
                    "total_qty": 0,
                    "tables": set(),
                    "task_ids": [],
                }
            g = groups[dish_id]
            g["total_qty"] += row.quantity
            if row.table_no:
                g["tables"].add(row.table_no)
            g["task_ids"].append(str(row.task_id))

        # 批量获取各菜品基准份数（并发查询）
        result_groups: List[BatchGroup] = []
        for dish_id, g in groups.items():
            base_qty = await BatchGroupService.get_dish_base_quantity(
                dish_id, dept_id, tenant_id, db
            )
            total_qty = g["total_qty"]
            batch_count = total_qty // base_qty
            remainder = total_qty % base_qty
            result_groups.append(
                BatchGroup(
                    dish_id=dish_id,
                    dish_name=g["dish_name"],
                    total_qty=total_qty,
                    base_qty=base_qty,
                    batch_count=batch_count,
                    remainder=remainder,
                    table_list=sorted(g["tables"]),
                    task_ids=g["task_ids"],
                )
            )

        # 按总份数降序，方便厨师优先处理大批次
        result_groups.sort(key=lambda x: x.total_qty, reverse=True)
        logger.info(
            "batch_group.get_batched_queue",
            dept_id=dept_id,
            store_id=store_id,
            dish_count=len(result_groups),
        )
        return result_groups
