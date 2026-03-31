"""外卖聚合接单面板核心服务

职责：
  1. 接收平台 Webhook → 验签 → 解析 → 写库 → 自动接单检查 → 推送通知
  2. 手动接单（accept）：调用平台 API → 更新状态 → 触发打印 → 推送 KDS
  3. 拒单（reject）：调用平台 API → 更新状态
  4. 出餐完成（mark_ready）：通知平台骑手可取单
  5. 自动接单规则：CRUD + 实时检查

编码约束（遵循 CLAUDE.md）：
  - FastAPI + Pydantic V2 + async/await
  - Repository 模式，Service 层不直接执行 SQL
  - 禁止 except Exception（最外层 HTTP 兜底除外）
  - 所有函数 type hints
  - 金额用 int（分）
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, time
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .delivery_adapters import (
    BaseDeliveryAdapter,
    DeliveryOrder as AdapterOrder,
    MeituanAdapter,
    ElemeAdapter,
    DouyinAdapter,
)
from ..models.delivery_order import DeliveryOrder as DeliveryOrderModel
from ..models.delivery_auto_accept_rule import DeliveryAutoAcceptRule
from ..repositories.delivery_order_repo import (
    DeliveryOrderRepository,
    DeliveryAutoAcceptRuleRepository,
)

logger = structlog.get_logger(__name__)

# 平台友好名称映射
_PLATFORM_NAMES: dict[str, str] = {
    "meituan": "美团外卖",
    "eleme": "饿了么",
    "douyin": "抖音外卖",
}

# Mac mini 地址（用于推送 KDS 通知）
_MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")


# ─── 自定义异常 ────────────────────────────────────────────────────────────────

class DeliveryOrderNotFound(ValueError):
    """订单不存在或租户不匹配"""


class DeliveryOrderStatusError(ValueError):
    """订单状态不允许此操作（如已接单不能再接单）"""


class PlatformAdapterError(RuntimeError):
    """平台 API 调用失败"""


class SignatureVerifyError(ValueError):
    """Webhook 签名验证失败"""


class DuplicateOrderError(ValueError):
    """平台订单号重复入库"""


# ─── 内部工具 ──────────────────────────────────────────────────────────────────

def _make_order_no(platform: str) -> str:
    """生成内部流水号，格式：MT/EL/DY + YYYYMMDDHHMMSS + 6位随机"""
    prefix_map = {"meituan": "MT", "eleme": "EL", "douyin": "DY"}
    prefix = prefix_map.get(platform, "OT")
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{now}{suffix}"


def _get_adapter(
    platform: str,
    app_id: str,
    app_secret: str,
    shop_id: str,
) -> BaseDeliveryAdapter:
    """根据平台标识返回对应适配器实例"""
    adapter_map: dict[str, type[BaseDeliveryAdapter]] = {
        "meituan": MeituanAdapter,
        "eleme": ElemeAdapter,
        "douyin": DouyinAdapter,
    }
    cls = adapter_map.get(platform)
    if cls is None:
        raise ValueError(f"不支持的外卖平台: {platform}")
    return cls(app_id=app_id, app_secret=app_secret, shop_id=shop_id)


async def _push_kds_event(store_id: UUID, event: dict) -> None:
    """通过 Mac mini 推送 KDS 事件（失败不阻断主流程）"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3) as client:
            await client.post(
                f"{_MAC_STATION_URL}/api/v1/kds/push",
                json={"store_id": str(store_id), "event": event},
            )
    except (ImportError, Exception) as exc:  # noqa: BLE001 — KDS 推送不阻断接单主流程
        logger.warning("delivery_panel.kds_push_failed", error=str(exc))


async def _trigger_delivery_print(
    order: DeliveryOrderModel,
) -> None:
    """触发外卖出餐单打印（通过 Mac mini 调度，失败不阻断）"""
    try:
        import httpx
        payload = {
            "type": "delivery_receipt",
            "store_id": str(order.store_id),
            "order_id": str(order.id),
            "order_no": order.order_no,
            "platform": order.platform,
            "platform_name": order.platform_name,
            "customer_name": order.customer_name,
            "delivery_address": order.delivery_address,
            "items": order.items_json or [],
            "total_fen": order.total_fen,
            "special_request": order.special_request,
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{_MAC_STATION_URL}/api/v1/print/delivery",
                json=payload,
            )
        logger.info(
            "delivery_panel.print_triggered",
            order_id=str(order.id),
            order_no=order.order_no,
        )
    except (ImportError, Exception) as exc:  # noqa: BLE001 — 打印失败不阻断接单
        logger.warning("delivery_panel.print_failed", error=str(exc))


# ─── 核心 Service ──────────────────────────────────────────────────────────────

class DeliveryPanelService:
    """外卖聚合接单面板服务层（所有方法通过 Repository 访问 DB）"""

    # ── Webhook 接收 ───────────────────────────────────────────────────────────

    @staticmethod
    async def receive_webhook(
        *,
        platform: str,
        raw_body: bytes,
        payload: dict,
        signature: str,
        tenant_id: UUID,
        store_id: UUID,
        brand_id: str,
        app_id: str,
        app_secret: str,
        shop_id: str,
        commission_rate: float,
        db: AsyncSession,
    ) -> DeliveryOrderModel:
        """
        接收平台 Webhook 推送的新订单。

        流程：
          1. 验签
          2. 解析为统一格式
          3. 幂等检查（防重复入库）
          4. 写入 delivery_orders（status='pending_accept'）
          5. 检查自动接单规则
          6. 推送 WebSocket 通知前端
        """
        log = logger.bind(
            platform=platform,
            tenant_id=str(tenant_id),
            store_id=str(store_id),
        )

        # 1. 验签
        adapter = _get_adapter(platform, app_id, app_secret, shop_id)
        if signature and not adapter.verify_signature(raw_body, signature):
            log.warning("delivery_panel.signature_verify_failed", platform=platform)
            raise SignatureVerifyError(f"{platform} Webhook 签名验证失败")

        # 2. 解析订单
        try:
            parsed: AdapterOrder = adapter.parse_order(payload)
        except ValueError as exc:
            log.error("delivery_panel.parse_order_failed", error=str(exc))
            raise

        # 3. 幂等检查
        existing = await DeliveryOrderRepository.get_by_platform_order_id(
            db, platform, parsed.platform_order_id, tenant_id
        )
        if existing is not None:
            log.info(
                "delivery_panel.duplicate_order_skipped",
                platform_order_id=parsed.platform_order_id,
            )
            raise DuplicateOrderError(
                f"订单已存在: platform={platform}, "
                f"platform_order_id={parsed.platform_order_id}"
            )

        # 4. 计算佣金
        commission_fen: int = round(parsed.total_fen * commission_rate)
        actual_revenue_fen: int = parsed.total_fen - commission_fen

        # 5. 写入 DB
        order = await DeliveryOrderRepository.create(
            db,
            tenant_id=tenant_id,
            store_id=store_id,
            brand_id=brand_id,
            platform=platform,
            platform_name=_PLATFORM_NAMES.get(platform, platform),
            platform_order_id=parsed.platform_order_id,
            platform_order_no=payload.get("order_no") or payload.get("orderNo"),
            sales_channel=f"delivery_{platform}",
            status="pending_accept",
            items_json=[item.model_dump() for item in parsed.items],
            total_fen=parsed.total_fen,
            commission_rate=commission_rate,
            commission_fen=commission_fen,
            merchant_receive_fen=actual_revenue_fen,
            actual_revenue_fen=actual_revenue_fen,
            customer_name=parsed.customer_name,
            customer_phone=parsed.customer_phone,
            delivery_address=parsed.delivery_address,
            expected_time=(
                parsed.estimated_delivery_at.isoformat()
                if parsed.estimated_delivery_at
                else None
            ),
            estimated_prep_time=None,
            special_request=payload.get("notes") or payload.get("remark"),
            notes=payload.get("notes") or payload.get("remark"),
            order_no=_make_order_no(platform),
        )
        await db.commit()

        log.info(
            "delivery_panel.order_created",
            order_id=str(order.id),
            order_no=order.order_no,
            total_fen=order.total_fen,
        )

        # 6. 检查自动接单
        auto_accepted = await DeliveryPanelService._check_and_auto_accept(
            order=order,
            tenant_id=tenant_id,
            store_id=store_id,
            adapter=adapter,
            db=db,
        )

        # 7. 推送前端通知
        await _push_kds_event(
            store_id,
            {
                "type": "delivery_order_new",
                "order_id": str(order.id),
                "platform": platform,
                "platform_order_id": parsed.platform_order_id,
                "status": order.status,
                "total_fen": order.total_fen,
                "auto_accepted": auto_accepted,
                "items_count": len(parsed.items),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return order

    # ── 自动接单内部逻辑 ───────────────────────────────────────────────────────

    @staticmethod
    async def _check_and_auto_accept(
        *,
        order: DeliveryOrderModel,
        tenant_id: UUID,
        store_id: UUID,
        adapter: BaseDeliveryAdapter,
        db: AsyncSession,
    ) -> bool:
        """检查自动接单规则，符合条件则自动接单。返回是否执行了自动接单。"""
        log = logger.bind(order_id=str(order.id), platform=order.platform)

        rule = await DeliveryAutoAcceptRuleRepository.get_by_store(db, store_id, tenant_id)
        if rule is None or not rule.is_enabled:
            return False

        # 检查时间窗口
        now_time: time = datetime.now().time()
        if rule.business_hours_start and rule.business_hours_end:
            if not (rule.business_hours_start <= now_time <= rule.business_hours_end):
                log.info("delivery_panel.auto_accept.outside_hours")
                return False

        # 检查排除平台
        excluded: list = rule.excluded_platforms or []
        if order.platform in excluded:
            log.info("delivery_panel.auto_accept.platform_excluded", platform=order.platform)
            return False

        # 检查并发上限
        active_count = await DeliveryOrderRepository.count_active_orders(
            db, store_id, tenant_id
        )
        # active_count 包含刚创建的 pending_accept 订单本身
        if active_count > rule.max_concurrent_orders:
            log.info(
                "delivery_panel.auto_accept.concurrent_limit_reached",
                active_count=active_count,
                max_concurrent=rule.max_concurrent_orders,
            )
            return False

        # 执行自动接单
        try:
            await DeliveryPanelService._do_accept_order(
                order=order,
                tenant_id=tenant_id,
                adapter=adapter,
                prep_time_minutes=order.estimated_prep_time or 20,
                auto=True,
                db=db,
            )
            log.info("delivery_panel.auto_accept.done", order_id=str(order.id))
            return True
        except (PlatformAdapterError, ValueError) as exc:
            log.warning("delivery_panel.auto_accept.failed", error=str(exc))
            return False

    # ── 手动接单 ───────────────────────────────────────────────────────────────

    @staticmethod
    async def accept_order(
        *,
        order_id: UUID,
        tenant_id: UUID,
        prep_time_minutes: int = 20,
        app_id: str,
        app_secret: str,
        shop_id: str,
        db: AsyncSession,
    ) -> DeliveryOrderModel:
        """
        手动接单。

        1. 查询订单（校验状态必须为 pending_accept）
        2. 调用平台接单 API
        3. 更新状态 → accepted
        4. 触发外卖打印单
        5. 推送 KDS
        """
        order = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order is None:
            raise DeliveryOrderNotFound(f"订单不存在: {order_id}")
        if order.status != "pending_accept":
            raise DeliveryOrderStatusError(
                f"订单状态 '{order.status}' 不允许接单，需为 pending_accept"
            )

        adapter = _get_adapter(order.platform, app_id, app_secret, shop_id)
        await DeliveryPanelService._do_accept_order(
            order=order,
            tenant_id=tenant_id,
            adapter=adapter,
            prep_time_minutes=prep_time_minutes,
            auto=False,
            db=db,
        )
        # 刷新 order 对象
        refreshed = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        return refreshed  # type: ignore[return-value]

    @staticmethod
    async def _do_accept_order(
        *,
        order: DeliveryOrderModel,
        tenant_id: UUID,
        adapter: BaseDeliveryAdapter,
        prep_time_minutes: int,
        auto: bool,
        db: AsyncSession,
    ) -> None:
        """内部接单执行：调用平台API + 更新DB + 打印 + KDS推送"""
        log = logger.bind(order_id=str(order.id), auto=auto)

        # 调用平台接单 API
        ok = await adapter.confirm_order(order.platform_order_id)
        if not ok:
            raise PlatformAdapterError(
                f"平台接单 API 返回失败: platform={order.platform}, "
                f"platform_order_id={order.platform_order_id}"
            )

        now = datetime.now(timezone.utc)
        updated = await DeliveryOrderRepository.update_status(
            db,
            order.id,
            tenant_id,
            "accepted",
            accepted_at=now,
            auto_accepted=auto,
            estimated_prep_time=prep_time_minutes,
        )
        if not updated:
            raise DeliveryOrderNotFound(f"更新状态失败，订单可能已被删除: {order.id}")
        await db.commit()

        log.info(
            "delivery_panel.order_accepted",
            order_id=str(order.id),
            platform=order.platform,
            prep_time_minutes=prep_time_minutes,
        )

        # 触发打印（刷新 order 对象以获取新状态）
        order.status = "accepted"
        order.accepted_at = now
        order.auto_accepted = auto
        order.estimated_prep_time = prep_time_minutes
        await _trigger_delivery_print(order)

        # 推送 KDS
        await _push_kds_event(
            order.store_id,
            {
                "type": "delivery_order_accepted",
                "order_id": str(order.id),
                "platform": order.platform,
                "auto": auto,
                "prep_time_minutes": prep_time_minutes,
            },
        )

    # ── 拒单 ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def reject_order(
        *,
        order_id: UUID,
        tenant_id: UUID,
        reason: str,
        reason_code: str,
        app_id: str,
        app_secret: str,
        shop_id: str,
        db: AsyncSession,
    ) -> DeliveryOrderModel:
        """
        拒单。

        1. 校验订单状态（必须为 pending_accept 或 accepted）
        2. 调用平台拒单 API
        3. 更新状态 → rejected
        """
        order = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order is None:
            raise DeliveryOrderNotFound(f"订单不存在: {order_id}")
        if order.status not in ("pending_accept", "accepted"):
            raise DeliveryOrderStatusError(
                f"订单状态 '{order.status}' 不允许拒单"
            )

        adapter = _get_adapter(order.platform, app_id, app_secret, shop_id)
        reject_reason_full = f"[{reason_code}] {reason}" if reason_code else reason
        ok = await adapter.reject_order(order.platform_order_id, reject_reason_full)
        if not ok:
            raise PlatformAdapterError(
                f"平台拒单 API 返回失败: platform={order.platform}"
            )

        now = datetime.now(timezone.utc)
        await DeliveryOrderRepository.update_status(
            db,
            order.id,
            tenant_id,
            "rejected",
            rejected_at=now,
            rejected_reason=reason,
            cancel_reason=reason,
        )
        await db.commit()

        logger.info(
            "delivery_panel.order_rejected",
            order_id=str(order_id),
            reason=reason,
        )

        refreshed = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        return refreshed  # type: ignore[return-value]

    # ── 出餐完成 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def mark_ready(
        *,
        order_id: UUID,
        tenant_id: UUID,
        app_id: str,
        app_secret: str,
        shop_id: str,
        db: AsyncSession,
    ) -> DeliveryOrderModel:
        """
        标记出餐完成，通知平台骑手可取单。

        允许状态：accepted → preparing → ready（也接受 accepted 直接跳到 ready）
        """
        order = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        if order is None:
            raise DeliveryOrderNotFound(f"订单不存在: {order_id}")
        if order.status not in ("accepted", "preparing"):
            raise DeliveryOrderStatusError(
                f"订单状态 '{order.status}' 不允许标记出餐完成"
            )

        now = datetime.now(timezone.utc)
        await DeliveryOrderRepository.update_status(
            db,
            order.id,
            tenant_id,
            "ready",
            ready_at=now,
        )
        await db.commit()

        logger.info("delivery_panel.order_ready", order_id=str(order_id))

        await _push_kds_event(
            order.store_id,
            {
                "type": "delivery_order_ready",
                "order_id": str(order.id),
                "platform": order.platform,
                "ready_at": now.isoformat(),
            },
        )

        refreshed = await DeliveryOrderRepository.get_by_id(db, order_id, tenant_id)
        return refreshed  # type: ignore[return-value]

    # ── 统计 ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_daily_stats(
        *,
        tenant_id: UUID,
        store_id: UUID,
        target_date,
        db: AsyncSession,
    ) -> dict:
        """今日外卖汇总：各平台订单数/营收/佣金/实收"""
        rows = await DeliveryOrderRepository.get_daily_stats_by_platform(
            db, tenant_id, store_id, target_date
        )
        total_orders = sum(r["order_count"] for r in rows)
        total_revenue = sum(r["revenue_fen"] for r in rows)
        total_commission = sum(r["commission_fen"] for r in rows)
        total_net = sum(r["net_revenue_fen"] for r in rows)

        platforms_out = []
        for r in rows:
            revenue = r["revenue_fen"]
            commission = r["commission_fen"]
            platforms_out.append(
                {
                    "platform": r["platform"],
                    "platform_name": _PLATFORM_NAMES.get(r["platform"], r["platform"]),
                    "order_count": r["order_count"],
                    "revenue_fen": revenue,
                    "commission_fen": commission,
                    "net_revenue_fen": r["net_revenue_fen"],
                    "effective_rate": round(commission / revenue, 4) if revenue > 0 else 0.0,
                }
            )

        return {
            "date": target_date.isoformat(),
            "store_id": str(store_id),
            "platforms": platforms_out,
            "total_orders": total_orders,
            "total_revenue_fen": total_revenue,
            "total_commission_fen": total_commission,
            "total_net_revenue_fen": total_net,
        }

    # ── 自动接单规则管理 ──────────────────────────────────────────────────────

    @staticmethod
    async def get_auto_accept_rule(
        *,
        store_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> Optional[DeliveryAutoAcceptRule]:
        """获取门店自动接单规则（未配置则返回 None）"""
        return await DeliveryAutoAcceptRuleRepository.get_by_store(db, store_id, tenant_id)

    @staticmethod
    async def upsert_auto_accept_rule(
        *,
        tenant_id: UUID,
        store_id: UUID,
        is_enabled: Optional[bool],
        business_hours_start: Optional[time],
        business_hours_end: Optional[time],
        max_concurrent_orders: Optional[int],
        excluded_platforms: Optional[list],
        db: AsyncSession,
    ) -> DeliveryAutoAcceptRule:
        """创建或更新自动接单规则"""
        rule = await DeliveryAutoAcceptRuleRepository.upsert(
            db,
            tenant_id=tenant_id,
            store_id=store_id,
            is_enabled=is_enabled,
            business_hours_start=business_hours_start,
            business_hours_end=business_hours_end,
            max_concurrent_orders=max_concurrent_orders,
            excluded_platforms=excluded_platforms,
        )
        await db.commit()
        await db.refresh(rule)
        logger.info(
            "delivery_panel.auto_accept_rule_updated",
            store_id=str(store_id),
            is_enabled=rule.is_enabled,
        )
        return rule
