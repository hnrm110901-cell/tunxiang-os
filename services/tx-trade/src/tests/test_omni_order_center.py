"""
Y-A12 全渠道订单中心 — 单元测试
测试全渠道列表、渠道过滤、快速搜索、统计、会员历史、详情等端点。
"""
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from ..api.omni_order_center_routes import router

# ─── Test App ────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app)

HEADERS = {"X-Tenant-ID": "test-tenant"}

ALL_CHANNELS = {"dine_in", "takeaway", "miniapp", "group_meal", "banquet"}


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def list_orders(**kwargs):
    return client.get("/api/v1/trade/omni-orders", params=kwargs, headers=HEADERS)


def search_orders(q: str, limit: int = 20):
    return client.get(
        "/api/v1/trade/omni-orders/search",
        params={"q": q, "limit": limit},
        headers=HEADERS,
    )


def get_stats():
    return client.get("/api/v1/trade/omni-orders/stats", headers=HEADERS)


def get_customer_history(golden_id: str):
    return client.get(
        f"/api/v1/trade/omni-orders/customer/{golden_id}",
        headers=HEADERS,
    )


def get_detail(order_id: str):
    return client.get(
        f"/api/v1/trade/omni-orders/{order_id}",
        headers=HEADERS,
    )


# ─── Test 1: 全渠道列表 ──────────────────────────────────────────────────────

class TestOmniListAllChannels:
    def test_response_ok(self):
        """基础 HTTP 200 + ok=True"""
        resp = list_orders()
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_items_not_empty(self):
        """items 列表非空"""
        resp = list_orders()
        data = resp.json()["data"]
        assert len(data["items"]) > 0

    def test_contains_all_channels(self):
        """返回数据中包含所有 5 个渠道"""
        resp = list_orders(size=100)
        data = resp.json()["data"]
        actual_channels = {item["channel"] for item in data["items"]}
        # Mock 数据应包含所有5个渠道
        assert actual_channels == ALL_CHANNELS

    def test_channel_summary_has_required_fields(self):
        """channel_summary 包含 dine_in 和 takeaway 字段"""
        resp = list_orders()
        data = resp.json()["data"]
        assert "channel_summary" in data
        assert "dine_in" in data["channel_summary"]
        assert "takeaway" in data["channel_summary"]

    def test_channel_summary_all_channels_present(self):
        """channel_summary 包含全部5个渠道"""
        resp = list_orders()
        summary = resp.json()["data"]["channel_summary"]
        for ch in ALL_CHANNELS:
            assert ch in summary

    def test_pagination_fields(self):
        """返回包含分页字段 total/page/size"""
        resp = list_orders(page=1, size=3)
        data = resp.json()["data"]
        assert "total" in data
        assert "page" in data
        assert "size" in data
        assert data["page"] == 1
        assert data["size"] == 3

    def test_pagination_limits_items(self):
        """size=2 时 items 最多2条"""
        resp = list_orders(size=2)
        data = resp.json()["data"]
        assert len(data["items"]) <= 2

    def test_order_fields_present(self):
        """每条订单包含核心字段"""
        resp = list_orders()
        data = resp.json()["data"]
        required_fields = {
            "order_id", "channel", "channel_label", "order_no",
            "total_fen", "paid_fen", "status", "status_label",
        }
        for item in data["items"]:
            for field in required_fields:
                assert field in item, f"缺少字段: {field}"

    def test_phone_masked(self):
        """手机号已脱敏（包含 **** 或为空）"""
        resp = list_orders()
        data = resp.json()["data"]
        for item in data["items"]:
            phone = item.get("customer_phone")
            if phone:
                assert "****" in phone

    def test_status_filter_open(self):
        """status=open 只返回进行中订单"""
        resp = list_orders(status="open")
        data = resp.json()["data"]
        for item in data["items"]:
            assert item["status"] == "open"

    def test_status_filter_closed(self):
        """status=closed 只返回已完成订单"""
        resp = list_orders(status="closed")
        data = resp.json()["data"]
        for item in data["items"]:
            assert item["status"] == "closed"


# ─── Test 2: 渠道过滤 ────────────────────────────────────────────────────────

class TestOmniChannelFilter:
    def test_filter_takeaway_only(self):
        """channel=takeaway 只返回外卖订单"""
        resp = list_orders(channel="takeaway")
        data = resp.json()["data"]
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["channel"] == "takeaway"

    def test_filter_dine_in_only(self):
        """channel=dine_in 只返回堂食订单"""
        resp = list_orders(channel="dine_in")
        data = resp.json()["data"]
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["channel"] == "dine_in"

    def test_filter_miniapp_only(self):
        """channel=miniapp 只返回小程序订单"""
        resp = list_orders(channel="miniapp")
        data = resp.json()["data"]
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["channel"] == "miniapp"

    def test_filter_group_meal_only(self):
        """channel=group_meal 只返回团餐订单"""
        resp = list_orders(channel="group_meal")
        data = resp.json()["data"]
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["channel"] == "group_meal"

    def test_filter_banquet_only(self):
        """channel=banquet 只返回宴席订单"""
        resp = list_orders(channel="banquet")
        data = resp.json()["data"]
        assert len(data["items"]) > 0
        for item in data["items"]:
            assert item["channel"] == "banquet"

    def test_filter_all_equals_no_filter(self):
        """channel=all 返回与不过滤相同数量"""
        resp_all = list_orders(channel="all", size=100)
        resp_none = list_orders(size=100)
        assert resp_all.json()["data"]["total"] == resp_none.json()["data"]["total"]

    def test_channel_label_matches_channel(self):
        """channel_label 与 channel 对应正确"""
        channel_label_map = {
            "dine_in":    "堂食",
            "takeaway":   "美团外卖",
            "miniapp":    "小程序自助",
            "group_meal": "团餐企业",
            "banquet":    "宴席预订",
        }
        resp = list_orders(size=100)
        for item in resp.json()["data"]["items"]:
            expected_label = channel_label_map.get(item["channel"])
            if expected_label:
                assert item["channel_label"] == expected_label


# ─── Test 3: 快速搜索 ────────────────────────────────────────────────────────

class TestOmniSearch:
    def test_search_response_ok(self):
        """搜索基础响应正常"""
        resp = search_orders("美团")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_search_meituan_returns_takeaway(self):
        """搜索 '美团' 返回外卖渠道订单"""
        resp = search_orders("美团")
        data = resp.json()["data"]
        assert data["total"] > 0
        for item in data["items"]:
            assert item["channel"] == "takeaway"

    def test_search_banquet_returns_banquet(self):
        """搜索 '宴席' 返回宴席渠道订单"""
        resp = search_orders("宴席")
        data = resp.json()["data"]
        assert data["total"] > 0
        for item in data["items"]:
            assert item["channel"] == "banquet"

    def test_search_by_order_no(self):
        """按订单号前缀搜索"""
        resp = search_orders("2026040600001")
        data = resp.json()["data"]
        assert data["total"] >= 1
        assert any(item["order_no"] == "2026040600001" for item in data["items"])

    def test_search_by_platform_order_id(self):
        """按平台单号搜索（外卖）"""
        resp = search_orders("MT-12345678")
        data = resp.json()["data"]
        assert data["total"] >= 1

    def test_search_returns_query_field(self):
        """返回数据中包含 query 字段"""
        resp = search_orders("美团")
        data = resp.json()["data"]
        assert data["query"] == "美团"

    def test_search_limit_respected(self):
        """limit 参数有效"""
        resp = search_orders("a", limit=2)
        data = resp.json()["data"]
        assert len(data["items"]) <= 2

    def test_search_no_result(self):
        """搜索不存在的关键词返回空列表"""
        resp = search_orders("这个关键词绝对不存在XYZ999")
        data = resp.json()["data"]
        assert data["total"] == 0
        assert data["items"] == []

    def test_search_small_program(self):
        """搜索 '小程序' 返回 miniapp 渠道"""
        resp = search_orders("小程序")
        data = resp.json()["data"]
        assert data["total"] > 0
        for item in data["items"]:
            assert item["channel"] == "miniapp"

    def test_search_by_table_no(self):
        """按桌台号搜索"""
        resp = search_orders("A8")
        data = resp.json()["data"]
        assert data["total"] >= 1


# ─── Test 4: 统计端点 ────────────────────────────────────────────────────────

class TestOmniStats:
    def test_stats_response_ok(self):
        resp = get_stats()
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_stats_has_channel_stats(self):
        data = get_stats().json()["data"]
        assert "channel_stats" in data
        assert len(data["channel_stats"]) == 5

    def test_stats_total_revenue_positive(self):
        data = get_stats().json()["data"]
        assert data["total_revenue_fen"] > 0

    def test_stats_growth_rate_is_float(self):
        data = get_stats().json()["data"]
        assert isinstance(data["overall_growth_rate"], float)

    def test_stats_each_channel_has_required_fields(self):
        data = get_stats().json()["data"]
        for cs in data["channel_stats"]:
            assert "channel" in cs
            assert "order_count" in cs
            assert "revenue_fen" in cs
            assert "avg_ticket_fen" in cs
            assert "growth_rate" in cs


# ─── Test 5: 订单详情 ────────────────────────────────────────────────────────

class TestOmniOrderDetail:
    def test_detail_existing_order(self):
        resp = get_detail("ord-001")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["order_id"] == "ord-001"

    def test_detail_not_found(self):
        resp = get_detail("ord-nonexistent-99999")
        assert resp.status_code == 404

    def test_detail_has_items(self):
        resp = get_detail("ord-001")
        data = resp.json()["data"]
        assert "items" in data
        assert len(data["items"]) > 0

    def test_detail_has_payment_records(self):
        resp = get_detail("ord-001")
        data = resp.json()["data"]
        assert "payment_records" in data

    def test_detail_has_discount_detail(self):
        resp = get_detail("ord-001")
        data = resp.json()["data"]
        assert "discount_detail" in data
        assert "discount_rate" in data["discount_detail"]

    def test_detail_channel_info(self):
        resp = get_detail("ord-002")  # takeaway
        data = resp.json()["data"]
        assert "channel_info" in data
        assert data["channel_info"]["channel"] == "takeaway"


# ─── Test 6: 会员跨渠道历史 ─────────────────────────────────────────────────

class TestCustomerOrderHistory:
    def test_existing_customer(self):
        resp = get_customer_history("gid-1001")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["golden_id"] == "gid-1001"
        assert data["total_order_count"] >= 1

    def test_nonexistent_customer_empty(self):
        resp = get_customer_history("gid-nonexistent-99999")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_order_count"] == 0
        assert data["items"] == []

    def test_history_has_channel_breakdown(self):
        resp = get_customer_history("gid-1001")
        data = resp.json()["data"]
        assert "channel_breakdown" in data
