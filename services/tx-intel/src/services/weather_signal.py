"""天气信号服务 — 天气变化对餐饮客流的影响评估"""
from datetime import date, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class WeatherSignalService:
    """天气信号 → 增长策略调整

    规则:
    - 雨天/雪天 → 到店客流下降 → 加大外卖渠道触达 + 储值余额提醒
    - 极端高温/低温 → 室内消费偏好 → 包厢/空调舒适提醒
    - 节假日前晴天 → 出游高峰 → 提前触达预订
    - 连续好天气 → 户外/露台推荐
    """

    # 天气影响评分模型（简化版）
    WEATHER_IMPACT: dict[str, dict[str, float]] = {
        "rain": {"traffic_impact": -0.3, "delivery_boost": 0.4, "indoor_preference": 0.5},
        "heavy_rain": {"traffic_impact": -0.5, "delivery_boost": 0.6, "indoor_preference": 0.7},
        "snow": {"traffic_impact": -0.4, "delivery_boost": 0.5, "indoor_preference": 0.6},
        "extreme_heat": {"traffic_impact": -0.2, "delivery_boost": 0.3, "indoor_preference": 0.8},
        "extreme_cold": {"traffic_impact": -0.3, "delivery_boost": 0.4, "indoor_preference": 0.7},
        "sunny": {"traffic_impact": 0.1, "delivery_boost": -0.1, "outdoor_preference": 0.3},
        "cloudy": {"traffic_impact": 0.0, "delivery_boost": 0.0, "indoor_preference": 0.1},
    }

    async def get_weather_signal(self, city: str, target_date: Optional[date] = None) -> dict:
        """获取城市天气信号（P0: 模拟数据，后续接入真实API）"""
        if target_date is None:
            target_date = date.today()

        # P0简化：返回模拟天气信号
        # 后续接入: 和风天气API / 心知天气API
        import random
        weather_types = list(self.WEATHER_IMPACT.keys())
        weather = random.choice(weather_types)
        impact = self.WEATHER_IMPACT[weather]

        return {
            "city": city,
            "date": str(target_date),
            "weather_type": weather,
            "temperature_high": random.randint(15, 38),
            "temperature_low": random.randint(5, 25),
            "impact": impact,
            "growth_recommendations": self._generate_recommendations(weather, impact),
        }

    def _generate_recommendations(self, weather: str, impact: dict) -> list:
        """基于天气生成增长策略建议"""
        recs: list[dict] = []

        if impact.get("traffic_impact", 0) < -0.2:
            recs.append({
                "type": "boost_delivery",
                "description": (
                    f"天气({weather})导致到店客流预计下降"
                    f"{abs(impact['traffic_impact']) * 100:.0f}%，"
                    "建议加大外卖/储值触达"
                ),
                "suggested_journey": "stored_value_renewal_v1",
                "suggested_channel": "miniapp",
            })

        if impact.get("indoor_preference", 0) > 0.5:
            recs.append({
                "type": "promote_indoor",
                "description": "室内消费偏好增强，建议推荐包厢/空调舒适环境",
                "suggested_journey": "banquet_repurchase_v1",
                "suggested_channel": "wecom",
            })

        if impact.get("delivery_boost", 0) > 0.3:
            recs.append({
                "type": "delivery_recall",
                "description": "外卖需求上升，建议触达渠道客回流",
                "suggested_journey": "channel_reflow_v1",
                "suggested_channel": "sms",
            })

        if impact.get("outdoor_preference", 0) > 0.2:
            recs.append({
                "type": "outdoor_dining",
                "description": "好天气适合户外用餐，建议推荐露台/花园席位",
                "suggested_journey": None,
                "suggested_channel": "wecom",
            })

        return recs

    async def get_weekly_forecast_signals(self, city: str) -> dict:
        """未来7天天气信号预测"""
        signals = []
        today = date.today()
        for i in range(7):
            d = today + timedelta(days=i)
            signal = await self.get_weather_signal(city, d)
            signals.append(signal)

        # 汇总建议
        all_recs: list[dict] = []
        for s in signals:
            for r in s["growth_recommendations"]:
                r["date"] = s["date"]
                all_recs.append(r)

        return {
            "city": city,
            "period": f"{today} ~ {today + timedelta(days=6)}",
            "daily_signals": signals,
            "aggregated_recommendations": all_recs,
        }
