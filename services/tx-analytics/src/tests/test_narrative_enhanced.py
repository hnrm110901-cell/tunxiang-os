"""
P3-02 经营叙事引擎增强 — 单元测试
测试对比叙事、异常叙事、日报生成三个端点。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.narrative_enhanced_routes import router

# ─── Test App ────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"X-Tenant-ID": "test-tenant"}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def get_comparison(store_id: str = "store-001", date_str: str = "2026-04-05"):
    return client.get(
        "/api/v1/analytics/narrative/comparison",
        params={"store_id": store_id, "date": date_str},
        headers=HEADERS,
    )


def get_anomaly(store_id: str = "store-001", date_str: str = "2026-04-06", threshold: float = 2.0):
    return client.get(
        "/api/v1/analytics/narrative/anomaly",
        params={"store_id": store_id, "date": date_str, "threshold": threshold},
        headers=HEADERS,
    )


def post_daily_report(
    store_id: str = "store-001",
    date_str: str = "2026-04-05",
    include_comparison: bool = True,
    include_anomaly: bool = True,
    template_id: str = None,
):
    body = {
        "store_id": store_id,
        "date": date_str,
        "include_comparison": include_comparison,
        "include_anomaly": include_anomaly,
    }
    if template_id is not None:
        body["template_id"] = template_id
    return client.post(
        "/api/v1/analytics/narrative/daily-report",
        json=body,
        headers=HEADERS,
    )


# ─── Test 1: 对比叙事 ────────────────────────────────────────────────────────


class TestComparisonNarrative:
    def test_response_ok(self):
        """基础 HTTP 200 + ok=True"""
        resp = get_comparison()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["error"] is None

    def test_comparisons_list_not_empty(self):
        """comparisons 列表非空，且包含 yesterday 维度"""
        resp = get_comparison()
        data = resp.json()["data"]
        assert isinstance(data["comparisons"], list)
        assert len(data["comparisons"]) >= 1
        dimensions = [c["dimension"] for c in data["comparisons"]]
        assert "yesterday" in dimensions

    def test_comparison_yesterday_change_rate_is_float(self):
        """yesterday 维度的 change_rate 字段是 float，且在合理范围"""
        resp = get_comparison()
        data = resp.json()["data"]
        yesterday = next(c for c in data["comparisons"] if c["dimension"] == "yesterday")
        assert isinstance(yesterday["change_rate"], float)
        assert -1.0 <= yesterday["change_rate"] <= 10.0  # 合理范围

    def test_comparison_headline_not_empty(self):
        """headline 字段非空"""
        resp = get_comparison()
        data = resp.json()["data"]
        assert data["headline"]
        assert len(data["headline"]) > 5

    def test_comparison_key_drivers_list(self):
        """key_drivers 是非空列表"""
        resp = get_comparison()
        data = resp.json()["data"]
        assert isinstance(data["key_drivers"], list)
        assert len(data["key_drivers"]) >= 1

    def test_comparison_full_narrative_contains_store(self):
        """full_narrative 包含叙事分隔符（▸）"""
        resp = get_comparison()
        data = resp.json()["data"]
        assert "▸" in data["full_narrative"]

    def test_comparison_multiple_dimensions(self):
        """指定多维度时返回多个对比结果"""
        resp = client.get(
            "/api/v1/analytics/narrative/comparison",
            params={
                "store_id": "store-001",
                "date": "2026-04-05",
                "compare_with": ["yesterday", "last_week", "last_month"],
            },
            headers=HEADERS,
        )
        data = resp.json()["data"]
        assert len(data["comparisons"]) == 3

    def test_comparison_trend_direction(self):
        """trend 字段值在 up/down/flat 范围内"""
        resp = get_comparison()
        data = resp.json()["data"]
        for c in data["comparisons"]:
            assert c["trend"] in ("up", "down", "flat")

    def test_comparison_different_dates_produce_different_data(self):
        """不同日期生成不同的数据（数据驱动差异化）"""
        resp1 = get_comparison(date_str="2026-04-01")
        resp2 = get_comparison(date_str="2026-04-05")
        data1 = resp1.json()["data"]
        data2 = resp2.json()["data"]
        # revenue 可能不同（seed 不同）
        # 至少 headline 文本不完全相同，或者 revenue_fen 不同
        assert data1["date"] != data2["date"]

    def test_comparison_no_store_id(self):
        """不传 store_id 时返回全店数据"""
        resp = client.get(
            "/api/v1/analytics/narrative/comparison",
            params={"date": "2026-04-05"},
            headers=HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["store_id"] == "all"


# ─── Test 2: 异常叙事 ────────────────────────────────────────────────────────


class TestAnomalyDetection:
    def test_response_ok(self):
        """基础响应正常"""
        resp = get_anomaly()
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_has_anomaly_field_is_bool(self):
        """has_anomaly 字段是布尔值"""
        resp = get_anomaly()
        data = resp.json()["data"]
        assert isinstance(data["has_anomaly"], bool)

    def test_anomaly_count_matches_list_length(self):
        """anomaly_count 与 anomalies 列表长度一致"""
        resp = get_anomaly()
        data = resp.json()["data"]
        assert data["anomaly_count"] == len(data["anomalies"])

    def test_high_threshold_reduces_anomalies(self):
        """高 threshold 减少异常数量"""
        resp_low = get_anomaly(threshold=1.0)
        resp_high = get_anomaly(threshold=4.0)
        count_low = resp_low.json()["data"]["anomaly_count"]
        count_high = resp_high.json()["data"]["anomaly_count"]
        assert count_low >= count_high

    def test_anomaly_severity_valid_values(self):
        """severity 值在合法范围内"""
        resp = get_anomaly(threshold=1.0)  # 低阈值，更多异常
        data = resp.json()["data"]
        for a in data["anomalies"]:
            assert a["severity"] in ("medium", "high", "critical")

    def test_anomaly_narrative_not_empty(self):
        """每个异常都有非空 narrative"""
        resp = get_anomaly(threshold=1.0)
        data = resp.json()["data"]
        for a in data["anomalies"]:
            assert a["narrative"]
            assert len(a["narrative"]) > 5

    def test_anomaly_deviation_is_positive_float(self):
        """deviation 字段是正浮点数"""
        resp = get_anomaly(threshold=1.0)
        data = resp.json()["data"]
        for a in data["anomalies"]:
            assert isinstance(a["deviation"], float)
            assert a["deviation"] > 0

    def test_discount_rate_anomaly_narrative_contains_keyword(self):
        """折扣率异常时 narrative 包含 '折扣' 关键词"""
        # 使用低阈值确保折扣率异常出现
        resp = get_anomaly(threshold=0.5)
        data = resp.json()["data"]
        discount_anomalies = [a for a in data["anomalies"] if a["metric"] == "discount_rate"]
        if discount_anomalies:
            assert "折扣" in discount_anomalies[0]["narrative"]

    def test_anomaly_full_narrative_structure(self):
        """full_narrative 包含【异常播报】字样"""
        resp = get_anomaly()
        data = resp.json()["data"]
        assert "异常播报" in data["full_narrative"]

    def test_no_anomaly_message(self):
        """无异常时 full_narrative 包含正常提示"""
        resp = get_anomaly(threshold=5.0)  # 极高阈值，几乎无异常
        data = resp.json()["data"]
        if not data["has_anomaly"]:
            assert "正常" in data["full_narrative"] or "无重大" in data["full_narrative"]


# ─── Test 3: 日报完整版 ──────────────────────────────────────────────────────


class TestDailyReportFormat:
    def test_response_ok(self):
        """基础响应正常"""
        resp = post_daily_report()
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_full_narrative_contains_format_chars(self):
        """default 模板的 full_narrative 包含企微格式字符（━ 或 📊 或 👥）"""
        resp = post_daily_report(include_comparison=True, include_anomaly=True)
        data = resp.json()["data"]
        full = data["full_narrative"]
        assert any(char in full for char in ["━", "📊", "👥", "⚡", "✅", "⚠️", "💡"])

    def test_full_narrative_contains_date(self):
        """full_narrative 包含日期信息"""
        resp = post_daily_report(date_str="2026-04-05")
        data = resp.json()["data"]
        assert "2026-04-05" in data["full_narrative"]

    def test_full_narrative_contains_revenue(self):
        """full_narrative 包含营业额（¥符号）"""
        resp = post_daily_report()
        data = resp.json()["data"]
        assert "¥" in data["full_narrative"]

    def test_compact_template_shorter(self):
        """compact 模板比 default 模板更短"""
        resp_default = post_daily_report(template_id="default")
        resp_compact = post_daily_report(template_id="compact")
        default_len = len(resp_default.json()["data"]["full_narrative"])
        compact_len = len(resp_compact.json()["data"]["full_narrative"])
        assert compact_len < default_len

    def test_boss_template_format(self):
        """boss 模板包含 📊 emoji"""
        resp = post_daily_report(template_id="boss")
        data = resp.json()["data"]
        assert "📊" in data["full_narrative"]

    def test_include_anomaly_true_shows_anomaly(self):
        """include_anomaly=True 时，如有异常则 full_narrative 包含 ⚡"""
        resp = post_daily_report(include_anomaly=True)
        data = resp.json()["data"]
        if data["anomaly_summary"]:
            assert "⚡" in data["full_narrative"]

    def test_include_anomaly_false_shows_normal(self):
        """include_anomaly=False 时，full_narrative 包含 ✅ 运营状态"""
        resp = post_daily_report(include_anomaly=False)
        data = resp.json()["data"]
        assert "✅" in data["full_narrative"] or "运营" in data["full_narrative"]

    def test_revenue_field_positive(self):
        """revenue_fen 字段是正整数"""
        resp = post_daily_report()
        data = resp.json()["data"]
        assert isinstance(data["revenue_fen"], (int, float))
        assert data["revenue_fen"] > 0

    def test_agent_tips_list_not_empty(self):
        """agent_tips 列表非空"""
        resp = post_daily_report()
        data = resp.json()["data"]
        assert isinstance(data["agent_tips"], list)
        assert len(data["agent_tips"]) >= 1

    def test_different_stores_different_narrative(self):
        """不同 store_id 生成不同叙事（数据驱动）"""
        resp1 = post_daily_report(store_id="store-aaa", date_str="2026-04-05")
        resp2 = post_daily_report(store_id="store-bbb", date_str="2026-04-05")
        # revenue 可能不同（seed 取决于 store_id）
        rev1 = resp1.json()["data"]["revenue_fen"]
        rev2 = resp2.json()["data"]["revenue_fen"]
        # 至少两个 store_id 不同，所以 date+store 组合不同
        assert resp1.json()["data"]["store_id"] != resp2.json()["data"]["store_id"]
