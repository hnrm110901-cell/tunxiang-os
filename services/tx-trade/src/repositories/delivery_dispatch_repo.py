"""配送调度 Repository — 封装 delivery_dispatches & delivery_provider_configs 的 DB 操作

约束：
  - 所有方法接受 AsyncSession，由路由层通过 Depends(get_db) 注入
  - 不直接 import 路由层任何模块（单向依赖）
  - 金额字段统一使用 int（分），严禁 float
  - 显式 tenant_id 过滤 + RLS 双重保障

唯一标识策略：
  - DB 层主键是 UUID id（TenantBase 默认）
  - 业务可读编号是 dispatch_no（VARCHAR(40)，如 DSP-XXXX）
  - 路由层与前端只暴露 dispatch_no
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.delivery_dispatch import DeliveryDispatch, DeliveryProviderConfig

logger = structlog.get_logger(__name__)


class DeliveryDispatchRepository:
    """配送调度记录持久化操作"""

    @staticmethod
    async def get(
        db: AsyncSession,
        dispatch_no: str,
        tenant_id: UUID,
    ) -> Optional[DeliveryDispatch]:
        """按业务编号查单条调度记录（已过滤软删除）"""
        stmt = select(DeliveryDispatch).where(
            and_(
                DeliveryDispatch.dispatch_no == dispatch_no,
                DeliveryDispatch.tenant_id == tenant_id,
                DeliveryDispatch.is_deleted.is_(False),
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_order(
        db: AsyncSession,
        order_id: str,
        tenant_id: UUID,
    ) -> Optional[DeliveryDispatch]:
        """按 order_id 查最新一条调度记录（用于 KDS Ready 触发推送）"""
        stmt = (
            select(DeliveryDispatch)
            .where(
                and_(
                    DeliveryDispatch.order_id == order_id,
                    DeliveryDispatch.tenant_id == tenant_id,
                    DeliveryDispatch.is_deleted.is_(False),
                )
            )
            .order_by(DeliveryDispatch.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        dispatch_no: str,
        tenant_id: UUID,
        store_id: str,
        order_id: str,
        provider: str,
        provider_order_id: Optional[str],
        delivery_address: str,
        delivery_lat: Optional[float],
        delivery_lng: Optional[float],
        distance_meters: int,
        delivery_fee_fen: int,
        tip_fen: int,
        estimated_minutes: int,
    ) -> DeliveryDispatch:
        now = datetime.now(timezone.utc)
        dispatch = DeliveryDispatch(
            id=uuid.uuid4(),
            dispatch_no=dispatch_no,
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
            provider=provider,
            provider_order_id=provider_order_id,
            status="dispatched",
            delivery_address=delivery_address,
            delivery_lat=delivery_lat,
            delivery_lng=delivery_lng,
            distance_meters=distance_meters,
            delivery_fee_fen=delivery_fee_fen,
            tip_fen=tip_fen,
            estimated_minutes=estimated_minutes,
            dispatched_at=now,
        )
        db.add(dispatch)
        await db.flush()
        logger.info(
            "delivery_dispatch_repo.create.ok",
            dispatch_no=dispatch_no,
            provider=provider,
            order_id=order_id,
        )
        return dispatch

    @staticmethod
    async def update_rider_location(
        db: AsyncSession,
        dispatch_no: str,
        tenant_id: UUID,
        *,
        rider_lat: float,
        rider_lng: float,
        rider_name: Optional[str] = None,
        rider_phone: Optional[str] = None,
    ) -> bool:
        """更新骑手位置（达达/顺丰轮询回填，自有骑手 App 上报）"""
        values: dict = {
            "rider_lat": rider_lat,
            "rider_lng": rider_lng,
            "rider_updated_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        if rider_name is not None:
            values["rider_name"] = rider_name
        if rider_phone is not None:
            values["rider_phone"] = rider_phone

        stmt = (
            update(DeliveryDispatch)
            .where(
                and_(
                    DeliveryDispatch.dispatch_no == dispatch_no,
                    DeliveryDispatch.tenant_id == tenant_id,
                    DeliveryDispatch.is_deleted.is_(False),
                )
            )
            .values(**values)
        )
        result = await db.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    async def cancel(
        db: AsyncSession,
        dispatch_no: str,
        tenant_id: UUID,
        reason: str,
    ) -> bool:
        """取消配送（已校验状态后调用）"""
        now = datetime.now(timezone.utc)
        stmt = (
            update(DeliveryDispatch)
            .where(
                and_(
                    DeliveryDispatch.dispatch_no == dispatch_no,
                    DeliveryDispatch.tenant_id == tenant_id,
                    DeliveryDispatch.is_deleted.is_(False),
                )
            )
            .values(
                status="cancelled",
                cancelled_at=now,
                cancel_reason=reason,
                updated_at=now,
            )
        )
        result = await db.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    async def mark_kds_ready(
        db: AsyncSession,
        dispatch_no: str,
        tenant_id: UUID,
    ) -> bool:
        """KDS 出餐完成，记录时间戳（用于触发骑手 App 取货推送）。幂等：已 set 不重复"""
        now = datetime.now(timezone.utc)
        stmt = (
            update(DeliveryDispatch)
            .where(
                and_(
                    DeliveryDispatch.dispatch_no == dispatch_no,
                    DeliveryDispatch.tenant_id == tenant_id,
                    DeliveryDispatch.is_deleted.is_(False),
                    DeliveryDispatch.kds_ready_at.is_(None),
                )
            )
            .values(kds_ready_at=now, updated_at=now)
        )
        result = await db.execute(stmt)
        return result.rowcount > 0

    @staticmethod
    async def mark_rider_notified(
        db: AsyncSession,
        dispatch_no: str,
        tenant_id: UUID,
    ) -> bool:
        """骑手 App 收到取货推送时回写"""
        now = datetime.now(timezone.utc)
        stmt = (
            update(DeliveryDispatch)
            .where(
                and_(
                    DeliveryDispatch.dispatch_no == dispatch_no,
                    DeliveryDispatch.tenant_id == tenant_id,
                    DeliveryDispatch.is_deleted.is_(False),
                )
            )
            .values(rider_notified_at=now, updated_at=now)
        )
        result = await db.execute(stmt)
        return result.rowcount > 0


class DeliveryProviderConfigRepository:
    """配送商配置持久化操作"""

    @staticmethod
    async def list_for_store(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: str,
    ) -> list[DeliveryProviderConfig]:
        stmt = select(DeliveryProviderConfig).where(
            and_(
                DeliveryProviderConfig.tenant_id == tenant_id,
                DeliveryProviderConfig.store_id == store_id,
                DeliveryProviderConfig.is_deleted.is_(False),
            )
        )
        rows = (await db.execute(stmt)).scalars().all()
        return list(rows)

    @staticmethod
    async def select_best_enabled(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: str,
    ) -> Optional[DeliveryProviderConfig]:
        """按优先级选已启用的最高优先级 provider（priority 数字越小越优先）"""
        stmt = (
            select(DeliveryProviderConfig)
            .where(
                and_(
                    DeliveryProviderConfig.tenant_id == tenant_id,
                    DeliveryProviderConfig.store_id == store_id,
                    DeliveryProviderConfig.enabled.is_(True),
                    DeliveryProviderConfig.is_deleted.is_(False),
                )
            )
            .order_by(DeliveryProviderConfig.priority.asc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_one(
        db: AsyncSession,
        tenant_id: UUID,
        store_id: str,
        provider: str,
    ) -> Optional[DeliveryProviderConfig]:
        stmt = select(DeliveryProviderConfig).where(
            and_(
                DeliveryProviderConfig.tenant_id == tenant_id,
                DeliveryProviderConfig.store_id == store_id,
                DeliveryProviderConfig.provider == provider,
                DeliveryProviderConfig.is_deleted.is_(False),
            )
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        store_id: str,
        provider: str,
        enabled: bool,
        priority: int,
        app_key: Optional[str],
        app_secret: Optional[str],
        merchant_id: Optional[str],
        shop_no: Optional[str],
        callback_url: Optional[str],
        extra_config: Optional[dict],
        update_secret_only_if_provided: bool = True,
    ) -> DeliveryProviderConfig:
        """新建或更新配置。

        update_secret_only_if_provided=True 时：app_key/app_secret 仅在显式
        提供（非 None）才覆盖，避免脱敏返回的 ****掩码 回写后破坏凭据。
        """
        existing = await DeliveryProviderConfigRepository.get_one(
            db, tenant_id, store_id, provider
        )
        now = datetime.now(timezone.utc)
        if existing is not None:
            existing.enabled = enabled
            existing.priority = priority
            existing.merchant_id = merchant_id
            existing.shop_no = shop_no
            existing.callback_url = callback_url
            existing.extra_config = extra_config or {}
            if not update_secret_only_if_provided or app_key is not None:
                existing.app_key = app_key
            if not update_secret_only_if_provided or app_secret is not None:
                existing.app_secret = app_secret
            existing.updated_at = now
            await db.flush()
            return existing

        new = DeliveryProviderConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            provider=provider,
            enabled=enabled,
            priority=priority,
            app_key=app_key,
            app_secret=app_secret,
            merchant_id=merchant_id,
            shop_no=shop_no,
            callback_url=callback_url,
            extra_config=extra_config or {},
        )
        db.add(new)
        await db.flush()
        return new
