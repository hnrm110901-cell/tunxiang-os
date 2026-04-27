"""门店基线计算 + 异常检测

正常不说，异常论述 — 只在指标超过2个标准差时触发预警。
使用 Welford's 在线算法实现增量更新均值和方差，避免全量重算。

基线维度：
  - metric_code: 指标代码（lunch_covers/food_cost_rate/avg_ticket_fen 等）
  - day_of_week: 星期（可选，区分工作日/周末模式）
  - slot_code: 时段（可选，区分午市/晚市/全天）

异常等级：
  - > 2σ = warning（黄色预警）
  - > 3σ = critical（红色预警，需立即处理）
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.coaching import StoreBaseline

logger = structlog.get_logger(__name__)

# 指标元数据：名称 + 单位 + 方向（higher_better / lower_better）
METRIC_META: dict[str, dict] = {
    "lunch_covers": {"name": "午市客数", "unit": "人", "direction": "higher_better"},
    "dinner_covers": {"name": "晚市客数", "unit": "人", "direction": "higher_better"},
    "food_cost_rate": {"name": "食材成本率", "unit": "%", "direction": "lower_better"},
    "labor_cost_rate": {"name": "人力成本率", "unit": "%", "direction": "lower_better"},
    "avg_ticket_fen": {"name": "客单价", "unit": "分", "direction": "higher_better"},
    "table_turnover": {"name": "翻台率", "unit": "次", "direction": "higher_better"},
    "serve_time_min": {"name": "出餐时长", "unit": "分钟", "direction": "lower_better"},
    "waste_rate": {"name": "废弃率", "unit": "%", "direction": "lower_better"},
    "takeout_count": {"name": "外卖单量", "unit": "单", "direction": "higher_better"},
    "customer_complaints": {"name": "顾客投诉", "unit": "次", "direction": "lower_better"},
}


class BaselineService:
    """门店基线管理服务 — 异常检测的数据基础"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 查询 ──────────────────────────────────────────────────────────

    async def get_baseline(
        self,
        tenant_id: str,
        store_id: str,
        metric_code: str,
        *,
        day_of_week: int | None = None,
        slot_code: str | None = None,
    ) -> dict | None:
        """获取单个指标的基线数据"""
        conditions = [
            StoreBaseline.tenant_id == UUID(tenant_id),
            StoreBaseline.store_id == UUID(store_id),
            StoreBaseline.metric_code == metric_code,
            StoreBaseline.is_deleted.is_(False),
        ]
        if day_of_week is not None:
            conditions.append(StoreBaseline.day_of_week == day_of_week)
        else:
            conditions.append(StoreBaseline.day_of_week.is_(None))

        if slot_code is not None:
            conditions.append(StoreBaseline.slot_code == slot_code)
        else:
            conditions.append(StoreBaseline.slot_code.is_(None))

        stmt = select(StoreBaseline).where(and_(*conditions))
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_dict(row)

    async def get_all_baselines(
        self,
        tenant_id: str,
        store_id: str,
        *,
        slot_code: str | None = None,
    ) -> list[dict]:
        """获取门店所有指标的基线数据"""
        conditions = [
            StoreBaseline.tenant_id == UUID(tenant_id),
            StoreBaseline.store_id == UUID(store_id),
            StoreBaseline.is_deleted.is_(False),
        ]
        if slot_code is not None:
            conditions.append(StoreBaseline.slot_code == slot_code)

        stmt = (
            select(StoreBaseline)
            .where(and_(*conditions))
            .order_by(
                StoreBaseline.metric_code,
            )
        )
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [self._to_dict(r) for r in rows]

    # ── 增量更新（Welford's 在线算法）──────────────────────────────

    async def upsert_baseline(
        self,
        tenant_id: str,
        store_id: str,
        metric_code: str,
        value: float,
        *,
        day_of_week: int | None = None,
        slot_code: str | None = None,
    ) -> dict:
        """增量更新基线 — Welford's 在线算法

        Welford 递推公式（数值稳定）：
          n = n + 1
          delta = new_value - old_mean
          new_mean = old_mean + delta / n
          delta2 = new_value - new_mean
          M2 = M2 + delta * delta2
          new_variance = M2 / n  (总体方差)
          new_std = sqrt(new_variance)
        """
        existing = await self._get_baseline_row(
            tenant_id,
            store_id,
            metric_code,
            day_of_week=day_of_week,
            slot_code=slot_code,
        )

        now = datetime.now(timezone.utc)

        if existing is None:
            # 首次插入：第一个样本，标准差为0
            baseline = StoreBaseline(
                tenant_id=UUID(tenant_id),
                store_id=UUID(store_id),
                metric_code=metric_code,
                day_of_week=day_of_week,
                slot_code=slot_code,
                baseline_value=value,
                std_deviation=0.0,
                sample_count=1,
                min_value=value,
                max_value=value,
                last_updated=now,
            )
            self.db.add(baseline)
            await self.db.flush()
            logger.info(
                "baseline.created",
                store_id=store_id,
                metric=metric_code,
                value=value,
            )
            return self._to_dict(baseline)

        # Welford's 在线更新
        n = existing.sample_count
        old_mean = existing.baseline_value

        # 重建 M2 from 已有 std_deviation 和 sample_count
        # M2 = variance * n = std^2 * n
        old_m2 = (existing.std_deviation**2) * n if n > 0 else 0.0

        n_new = n + 1
        delta = value - old_mean
        new_mean = old_mean + delta / n_new
        delta2 = value - new_mean
        new_m2 = old_m2 + delta * delta2
        new_std = math.sqrt(new_m2 / n_new) if n_new > 0 else 0.0

        new_min = min(existing.min_value, value) if existing.min_value is not None else value
        new_max = max(existing.max_value, value) if existing.max_value is not None else value

        existing.baseline_value = new_mean
        existing.std_deviation = new_std
        existing.sample_count = n_new
        existing.min_value = new_min
        existing.max_value = new_max
        existing.last_updated = now
        existing.updated_at = now
        await self.db.flush()

        logger.info(
            "baseline.updated",
            store_id=store_id,
            metric=metric_code,
            new_mean=round(new_mean, 4),
            new_std=round(new_std, 4),
            sample_count=n_new,
        )
        return self._to_dict(existing)

    # ── 从历史数据重建 ────────────────────────────────────────────

    async def rebuild_from_history(
        self,
        tenant_id: str,
        store_id: str,
        metric_code: str,
        values: list[float],
        *,
        day_of_week: int | None = None,
        slot_code: str | None = None,
    ) -> dict:
        """从历史数据完全重建基线

        用于初始化或修正错误的基线。传入全部历史值，计算均值/标准差/极值。
        """
        if not values:
            raise ValueError("至少需要1个历史值来重建基线")

        mean_val = statistics.mean(values)
        std_val = statistics.pstdev(values) if len(values) > 1 else 0.0
        min_val = min(values)
        max_val = max(values)
        now = datetime.now(timezone.utc)

        existing = await self._get_baseline_row(
            tenant_id,
            store_id,
            metric_code,
            day_of_week=day_of_week,
            slot_code=slot_code,
        )

        if existing is None:
            baseline = StoreBaseline(
                tenant_id=UUID(tenant_id),
                store_id=UUID(store_id),
                metric_code=metric_code,
                day_of_week=day_of_week,
                slot_code=slot_code,
                baseline_value=mean_val,
                std_deviation=std_val,
                sample_count=len(values),
                min_value=min_val,
                max_value=max_val,
                last_updated=now,
            )
            self.db.add(baseline)
            await self.db.flush()
            result = baseline
        else:
            existing.baseline_value = mean_val
            existing.std_deviation = std_val
            existing.sample_count = len(values)
            existing.min_value = min_val
            existing.max_value = max_val
            existing.last_updated = now
            existing.updated_at = now
            await self.db.flush()
            result = existing

        logger.info(
            "baseline.rebuilt",
            store_id=store_id,
            metric=metric_code,
            mean=round(mean_val, 4),
            std=round(std_val, 4),
            samples=len(values),
        )
        return self._to_dict(result)

    # ── 异常检测 ──────────────────────────────────────────────────

    async def detect_anomalies(
        self,
        tenant_id: str,
        store_id: str,
        current_metrics: dict[str, float],
        *,
        slot_code: str | None = None,
        threshold_sigma: float = 2.0,
    ) -> list[dict]:
        """异常检测 — 正常不说，异常论述

        对比当前指标与基线，超过 threshold_sigma 个标准差视为异常。

        返回异常列表（无异常则返回空列表）：
          [{
            metric, metric_name, current, baseline, std_dev,
            sigma, direction(above/below),
            severity(warning/critical)
          }]
        """
        baselines = await self.get_all_baselines(
            tenant_id,
            store_id,
            slot_code=slot_code,
        )

        # 构建 metric_code → baseline 映射
        baseline_map: dict[str, dict] = {}
        for b in baselines:
            key = b["metric_code"]
            baseline_map[key] = b

        anomalies: list[dict] = []

        for metric_code, current_value in current_metrics.items():
            bl = baseline_map.get(metric_code)
            if bl is None:
                # 没有基线数据，跳过
                continue

            baseline_val = bl["baseline_value"]
            std_dev = bl["std_deviation"]

            # 标准差为0或样本太少，无法判断异常
            if std_dev <= 0 or bl["sample_count"] < 3:
                continue

            deviation = current_value - baseline_val
            sigma = abs(deviation) / std_dev

            if sigma < threshold_sigma:
                continue

            # 判断方向
            direction = "above" if deviation > 0 else "below"

            # 判断严重度
            severity = "critical" if sigma >= 3.0 else "warning"

            meta = METRIC_META.get(metric_code, {})

            anomalies.append(
                {
                    "metric": metric_code,
                    "metric_name": meta.get("name", metric_code),
                    "unit": meta.get("unit", ""),
                    "current": current_value,
                    "baseline": round(baseline_val, 2),
                    "std_dev": round(std_dev, 4),
                    "sigma": round(sigma, 2),
                    "direction": direction,
                    "severity": severity,
                    "is_positive": self._is_positive_anomaly(
                        metric_code,
                        direction,
                    ),
                }
            )

        # 按 sigma 降序排列（最异常的在前）
        anomalies.sort(key=lambda x: x["sigma"], reverse=True)

        if anomalies:
            logger.info(
                "baseline.anomalies_detected",
                store_id=store_id,
                count=len(anomalies),
                metrics=[a["metric"] for a in anomalies],
            )

        return anomalies

    # ── 批量更新 ──────────────────────────────────────────────────

    async def batch_update(
        self,
        tenant_id: str,
        store_id: str,
        metrics: dict[str, float],
        *,
        day_of_week: int | None = None,
        slot_code: str | None = None,
    ) -> int:
        """批量更新多个指标基线

        返回成功更新的指标数量。
        """
        updated = 0
        for metric_code, value in metrics.items():
            try:
                await self.upsert_baseline(
                    tenant_id,
                    store_id,
                    metric_code,
                    value,
                    day_of_week=day_of_week,
                    slot_code=slot_code,
                )
                updated += 1
            except ValueError as e:
                logger.warning(
                    "baseline.batch_update_skip",
                    metric=metric_code,
                    error=str(e),
                )

        logger.info(
            "baseline.batch_updated",
            store_id=store_id,
            updated=updated,
            total=len(metrics),
        )
        return updated

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _get_baseline_row(
        self,
        tenant_id: str,
        store_id: str,
        metric_code: str,
        *,
        day_of_week: int | None = None,
        slot_code: str | None = None,
    ) -> StoreBaseline | None:
        """获取基线 ORM 行"""
        conditions = [
            StoreBaseline.tenant_id == UUID(tenant_id),
            StoreBaseline.store_id == UUID(store_id),
            StoreBaseline.metric_code == metric_code,
            StoreBaseline.is_deleted.is_(False),
        ]
        if day_of_week is not None:
            conditions.append(StoreBaseline.day_of_week == day_of_week)
        else:
            conditions.append(StoreBaseline.day_of_week.is_(None))

        if slot_code is not None:
            conditions.append(StoreBaseline.slot_code == slot_code)
        else:
            conditions.append(StoreBaseline.slot_code.is_(None))

        stmt = select(StoreBaseline).where(and_(*conditions))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _is_positive_anomaly(metric_code: str, direction: str) -> bool:
        """判断异常方向是否积极

        例：客数高于基线是好事，食材成本率高于基线是坏事。
        """
        meta = METRIC_META.get(metric_code, {})
        preferred = meta.get("direction", "higher_better")
        if preferred == "higher_better":
            return direction == "above"
        return direction == "below"

    @staticmethod
    def _to_dict(row: StoreBaseline) -> dict:
        """ORM 行转字典"""
        meta = METRIC_META.get(row.metric_code, {})
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "store_id": str(row.store_id),
            "metric_code": row.metric_code,
            "metric_name": meta.get("name", row.metric_code),
            "unit": meta.get("unit", ""),
            "day_of_week": row.day_of_week,
            "slot_code": row.slot_code,
            "baseline_value": round(row.baseline_value, 4),
            "std_deviation": round(row.std_deviation, 4),
            "sample_count": row.sample_count,
            "min_value": round(row.min_value, 4) if row.min_value is not None else None,
            "max_value": round(row.max_value, 4) if row.max_value is not None else None,
            "last_updated": row.last_updated.isoformat() if row.last_updated else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
