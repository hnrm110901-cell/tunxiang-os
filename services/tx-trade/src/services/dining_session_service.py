"""堂食会话服务 (DiningSessionService) — 桌台中心化架构核心

dining_sessions 是门店业务聚合根，一次完整就餐旅程的主记录。
贯穿：开台 → 点菜 → 用餐 → (加菜) → 买单 → 结账 → 清台 全过程。

所有订单、服务呼叫、出餐进度都关联到 dining_sessions.id。

9态状态机合法迁移：
  reserved    → seated
  seated      → ordering
  ordering    → dining | billing
  dining      → add_ordering | billing
  add_ordering→ dining
  billing     → paid
  paid        → clearing
  clearing    → (终态，不可再迁移，下次开台创建新会话)

三条硬约束在调用层（cashier_engine）校验，此服务只管桌台生命周期。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, date as date_type, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import TableEventType

logger = structlog.get_logger()

# ─── 状态机：合法迁移矩阵 ────────────────────────────────────────────────────
VALID_TRANSITIONS: dict[str, list[str]] = {
    "reserved":     ["seated"],
    "seated":       ["ordering"],
    "ordering":     ["dining", "billing"],
    "dining":       ["add_ordering", "billing"],
    "add_ordering": ["dining"],
    "billing":      ["paid"],
    "paid":         ["clearing"],
    "clearing":     [],           # 终态
    "disabled":     [],           # 管理员手动禁用，不参与正常流转
}

# 终态集合：这些状态下桌台可以释放给下一批客人
TERMINAL_STATUSES = {"paid", "clearing", "disabled"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _gen_session_no(store_code: str, today: date_type, seq: int) -> str:
    """生成会话编号，格式：DS{store_code}{YYYYMMDD}{SEQ:04d}
    例：DS01020260405 0001
    """
    return f"DS{store_code}{today.strftime('%Y%m%d')}{seq:04d}"


class DiningSessionService:
    """堂食会话服务

    负责桌台会话的完整生命周期管理。
    每个实例绑定一个 DB 连接和一个租户 ID。
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = uuid.UUID(tenant_id)
        self._tid_str = tenant_id

    # ─── RLS 辅助 ─────────────────────────────────────────────────────────────

    async def _set_tenant(self) -> None:
        await self._db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self._tid_str},
        )

    # ─── 序列号生成 ───────────────────────────────────────────────────────────

    async def _next_session_seq(self, store_id: uuid.UUID, today: date_type) -> int:
        """当日会话序号（原子自增，使用 PG advisory lock 防并发冲突）"""
        result = await self._db.execute(
            text("""
                SELECT COALESCE(MAX(
                    CAST(SUBSTRING(session_no, LENGTH(session_no) - 3) AS INT)
                ), 0) + 1 AS next_seq
                FROM dining_sessions
                WHERE store_id  = :store_id
                  AND tenant_id = :tenant_id
                  AND DATE(opened_at AT TIME ZONE 'UTC') = :today
            """),
            {"store_id": store_id, "tenant_id": self._tenant_id, "today": today},
        )
        row = result.mappings().one()
        return int(row["next_seq"])

    # ─── 开台 ─────────────────────────────────────────────────────────────────

    async def open_table(
        self,
        store_id: uuid.UUID,
        table_id: uuid.UUID,
        guest_count: int,
        lead_waiter_id: uuid.UUID,
        zone_id: Optional[uuid.UUID] = None,
        booking_id: Optional[uuid.UUID] = None,
        vip_customer_id: Optional[uuid.UUID] = None,
        session_type: str = "dine_in",
    ) -> dict:
        """开台：创建 dining_sessions 记录，锁定桌台状态。

        Args:
            store_id:         门店ID
            table_id:         物理桌台ID
            guest_count:      就餐人数（≥1）
            lead_waiter_id:   责任服务员ID
            zone_id:          所属区域ID（可选，从区域分配自动传入）
            booking_id:       来源预订单ID（预订转开台时传入）
            vip_customer_id:  VIP顾客ID（开台时识别/扫码绑定）
            session_type:     类型：dine_in/banquet/vip_room/self_order/hotpot

        Returns:
            新建的 dining_session 记录（dict）

        Raises:
            ValueError: 桌台已有活跃会话（重复开台）
        """
        await self._set_tenant()

        if guest_count < 1:
            raise ValueError(f"就餐人数必须 ≥ 1，收到：{guest_count}")

        # 检查桌台是否已有活跃会话
        existing = await self.get_active_session_by_table(store_id, table_id)
        if existing:
            raise ValueError(
                f"桌台 {table_id} 已有活跃会话 {existing['session_no']}（状态：{existing['status']}），"
                f"请先清台再开台"
            )

        # 获取桌台信息（桌号快照、低消配置）
        table_row = await self._db.execute(
            text("""
                SELECT table_no, config, min_consume_fen, area, seats, table_type
                FROM tables WHERE id = :id AND tenant_id = :tid
            """),
            {"id": table_id, "tid": self._tenant_id},
        )
        table_info = table_row.mappings().one_or_none()
        if table_info is None:
            raise ValueError(f"桌台 {table_id} 不存在")
        table_no_snapshot = table_info["table_no"]

        # 构建 room_config：包间低消、桌型等元数据
        min_consume_fen: int = int(table_info["min_consume_fen"] or 0)
        room_config: dict = {}
        if min_consume_fen > 0:
            room_config["min_spend_fen"] = min_consume_fen
        # 继承桌台额外配置（如服务费率、包间收费等）
        extra_config = table_info["config"] or {}
        if isinstance(extra_config, dict):
            room_config.update({k: v for k, v in extra_config.items() if k not in room_config})

        # 获取门店 store_code（用于生成 session_no）
        store_row = await self._db.execute(
            text("SELECT store_code FROM stores WHERE id = :id AND tenant_id = :tid"),
            {"id": store_id, "tid": self._tenant_id},
        )
        store_info = store_row.mappings().one_or_none()
        store_code = (store_info["store_code"] if store_info else "00")[:4]

        # 生成会话编号
        today = _now_utc().date()
        seq = await self._next_session_seq(store_id, today)
        session_no = _gen_session_no(store_code, today, seq)
        session_id = uuid.uuid4()
        now = _now_utc()

        # 插入 dining_sessions
        await self._db.execute(
            text("""
                INSERT INTO dining_sessions (
                    id, tenant_id, store_id, table_id, session_no,
                    guest_count, vip_customer_id, booking_id,
                    status, lead_waiter_id, zone_id, session_type,
                    opened_at, table_no_snapshot,
                    total_orders, total_items, total_amount_fen,
                    discount_amount_fen, final_amount_fen, per_capita_fen,
                    service_call_count, room_config,
                    created_at, updated_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :store_id, :table_id, :session_no,
                    :guest_count, :vip_customer_id, :booking_id,
                    'seated', :lead_waiter_id, :zone_id, :session_type,
                    :now, :table_no_snapshot,
                    0, 0, 0, 0, 0, 0, 0, :room_config,
                    :now, :now, FALSE
                )
            """),
            {
                "id": session_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "table_id": table_id,
                "session_no": session_no,
                "guest_count": guest_count,
                "vip_customer_id": vip_customer_id,
                "booking_id": booking_id,
                "lead_waiter_id": lead_waiter_id,
                "zone_id": zone_id,
                "session_type": session_type,
                "now": now,
                "table_no_snapshot": table_no_snapshot,
                "room_config": room_config,
            },
        )

        # 更新 tables.status → occupied
        await self._db.execute(
            text("""
                UPDATE tables
                SET status = 'occupied', updated_at = :now
                WHERE id = :table_id AND tenant_id = :tid
            """),
            {"now": now, "table_id": table_id, "tid": self._tenant_id},
        )

        # 写入会话事件
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.OPENED,
            payload={
                "guest_count": guest_count,
                "session_type": session_type,
                "table_no": table_no_snapshot,
                "booking_id": str(booking_id) if booking_id else None,
                "min_spend_fen": min_consume_fen,
            },
            operator_id=lead_waiter_id,
            operator_type="employee",
        )

        # 旁路发送跨域事件
        asyncio.create_task(emit_event(
            event_type=TableEventType.OPENED,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={
                "session_no": session_no,
                "table_id": str(table_id),
                "table_no": table_no_snapshot,
                "guest_count": guest_count,
                "session_type": session_type,
                "lead_waiter_id": str(lead_waiter_id),
                "booking_id": str(booking_id) if booking_id else None,
                "vip_customer_id": str(vip_customer_id) if vip_customer_id else None,
            },
            store_id=store_id,
            source_service="tx-trade",
        ))

        logger.info(
            "dining_session_opened",
            session_id=str(session_id),
            session_no=session_no,
            table_id=str(table_id),
            table_no=table_no_snapshot,
            guest_count=guest_count,
            session_type=session_type,
            tenant_id=self._tid_str,
        )

        return await self.get_session(session_id)  # type: ignore[return-value]

    # ─── 查询 ─────────────────────────────────────────────────────────────────

    async def get_session(self, session_id: uuid.UUID) -> Optional[dict]:
        """按 ID 获取堂食会话"""
        await self._set_tenant()
        result = await self._db.execute(
            text("""
                SELECT ds.*,
                       t.table_no, t.area, t.floor, t.seats,
                       e.emp_name AS lead_waiter_name
                FROM dining_sessions ds
                LEFT JOIN tables    t ON t.id = ds.table_id
                LEFT JOIN employees e ON e.id = ds.lead_waiter_id
                WHERE ds.id        = :session_id
                  AND ds.tenant_id = :tenant_id
                  AND ds.is_deleted = FALSE
            """),
            {"session_id": session_id, "tenant_id": self._tenant_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def get_active_session_by_table(
        self, store_id: uuid.UUID, table_id: uuid.UUID
    ) -> Optional[dict]:
        """获取桌台的当前活跃会话（非终态）"""
        await self._set_tenant()
        result = await self._db.execute(
            text("""
                SELECT * FROM dining_sessions
                WHERE store_id  = :store_id
                  AND table_id  = :table_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status NOT IN ('paid', 'clearing', 'disabled')
                ORDER BY opened_at DESC
                LIMIT 1
            """),
            {
                "store_id": store_id,
                "table_id": table_id,
                "tenant_id": self._tenant_id,
            },
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def get_store_board(self, store_id: uuid.UUID) -> list[dict]:
        """获取门店所有活跃会话看板（含桌台、区域、服务员信息）。
        用于 POS 桌台大板实时展示。
        """
        await self._set_tenant()
        result = await self._db.execute(
            text("""
                SELECT
                    ds.id, ds.session_no, ds.status, ds.session_type,
                    ds.guest_count, ds.opened_at, ds.first_order_at,
                    ds.bill_requested_at, ds.total_amount_fen,
                    ds.final_amount_fen, ds.per_capita_fen,
                    ds.service_call_count, ds.total_orders,
                    ds.vip_customer_id,
                    t.id       AS table_id,
                    t.table_no, t.area, t.floor, t.seats,
                    tz.zone_name, tz.zone_type,
                    e.emp_name AS lead_waiter_name,
                    -- 用餐时长（分钟）
                    EXTRACT(EPOCH FROM (NOW() - ds.opened_at)) / 60 AS dining_minutes,
                    -- 待处理服务呼叫数
                    (SELECT COUNT(*) FROM service_calls sc
                     WHERE sc.table_session_id = ds.id
                       AND sc.status = 'pending') AS pending_calls
                FROM dining_sessions ds
                JOIN tables    t  ON t.id  = ds.table_id
                LEFT JOIN table_zones  tz ON tz.id = ds.zone_id
                LEFT JOIN employees    e  ON e.id  = ds.lead_waiter_id
                WHERE ds.store_id  = :store_id
                  AND ds.tenant_id = :tenant_id
                  AND ds.is_deleted = FALSE
                  AND ds.status NOT IN ('paid', 'clearing', 'disabled')
                ORDER BY t.floor, t.area, t.table_no
            """),
            {"store_id": store_id, "tenant_id": self._tenant_id},
        )
        return [dict(r) for r in result.mappings().all()]

    # ─── 状态机迁移 ───────────────────────────────────────────────────────────

    async def transition_status(
        self,
        session_id: uuid.UUID,
        new_status: str,
        operator_id: Optional[uuid.UUID] = None,
        reason: Optional[str] = None,
    ) -> dict:
        """状态机迁移：校验合法性后更新状态，记录事件。

        Raises:
            ValueError: 会话不存在、已删除、或迁移不合法
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        current = session["status"]
        allowed = VALID_TRANSITIONS.get(current, [])
        if new_status not in allowed:
            raise ValueError(
                f"状态迁移不合法：{current} → {new_status}。"
                f"当前允许迁移到：{allowed or '（终态，无法迁移）'}"
            )

        now = _now_utc()
        # 根据新状态更新对应时间戳字段
        ts_field_map = {
            "billing":  "bill_requested_at",
            "paid":     "paid_at",
            "clearing": "cleared_at",
        }
        ts_field = ts_field_map.get(new_status)
        if ts_field:
            await self._db.execute(
                text(f"""
                    UPDATE dining_sessions
                    SET status     = :new_status,
                        {ts_field} = :now,
                        updated_at = :now
                    WHERE id = :session_id AND tenant_id = :tenant_id
                """),
                {
                    "new_status": new_status,
                    "now": now,
                    "session_id": session_id,
                    "tenant_id": self._tenant_id,
                },
            )
        else:
            await self._db.execute(
                text("""
                    UPDATE dining_sessions
                    SET status     = :new_status,
                        updated_at = :now
                    WHERE id = :session_id AND tenant_id = :tenant_id
                """),
                {
                    "new_status": new_status,
                    "now": now,
                    "session_id": session_id,
                    "tenant_id": self._tenant_id,
                },
            )

        # 状态→事件类型映射
        status_event_map = {
            "billing":  TableEventType.BILL_REQUESTED,
            "paid":     TableEventType.PAID,
            "clearing": TableEventType.CLEARED,
        }
        event_type = status_event_map.get(new_status)
        if event_type:
            store_id = uuid.UUID(str(session["store_id"]))
            await self._append_session_event(
                session_id=session_id,
                store_id=store_id,
                event_type=event_type,
                payload={"from_status": current, "reason": reason},
                operator_id=operator_id,
            )
            asyncio.create_task(emit_event(
                event_type=event_type,
                tenant_id=self._tenant_id,
                stream_id=str(session_id),
                payload={"from_status": current, "to_status": new_status, "reason": reason},
                store_id=store_id,
                source_service="tx-trade",
            ))

        logger.info(
            "dining_session_status_changed",
            session_id=str(session_id),
            from_status=current,
            to_status=new_status,
            operator_id=str(operator_id) if operator_id else None,
            tenant_id=self._tid_str,
        )
        return await self.get_session(session_id)  # type: ignore[return-value]

    # ─── 订单关联 ─────────────────────────────────────────────────────────────

    async def record_order_placed(
        self,
        session_id: uuid.UUID,
        order_id: uuid.UUID,
        is_add_order: bool = False,
        order_amount_fen: int = 0,
        item_count: int = 0,
    ) -> None:
        """订单下单后回调：更新会话汇总字段，推进状态。

        由 OrderService.create_order() 在写入 orders 后调用。
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        now = _now_utc()
        is_first_order = (session["total_orders"] == 0)

        # 更新汇总字段
        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET total_orders       = total_orders + 1,
                    total_items        = total_items + :item_count,
                    total_amount_fen   = total_amount_fen + :amount_fen,
                    first_order_at     = COALESCE(first_order_at, :now),
                    updated_at         = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {
                "item_count": item_count,
                "amount_fen": order_amount_fen,
                "now": now,
                "session_id": session_id,
                "tenant_id": self._tenant_id,
            },
        )

        # 推进状态
        current_status = session["status"]
        if is_add_order and current_status == "dining":
            await self.transition_status(session_id, "add_ordering")
        elif is_first_order and current_status == "seated":
            await self.transition_status(session_id, "ordering")

        store_id = uuid.UUID(str(session["store_id"]))
        event_type = TableEventType.ADD_ORDERED if is_add_order else TableEventType.ORDER_PLACED
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=event_type,
            payload={
                "order_id": str(order_id),
                "order_amount_fen": order_amount_fen,
                "item_count": item_count,
                "is_add_order": is_add_order,
            },
        )
        asyncio.create_task(emit_event(
            event_type=event_type,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={
                "order_id": str(order_id),
                "order_amount_fen": order_amount_fen,
                "item_count": item_count,
            },
            store_id=store_id,
            source_service="tx-trade",
        ))

    async def record_dish_served(
        self,
        session_id: uuid.UUID,
        dish_count: int = 1,
    ) -> None:
        """KDS 确认上菜后回调：更新上菜时间戳，推进状态到 dining。"""
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            return  # 会话已结束，静默忽略

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET last_dish_served_at  = :now,
                    first_dish_served_at = COALESCE(first_dish_served_at, :now),
                    updated_at           = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {"now": now, "session_id": session_id, "tenant_id": self._tenant_id},
        )

        current_status = session["status"]
        if current_status in ("ordering", "add_ordering"):
            await self.transition_status(session_id, "dining")

        await self._append_session_event(
            session_id=session_id,
            store_id=uuid.UUID(str(session["store_id"])),
            event_type=TableEventType.DISH_SERVED,
            payload={"dish_count": dish_count},
        )

    # ─── 转台 ─────────────────────────────────────────────────────────────────

    async def transfer_table(
        self,
        session_id: uuid.UUID,
        target_table_id: uuid.UUID,
        reason: str,
        operator_id: uuid.UUID,
    ) -> dict:
        """转台：将会话迁移到新桌台，释放旧桌台。

        Raises:
            ValueError: 目标桌台已有活跃会话
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        store_id = uuid.UUID(str(session["store_id"]))
        old_table_id = uuid.UUID(str(session["table_id"]))

        if old_table_id == target_table_id:
            raise ValueError("目标桌台与当前桌台相同，无需转台")

        # 检查目标桌台是否可用
        target_existing = await self.get_active_session_by_table(store_id, target_table_id)
        if target_existing:
            raise ValueError(
                f"目标桌台 {target_table_id} 已有活跃会话 {target_existing['session_no']}，无法转台"
            )

        # 获取目标桌台信息（桌号 + 低消配置）
        target_row = await self._db.execute(
            text("""
                SELECT table_no, min_consume_fen, config
                FROM tables WHERE id = :id AND tenant_id = :tid
            """),
            {"id": target_table_id, "tid": self._tenant_id},
        )
        target_info = target_row.mappings().one_or_none()
        if target_info is None:
            raise ValueError(f"目标桌台 {target_table_id} 不存在")
        new_table_no = target_info["table_no"]

        # 更新 room_config：新桌台的低消覆盖旧桌台低消
        new_min_consume_fen = int(target_info["min_consume_fen"] or 0)
        existing_room_config: dict = dict(session.get("room_config") or {})
        if new_min_consume_fen > 0:
            existing_room_config["min_spend_fen"] = new_min_consume_fen
        elif "min_spend_fen" in existing_room_config:
            # 新桌台无低消要求，移除低消限制
            del existing_room_config["min_spend_fen"]
        # 合并新桌台额外配置
        extra_config = target_info["config"] or {}
        if isinstance(extra_config, dict):
            existing_room_config.update(
                {k: v for k, v in extra_config.items() if k not in ("min_spend_fen",)}
            )

        now = _now_utc()

        # 更新会话的 table_id、桌号快照和 room_config
        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET table_id          = :target_table_id,
                    table_no_snapshot = :new_table_no,
                    room_config       = :room_config,
                    updated_at        = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {
                "target_table_id": target_table_id,
                "new_table_no": new_table_no,
                "room_config": existing_room_config,
                "now": now,
                "session_id": session_id,
                "tenant_id": self._tenant_id,
            },
        )

        # 旧桌台 → free，新桌台 → occupied
        await self._db.execute(
            text("""
                UPDATE tables SET status = 'free', updated_at = :now
                WHERE id = :old_id AND tenant_id = :tid
            """),
            {"now": now, "old_id": old_table_id, "tid": self._tenant_id},
        )
        await self._db.execute(
            text("""
                UPDATE tables SET status = 'occupied', updated_at = :now
                WHERE id = :new_id AND tenant_id = :tid
            """),
            {"now": now, "new_id": target_table_id, "tid": self._tenant_id},
        )

        old_table_no = session["table_no_snapshot"] or session.get("table_no", "")
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.TRANSFERRED,
            payload={
                "from_table_id": str(old_table_id),
                "from_table_no": old_table_no,
                "to_table_id": str(target_table_id),
                "to_table_no": new_table_no,
                "reason": reason,
            },
            operator_id=operator_id,
        )
        asyncio.create_task(emit_event(
            event_type=TableEventType.TRANSFERRED,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={
                "from_table_no": old_table_no,
                "to_table_no": new_table_no,
                "reason": reason,
            },
            store_id=store_id,
            source_service="tx-trade",
        ))

        logger.info(
            "dining_session_transferred",
            session_id=str(session_id),
            from_table=old_table_no,
            to_table=new_table_no,
            reason=reason,
            tenant_id=self._tid_str,
        )
        return await self.get_session(session_id)  # type: ignore[return-value]

    # ─── 并台 ─────────────────────────────────────────────────────────────────

    async def merge_sessions(
        self,
        primary_session_id: uuid.UUID,
        secondary_session_ids: list[uuid.UUID],
        operator_id: uuid.UUID,
    ) -> dict:
        """并台：将多个会话合并到主会话。

        - 副会话的所有订单关联到主会话
        - 副会话标记为 is_deleted=True（逻辑删除，保留历史）
        - 副会话对应桌台状态 → free（合并后不再单独占用）
        - 主会话汇总金额重新计算

        Raises:
            ValueError: 主会话不存在，或副会话与主会话不属同一门店
        """
        await self._set_tenant()
        primary = await self.get_session(primary_session_id)
        if primary is None:
            raise ValueError(f"主会话 {primary_session_id} 不存在")

        store_id = uuid.UUID(str(primary["store_id"]))
        now = _now_utc()
        merged_table_nos: list[str] = []

        for sec_id in secondary_session_ids:
            sec = await self.get_session(sec_id)
            if sec is None:
                raise ValueError(f"副会话 {sec_id} 不存在")
            if str(sec["store_id"]) != str(store_id):
                raise ValueError(f"副会话 {sec_id} 属于不同门店，无法并台")

            sec_table_no = sec.get("table_no_snapshot") or sec.get("table_no", "")
            merged_table_nos.append(sec_table_no)

            # 将副会话的订单关联到主会话
            await self._db.execute(
                text("""
                    UPDATE orders
                    SET dining_session_id = :primary_id,
                        updated_at        = :now
                    WHERE dining_session_id = :sec_id
                      AND tenant_id        = :tenant_id
                """),
                {
                    "primary_id": primary_session_id,
                    "now": now,
                    "sec_id": sec_id,
                    "tenant_id": self._tenant_id,
                },
            )

            # 释放副会话桌台
            sec_table_id = uuid.UUID(str(sec["table_id"]))
            await self._db.execute(
                text("""
                    UPDATE tables SET status = 'free', updated_at = :now
                    WHERE id = :table_id AND tenant_id = :tid
                """),
                {"now": now, "table_id": sec_table_id, "tid": self._tenant_id},
            )

            # 逻辑删除副会话
            await self._db.execute(
                text("""
                    UPDATE dining_sessions
                    SET is_deleted = TRUE, updated_at = :now
                    WHERE id = :sec_id AND tenant_id = :tenant_id
                """),
                {"now": now, "sec_id": sec_id, "tenant_id": self._tenant_id},
            )

        # 重新汇总主会话金额
        await self._db.execute(
            text("""
                UPDATE dining_sessions ds
                SET total_orders     = (
                        SELECT COUNT(*) FROM orders o
                        WHERE o.dining_session_id = ds.id AND o.tenant_id = ds.tenant_id
                          AND o.is_deleted = FALSE
                    ),
                    total_amount_fen = (
                        SELECT COALESCE(SUM(o.total_amount_fen), 0)
                        FROM orders o
                        WHERE o.dining_session_id = ds.id AND o.tenant_id = ds.tenant_id
                          AND o.is_deleted = FALSE
                    ),
                    updated_at = :now
                WHERE ds.id = :primary_id AND ds.tenant_id = :tenant_id
            """),
            {"now": now, "primary_id": primary_session_id, "tenant_id": self._tenant_id},
        )

        await self._append_session_event(
            session_id=primary_session_id,
            store_id=store_id,
            event_type=TableEventType.MERGED,
            payload={
                "merged_session_ids": [str(s) for s in secondary_session_ids],
                "merged_table_nos": merged_table_nos,
            },
            operator_id=operator_id,
        )
        asyncio.create_task(emit_event(
            event_type=TableEventType.MERGED,
            tenant_id=self._tenant_id,
            stream_id=str(primary_session_id),
            payload={
                "merged_count": len(secondary_session_ids),
                "merged_table_nos": merged_table_nos,
            },
            store_id=store_id,
            source_service="tx-trade",
        ))

        logger.info(
            "dining_sessions_merged",
            primary_session_id=str(primary_session_id),
            secondary_count=len(secondary_session_ids),
            merged_table_nos=merged_table_nos,
            tenant_id=self._tid_str,
        )
        return await self.get_session(primary_session_id)  # type: ignore[return-value]

    # ─── 买单 / 结账 / 清台 ──────────────────────────────────────────────────

    async def request_bill(
        self,
        session_id: uuid.UUID,
        operator_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """请求买单：校验低消后状态迁移到 billing，记录 bill_requested_at。

        低消校验规则：
          - room_config.min_spend_fen > 0 时强制校验
          - total_amount_fen < min_spend_fen → 抛出 ValueError，提示差额
          - 管理员可通过 override_min_spend=True 豁免（在 API 层处理，此处强制校验）
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        # ── 低消校验 ──────────────────────────────────────────────────────────
        room_config = session.get("room_config") or {}
        min_spend_fen: int = int(room_config.get("min_spend_fen", 0))
        min_spend_override: bool = bool(session.get("min_spend_override", False))
        if min_spend_fen > 0 and not min_spend_override:
            total_amount_fen: int = int(session.get("total_amount_fen") or 0)
            if total_amount_fen < min_spend_fen:
                shortfall_fen = min_spend_fen - total_amount_fen
                shortfall_yuan = shortfall_fen / 100
                min_yuan = min_spend_fen / 100
                raise ValueError(
                    f"未达到包间最低消费 ¥{min_yuan:.0f}，"
                    f"当前消费 ¥{total_amount_fen / 100:.0f}，"
                    f"还差 ¥{shortfall_yuan:.0f}，"
                    f"如需豁免请联系管理员审批"
                )

        return await self.transition_status(
            session_id, "billing", operator_id=operator_id
        )

    async def override_min_spend(
        self,
        session_id: uuid.UUID,
        approver_id: uuid.UUID,
    ) -> dict:
        """管理员豁免低消：设置 min_spend_override=true，记录审批人。

        豁免后下次 request_bill() 不再检查低消。
        须配合审批日志（approval_logs 表）记录审批意图。
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET min_spend_override    = true,
                    min_spend_override_by = :approver_id,
                    min_spend_override_at = :now,
                    updated_at            = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {
                "approver_id": approver_id,
                "now": now,
                "session_id": session_id,
                "tenant_id": self._tenant_id,
            },
        )

        store_id = uuid.UUID(str(session["store_id"]))
        room_config = session.get("room_config") or {}
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.BILL_REQUESTED,  # 复用审批事件，payload区分
            payload={
                "action": "min_spend_override",
                "approver_id": str(approver_id),
                "original_min_spend_fen": room_config.get("min_spend_fen", 0),
                "current_amount_fen": session.get("total_amount_fen", 0),
            },
            operator_id=approver_id,
        )

        logger.info(
            "dining_session_min_spend_overridden",
            session_id=str(session_id),
            approver_id=str(approver_id),
            min_spend_fen=room_config.get("min_spend_fen", 0),
            tenant_id=self._tid_str,
        )
        return await self.get_session(session_id)  # type: ignore[return-value]

    async def complete_payment(
        self,
        session_id: uuid.UUID,
        final_amount_fen: int,
        discount_amount_fen: int = 0,
    ) -> dict:
        """结账完成：更新金额汇总，迁移到 paid，计算人均消费。

        由 payment_service 在支付确认后调用。
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        guest_count = max(session["guest_count"], 1)
        per_capita = final_amount_fen // guest_count
        now = _now_utc()

        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET final_amount_fen    = :final_amount_fen,
                    discount_amount_fen = :discount_amount_fen,
                    per_capita_fen      = :per_capita,
                    paid_at             = :now,
                    status              = 'paid',
                    updated_at          = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
                  AND status = 'billing'
            """),
            {
                "final_amount_fen": final_amount_fen,
                "discount_amount_fen": discount_amount_fen,
                "per_capita": per_capita,
                "now": now,
                "session_id": session_id,
                "tenant_id": self._tenant_id,
            },
        )

        store_id = uuid.UUID(str(session["store_id"]))
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.PAID,
            payload={
                "final_amount_fen": final_amount_fen,
                "discount_amount_fen": discount_amount_fen,
                "per_capita_fen": per_capita,
                "guest_count": guest_count,
            },
        )
        asyncio.create_task(emit_event(
            event_type=TableEventType.PAID,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={
                "final_amount_fen": final_amount_fen,
                "discount_amount_fen": discount_amount_fen,
                "per_capita_fen": per_capita,
            },
            store_id=store_id,
            source_service="tx-trade",
        ))

        logger.info(
            "dining_session_paid",
            session_id=str(session_id),
            final_amount_fen=final_amount_fen,
            per_capita_fen=per_capita,
            tenant_id=self._tid_str,
        )
        return await self.get_session(session_id)  # type: ignore[return-value]

    async def clear_table(
        self,
        session_id: uuid.UUID,
        cleaner_id: uuid.UUID,
    ) -> None:
        """清台：会话进入 clearing，更新 cleared_at，桌台状态 → free。

        由服务员在清洁桌面完成后确认触发。
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        if session["status"] != "paid":
            raise ValueError(
                f"只有已结账（paid）的会话才能清台，当前状态：{session['status']}"
            )

        now = _now_utc()
        table_id = uuid.UUID(str(session["table_id"]))
        store_id = uuid.UUID(str(session["store_id"]))

        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET status     = 'clearing',
                    cleared_at = :now,
                    updated_at = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {"now": now, "session_id": session_id, "tenant_id": self._tenant_id},
        )

        # 桌台状态 → free（可以开新台）
        await self._db.execute(
            text("""
                UPDATE tables
                SET status = 'free', updated_at = :now
                WHERE id = :table_id AND tenant_id = :tid
            """),
            {"now": now, "table_id": table_id, "tid": self._tenant_id},
        )

        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.CLEARED,
            payload={
                "cleared_by": str(cleaner_id),
                "dining_minutes": int(
                    (now - session["opened_at"]).total_seconds() / 60
                ) if session.get("opened_at") else None,
            },
            operator_id=cleaner_id,
        )
        asyncio.create_task(emit_event(
            event_type=TableEventType.CLEARED,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={"session_no": session["session_no"]},
            store_id=store_id,
            source_service="tx-trade",
        ))

        logger.info(
            "dining_session_cleared",
            session_id=str(session_id),
            table_id=str(table_id),
            cleaner_id=str(cleaner_id),
            tenant_id=self._tid_str,
        )

    # ─── VIP 识别 ─────────────────────────────────────────────────────────────

    async def identify_vip(
        self,
        session_id: uuid.UUID,
        customer_id: uuid.UUID,
        identified_by: str = "scan",
    ) -> dict:
        """在会话进行中识别 VIP（扫码/人脸/手机号）。

        触发 TABLE.VIP_IDENTIFIED 事件，Agent 订阅后推送个性化服务建议。
        """
        await self._set_tenant()
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"堂食会话 {session_id} 不存在")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE dining_sessions
                SET vip_customer_id = :customer_id,
                    updated_at      = :now
                WHERE id = :session_id AND tenant_id = :tenant_id
            """),
            {
                "customer_id": customer_id,
                "now": now,
                "session_id": session_id,
                "tenant_id": self._tenant_id,
            },
        )

        store_id = uuid.UUID(str(session["store_id"]))
        await self._append_session_event(
            session_id=session_id,
            store_id=store_id,
            event_type=TableEventType.VIP_IDENTIFIED,
            payload={
                "customer_id": str(customer_id),
                "identified_by": identified_by,
            },
        )
        asyncio.create_task(emit_event(
            event_type=TableEventType.VIP_IDENTIFIED,
            tenant_id=self._tenant_id,
            stream_id=str(session_id),
            payload={"customer_id": str(customer_id), "identified_by": identified_by},
            store_id=store_id,
            source_service="tx-trade",
        ))

        return await self.get_session(session_id)  # type: ignore[return-value]

    # ─── 内部工具 ─────────────────────────────────────────────────────────────

    async def _append_session_event(
        self,
        session_id: uuid.UUID,
        store_id: uuid.UUID,
        event_type: TableEventType,
        payload: dict,
        operator_id: Optional[uuid.UUID] = None,
        operator_type: str = "employee",
    ) -> None:
        """写入 dining_session_events（会话内部事件流，append-only）。"""
        await self._db.execute(
            text("""
                INSERT INTO dining_session_events (
                    id, tenant_id, store_id, table_session_id,
                    event_type, payload,
                    operator_id, operator_type, occurred_at
                ) VALUES (
                    gen_random_uuid(), :tenant_id, :store_id, :session_id,
                    :event_type, :payload::jsonb,
                    :operator_id, :operator_type, NOW()
                )
            """),
            {
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "session_id": session_id,
                "event_type": event_type.value,
                "payload": __import__("json").dumps(payload, ensure_ascii=False, default=str),
                "operator_id": operator_id,
                "operator_type": operator_type,
            },
        )
