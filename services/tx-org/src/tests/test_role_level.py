"""角色级别体系测试"""

import os
import sys

# 项目根目录（让 shared.ontology.src.base 可被解析）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
# 服务 src 目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app
from models.role_level import check_role_permission

client = TestClient(app)


class TestCheckRolePermission:
    def test_high_level_can_discount(self):
        """高级别角色可以打折"""
        assert check_role_permission(5, "discount") is True

    def test_low_level_cannot_discount(self):
        """低级别角色不能打折"""
        assert check_role_permission(1, "discount") is False

    def test_level_boundary_exact(self):
        """刚好达到所需级别应允许"""
        assert check_role_permission(3, "discount") is True
        assert check_role_permission(2, "tip_off") is True

    def test_level_boundary_below(self):
        """低于所需级别一级应拒绝"""
        assert check_role_permission(2, "discount") is False
        assert check_role_permission(1, "tip_off") is False

    def test_invalid_level_rejected(self):
        """无效级别 (0, 11, -1) 应拒绝"""
        assert check_role_permission(0, "discount") is False
        assert check_role_permission(11, "discount") is False
        assert check_role_permission(-1, "discount") is False

    def test_unknown_action_rejected(self):
        """未知操作类型应拒绝"""
        assert check_role_permission(10, "unknown_action") is False

    def test_system_settings_requires_level_10(self):
        """系统设置需要最高级别"""
        assert check_role_permission(9, "system_settings") is False
        assert check_role_permission(10, "system_settings") is True


class TestRoleAPI:
    def test_list_roles(self):
        """获取角色列表"""
        r = client.get("/api/v1/org/roles")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["data"]["items"]) >= 1

    def test_create_role(self):
        """创建角色"""
        r = client.post(
            "/api/v1/org/roles",
            json={
                "role_name": "收银员",
                "role_code": "cashier",
                "role_level": 3,
                "max_discount_pct": 95,
                "max_tip_off_fen": 500,
                "max_gift_fen": 0,
                "max_order_gift_fen": 0,
                "data_query_limit": "7d",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["data"]["role_name"] == "收银员"
        assert data["data"]["role_level"] == 3

    def test_create_role_invalid_level(self):
        """创建角色时级别超范围应报错"""
        r = client.post(
            "/api/v1/org/roles",
            json={
                "role_name": "测试",
                "role_code": "test",
                "role_level": 15,
            },
        )
        assert r.status_code == 422

    def test_create_role_defaults(self):
        """创建角色时默认值正确"""
        r = client.post(
            "/api/v1/org/roles",
            json={
                "role_name": "基础角色",
                "role_code": "basic",
                "role_level": 1,
            },
        )
        data = r.json()["data"]
        assert data["max_discount_pct"] == 100
        assert data["max_tip_off_fen"] == 0
        assert data["data_query_limit"] == "7d"

    def test_list_roles_contains_mock_data(self):
        """角色列表应包含预置的模拟数据"""
        r = client.get("/api/v1/org/roles")
        items = r.json()["data"]["items"]
        codes = [item["role_code"] for item in items]
        assert "waiter" in codes
        assert "store_manager" in codes
