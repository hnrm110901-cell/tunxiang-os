"""天气信号服务代理 — 在 tx-growth 内直接实例化（无状态纯计算，无需跨服务调用）

与 tx-intel/services/weather_signal.py 保持同步。后续可改为 httpx 调用 tx-intel。
"""

from datetime import date, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class WeatherSignalService:
    """天气信号 → 增长策略调整"""

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
        """获取城市天气信号（P0: 模拟数据，后续接入和风天气/心知天气 API）"""
        if target_date is None:
            target_date = date.today()

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
        recs: list[dict] = []
        if impact.get("traffic_impact", 0) < -0.2:
            recs.append(
                {
                    "type": "boost_delivery",
                    "description": (
                        f"天气({weather})导致到店客流预计下降"
                        f"{abs(impact['traffic_impact']) * 100:.0f}%，"
                        "建议加大外卖/储值触达"
                    ),
                    "suggested_journey": "stored_value_renewal_v1",
                    "suggested_channel": "miniapp",
                }
            )
        if impact.get("indoor_preference", 0) > 0.5:
            recs.append(
                {
                    "type": "promote_indoor",
                    "description": "室内消费偏好增强，建议推荐包厢/空调舒适环境",
                    "suggested_journey": "banquet_repurchase_v1",
                    "suggested_channel": "wecom",
                }
            )
        if impact.get("delivery_boost", 0) > 0.3:
            recs.append(
                {
                    "type": "delivery_recall",
                    "description": "外卖需求上升，建议触达渠道客回流",
                    "suggested_journey": "channel_reflow_v1",
                    "suggested_channel": "sms",
                }
            )
        if impact.get("outdoor_preference", 0) > 0.2:
            recs.append(
                {
                    "type": "outdoor_dining",
                    "description": "好天气适合户外用餐，建议推荐露台/花园席位",
                    "suggested_journey": None,
                    "suggested_channel": "wecom",
                }
            )
        return recs

    async def get_weekly_forecast_signals(self, city: str) -> dict:
        signals = []
        today = date.today()
        for i in range(7):
            d = today + timedelta(days=i)
            signal = await self.get_weather_signal(city, d)
            signals.append(signal)

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
