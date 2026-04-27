"""天气数据对接服务 — 和风天气 API

功能：
  1. 获取指定城市7天天气预报
  2. 缓存天气数据到 weather_cache 表（避免重复请求）
  3. 计算天气对营业的影响系数

和风天气 API 文档：https://dev.qweather.com/docs/api/weather/weather-daily-forecast/
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# 和风天气 API 配置
QWEATHER_BASE_URL = os.getenv("QWEATHER_BASE_URL", "https://devapi.qweather.com")
QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "")
CACHE_TTL_HOURS = 6  # 天气缓存6小时

# 天气影响系数映射（对营业额的影响倍率）
WEATHER_IMPACT_FACTORS: dict[str, float] = {
    "晴": 1.0,
    "多云": 1.0,
    "阴": 0.95,
    "小雨": 0.85,
    "中雨": 0.75,
    "大雨": 0.65,
    "暴雨": 0.50,
    "雷阵雨": 0.60,
    "小雪": 0.80,
    "中雪": 0.70,
    "大雪": 0.55,
    "暴雪": 0.40,
    "雾": 0.85,
    "霾": 0.90,
}

# 温度极端值影响
HIGH_TEMP_THRESHOLD = 38  # 高温预警
LOW_TEMP_THRESHOLD = -5  # 低温预警
EXTREME_TEMP_PENALTY = 0.85  # 极端温度惩罚系数


class WeatherService:
    """天气数据服务

    职责：
    - 对接和风天气 API 获取7天预报
    - 缓存天气数据到数据库
    - 计算天气对客流/营收的影响系数
    """

    def __init__(self) -> None:
        self._api_key = QWEATHER_API_KEY

    # ── 公开接口 ──

    async def get_7day_forecast(
        self,
        city: str,
        tenant_id: str,
        db: Optional[AsyncSession] = None,
    ) -> list[dict[str, Any]]:
        """获取7天天气预报

        优先从缓存读取，缓存过期时调用和风天气API。

        Args:
            city: 城市名称或城市ID（如 "长沙" 或 "101250101"）
            tenant_id: 租户ID
            db: 数据库会话（用于缓存读写）

        Returns:
            [{date, text_day, text_night, temp_max, temp_min,
              humidity, wind_dir, wind_scale, impact_factor}]
        """
        # 尝试从缓存读取
        if db is not None:
            cached = await self._read_cache(city, tenant_id, db)
            if cached:
                log.debug("weather.cache_hit", city=city)
                return cached

        # 调用和风天气 API
        forecast = await self._fetch_from_api(city)

        # 写入缓存
        if db is not None and forecast:
            await self._write_cache(city, tenant_id, forecast, db)

        return forecast

    def calc_impact_factor(self, weather_text: str, temp_max: int, temp_min: int) -> float:
        """计算天气对营业的综合影响系数

        规则：
        1. 基础系数来自天气文本映射
        2. 极端高温(>=38) 或极端低温(<=-5) 额外惩罚
        3. 返回值范围 [0.3, 1.2]

        Args:
            weather_text: 白天天气描述（如"小雨"、"晴"）
            temp_max: 最高温度
            temp_min: 最低温度

        Returns:
            影响系数，1.0 为正常，<1.0 表示负面影响
        """
        base_factor = WEATHER_IMPACT_FACTORS.get(weather_text, 0.95)

        # 极端温度惩罚
        if temp_max >= HIGH_TEMP_THRESHOLD or temp_min <= LOW_TEMP_THRESHOLD:
            base_factor *= EXTREME_TEMP_PENALTY

        return max(0.3, min(1.2, round(base_factor, 3)))

    async def analyze_weather_impact(
        self,
        city: str,
        tenant_id: str,
        db: Optional[AsyncSession] = None,
    ) -> dict[str, Any]:
        """分析天气对营业的影响

        Returns:
            {
                city, forecast_days,
                daily_impacts: [{date, weather, impact_factor, risk_level}],
                avg_impact_factor, worst_day, recommendations
            }
        """
        forecast = await self.get_7day_forecast(city, tenant_id, db)

        if not forecast:
            return {
                "city": city,
                "forecast_days": 0,
                "daily_impacts": [],
                "avg_impact_factor": 1.0,
                "worst_day": None,
                "recommendations": ["天气数据暂不可用，建议按正常营业准备"],
            }

        daily_impacts = []
        worst_factor = 1.0
        worst_day = None

        for day in forecast:
            factor = day.get("impact_factor", 1.0)
            risk_level = "normal"
            if factor < 0.7:
                risk_level = "high"
            elif factor < 0.85:
                risk_level = "medium"

            daily_impacts.append(
                {
                    "date": day["date"],
                    "weather": day.get("text_day", ""),
                    "temp_max": day.get("temp_max"),
                    "temp_min": day.get("temp_min"),
                    "impact_factor": factor,
                    "risk_level": risk_level,
                }
            )

            if factor < worst_factor:
                worst_factor = factor
                worst_day = day["date"]

        avg_factor = sum(d["impact_factor"] for d in daily_impacts) / len(daily_impacts)

        recommendations = self._generate_recommendations(daily_impacts)

        return {
            "city": city,
            "forecast_days": len(daily_impacts),
            "daily_impacts": daily_impacts,
            "avg_impact_factor": round(avg_factor, 3),
            "worst_day": worst_day,
            "recommendations": recommendations,
        }

    # ── 私有方法 ──

    async def _fetch_from_api(self, city: str) -> list[dict[str, Any]]:
        """调用和风天气 API 获取7天预报"""
        if not self._api_key:
            log.warning("weather.api_key_missing")
            return self._fallback_forecast()

        location = await self._resolve_city_id(city)
        url = f"{QWEATHER_BASE_URL}/v7/weather/7d"
        params = {"location": location, "key": self._api_key}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != "200":
                log.warning("weather.api_error", code=data.get("code"), city=city)
                return self._fallback_forecast()

            result = []
            for day in data.get("daily", []):
                temp_max = int(day.get("tempMax", 25))
                temp_min = int(day.get("tempMin", 15))
                text_day = day.get("textDay", "晴")

                result.append(
                    {
                        "date": day.get("fxDate", ""),
                        "text_day": text_day,
                        "text_night": day.get("textNight", ""),
                        "temp_max": temp_max,
                        "temp_min": temp_min,
                        "humidity": int(day.get("humidity", 50)),
                        "wind_dir": day.get("windDirDay", ""),
                        "wind_scale": day.get("windScaleDay", ""),
                        "impact_factor": self.calc_impact_factor(text_day, temp_max, temp_min),
                    }
                )

            log.info("weather.api_success", city=city, days=len(result))
            return result

        except httpx.TimeoutException:
            log.warning("weather.api_timeout", city=city)
            return self._fallback_forecast()
        except httpx.HTTPStatusError as exc:
            log.warning("weather.api_http_error", city=city, status=exc.response.status_code)
            return self._fallback_forecast()

    async def _resolve_city_id(self, city: str) -> str:
        """将城市名解析为和风天气城市ID

        如果输入已是数字ID则直接返回。
        否则调用城市查询API。
        """
        if city.isdigit():
            return city

        url = f"{QWEATHER_BASE_URL}/v7/geo/city/lookup"
        params = {"location": city, "key": self._api_key}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            locations = data.get("location", [])
            if locations:
                return locations[0].get("id", city)
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            log.warning("weather.city_resolve_failed", city=city, error=str(exc))

        return city

    def _fallback_forecast(self) -> list[dict[str, Any]]:
        """API 不可用时的降级预报（默认晴天）"""
        today = datetime.now(timezone.utc).date()
        result = []
        for i in range(7):
            day_date = today + timedelta(days=i)
            result.append(
                {
                    "date": day_date.isoformat(),
                    "text_day": "晴",
                    "text_night": "晴",
                    "temp_max": 25,
                    "temp_min": 15,
                    "humidity": 50,
                    "wind_dir": "北风",
                    "wind_scale": "1-2",
                    "impact_factor": 1.0,
                }
            )
        return result

    async def _read_cache(
        self,
        city: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Optional[list[dict[str, Any]]]:
        """从 weather_cache 读取缓存"""
        try:
            result = await db.execute(
                text("""
                    SELECT forecast_data
                    FROM weather_cache
                    WHERE city = :city
                      AND tenant_id = :tenant_id::uuid
                      AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"city": city, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            if row and row[0]:
                return row[0]  # JSONB 自动反序列化
        except (AttributeError, TypeError, KeyError) as exc:
            log.debug("weather.cache_read_error", error=str(exc))
        return None

    async def _write_cache(
        self,
        city: str,
        tenant_id: str,
        forecast: list[dict[str, Any]],
        db: AsyncSession,
    ) -> None:
        """写入 weather_cache"""
        import json

        try:
            await db.execute(
                text("""
                    INSERT INTO weather_cache (tenant_id, city, forecast_data, expires_at)
                    VALUES (:tenant_id::uuid, :city, :data::jsonb, NOW() + INTERVAL ':ttl hours')
                    ON CONFLICT (tenant_id, city)
                    DO UPDATE SET forecast_data = EXCLUDED.forecast_data,
                                  expires_at = EXCLUDED.expires_at,
                                  updated_at = NOW()
                """),
                {
                    "tenant_id": tenant_id,
                    "city": city,
                    "data": json.dumps(forecast, ensure_ascii=False),
                    "ttl": CACHE_TTL_HOURS,
                },
            )
            await db.commit()
        except (AttributeError, TypeError) as exc:
            log.debug("weather.cache_write_error", error=str(exc))

    def _generate_recommendations(self, daily_impacts: list[dict]) -> list[str]:
        """根据天气影响生成运营建议"""
        recommendations = []

        high_risk_days = [d for d in daily_impacts if d["risk_level"] == "high"]
        medium_risk_days = [d for d in daily_impacts if d["risk_level"] == "medium"]

        if high_risk_days:
            dates = ", ".join(d["date"] for d in high_risk_days)
            recommendations.append(f"高风险日期({dates})建议减少备货量30%，降低损耗")
            recommendations.append("恶劣天气期间可增加外卖平台曝光，弥补堂食下降")

        if medium_risk_days:
            dates = ", ".join(d["date"] for d in medium_risk_days)
            recommendations.append(f"中等风险日期({dates})建议减少备货量15%")

        if not high_risk_days and not medium_risk_days:
            recommendations.append("未来7天天气良好，可正常备货")

        return recommendations
