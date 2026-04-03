"""金蝶ERP路由端点测试

验证8个API端点的请求/响应模型:
1. POST /export/purchase-receipt
2. POST /export/cost-transfer
3. POST /export/transfer
4. POST /export/salary-accrual
5. POST /export/daily-revenue
6. POST /export/sales-delivery
7. GET  /export/history
8. POST /export/retry
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.kingdee_routes import (
    DailyExportRequest,
    MonthExportRequest,
    RetryRequest,
    router,
)


class TestRequestModels:
    def test_month_export_valid(self):
        req = MonthExportRequest(store_id="s1", month="2026-03")
        assert req.store_id == "s1"
        assert req.month == "2026-03"

    def test_month_export_invalid_format(self):
        with pytest.raises(Exception):
            MonthExportRequest(store_id="s1", month="2026-3")

    def test_daily_export_valid(self):
        req = DailyExportRequest(store_id="s1", date="2026-03-15")
        assert req.date == "2026-03-15"

    def test_daily_export_invalid_format(self):
        with pytest.raises(Exception):
            DailyExportRequest(store_id="s1", date="20260315")

    def test_retry_request(self):
        req = RetryRequest(export_id="abc123")
        assert req.export_id == "abc123"


class TestRouterRegistration:
    def test_router_prefix(self):
        assert router.prefix == "/api/v1/kingdee"

    def test_router_has_8_routes(self):
        """路由器应包含8个端点"""
        route_paths = [r.path for r in router.routes]
        expected_paths = [
            "/export/purchase-receipt",
            "/export/cost-transfer",
            "/export/transfer",
            "/export/salary-accrual",
            "/export/daily-revenue",
            "/export/sales-delivery",
            "/export/history",
            "/export/retry",
        ]
        for path in expected_paths:
            assert path in route_paths, f"Missing route: {path}"

    def test_post_endpoints_count(self):
        """POST 端点应有 7 个"""
        post_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "POST" in r.methods
        ]
        assert len(post_routes) == 7

    def test_get_endpoints_count(self):
        """GET 端点应有 1 个"""
        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
        ]
        assert len(get_routes) == 1
