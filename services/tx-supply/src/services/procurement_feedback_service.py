"""采购建议 -> 实际结果反馈闭环

每日收货完成后自动记录:
  建议量 vs 实际采购量 vs 实际消耗量 -> 偏差率 -> 修正系数

修正系数算法:
  最近30天偏差均值 -> EMA(指数移动平均, alpha=0.3)
  correction = 1.0 + EMA(deviation_pct / 100)
  限制在 [0.7, 1.5] 区间, 防止极端修正

金额单位: 分(fen)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  修正系数常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CORRECTION_MIN = 0.7
CORRECTION_MAX = 1.5
CORRECTION_DEFAULT = 1.0
EMA_ALPHA = 0.3
DEFAULT_LOOKBACK_DAYS = 30


class ProcurementFeedbackService:
    """采购反馈闭环服务

    职责:
    - 记录采购建议 vs 实际结果
    - 计算偏差率和修正系数 (EMA)
    - 提供预测准确率统计 (MAPE)
    - 汇总反馈报告
    """

    # ──────────────────────────────────────────────────────
    #  RLS set_config
    # ──────────────────────────────────────────────────────

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ──────────────────────────────────────────────────────
    #  录入反馈
    # ──────────────────────────────────────────────────────

    async def record_feedback(
        self,
        store_id: str,
        ingredient_id: str,
        recommended_qty: float,
        actual_purchased_qty: float | None,
        actual_consumed_qty: float | None,
        tenant_id: str,
        db: AsyncSession,
        *,
        feedback_date: date | None = None,
        weather_condition: str | None = None,
        is_holiday: bool = False,
        holiday_name: str | None = None,
        waste_qty: float = 0.0,
    ) -> dict[str, Any]:
        """写入采购反馈日志

        deviation_pct = (actual_consumed - recommended) / recommended * 100

        Args:
            store_id: 门店ID
            ingredient_id: 原料ID
            recommended_qty: 建议采购量
            actual_purchased_qty: 实际采购量
            actual_consumed_qty: 实际消耗量
            tenant_id: 租户ID
            db: 数据库会话
            feedback_date: 反馈日期 (默认今天)
            weather_condition: 天气 (sunny/cloudy/rainy/heavy_rain/snow)
            is_holiday: 是否节假日
            holiday_name: 节假日名称
            waste_qty: 浪费量

        Returns:
            反馈记录字典
        """
        await self._set_tenant(db, tenant_id)

        if feedback_date is None:
            feedback_date = date.today()

        # 计算偏差率
        deviation_pct: float | None = None
        if actual_consumed_qty is not None and recommended_qty > 0:
            deviation_pct = round(
                (actual_consumed_qty - recommended_qty) / recommended_qty * 100,
                2,
            )

        # 计算当前修正系数
        correction = await self.compute_correction_factor(
            ingredient_id=ingredient_id,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )

        feedback_id = str(uuid.uuid4())

        sql = text("""
            INSERT INTO procurement_feedback_logs (
                id, tenant_id, store_id, ingredient_id, feedback_date,
                recommended_qty, actual_purchased_qty, actual_consumed_qty,
                waste_qty, deviation_pct, weather_condition,
                is_holiday, holiday_name, correction_factor
            ) VALUES (
                :id, :tenant_id, :store_id::UUID, :ingredient_id::UUID,
                :feedback_date, :recommended_qty, :actual_purchased_qty,
                :actual_consumed_qty, :waste_qty, :deviation_pct,
                :weather_condition, :is_holiday, :holiday_name,
                :correction_factor
            )
            RETURNING id, feedback_date, deviation_pct, correction_factor
        """)

        result = await db.execute(
            sql,
            {
                "id": feedback_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "ingredient_id": ingredient_id,
                "feedback_date": feedback_date,
                "recommended_qty": recommended_qty,
                "actual_purchased_qty": actual_purchased_qty,
                "actual_consumed_qty": actual_consumed_qty,
                "waste_qty": waste_qty,
                "deviation_pct": deviation_pct,
                "weather_condition": weather_condition,
                "is_holiday": is_holiday,
                "holiday_name": holiday_name,
                "correction_factor": correction,
            },
        )
        row = result.fetchone()
        await db.commit()

        log.info(
            "procurement_feedback.recorded",
            feedback_id=feedback_id,
            store_id=store_id,
            ingredient_id=ingredient_id,
            recommended_qty=recommended_qty,
            actual_consumed_qty=actual_consumed_qty,
            deviation_pct=deviation_pct,
            correction_factor=correction,
        )

        return {
            "ok": True,
            "feedback_id": feedback_id,
            "feedback_date": feedback_date.isoformat(),
            "store_id": store_id,
            "ingredient_id": ingredient_id,
            "recommended_qty": recommended_qty,
            "actual_purchased_qty": actual_purchased_qty,
            "actual_consumed_qty": actual_consumed_qty,
            "waste_qty": waste_qty,
            "deviation_pct": deviation_pct,
            "correction_factor": correction,
        }

    # ──────────────────────────────────────────────────────
    #  计算修正系数 (EMA)
    # ──────────────────────────────────────────────────────

    async def compute_correction_factor(
        self,
        ingredient_id: str,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> float:
        """计算修正系数 (EMA 指数移动平均)

        算法:
          1. 查最近 lookback_days 天的 deviation_pct
          2. 按时间正序排列, 用 EMA(alpha=0.3) 加权
          3. correction = 1.0 + EMA(deviation_pct / 100)
          4. 限制在 [0.7, 1.5] 区间

        Args:
            ingredient_id: 原料ID
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            lookback_days: 回溯天数

        Returns:
            修正系数 (0.7~1.5)
        """
        await self._set_tenant(db, tenant_id)

        since_date = date.today() - timedelta(days=lookback_days)

        sql = text("""
            SELECT deviation_pct
            FROM procurement_feedback_logs
            WHERE tenant_id = :tenant_id
              AND ingredient_id = :ingredient_id::UUID
              AND store_id = :store_id::UUID
              AND feedback_date >= :since_date
              AND is_deleted = FALSE
              AND deviation_pct IS NOT NULL
            ORDER BY feedback_date ASC, created_at ASC
        """)

        try:
            result = await db.execute(
                sql,
                {
                    "tenant_id": tenant_id,
                    "ingredient_id": ingredient_id,
                    "store_id": store_id,
                    "since_date": since_date,
                },
            )
            rows = result.fetchall()
        except (SQLAlchemyError, OperationalError) as exc:
            log.warning(
                "procurement_feedback.correction_query_failed",
                ingredient_id=ingredient_id,
                store_id=store_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return CORRECTION_DEFAULT

        if not rows:
            return CORRECTION_DEFAULT

        # EMA 计算: 对 deviation_pct 序列做指数移动平均
        ema = 0.0
        for row in rows:
            deviation = float(row.deviation_pct)
            ema = EMA_ALPHA * deviation + (1 - EMA_ALPHA) * ema

        correction = 1.0 + ema / 100.0
        correction = max(CORRECTION_MIN, min(CORRECTION_MAX, correction))
        correction = round(correction, 3)

        log.info(
            "procurement_feedback.correction_computed",
            ingredient_id=ingredient_id,
            store_id=store_id,
            data_points=len(rows),
            ema_deviation=round(ema, 2),
            correction=correction,
        )
        return correction

    # ──────────────────────────────────────────────────────
    #  预测准确率统计 (MAPE)
    # ──────────────────────────────────────────────────────

    async def get_forecast_accuracy(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """预测准确率统计

        使用 MAPE (Mean Absolute Percentage Error) 指标:
          MAPE = AVG(|actual_consumed - recommended| / actual_consumed) * 100

        同时计算:
          - 平均偏差率
          - 偏差率分布 (正负/大小)
          - 准确率 = 100 - MAPE

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            period_days: 统计周期 (天)

        Returns:
            准确率统计字典
        """
        await self._set_tenant(db, tenant_id)

        since_date = date.today() - timedelta(days=period_days)

        sql = text("""
            SELECT
                ingredient_id,
                recommended_qty,
                actual_consumed_qty,
                deviation_pct,
                feedback_date
            FROM procurement_feedback_logs
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id::UUID
              AND feedback_date >= :since_date
              AND is_deleted = FALSE
              AND actual_consumed_qty IS NOT NULL
              AND actual_consumed_qty > 0
              AND recommended_qty > 0
            ORDER BY feedback_date ASC
        """)

        result = await db.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "since_date": since_date,
            },
        )
        rows = result.fetchall()

        if not rows:
            return {
                "store_id": store_id,
                "period_days": period_days,
                "data_points": 0,
                "mape": None,
                "accuracy_pct": None,
                "avg_deviation_pct": None,
                "message": "统计周期内无有效反馈数据",
            }

        # 计算 MAPE 和其他指标
        abs_pct_errors: list[float] = []
        deviations: list[float] = []
        over_predict_count = 0
        under_predict_count = 0
        accurate_count = 0  # |deviation| < 5%

        # 按原料分组统计
        ingredient_stats: dict[str, dict[str, Any]] = {}

        for row in rows:
            recommended = float(row.recommended_qty)
            actual = float(row.actual_consumed_qty)
            ape = abs(actual - recommended) / actual * 100
            abs_pct_errors.append(ape)

            dev = float(row.deviation_pct) if row.deviation_pct is not None else 0.0
            deviations.append(dev)

            if dev > 5:
                under_predict_count += 1
            elif dev < -5:
                over_predict_count += 1
            else:
                accurate_count += 1

            ing_id = str(row.ingredient_id)
            if ing_id not in ingredient_stats:
                ingredient_stats[ing_id] = {
                    "ingredient_id": ing_id,
                    "count": 0,
                    "total_ape": 0.0,
                    "total_deviation": 0.0,
                }
            ingredient_stats[ing_id]["count"] += 1
            ingredient_stats[ing_id]["total_ape"] += ape
            ingredient_stats[ing_id]["total_deviation"] += dev

        mape = sum(abs_pct_errors) / len(abs_pct_errors)
        accuracy_pct = max(0.0, 100.0 - mape)
        avg_deviation = sum(deviations) / len(deviations)

        # 按原料的MAPE排行 (最差的前5)
        worst_ingredients: list[dict[str, Any]] = []
        for stats in ingredient_stats.values():
            ing_mape = stats["total_ape"] / stats["count"]
            worst_ingredients.append({
                "ingredient_id": stats["ingredient_id"],
                "mape": round(ing_mape, 2),
                "avg_deviation_pct": round(stats["total_deviation"] / stats["count"], 2),
                "data_points": stats["count"],
            })
        worst_ingredients.sort(key=lambda x: x["mape"], reverse=True)

        result_data = {
            "store_id": store_id,
            "period_days": period_days,
            "data_points": len(rows),
            "mape": round(mape, 2),
            "accuracy_pct": round(accuracy_pct, 2),
            "avg_deviation_pct": round(avg_deviation, 2),
            "deviation_distribution": {
                "accurate_count": accurate_count,       # |dev| < 5%
                "over_predict_count": over_predict_count,   # dev < -5%
                "under_predict_count": under_predict_count,  # dev > 5%
            },
            "worst_ingredients": worst_ingredients[:5],
        }

        log.info(
            "procurement_feedback.accuracy_report",
            store_id=store_id,
            period_days=period_days,
            data_points=len(rows),
            mape=round(mape, 2),
            accuracy_pct=round(accuracy_pct, 2),
        )
        return result_data

    # ──────────────────────────────────────────────────────
    #  反馈汇总报告
    # ──────────────────────────────────────────────────────

    async def get_feedback_summary(
        self,
        store_id: str,
        start_date: date,
        end_date: date,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """反馈汇总报告

        按原料维度汇总:
        - 总反馈次数
        - 平均偏差率
        - 平均浪费量
        - 修正系数
        - 天气/节假日分布

        Args:
            store_id: 门店ID
            start_date: 开始日期
            end_date: 结束日期
            tenant_id: 租户ID
            db: 数据库会话

        Returns:
            汇总报告字典
        """
        await self._set_tenant(db, tenant_id)

        # 按原料汇总
        sql_by_ingredient = text("""
            SELECT
                pfl.ingredient_id,
                i.name AS ingredient_name,
                COUNT(*) AS feedback_count,
                AVG(pfl.deviation_pct) AS avg_deviation_pct,
                AVG(ABS(pfl.deviation_pct)) AS avg_abs_deviation_pct,
                SUM(pfl.waste_qty) AS total_waste_qty,
                AVG(pfl.correction_factor) AS avg_correction
            FROM procurement_feedback_logs pfl
            LEFT JOIN ingredients i ON i.id = pfl.ingredient_id
                AND i.tenant_id = pfl.tenant_id
            WHERE pfl.tenant_id = :tenant_id
              AND pfl.store_id = :store_id::UUID
              AND pfl.feedback_date BETWEEN :start_date AND :end_date
              AND pfl.is_deleted = FALSE
            GROUP BY pfl.ingredient_id, i.name
            ORDER BY COUNT(*) DESC
        """)

        result = await db.execute(
            sql_by_ingredient,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        ingredient_rows = result.fetchall()

        # 天气分布
        sql_weather = text("""
            SELECT
                COALESCE(weather_condition, 'unknown') AS weather,
                COUNT(*) AS count,
                AVG(deviation_pct) AS avg_deviation
            FROM procurement_feedback_logs
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id::UUID
              AND feedback_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              AND deviation_pct IS NOT NULL
            GROUP BY weather_condition
            ORDER BY COUNT(*) DESC
        """)

        weather_result = await db.execute(
            sql_weather,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        weather_rows = weather_result.fetchall()

        # 节假日 vs 工作日
        sql_holiday = text("""
            SELECT
                is_holiday,
                COUNT(*) AS count,
                AVG(deviation_pct) AS avg_deviation,
                AVG(ABS(deviation_pct)) AS avg_abs_deviation
            FROM procurement_feedback_logs
            WHERE tenant_id = :tenant_id
              AND store_id = :store_id::UUID
              AND feedback_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              AND deviation_pct IS NOT NULL
            GROUP BY is_holiday
        """)

        holiday_result = await db.execute(
            sql_holiday,
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        holiday_rows = holiday_result.fetchall()

        # 组装结果
        by_ingredient = [
            {
                "ingredient_id": str(row.ingredient_id),
                "ingredient_name": row.ingredient_name or "未知",
                "feedback_count": int(row.feedback_count),
                "avg_deviation_pct": round(float(row.avg_deviation_pct or 0), 2),
                "avg_abs_deviation_pct": round(float(row.avg_abs_deviation_pct or 0), 2),
                "total_waste_qty": round(float(row.total_waste_qty or 0), 2),
                "avg_correction": round(float(row.avg_correction or 1.0), 3),
            }
            for row in ingredient_rows
        ]

        by_weather = [
            {
                "weather": str(row.weather),
                "count": int(row.count),
                "avg_deviation_pct": round(float(row.avg_deviation or 0), 2),
            }
            for row in weather_rows
        ]

        by_holiday = {
            "holiday": None,
            "workday": None,
        }
        for row in holiday_rows:
            key = "holiday" if row.is_holiday else "workday"
            by_holiday[key] = {
                "count": int(row.count),
                "avg_deviation_pct": round(float(row.avg_deviation or 0), 2),
                "avg_abs_deviation_pct": round(float(row.avg_abs_deviation or 0), 2),
            }

        total_feedback = sum(item["feedback_count"] for item in by_ingredient)
        total_waste = sum(item["total_waste_qty"] for item in by_ingredient)

        summary = {
            "store_id": store_id,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "total_feedback_count": total_feedback,
            "total_waste_qty": round(total_waste, 2),
            "ingredient_count": len(by_ingredient),
            "by_ingredient": by_ingredient,
            "by_weather": by_weather,
            "by_holiday": by_holiday,
        }

        log.info(
            "procurement_feedback.summary_report",
            store_id=store_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            total_feedback=total_feedback,
            ingredient_count=len(by_ingredient),
        )
        return summary
