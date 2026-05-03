"""AI 2.0 多市场联合预测 + 区域服务集成测试"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date

import pytest


def _load_module(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRegionalForecasting:
    """AI 2.0 跨市场预测服务"""

    @pytest.fixture
    def service(self):
        mod = _load_module(
            "regional_forecasting_service",
            "services/tx-agent/src/services/regional_forecasting_service.py",
        )
        return mod.RegionalForecastingService()

    def test_get_market_overview_my(self, service):
        """马来西亚市场配置"""
        ov = service.get_market_overview("MY")
        assert ov["country_code"] == "MY"
        assert ov["currency"]["symbol"] == "RM"
        assert "sst_standard" in ov["tax_rates"]
        assert ov["timezone"] == "Asia/Kuala_Lumpur"

    def test_get_market_overview_id(self, service):
        """印尼市场配置"""
        ov = service.get_market_overview("ID")
        assert ov["currency"]["code"] == "IDR"
        assert "ppn_standard" in ov["tax_rates"]

    def test_get_market_overview_vn(self, service):
        """越南市场配置"""
        ov = service.get_market_overview("VN")
        assert ov["currency"]["code"] == "VND"
        assert "vat_standard" in ov["tax_rates"]

    def test_get_market_overview_unlisted(self, service):
        """未列出的市场返回默认配置参数 (fallback to MY)"""
        ov = service.get_market_overview("SG")
        assert ov["country_code"] == "SG"
        assert ov["timezone"] == "Asia/Kuala_Lumpur"

    def test_cross_market_forecast(self, service):
        """跨市场预测扩展"""
        base = {"market": "MY", "predicted_revenue": 100000}
        result = service.forecast_cross_market(base, ["MY", "ID", "VN"])
        assert "market_forecasts" in result
        assert "MY" in result["market_forecasts"]
        assert "ID" in result["market_forecasts"]
        assert "VN" in result["market_forecasts"]

    def test_holiday_impact_multi_market(self, service):
        """多市场节假日分析"""
        result = service.get_holiday_impact_multi_market(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 12, 31),
            markets=["MY", "ID", "VN"],
        )
        assert result["market_impacts"]["MY"]["holiday_count"] > 0
        assert result["market_impacts"]["ID"]["holiday_count"] > 0
        assert result["market_impacts"]["VN"]["holiday_count"] > 0

    def test_cuisine_recommendations_my(self, service):
        """马来西亚菜系推荐"""
        recs = service.get_cuisine_recommendations("MY")
        assert len(recs) > 0
        names = [r["cuisine"] for r in recs]
        assert "Nasi Lemak" in names

    def test_cuisine_recommendations_id(self, service):
        """印尼菜系推荐"""
        recs = service.get_cuisine_recommendations("ID")
        names = [r["cuisine"] for r in recs]
        assert "Nasi Goreng" in names

    def test_cuisine_recommendations_vn(self, service):
        """越南菜系推荐"""
        recs = service.get_cuisine_recommendations("VN")
        names = [r["cuisine"] for r in recs]
        assert "Phở" in names

    def test_market_readiness_my(self, service):
        """马来西亚市场就绪度"""
        ra = service.assess_market_readiness("MY")
        assert ra["readiness_score"] >= 0.8
        assert ra["recommendation"] == "全面进入"

    def test_market_readiness_id(self, service):
        """印尼市场就绪度"""
        ra = service.assess_market_readiness("ID")
        assert "readiness_score" in ra
        assert ra["recommendation"] in ("Beta 测试", "全面进入", "预研阶段")

    def test_market_readiness_unknown(self, service):
        """未知市场"""
        ra = service.assess_market_readiness("TH")
        assert ra["recommendation"] == "预研阶段"
