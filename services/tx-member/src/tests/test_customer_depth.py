"""客户深度业务逻辑 + API 端点测试

覆盖: golden_id_merge, channel_attribution, tag_customer_scene,
      calculate_customer_value, get_customer_360, 以及5个API端点
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── API 冒烟测试 ──────────────────────────────────────────────
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


class TestCustomerDepthAPI:
    """客户深度 API 端点冒烟测试"""

    def test_golden_id_merge(self):
        r = client.post(
            "/api/v1/member/depth/golden-id/merge?tenant_id=t1",
            json={"phone": "13800138000", "wechat_openid": "wx_123", "pos_id": "pos_001"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "golden_id" in data["data"]

    def test_channel_attribution(self):
        r = client.get("/api/v1/member/depth/customers/c1/channel-attribution?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["customer_id"] == "c1"
        assert "first_channel" in data["data"]

    def test_scene_tags(self):
        r = client.post("/api/v1/member/depth/customers/c1/scene-tags?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "scenes" in data["data"]

    def test_customer_value(self):
        r = client.get("/api/v1/member/depth/customers/c1/value?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "level" in data["data"]
        assert "r_score" in data["data"]

    def test_customer_360(self):
        r = client.get("/api/v1/member/depth/customers/c1/360?tenant_id=t1")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "profile" in data["data"]
        assert "value" in data["data"]
        assert "timeline" in data["data"]

    def test_golden_id_merge_phone_only(self):
        r = client.post(
            "/api/v1/member/depth/golden-id/merge?tenant_id=t1",
            json={"phone": "13900139000"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── 业务逻辑单元测试 ──────────────────────────────────────────

from services.customer_depth import (
    _rfm_level,
)


class TestRFMLevel:
    """RFM 分层逻辑测试"""

    def test_high_value(self):
        assert _rfm_level(5, 4, 4) == "high_value"  # 13 >= 12
        assert _rfm_level(4, 4, 4) == "high_value"  # 12 >= 12

    def test_growth(self):
        assert _rfm_level(3, 3, 3) == "growth"  # 9, 8-11
        assert _rfm_level(4, 4, 3) == "growth"  # 11

    def test_dormant(self):
        assert _rfm_level(2, 2, 2) == "dormant"  # 6, 5-7
        assert _rfm_level(3, 2, 2) == "dormant"  # 7

    def test_churn(self):
        assert _rfm_level(1, 1, 1) == "churn"  # 3 < 5
        assert _rfm_level(1, 1, 2) == "churn"  # 4 < 5

    def test_boundary_12(self):
        """边界: 总分恰好等于12"""
        assert _rfm_level(4, 4, 4) == "high_value"

    def test_boundary_8(self):
        """边界: 总分恰好等于8"""
        assert _rfm_level(3, 3, 2) == "growth"

    def test_boundary_5(self):
        """边界: 总分恰好等于5"""
        assert _rfm_level(2, 2, 1) == "dormant"

    def test_boundary_4(self):
        """边界: 总分恰好等于4"""
        assert _rfm_level(2, 1, 1) == "churn"
