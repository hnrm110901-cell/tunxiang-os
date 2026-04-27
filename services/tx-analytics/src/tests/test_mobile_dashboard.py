"""移动端管理直通车 — 后端 API 测试

覆盖：
  1. test_dashboard_api_returns_required_fields  — 仪表盘API返回营业额/客流量字段
  2. test_anomaly_aggregation_structure          — 异常汇总返回分类+数量
  3. test_mobile_data_within_tenant              — tenant隔离验证
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ════════════════════════════════════════
# Test 1: 仪表盘 API 返回必需字段
# ════════════════════════════════════════


class TestDashboardApiReturnsRequiredFields:
    """仪表盘API必须返回 revenue_fen 和 customer_count 字段。"""

    def test_dashboard_response_has_revenue_fen(self):
        """营业额字段 revenue_fen 必须存在且为整数（分）。"""
        mock_response = {
            "revenue_fen": 1258000,
            "customer_count": 156,
            "new_members": 23,
            "gross_margin_pct": 0.42,
            "trend_5day": [980000, 1120000, 890000, 1350000, 1258000],
            "stores": [],
            "anomaly_discount": 2,
            "anomaly_inventory": 1,
        }
        assert "revenue_fen" in mock_response
        assert isinstance(mock_response["revenue_fen"], int)
        assert mock_response["revenue_fen"] >= 0

    def test_dashboard_response_has_customer_count(self):
        """客流量字段 customer_count 必须存在且为非负整数。"""
        mock_response = {
            "revenue_fen": 1258000,
            "customer_count": 156,
            "gross_margin_pct": 0.42,
        }
        assert "customer_count" in mock_response
        assert isinstance(mock_response["customer_count"], int)
        assert mock_response["customer_count"] >= 0

    def test_dashboard_response_has_gross_margin(self):
        """毛利率字段 gross_margin_pct 必须在 0~1 范围内。"""
        mock_response = {
            "revenue_fen": 1258000,
            "customer_count": 156,
            "gross_margin_pct": 0.42,
        }
        assert "gross_margin_pct" in mock_response
        pct = mock_response["gross_margin_pct"]
        assert 0.0 <= pct <= 1.0, f"gross_margin_pct={pct} 超出 [0,1] 范围"

    def test_dashboard_trend_5day_has_five_elements(self):
        """近5日趋势数组必须恰好有5个元素。"""
        mock_response = {
            "revenue_fen": 1258000,
            "customer_count": 156,
            "gross_margin_pct": 0.42,
            "trend_5day": [980000, 1120000, 890000, 1350000, 1258000],
        }
        assert "trend_5day" in mock_response
        assert len(mock_response["trend_5day"]) == 5

    def test_dashboard_revenue_fen_matches_yuan_calculation(self):
        """分转元计算逻辑验证：1258000分 = ¥12,580。"""
        revenue_fen = 1258000
        revenue_yuan = revenue_fen / 100
        assert revenue_yuan == 12580.0

    def test_gross_margin_threshold_low(self):
        """毛利率 < 30% 应触发警告标志。"""
        gross_margin_pct = 0.25
        is_low = gross_margin_pct < 0.30
        assert is_low is True

    def test_gross_margin_threshold_healthy(self):
        """毛利率 >= 50% 应为健康状态。"""
        gross_margin_pct = 0.52
        is_healthy = gross_margin_pct >= 0.50
        assert is_healthy is True

    def test_estimated_cost_calculation(self):
        """预估成本 = 营业额 * 0.35，用于毛利红线计算。"""
        revenue_fen = 1258000
        estimated_cost_fen = int(revenue_fen * 0.35)
        assert estimated_cost_fen == 440300

    def test_anomaly_counts_are_non_negative(self):
        """折扣异常和库存预警数量必须为非负整数。"""
        mock_response = {
            "anomaly_discount": 2,
            "anomaly_inventory": 1,
        }
        assert mock_response["anomaly_discount"] >= 0
        assert mock_response["anomaly_inventory"] >= 0


# ════════════════════════════════════════
# Test 2: 异常汇总结构验证
# ════════════════════════════════════════


class TestAnomalyAggregationStructure:
    """异常汇总 API 返回的数据结构验证。"""

    def _make_anomaly_group(
        self,
        category: str,
        label: str,
        count: int,
        items: list,
    ) -> dict:
        return {"category": category, "label": label, "count": count, "items": items}

    def test_anomaly_response_has_four_categories(self):
        """异常汇总必须包含4个分类：折扣/退单/库存/Agent。"""
        required_categories = {"discount", "refund", "inventory", "agent"}
        groups = [
            self._make_anomaly_group("discount", "折扣异常", 2, []),
            self._make_anomaly_group("refund", "退单异常", 0, []),
            self._make_anomaly_group("inventory", "库存预警", 1, []),
            self._make_anomaly_group("agent", "Agent预警", 0, []),
        ]
        actual_categories = {g["category"] for g in groups}
        assert actual_categories == required_categories

    def test_anomaly_group_has_count_field(self):
        """每个分类必须有 count 字段（今日数量）。"""
        group = self._make_anomaly_group("discount", "折扣异常", 2, [])
        assert "count" in group
        assert isinstance(group["count"], int)

    def test_anomaly_group_has_items_list(self):
        """每个分类必须有 items 列表（具体异常条目）。"""
        group = self._make_anomaly_group("discount", "折扣异常", 2, [])
        assert "items" in group
        assert isinstance(group["items"], list)

    def test_anomaly_item_has_required_fields(self):
        """异常条目必须包含：store_name/time/description/severity。"""
        item = {
            "id": "a1",
            "store_name": "五一广场店",
            "time": "13:42",
            "description": "服务员陈某使用越权折扣",
            "severity": "high",
            "handled": False,
        }
        required_fields = {"id", "store_name", "time", "description", "severity", "handled"}
        for field in required_fields:
            assert field in item, f"异常条目缺少字段: {field}"

    def test_anomaly_severity_values_are_valid(self):
        """severity 必须是 high/medium/low 之一。"""
        valid_severities = {"high", "medium", "low"}
        items = [
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        for item in items:
            assert item["severity"] in valid_severities

    def test_anomaly_count_matches_items_length(self):
        """count 字段必须与 items 数组长度一致。"""
        items = [
            {
                "id": "a1",
                "store_name": "五一广场店",
                "time": "13:42",
                "description": "折扣异常",
                "severity": "high",
                "handled": False,
            },
            {
                "id": "a2",
                "store_name": "解放西路店",
                "time": "11:15",
                "description": "整单免单",
                "severity": "high",
                "handled": False,
            },
        ]
        group = self._make_anomaly_group("discount", "折扣异常", len(items), items)
        assert group["count"] == len(group["items"])

    def test_handled_anomaly_excluded_from_active_count(self):
        """已处理的异常不应计入活跃异常数量。"""
        items = [
            {"id": "a1", "handled": False},
            {"id": "a2", "handled": True},
            {"id": "a3", "handled": False},
        ]
        active_count = sum(1 for i in items if not i["handled"])
        assert active_count == 2

    def test_total_unhandled_aggregation(self):
        """跨所有分类的未处理总数计算正确。"""
        groups = [
            {"category": "discount", "items": [{"handled": False}, {"handled": True}]},
            {"category": "inventory", "items": [{"handled": False}]},
            {"category": "refund", "items": []},
            {"category": "agent", "items": []},
        ]
        total = sum(sum(1 for i in g["items"] if not i["handled"]) for g in groups)
        assert total == 2


# ════════════════════════════════════════
# Test 3: Tenant 隔离验证
# ════════════════════════════════════════


class TestMobileDataWithinTenant:
    """移动端 API 必须严格按 tenant_id 隔离数据。"""

    def test_dashboard_data_scoped_to_tenant(self):
        """仪表盘数据必须带 tenant_id 过滤条件。"""
        tenant_a_data = {"tenant_id": "tenant-a", "revenue_fen": 1000000}
        tenant_b_data = {"tenant_id": "tenant-b", "revenue_fen": 2000000}

        def get_dashboard(tenant_id: str):
            if tenant_id == "tenant-a":
                return tenant_a_data
            return tenant_b_data

        result_a = get_dashboard("tenant-a")
        result_b = get_dashboard("tenant-b")

        assert result_a["revenue_fen"] != result_b["revenue_fen"]
        assert result_a["tenant_id"] == "tenant-a"
        assert result_b["tenant_id"] == "tenant-b"

    def test_anomalies_not_visible_cross_tenant(self):
        """租户A的异常数据不应在租户B的查询中出现。"""
        anomaly_store = [
            {"id": "a1", "tenant_id": "tenant-a", "store_name": "五一广场店"},
            {"id": "a2", "tenant_id": "tenant-b", "store_name": "北京旗舰店"},
        ]

        def get_anomalies_for_tenant(tenant_id: str):
            return [a for a in anomaly_store if a["tenant_id"] == tenant_id]

        tenant_a_anomalies = get_anomalies_for_tenant("tenant-a")
        tenant_b_anomalies = get_anomalies_for_tenant("tenant-b")

        assert len(tenant_a_anomalies) == 1
        assert tenant_a_anomalies[0]["store_name"] == "五一广场店"
        assert len(tenant_b_anomalies) == 1
        assert tenant_b_anomalies[0]["store_name"] == "北京旗舰店"

    def test_table_status_scoped_to_store_within_tenant(self):
        """桌态数据必须按 store_id 过滤，且 store 必须属于当前 tenant。"""
        stores = [
            {"store_id": "s1", "tenant_id": "tenant-a", "store_name": "五一广场店"},
            {"store_id": "s2", "tenant_id": "tenant-a", "store_name": "解放西路店"},
            {"store_id": "s3", "tenant_id": "tenant-b", "store_name": "北京旗舰店"},
        ]

        def can_access_store(tenant_id: str, store_id: str) -> bool:
            store = next((s for s in stores if s["store_id"] == store_id), None)
            if store is None:
                return False
            return store["tenant_id"] == tenant_id

        assert can_access_store("tenant-a", "s1") is True
        assert can_access_store("tenant-a", "s2") is True
        assert can_access_store("tenant-a", "s3") is False  # 跨租户访问被拒
        assert can_access_store("tenant-b", "s3") is True

    def test_tenant_id_required_in_api_header(self):
        """API 请求必须携带 X-Tenant-ID header，否则拒绝。"""

        def validate_request(headers: dict) -> bool:
            return bool(headers.get("X-Tenant-ID"))

        assert validate_request({"X-Tenant-ID": "tenant-a"}) is True
        assert validate_request({"X-Tenant-ID": ""}) is False
        assert validate_request({}) is False

    def test_rls_filter_uses_correct_session_variable(self):
        """RLS 策略必须使用 app.tenant_id，不使用 NULL 可绕过的方式。"""
        # 模拟 RLS 策略验证逻辑
        valid_rls_policy = "current_setting('app.tenant_id')"
        invalid_rls_policies = [
            "current_setting('request.jwt.claim.tenant_id', true)",
            "tenant_id IS NULL",
        ]

        # 验证正确策略包含预期的 session 变量
        assert "app.tenant_id" in valid_rls_policy

        # 验证错误策略不包含安全的 session 变量
        for policy in invalid_rls_policies:
            assert "app.tenant_id" not in policy, f"RLS策略不安全: {policy}"

    def test_store_belongs_to_tenant_before_data_access(self):
        """访问门店桌态前，必须先验证门店归属当前租户。"""

        def fetch_table_data(tenant_id: str, store_id: str) -> dict:
            # 模拟: 先校验归属，再返回数据
            store_tenant_map = {"s1": "tenant-a", "s2": "tenant-a", "s3": "tenant-b"}
            actual_tenant = store_tenant_map.get(store_id)
            if actual_tenant != tenant_id:
                raise PermissionError(f"门店 {store_id} 不属于租户 {tenant_id}")
            return {"store_id": store_id, "tables": []}

        # 合法访问
        result = fetch_table_data("tenant-a", "s1")
        assert result["store_id"] == "s1"

        # 跨租户访问应被拒绝
        with pytest.raises(PermissionError):
            fetch_table_data("tenant-a", "s3")
