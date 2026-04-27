"""增强型需求预测 -- 天气 x 节假日 x 季节 x 历史反馈

在原有 DemandForecastService 基础上增加:
1. 天气因子: 晴天1.0, 阴天0.95, 小雨0.85, 大雨0.70, 暴雪0.50
2. 节假日日历: 春节1.8, 国庆1.5, 中秋1.3, 元旦1.2, 周末1.15, 工作日1.0
3. 季节系数: 火锅/烧烤夏冬差异, 冷饮/热饮季节波动
4. 历史反馈修正: 从 procurement_feedback_logs 学习修正系数

预测公式:
  建议量 = 日均消耗 x 天气因子 x 节假日因子 x 季节因子 x 历史修正系数 x 预测天数

金额单位: 分(fen)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .demand_forecast import DemandForecastService

log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  天气因子
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WEATHER_FACTORS: dict[str, float] = {
    "sunny": 1.00,
    "cloudy": 0.95,
    "rainy": 0.85,
    "heavy_rain": 0.70,
    "snow": 0.50,
}

DEFAULT_WEATHER_FACTOR = 1.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  节假日日历 (2026年中国法定节假日+调休)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 格式: (month, day) -> (factor, holiday_name)
HOLIDAY_CALENDAR_2026: dict[tuple[int, int], tuple[float, str]] = {
    # 元旦 (1.1-1.3)
    (1, 1): (1.2, "元旦"),
    (1, 2): (1.2, "元旦"),
    (1, 3): (1.2, "元旦"),
    # 春节 (2.17-2.23, 农历正月初一~初七)
    (2, 17): (1.8, "春节"),
    (2, 18): (1.8, "春节"),
    (2, 19): (1.8, "春节"),
    (2, 20): (1.8, "春节"),
    (2, 21): (1.7, "春节"),
    (2, 22): (1.6, "春节"),
    (2, 23): (1.5, "春节"),
    # 除夕
    (2, 16): (1.6, "除夕"),
    # 清明 (4.4-4.6)
    (4, 4): (1.2, "清明"),
    (4, 5): (1.2, "清明"),
    (4, 6): (1.2, "清明"),
    # 劳动节 (5.1-5.5)
    (5, 1): (1.4, "劳动节"),
    (5, 2): (1.4, "劳动节"),
    (5, 3): (1.3, "劳动节"),
    (5, 4): (1.3, "劳动节"),
    (5, 5): (1.2, "劳动节"),
    # 端午 (5.31-6.2)
    (5, 31): (1.2, "端午"),
    (6, 1): (1.2, "端午"),
    (6, 2): (1.2, "端午"),
    # 中秋 (9.27-9.29, 预估)
    (9, 27): (1.3, "中秋"),
    (9, 28): (1.3, "中秋"),
    (9, 29): (1.3, "中秋"),
    # 国庆 (10.1-10.7)
    (10, 1): (1.5, "国庆"),
    (10, 2): (1.5, "国庆"),
    (10, 3): (1.5, "国庆"),
    (10, 4): (1.4, "国庆"),
    (10, 5): (1.4, "国庆"),
    (10, 6): (1.3, "国庆"),
    (10, 7): (1.3, "国庆"),
}

# 调休上班日 (这些本来是周末但需上班, 因子降回工作日水平)
WORKDAY_ADJUSTMENTS_2026: set[tuple[int, int]] = {
    (2, 14),  # 春节调休
    (2, 15),  # 春节调休
    (4, 7),   # 清明调休 (预估)
    (9, 26),  # 中秋调休 (预估)
    (10, 10), # 国庆调休 (预估)
}

WEEKEND_FACTOR = 1.15
WORKDAY_FACTOR = 1.0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  季节系数矩阵 (食材品类 x 月份)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 品类 -> 12个月的季节系数 (index 0=1月, 11=12月)
SEASON_MATRIX: dict[str, list[float]] = {
    # 火锅类食材: 冬高夏低
    "hotpot": [1.3, 1.2, 1.1, 0.9, 0.8, 0.7, 0.7, 0.7, 0.8, 1.0, 1.2, 1.3],
    # 烧烤类: 夏高冬低
    "bbq": [0.7, 0.7, 0.8, 0.9, 1.1, 1.3, 1.3, 1.3, 1.1, 0.9, 0.8, 0.7],
    # 冷饮冰品: 夏季爆发
    "cold_drink": [0.5, 0.5, 0.6, 0.8, 1.0, 1.3, 1.5, 1.5, 1.2, 0.8, 0.6, 0.5],
    # 热饮汤品: 冬高夏低
    "hot_drink": [1.4, 1.3, 1.1, 0.9, 0.8, 0.6, 0.5, 0.5, 0.7, 0.9, 1.2, 1.4],
    # 海鲜水产: 春夏略高(开渔季)
    "seafood": [0.9, 0.9, 1.0, 1.1, 1.2, 1.2, 1.1, 1.1, 1.2, 1.0, 0.9, 0.9],
    # 蔬菜: 春夏品种多略高
    "vegetable": [0.9, 0.9, 1.0, 1.1, 1.1, 1.1, 1.0, 1.0, 1.0, 1.0, 0.9, 0.9],
    # 肉类: 全年相对稳定, 冬季略高
    "meat": [1.1, 1.1, 1.0, 1.0, 1.0, 0.9, 0.9, 0.9, 1.0, 1.0, 1.1, 1.1],
    # 主食: 全年稳定
    "staple": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    # 调料: 全年稳定
    "seasoning": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    # 默认: 全年1.0
    "default": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  修正系数约束
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CORRECTION_MIN = 0.7
CORRECTION_MAX = 1.5
CORRECTION_DEFAULT = 1.0
EMA_ALPHA = 0.3


class EnhancedDemandForecastService:
    """增强型需求预测服务

    在 DemandForecastService 基础上组合:
      天气因子 x 节假日因子 x 季节因子 x 历史修正系数

    职责:
    - 获取天气因子 (和风天气API或降级默认值)
    - 内置中国法定节假日+调休日历
    - 按食材品类x月份的季节系数
    - 从 procurement_feedback_logs 学习修正系数 (EMA)
    """

    def __init__(self) -> None:
        self._base_forecast = DemandForecastService()
        self._weather_api_key: str | None = os.environ.get("QWEATHER_API_KEY")
        self._weather_api_base: str = os.environ.get(
            "QWEATHER_API_BASE", "https://devapi.qweather.com"
        )

    # ──────────────────────────────────────────────────────
    #  RLS set_config
    # ──────────────────────────────────────────────────────

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ──────────────────────────────────────────────────────
    #  天气因子
    # ──────────────────────────────────────────────────────

    async def get_weather_factor(
        self,
        target_date: date,
        city: str = "changsha",
    ) -> tuple[float, str]:
        """获取指定日期的天气因子

        优先调用和风天气API (3日预报), API不可用时降级为默认1.0。
        绝不阻塞主流程。

        Args:
            target_date: 目标日期
            city: 城市标识 (和风天气location id或名称)

        Returns:
            (天气因子, 天气描述) 元组
        """
        if not self._weather_api_key:
            log.debug(
                "demand_forecast_enhanced.weather_api_disabled",
                reason="QWEATHER_API_KEY not set",
            )
            return DEFAULT_WEATHER_FACTOR, "unknown"

        try:
            return await self._fetch_weather_from_api(target_date, city)
        except (OSError, ValueError, TimeoutError, KeyError) as exc:
            log.warning(
                "demand_forecast_enhanced.weather_api_failed",
                city=city,
                target_date=target_date.isoformat(),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return DEFAULT_WEATHER_FACTOR, "api_unavailable"

    async def _fetch_weather_from_api(
        self,
        target_date: date,
        city: str,
    ) -> tuple[float, str]:
        """调用和风天气API获取天气预报

        使用 3 日天气预报接口。
        超时 3 秒, 超时按默认值处理。
        """
        import httpx

        today = date.today()
        days_ahead = (target_date - today).days

        # 和风天气只支持3日预报(免费版), 超出范围用默认值
        if days_ahead < 0 or days_ahead > 2:
            log.debug(
                "demand_forecast_enhanced.weather_out_of_range",
                target_date=target_date.isoformat(),
                days_ahead=days_ahead,
            )
            return DEFAULT_WEATHER_FACTOR, "out_of_forecast_range"

        url = f"{self._weather_api_base}/v7/weather/3d"
        params = {
            "location": city,
            "key": self._weather_api_key,
            "lang": "en",
        }

        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != "200":
            log.warning(
                "demand_forecast_enhanced.weather_api_error_code",
                code=data.get("code"),
            )
            return DEFAULT_WEATHER_FACTOR, "api_error"

        daily_forecasts = data.get("daily", [])
        if days_ahead >= len(daily_forecasts):
            return DEFAULT_WEATHER_FACTOR, "no_data"

        forecast = daily_forecasts[days_ahead]
        condition = self._map_weather_condition(forecast.get("textDay", ""))
        factor = WEATHER_FACTORS.get(condition, DEFAULT_WEATHER_FACTOR)

        log.info(
            "demand_forecast_enhanced.weather_fetched",
            target_date=target_date.isoformat(),
            condition=condition,
            factor=factor,
            raw_text=forecast.get("textDay", ""),
        )
        return factor, condition

    @staticmethod
    def _map_weather_condition(text_day: str) -> str:
        """将和风天气API的天气文本映射为标准天气标识"""
        text_lower = text_day.lower()
        if "snow" in text_lower or "blizzard" in text_lower:
            return "snow"
        if "heavy rain" in text_lower or "storm" in text_lower or "torrential" in text_lower:
            return "heavy_rain"
        if "rain" in text_lower or "drizzle" in text_lower or "shower" in text_lower:
            return "rainy"
        if "cloud" in text_lower or "overcast" in text_lower:
            return "cloudy"
        return "sunny"

    # ──────────────────────────────────────────────────────
    #  节假日因子
    # ──────────────────────────────────────────────────────

    def get_holiday_factor(self, target_date: date) -> tuple[float, str | None]:
        """获取指定日期的节假日因子

        优先级:
          1. 法定节假日日历 (2026年)
          2. 调休工作日 -> 工作日因子
          3. 周末 -> 1.15
          4. 工作日 -> 1.0

        Args:
            target_date: 目标日期

        Returns:
            (节假日因子, 节假日名称或None)
        """
        key = (target_date.month, target_date.day)

        # 检查法定节假日
        if key in HOLIDAY_CALENDAR_2026:
            factor, name = HOLIDAY_CALENDAR_2026[key]
            return factor, name

        # 检查调休工作日 (本来是周末但要上班)
        if key in WORKDAY_ADJUSTMENTS_2026:
            return WORKDAY_FACTOR, None

        # 周末 (周六=5, 周日=6)
        if target_date.weekday() >= 5:
            return WEEKEND_FACTOR, None

        return WORKDAY_FACTOR, None

    # ──────────────────────────────────────────────────────
    #  季节因子
    # ──────────────────────────────────────────────────────

    def get_season_factor(
        self,
        ingredient_category: str | None,
        month: int,
    ) -> float:
        """按食材品类和月份获取季节系数

        Args:
            ingredient_category: 食材品类 (hotpot/bbq/cold_drink/hot_drink/
                                 seafood/vegetable/meat/staple/seasoning)
                                 None 或未知品类使用 default
            month: 月份 (1-12)

        Returns:
            季节系数 (0.5~1.5)
        """
        if month < 1 or month > 12:
            log.warning(
                "demand_forecast_enhanced.invalid_month",
                month=month,
            )
            return 1.0

        category_key = (ingredient_category or "default").lower()
        month_factors = SEASON_MATRIX.get(category_key, SEASON_MATRIX["default"])
        return month_factors[month - 1]

    # ──────────────────────────────────────────────────────
    #  历史反馈修正系数
    # ──────────────────────────────────────────────────────

    async def get_correction_factor(
        self,
        ingredient_id: str,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        *,
        lookback_days: int = 30,
    ) -> float:
        """从 procurement_feedback_logs 取最近30天偏差, 计算EMA修正系数

        算法:
          1. 查最近 lookback_days 天的 deviation_pct 记录
          2. 按时间排序, 用 EMA(alpha=0.3) 加权
          3. correction = 1.0 + EMA(deviation_pct / 100)
          4. 限制在 [0.7, 1.5] 区间

        无历史数据时返回 1.0 (不修正)

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
                "demand_forecast_enhanced.correction_query_failed",
                ingredient_id=ingredient_id,
                store_id=store_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return CORRECTION_DEFAULT

        if not rows:
            return CORRECTION_DEFAULT

        # EMA 计算
        ema = 0.0
        for row in rows:
            deviation = float(row.deviation_pct)
            ema = EMA_ALPHA * deviation + (1 - EMA_ALPHA) * ema

        correction = 1.0 + ema / 100.0
        correction = max(CORRECTION_MIN, min(CORRECTION_MAX, correction))

        log.info(
            "demand_forecast_enhanced.correction_factor",
            ingredient_id=ingredient_id,
            store_id=store_id,
            data_points=len(rows),
            ema_deviation=round(ema, 2),
            correction=round(correction, 3),
        )
        return round(correction, 3)

    # ──────────────────────────────────────────────────────
    #  获取食材品类 (辅助)
    # ──────────────────────────────────────────────────────

    async def _get_ingredient_category(
        self,
        ingredient_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> str | None:
        """从 ingredients 表获取食材品类"""
        sql = text("""
            SELECT category
            FROM ingredients
            WHERE id = :ingredient_id::UUID
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
            LIMIT 1
        """)
        try:
            result = await db.execute(
                sql,
                {"ingredient_id": ingredient_id, "tenant_id": tenant_id},
            )
            row = result.fetchone()
            return str(row.category) if row and row.category else None
        except (SQLAlchemyError, OperationalError) as exc:
            log.debug(
                "demand_forecast_enhanced.category_query_failed",
                ingredient_id=ingredient_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    # ──────────────────────────────────────────────────────
    #  主入口: 组合所有因子的需求预测
    # ──────────────────────────────────────────────────────

    async def forecast_demand(
        self,
        ingredient_id: str,
        store_id: str,
        days: int,
        tenant_id: str,
        db: AsyncSession,
        *,
        city: str = "changsha",
        ingredient_category: str | None = None,
        _mock_daily: float | None = None,
        _mock_weather_factor: float | None = None,
        _mock_holiday_factor: float | None = None,
        _mock_season_factor: float | None = None,
        _mock_correction_factor: float | None = None,
    ) -> dict[str, Any]:
        """增强型需求预测 -- 主入口

        公式:
          建议量 = 日均消耗 x 天气因子 x 节假日因子 x 季节因子
                   x 历史修正系数 x 预测天数

        每天的因子可能不同, 实际逐日累加。

        Args:
            ingredient_id: 原料ID
            store_id: 门店ID
            days: 预测天数
            tenant_id: 租户ID
            db: 数据库会话
            city: 城市(天气API用)
            ingredient_category: 食材品类 (None时从DB查询)
            _mock_*: 测试注入参数

        Returns:
            预测结果字典, 含 total_forecast、daily_breakdown、各因子明细
        """
        await self._set_tenant(db, tenant_id)

        # 1. 日均消耗 (复用基础预测服务)
        if _mock_daily is not None:
            daily_consumption = _mock_daily
        else:
            daily_consumption = await self._base_forecast.get_daily_consumption(
                ingredient_id=ingredient_id,
                store_id=store_id,
                days=7,
                tenant_id=tenant_id,
                db=db,
            )

        if daily_consumption <= 0:
            log.info(
                "demand_forecast_enhanced.zero_consumption",
                ingredient_id=ingredient_id,
                store_id=store_id,
            )
            return {
                "ingredient_id": ingredient_id,
                "store_id": store_id,
                "daily_consumption": 0.0,
                "total_forecast": 0.0,
                "days": days,
                "daily_breakdown": [],
                "factors_summary": {},
            }

        # 2. 获取食材品类 (季节系数用)
        if ingredient_category is None and _mock_season_factor is None:
            ingredient_category = await self._get_ingredient_category(
                ingredient_id, tenant_id, db,
            )

        # 3. 历史修正系数
        if _mock_correction_factor is not None:
            correction = _mock_correction_factor
        else:
            correction = await self.get_correction_factor(
                ingredient_id, store_id, tenant_id, db,
            )

        # 4. 逐日计算 (天气+节假日+季节各日不同)
        today = date.today()
        daily_breakdown: list[dict[str, Any]] = []
        total_forecast = 0.0

        weather_factors_used: list[float] = []
        holiday_factors_used: list[float] = []
        season_factors_used: list[float] = []

        for i in range(days):
            target_date = today + timedelta(days=i + 1)

            # 天气因子
            if _mock_weather_factor is not None:
                w_factor = _mock_weather_factor
                w_condition = "mock"
            else:
                w_factor, w_condition = await self.get_weather_factor(
                    target_date, city,
                )

            # 节假日因子
            if _mock_holiday_factor is not None:
                h_factor = _mock_holiday_factor
                h_name: str | None = "mock"
            else:
                h_factor, h_name = self.get_holiday_factor(target_date)

            # 季节因子
            if _mock_season_factor is not None:
                s_factor = _mock_season_factor
            else:
                s_factor = self.get_season_factor(
                    ingredient_category, target_date.month,
                )

            # 组合: 日均消耗 x 天气 x 节假日 x 季节 x 修正
            day_forecast = (
                daily_consumption
                * w_factor
                * h_factor
                * s_factor
                * correction
            )
            total_forecast += day_forecast

            weather_factors_used.append(w_factor)
            holiday_factors_used.append(h_factor)
            season_factors_used.append(s_factor)

            daily_breakdown.append({
                "date": target_date.isoformat(),
                "day_of_week": target_date.strftime("%A"),
                "base_consumption": round(daily_consumption, 4),
                "weather_factor": round(w_factor, 2),
                "weather_condition": w_condition,
                "holiday_factor": round(h_factor, 2),
                "holiday_name": h_name,
                "season_factor": round(s_factor, 2),
                "correction_factor": round(correction, 3),
                "forecast_qty": round(day_forecast, 4),
            })

        # 汇总因子平均值 (用于概览)
        avg_weather = (
            sum(weather_factors_used) / len(weather_factors_used)
            if weather_factors_used else DEFAULT_WEATHER_FACTOR
        )
        avg_holiday = (
            sum(holiday_factors_used) / len(holiday_factors_used)
            if holiday_factors_used else WORKDAY_FACTOR
        )
        avg_season = (
            sum(season_factors_used) / len(season_factors_used)
            if season_factors_used else 1.0
        )

        result = {
            "ingredient_id": ingredient_id,
            "store_id": store_id,
            "daily_consumption": round(daily_consumption, 4),
            "total_forecast": round(total_forecast, 2),
            "days": days,
            "daily_breakdown": daily_breakdown,
            "factors_summary": {
                "avg_weather_factor": round(avg_weather, 3),
                "avg_holiday_factor": round(avg_holiday, 3),
                "avg_season_factor": round(avg_season, 3),
                "correction_factor": round(correction, 3),
                "ingredient_category": ingredient_category or "default",
            },
        }

        log.info(
            "demand_forecast_enhanced.forecast_complete",
            ingredient_id=ingredient_id,
            store_id=store_id,
            days=days,
            daily_consumption=round(daily_consumption, 4),
            total_forecast=round(total_forecast, 2),
            correction=round(correction, 3),
            avg_weather=round(avg_weather, 3),
            avg_holiday=round(avg_holiday, 3),
            avg_season=round(avg_season, 3),
        )
        return result

    # ──────────────────────────────────────────────────────
    #  批量预测 (多原料)
    # ──────────────────────────────────────────────────────

    async def forecast_batch(
        self,
        ingredient_ids: list[str],
        store_id: str,
        days: int,
        tenant_id: str,
        db: AsyncSession,
        *,
        city: str = "changsha",
    ) -> dict[str, Any]:
        """批量预测多个原料的需求

        Args:
            ingredient_ids: 原料ID列表
            store_id: 门店ID
            days: 预测天数
            tenant_id: 租户ID
            db: 数据库会话
            city: 城市

        Returns:
            {
                "store_id": str,
                "days": int,
                "forecasts": [预测结果列表],
                "total_count": int,
            }
        """
        forecasts: list[dict[str, Any]] = []
        for ingredient_id in ingredient_ids:
            forecast = await self.forecast_demand(
                ingredient_id=ingredient_id,
                store_id=store_id,
                days=days,
                tenant_id=tenant_id,
                db=db,
                city=city,
            )
            forecasts.append(forecast)

        log.info(
            "demand_forecast_enhanced.batch_complete",
            store_id=store_id,
            count=len(forecasts),
            days=days,
        )
        return {
            "store_id": store_id,
            "days": days,
            "forecasts": forecasts,
            "total_count": len(forecasts),
        }
