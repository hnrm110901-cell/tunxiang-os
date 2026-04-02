"""外卖运营配置服务 — 自动接单 / Busy Mode / 差评预警 / 健康度看板

提供:
  DeliveryOpsService — 核心业务逻辑（门店配置/忙碌模式/评价管理/健康度）

Pydantic 模型:
  DeliveryStoreConfig  — 门店平台配置（含动态出餐时间）
  DeliveryReview       — 评价记录
  PlatformHealth       — 单平台健康度
  HealthDashboard      — 多平台健康度看板
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ─── Pydantic 响应模型 ────────────────────────────────────────────────────────


class DeliveryStoreConfig(BaseModel):
    """门店平台外卖运营配置（含动态计算的当前出餐时间）"""

    id: uuid.UUID
    store_id: uuid.UUID
    platform: str
    auto_accept: bool
    auto_accept_max_per_hour: int
    busy_mode: bool
    busy_mode_prep_time_min: int
    normal_prep_time_min: int
    current_prep_time_min: int  # 动态计算：busy_mode 时返回 busy_mode_prep_time_min
    busy_mode_started_at: Optional[datetime]
    busy_mode_auto_off_at: Optional[datetime]
    max_delivery_distance_km: float
    is_active: bool
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class DeliveryReview(BaseModel):
    """外卖评价记录"""

    id: uuid.UUID
    store_id: uuid.UUID
    platform: str
    platform_order_id: Optional[str]
    platform_review_id: Optional[str]
    rating: int
    content: Optional[str]
    tags: Optional[list[str]]
    is_negative: bool
    reply_content: Optional[str]
    replied_at: Optional[datetime]
    alert_sent: bool
    reviewed_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformHealth(BaseModel):
    """单平台健康度指标"""

    platform: str
    overall_score: Optional[float]
    dsr_food: Optional[float]
    dsr_service: Optional[float]
    dsr_delivery: Optional[float]
    monthly_sales: int
    positive_rate: Optional[float]
    recent_bad_reviews: int  # 近7天差评数
    status: str  # healthy / warning / critical

    @classmethod
    def compute_status(
        cls,
        overall_score: Optional[float],
        recent_bad_reviews: int,
    ) -> str:
        """根据综合评分和近7天差评数判断健康状态"""
        if overall_score is not None and overall_score < 4.0:
            return "critical"
        if overall_score is not None and overall_score < 4.5:
            return "warning"
        if recent_bad_reviews >= 5:
            return "warning"
        if recent_bad_reviews >= 10:
            return "critical"
        return "healthy"


class HealthDashboard(BaseModel):
    """多平台健康度看板"""

    platforms: list[PlatformHealth]


# ─── 自定义异常 ────────────────────────────────────────────────────────────────


class DeliveryOpsError(Exception):
    """外卖运营服务基础异常"""


class ConfigNotFoundError(DeliveryOpsError):
    """门店平台配置不存在"""


class ReviewNotFoundError(DeliveryOpsError):
    """评价记录不存在"""


# ─── 服务层 ───────────────────────────────────────────────────────────────────


class DeliveryOpsService:
    """外卖运营配置服务

    所有方法均需传入 tenant_id（UUID 或 str），供 RLS 隔离使用。
    调用方负责在 DB session 上设置 app.tenant_id（通过中间件或手动执行）。
    """

    PLATFORMS: tuple[str, ...] = ("meituan", "eleme", "douyin")

    # ─── 配置管理 ─────────────────────────────────────────────────────

    async def get_store_config(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryStoreConfig:
        """获取门店指定平台的外卖运营配置，不存在则自动创建默认配置"""
        from shared.ontology.src.database import run_with_tenant  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        row = await self._fetch_config_row(sid, platform, tid, db)
        if row is None:
            row = await self._create_default_config(sid, platform, tid, db)

        return self._row_to_config(row)

    async def get_all_store_configs(
        self,
        store_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> list[DeliveryStoreConfig]:
        """获取门店所有平台的配置"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        stmt = (
            select(_DeliveryStoreConfigRow.__table__)
            .where(
                and_(
                    _DeliveryStoreConfigRow.__table__.c.tenant_id == tid,
                    _DeliveryStoreConfigRow.__table__.c.store_id == sid,
                    _DeliveryStoreConfigRow.__table__.c.is_active.is_(True),
                )
            )
            .order_by(_DeliveryStoreConfigRow.__table__.c.platform)
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()

        configs = [self._row_to_config(dict(r)) for r in rows]

        # 补充缺失平台的默认配置
        existing_platforms = {c.platform for c in configs}
        for platform in self.PLATFORMS:
            if platform not in existing_platforms:
                row = await self._create_default_config(sid, platform, tid, db)
                configs.append(self._row_to_config(row))

        return sorted(configs, key=lambda c: c.platform)

    async def update_store_config(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        config_update: dict[str, Any],
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryStoreConfig:
        """更新门店平台配置（只允许更新白名单字段）"""
        from sqlalchemy import text  # noqa: PLC0415

        _UPDATABLE_FIELDS = {
            "auto_accept",
            "auto_accept_max_per_hour",
            "busy_mode_prep_time_min",
            "normal_prep_time_min",
            "max_delivery_distance_km",
            "is_active",
        }

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        # 确保配置存在
        row = await self._fetch_config_row(sid, platform, tid, db)
        if row is None:
            row = await self._create_default_config(sid, platform, tid, db)

        safe_update = {
            k: v for k, v in config_update.items() if k in _UPDATABLE_FIELDS
        }
        if not safe_update:
            return self._row_to_config(row)

        safe_update["updated_at"] = datetime.now(tz=timezone.utc)

        stmt = (
            _DeliveryStoreConfigRow.__table__.update()
            .where(
                and_(
                    _DeliveryStoreConfigRow.__table__.c.tenant_id == tid,
                    _DeliveryStoreConfigRow.__table__.c.store_id == sid,
                    _DeliveryStoreConfigRow.__table__.c.platform == platform,
                )
            )
            .values(**safe_update)
            .returning(*_DeliveryStoreConfigRow.__table__.c)
        )
        result = await db.execute(stmt)
        updated = result.mappings().one()
        await db.flush()

        log = logger.bind(store_id=str(sid), platform=platform, fields=list(safe_update))
        log.info("delivery_ops.config_updated")
        return self._row_to_config(dict(updated))

    # ─── Busy Mode ────────────────────────────────────────────────────

    async def enable_busy_mode(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
        duration_minutes: int = 120,
    ) -> DeliveryStoreConfig:
        """开启忙碌模式，自动设置 duration_minutes 后的关闭时间"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        now = datetime.now(tz=timezone.utc)
        auto_off = now + timedelta(minutes=duration_minutes)

        # 确保配置存在
        row = await self._fetch_config_row(sid, platform, tid, db)
        if row is None:
            row = await self._create_default_config(sid, platform, tid, db)

        stmt = (
            _DeliveryStoreConfigRow.__table__.update()
            .where(
                and_(
                    _DeliveryStoreConfigRow.__table__.c.tenant_id == tid,
                    _DeliveryStoreConfigRow.__table__.c.store_id == sid,
                    _DeliveryStoreConfigRow.__table__.c.platform == platform,
                )
            )
            .values(
                busy_mode=True,
                busy_mode_started_at=now,
                busy_mode_auto_off_at=auto_off,
                updated_at=now,
            )
            .returning(*_DeliveryStoreConfigRow.__table__.c)
        )
        result = await db.execute(stmt)
        updated = result.mappings().one()
        await db.flush()

        logger.bind(
            store_id=str(sid),
            platform=platform,
            duration_minutes=duration_minutes,
            auto_off_at=auto_off.isoformat(),
        ).info("delivery_ops.busy_mode_enabled")

        return self._row_to_config(dict(updated))

    async def disable_busy_mode(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryStoreConfig:
        """关闭忙碌模式"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        row = await self._fetch_config_row(sid, platform, tid, db)
        if row is None:
            raise ConfigNotFoundError(
                f"Config not found: store={store_id} platform={platform}"
            )

        now = datetime.now(tz=timezone.utc)
        stmt = (
            _DeliveryStoreConfigRow.__table__.update()
            .where(
                and_(
                    _DeliveryStoreConfigRow.__table__.c.tenant_id == tid,
                    _DeliveryStoreConfigRow.__table__.c.store_id == sid,
                    _DeliveryStoreConfigRow.__table__.c.platform == platform,
                )
            )
            .values(
                busy_mode=False,
                busy_mode_started_at=None,
                busy_mode_auto_off_at=None,
                updated_at=now,
            )
            .returning(*_DeliveryStoreConfigRow.__table__.c)
        )
        result = await db.execute(stmt)
        updated = result.mappings().one()
        await db.flush()

        logger.bind(store_id=str(sid), platform=platform).info(
            "delivery_ops.busy_mode_disabled"
        )
        return self._row_to_config(dict(updated))

    async def get_current_prep_time(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """获取当前有效出餐时间（忙碌模式时返回忙碌出餐时间）"""
        config = await self.get_store_config(store_id, platform, tenant_id, db)
        return config.current_prep_time_min

    async def should_auto_accept(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        current_hour_count: int,
        db: AsyncSession,
    ) -> bool:
        """判断是否应自动接单（考虑开关状态和每小时上限）"""
        config = await self.get_store_config(store_id, platform, tenant_id, db)

        if not config.auto_accept:
            return False
        if not config.is_active:
            return False
        if current_hour_count >= config.auto_accept_max_per_hour:
            logger.bind(
                store_id=str(store_id),
                platform=platform,
                current_hour_count=current_hour_count,
                max_per_hour=config.auto_accept_max_per_hour,
            ).info("delivery_ops.auto_accept_limit_reached")
            return False

        return True

    # ─── 评价管理 ─────────────────────────────────────────────────────

    async def add_review(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        review_data: dict[str, Any],
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryReview:
        """录入评价；rating≤3 的差评自动设置 alert_sent=False（待预警发送）"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        rating = int(review_data.get("rating", 5))
        reviewed_at = review_data.get("reviewed_at") or datetime.now(tz=timezone.utc)
        if isinstance(reviewed_at, (int, float)):
            reviewed_at = datetime.fromtimestamp(reviewed_at, tz=timezone.utc)

        insert_values = {
            "tenant_id": tid,
            "store_id": sid,
            "platform": platform,
            "platform_order_id": review_data.get("platform_order_id"),
            "platform_review_id": review_data.get("platform_review_id"),
            "rating": rating,
            "content": review_data.get("content"),
            "tags": review_data.get("tags"),
            "reply_content": None,
            "replied_at": None,
            "alert_sent": False,  # 差评需等待 send_negative_alert() 发出预警
            "reviewed_at": reviewed_at,
        }

        stmt = (
            _DeliveryReviewRow.__table__.insert()
            .values(**insert_values)
            .returning(*_DeliveryReviewRow.__table__.c)
        )
        result = await db.execute(stmt)
        row = result.mappings().one()
        await db.flush()

        review = self._review_row_to_model(dict(row))

        if review.is_negative:
            logger.bind(
                store_id=str(sid),
                platform=platform,
                rating=rating,
                review_id=str(review.id),
            ).warning("delivery_ops.negative_review_received")

        return review

    async def send_negative_alert(
        self,
        review_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryReview:
        """发送差评预警并标记 alert_sent=True

        具体推送渠道（企微群/短信/站内通知）留 TODO，
        待对接 tx-agent 通知系统后实现。
        """
        from sqlalchemy import text  # noqa: PLC0415

        rid = uuid.UUID(str(review_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        row = await self._fetch_review_row(rid, tid, db)
        if row is None:
            raise ReviewNotFoundError(f"Review not found: {review_id}")
        if not row.get("is_negative"):
            logger.bind(review_id=str(rid)).info(
                "delivery_ops.alert_skip_not_negative"
            )
            return self._review_row_to_model(row)

        logger.bind(
            review_id=str(rid),
            store_id=str(row.get("store_id")),
            platform=row.get("platform"),
            rating=row.get("rating"),
        ).warning("delivery_ops.negative_alert_triggered")
        # 向 sms_jobs Redis Stream 推送差评预警作业，告警 Worker 消费后发送企微/短信通知
        try:
            import redis.asyncio as aioredis  # type: ignore

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            async with aioredis.from_url(redis_url, decode_responses=True) as r:
                await r.xadd(
                    "sms_jobs",
                    {
                        "sms_type": "delivery_negative_review",
                        "review_id": str(rid),
                        "store_id": str(row.get("store_id") or ""),
                        "platform": str(row.get("platform") or ""),
                        "rating": str(row.get("rating") or ""),
                        "tenant_id": str(tid),
                    },
                    maxlen=50_000,
                    approximate=True,
                )
        except (OSError, RuntimeError) as exc:
            logger.warning("delivery_ops.alert_publish_failed", review_id=str(rid), error=str(exc))

        stmt = (
            _DeliveryReviewRow.__table__.update()
            .where(
                and_(
                    _DeliveryReviewRow.__table__.c.id == rid,
                    _DeliveryReviewRow.__table__.c.tenant_id == tid,
                )
            )
            .values(alert_sent=True)
            .returning(*_DeliveryReviewRow.__table__.c)
        )
        result = await db.execute(stmt)
        updated = result.mappings().one()
        await db.flush()
        return self._review_row_to_model(dict(updated))

    async def get_negative_reviews(
        self,
        store_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
        platform: Optional[str] = None,
        days: int = 7,
        rating_max: int = 3,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DeliveryReview], int]:
        """获取近N天差评列表，返回 (items, total)"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        tbl = _DeliveryReviewRow.__table__

        conditions = [
            tbl.c.tenant_id == tid,
            tbl.c.store_id == sid,
            tbl.c.rating <= rating_max,
            tbl.c.reviewed_at >= cutoff,
        ]
        if platform:
            conditions.append(tbl.c.platform == platform)

        total_stmt = select(func.count()).select_from(tbl).where(and_(*conditions))
        total_result = await db.execute(total_stmt)
        total = total_result.scalar() or 0

        stmt = (
            select(tbl)
            .where(and_(*conditions))
            .order_by(tbl.c.reviewed_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()
        items = [self._review_row_to_model(dict(r)) for r in rows]
        return items, total

    async def reply_review(
        self,
        review_id: str | uuid.UUID,
        content: str,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> DeliveryReview:
        """回复差评（写入 reply_content + replied_at）"""
        from sqlalchemy import text  # noqa: PLC0415

        rid = uuid.UUID(str(review_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        row = await self._fetch_review_row(rid, tid, db)
        if row is None:
            raise ReviewNotFoundError(f"Review not found: {review_id}")

        now = datetime.now(tz=timezone.utc)
        stmt = (
            _DeliveryReviewRow.__table__.update()
            .where(
                and_(
                    _DeliveryReviewRow.__table__.c.id == rid,
                    _DeliveryReviewRow.__table__.c.tenant_id == tid,
                )
            )
            .values(reply_content=content, replied_at=now)
            .returning(*_DeliveryReviewRow.__table__.c)
        )
        result = await db.execute(stmt)
        updated = result.mappings().one()
        await db.flush()

        logger.bind(review_id=str(rid)).info("delivery_ops.review_replied")
        return self._review_row_to_model(dict(updated))

    async def get_unhandled_alert_count(
        self,
        store_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """获取未发送预警的差评数（用于前端 badge 显示）"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        tbl = _DeliveryReviewRow.__table__
        stmt = select(func.count()).select_from(tbl).where(
            and_(
                tbl.c.tenant_id == tid,
                tbl.c.store_id == sid,
                tbl.c.is_negative.is_(True),
                tbl.c.alert_sent.is_(False),
            )
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    # ─── 健康度看板 ───────────────────────────────────────────────────

    async def get_health_dashboard(
        self,
        store_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
    ) -> HealthDashboard:
        """获取各平台健康度看板（最新快照 + 近7天差评数）"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        platform_healths: list[PlatformHealth] = []

        for platform in self.PLATFORMS:
            # 取最新快照
            snap = await self._get_latest_snapshot(sid, platform, tid, db)
            # 近7天差评数
            _, bad_count = await self.get_negative_reviews(
                sid, tid, db, platform=platform, days=7, rating_max=3, size=1000
            )
            overall_score = float(snap["overall_score"]) if snap and snap.get("overall_score") is not None else None
            ph = PlatformHealth(
                platform=platform,
                overall_score=overall_score,
                dsr_food=float(snap["dsr_food"]) if snap and snap.get("dsr_food") is not None else None,
                dsr_service=float(snap["dsr_service"]) if snap and snap.get("dsr_service") is not None else None,
                dsr_delivery=float(snap["dsr_delivery"]) if snap and snap.get("dsr_delivery") is not None else None,
                monthly_sales=int(snap["monthly_sales"]) if snap else 0,
                positive_rate=float(snap["positive_rate"]) if snap and snap.get("positive_rate") is not None else None,
                recent_bad_reviews=bad_count,
                status=PlatformHealth.compute_status(overall_score, bad_count),
            )
            platform_healths.append(ph)

        return HealthDashboard(platforms=platform_healths)

    async def get_health_trend(
        self,
        store_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        db: AsyncSession,
        platform: Optional[str] = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """获取近N天健康度趋势（每日快照列表），支持单平台筛选"""
        from sqlalchemy import text  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        from datetime import date  # noqa: PLC0415

        cutoff = datetime.now(tz=timezone.utc).date() - timedelta(days=days)
        tbl = _PlatformHealthSnapshotRow.__table__

        conditions = [
            tbl.c.tenant_id == tid,
            tbl.c.store_id == sid,
            tbl.c.snapshot_date >= cutoff,
        ]
        if platform:
            conditions.append(tbl.c.platform == platform)

        stmt = (
            select(tbl)
            .where(and_(*conditions))
            .order_by(tbl.c.platform, tbl.c.snapshot_date.asc())
        )
        result = await db.execute(stmt)
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def upsert_health_snapshot(
        self,
        store_id: str | uuid.UUID,
        platform: str,
        tenant_id: str | uuid.UUID,
        snapshot_date: Any,  # date
        snapshot_data: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any]:
        """插入或更新平台健康度每日快照（供爬虫/数据同步任务调用）"""
        from sqlalchemy import text  # noqa: PLC0415
        from datetime import date  # noqa: PLC0415

        sid = uuid.UUID(str(store_id))
        tid = uuid.UUID(str(tenant_id))

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tid)}
        )

        tbl = _PlatformHealthSnapshotRow.__table__
        values = {
            "tenant_id": tid,
            "store_id": sid,
            "platform": platform,
            "snapshot_date": snapshot_date,
            "overall_score": snapshot_data.get("overall_score"),
            "dsr_food": snapshot_data.get("dsr_food"),
            "dsr_service": snapshot_data.get("dsr_service"),
            "dsr_delivery": snapshot_data.get("dsr_delivery"),
            "monthly_sales": snapshot_data.get("monthly_sales", 0),
            "positive_rate": snapshot_data.get("positive_rate"),
            "bad_review_count": snapshot_data.get("bad_review_count", 0),
        }

        stmt = (
            tbl.insert()
            .values(**values)
            .on_conflict_do_update(
                index_elements=["tenant_id", "store_id", "platform", "snapshot_date"],
                set_={k: v for k, v in values.items() if k not in ("tenant_id", "store_id", "platform", "snapshot_date")},
            )
            .returning(*tbl.c)
        )
        result = await db.execute(stmt)
        row = result.mappings().one()
        await db.flush()
        return dict(row)

    # ─── 内部辅助 ─────────────────────────────────────────────────────

    async def _fetch_config_row(
        self,
        store_id: uuid.UUID,
        platform: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        from sqlalchemy import text  # noqa: PLC0415

        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        tbl = _DeliveryStoreConfigRow.__table__
        stmt = select(tbl).where(
            and_(
                tbl.c.tenant_id == tenant_id,
                tbl.c.store_id == store_id,
                tbl.c.platform == platform,
            )
        )
        result = await db.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def _create_default_config(
        self,
        store_id: uuid.UUID,
        platform: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        tbl = _DeliveryStoreConfigRow.__table__
        stmt = (
            tbl.insert()
            .values(
                tenant_id=tenant_id,
                store_id=store_id,
                platform=platform,
                auto_accept=False,
                auto_accept_max_per_hour=30,
                busy_mode=False,
                busy_mode_prep_time_min=40,
                normal_prep_time_min=25,
                busy_mode_started_at=None,
                busy_mode_auto_off_at=None,
                max_delivery_distance_km=5.0,
                is_active=True,
            )
            .returning(*tbl.c)
        )
        result = await db.execute(stmt)
        row = result.mappings().one()
        await db.flush()
        return dict(row)

    async def _fetch_review_row(
        self,
        review_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        tbl = _DeliveryReviewRow.__table__
        stmt = select(tbl).where(
            and_(
                tbl.c.id == review_id,
                tbl.c.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def _get_latest_snapshot(
        self,
        store_id: uuid.UUID,
        platform: str,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[dict[str, Any]]:
        tbl = _PlatformHealthSnapshotRow.__table__
        stmt = (
            select(tbl)
            .where(
                and_(
                    tbl.c.tenant_id == tenant_id,
                    tbl.c.store_id == store_id,
                    tbl.c.platform == platform,
                )
            )
            .order_by(tbl.c.snapshot_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def _row_to_config(row: dict[str, Any]) -> DeliveryStoreConfig:
        busy = bool(row.get("busy_mode", False))
        # 自动检查 busy_mode 是否已过期
        auto_off = row.get("busy_mode_auto_off_at")
        if busy and auto_off is not None:
            now = datetime.now(tz=timezone.utc)
            if hasattr(auto_off, "tzinfo") and auto_off.tzinfo is None:
                auto_off = auto_off.replace(tzinfo=timezone.utc)
            if now >= auto_off:
                busy = False  # 逻辑过期，下次 disable_busy_mode 写库清除

        current_prep = (
            int(row.get("busy_mode_prep_time_min", 40))
            if busy
            else int(row.get("normal_prep_time_min", 25))
        )
        return DeliveryStoreConfig(
            id=row["id"],
            store_id=row["store_id"],
            platform=row["platform"],
            auto_accept=bool(row.get("auto_accept", False)),
            auto_accept_max_per_hour=int(row.get("auto_accept_max_per_hour", 30)),
            busy_mode=busy,
            busy_mode_prep_time_min=int(row.get("busy_mode_prep_time_min", 40)),
            normal_prep_time_min=int(row.get("normal_prep_time_min", 25)),
            current_prep_time_min=current_prep,
            busy_mode_started_at=row.get("busy_mode_started_at"),
            busy_mode_auto_off_at=row.get("busy_mode_auto_off_at"),
            max_delivery_distance_km=float(row.get("max_delivery_distance_km", 5.0)),
            is_active=bool(row.get("is_active", True)),
            updated_at=row["updated_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _review_row_to_model(row: dict[str, Any]) -> DeliveryReview:
        return DeliveryReview(
            id=row["id"],
            store_id=row["store_id"],
            platform=row["platform"],
            platform_order_id=row.get("platform_order_id"),
            platform_review_id=row.get("platform_review_id"),
            rating=int(row["rating"]),
            content=row.get("content"),
            tags=row.get("tags"),
            is_negative=bool(row.get("is_negative", False)),
            reply_content=row.get("reply_content"),
            replied_at=row.get("replied_at"),
            alert_sent=bool(row.get("alert_sent", False)),
            reviewed_at=row["reviewed_at"],
            created_at=row["created_at"],
        )


# ─── 轻量级 SQLAlchemy Table 代理（避免重复定义 ORM model） ─────────────────────


class _DeliveryStoreConfigRow:
    """Table accessor — maps to delivery_store_configs DDL in v039 migration"""
    from sqlalchemy import (  # noqa: PLC0415
        Table, Column, MetaData, Boolean, Integer, String, Numeric,
        DateTime,
    )
    from sqlalchemy.dialects.postgresql import UUID as _PGUUID  # noqa: PLC0415

    __table__ = None  # populated at module load below


class _DeliveryReviewRow:
    """Table accessor — maps to delivery_reviews DDL in v039 migration"""
    __table__ = None


class _PlatformHealthSnapshotRow:
    """Table accessor — maps to platform_health_snapshots DDL in v039 migration"""
    __table__ = None


def _build_tables() -> None:
    """Lazily build SQLAlchemy Table objects using reflected metadata.

    Called once on first import so tests can override the engine/metadata
    before this runs.
    """
    from sqlalchemy import (  # noqa: PLC0415
        Table, Column, MetaData, Boolean, Integer, String, Numeric,
        DateTime, Date, ARRAY, Text,
    )
    from sqlalchemy.dialects.postgresql import UUID as PGUUID  # noqa: PLC0415

    meta = MetaData()

    _DeliveryStoreConfigRow.__table__ = Table(
        "delivery_store_configs",
        meta,
        Column("id", PGUUID(as_uuid=True)),
        Column("tenant_id", PGUUID(as_uuid=True)),
        Column("store_id", PGUUID(as_uuid=True)),
        Column("platform", String(20)),
        Column("auto_accept", Boolean),
        Column("auto_accept_max_per_hour", Integer),
        Column("busy_mode", Boolean),
        Column("busy_mode_prep_time_min", Integer),
        Column("normal_prep_time_min", Integer),
        Column("busy_mode_started_at", DateTime(timezone=True)),
        Column("busy_mode_auto_off_at", DateTime(timezone=True)),
        Column("max_delivery_distance_km", Numeric(5, 2)),
        Column("is_active", Boolean),
        Column("updated_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True)),
    )

    _DeliveryReviewRow.__table__ = Table(
        "delivery_reviews",
        meta,
        Column("id", PGUUID(as_uuid=True)),
        Column("tenant_id", PGUUID(as_uuid=True)),
        Column("store_id", PGUUID(as_uuid=True)),
        Column("platform", String(20)),
        Column("platform_order_id", String(100)),
        Column("platform_review_id", String(100)),
        Column("rating", Integer),
        Column("content", Text),
        Column("tags", ARRAY(Text)),
        Column("is_negative", Boolean),
        Column("reply_content", Text),
        Column("replied_at", DateTime(timezone=True)),
        Column("alert_sent", Boolean),
        Column("reviewed_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True)),
    )

    _PlatformHealthSnapshotRow.__table__ = Table(
        "platform_health_snapshots",
        meta,
        Column("id", PGUUID(as_uuid=True)),
        Column("tenant_id", PGUUID(as_uuid=True)),
        Column("store_id", PGUUID(as_uuid=True)),
        Column("platform", String(20)),
        Column("snapshot_date", Date),
        Column("overall_score", Numeric(3, 2)),
        Column("dsr_food", Numeric(3, 2)),
        Column("dsr_service", Numeric(3, 2)),
        Column("dsr_delivery", Numeric(3, 2)),
        Column("monthly_sales", Integer),
        Column("positive_rate", Numeric(5, 4)),
        Column("bad_review_count", Integer),
        Column("created_at", DateTime(timezone=True)),
    )


_build_tables()
