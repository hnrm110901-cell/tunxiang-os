"""AI 2.0 — 东南亚多市场联合预测服务

支持市场: MY(马来西亚), ID(印度尼西亚), VN(越南)
数据源: 各市场本地节假日 + 菜系 + 食材 + 历史订单
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# 各市场货币信息
MARKET_CURRENCIES = {
    "MY": {"code": "MYR", "symbol": "RM", "name": "Malaysian Ringgit"},
    "ID": {"code": "IDR", "symbol": "Rp", "name": "Indonesian Rupiah"},
    "VN": {"code": "VND", "symbol": "₫", "name": "Vietnamese Dong"},
}

# 各市场税率
MARKET_TAX_RATES = {
    "MY": {"sst_standard": 0.06, "sst_specific": 0.08},
    "ID": {"ppn_standard": 0.11, "ppn_luxury": 0.12},
    "VN": {"vat_standard": 0.10, "vat_reduced": 0.08},
}

# 各市场营业高峰时段（本地时间）
MARKET_PEAK_HOURS = {
    "MY": {"breakfast": (7, 10), "lunch": (11, 14), "dinner": (18, 21)},
    "ID": {"breakfast": (6, 9), "lunch": (11, 14), "dinner": (18, 21)},
    "VN": {"breakfast": (6, 9), "lunch": (11, 13), "dinner": (17, 20)},
}


class RegionalForecastingService:
    """跨市场 AI 预测服务"""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    # ── 市场概况 ──────────────────────────────────────────────────────────

    def get_market_overview(self, country_code: str) -> dict[str, Any]:
        """返回指定市场的基础配置信息。"""
        currency = MARKET_CURRENCIES.get(country_code, MARKET_CURRENCIES["MY"])
        tax = MARKET_TAX_RATES.get(country_code, MARKET_TAX_RATES["MY"])
        peak = MARKET_PEAK_HOURS.get(country_code, MARKET_PEAK_HOURS["MY"])

        return {
            "country_code": country_code,
            "currency": currency,
            "tax_rates": tax,
            "peak_hours": peak,
            "timezone": self._get_timezone(country_code),
        }

    @staticmethod
    def _get_timezone(country_code: str) -> str:
        mapping = {"MY": "Asia/Kuala_Lumpur", "ID": "Asia/Jakarta", "VN": "Asia/Ho_Chi_Minh"}
        return mapping.get(country_code, "Asia/Kuala_Lumpur")

    # ── 跨市场预测 ────────────────────────────────────────────────────────

    def forecast_cross_market(
        self,
        base_forecast: dict[str, Any],
        target_markets: list[str],
    ) -> dict[str, Any]:
        """将基准市场预测扩展到多个目标市场。

        使用市场系数调整：
          - 人口系数 (人口比例)
          - 购买力系数 (PPP per capita 比例)
          - 餐饮支出系数 (外出就餐支出比例)
        """
        # 市场调整系数（相对于 MY 基准）
        market_factors = {
            "MY": {"population": 1.0, "purchasing_power": 1.0, "dining_spend": 1.0},
            "ID": {"population": 4.2, "purchasing_power": 0.6, "dining_spend": 0.7},
            "VN": {"population": 1.8, "purchasing_power": 0.5, "dining_spend": 0.6},
        }

        market_forecasts = {}
        for market in target_markets:
            factors = market_factors.get(market, market_factors["MY"])
            adjustment = factors["population"] * factors["purchasing_power"] * factors["dining_spend"]
            market_forecasts[market] = {
                "market": market,
                "adjusted_revenue": round(base_forecast.get("predicted_revenue", 0) * adjustment, 2),
                "adjustment_factors": factors,
                "currency": MARKET_CURRENCIES.get(market, MARKET_CURRENCIES["MY"]),
                "confidence": self._calculate_cross_market_confidence(market),
            }

        return {
            "base_market": base_forecast.get("market", "MY"),
            "base_forecast": base_forecast,
            "market_forecasts": market_forecasts,
            "generated_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _calculate_cross_market_confidence(market: str) -> float:
        """计算跨市场预测的置信度。

        新市场数据较少，置信度低于基准市场。
        """
        base = {"MY": 0.85, "ID": 0.65, "VN": 0.60}
        return base.get(market, 0.50)

    # ── 多市场节假日影响 ──────────────────────────────────────────────────

    def get_holiday_impact_multi_market(
        self,
        start_date: date,
        end_date: date,
        markets: list[str],
    ) -> dict[str, Any]:
        """分析多个市场在日期范围内的节假日影响。"""
        impacts = {}
        for market in markets:
            holidays = self._get_market_holidays(market, start_date, end_date)
            impact_score = sum(h.get("impact", 0) for h in holidays)
            impacts[market] = {
                "holiday_count": len(holidays),
                "total_impact_score": impact_score,
                "holidays": holidays[:5],  # 最多返回 5 个
                "expected_revenue_multiplier": self._holiday_to_multiplier(impact_score),
            }

        return {
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "market_impacts": impacts,
        }

    @staticmethod
    def _get_market_holidays(market: str, start: date, end: date) -> list[dict[str, Any]]:
        """获取指定市场的节假日列表（简化版）。"""
        holidays_db = {
            "MY": [
                {"name": "Hari Raya Aidilfitri", "date": "2026-04-10", "impact": 8},
                {"name": "Labour Day", "date": "2026-05-01", "impact": 5},
                {"name": "National Day", "date": "2026-08-31", "impact": 7},
                {"name": "Deepavali", "date": "2026-11-08", "impact": 6},
                {"name": "Christmas", "date": "2026-12-25", "impact": 7},
            ],
            "ID": [
                {"name": "Idul Fitri", "date": "2026-04-10", "impact": 9},
                {"name": "Independence Day", "date": "2026-08-17", "impact": 6},
                {"name": "Christmas", "date": "2026-12-25", "impact": 5},
            ],
            "VN": [
                {"name": "Tet (Lunar New Year)", "date": "2026-02-17", "impact": 9},
                {"name": "Reunification Day", "date": "2026-04-30", "impact": 6},
                {"name": "National Day", "date": "2026-09-02", "impact": 5},
            ],
        }

        holidays = holidays_db.get(market, [])
        result = []
        for h in holidays:
            h_date = date.fromisoformat(h["date"])
            if start <= h_date <= end:
                result.append(h)
        return result

    @staticmethod
    def _holiday_to_multiplier(impact_score: int) -> float:
        """将节假日影响分数转换为营收倍数。"""
        mapping = {9: 2.5, 8: 2.0, 7: 1.8, 6: 1.5, 5: 1.3, 4: 1.2, 3: 1.1, 2: 1.05, 1: 1.02, 0: 1.0}
        return mapping.get(impact_score, 1.0)

    # ── 跨市场菜系推荐 ────────────────────────────────────────────────────

    def get_cuisine_recommendations(
        self, market: str, season: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """获取面向特定市场的菜系优化推荐。"""
        profiles = {
            "MY": [
                {"cuisine": "Nasi Lemak", "popularity": 0.95, "margin": 0.65, "trend": "stable"},
                {"cuisine": "Satay", "popularity": 0.88, "margin": 0.70, "trend": "growing"},
                {"cuisine": "Roti Canai", "popularity": 0.90, "margin": 0.75, "trend": "stable"},
                {"cuisine": "Laksa", "popularity": 0.82, "margin": 0.68, "trend": "growing"},
            ],
            "ID": [
                {"cuisine": "Nasi Goreng", "popularity": 0.95, "margin": 0.62, "trend": "stable"},
                {"cuisine": "Sate", "popularity": 0.85, "margin": 0.68, "trend": "stable"},
                {"cuisine": "Rendang", "popularity": 0.80, "margin": 0.72, "trend": "growing"},
                {"cuisine": "Gado-Gado", "popularity": 0.72, "margin": 0.78, "trend": "growing"},
            ],
            "VN": [
                {"cuisine": "Phở", "popularity": 0.96, "margin": 0.60, "trend": "stable"},
                {"cuisine": "Bánh Mì", "popularity": 0.90, "margin": 0.72, "trend": "growing"},
                {"cuisine": "Bún Chả", "popularity": 0.78, "margin": 0.65, "trend": "stable"},
                {"cuisine": "Spring Rolls", "popularity": 0.82, "margin": 0.70, "trend": "growing"},
            ],
        }

        return profiles.get(market, profiles["MY"])

    # ── 市场扩张建议 ──────────────────────────────────────────────────────

    def assess_market_readiness(self, country_code: str) -> dict[str, Any]:
        """评估某个市场的扩张就绪度。"""
        assessments = {
            "MY": {
                "readiness_score": 0.92,
                "strengths": ["已部署 MyInvois", "SST 合规就绪", "本地支付已集成"],
                "gaps": ["淡米尔语翻译待完善", "Foodpanda 深度集成进行中"],
                "recommendation": "全面进入",
            },
            "ID": {
                "readiness_score": 0.78,
                "strengths": ["PPN 税引擎就绪", "GoPay/DANA 已集成"],
                "gaps": ["ShopeeFood ID 适配器待开发", "印尼语翻译覆盖 80%"],
                "recommendation": "Beta 测试",
            },
            "VN": {
                "readiness_score": 0.72,
                "strengths": ["VAT 税引擎就绪", "MoMo/ZaloPay 已集成"],
                "gaps": ["ShopeeFood VN 适配器待开发", "越南语翻译覆盖 70%"],
                "recommendation": "Beta 测试",
            },
        }

        return assessments.get(country_code, {"readiness_score": 0.5, "recommendation": "预研阶段"})
