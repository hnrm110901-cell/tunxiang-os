"""菜品需求预测引擎 — 基于销售历史的SKU级需求预测

策略：
  1. 从 order_items 提取每个菜品的日销量（近14天）
  2. 加权移动平均（近7天权重递增）
  3. 星期几系数修正
  4. 天气/季节修正
  5. 返回每个菜品的预测需求量 + 备餐建议

输出单位：预测份数（整数）
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
LOOKBACK_DAYS = 14          # 回溯14天销售数据
WEIGHTED_DAYS = 7           # 加权移动平均窗口
FORECAST_DAYS = 3           # 预测未来3天

# 加权移动平均权重（近日权重高）
# day-1 权重7, day-2 权重6, ..., day-7 权重1
WMA_WEIGHTS = list(range(WEIGHTED_DAYS, 0, -1))  # [7,6,5,4,3,2,1]
WMA_SUM = sum(WMA_WEIGHTS)  # 28

# 星期修正系数（餐饮行业菜品销量周期性）
WEEKDAY_FACTORS: dict[int, float] = {
    0: 1.00,  # 周一
    1: 0.95,  # 周二
    2: 1.00,  # 周三
    3: 1.05,  # 周四
    4: 1.10,  # 周五（周末前夜提升）
    5: 1.25,  # 周六
    6: 1.20,  # 周日
}

# 季节修正（不同季节菜品偏好变化）
SEASON_FACTORS: dict[str, dict[str, float]] = {
    "summer": {"凉菜": 1.3, "热菜": 0.9, "汤": 0.8, "火锅": 0.6},
    "winter": {"凉菜": 0.7, "热菜": 1.1, "汤": 1.3, "火锅": 1.5},
    "spring": {"凉菜": 1.0, "热菜": 1.0, "汤": 1.0, "火锅": 0.9},
    "autumn": {"凉菜": 0.9, "热菜": 1.05, "汤": 1.1, "火锅": 1.1},
}

# 备餐安全系数（多备一点避免沽清）
PREP_SAFETY_FACTOR = 1.15


def _get_season() -> str:
    """根据当前月份判断季节"""
    month = datetime.now(timezone.utc).month
    if month in (6, 7, 8):
        return "summer"
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    return "autumn"


class DemandPredictor:
    """菜品需求预测引擎

    职责：
    - 基于历史销售数据预测未来3天每道菜的需求量
    - 加权移动平均 + 多维修正（星期/天气/季节）
    - 生成备餐建议（半成品提前准备量）
    - 追踪预测准确率
    """

    def __init__(self, weather_service: Optional[WeatherService] = None) -> None:
        self._weather_svc = weather_service or WeatherService()

    # ── 公开接口 ──

    async def forecast_demand(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        forecast_days: int = FORECAST_DAYS,
        city: Optional[str] = None,
    ) -> dict[str, Any]:
        """未来N天SKU级需求预测

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            db: 数据库会话
            forecast_days: 预测天数（默认3）
            city: 城市名（天气修正）

        Returns:
            {
                store_id, forecast_days,
                dishes: [{
                    dish_id, dish_name, category,
                    daily_forecasts: [{date, predicted_qty, confidence}],
                    avg_daily, total_forecast
                }],
                summary: {total_dishes, total_qty, high_confidence_count}
            }
        """
        # Step 1: 获取历史销售数据
        sales_history = await self._fetch_sales_history(store_id, tenant_id, db)

        if not sales_history:
            return {
                "store_id": store_id,
                "forecast_days": forecast_days,
                "dishes": [],
                "summary": {"total_dishes": 0, "total_qty": 0, "high_confidence_count": 0},
            }

        # Step 2: 天气预报
        weather_forecast = []
        if city:
            weather_forecast = await self._weather_svc.get_7day_forecast(city, tenant_id, db)

        # Step 3: 逐菜品预测
        today = datetime.now(timezone.utc).date()
        season = _get_season()
        dishes_result = []
        total_qty = 0
        high_confidence = 0

        for dish_id, dish_data in sales_history.items():
            dish_name = dish_data["dish_name"]
            category = dish_data.get("category", "热菜")
            daily_sales = dish_data["daily_sales"]  # {date_str: qty}

            # 加权移动平均计算基线
            wma_baseline = self._calc_wma(daily_sales, today)

            # 逐天预测
            daily_forecasts = []
            dish_total = 0

            for day_offset in range(forecast_days):
                target_date = today + timedelta(days=day_offset)
                weekday = target_date.weekday()

                # 修正系数
                weekday_factor = WEEKDAY_FACTORS.get(weekday, 1.0)
                season_factor = SEASON_FACTORS.get(season, {}).get(category, 1.0)
                weather_factor = 1.0
                if day_offset < len(weather_forecast):
                    weather_factor = weather_forecast[day_offset].get("impact_factor", 1.0)

                predicted = wma_baseline * weekday_factor * season_factor * weather_factor
                predicted = max(0, round(predicted))

                # 置信度
                data_days = len(daily_sales)
                confidence = min(0.90, 0.40 + data_days * 0.04)

                daily_forecasts.append({
                    "date": target_date.isoformat(),
                    "predicted_qty": predicted,
                    "confidence": round(confidence, 2),
                })
                dish_total += predicted

            avg_daily = dish_total / forecast_days if forecast_days > 0 else 0

            dishes_result.append({
                "dish_id": dish_id,
                "dish_name": dish_name,
                "category": category,
                "daily_forecasts": daily_forecasts,
                "avg_daily": round(avg_daily, 1),
                "total_forecast": dish_total,
            })

            total_qty += dish_total
            if len(daily_sales) >= 7:
                high_confidence += 1

        # 按总预测量降序排列
        dishes_result.sort(key=lambda x: x["total_forecast"], reverse=True)

        log.info(
            "demand_predictor.forecast",
            store_id=store_id,
            total_dishes=len(dishes_result),
            total_qty=total_qty,
        )

        return {
            "store_id": store_id,
            "forecast_days": forecast_days,
            "dishes": dishes_result,
            "summary": {
                "total_dishes": len(dishes_result),
                "total_qty": total_qty,
                "high_confidence_count": high_confidence,
            },
        }

    async def get_prep_suggestions(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        city: Optional[str] = None,
    ) -> dict[str, Any]:
        """备餐建议 — 半成品提前准备量

        基于明天的需求预测，乘以安全系数，生成备餐清单。

        Returns:
            {
                store_id, target_date,
                prep_items: [{dish_id, dish_name, prep_qty, unit, priority}],
                total_items
            }
        """
        forecast = await self.forecast_demand(
            store_id, tenant_id, db, forecast_days=1, city=city,
        )

        tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        prep_items = []

        for dish in forecast.get("dishes", []):
            daily_forecasts = dish.get("daily_forecasts", [])
            if not daily_forecasts:
                continue

            predicted_qty = daily_forecasts[0].get("predicted_qty", 0)
            if predicted_qty <= 0:
                continue

            prep_qty = math.ceil(predicted_qty * PREP_SAFETY_FACTOR)

            # 优先级：高销量 = high
            priority = "high" if predicted_qty >= 20 else ("medium" if predicted_qty >= 5 else "low")

            prep_items.append({
                "dish_id": dish["dish_id"],
                "dish_name": dish["dish_name"],
                "category": dish.get("category", ""),
                "predicted_qty": predicted_qty,
                "prep_qty": prep_qty,
                "priority": priority,
            })

        # 高优先级排前面
        priority_order = {"high": 0, "medium": 1, "low": 2}
        prep_items.sort(key=lambda x: priority_order.get(x["priority"], 9))

        return {
            "store_id": store_id,
            "target_date": tomorrow,
            "prep_items": prep_items,
            "total_items": len(prep_items),
        }

    async def get_accuracy(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        days: int = 7,
    ) -> dict[str, Any]:
        """预测准确率追踪

        对比过去N天的预测值与实际销量，计算MAPE。

        Returns:
            {store_id, period_days, overall_mape, dish_accuracy: [{dish_id, dish_name, mape}]}
        """
        try:
            result = await db.execute(
                text("""
                    SELECT
                        pr.result_data,
                        pr.target_date
                    FROM prediction_results pr
                    WHERE pr.tenant_id = :tenant_id::uuid
                      AND pr.store_id = :store_id::uuid
                      AND pr.prediction_type = 'demand'
                      AND pr.target_date >= CURRENT_DATE - :days
                      AND pr.target_date < CURRENT_DATE
                    ORDER BY pr.target_date
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "days": days},
            )
            prediction_rows = result.fetchall()

            if not prediction_rows:
                return {
                    "store_id": store_id,
                    "period_days": days,
                    "overall_mape": None,
                    "dish_accuracy": [],
                    "message": "暂无历史预测数据可对比",
                }

            # 获取同期实际销量
            actual_result = await db.execute(
                text("""
                    SELECT
                        oi.dish_id::text,
                        o.created_at::date AS sale_date,
                        SUM(oi.quantity) AS actual_qty
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    WHERE o.tenant_id = :tenant_id::uuid
                      AND o.store_id = :store_id::uuid
                      AND o.is_deleted = FALSE
                      AND o.created_at::date >= CURRENT_DATE - :days
                      AND o.created_at::date < CURRENT_DATE
                    GROUP BY oi.dish_id, sale_date
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "days": days},
            )
            actual_rows = actual_result.fetchall()

            # 计算 MAPE（简化版，整体）
            total_predicted = 0
            total_actual = 0
            for row in actual_rows:
                total_actual += int(row[2] or 0)

            # 从缓存的预测结果中汇总预测值
            for prow in prediction_rows:
                data = prow[0] or {}
                for _dish_id, qty in data.items():
                    total_predicted += int(qty) if isinstance(qty, (int, float)) else 0

            if total_actual > 0:
                mape = abs(total_predicted - total_actual) / total_actual * 100
            else:
                mape = None

            return {
                "store_id": store_id,
                "period_days": days,
                "overall_mape": round(mape, 1) if mape is not None else None,
                "total_predicted": total_predicted,
                "total_actual": total_actual,
                "dish_accuracy": [],  # TODO: 逐菜品MAPE
            }

        except (AttributeError, TypeError, KeyError) as exc:
            log.warning("demand_predictor.accuracy_error", error=str(exc))
            return {
                "store_id": store_id,
                "period_days": days,
                "overall_mape": None,
                "dish_accuracy": [],
                "message": f"计算准确率时出错: {exc}",
            }

    # ── 私有方法 ──

    async def _fetch_sales_history(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, dict[str, Any]]:
        """获取近14天每个菜品的日销量

        Returns:
            {dish_id: {dish_name, category, daily_sales: {date_str: qty}}}
        """
        try:
            result = await db.execute(
                text("""
                    SELECT
                        oi.dish_id::text,
                        d.dish_name,
                        d.category,
                        o.created_at::date AS sale_date,
                        SUM(oi.quantity) AS daily_qty
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id
                    LEFT JOIN dishes d ON d.id = oi.dish_id
                    WHERE o.tenant_id = :tenant_id::uuid
                      AND o.store_id = :store_id::uuid
                      AND o.is_deleted = FALSE
                      AND o.created_at >= NOW() - INTERVAL ':days days'
                    GROUP BY oi.dish_id, d.dish_name, d.category, sale_date
                    ORDER BY oi.dish_id, sale_date
                """),
                {"tenant_id": tenant_id, "store_id": store_id, "days": LOOKBACK_DAYS},
            )
            rows = result.fetchall()

            history: dict[str, dict[str, Any]] = {}
            for row in rows:
                dish_id = str(row[0])
                dish_name = row[1] or "未知菜品"
                category = row[2] or "热菜"
                sale_date = str(row[3])
                daily_qty = int(row[4] or 0)

                if dish_id not in history:
                    history[dish_id] = {
                        "dish_name": dish_name,
                        "category": category,
                        "daily_sales": {},
                    }
                history[dish_id]["daily_sales"][sale_date] = daily_qty

            return history

        except (AttributeError, TypeError, KeyError) as exc:
            log.warning("demand_predictor.history_error", error=str(exc))
            return {}

    def _calc_wma(self, daily_sales: dict[str, int], today: Any) -> float:
        """加权移动平均计算基线

        近7天权重递增：day-1权重7, day-2权重6, ..., day-7权重1
        无数据的日期用0补齐。
        """
        weighted_sum = 0.0
        actual_weight_sum = 0

        for i in range(WEIGHTED_DAYS):
            target_date = today - timedelta(days=i + 1)
            date_str = target_date.isoformat()
            qty = daily_sales.get(date_str, 0)
            weight = WMA_WEIGHTS[i]  # i=0 -> 权重7（最近一天）

            weighted_sum += qty * weight
            if qty > 0:
                actual_weight_sum += weight

        if actual_weight_sum == 0:
            # 无近7天数据，取全量平均
            values = list(daily_sales.values())
            return sum(values) / len(values) if values else 0.0

        return weighted_sum / WMA_SUM
