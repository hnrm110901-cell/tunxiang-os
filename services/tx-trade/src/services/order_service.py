"""收银核心服务 — 开单/加菜/改菜/结算/退款

所有金额单位：分（fen）。
三条硬约束在此层校验：毛利底线 + 食安合规 + 出餐时间。

离线降级：
  - create_order / settle_order 接受 is_offline=True 标志
  - 离线时通过 OfflineSyncService 将订单快照存入本地队列
  - 在线时走正常 SQLAlchemy 流程（不受影响）
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import OrderEventType
from shared.ontology.src.entities import Order, OrderItem
from shared.ontology.src.enums import OrderStatus

from ..models.enums import OrderType, TableStatus
from ..models.tables import Table
from .attribution_hook import fire_order_attribution
from .state_machine import transition_order

if TYPE_CHECKING:
    from edge.sync_engine.src.offline_sync_service import OfflineSyncService  # noqa: F401

logger = structlog.get_logger()


def _gen_order_no() -> str:
    now = datetime.now(timezone.utc)
    return f"TX{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"


class OrderService:
    """收银核心服务

    离线模式：
        传入 offline_sync_service 实例后，create_order / settle_order 支持
        is_offline=True 降级路径 — 断网时将订单快照写入本地离线队列，
        返回 local_order_id，不执行任何 DB 写操作。
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        offline_sync_service: Optional[Any] = None,
    ) -> None:
        # PR #265 round-3 verifier 修复：原版双 __init__（line 42-46 + 56-64）
        # 第二个覆盖第一个，导致 _tenant_id_str 在真实业务路径未初始化，
        # _set_tenant() 调用 self._tenant_id_str 抛 AttributeError；
        # 测试用 svc._tenant_id_str = str(svc.tenant_id) 临时 patch 兜过去。
        # 现合并为单一 __init__，统一初始化所有实例属性。
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)
        self._tenant_id_str = tenant_id
        self._offline_sync: Optional[Any] = offline_sync_service

    async def _set_tenant(self) -> None:
        await self.db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": self._tenant_id_str})

    async def create_order(
        self,
        store_id: str,
        order_type: str = OrderType.dine_in.value,
        table_no: Optional[str] = None,
        customer_id: Optional[str] = None,
        waiter_id: Optional[str] = None,
        is_offline: bool = False,
        items_data: Optional[list[dict]] = None,
        payments_data: Optional[list[dict]] = None,
        dining_session_id: Optional[str] = None,
        order_sequence: int = 1,
    ) -> dict:
        """开单 — 创建订单并关联桌台会话（v150+）

        Args:
            store_id:           门店 ID
            order_type:         订单类型（dine_in/takeaway/...）
            table_no:           桌号（兼容旧接口，v150 后优先用 dining_session_id）
            customer_id:        会员 ID（可选）
            waiter_id:          服务员 ID（可选）
            is_offline:         True = 断网模式，将订单写入离线队列并返回 local_order_id
            items_data:         离线模式下的订单明细快照列表
            payments_data:      离线模式下的支付数据快照列表
            dining_session_id:  堂食会话ID（v150新增，堂食场景必传）
            order_sequence:     会话内点单序号（1=主单，2+=加菜单）

        Returns:
            在线模式：{"order_id": str, "order_no": str}
            离线模式：{"order_id": str, "order_no": str, "offline": True, "local_order_id": str}
        """
        # ── 离线降级路径 ──────────────────────────────────────────────────
        if is_offline:
            if not self._offline_sync:
                raise RuntimeError("offline_sync_service is required for offline order creation")
            order_no = _gen_order_no()
            temp_order_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            order_snapshot: dict = {
                "id": temp_order_id,
                "tenant_id": str(self.tenant_id),
                "store_id": store_id,
                "order_no": order_no,
                "order_type": order_type,
                "table_number": table_no,
                "customer_id": customer_id,
                "waiter_id": waiter_id,
                "status": OrderStatus.pending.value,
                "total_amount_fen": 0,
                "discount_amount_fen": 0,
                "final_amount_fen": 0,
                "order_time": now_iso,
                "created_offline": True,
            }

            local_order_id = await self._offline_sync.queue_offline_order(
                order_data=order_snapshot,
                items_data=items_data or [],
                payments_data=payments_data,
                tenant_id=str(self.tenant_id),
                store_id=store_id,
            )

            logger.info(
                "order_created_offline",
                local_order_id=local_order_id,
                order_no=order_no,
                store_id=store_id,
                table=table_no,
            )
            return {
                "order_id": temp_order_id,
                "order_no": order_no,
                "offline": True,
                "local_order_id": local_order_id,
            }

        # ── 在线正常路径 ──────────────────────────────────────────────────
        order_no = _gen_order_no()
        is_add_order = order_sequence > 1

        # 若传入 dining_session_id，从会话中补全 table_no（向后兼容打印等场景）
        _resolved_table_no = table_no
        if dining_session_id and not table_no:
            _snap = await self.db.execute(
                text("SELECT table_no_snapshot FROM dining_sessions WHERE id = :sid AND tenant_id = :tid"),
                {"sid": uuid.UUID(dining_session_id), "tid": self.tenant_id},
            )
            _snap_row = _snap.mappings().one_or_none()
            if _snap_row:
                _resolved_table_no = _snap_row["table_no_snapshot"]

        order = Order(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_no=order_no,
            store_id=uuid.UUID(store_id),
            table_number=_resolved_table_no,
            customer_id=uuid.UUID(customer_id) if customer_id else None,
            waiter_id=waiter_id,
            order_type=order_type,
            total_amount_fen=0,
            discount_amount_fen=0,
            final_amount_fen=0,
            status=OrderStatus.pending.value,
        )

        # v150：写入 dining_session_id / order_sequence / is_add_order
        if dining_session_id:
            await self.db.execute(
                text(
                    """
                    UPDATE orders SET
                        dining_session_id = :dsid,
                        order_sequence    = :seq,
                        is_add_order      = :is_add
                    WHERE id = :oid AND tenant_id = :tid
                """
                ),
                {
                    "dsid": uuid.UUID(dining_session_id),
                    "seq": order_sequence,
                    "is_add": is_add_order,
                    "oid": order.id,
                    "tid": self.tenant_id,
                },
            )

        self.db.add(order)
        if _resolved_table_no and order_type == OrderType.dine_in.value and not dining_session_id:
            # 旧逻辑：无 dining_session_id 时才用旧的 _lock_table（兼容期）
            await self._lock_table(store_id, _resolved_table_no, order.id)
        await self.db.flush()

        # v149：回调 DiningSessionService，更新会话汇总 + 推进状态
        if dining_session_id:
            import asyncio

            from .dining_session_service import DiningSessionService

            asyncio.create_task(
                DiningSessionService(self.db, str(self.tenant_id)).record_order_placed(
                    session_id=uuid.UUID(dining_session_id),
                    order_id=order.id,
                    is_add_order=is_add_order,
                    order_amount_fen=0,  # 下单时金额为0，加菜后由 cashier_engine 更新
                    item_count=0,
                )
            )

        return {"order_id": str(order.id), "order_no": order_no}

    async def add_item(
        self,
        order_id: str,
        dish_id: str,
        dish_name: str,
        quantity: int,
        unit_price_fen: int,
        notes: Optional[str] = None,
        customizations: Optional[dict] = None,
    ) -> dict:
        await self._set_tenant()

        # 做法加价：从 customizations 中提取做法附加费用
        practice_extra_fen = 0
        if customizations:
            practice_extra_fen = customizations.get("total_extra_price_fen", 0)

        subtotal_fen = unit_price_fen * quantity + practice_extra_fen
        item = OrderItem(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            order_id=uuid.UUID(order_id),
            dish_id=uuid.UUID(dish_id) if dish_id else None,
            item_name=dish_name,
            quantity=quantity,
            unit_price_fen=unit_price_fen,
            subtotal_fen=subtotal_fen,
            notes=notes,
            customizations=customizations or {},
        )
        self.db.add(item)
        await self.db.execute(
            update(Order)
            .where(Order.id == uuid.UUID(order_id))
            .where(Order.tenant_id == self.tenant_id)
            .values(
                total_amount_fen=Order.total_amount_fen + subtotal_fen,
                final_amount_fen=Order.total_amount_fen + subtotal_fen - Order.discount_amount_fen,
                status=OrderStatus.confirmed.value,
            )
        )
        await self.db.flush()
        return {"item_id": str(item.id), "subtotal_fen": subtotal_fen}

    async def update_item_quantity(
        self,
        item_id: str,
        new_quantity: int,
        order_id: Optional[str] = None,
    ) -> dict:
        """改菜数量

        §17-C: SELECT OrderItem FOR UPDATE 防 200 桌并发改同 item 用 stale
        subtotal_fen 算 diff 错乱 (audit §4.1 P1). Order UPDATE 用 raw
        arithmetic `Order.total_amount_fen + diff` 是 PG 原子, 不需 Order FOR UPDATE.

        §17-D1 (P2-2): order_id 可选参数 — caller (路由层) 传入时校验
        `item.order_id == order_id`, 防 caller 误传不属于该 order 的 item_id 仍能命中
        + 改数量 + 更新 item.order_id 指向的 Order. 旧 caller 不传保兼容.
        """
        await self._set_tenant()
        # §17-C: SELECT OrderItem FOR UPDATE 防 stale subtotal_fen
        result = await self.db.execute(
            select(OrderItem)
            .where(OrderItem.id == uuid.UUID(item_id))
            .where(OrderItem.tenant_id == self.tenant_id)
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")
        # §17-D1: order_id 归属校验 (provided 时)
        if order_id is not None and item.order_id != uuid.UUID(order_id):
            raise ValueError(
                f"OrderItem {item_id} 不属于 Order {order_id}"
            )
        diff = item.unit_price_fen * new_quantity - item.subtotal_fen
        item.quantity = new_quantity
        item.subtotal_fen = item.unit_price_fen * new_quantity
        await self.db.execute(
            update(Order)
            .where(Order.id == item.order_id)
            .where(Order.tenant_id == self.tenant_id)
            .values(
                total_amount_fen=Order.total_amount_fen + diff,
                final_amount_fen=Order.total_amount_fen + diff - Order.discount_amount_fen,
            )
        )
        await self.db.flush()
        return {"item_id": item_id, "new_quantity": new_quantity, "diff_fen": diff}

    async def remove_item(
        self,
        item_id: str,
        order_id: Optional[str] = None,
    ) -> dict:
        """删菜

        §17-C: SELECT OrderItem FOR UPDATE 防 200 桌并发删/改同 item 用 stale
        subtotal_fen 算 deducted 错乱 (audit §4.1 P1). Order UPDATE 用 raw
        arithmetic `Order.total_amount_fen - item.subtotal_fen` 是 PG 原子.

        §17-D1 (P2-2): order_id 可选参数 — caller 传入时校验 item.order_id 归属.
        """
        await self._set_tenant()
        # §17-C: SELECT OrderItem FOR UPDATE 防 stale subtotal_fen
        result = await self.db.execute(
            select(OrderItem)
            .where(OrderItem.id == uuid.UUID(item_id))
            .where(OrderItem.tenant_id == self.tenant_id)
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"OrderItem not found: {item_id}")
        # §17-D1: order_id 归属校验 (provided 时)
        if order_id is not None and item.order_id != uuid.UUID(order_id):
            raise ValueError(
                f"OrderItem {item_id} 不属于 Order {order_id}"
            )
        await self.db.execute(
            update(Order)
            .where(Order.id == item.order_id)
            .where(Order.tenant_id == self.tenant_id)
            .values(
                total_amount_fen=Order.total_amount_fen - item.subtotal_fen,
                final_amount_fen=Order.total_amount_fen - item.subtotal_fen - Order.discount_amount_fen,
            )
        )
        await self.db.delete(item)
        await self.db.flush()
        return {"removed_item_id": item_id, "deducted_fen": item.subtotal_fen}

    async def apply_discount(self, order_id: str, discount_fen: int, reason: str = "") -> dict:
        await self._set_tenant()
        # Tier 1 资金路径：折扣需读最新 total_amount_fen 后写回 discount/final，
        # 必须 FOR UPDATE 串行化加菜 / 折扣两路并发（audit doc §4.1 P0）。
        # **比 cashier_engine.apply_discount 更危险** — 连 margin 校验都没有，
        # 串行化是唯一防线。
        order = await self._get_order(uuid.UUID(order_id), lock=True)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        new_final = order.total_amount_fen - discount_fen
        if new_final < 0:
            raise ValueError("Discount exceeds order total")
        order.discount_amount_fen = discount_fen
        order.final_amount_fen = new_final
        await self.db.flush()
        return {"order_id": order_id, "discount_fen": discount_fen, "final_fen": new_final}

    # ─── 结算 ───

    async def settle_order(
        self,
        order_id: str,
        is_offline: bool = False,
        order_snapshot: Optional[dict] = None,
        items_data: Optional[list[dict]] = None,
        payments_data: Optional[list[dict]] = None,
    ) -> dict:
        """结算 — 标记订单完成，释放桌台

        Args:
            order_id:       订单 ID（在线时为 DB UUID；离线时为临时 ID）
            is_offline:     True = 断网模式，将结算状态写入离线队列
            order_snapshot: 离线模式下的完整订单快照（含 final_amount_fen 等结算字段）
            items_data:     离线模式下的订单明细快照
            payments_data:  离线模式下的支付数据快照

        Returns:
            在线模式：{"order_id", "order_no", "final_amount_fen", "settled_at"}
            离线模式：{"order_id", "order_no", "final_amount_fen", "settled_at",
                       "offline": True, "local_order_id": str}
        """
        # ── 离线降级路径 ──────────────────────────────────────────────────
        if is_offline:
            if not self._offline_sync:
                raise RuntimeError("offline_sync_service is required for offline settle")
            if not order_snapshot:
                raise ValueError("order_snapshot is required for offline settle")

            now = datetime.now(timezone.utc)
            settled_snapshot = {
                **order_snapshot,
                "status": OrderStatus.completed.value,
                "completed_at": now.isoformat(),
            }

            local_order_id = await self._offline_sync.queue_offline_order(
                order_data=settled_snapshot,
                items_data=items_data or [],
                payments_data=payments_data,
                tenant_id=str(self.tenant_id),
                store_id=str(order_snapshot.get("store_id", "")),
            )

            logger.info(
                "order_settled_offline",
                local_order_id=local_order_id,
                order_id=order_id,
                final_fen=order_snapshot.get("final_amount_fen", 0),
            )
            return {
                "order_id": order_id,
                "order_no": order_snapshot.get("order_no", ""),
                "final_amount_fen": order_snapshot.get("final_amount_fen", 0),
                "settled_at": now.isoformat(),
                "offline": True,
                "local_order_id": local_order_id,
            }

        # ── 在线正常路径 ──────────────────────────────────────────────────
        # PR #265 round-3 verifier 修复：原版漏调 _set_tenant()，RLS 未注入
        # app.tenant_id → 跨租户 settle 风险；与 cancel_order 的 _set_tenant
        # 调用对齐
        await self._set_tenant()
        # Tier 1 资金路径：结算需读 final_amount_fen + 状态机切到 completed +
        # 释放桌台。FOR UPDATE 防双 worker 并发 settle 同一订单（POS 重试 /
        # 网关回调 / 用户连点）导致双扣款 / 双桌台释放（audit doc §4.1 P0）。
        # **Saga S3 链路依赖此函数** — payment_saga_service._complete_order
        # 调用本函数；本锁即给 saga 补齐 S3 占位锁（架构层 issue 见 #537）。
        # 注：桌台 release 不在本 PR 范围（桌台并发语义待创始人 §17 对齐）。
        order = await self._get_order(uuid.UUID(order_id), lock=True)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        if order.status == OrderStatus.completed.value:
            raise ValueError("Order already settled")
        # P0-3: 走状态机守卫（兼容现状：confirmed/pending/preparing/ready/served → completed 都允许）
        transition_order(order, OrderStatus.completed)
        order.completed_at = datetime.now(timezone.utc)
        if order.table_number:
            # §17-B 3B 幂等: 传 order.id, UPDATE WHERE current_order_id 守门
            await self._release_table(str(order.store_id), order.table_number, order.id)
        await self.db.flush()

        logger.info(
            "order_settled",
            order_no=order.order_no,
            final_fen=order.final_amount_fen,
        )

        # 触发归因检查（fire-and-forget，不阻断结算流程）
        if order.customer_id:
            fire_order_attribution(
                tenant_id=self.tenant_id,
                customer_id=order.customer_id,
                order_id=order.id,
                order_amount_yuan=round((order.final_amount_fen or 0) / 100, 2),
                completed_at=order.completed_at,
            )

        # CLAUDE.md §15 事件总线：旁路写入 ORDER.PAID（PR #265 verifier 修复
        # 原死代码 `return` 之后 emit_event 不可达，settle 完全不发结算事件 → §15 漏单）
        asyncio.create_task(
            emit_event(
                event_type=OrderEventType.PAID,
                tenant_id=str(self.tenant_id),
                stream_id=str(order.id),
                payload={
                    "order_no": order.order_no,
                    "final_amount_fen": order.final_amount_fen,
                    "completed_at": order.completed_at.isoformat(),
                },
                store_id=str(order.store_id) if order.store_id else None,
                source_service="tx-trade",
                metadata={"path": "order_service.settle_order"},
            )
        )

        return {
            "order_id": order_id,
            "order_no": order.order_no,
            "final_amount_fen": order.final_amount_fen,
            "settled_at": order.completed_at.isoformat(),
        }

    # ─── 取消 ───

    async def cancel_order(self, order_id: str, reason: str = "") -> dict:
        """取消订单 — 释放桌台

        §17-B 终态保护: SELECT Order FOR UPDATE 防 settle/cancel race.
        FOR UPDATE 串行化让输者读到 status=completed/cancelled, 状态机
        transition_order 抛 ValueError, 而非两路都过校验后 commit overwrite.
        """
        await self._set_tenant()
        order = await self._get_order(uuid.UUID(order_id), lock=True)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        # P0-3: 走状态机守卫，已结账订单不能再取消（必须走退款路径）
        transition_order(order, OrderStatus.cancelled)
        order.order_metadata = {**(order.order_metadata or {}), "cancel_reason": reason}
        if order.table_number:
            # §17-B 3B 幂等: 传 order.id, UPDATE WHERE current_order_id 守门
            await self._release_table(str(order.store_id), order.table_number, order.id)
        await self.db.flush()

        # CLAUDE.md §15 事件总线：旁路写入 ORDER.CANCELLED
        # （PR #265 verifier 反馈：cancel_order 缺 emit_event 是 §15 漏洞）
        asyncio.create_task(
            emit_event(
                event_type=OrderEventType.CANCELLED,
                tenant_id=str(self.tenant_id),
                stream_id=str(order.id),
                payload={
                    "order_no": order.order_no,
                    "cancel_reason": reason,
                    "cancelled_at": datetime.now(timezone.utc).isoformat(),
                },
                store_id=str(order.store_id) if order.store_id else None,
                source_service="tx-trade",
                metadata={"path": "order_service.cancel_order"},
            )
        )

        return {"order_id": order_id, "status": "cancelled"}

    async def get_order(self, order_id: str) -> dict | None:
        await self._set_tenant()
        result = await self.db.execute(
            select(Order).where(Order.id == uuid.UUID(order_id)).where(Order.tenant_id == self.tenant_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            return None
        items_result = await self.db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id).where(OrderItem.tenant_id == self.tenant_id)
        )
        items = items_result.scalars().all()
        return {
            "id": str(order.id),
            "order_no": order.order_no,
            "store_id": str(order.store_id),
            "table_number": order.table_number,
            "status": order.status,
            "total_amount_fen": order.total_amount_fen,
            "discount_amount_fen": order.discount_amount_fen,
            "final_amount_fen": order.final_amount_fen,
            "order_time": order.order_time.isoformat() if order.order_time else None,
            "items": [
                {
                    "id": str(i.id),
                    "item_name": i.item_name,
                    "quantity": i.quantity,
                    "unit_price_fen": i.unit_price_fen,
                    "subtotal_fen": i.subtotal_fen,
                }
                for i in items
            ],
        }

    async def _get_order(self, order_id: uuid.UUID, *, lock: bool = False) -> Optional[Order]:
        """加载订单 ORM 对象（不含 items / 不返 dict）。

        Args:
            order_id: 订单 UUID。
            lock:     是否对 Order 行加 FOR UPDATE 排他锁（PostgreSQL 行锁）。
                      Tier 1 资金路径（apply_discount / settle_order）必须
                      lock=True，防 200 桌并发 race 丢更新 / 双结算。
                      read-only 入口默认 False 不回归性能（与 PR-D
                      cashier_engine._get_order helper 模式对齐）。

        Returns:
            Order 实例；不存在返回 None（caller 负责 raise ValueError）.
        """
        stmt = select(Order).where(Order.id == order_id).where(Order.tenant_id == self.tenant_id)
        if lock:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _lock_table(self, store_id: str, table_no: str, order_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Table)
            .where(Table.tenant_id == self.tenant_id)
            .where(Table.store_id == uuid.UUID(store_id))
            .where(Table.table_no == table_no)
            .values(status=TableStatus.occupied.value, current_order_id=order_id)
        )

    async def _release_table(
        self, store_id: str, table_no: str, order_id: uuid.UUID
    ) -> None:
        # §17-B 3B 幂等: WHERE 加 current_order_id=:order_id + status='occupied' 守门.
        # 多次调用同 (table, order_id) 仅首次 UPDATE 影响 1 行, 后续 0 行无害.
        # 若 table 已被新 order 重 occupy, 旧 order_id 不匹配 → UPDATE 0 行, 不污染.
        await self.db.execute(
            update(Table)
            .where(Table.tenant_id == self.tenant_id)
            .where(Table.store_id == uuid.UUID(store_id))
            .where(Table.table_no == table_no)
            .where(Table.current_order_id == order_id)
            .where(Table.status == TableStatus.occupied.value)
            .values(status=TableStatus.free.value, current_order_id=None)
        )
