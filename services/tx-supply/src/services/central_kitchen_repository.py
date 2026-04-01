"""中央厨房 Repository — 内存 → DB 迁移（接 v062 表）

5 张 v062 表的完整 CRUD：
  central_kitchen_profiles      ← _kitchens
  production_plans              ← _plans
  production_orders             ← _production_orders
  distribution_orders           ← _distribution_orders
  store_receiving_confirmations ← _receiving_confirmations

需求预测（forecast_demand）从已完成的 production_orders 计算近 30 天日均量。
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

_WEEKEND_WEIGHT = 1.3
_WEEKEND_DAYS = {5, 6}


class CentralKitchenRepository:
    """中央厨房数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 厨房档案
    # ══════════════════════════════════════════════════════

    async def create_kitchen(
        self,
        name: str,
        address: Optional[str],
        capacity_daily: float,
        manager_id: Optional[str],
        contact_phone: Optional[str],
    ) -> Dict[str, Any]:
        await self._set_tenant()
        kid = uuid.uuid4()
        result = await self.db.execute(
            text("""
                INSERT INTO central_kitchen_profiles
                    (id, tenant_id, name, address, capacity_daily,
                     manager_id, contact_phone, is_active, created_at)
                VALUES
                    (:id, :tid, :name, :address, :capacity,
                     :mgr, :phone, true, NOW())
                RETURNING id, name, address, capacity_daily,
                          manager_id, contact_phone, is_active, created_at
            """),
            {
                "id": kid,
                "tid": self._tid,
                "name": name.strip(),
                "address": address,
                "capacity": capacity_daily,
                "mgr": uuid.UUID(manager_id) if manager_id else None,
                "phone": contact_phone,
            },
        )
        row = result.fetchone()
        await self.db.flush()
        log.info("kitchen_created", kitchen_id=str(kid), name=name, tenant_id=self.tenant_id)
        return self._kitchen_row(row)

    async def list_kitchens(self) -> List[Dict[str, Any]]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, name, address, capacity_daily, manager_id,
                       contact_phone, is_active, created_at
                FROM central_kitchen_profiles
                WHERE tenant_id = :tid AND is_active = true
                ORDER BY created_at DESC
            """),
            {"tid": self._tid},
        )
        return [self._kitchen_row(r) for r in result.fetchall()]

    async def get_kitchen(self, kitchen_id: str) -> Optional[Dict[str, Any]]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, name, address, capacity_daily, manager_id,
                       contact_phone, is_active, created_at
                FROM central_kitchen_profiles
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(kitchen_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._kitchen_row(row) if row else None

    # ══════════════════════════════════════════════════════
    # 生产计划
    # ══════════════════════════════════════════════════════

    async def create_plan(
        self,
        kitchen_id: str,
        plan_date: str,
        items: List[Dict[str, Any]],
        created_by: Optional[str],
    ) -> Dict[str, Any]:
        await self._set_tenant()
        plan_id = uuid.uuid4()
        result = await self.db.execute(
            text("""
                INSERT INTO production_plans
                    (id, tenant_id, kitchen_id, plan_date, status, items, created_by, created_at)
                VALUES
                    (:id, :tid, :kid, :plan_date::date, 'draft', :items::jsonb, :created_by, NOW())
                RETURNING id, kitchen_id, plan_date, status, items,
                          created_by, confirmed_at, created_at
            """),
            {
                "id": plan_id,
                "tid": self._tid,
                "kid": uuid.UUID(kitchen_id),
                "plan_date": plan_date,
                "items": json.dumps(items),
                "created_by": uuid.UUID(created_by) if created_by else None,
            },
        )
        row = result.fetchone()
        await self.db.flush()
        log.info("production_plan_created", plan_id=str(plan_id),
                 kitchen_id=kitchen_id, plan_date=plan_date, tenant_id=self.tenant_id)
        return self._plan_row(row, str(plan_id))

    async def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, kitchen_id, plan_date, status, items,
                       created_by, confirmed_at, created_at
                FROM production_plans
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._plan_row(row, plan_id) if row else None

    async def list_plans(
        self,
        kitchen_id: Optional[str],
        plan_date: Optional[str],
        status: Optional[str],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tid}
        if kitchen_id:
            where += " AND kitchen_id = :kid"
            params["kid"] = uuid.UUID(kitchen_id)
        if plan_date:
            where += " AND plan_date = :plan_date::date"
            params["plan_date"] = plan_date
        if status:
            where += " AND status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM production_plans {where}"), params
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT id, kitchen_id, plan_date, status, items,
                       created_by, confirmed_at, created_at
                FROM production_plans {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._plan_row(r, str(r.id)) for r in result.fetchall()]
        return {"items": items, "total": total}

    async def confirm_plan(self, plan_id: str, operator_id: str) -> Dict[str, Any]:
        """确认计划并批量生成生产工单"""
        await self._set_tenant()
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["status"] != "draft":
            raise ValueError(f"计划状态为 {plan['status']}，只有 draft 状态可确认")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE production_plans
                SET status = 'confirmed', confirmed_at = :now
                WHERE id = :id AND tenant_id = :tid
            """),
            {"now": now, "id": uuid.UUID(plan_id), "tid": self._tid},
        )

        kitchen_id = plan["kitchen_id"]
        op_uuid = uuid.UUID(operator_id) if operator_id else None
        for item in plan.get("items", []):
            await self.db.execute(
                text("""
                    INSERT INTO production_orders
                        (id, tenant_id, kitchen_id, plan_id, dish_id,
                         quantity, unit, status, operator_id, created_at)
                    VALUES
                        (:id, :tid, :kid, :pid, :dish_id,
                         :qty, :unit, 'pending', :op, NOW())
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": self._tid,
                    "kid": uuid.UUID(kitchen_id),
                    "pid": uuid.UUID(plan_id),
                    "dish_id": uuid.UUID(item["dish_id"]),
                    "qty": float(item["quantity"]),
                    "unit": item.get("unit", "份"),
                    "op": op_uuid,
                },
            )

        await self.db.flush()
        log.info("production_plan_confirmed", plan_id=plan_id,
                 order_count=len(plan.get("items", [])), tenant_id=self.tenant_id)
        return await self.get_plan(plan_id)  # type: ignore[return-value]

    async def start_production(self, plan_id: str) -> Dict[str, Any]:
        """confirmed → in_progress，所有 pending 工单批量启动"""
        await self._set_tenant()
        plan = await self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"生产计划 {plan_id} 不存在")
        if plan["status"] != "confirmed":
            raise ValueError(f"计划状态为 {plan['status']}，只有 confirmed 状态可开始生产")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("UPDATE production_plans SET status='in_progress' WHERE id=:id AND tenant_id=:tid"),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        result = await self.db.execute(
            text("""
                UPDATE production_orders
                SET status='in_progress', started_at=:now
                WHERE plan_id=:pid AND tenant_id=:tid AND status='pending'
            """),
            {"now": now, "pid": uuid.UUID(plan_id), "tid": self._tid},
        )
        await self.db.flush()
        log.info("production_started", plan_id=plan_id,
                 orders_started=result.rowcount, tenant_id=self.tenant_id)
        return await self.get_plan(plan_id)  # type: ignore[return-value]

    # ══════════════════════════════════════════════════════
    # 生产工单
    # ══════════════════════════════════════════════════════

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, kitchen_id, plan_id, dish_id, quantity, unit,
                       status, started_at, completed_at, operator_id, created_at
                FROM production_orders
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(order_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._order_row(row, order_id) if row else None

    async def complete_order(self, order_id: str, actual_qty: float) -> Dict[str, Any]:
        await self._set_tenant()
        order = await self.get_order(order_id)
        if not order:
            raise ValueError(f"生产工单 {order_id} 不存在")
        if order["status"] in ("completed", "cancelled"):
            raise ValueError(f"工单 {order_id} 已处于 {order['status']} 状态")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                UPDATE production_orders
                SET status='completed', completed_at=:now,
                    quantity=:qty,
                    started_at=COALESCE(started_at, :now)
                WHERE id=:id AND tenant_id=:tid
            """),
            {"now": now, "qty": actual_qty, "id": uuid.UUID(order_id), "tid": self._tid},
        )
        await self._auto_complete_plan(order["plan_id"])
        await self.db.flush()
        log.info("production_order_completed", order_id=order_id,
                 actual_qty=actual_qty, tenant_id=self.tenant_id)
        return await self.get_order(order_id)  # type: ignore[return-value]

    async def update_order_progress(
        self, order_id: str, status: str, quantity_done: Optional[float]
    ) -> Dict[str, Any]:
        await self._set_tenant()
        order = await self.get_order(order_id)
        if not order:
            raise ValueError(f"生产工单 {order_id} 不存在")
        if order["status"] in ("completed", "cancelled"):
            raise ValueError(f"工单 {order_id} 已处于 {order['status']} 状态")

        now = datetime.now(timezone.utc)
        started_at_clause = "started_at = CASE WHEN status='pending' THEN :now ELSE started_at END,"
        completed_at_clause = "completed_at = CASE WHEN :status='completed' THEN :now ELSE completed_at END,"
        qty_clause = "quantity = CASE WHEN :status='completed' THEN :qty ELSE quantity END,"

        await self.db.execute(
            text(f"""
                UPDATE production_orders
                SET {started_at_clause}
                    {completed_at_clause}
                    {qty_clause}
                    status = :status
                WHERE id=:id AND tenant_id=:tid
            """),
            {
                "now": now,
                "status": status,
                "qty": quantity_done,
                "id": uuid.UUID(order_id),
                "tid": self._tid,
            },
        )
        if status == "completed":
            await self._auto_complete_plan(order["plan_id"])
        await self.db.flush()
        return await self.get_order(order_id)  # type: ignore[return-value]

    async def list_orders(
        self,
        kitchen_id: Optional[str],
        plan_id: Optional[str],
        status: Optional[str],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tid}
        if kitchen_id:
            where += " AND kitchen_id = :kid"
            params["kid"] = uuid.UUID(kitchen_id)
        if plan_id:
            where += " AND plan_id = :pid"
            params["pid"] = uuid.UUID(plan_id)
        if status:
            where += " AND status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM production_orders {where}"), params
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT id, kitchen_id, plan_id, dish_id, quantity, unit,
                       status, started_at, completed_at, operator_id, created_at
                FROM production_orders {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._order_row(r, str(r.id)) for r in result.fetchall()]
        return {"items": items, "total": total}

    async def _auto_complete_plan(self, plan_id: str) -> None:
        """若同计划所有工单均已终结，自动将计划升为 completed"""
        result = await self.db.execute(
            text("""
                SELECT COUNT(*) FILTER (WHERE status NOT IN ('completed','cancelled')) AS pending_cnt
                FROM production_orders
                WHERE plan_id=:pid AND tenant_id=:tid
            """),
            {"pid": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        if row and row.pending_cnt == 0:
            await self.db.execute(
                text("UPDATE production_plans SET status='completed' WHERE id=:id AND tenant_id=:tid"),
                {"id": uuid.UUID(plan_id), "tid": self._tid},
            )
            log.info("production_plan_auto_completed", plan_id=plan_id, tenant_id=self.tenant_id)

    # ══════════════════════════════════════════════════════
    # 配送单
    # ══════════════════════════════════════════════════════

    async def create_distribution_order(
        self,
        kitchen_id: str,
        store_id: str,
        items: List[Dict[str, Any]],
        scheduled_at: str,
        driver_name: Optional[str],
        driver_phone: Optional[str],
    ) -> Dict[str, Any]:
        await self._set_tenant()
        oid = uuid.uuid4()
        result = await self.db.execute(
            text("""
                INSERT INTO distribution_orders
                    (id, tenant_id, kitchen_id, target_store_id, scheduled_at,
                     status, items, driver_name, driver_phone, created_at)
                VALUES
                    (:id, :tid, :kid, :sid, :scheduled_at::timestamptz,
                     'pending', :items::jsonb, :drv_name, :drv_phone, NOW())
                RETURNING id, kitchen_id, target_store_id, scheduled_at, delivered_at,
                          status, items, driver_name, driver_phone, created_at
            """),
            {
                "id": oid,
                "tid": self._tid,
                "kid": uuid.UUID(kitchen_id),
                "sid": uuid.UUID(store_id),
                "scheduled_at": scheduled_at,
                "items": json.dumps(items),
                "drv_name": driver_name,
                "drv_phone": driver_phone,
            },
        )
        row = result.fetchone()
        await self.db.flush()
        log.info("distribution_order_created", order_id=str(oid),
                 kitchen_id=kitchen_id, store_id=store_id, tenant_id=self.tenant_id)
        return self._dist_row(row, str(oid))

    async def mark_dispatched(self, order_id: str) -> Dict[str, Any]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                UPDATE distribution_orders
                SET status='dispatched', delivered_at=NOW()
                WHERE id=:id AND tenant_id=:tid AND status='pending'
                RETURNING id, kitchen_id, target_store_id, scheduled_at, delivered_at,
                          status, items, driver_name, driver_phone, created_at
            """),
            {"id": uuid.UUID(order_id), "tid": self._tid},
        )
        row = result.fetchone()
        await self.db.flush()
        if not row:
            raise ValueError(f"配送单 {order_id} 不存在或状态不是 pending")
        log.info("distribution_order_dispatched", order_id=order_id, tenant_id=self.tenant_id)
        return self._dist_row(row, order_id)

    async def list_distribution_orders(
        self,
        kitchen_id: Optional[str],
        store_id: Optional[str],
        status: Optional[str],
        page: int,
        size: int,
    ) -> Dict[str, Any]:
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tid}
        if kitchen_id:
            where += " AND kitchen_id = :kid"
            params["kid"] = uuid.UUID(kitchen_id)
        if store_id:
            where += " AND target_store_id = :sid"
            params["sid"] = uuid.UUID(store_id)
        if status:
            where += " AND status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM distribution_orders {where}"), params
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT id, kitchen_id, target_store_id, scheduled_at, delivered_at,
                       status, items, driver_name, driver_phone, created_at
                FROM distribution_orders {where}
                ORDER BY scheduled_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._dist_row(r, str(r.id)) for r in result.fetchall()]
        return {"items": items, "total": total}

    # ══════════════════════════════════════════════════════
    # 门店收货确认
    # ══════════════════════════════════════════════════════

    async def confirm_receiving(
        self,
        distribution_order_id: str,
        store_id: str,
        confirmed_by: str,
        items: List[Dict[str, Any]],
        notes: Optional[str],
    ) -> Dict[str, Any]:
        await self._set_tenant()
        # 查配送单
        dist_result = await self.db.execute(
            text("""
                SELECT id, target_store_id, status, items, delivered_at
                FROM distribution_orders
                WHERE id=:id AND tenant_id=:tid
            """),
            {"id": uuid.UUID(distribution_order_id), "tid": self._tid},
        )
        dist = dist_result.fetchone()
        if not dist:
            raise ValueError(f"配送单 {distribution_order_id} 不存在")
        if str(dist.target_store_id) != store_id:
            raise ValueError(f"配送单 {distribution_order_id} 目标门店不匹配")
        if dist.status not in ("dispatched", "delivered"):
            raise ValueError(f"配送单状态为 {dist.status}，需为 dispatched 或 delivered")

        # 差异检测
        dist_items = dist.items if isinstance(dist.items, list) else json.loads(dist.items or "[]")
        expected_map = {i["dish_id"]: float(i.get("quantity", 0)) for i in dist_items}

        confirmed_items: List[Dict[str, Any]] = []
        for item in items:
            dish_id = item.get("dish_id", "")
            received = float(item.get("received_qty", 0))
            expected = expected_map.get(dish_id, 0.0)
            variance_pct = abs(received - expected) / expected * 100 if expected > 0 else 0.0
            variance_notes = item.get("variance_notes")
            if variance_pct > 5.0 and not variance_notes:
                variance_notes = (
                    f"差异 {variance_pct:.1f}%：期望 {expected} {item.get('unit','份')}，"
                    f"实收 {received} {item.get('unit','份')}"
                )
            confirmed_items.append({
                "dish_id": dish_id,
                "dish_name": item.get("dish_name", ""),
                "expected_qty": expected,
                "received_qty": received,
                "unit": item.get("unit", "份"),
                "variance_notes": variance_notes,
            })

        now = datetime.now(timezone.utc)
        conf_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO store_receiving_confirmations
                    (id, tenant_id, distribution_order_id, store_id,
                     confirmed_by, confirmed_at, items, notes, created_at)
                VALUES
                    (:id, :tid, :did, :sid, :by, :now, :items::jsonb, :notes, :now)
            """),
            {
                "id": conf_id,
                "tid": self._tid,
                "did": uuid.UUID(distribution_order_id),
                "sid": uuid.UUID(store_id),
                "by": uuid.UUID(confirmed_by),
                "now": now,
                "items": json.dumps(confirmed_items),
                "notes": notes,
            },
        )
        delivered_at = dist.delivered_at or now
        await self.db.execute(
            text("""
                UPDATE distribution_orders
                SET status='confirmed', delivered_at=:da
                WHERE id=:id AND tenant_id=:tid
            """),
            {"da": delivered_at, "id": uuid.UUID(distribution_order_id), "tid": self._tid},
        )
        await self.db.flush()
        log.info("store_receiving_confirmed", confirmation_id=str(conf_id),
                 distribution_order_id=distribution_order_id, tenant_id=self.tenant_id)
        return {
            "id": str(conf_id),
            "tenant_id": self.tenant_id,
            "distribution_order_id": distribution_order_id,
            "store_id": store_id,
            "confirmed_by": confirmed_by,
            "confirmed_at": now.isoformat(),
            "items": confirmed_items,
            "notes": notes,
            "created_at": now.isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 日看板
    # ══════════════════════════════════════════════════════

    async def get_daily_dashboard(self, kitchen_id: str, date_str: str) -> Dict[str, Any]:
        await self._set_tenant()
        kid = uuid.UUID(kitchen_id)

        plans_result = await self.db.execute(
            text("""
                SELECT id, kitchen_id, plan_date, status, items,
                       created_by, confirmed_at, created_at
                FROM production_plans
                WHERE tenant_id=:tid AND kitchen_id=:kid AND plan_date=:d::date
            """),
            {"tid": self._tid, "kid": kid, "d": date_str},
        )
        plan_rows = plans_result.fetchall()
        plans = [self._plan_row(r, str(r.id)) for r in plan_rows]
        plan_ids = [uuid.UUID(p["id"]) for p in plans]

        prod_summary: Dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
        if plan_ids:
            ord_result = await self.db.execute(
                text("""
                    SELECT status, COUNT(*) as cnt
                    FROM production_orders
                    WHERE tenant_id=:tid AND plan_id=ANY(:pids)
                    GROUP BY status
                """),
                {"tid": self._tid, "pids": plan_ids},
            )
            for r in ord_result.fetchall():
                prod_summary[r.status] = r.cnt

        dist_result = await self.db.execute(
            text("""
                SELECT status, COUNT(*) as cnt
                FROM distribution_orders
                WHERE tenant_id=:tid AND kitchen_id=:kid
                  AND scheduled_at::date = :d::date
                GROUP BY status
            """),
            {"tid": self._tid, "kid": kid, "d": date_str},
        )
        dist_summary: Dict[str, int] = {"pending": 0, "dispatched": 0, "delivered": 0, "confirmed": 0}
        for r in dist_result.fetchall():
            dist_summary[r.status] = r.cnt

        return {
            "kitchen_id": kitchen_id,
            "date": date_str,
            "plan_count": len(plans),
            "plans": plans,
            "production_order_summary": prod_summary,
            "distribution_summary": dist_summary,
        }

    # ══════════════════════════════════════════════════════
    # 需求预测（从历史完工工单计算日均）
    # ══════════════════════════════════════════════════════

    async def forecast_demand(self, kitchen_id: str, target_date: str) -> Dict[str, Any]:
        await self._set_tenant()
        target = date.fromisoformat(target_date)
        is_weekend = target.weekday() in _WEEKEND_DAYS
        since = (target - timedelta(days=30)).isoformat()

        result = await self.db.execute(
            text("""
                SELECT po.dish_id, SUM(po.quantity) AS total_qty,
                       COUNT(DISTINCT pp.plan_date) AS day_count,
                       po.unit
                FROM production_orders po
                JOIN production_plans pp ON pp.id = po.plan_id
                WHERE po.tenant_id = :tid AND po.kitchen_id = :kid
                  AND po.status = 'completed'
                  AND pp.plan_date >= :since::date
                GROUP BY po.dish_id, po.unit
            """),
            {"tid": self._tid, "kid": uuid.UUID(kitchen_id), "since": since},
        )
        rows = result.fetchall()

        dishes = []
        for r in rows:
            avg_qty = round(float(r.total_qty) / max(1, r.day_count), 2)
            suggested = round(avg_qty * _WEEKEND_WEIGHT, 2) if is_weekend else avg_qty
            dishes.append({
                "dish_id": str(r.dish_id),
                "dish_name": "",   # 菜品名称从 dishes 表读取，此处省略
                "avg_daily_qty": avg_qty,
                "suggested_qty": suggested,
                "unit": r.unit or "份",
                "weekend_adjusted": is_weekend,
            })

        return {
            "kitchen_id": kitchen_id,
            "target_date": target_date,
            "is_weekend": is_weekend,
            "dishes": dishes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 内部工具
    # ══════════════════════════════════════════════════════

    def _kitchen_row(self, row) -> Dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": self.tenant_id,
            "name": row.name,
            "address": row.address,
            "capacity_daily": float(row.capacity_daily),
            "manager_id": str(row.manager_id) if row.manager_id else None,
            "contact_phone": row.contact_phone,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _plan_row(self, row, plan_id: str) -> Dict[str, Any]:
        items = row.items
        if isinstance(items, str):
            items = json.loads(items)
        return {
            "id": plan_id,
            "tenant_id": self.tenant_id,
            "kitchen_id": str(row.kitchen_id),
            "plan_date": str(row.plan_date),
            "status": row.status,
            "items": items or [],
            "created_by": str(row.created_by) if row.created_by else None,
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _order_row(self, row, order_id: str) -> Dict[str, Any]:
        return {
            "id": order_id,
            "tenant_id": self.tenant_id,
            "kitchen_id": str(row.kitchen_id),
            "plan_id": str(row.plan_id),
            "dish_id": str(row.dish_id),
            "quantity": float(row.quantity),
            "unit": row.unit,
            "status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "operator_id": str(row.operator_id) if row.operator_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _dist_row(self, row, order_id: str) -> Dict[str, Any]:
        items = row.items
        if isinstance(items, str):
            items = json.loads(items)
        return {
            "id": order_id,
            "tenant_id": self.tenant_id,
            "kitchen_id": str(row.kitchen_id),
            "target_store_id": str(row.target_store_id),
            "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "status": row.status,
            "items": items or [],
            "driver_name": row.driver_name,
            "driver_phone": row.driver_phone,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
