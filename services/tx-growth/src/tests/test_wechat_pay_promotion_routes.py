"""WP-1/WP-2 微信支付营销 API 路由测试

测试：创建摇优惠活动 / 配置商家名片 / 创建投放计划 / 投放计划管理
"""

import os
import sys

# src 目录+项目根目录（shared 模块）
_src = os.path.join(os.path.dirname(__file__), "..")
_root = os.path.join(_src, "..", "..", "..", "..")
for p in [_src, _root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.wechat_pay_promotion_routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

_TENANT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_STORE_ID = "store-001"


class TestShakeActivity:
    """创建摇一摇优惠活动"""

    def test_create_shake_returns_200(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/shake",
            json={
                "store_id": _STORE_ID,
                "activity_name": "周末摇一摇",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-31T23:59:59Z",
                "award_amount_fen": 500,
                "total_count": 1000,
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "id" in data["data"]

    def test_create_shake_missing_store_id_returns_422(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/shake",
            json={"activity_name": "test", "begin_time": "2026-05-01T00:00:00Z",
                  "end_time": "2026-05-31T23:59:59Z", "award_amount_fen": 500,
                  "total_count": 100},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 422

    def test_create_shake_missing_tenant_returns_422(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/shake",
            json={
                "store_id": _STORE_ID,
                "activity_name": "test",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-31T23:59:59Z",
                "award_amount_fen": 500,
                "total_count": 100,
            },
        )
        assert resp.status_code == 422

    def test_create_shake_zero_amount_returns_422(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/shake",
            json={
                "store_id": _STORE_ID,
                "activity_name": "test",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-31T23:59:59Z",
                "award_amount_fen": 0,
                "total_count": 100,
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 422


class TestMerchantCard:
    """配置商家名片"""

    def test_create_merchant_card_returns_200(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/merchant-card",
            json={
                "store_id": _STORE_ID,
                "card_name": "徐记海鲜·五一广场店",
                "card_type": "phone",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "id" in data["data"]

    def test_create_merchant_card_missing_card_type_returns_422(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/merchant-card",
            json={"store_id": _STORE_ID, "card_name": "test"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 422


class TestPromotionPlan:
    """创建投放计划"""

    def test_create_plan_returns_200(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/plan",
            json={
                "store_id": _STORE_ID,
                "plan_name": "五一投放计划",
                "plan_type": "coupon",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-07T23:59:59Z",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "id" in data["data"]

    def test_create_plan_missing_plan_type_returns_422(self):
        resp = client.post(
            "/api/v1/growth/wechat-promotion/plan",
            json={
                "store_id": _STORE_ID,
                "plan_name": "test",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-07T23:59:59Z",
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 422


class TestListActivities:
    """活动/名片/计划列表"""

    def test_list_activities_returns_200(self):
        resp = client.get(
            "/api/v1/growth/wechat-promotion/activities",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "items" in data["data"]

    def test_list_activities_by_type_returns_200(self):
        resp = client.get(
            "/api/v1/growth/wechat-promotion/activities?activity_type=shake_coupon",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_list_activities_by_status_returns_200(self):
        resp = client.get(
            "/api/v1/growth/wechat-promotion/activities?status=active",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200

    def test_get_activity_detail_not_found_returns_404(self):
        resp = client.get(
            "/api/v1/growth/wechat-promotion/activities/nonexistent-id",
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 404

    def test_update_activity_status_returns_200(self):
        # 先创建一个活动
        create_resp = client.post(
            "/api/v1/growth/wechat-promotion/shake",
            json={
                "store_id": _STORE_ID,
                "activity_name": "status-test",
                "begin_time": "2026-05-01T00:00:00Z",
                "end_time": "2026-05-31T23:59:59Z",
                "award_amount_fen": 500,
                "total_count": 100,
            },
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        activity_id = create_resp.json()["data"]["id"]

        resp = client.patch(
            f"/api/v1/growth/wechat-promotion/activities/{activity_id}/status",
            json={"status": "paused"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"] == "paused"

    def test_update_activity_status_invalid_value_returns_400(self):
        resp = client.patch(
            "/api/v1/growth/wechat-promotion/activities/some-id/status",
            json={"status": "invalid_status"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    def test_update_activity_status_not_found_returns_404(self):
        resp = client.patch(
            "/api/v1/growth/wechat-promotion/activities/bad-id/status",
            json={"status": "paused"},
            headers={"X-Tenant-ID": _TENANT_ID},
        )
        assert resp.status_code == 404
