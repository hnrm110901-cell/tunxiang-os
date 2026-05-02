"""外卖订单 → KDS 调度桥接（Task P0-08）

当外卖平台订单通过 Adapter/Webhook 进入系统后，本模块负责：
  1. 将外卖订单拆分为 KDS 菜品任务（按档口分组）
  2. 推送 KDS 出餐屏（支持自动/手动接单模式）
  3. 跟踪出餐状态 → 回写平台（mark_ready）
  4. 外卖退款 → 取消 KDS 未制作任务

流程：
  美团/饿了么 Webhook → delivery_adapter.accept_order()
  → DeliveryKDSBridge.dispatch_to_kds(order)
  → 按 dish→dept 映射分发到各档口 KDS
  → 出餐完成后 callback adapter.mark_ready(order_id)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class DeliveryKDSBridge:
    """外卖 → KDS 桥接"""

    def __init__(self, db: AsyncSession, store_id: str, tenant_id: str):
        self._db = db
        self._store_id = uuid.UUID(store_id)
        self._tenant_id = uuid.UUID(tenant_id)

    async def dispatch_to_kds(self, delivery_order: Dict[str, Any]) -> Dict[str, Any]:
        """将外卖订单拆分为 KDS 任务并推送到对应档口。

        Args:
            delivery_order: 统一格式的外卖订单（由 adapter._map_order 产出）

        Returns:
            {kds_task_count, dept_breakdown, push_mode}
        """
        order_id = delivery_order.get("order_id", "")
        items = delivery_order.get("items", delivery_order.get("detail", []))
        platform = delivery_order.get("platform", "unknown")

        # 1. 查门店 push 模式
        push_mode = await self._get_push_mode()

        # 2. 按菜品 → 档口映射分发
        dept_tasks: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            dept_id = await self._resolve_dept(
                item.get("dish_id", ""),
                item.get("dish_name", item.get("food_name", "")),
            )
            if dept_id not in dept_tasks:
                dept_tasks[dept_id] = []
            dept_tasks[dept_id].append(item)

        # 3. 写入 KDS 任务
        now = datetime.now(timezone.utc)
        created_tasks = []
        for dept_id, dept_items in dept_tasks.items():
            task_id = uuid.uuid4()
            await self._db.execute(
                text("""
                    INSERT INTO kds_tasks
                        (id, store_id, tenant_id, order_id, dept_id,
                         platform, items, status, push_mode, created_at)
                    VALUES (:id, :sid, :tid, :oid, :dept, :platform,
                            :items::jsonb, 'pending', :mode, :now)
                """),
                {
                    "id": task_id,
                    "sid": self._store_id,
                    "tid": self._tenant_id,
                    "oid": order_id,
                    "dept": uuid.UUID(dept_id) if dept_id else None,
                    "platform": platform,
                    "items": json.dumps(dept_items, ensure_ascii=False),
                    "mode": push_mode,
                    "now": now,
                },
            )
            created_tasks.append({
                "task_id": str(task_id),
                "dept_id": dept_id,
                "item_count": len(dept_items),
            })

        await self._db.flush()

        logger.info(
            "delivery_kds_dispatched",
            order_id=order_id,
            platform=platform,
            depts=len(dept_tasks),
            tasks=len(created_tasks),
            push_mode=push_mode,
        )

        return {
            "order_id": order_id,
            "kds_task_count": len(created_tasks),
            "dept_breakdown": {
                dept: len(items) for dept, items in dept_tasks.items()
            },
            "push_mode": push_mode,
        }

    async def cancel_kds_tasks(self, order_id: str, reason: str = "订单取消") -> int:
        """外卖退款/取消时，取消未开始的 KDS 任务"""
        result = await self._db.execute(
            text("""
                UPDATE kds_tasks
                SET status = 'cancelled',
                    cancel_reason = :reason,
                    cancelled_at = NOW()
                WHERE order_id = :oid
                  AND store_id = :sid
                  AND tenant_id = :tid
                  AND status IN ('pending', 'cooking')
            """),
            {
                "oid": order_id,
                "sid": self._store_id,
                "tid": self._tenant_id,
                "reason": reason,
            },
        )
        await self._db.flush()
        count = result.rowcount
        if count > 0:
            logger.info(
                "delivery_kds_cancelled",
                order_id=order_id,
                tasks_cancelled=count,
                reason=reason,
            )
        return count

    async def mark_kds_ready(self, order_id: str) -> bool:
        """KDS 出餐完成后标记，返回是否全部完成（可通知骑手）"""
        result = await self._db.execute(
            text("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
                FROM kds_tasks
                WHERE order_id = :oid
                  AND store_id = :sid
                  AND tenant_id = :tid
            """),
            {"oid": order_id, "sid": self._store_id, "tid": self._tenant_id},
        )
        row = result.fetchone()
        if row and row.total > 0 and row.done == row.total:
            return True
        return False

    # ── 内部 ────────────────────────────────────────────────────────

    async def _get_push_mode(self) -> str:
        result = await self._db.execute(
            text("""
                SELECT push_mode FROM store_push_configs
                WHERE store_id = :sid AND tenant_id = :tid
            """),
            {"sid": self._store_id, "tid": self._tenant_id},
        )
        row = result.fetchone()
        return row.push_mode if row else "immediate"

    async def _resolve_dept(self, dish_id: str, dish_name: str) -> str:
        """根据菜品 ID 或名称匹配档口"""
        if dish_id:
            result = await self._db.execute(
                text("""
                    SELECT dept_id FROM dispatch_rules
                    WHERE (match_dish_id = :did OR match_dish_category IS NOT NULL)
                      AND store_id = :sid
                    ORDER BY priority ASC LIMIT 1
                """),
                {"did": dish_id, "sid": self._store_id},
            )
            row = result.fetchone()
            if row and row.dept_id:
                return str(row.dept_id)

        # fallback: 默认档口
        return "default"
