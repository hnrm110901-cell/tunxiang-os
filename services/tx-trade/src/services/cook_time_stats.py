"""菜品制作时间统计基准服务

核心能力：
1. recompute_baselines — 从kds_tasks历史数据重算dish×时段的P50/P90基准
2. get_expected_duration — 返回当前时段的预期制作时间（秒）
3. estimate_queue_clear_time — 预估档口队列清空时间
4. get_dept_timeout_thresholds — 返回动态超时阈值（替代固定25分钟）

依赖说明：
- kds_tasks 表由 P1-A 并行开发创建，本服务对其不存在的情况做优雅降级
- 所有查询必须显式传入 tenant_id，禁止通过上下文隐式传递
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import and_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.cook_time_baseline import MIN_RELIABLE_SAMPLES, CookTimeBaseline
from ..models.production_dept import ProductionDept

logger = structlog.get_logger()

# ─── 常量 ───

# 档口默认并发烹饪能力（多少道菜同时在制作）
DEFAULT_CONCURRENT_CAPACITY = 2

# fallback系数：dept.default_timeout_minutes * FALLBACK_RATIO = 预估秒数
FALLBACK_RATIO = 0.6

# P90的多少倍作为warn阈值
WARN_RATIO = 0.8


def _get_day_type(dt: datetime) -> str:
    """判断日期类型：weekday(周一至周五) / weekend(周六周日)"""
    return "weekend" if dt.weekday() >= 5 else "weekday"


class CookTimeStatsService:
    """菜品制作时间统计基准服务

    Usage:
        service = CookTimeStatsService(db)
        await service.recompute_baselines(tenant_id)
        duration = await service.get_expected_duration(dish_id, dept_id, tenant_id)
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────

    async def recompute_baselines(
        self,
        tenant_id: str,
        dept_id: Optional[str] = None,
    ) -> list[dict]:
        """从kds_tasks历史数据重新计算制作时间基准。

        使用 PostgreSQL PERCENTILE_CONT 计算 P50/P90。
        kds_tasks表不存在时优雅降级，返回空列表并记录警告日志。

        Args:
            tenant_id: 租户ID（必填，隔离数据）
            dept_id: 仅重算指定档口，None表示重算该租户所有档口

        Returns:
            [{"dish_id": ..., "dept_id": ..., "hour_bucket": ..., "day_type": ...,
              "p50_seconds": ..., "p90_seconds": ..., "sample_count": ...}, ...]
        """
        tid = uuid.UUID(tenant_id)
        log = logger.bind(tenant_id=tenant_id, dept_id=dept_id)

        # 构建 SQL — PERCENTILE_CONT 需要原生SQL
        dept_filter = ""
        params: dict = {"tenant_id": str(tid)}
        if dept_id:
            dept_filter = "AND dept_id = :dept_id"
            params["dept_id"] = dept_id

        sql = text(f"""
            SELECT
                dish_id,
                dept_id,
                EXTRACT(hour FROM started_at)::int AS hour_bucket,
                CASE WHEN EXTRACT(dow FROM started_at) >= 5 THEN 'weekend' ELSE 'weekday' END AS day_type,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                    EXTRACT(epoch FROM (completed_at - started_at))
                )::int AS p50,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
                    EXTRACT(epoch FROM (completed_at - started_at))
                )::int AS p90,
                COUNT(*) AS sample_count
            FROM kds_tasks
            WHERE
                completed_at IS NOT NULL
                AND started_at IS NOT NULL
                AND tenant_id = :tenant_id::uuid
                {dept_filter}
            GROUP BY dish_id, dept_id, hour_bucket, day_type
        """)

        try:
            result = await self._db.execute(sql, params)
            rows = result.all()
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄（kds_tasks表可能不存在）
            # kds_tasks表可能还不存在（P1-A并行开发中）
            log.warning(
                "cook_time_stats.recompute.kds_tasks_unavailable",
                error=str(exc),
            )
            return []

        now = datetime.now(timezone.utc)
        baselines = []

        for row in rows:
            dish_id_val = row.dish_id
            dept_id_val = row.dept_id
            hour_bucket = int(row.hour_bucket)
            day_type = row.day_type
            p50 = int(row.p50) if row.p50 is not None else 0
            p90 = int(row.p90) if row.p90 is not None else 0
            sample_count = int(row.sample_count)

            # 跳过无效数据
            if p50 <= 0 or p90 <= 0:
                continue

            # upsert baseline
            await self._upsert_baseline(
                tenant_id=tid,
                dish_id=dish_id_val,
                dept_id=dept_id_val,
                hour_bucket=hour_bucket,
                day_type=day_type,
                p50_seconds=p50,
                p90_seconds=p90,
                sample_count=sample_count,
                computed_at=now,
            )

            baselines.append(
                {
                    "dish_id": str(dish_id_val),
                    "dept_id": str(dept_id_val),
                    "hour_bucket": hour_bucket,
                    "day_type": day_type,
                    "p50_seconds": p50,
                    "p90_seconds": p90,
                    "sample_count": sample_count,
                }
            )

        log.info(
            "cook_time_stats.recompute.done",
            baselines_computed=len(baselines),
        )
        return baselines

    async def get_expected_duration(
        self,
        dish_id: str,
        dept_id: str,
        tenant_id: str,
        at_time: Optional[datetime] = None,
        hour_override: Optional[int] = None,
    ) -> int:
        """获取预期制作时间（秒）。

        优先级：
        1. 当前时段的历史baseline（P50）且样本数>=10
        2. 不可靠baseline（<10样本）降级到dept默认值
        3. 无baseline → dept.default_timeout_minutes * FALLBACK_RATIO

        Args:
            dish_id: 菜品ID
            dept_id: 档口ID
            tenant_id: 租户ID
            at_time: 参考时间（默认当前时间）
            hour_override: 强制指定时段（测试用）

        Returns:
            预期制作时间（秒）
        """
        result = await self.get_expected_duration_with_meta(
            dish_id, dept_id, tenant_id, at_time=at_time, hour_override=hour_override
        )
        return result["estimated_seconds"]

    async def get_expected_duration_with_meta(
        self,
        dish_id: str,
        dept_id: str,
        tenant_id: str,
        at_time: Optional[datetime] = None,
        hour_override: Optional[int] = None,
    ) -> dict:
        """获取预期制作时间，附带来源元数据。

        Returns:
            {
                "estimated_seconds": int,
                "source": "baseline" | "dept_default",
                "reliable": bool,
                "p50_seconds": int | None,
                "p90_seconds": int | None,
                "sample_count": int | None,
            }
        """
        now = at_time or datetime.now(timezone.utc)
        hour_bucket = hour_override if hour_override is not None else now.hour
        day_type = _get_day_type(now)

        log = logger.bind(
            dish_id=dish_id,
            dept_id=dept_id,
            tenant_id=tenant_id,
            hour_bucket=hour_bucket,
        )

        baseline = await self._get_baseline_from_db(dish_id, dept_id, tenant_id, hour_bucket, day_type)

        if baseline is not None and baseline["sample_count"] >= MIN_RELIABLE_SAMPLES:
            log.debug("cook_time_stats.duration.from_baseline")
            return {
                "estimated_seconds": baseline["p50_seconds"],
                "source": "baseline",
                "reliable": True,
                "p50_seconds": baseline["p50_seconds"],
                "p90_seconds": baseline["p90_seconds"],
                "sample_count": baseline["sample_count"],
            }

        if baseline is not None and baseline["sample_count"] > 0:
            # 样本不足，baseline存在但不可靠
            log.debug("cook_time_stats.duration.baseline_unreliable", sample_count=baseline["sample_count"])
            return {
                "estimated_seconds": baseline["p50_seconds"],
                "source": "baseline",
                "reliable": False,
                "p50_seconds": baseline["p50_seconds"],
                "p90_seconds": baseline["p90_seconds"],
                "sample_count": baseline["sample_count"],
            }

        # fallback到dept默认值
        default_minutes = await self._get_dept_default_minutes(dept_id, tenant_id)
        fallback_seconds = int(default_minutes * FALLBACK_RATIO * 60)

        log.info(
            "cook_time_stats.duration.dept_default_fallback",
            default_minutes=default_minutes,
            fallback_seconds=fallback_seconds,
        )
        return {
            "estimated_seconds": fallback_seconds,
            "source": "dept_default",
            "reliable": False,
            "p50_seconds": None,
            "p90_seconds": None,
            "sample_count": None,
        }

    async def estimate_queue_clear_time(
        self,
        dept_id: str,
        tenant_id: str,
        concurrent_capacity: int = DEFAULT_CONCURRENT_CAPACITY,
    ) -> dict:
        """预估档口队列清空时间。

        算法（简单版）：
          total_seconds = sum(get_expected_duration(item) for item in pending+cooking)
          clear_time = now + total_seconds / concurrent_capacity

        Args:
            dept_id: 档口ID
            tenant_id: 租户ID
            concurrent_capacity: 并发烹饪能力（默认2道菜同时进行）

        Returns:
            {
                "estimated_clear_at": datetime,
                "pending_count": int,
                "total_expected_seconds": int,
                "concurrent_capacity": int,
            }
        """
        tid = uuid.UUID(tenant_id)
        log = logger.bind(dept_id=dept_id, tenant_id=tenant_id)

        # 查询pending和cooking状态的任务
        try:
            pending_sql = text("""
                SELECT kt.order_item_id, oi.dish_id
                FROM kds_tasks kt
                LEFT JOIN order_items oi ON oi.id = kt.order_item_id
                WHERE kt.dept_id = :dept_id::uuid
                  AND kt.tenant_id = :tenant_id::uuid
                  AND kt.status IN ('pending', 'cooking')
            """)
            result = await self._db.execute(
                pending_sql,
                {
                    "dept_id": dept_id,
                    "tenant_id": tenant_id,
                },
            )
            rows = result.all()
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            log.warning("cook_time_stats.queue_estimate.query_failed", error=str(exc))
            rows = []

        now = datetime.now(timezone.utc)
        total_seconds = 0

        for row in rows:
            dish_id = str(row.dish_id) if row.dish_id else None
            if dish_id:
                duration = await self.get_expected_duration(dish_id, dept_id, tenant_id)
            else:
                # 无dish_id时用档口默认值的fallback
                default_minutes = await self._get_dept_default_minutes(dept_id, tenant_id)
                duration = int(default_minutes * FALLBACK_RATIO * 60)
            total_seconds += duration

        cap = max(concurrent_capacity, 1)
        clear_seconds = total_seconds / cap
        estimated_clear_at = now + timedelta(seconds=clear_seconds)

        log.info(
            "cook_time_stats.queue_estimate.done",
            pending_count=len(rows),
            total_expected_seconds=total_seconds,
            concurrent_capacity=cap,
            clear_seconds=round(clear_seconds),
        )

        return {
            "estimated_clear_at": estimated_clear_at,
            "pending_count": len(rows),
            "total_expected_seconds": total_seconds,
            "concurrent_capacity": cap,
        }

    async def get_dept_timeout_thresholds(
        self,
        dept_id: str,
        dish_id: str,
        tenant_id: str,
        at_time: Optional[datetime] = None,
    ) -> dict:
        """获取动态超时阈值（替代固定25分钟配置）。

        Returns:
            {
                "warn_seconds": int,      # p90 * WARN_RATIO（接近超时开始预警）
                "critical_seconds": int,  # p90（已超时）
                "source": "baseline" | "dept_default",
            }
        """
        now = at_time or datetime.now(timezone.utc)
        hour_bucket = now.hour
        day_type = _get_day_type(now)

        baseline = await self._get_baseline_from_db(dish_id, dept_id, tenant_id, hour_bucket, day_type)

        if baseline is not None and baseline["sample_count"] >= MIN_RELIABLE_SAMPLES:
            p90 = baseline["p90_seconds"]
            return {
                "warn_seconds": int(p90 * WARN_RATIO),
                "critical_seconds": p90,
                "source": "baseline",
            }

        # fallback到dept默认超时（传统固定配置）
        default_minutes = await self._get_dept_default_minutes(dept_id, tenant_id)
        critical = default_minutes * 60
        return {
            "warn_seconds": int(critical * WARN_RATIO),
            "critical_seconds": critical,
            "source": "dept_default",
        }

    async def get_dept_baselines(
        self,
        dept_id: str,
        tenant_id: str,
    ) -> list[dict]:
        """查询档口当前所有有效的基准数据。

        Returns:
            [{dish_id, hour_bucket, day_type, p50_seconds, p90_seconds,
              sample_count, computed_at, is_reliable}, ...]
        """
        tid = uuid.UUID(tenant_id)
        dept_uuid = uuid.UUID(dept_id)

        stmt = (
            select(CookTimeBaseline)
            .where(
                and_(
                    CookTimeBaseline.tenant_id == tid,
                    CookTimeBaseline.dept_id == dept_uuid,
                    CookTimeBaseline.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(
                CookTimeBaseline.dish_id,
                CookTimeBaseline.hour_bucket,
                CookTimeBaseline.day_type,
            )
        )

        try:
            result = await self._db.execute(stmt)
            baselines = result.scalars().all()
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.warning(
                "cook_time_stats.get_dept_baselines.failed",
                dept_id=dept_id,
                error=str(exc),
            )
            return []

        return [
            {
                "dish_id": str(b.dish_id),
                "dept_id": str(b.dept_id),
                "hour_bucket": b.hour_bucket,
                "day_type": b.day_type,
                "p50_seconds": b.p50_seconds,
                "p90_seconds": b.p90_seconds,
                "sample_count": b.sample_count,
                "computed_at": b.computed_at.isoformat() if b.computed_at else None,
                "is_reliable": b.is_reliable,
            }
            for b in baselines
        ]

    # ─────────────────────────────────────────────
    # 内部方法
    # ─────────────────────────────────────────────

    async def _get_baseline_from_db(
        self,
        dish_id: str,
        dept_id: str,
        tenant_id: str,
        hour_bucket: int,
        day_type: str,
    ) -> Optional[dict]:
        """从cook_time_baselines表查询单条基准数据。

        Returns:
            {"p50_seconds": int, "p90_seconds": int, "sample_count": int} or None
        """
        try:
            tid = uuid.UUID(tenant_id)
            dish_uuid = uuid.UUID(dish_id)
            dept_uuid = uuid.UUID(dept_id)
        except ValueError as exc:
            logger.warning("cook_time_stats._get_baseline.invalid_uuid", error=str(exc))
            return None

        stmt = (
            select(CookTimeBaseline)
            .where(
                and_(
                    CookTimeBaseline.tenant_id == tid,
                    CookTimeBaseline.dish_id == dish_uuid,
                    CookTimeBaseline.dept_id == dept_uuid,
                    CookTimeBaseline.hour_bucket == hour_bucket,
                    CookTimeBaseline.day_type == day_type,
                    CookTimeBaseline.is_deleted == False,  # noqa: E712
                )
            )
            .limit(1)
        )

        try:
            result = await self._db.execute(stmt)
            baseline = result.scalar_one_or_none()
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.warning(
                "cook_time_stats._get_baseline.query_failed",
                dish_id=dish_id,
                dept_id=dept_id,
                error=str(exc),
            )
            return None

        if baseline is None:
            return None

        return {
            "p50_seconds": baseline.p50_seconds,
            "p90_seconds": baseline.p90_seconds,
            "sample_count": baseline.sample_count,
        }

    async def _get_dept_default_minutes(self, dept_id: str, tenant_id: str) -> int:
        """查询档口默认出品时限（分钟）。

        Returns:
            档口设置的 default_timeout_minutes，查询失败时返回25（行业通用默认值）
        """
        try:
            tid = uuid.UUID(tenant_id)
            dept_uuid = uuid.UUID(dept_id)
        except ValueError:
            return 25

        stmt = (
            select(ProductionDept.default_timeout_minutes)
            .where(
                and_(
                    ProductionDept.tenant_id == tid,
                    ProductionDept.id == dept_uuid,
                    ProductionDept.is_deleted == False,  # noqa: E712
                )
            )
            .limit(1)
        )

        try:
            result = await self._db.execute(stmt)
            minutes = result.scalar_one_or_none()
            return int(minutes) if minutes and minutes > 0 else 25
        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.warning(
                "cook_time_stats._get_dept_default.query_failed",
                dept_id=dept_id,
                error=str(exc),
            )
            return 25

    async def _upsert_baseline(
        self,
        *,
        tenant_id: uuid.UUID,
        dish_id: uuid.UUID,
        dept_id: uuid.UUID,
        hour_bucket: int,
        day_type: str,
        p50_seconds: int,
        p90_seconds: int,
        sample_count: int,
        computed_at: datetime,
    ) -> None:
        """插入或更新基准记录（按 tenant+dish+dept+hour+day_type 唯一）"""
        # 先查是否存在
        stmt = (
            select(CookTimeBaseline)
            .where(
                and_(
                    CookTimeBaseline.tenant_id == tenant_id,
                    CookTimeBaseline.dish_id == dish_id,
                    CookTimeBaseline.dept_id == dept_id,
                    CookTimeBaseline.hour_bucket == hour_bucket,
                    CookTimeBaseline.day_type == day_type,
                    CookTimeBaseline.is_deleted == False,  # noqa: E712
                )
            )
            .limit(1)
        )

        try:
            result = await self._db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is not None:
                existing.p50_seconds = p50_seconds
                existing.p90_seconds = p90_seconds
                existing.sample_count = sample_count
                existing.computed_at = computed_at
                self._db.add(existing)
            else:
                new_baseline = CookTimeBaseline(
                    tenant_id=tenant_id,
                    dish_id=dish_id,
                    dept_id=dept_id,
                    hour_bucket=hour_bucket,
                    day_type=day_type,
                    p50_seconds=p50_seconds,
                    p90_seconds=p90_seconds,
                    sample_count=sample_count,
                    computed_at=computed_at,
                )
                self._db.add(new_baseline)

            await self._db.flush()

        except SQLAlchemyError as exc:  # MLPS3-P0: 异常收窄
            logger.warning(
                "cook_time_stats._upsert_baseline.failed",
                dish_id=str(dish_id),
                dept_id=str(dept_id),
                error=str(exc),
            )
