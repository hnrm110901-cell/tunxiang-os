"""外卖订单 Repository — 封装 delivery_orders 和 delivery_auto_accept_rules 的所有 DB 操作

架构约束：
  - 所有方法接受 AsyncSession，由路由层通过 Depends(get_db) 注入
  - 不直接 import 路由层任何模块（单向依赖）
  - 金额字段统一使用 int（分），严禁 float
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.delivery_auto_accept_rule import DeliveryAutoAcceptRule
from ..models.delivery_order import DeliveryOrder as DeliveryOrderModel

logger = structlog.get_logger(__name__)

# 活跃状态：用于统计并发单量
_ACTIVE_STATUSES = ("pending_accept", "accepted", "preparing")

# 终态：对账任务只扫这些状态，避免与进行中单混淆
_TERMINAL_STATUSES = ("completed", "cancelled", "refunded")


class DeliveryOrderRepository:
    """外卖订单持久化操作"""

    # ─── 查询 ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        order_id: UUID,
        tenant_id: UUID,
    ) -> Optional[DeliveryOrderModel]:
        """按 ID 查单条订单（已过滤软删除）"""
        stmt = select(DeliveryOrderModel).where(
            and_(
                DeliveryOrderModel.id == order_id,
                DeliveryOrderModel.tenant_id == tenant_id,
                DeliveryOrderModel.is_deleted.is_(False),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_platform_order_id(
        db: AsyncSession,
        platform: str,
        platform_order_id: str,
        tenant_id: UUID,
    ) -> Optional[DeliveryOrderModel]:
        """按平台订单号查询（防重复入库）"""
        stmt = select(DeliveryOrderModel).where(
            and_(
                DeliveryOrderModel.platform == platform,
                DeliveryOrderModel.platform_order_id == platform_order_id,
                DeliveryOrderModel.tenant_id == tenant_id,
                DeliveryOrderModel.is_deleted.is_(False),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_orders(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        store_id: Optional[UUID] = None,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        target_date: Optional[date] = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DeliveryOrderModel], int]:
        """分页查询外卖订单，支持门店/平台/状态/日期筛选。

        Returns:
            (items, total)
        """
        conditions = [
            DeliveryOrderModel.tenant_id == tenant_id,
            DeliveryOrderModel.is_deleted.is_(False),
        ]
        if store_id is not None:
            conditions.append(DeliveryOrderModel.store_id == store_id)
        if platform is not None:
            conditions.append(DeliveryOrderModel.platform == platform)
        if status is not None:
            conditions.append(DeliveryOrderModel.status == status)
        if target_date is not None:
            conditions.append(func.date(DeliveryOrderModel.created_at) == target_date)

        count_stmt = select(func.count()).select_from(DeliveryOrderModel).where(and_(*conditions))
        total: int = (await db.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(DeliveryOrderModel)
            .where(and_(*conditions))
            .order_by(DeliveryOrderModel.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await db.execute(data_stmt)).scalars().all()
        return list(rows), total

    @staticmethod
    async def count_active_orders(
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
    ) -> int:
        """统计当前活跃（待接/接单/备餐）订单数量，用于自动接单并发限制"""
        stmt = (
            select(func.count())
            .select_from(DeliveryOrderModel)
            .where(
                and_(
                    DeliveryOrderModel.store_id == store_id,
                    DeliveryOrderModel.tenant_id == tenant_id,
                    DeliveryOrderModel.status.in_(_ACTIVE_STATUSES),
                    DeliveryOrderModel.is_deleted.is_(False),
                )
            )
        )
        return (await db.execute(stmt)).scalar_one()

    @staticmethod
    async def get_daily_stats_by_platform(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        target_date: date,
    ) -> list[dict]:
        """按平台聚合日统计：订单数/营收/佣金/实收"""
        stmt = (
            select(
                DeliveryOrderModel.platform,
                func.count().label("order_count"),
                func.sum(DeliveryOrderModel.total_fen).label("revenue_fen"),
                func.sum(DeliveryOrderModel.commission_fen).label("commission_fen"),
                func.sum(DeliveryOrderModel.merchant_receive_fen).label("net_revenue_fen"),
            )
            .where(
                and_(
                    DeliveryOrderModel.tenant_id == tenant_id,
                    DeliveryOrderModel.store_id == store_id,
                    func.date(DeliveryOrderModel.created_at) == target_date,
                    DeliveryOrderModel.status.notin_(("cancelled", "rejected")),
                    DeliveryOrderModel.is_deleted.is_(False),
                )
            )
            .group_by(DeliveryOrderModel.platform)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "platform": r.platform,
                "order_count": r.order_count,
                "revenue_fen": r.revenue_fen or 0,
                "commission_fen": r.commission_fen or 0,
                "net_revenue_fen": r.net_revenue_fen or 0,
            }
            for r in rows
        ]

    @staticmethod
    def _amount_variance_condition():
        """实际到账与商户实收不一致，或 total-commission 与 merchant_receive 不一致。"""
        net_expr = DeliveryOrderModel.total_fen - DeliveryOrderModel.commission_fen
        return or_(
            and_(
                DeliveryOrderModel.actual_revenue_fen.isnot(None),
                DeliveryOrderModel.actual_revenue_fen != DeliveryOrderModel.merchant_receive_fen,
            ),
            net_expr != DeliveryOrderModel.merchant_receive_fen,
        )

    @staticmethod
    def _reconciliation_base_conditions(
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        *,
        store_id: Optional[UUID] = None,
        platform: Optional[str] = None,
    ) -> list:
        conds = [
            DeliveryOrderModel.tenant_id == tenant_id,
            DeliveryOrderModel.is_deleted.is_(False),
            DeliveryOrderModel.status.in_(_TERMINAL_STATUSES),
            func.date(DeliveryOrderModel.created_at) >= date_from,
            func.date(DeliveryOrderModel.created_at) <= date_to,
        ]
        if store_id is not None:
            conds.append(DeliveryOrderModel.store_id == store_id)
        if platform is not None:
            conds.append(DeliveryOrderModel.platform == platform)
        return conds

    @staticmethod
    async def list_reconciliation_candidates(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        date_from: date,
        date_to: date,
        store_id: Optional[UUID] = None,
        platform: Optional[str] = None,
        issue_type: str = "any",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DeliveryOrderModel], int]:
        """外卖对账候选单（Y-A5 骨架）：终态单 + 日期范围内 + 异常条件。

        issue_type:
          - any: 未关联内部订单 **或** 金额口径不一致
          - unlink: 仅 internal_order_id 为空
          - amount: 仅金额口径疑似不一致
        """
        base = DeliveryOrderRepository._reconciliation_base_conditions(
            tenant_id, date_from, date_to, store_id=store_id, platform=platform
        )
        unlink = DeliveryOrderModel.internal_order_id.is_(None)
        amt = DeliveryOrderRepository._amount_variance_condition()
        if issue_type == "unlink":
            base.append(unlink)
        elif issue_type == "amount":
            base.append(amt)
        else:
            base.append(or_(unlink, amt))

        where = and_(*base)
        count_stmt = select(func.count()).select_from(DeliveryOrderModel).where(where)
        total: int = (await db.execute(count_stmt)).scalar_one()

        data_stmt = (
            select(DeliveryOrderModel)
            .where(where)
            .order_by(DeliveryOrderModel.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        rows = (await db.execute(data_stmt)).scalars().all()
        return list(rows), total

    @staticmethod
    async def reconciliation_summary(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        date_from: date,
        date_to: date,
        store_id: Optional[UUID] = None,
        platform: Optional[str] = None,
    ) -> dict:
        """对账看板计数（同一单可同时计入 unlink 与 amount）。"""
        base = DeliveryOrderRepository._reconciliation_base_conditions(
            tenant_id, date_from, date_to, store_id=store_id, platform=platform
        )
        unlink = DeliveryOrderModel.internal_order_id.is_(None)
        amt = DeliveryOrderRepository._amount_variance_condition()

        async def _cnt(extra) -> int:
            w = and_(*base, extra)
            stmt = select(func.count()).select_from(DeliveryOrderModel).where(w)
            return int((await db.execute(stmt)).scalar_one())

        unlink_n = await _cnt(unlink)
        amount_n = await _cnt(amt)
        candidates_n = await _cnt(or_(unlink, amt))
        return {
            "candidates_total": candidates_n,
            "unlink_count": unlink_n,
            "amount_variance_count": amount_n,
        }

    @staticmethod
    async def find_internal_order_id_by_omni_platform_order(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        platform: str,
        platform_order_id: str,
    ) -> Optional[UUID]:
        """根据 omni 落库元数据匹配 ``orders.id``（用于未关联 ``internal_order_id`` 的补偿建议）。

        先按 ``sales_channel_id == platform`` + ``order_metadata.omni.platform_order_id`` 精确匹配；
        若无唯一命中，再放宽为仅元数据平台单号（仍限同店同租户）。多行命中返回 None。
        """
        from shared.ontology.src.entities import Order as OrderModel

        base_conds = [
            OrderModel.tenant_id == tenant_id,
            OrderModel.store_id == store_id,
            OrderModel.is_deleted.is_(False),
            OrderModel.order_metadata["omni"]["platform_order_id"].astext == platform_order_id,
        ]

        stmt_strict = select(OrderModel.id).where(and_(*base_conds, OrderModel.sales_channel_id == platform)).limit(2)
        strict_rows = list((await db.execute(stmt_strict)).scalars().all())
        if len(strict_rows) == 1:
            return strict_rows[0]
        if len(strict_rows) > 1:
            return None

        stmt_relaxed = select(OrderModel.id).where(and_(*base_conds)).limit(2)
        relaxed_rows = list((await db.execute(stmt_relaxed)).scalars().all())
        if len(relaxed_rows) == 1:
            return relaxed_rows[0]
        return None

    @staticmethod
    async def link_delivery_to_internal_order(
        db: AsyncSession,
        *,
        delivery_order_id: UUID,
        tenant_id: UUID,
        internal_order_id: UUID,
    ) -> bool:
        """外卖单行写入 ``internal_order_id``。要求：外卖单存在、尚未关联、内部订单同租户且未删除。"""
        from shared.ontology.src.entities import Order as OrderModel

        delivery = await DeliveryOrderRepository.get_by_id(db, delivery_order_id, tenant_id)
        if delivery is None or delivery.internal_order_id is not None:
            return False

        o_stmt = select(OrderModel.id).where(
            and_(
                OrderModel.id == internal_order_id,
                OrderModel.tenant_id == tenant_id,
                OrderModel.is_deleted.is_(False),
            )
        )
        if (await db.execute(o_stmt)).scalar_one_or_none() is None:
            return False

        stmt = (
            update(DeliveryOrderModel)
            .where(
                and_(
                    DeliveryOrderModel.id == delivery_order_id,
                    DeliveryOrderModel.tenant_id == tenant_id,
                    DeliveryOrderModel.is_deleted.is_(False),
                    DeliveryOrderModel.internal_order_id.is_(None),
                )
            )
            .values(
                internal_order_id=internal_order_id,
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        return result.rowcount > 0

    # ─── 写入 ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: UUID,
        brand_id: str,
        platform: str,
        platform_name: str,
        platform_order_id: str,
        platform_order_no: Optional[str],
        sales_channel: str,
        status: str,
        items_json: list,
        total_fen: int,
        commission_rate: float,
        commission_fen: int,
        merchant_receive_fen: int,
        actual_revenue_fen: int,
        customer_name: Optional[str],
        customer_phone: Optional[str],
        delivery_address: Optional[str],
        expected_time: Optional[str],
        estimated_prep_time: Optional[int],
        special_request: Optional[str],
        notes: Optional[str],
        order_no: str,
    ) -> DeliveryOrderModel:
        """创建外卖订单记录"""
        order = DeliveryOrderModel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            brand_id=brand_id,
            platform=platform,
            platform_name=platform_name,
            platform_order_id=platform_order_id,
            platform_order_no=platform_order_no,
            sales_channel=sales_channel,
            status=status,
            items_json=items_json,
            total_fen=total_fen,
            commission_rate=commission_rate,
            commission_fen=commission_fen,
            merchant_receive_fen=merchant_receive_fen,
            actual_revenue_fen=actual_revenue_fen,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            expected_time=expected_time,
            estimated_ready_min=estimated_prep_time,
            estimated_prep_time=estimated_prep_time,
            special_request=special_request,
            notes=notes,
            order_no=order_no,
            auto_accepted=False,
        )
        db.add(order)
        await db.flush()
        await db.refresh(order)
        logger.info(
            "delivery_order_repo.create.ok",
            order_id=str(order.id),
            platform=platform,
            platform_order_id=platform_order_id,
        )
        return order

    @staticmethod
    async def update_status(
        db: AsyncSession,
        order_id: UUID,
        tenant_id: UUID,
        new_status: str,
        *,
        accepted_at: Optional[datetime] = None,
        rejected_at: Optional[datetime] = None,
        rejected_reason: Optional[str] = None,
        ready_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        cancelled_at: Optional[datetime] = None,
        cancel_reason: Optional[str] = None,
        auto_accepted: Optional[bool] = None,
        estimated_prep_time: Optional[int] = None,
    ) -> bool:
        """更新订单状态及相关时间戳。返回 True 表示更新成功（找到了记录）"""
        values: dict = {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
        }
        if accepted_at is not None:
            values["accepted_at"] = accepted_at
            values["confirmed_at"] = accepted_at  # 兼容旧字段
        if rejected_at is not None:
            values["rejected_at"] = rejected_at
        if rejected_reason is not None:
            values["rejected_reason"] = rejected_reason
            values["cancel_reason"] = rejected_reason  # 兼容旧字段
        if ready_at is not None:
            values["ready_at"] = ready_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at
        if cancel_reason is not None:
            values["cancel_reason"] = cancel_reason
        if auto_accepted is not None:
            values["auto_accepted"] = auto_accepted
        if estimated_prep_time is not None:
            values["estimated_ready_min"] = estimated_prep_time
            values["estimated_prep_time"] = estimated_prep_time

        stmt = (
            update(DeliveryOrderModel)
            .where(
                and_(
                    DeliveryOrderModel.id == order_id,
                    DeliveryOrderModel.tenant_id == tenant_id,
                    DeliveryOrderModel.is_deleted.is_(False),
                )
            )
            .values(**values)
        )
        result = await db.execute(stmt)
        return result.rowcount > 0


class DeliveryAutoAcceptRuleRepository:
    """自动接单规则持久化操作"""

    @staticmethod
    async def get_by_store(
        db: AsyncSession,
        store_id: UUID,
        tenant_id: UUID,
    ) -> Optional[DeliveryAutoAcceptRule]:
        """获取门店自动接单规则（可为 None，表示未配置）"""
        stmt = select(DeliveryAutoAcceptRule).where(
            and_(
                DeliveryAutoAcceptRule.store_id == store_id,
                DeliveryAutoAcceptRule.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        *,
        is_enabled: Optional[bool] = None,
        business_hours_start=None,
        business_hours_end=None,
        max_concurrent_orders: Optional[int] = None,
        excluded_platforms: Optional[list] = None,
    ) -> DeliveryAutoAcceptRule:
        """创建或更新自动接单规则"""
        existing = await DeliveryAutoAcceptRuleRepository.get_by_store(db, store_id, tenant_id)
        if existing is None:
            rule = DeliveryAutoAcceptRule(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                store_id=store_id,
                is_enabled=is_enabled if is_enabled is not None else False,
                business_hours_start=business_hours_start,
                business_hours_end=business_hours_end,
                max_concurrent_orders=max_concurrent_orders if max_concurrent_orders is not None else 10,
                excluded_platforms=excluded_platforms if excluded_platforms is not None else [],
            )
            db.add(rule)
            await db.flush()
            await db.refresh(rule)
            return rule

        # 更新现有
        if is_enabled is not None:
            existing.is_enabled = is_enabled
        if business_hours_start is not None:
            existing.business_hours_start = business_hours_start
        if business_hours_end is not None:
            existing.business_hours_end = business_hours_end
        if max_concurrent_orders is not None:
            existing.max_concurrent_orders = max_concurrent_orders
        if excluded_platforms is not None:
            existing.excluded_platforms = excluded_platforms
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(existing)
        return existing
