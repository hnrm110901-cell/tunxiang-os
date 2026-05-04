"""
P3-05 企微SCRM私域Agent测试
测试：生日会员列表 / 沉睡会员响应率预测 / 回访效果统计
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.wecom_scrm_agent_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ─── Test 1: 生日会员列表 ─────────────────────────────────────────────────────


class TestBirthdayUpcomingList:
    """test_birthday_upcoming_list — 获取7天内生日会员，验证 days_until<=7，含 recommend_template 字段"""

    def test_birthday_upcoming_returns_200(self):
        resp = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_all_members_within_days_ahead(self):
        days_ahead = 7
        resp = client.get(f"/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead={days_ahead}")
        items = resp.json()["data"]["items"]
        assert len(items) > 0
        for member in items:
            assert member["days_until"] <= days_ahead, (
                f"会员 {member['name']} 生日还有 {member['days_until']} 天，超出 days_ahead={days_ahead}"
            )

    def test_each_member_has_recommend_template(self):
        resp = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=7")
        items = resp.json()["data"]["items"]
        valid_templates = {"default", "vip", "super_vip"}
        for member in items:
            assert "recommend_template" in member, f"会员 {member['name']} 缺少 recommend_template 字段"
            assert member["recommend_template"] in valid_templates, (
                f"会员 {member['name']} 的模板 {member['recommend_template']} 不在允许集合"
            )

    def test_members_sorted_by_days_until(self):
        resp = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=7")
        items = resp.json()["data"]["items"]
        days = [m["days_until"] for m in items]
        assert days == sorted(days), "会员应按 days_until 升序排列"

    def test_each_member_has_required_fields(self):
        resp = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=7")
        items = resp.json()["data"]["items"]
        required = {
            "member_id",
            "name",
            "phone_masked",
            "birthday",
            "days_until",
            "level",
            "last_spend_fen",
            "recommend_template",
            "send_status",
            "wecom_connected",
        }
        for member in items:
            missing = required - set(member.keys())
            assert len(missing) == 0, f"会员 {member.get('name')} 缺少字段: {missing}"

    def test_days_ahead_filter_reduces_results(self):
        resp_3 = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=3")
        resp_7 = client.get("/api/v1/growth/scrm-agent/birthday/upcoming?days_ahead=7")
        count_3 = len(resp_3.json()["data"]["items"])
        count_7 = len(resp_7.json()["data"]["items"])
        assert count_3 <= count_7, "days_ahead=3 的结果不应多于 days_ahead=7"

    def test_birthday_send_valid_request(self):
        resp = client.post(
            "/api/v1/growth/scrm-agent/birthday/send",
            json={"member_ids": ["mem-b01", "mem-b05"], "message_template": "vip"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total" in data
        assert "success" in data
        assert "failed" in data
        assert data["total"] == 2

    def test_birthday_send_invalid_template_returns_400(self):
        resp = client.post(
            "/api/v1/growth/scrm-agent/birthday/send",
            json={"member_ids": ["mem-b01"], "message_template": "invalid_tpl"},
        )
        assert resp.status_code == 400

    def test_birthday_send_unconnected_member_fails(self):
        """未绑定企微的会员发送应失败"""
        resp = client.post(
            "/api/v1/growth/scrm-agent/birthday/send",
            json={"member_ids": ["mem-b04"], "message_template": "default"},
        )
        data = resp.json()["data"]
        failed_members = [r for r in data["details"] if r["status"] == "failed"]
        assert any(r["member_id"] == "mem-b04" for r in failed_members)


# ─── Test 2: 沉睡会员预测响应率 ───────────────────────────────────────────────


class TestDormantMemberList:
    """test_dormant_member_list — 沉睡>180天的 predicted_response_rate < 0.15"""

    def test_dormant_list_returns_200(self):
        resp = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_over_180_days_response_rate_below_15_percent(self):
        resp = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60")
        items = resp.json()["data"]["items"]
        for member in items:
            if member["dormant_days"] > 180:
                assert member["predicted_response_rate"] < 0.15, (
                    f"会员 {member['name']} 沉睡 {member['dormant_days']} 天，响应率 {member['predicted_response_rate']} 应 < 0.15"
                )

    def test_60_90_days_response_rate_range(self):
        """60-90天沉睡且历史消费>3000元的响应率应在合理范围内"""
        resp = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60&min_historical_spend_fen=300000")
        items = resp.json()["data"]["items"]
        mid_dormant = [m for m in items if 60 <= m["dormant_days"] <= 90]
        for member in mid_dormant:
            assert member["predicted_response_rate"] >= 0.15, (
                f"会员 {member['name']} 60-90天沉睡，响应率过低: {member['predicted_response_rate']}"
            )

    def test_dormant_filter_by_min_spend(self):
        resp_low = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60&min_historical_spend_fen=1000000")
        resp_all = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60&min_historical_spend_fen=0")
        count_low = len(resp_low.json()["data"]["items"])
        count_all = len(resp_all.json()["data"]["items"])
        assert count_low <= count_all, "高消费门槛过滤后结果不应多于无门槛"

    def test_each_member_has_required_fields(self):
        resp = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60")
        items = resp.json()["data"]["items"]
        required = {
            "member_id",
            "name",
            "dormant_days",
            "total_spend_fen",
            "predicted_response_rate",
            "suggest_offer",
            "favorite_dish",
        }
        for member in items:
            missing = required - set(member.keys())
            assert len(missing) == 0, f"会员 {member.get('name')} 缺少字段: {missing}"

    def test_wake_endpoint_invalid_offer_type_returns_400(self):
        resp = client.post(
            "/api/v1/growth/scrm-agent/dormant/wake",
            json={"member_ids": ["mem-d01"], "offer_type": "invalid", "offer_value_fen": 2000},
        )
        assert resp.status_code == 400

    def test_wake_endpoint_skips_over_180_days(self):
        """系统应自动跳过沉睡>180天的会员"""
        resp = client.post(
            "/api/v1/growth/scrm-agent/dormant/wake",
            json={"member_ids": ["mem-d04"], "offer_type": "coupon", "offer_value_fen": 2000},
        )
        data = resp.json()["data"]
        skipped = [r for r in data["details"] if r["status"] == "skipped"]
        assert any(r["member_id"] == "mem-d04" for r in skipped), "沉睡229天的会员应被系统自动跳过"

    def test_dormant_list_excludes_unsubscribed(self):
        """已退订营销的会员不应出现在沉睡列表"""
        resp = client.get("/api/v1/growth/scrm-agent/dormant/list?dormant_days=60")
        items = resp.json()["data"]["items"]
        for member in items:
            assert not member.get("unsubscribed"), f"已退订的会员 {member['name']} 不应出现在列表中"


# ─── Test 3: 回访效果统计 ─────────────────────────────────────────────────────


class TestPostOrderPerformanceStats:
    """test_post_order_performance_stats — 回访效果统计，3个动作均有统计数据"""

    def test_performance_returns_200(self):
        resp = client.get("/api/v1/growth/scrm-agent/performance")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_all_three_actions_present(self):
        resp = client.get("/api/v1/growth/scrm-agent/performance")
        data = resp.json()["data"]
        assert "birthday" in data, "缺少生日祝福统计"
        assert "dormant_wake" in data, "缺少沉睡唤醒统计"
        assert "post_order" in data, "缺少订单回访统计"

    def test_birthday_stats_fields(self):
        data = client.get("/api/v1/growth/scrm-agent/performance").json()["data"]["birthday"]
        required = {"sent", "converted", "conversion_rate", "revenue_fen"}
        missing = required - set(data.keys())
        assert len(missing) == 0, f"生日祝福统计缺少字段: {missing}"
        assert 0 <= data["conversion_rate"] <= 1.0

    def test_dormant_wake_stats_fields(self):
        data = client.get("/api/v1/growth/scrm-agent/performance").json()["data"]["dormant_wake"]
        required = {"touched", "awakened", "awaken_rate", "roi", "revenue_fen"}
        missing = required - set(data.keys())
        assert len(missing) == 0, f"沉睡唤醒统计缺少字段: {missing}"
        assert 0 <= data["awaken_rate"] <= 1.0
        assert data["roi"] > 0

    def test_post_order_stats_fields(self):
        data = client.get("/api/v1/growth/scrm-agent/performance").json()["data"]["post_order"]
        required = {"sent", "replied", "reply_rate", "repurchase_lift", "revenue_fen"}
        missing = required - set(data.keys())
        assert len(missing) == 0, f"回访统计缺少字段: {missing}"
        assert 0 <= data["reply_rate"] <= 1.0

    def test_overall_roi_positive(self):
        data = client.get("/api/v1/growth/scrm-agent/performance").json()["data"]
        assert "overall_roi" in data
        assert data["overall_roi"] > 0, "整体ROI应为正值"

    def test_post_order_stats_endpoint(self):
        resp = client.get("/api/v1/growth/scrm-agent/post-order/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "tasks_total" in data
        assert "tasks_sent" in data
        assert "reply_rate" in data
        assert "by_template" in data
        # 3个模板均应有统计
        templates = set(data["by_template"].keys())
        assert {"satisfaction", "recommend", "rebuy"} == templates

    def test_post_order_schedule_endpoint(self):
        resp = client.post(
            "/api/v1/growth/scrm-agent/post-order/schedule",
            json={
                "order_id": "ord-test-001",
                "member_id": "mem-c01",
                "delay_hours": 2,
                "template": "satisfaction",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "task_id" in data
        assert data["status"] == "scheduled"
        assert data["delay_hours"] == 2

    def test_post_order_schedule_invalid_template_returns_400(self):
        resp = client.post(
            "/api/v1/growth/scrm-agent/post-order/schedule",
            json={
                "order_id": "ord-test-002",
                "member_id": "mem-c01",
                "delay_hours": 1,
                "template": "invalid_template",
            },
        )
        assert resp.status_code == 400
