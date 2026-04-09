"""客流预测引擎 — 基于历史订单数据的时序预测

策略：
  1. 从 orders 表提取历史每小时订单数（近30天）
  2. 按星期几+小时计算均值和标准差
  3. 天气修正系数（雨天-15%，极端天气-30%）
  4. 节假日修正系数（+20%~+50%）
  5. 返回7天 x 24小时的预测矩阵

输出单位：预测客流数（整数）
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .weather_service import WeatherService

log = structlog.get_logger(__name__)

# 默认参数
LOOKBACK_DAYS = 30          # 回溯30天历史数据
FORECAST_DAYS = 7           # 预测未来7天
HOURS_PER_DAY = 24
BUSINESS_HOURS_START = 9    # 营业时间开始（24h）
BUSINESS_HOURS_END = 22     # 营业时间结束（24h）

# 节假日系数（可外部配置覆盖）
HOLIDAY_FACTORS: dict[str, float] = {
    "01-01": 1.30,   # 元旦
    "02-14": 1.25,   # 情人节
    "05-01": 1.40,   # 劳动节
    "06-01": 1.15,   # 儿童节
    "10-01": 1.50,   # 国庆节
    "10-02": 1.45,
    "10-03": 1.40,
    "12-24": 1.20,   # 平安夜
    "12-25": 1.15,   # 圣诞
    "12-31": 1.25,   # 跨年
}

# 星期权重（周末客流通常高于工作日）
WEEKDAY_FACTORS: dict[int, float] = {
    0: 1.00,  # 周一
    1: 0.95,  # 周二（通常最低）
    2: 1.00,  # 周三
    3: 1.05,  # 周四
    4: 1.15,  # 周五
    5: 1.30,  # 周六
    6: 1.25,  # 周日
}


class TrafficPredictor:
    """客流预测引擎

    职责：
    - 基于历史订单数据计算每小时客流基线
    - 结合天气、节假日、星期进行修正
    - 输出未来7天小时级客流预测矩阵
    """

    def __init__(self, weather_service: Optional[WeatherService] = None) -> None:
        self._weather_svc = weather_service or WeatherService()

    # ── 公开接口 ──

    async def forecast_7days(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        city: Optional[str] = None,
    ) -> dict[str, Any]:
        """未来7天小时级客流预测

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            city: 城市名（用于天气修正，可选）

        Returns:
            {
                store_id, forecast_days,
                daily_forecasts: [{
                    date, weekday, is_holiday, weather_factor,
                    total_traffic, hourly: [{hour, traffic, confidence}]
                }],
                summary: {total_7d, avg_daily, peak_day, peak_hour}
            }
        """
        # Step 1: 获取历史小时级客流基线
        hourly_baseline = await self._calc_hourly_baseline(store_id, tenant_id, db)

        # Step 2: 获取天气预报（可选）
        weather_forecast = []
        if city:
            weather_forecast = await self._weather_svc.get_7day_forecast(city, tenant_id, db)

        # Step 3: 逐天逐小时预测
        today = datetime.now(timezone.utc).date()
        daily_forecasts = []
        total_7d = 0
        peak_day = None
        peak_day_traffic = 0
        peak_hour_info = {"date": "", "hour": 0, "traffic": 0}

        for day_offset in range(FORECAST_DAYS):
            target_date = today + timedelta(days=day_offset)
            weekday = target_date.weekday()
            date_str = target_date.isoformat()
            mm_dd = target_date.strftime("%m-%d")

            # 节假日系数
            is_holiday = mm_dd in HOLIDAY_FACTORS
            holiday_factor = HOLIDAY_FACTORS.get(mm_dd, 1.0)

            # 天气系数
            weather_factor = 1.0
            if day_offset < len(weather_forecast):
                weather_factor = weather_forecast[day_offset].get("impact_factor", 1.0)

            # 星期系数
            weekday_factor = WEEKDAY_FACTORS.get(weekday, 1.0)

            # 逐小时预测
            hourly = []
            day_total = 0

            for hour in range(HOURS_PER_DAY):
                base = hourly_baseline.get((weekday, hour), 0.0)

                # 综合修正
                predicted = base * holiday_factor * weather_factor * weekday_factor
                predicted = max(0, round(predicted))

                # 置信度：有历史数据 -> 较高；无数据 -> 低
                confidence = 0.75 if base > 0 else 0.40

                hourly.append({
                    "hour": hour,
                    "traffic": predicted,
                    "confidence": confidence,
                })
                day_total += predicted

                if predicted > peak_hour_info["traffic"]:
                    peak_hour_info = {"date": date_str, "hour": hour, "traffic": predicted}

            daily_forecasts.append({
                "date": date_str,
                "weekday": weekday,
                "weekday_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday],
                "is_holiday": is_holiday,
                "weather_factor": weather_factor,
                "total_traffic": day_total,
                "hourly": hourly,
            })

            total_7d += day_total
            if day_total > peak_day_traffic:
                peak_day_traffic = day_total
                peak_day = date_str

        avg_daily = total_7d / FORECAST_DAYS if FORECAST_DAYS > 0 else 0

        log.info(
            "traffic_predictor.forecast_7days",
            store_id=store_id,
            total_7d=total_7d,
            avg_daily=round(avg_daily),
            peak_day=peak_day,
        )

        return {
            "store_id": store_id,
            "forecast_days": FORECAST_DAYS,
            "daily_forecasts": daily_forecasts,
            "summary": {
                "total_7d": total_7d,
                "avg_daily": round(avg_daily),
                "peak_day": peak_day,
                "peak_hour": peak_hour_info,
            },
        }

    async def forecast_today_remaining(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        city: Optional[str] = None,
    ) -> dict[str, Any]:
        """今日剩余时段客流预测

        Returns:
            {
                store_id, date, current_hour,
                remaining_hours: [{hour, traffic, confidence}],
                remaining_total, actual_so_far
            }
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        today = now.date()
        weekday = today.weekday()

        hourly_baseline = await self._calc_hourly_baseline(store_id, tenant_id, db)

        # 今日已有实际客流
        actual_so_far = await self._get_today_actual(store_id, tenant_id, db)

        # 天气修正
        weather_factor = 1.0
        if city:
            forecast = await self._weather_svc.get_7day_forecast(city, tenant_id, db)
            if forecast:
                weather_factor = forecast[0].get("impact_factor", 1.0)

        # 节假日修正
        mm_dd = today.strftime("%m-%d")
        holiday_factor = HOLIDAY_FACTORS.get(mm_dd, 1.0)
        weekday_factor = WEEKDAY_FACTORS.get(weekday, 1.0)

        remaining_hours = []
        remaining_total = 0

        for hour in range(current_hour + 1, HOURS_PER_DAY):
            base = hourly_baseline.get((weekday, hour), 0.0)
            predicted = max(0, round(base * holiday_factor * weather_factor * weekday_factor))
            confidence = 0.80 if base > 0 else 0.40

            remaining_hours.append({
                "hour": hour,
                "traffic": predicted,
                "confidence": confidence,
            })
            remaining_total += predicted

        return {
            "store_id": store_id,
            "date": today.isoformat(),
            "current_hour": current_hour,
            "remaining_hours": remaining_hours,
            "remaining_total": remaining_total,
            "actual_so_far": actual_so_far,
        }

    async def trigger_train(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """触发模型训练（重新计算基线并缓存到 prediction_results）

        Returns:
            {store_id, status, baseline_hours, data_days_used}
        """
        baseline = await self._calc_hourly_baseline(store_id, tenant_id, db)
        baseline_count = sum(1 for v in baseline.values() if v > 0)

        # 缓存训练结果到 prediction_results 表
        import json
        serialized = {f"{k[0]}_{k[1]}": v for k, v in baseline.items()}
        try:
            await db.execute(
                text("""
                    INSERT INTO prediction_results
                        (tenant_id, store_id, prediction_type, target_date, result_data)
                    VALUES
                        (:tenant_id::uuid, :store_id::uuid, 'traffic_baseline',
                         CURRENT_DATE, :data::jsonb)
                    ON CONFLICT (tenant_id, store_id, prediction_type, target_date)
                    DO UPDATE SET result_data = EXCLUDED.result_data, updated_at = NOW()
                """),
                {
                    "tenant_id": tenant_id,
                    "store_id": store_id,
                    "data": json.dumps(serialized),
                },
            )
            await db.commit()
        except (AttributeError, TypeError) as exc:
            log.warning("traffic_predictor.train_cache_error", error=str(exc))

        log.info(
            "traffic_predictor.train_complete",
            store_id=store_id,
            baseline_hours=baseline_count,
        )

        return {
            "store_id": store_id,
            "status": "trained",
            "baseline_hours": baseline_count,
            "data_days_used": LOOKBACK_DAYS,
        }

    # ── 私有方法 ──

    async def _calc_hourly_baseline(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[tuple[int, int], float]:
        """计算每个 (星期几, 小时) 的平均客流数

        从 orders 表近30天数据统计。

        Returns:
            {(weekday, hour): avg_traffic, ...}
        """
        try:
            result = await db.execute(
                text("""
                    SELECT
                        EXTRACT(DOW FROM created_at)::int AS weekday,
                        EXTRACT(HOUR FROM created_at)::int AS hour,
                        COUNT(DISTINCT id) AS order_count,
                        AVG(customer_count) AS avg_customers
                    FROM orders
                    WHERE tenant_id = :tenant_id::uuid
                      AND store_id = :store_id::uuid
                      AND is_deleted = FALSE
                      AND created_at >= NOW() - INTERVAL ':days days'
                    GROUP BY weekday, hour
                    ORDER BY weekday, hour
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "days": LOOKBACK_DAYS},
            )
            rows = result.fetchall()

            baseline: dict[tuple[int, int], float] = {}
            weeks_in_period = max(1, LOOKBACK_DAYS / 7)

            for row in rows:
                # PostgreSQL DOW: 0=Sunday...6=Saturday -> 转换为 Python weekday 0=Monday
                pg_dow = int(row[0])
                py_weekday = (pg_dow - 1) % 7  # 0=Monday
                hour = int(row[1])
                order_count = int(row[2])
                avg_customers = float(row[3] or 1)

                # 日均客流 = 总订单数 / 周数 * 平均每单客数
                avg_traffic = (order_count / weeks_in_period) * max(1.0, avg_customers)
                baseline[(py_weekday, hour)] = round(avg_traffic, 1)

            return baseline

        except (AttributeError, TypeError, KeyError) as exc:
            log.warning("traffic_predictor.baseline_error", error=str(exc))
            return {}

    async def _get_today_actual(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> int:
        """获取今日已有实际客流"""
        try:
            result = await db.execute(
                text("""
                    SELECT COALESCE(SUM(customer_count), COUNT(*))
                    FROM orders
                    WHERE tenant_id = :tenant_id::uuid
                      AND store_id = :store_id::uuid
                      AND is_deleted = FALSE
                      AND created_at::date = CURRENT_DATE
                """),
                {"tenant_id": tenant_id, "store_id": store_id},
            )
            return int(result.scalar() or 0)
        except (AttributeError, TypeError) as exc:
            log.debug("traffic_predictor.actual_error", error=str(exc))
            return 0
