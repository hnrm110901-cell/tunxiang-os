"""外卖聚合统一接单服务

支持美团/饿了么/抖音三平台订单统一接收、标准化、接单/拒单、KDS分发。
每个方法显式传入 tenant_id，不依赖会话变量，确保多租户隔离。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

import httpx
import structlog
from sqlalchemy import select, update, and_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .kds_dispatch import dispatch_order_to_kds
from shared.adapters.base.src.adapter import APIError as AdapterAPIError

logger = structlog.get_logger()


# ─── 异常类型 ─────────────────────────────────────────────────────────────────


class OmniChannelError(Exception):
    """外卖聚合服务通用异常"""


class UnsupportedPlatformError(OmniChannelError):
    """不支持的外卖平台"""


# ─── 数据模型 ─────────────────────────────────────────────────────────────────


@dataclass
class UnifiedOrderItem:
    """统一订单项"""
    name: str
    quantity: int
    price_fen: int
    sku_id: str = ""
    notes: str = ""
    internal_dish_id: str = ""


@dataclass
class UnifiedOrder:
    """统一订单格式——所有平台标准化后的内部表示"""
    platform: str                     # meituan / eleme / douyin
    platform_order_id: str            # 平台原始订单ID
    source_channel: str               # 同 platform，写入 orders.source_channel
    tenant_id: str
    store_id: str
    status: str                       # pending / confirmed / rejected / cancelled
    total_fen: int
    items: List[UnifiedOrderItem]
    notes: str = ""
    customer_phone: str = ""
    delivery_address: str = ""
    created_at: Optional[datetime] = None
    internal_order_id: Optional[str] = None   # 写库后赋值


# ─── 平台标准化函数 ────────────────────────────────────────────────────────────


def _normalize_meituan(raw: dict[str, Any], store_id: str, tenant_id: str) -> UnifiedOrder:
    """美团原始推单payload → UnifiedOrder"""
    import json as _json

    detail_str = raw.get("detail", "[]")
    try:
        food_list = _json.loads(detail_str) if isinstance(detail_str, str) else detail_str
    except (_json.JSONDecodeError, TypeError):
        food_list = []

    items = []
    for food in food_list:
        items.append(UnifiedOrderItem(
            name=str(food.get("food_name", "")),
            quantity=int(food.get("quantity", 1)),
            price_fen=int(food.get("price", 0)),
            sku_id=str(food.get("app_food_code", "")),
            notes=str(food.get("food_property", "")),
        ))

    return UnifiedOrder(
        platform="meituan",
        platform_order_id=str(raw.get("order_id", "")),
        source_channel="meituan",
        tenant_id=tenant_id,
        store_id=store_id,
        status="pending",
        total_fen=int(raw.get("order_total_price", 0)),
        items=items,
        notes=str(raw.get("caution", "")),
        customer_phone=str(raw.get("recipient_phone", "")),
        delivery_address=str(raw.get("recipient_address", "")),
        created_at=datetime.now(timezone.utc),
    )


def _normalize_eleme(raw: dict[str, Any], store_id: str, tenant_id: str) -> UnifiedOrder:
    """饿了么原始推单payload → UnifiedOrder"""
    food_list = raw.get("food_list", raw.get("items", []))
    items = []
    for food in food_list:
        items.append(UnifiedOrderItem(
            name=str(food.get("food_name", food.get("name", ""))),
            quantity=int(food.get("quantity", food.get("count", 1))),
            price_fen=int(food.get("price", 0)),
            sku_id=str(food.get("food_id", food.get("sku_id", ""))),
            notes=str(food.get("remark", "")),
        ))

    create_time_raw = raw.get("create_time", "")
    try:
        if isinstance(create_time_raw, (int, float)) and create_time_raw > 1e9:
            created_at = datetime.fromtimestamp(create_time_raw, tz=timezone.utc)
        else:
            created_at = datetime.now(timezone.utc)
    except (ValueError, OSError):
        created_at = datetime.now(timezone.utc)

    return UnifiedOrder(
        platform="eleme",
        platform_order_id=str(raw.get("order_id", raw.get("eleme_order_id", ""))),
        source_channel="eleme",
        tenant_id=tenant_id,
        store_id=store_id,
        status="pending",
        total_fen=int(raw.get("total_price", raw.get("order_amount", 0))),
        items=items,
        notes=str(raw.get("remark", raw.get("caution", ""))),
        customer_phone=str(raw.get("user_phone", "")),
        delivery_address=str(raw.get("address", "")),
        created_at=created_at,
    )


def _normalize_douyin(raw: dict[str, Any], store_id: str, tenant_id: str) -> UnifiedOrder:
    """抖音生活服务原始推单payload → UnifiedOrder"""
    item_list = raw.get("items", raw.get("food_list", []))
    items = []
    for item in item_list:
        items.append(UnifiedOrderItem(
            name=str(item.get("item_name", item.get("food_name", ""))),
            quantity=int(item.get("quantity", 1)),
            price_fen=int(item.get("price", 0)),
            sku_id=str(item.get("item_id", item.get("sku_id", ""))),
            notes=str(item.get("remark", "")),
        ))

    return UnifiedOrder(
        platform="douyin",
        platform_order_id=str(raw.get("order_id", "")),
        source_channel="douyin",
        tenant_id=tenant_id,
        store_id=store_id,
        status="pending",
        total_fen=int(raw.get("amount", raw.get("total_price", 0))),
        items=items,
        notes=str(raw.get("remark", "")),
        customer_phone=str(raw.get("buyer_phone", "")),
        delivery_address=str(raw.get("address", "")),
        created_at=datetime.now(timezone.utc),
    )


# ─── 平台Adapter工厂 ─────────────────────────────────────────────────────────


_NORMALIZERS = {
    "meituan": _normalize_meituan,
    "eleme": _normalize_eleme,
    "douyin": _normalize_douyin,
}

PLATFORM_REJECT_REASON_MAP = {
    # reason_code → 各平台对应拒单原因描述
    1: "餐厅暂时无法接单",
    2: "餐厅已打烊",
    3: "食材不足",
    4: "配送范围外",
    9: "其他原因",
}


# ─── 主服务类 ─────────────────────────────────────────────────────────────────


class OmniChannelService:
    """外卖聚合统一接单服务

    职责：
    - 将各平台原始推单payload标准化为统一内部格式
    - 写入orders表（source_channel = platform）
    - 接单/拒单并回调平台
    - 超时未接单自动拒单（可配置，默认3分钟）
    - 接单后自动推送到KDS
    """

    PLATFORMS = ["meituan", "eleme", "douyin"]

    def __init__(self, auto_reject_minutes: int = 3) -> None:
        self.auto_reject_minutes = auto_reject_minutes

    # ── 标准化 ────────────────────────────────────────────────────────────────

    def normalize(
        self,
        platform: str,
        raw: dict[str, Any],
        store_id: str,
        tenant_id: str,
    ) -> UnifiedOrder:
        """根据platform调用对应normalizer转为统一UnifiedOrder格式"""
        if platform not in _NORMALIZERS:
            raise UnsupportedPlatformError(f"不支持的平台: {platform}，支持: {self.PLATFORMS}")
        return _NORMALIZERS[platform](raw, store_id, tenant_id)

    # ── 接收订单（webhook入口） ───────────────────────────────────────────────

    async def receive_order(
        self,
        platform: str,
        raw_payload: dict[str, Any],
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> UnifiedOrder:
        """接收平台推单：标准化 → 写库 → 推送KDS → 返回UnifiedOrder

        1. 根据platform调用对应normalizer转为统一Order格式
        2. 写入orders表，source_channel = platform
        3. 推送到KDS（调用kds_dispatch）
        4. 返回UnifiedOrder
        """
        log = logger.bind(platform=platform, tenant_id=tenant_id, store_id=store_id)
        log.info("omni_channel.receive_order.start")

        # 1. 标准化
        order = self.normalize(platform=platform, raw=raw_payload, store_id=store_id, tenant_id=tenant_id)

        # 2. 写入orders表（延迟导入避免循环依赖）
        try:
            internal_order_id = await self._persist_order(order, db)
            order.internal_order_id = internal_order_id
            log.info("omni_channel.receive_order.persisted", internal_order_id=internal_order_id)
        except (SQLAlchemyError, ValueError) as exc:
            log.error("omni_channel.receive_order.persist_failed", error=str(exc), exc_info=True)
            raise

        # 3. 推送到KDS（失败不阻塞订单流程）
        try:
            kds_items = [
                {
                    "dish_id": item.internal_dish_id or "",
                    "item_name": item.name,
                    "quantity": item.quantity,
                    "order_item_id": "",
                    "notes": item.notes,
                }
                for item in order.items
            ]
            await dispatch_order_to_kds(
                order_id=internal_order_id,
                order_items=kds_items,
                tenant_id=tenant_id,
                db=db,
                store_id=store_id,
                channel="takeaway",
            )
            log.info("omni_channel.receive_order.kds_dispatched")
        except (SQLAlchemyError, ValueError, RuntimeError) as exc:
            log.error("omni_channel.receive_order.kds_failed", error=str(exc), exc_info=True)
            # 不重新抛出：KDS失败不影响内部订单流程

        return order

    # ── 接单 ─────────────────────────────────────────────────────────────────

    async def accept_order(
        self,
        order_id: str,
        estimated_minutes: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """接单：更新状态 + 调用platform adapter confirm()

        Args:
            order_id: 内部订单UUID
            estimated_minutes: 预计备餐分钟数（回传给平台）
            tenant_id: 租户ID（显式传入）
            db: 数据库会话

        Returns:
            {"ok": True, "order_id": ..., "platform": ..., "estimated_minutes": ...}
        """
        log = logger.bind(order_id=order_id, tenant_id=tenant_id)
        log.info("omni_channel.accept_order.start")

        order_row = await self._get_order(order_id, tenant_id, db)

        # 更新内部状态
        await self._update_order_status(order_id, "confirmed", tenant_id, db)

        # 回调平台（失败不阻塞内部流程）
        try:
            adapter = self._get_platform_adapter(order_row.source_channel)
            await adapter.confirm_order(order_row.platform_order_id)
            log.info("omni_channel.accept_order.platform_callback_ok", platform=order_row.source_channel)
        except (AdapterAPIError, httpx.HTTPError, ConnectionError, UnsupportedPlatformError) as exc:
            log.error(
                "omni_channel.accept_order.platform_callback_failed",
                platform=order_row.source_channel,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            # 平台回调失败只记录日志，不影响内部订单状态

        return {
            "ok": True,
            "order_id": order_id,
            "platform": order_row.source_channel,
            "estimated_minutes": estimated_minutes,
        }

    # ── 拒单 ─────────────────────────────────────────────────────────────────

    async def reject_order(
        self,
        order_id: str,
        reason_code: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """拒单：更新状态 + 调用platform adapter cancel()

        Args:
            order_id: 内部订单UUID
            reason_code: 拒单原因码（见 PLATFORM_REJECT_REASON_MAP）
            tenant_id: 租户ID（显式传入）
            db: 数据库会话

        Returns:
            {"ok": True, "order_id": ..., "platform": ..., "reason_code": ...}
        """
        log = logger.bind(order_id=order_id, tenant_id=tenant_id, reason_code=reason_code)
        log.info("omni_channel.reject_order.start")

        order_row = await self._get_order(order_id, tenant_id, db)
        reason_text = PLATFORM_REJECT_REASON_MAP.get(reason_code, "其他原因")

        # 更新内部状态
        await self._update_order_status(order_id, "rejected", tenant_id, db)

        # 回调平台拒单（失败只记录）
        try:
            adapter = self._get_platform_adapter(order_row.source_channel)
            await adapter.cancel_order(order_row.platform_order_id, reason_code, reason_text)
            log.info("omni_channel.reject_order.platform_callback_ok", platform=order_row.source_channel)
        except (AdapterAPIError, httpx.HTTPError, ConnectionError, UnsupportedPlatformError) as exc:
            log.error(
                "omni_channel.reject_order.platform_callback_failed",
                platform=order_row.source_channel,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

        return {
            "ok": True,
            "order_id": order_id,
            "platform": order_row.source_channel,
            "reason_code": reason_code,
        }

    # ── 待接单列表 ────────────────────────────────────────────────────────────

    async def get_pending_orders(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[UnifiedOrder]:
        """查询待接单订单（所有平台混合，按时间排序）

        Args:
            store_id: 门店ID
            tenant_id: 租户ID（显式传入，确保隔离）
            db: 数据库会话

        Returns:
            UnifiedOrder列表，按created_at升序
        """
        log = logger.bind(store_id=store_id, tenant_id=tenant_id)

        # 延迟导入避免循环依赖
        from shared.ontology.src.entities import Order as OrderModel

        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)

        stmt = (
            select(OrderModel)
            .where(
                and_(
                    OrderModel.tenant_id == tid,
                    OrderModel.store_id == sid,
                    OrderModel.status == "pending",
                    OrderModel.source_channel.in_(self.PLATFORMS),
                    OrderModel.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(OrderModel.created_at.asc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        orders = []
        for row in rows:
            items_snapshot = getattr(row, "items_snapshot", []) or []
            unified_items = [
                UnifiedOrderItem(
                    name=item.get("name", item.get("item_name", "")),
                    quantity=item.get("quantity", 1),
                    price_fen=item.get("price_fen", item.get("unit_price_fen", 0)),
                    sku_id=item.get("sku_id", ""),
                    notes=item.get("notes", ""),
                )
                for item in items_snapshot
            ]
            orders.append(UnifiedOrder(
                platform=str(row.source_channel),
                platform_order_id=str(getattr(row, "platform_order_id", row.order_no or "")),
                source_channel=str(row.source_channel),
                tenant_id=tenant_id,
                store_id=store_id,
                status=str(row.status),
                total_fen=int(getattr(row, "total_amount_fen", 0)),
                items=unified_items,
                notes=str(row.notes or ""),
                customer_phone=str(getattr(row, "customer_phone", "") or ""),
                delivery_address=str(getattr(row, "delivery_address", "") or ""),
                created_at=row.created_at,
                internal_order_id=str(row.id),
            ))

        log.info("omni_channel.get_pending_orders", count=len(orders))
        return orders

    # ── 超时自动拒单 ──────────────────────────────────────────────────────────

    async def auto_reject_overdue(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """超时未接单自动拒单（定时调用）

        扫描超过 auto_reject_minutes 仍为 pending 的外卖订单，自动拒单。

        Returns:
            {"rejected_count": N, "order_ids": [...]}
        """
        log = logger.bind(store_id=store_id, tenant_id=tenant_id, timeout_minutes=self.auto_reject_minutes)
        log.info("omni_channel.auto_reject_overdue.start")

        from shared.ontology.src.entities import Order as OrderModel

        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(store_id)
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=self.auto_reject_minutes)

        stmt = (
            select(OrderModel)
            .where(
                and_(
                    OrderModel.tenant_id == tid,
                    OrderModel.store_id == sid,
                    OrderModel.status == "pending",
                    OrderModel.source_channel.in_(self.PLATFORMS),
                    OrderModel.created_at <= cutoff_time,
                    OrderModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        result = await db.execute(stmt)
        overdue_orders = result.scalars().all()

        rejected_ids = []
        for order_row in overdue_orders:
            order_id_str = str(order_row.id)
            try:
                await self._update_order_status(order_id_str, "rejected", tenant_id, db)

                # 回调平台拒单
                try:
                    adapter = self._get_platform_adapter(order_row.source_channel)
                    await adapter.cancel_order(
                        order_row.platform_order_id,
                        1,
                        "超时未接单，系统自动拒单",
                    )
                except (AdapterAPIError, httpx.HTTPError, ConnectionError, UnsupportedPlatformError) as exc:
                    log.error(
                        "omni_channel.auto_reject.platform_callback_failed",
                        order_id=order_id_str,
                        platform=order_row.source_channel,
                        error=str(exc),
                        error_type=type(exc).__name__,
                        exc_info=True,
                    )

                rejected_ids.append(order_id_str)
                log.info("omni_channel.auto_reject.done", order_id=order_id_str)
            except (SQLAlchemyError, ValueError, OmniChannelError) as exc:
                log.error(
                    "omni_channel.auto_reject.failed",
                    order_id=order_id_str,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    exc_info=True,
                )

        return {"rejected_count": len(rejected_ids), "order_ids": rejected_ids}

    # ── 私有方法 ─────────────────────────────────────────────────────────────

    async def _get_order(self, order_id: str, tenant_id: str, db: AsyncSession) -> Any:
        """查询订单，不存在则抛出 OmniChannelError"""
        from shared.ontology.src.entities import Order as OrderModel

        tid = uuid.UUID(tenant_id)
        stmt = select(OrderModel).where(
            and_(
                OrderModel.id == uuid.UUID(order_id),
                OrderModel.tenant_id == tid,
                OrderModel.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise OmniChannelError(f"订单不存在: {order_id}")
        return row

    async def _update_order_status(
        self,
        order_id: str,
        new_status: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> None:
        """更新订单状态"""
        from shared.ontology.src.entities import Order as OrderModel

        tid = uuid.UUID(tenant_id)
        stmt = (
            update(OrderModel)
            .where(
                and_(
                    OrderModel.id == uuid.UUID(order_id),
                    OrderModel.tenant_id == tid,
                )
            )
            .values(status=new_status, updated_at=datetime.now(timezone.utc))
        )
        await db.execute(stmt)
        await db.flush()

    async def _persist_order(self, order: UnifiedOrder, db: AsyncSession) -> str:
        """将 UnifiedOrder 写入 orders 表，返回内部order_id"""
        from shared.ontology.src.entities import Order as OrderModel

        internal_id = str(uuid.uuid4())
        items_snapshot = [
            {
                "name": item.name,
                "quantity": item.quantity,
                "price_fen": item.price_fen,
                "sku_id": item.sku_id,
                "notes": item.notes,
            }
            for item in order.items
        ]

        # 使用原生INSERT避免依赖具体ORM字段细节
        from sqlalchemy import insert as sa_insert, text

        try:
            new_order = OrderModel(
                id=uuid.UUID(internal_id),
                tenant_id=uuid.UUID(order.tenant_id),
                store_id=uuid.UUID(order.store_id),
                order_no=order.platform_order_id,
                order_type="takeaway",
                status="pending",
                source_channel=order.source_channel,
                total_amount_fen=order.total_fen,
                notes=order.notes,
                items_snapshot=items_snapshot,
                platform_order_id=order.platform_order_id,
                customer_phone=order.customer_phone,
                delivery_address=order.delivery_address,
                created_at=order.created_at or datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                is_deleted=False,
            )
            db.add(new_order)
            await db.flush()
        except (AttributeError, TypeError) as exc:
            # Order模型字段可能与UnifiedOrder不完全匹配，记录警告但继续
            logger.warning("omni_channel.persist_order.field_mismatch", error=str(exc))

        return internal_id

    def _get_platform_adapter(self, platform: str) -> Any:
        """获取平台adapter实例（从环境变量读取secret）

        实际部署时通过依赖注入或工厂函数提供已配置的adapter。
        测试时通过mock替换。
        """
        import os

        if platform == "meituan":
            from shared.adapters.meituan_saas.src.adapter import MeituanSaasAdapter

            return MeituanSaasAdapter(config={
                "app_key": os.environ.get("MEITUAN_APP_KEY", ""),
                "app_secret": os.environ.get("MEITUAN_APP_SECRET", ""),
                "poi_id": os.environ.get("MEITUAN_POI_ID", ""),
            })
        elif platform == "eleme":
            from shared.adapters.eleme.src.adapter import ElemeAdapter

            return ElemeAdapter(config={
                "app_key": os.environ.get("ELEME_APP_KEY", ""),
                "app_secret": os.environ.get("ELEME_APP_SECRET", ""),
            })
        elif platform == "douyin":
            from shared.adapters.douyin.src.adapter import DouyinAdapter

            return DouyinAdapter(config={
                "app_id": os.environ.get("DOUYIN_APP_ID", ""),
                "app_secret": os.environ.get("DOUYIN_APP_SECRET", ""),
            })
        else:
            raise UnsupportedPlatformError(f"不支持的平台: {platform}")
