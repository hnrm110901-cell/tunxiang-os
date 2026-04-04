"""ck_recipe_routes.py — 配方管理 + 生产计划 + 配送调拨 路由测试

测试范围（12个测试）：
  - GET  /api/v1/supply/recipes                       — 配方列表（空列表 / 按 dish_id 过滤）
  - POST /api/v1/supply/recipes                       — 创建配方（正常 HTTP201 + emit_event 旁路 / 版本自增）
  - GET  /api/v1/supply/recipes/{recipe_id}           — 配方详情（找到 / 404）
  - PUT  /api/v1/supply/recipes/{recipe_id}           — 更新配方原料（正常 + emit_event 旁路）
  - POST /api/v1/supply/recipes/{recipe_id}/calculate — 按产量计算（正常公式 / 配方不存在404）
  - POST /api/v1/supply/ck/plans                      — 创建生产计划（正常 HTTP201）
  - PUT  /api/v1/supply/ck/plans/{plan_id}/status     — 非法状态流转 → 400 / 合法流转 → 200
  - POST /api/v1/supply/ck/dispatch                   — 创建调拨单（正常 + 单号格式验证）

技术说明：
  - ck_recipe_routes 使用模块级 _RECIPES/_PLANS/_DISPATCH_ORDERS in-memory dict（待 DB 替换阶段）
  - 每个测试用独立 TENANT_ID 隔离 in-memory 状态，避免测试间污染
  - emit_event 通过 asyncio.create_task 旁路，patch create_task 验证调用
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ck_recipe_routes import (
    _DISPATCH_ITEMS,
    _DISPATCH_ORDERS,
    _PLAN_ITEMS,
    _PLANS,
    _RECIPE_INGREDIENTS,
    _RECIPES,
    router as ck_recipe_router,
)

# ─── App 组装 ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(ck_recipe_router)
client = TestClient(app)

# ─── Patch 路径 ───────────────────────────────────────────────────────────────

_TASK_PATCH = "api.ck_recipe_routes.asyncio.create_task"


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _fresh_tid() -> str:
    """每次测试生成唯一 tenant_id，隔离 in-memory 状态。"""
    return str(uuid.uuid4())


def _recipe_body(dish_id: str) -> dict[str, Any]:
    return {
        "dish_id": dish_id,
        "yield_qty": 10.0,
        "yield_unit": "份",
        "notes": "单元测试配方",
        "ingredients": [
            {"ingredient_name": "猪肉", "qty": 500.0, "unit": "克", "loss_rate": 0.05},
            {"ingredient_name": "生姜", "qty": 20.0, "unit": "克", "loss_rate": 0.0},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/supply/recipes — 配方列表
# ═══════════════════════════════════════════════════════════════════════════════


class TestListRecipes:
    """GET /api/v1/supply/recipes"""

    def test_list_recipes_empty(self):
        """初始状态：新 tenant 无配方，返回空列表。"""
        tid = _fresh_tid()
        resp = client.get("/api/v1/supply/recipes", headers={"X-Tenant-ID": tid})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []

    def test_list_recipes_filter_by_dish_id(self):
        """创建两个配方，按 dish_id 过滤只返回匹配一条。"""
        tid = _fresh_tid()
        dish_a = str(uuid.uuid4())
        dish_b = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH):
            client.post("/api/v1/supply/recipes", json=_recipe_body(dish_a), headers=headers)
            client.post("/api/v1/supply/recipes", json=_recipe_body(dish_b), headers=headers)

        resp = client.get(f"/api/v1/supply/recipes?dish_id={dish_a}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["dish_id"] == dish_a


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/recipes — 创建配方
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateRecipe:
    """POST /api/v1/supply/recipes"""

    def test_create_recipe_returns_201_with_ingredients(self):
        """正常创建配方：HTTP 201，返回 recipe_id + 原料列表 + emit_event 旁路。"""
        tid = _fresh_tid()
        dish_id = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH) as mock_task:
            resp = client.post(
                "/api/v1/supply/recipes",
                json=_recipe_body(dish_id),
                headers=headers,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]
        assert body["data"]["dish_id"] == dish_id
        assert len(body["data"]["ingredients"]) == 2
        assert body["data"]["version"] == 1
        # emit_event 通过 create_task 异步旁路调用
        mock_task.assert_called_once()

    def test_create_recipe_version_auto_increments(self):
        """同一 dish_id 创建第二个版本，版本号自增 1→2。"""
        tid = _fresh_tid()
        dish_id = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH):
            r1 = client.post("/api/v1/supply/recipes", json=_recipe_body(dish_id), headers=headers)
            r2 = client.post("/api/v1/supply/recipes", json=_recipe_body(dish_id), headers=headers)

        assert r1.json()["data"]["version"] == 1
        assert r2.json()["data"]["version"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/supply/recipes/{recipe_id} — 配方详情
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRecipe:
    """GET /api/v1/supply/recipes/{recipe_id}"""

    def test_get_recipe_found_with_ingredients(self):
        """已创建的配方查询成功，含原料明细。"""
        tid = _fresh_tid()
        dish_id = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH):
            create_resp = client.post(
                "/api/v1/supply/recipes",
                json=_recipe_body(dish_id),
                headers=headers,
            )
        recipe_id = create_resp.json()["data"]["id"]

        resp = client.get(f"/api/v1/supply/recipes/{recipe_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == recipe_id
        assert len(body["data"]["ingredients"]) == 2

    def test_get_recipe_not_found_404(self):
        """不存在的 recipe_id 返回 404。"""
        tid = _fresh_tid()
        resp = client.get(
            f"/api/v1/supply/recipes/{uuid.uuid4()}",
            headers={"X-Tenant-ID": tid},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# PUT /api/v1/supply/recipes/{recipe_id} — 更新配方
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdateRecipe:
    """PUT /api/v1/supply/recipes/{recipe_id}"""

    def test_update_recipe_replaces_ingredients_and_emits_event(self):
        """更新原料明细：新原料替换旧原料，emit_event 被 create_task 旁路调用。"""
        tid = _fresh_tid()
        dish_id = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH):
            create_resp = client.post(
                "/api/v1/supply/recipes",
                json=_recipe_body(dish_id),
                headers=headers,
            )
        recipe_id = create_resp.json()["data"]["id"]

        new_ingredients = [
            {"ingredient_name": "牛肉", "qty": 300.0, "unit": "克", "loss_rate": 0.1},
        ]
        with patch(_TASK_PATCH) as mock_task:
            resp = client.put(
                f"/api/v1/supply/recipes/{recipe_id}",
                json={"ingredients": new_ingredients},
                headers=headers,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["ingredients"]) == 1
        assert body["data"]["ingredients"][0]["ingredient_name"] == "牛肉"
        mock_task.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/recipes/{recipe_id}/calculate — 按产量计算原料用量
# ═══════════════════════════════════════════════════════════════════════════════


class TestCalculateRecipe:
    """POST /api/v1/supply/recipes/{recipe_id}/calculate"""

    def test_calculate_recipe_correct_formula(self):
        """公式验证：actual_qty = (target / yield) * qty * (1 + loss_rate)
        yield_qty=10, target_qty=20 → scale=2
        猪肉: 2 * 500 * 1.05 = 1050.0
        生姜: 2 * 20 * 1.0 = 40.0
        """
        tid = _fresh_tid()
        dish_id = str(uuid.uuid4())
        headers = {"X-Tenant-ID": tid}

        with patch(_TASK_PATCH):
            create_resp = client.post(
                "/api/v1/supply/recipes",
                json=_recipe_body(dish_id),
                headers=headers,
            )
        recipe_id = create_resp.json()["data"]["id"]

        resp = client.post(
            f"/api/v1/supply/recipes/{recipe_id}/calculate",
            json={"target_qty": 20.0},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["scale_factor"] == 2.0
        pork = next(i for i in data["ingredients"] if i["ingredient_name"] == "猪肉")
        ginger = next(i for i in data["ingredients"] if i["ingredient_name"] == "生姜")
        assert pork["calculated_qty"] == round(2.0 * 500.0 * 1.05, 4)
        assert ginger["calculated_qty"] == round(2.0 * 20.0 * 1.0, 4)

    def test_calculate_recipe_not_found_404(self):
        """不存在的 recipe_id 返回 404。"""
        tid = _fresh_tid()
        resp = client.post(
            f"/api/v1/supply/recipes/{uuid.uuid4()}/calculate",
            json={"target_qty": 5.0},
            headers={"X-Tenant-ID": tid},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/ck/plans — 创建生产计划
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateProductionPlan:
    """POST /api/v1/supply/ck/plans"""

    def test_create_production_plan_draft_status(self):
        """正常创建：HTTP 201，初始状态 draft，含计划明细。"""
        tid = _fresh_tid()
        headers = {"X-Tenant-ID": tid}
        store_id = str(uuid.uuid4())
        dish_id = str(uuid.uuid4())

        plan_body = {
            "plan_date": "2026-04-10",
            "store_id": store_id,
            "created_by": "emp-001",
            "notes": "单测计划",
            "items": [
                {"dish_id": dish_id, "planned_qty": 50.0, "unit": "份"},
            ],
        }

        resp = client.post("/api/v1/supply/ck/plans", json=plan_body, headers=headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "draft"
        assert body["data"]["plan_date"] == "2026-04-10"
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["dish_id"] == dish_id


# ═══════════════════════════════════════════════════════════════════════════════
# PUT /api/v1/supply/ck/plans/{plan_id}/status — 状态流转
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdatePlanStatus:
    """PUT /api/v1/supply/ck/plans/{plan_id}/status"""

    def _make_plan(self, tid: str) -> str:
        """Helper：创建生产计划，返回 plan_id。"""
        headers = {"X-Tenant-ID": tid}
        resp = client.post(
            "/api/v1/supply/ck/plans",
            json={
                "plan_date": "2026-04-11",
                "items": [{"dish_id": str(uuid.uuid4()), "planned_qty": 10.0, "unit": "份"}],
            },
            headers=headers,
        )
        return resp.json()["data"]["id"]

    def test_invalid_status_transition_returns_400(self):
        """draft → done 跳过中间状态：返回 400，错误信息含'不可从'。"""
        tid = _fresh_tid()
        plan_id = self._make_plan(tid)

        resp = client.put(
            f"/api/v1/supply/ck/plans/{plan_id}/status",
            json={"status": "done"},  # draft 只能转 confirmed
            headers={"X-Tenant-ID": tid},
        )
        assert resp.status_code == 400
        assert "不可从" in resp.json()["detail"]

    def test_valid_status_transition_draft_to_confirmed(self):
        """draft → confirmed 合法流转：返回 200，状态更新为 confirmed。"""
        tid = _fresh_tid()
        plan_id = self._make_plan(tid)

        resp = client.put(
            f"/api/v1/supply/ck/plans/{plan_id}/status",
            json={"status": "confirmed"},
            headers={"X-Tenant-ID": tid},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "confirmed"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/supply/ck/dispatch — 创建调拨单
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateDispatchOrder:
    """POST /api/v1/supply/ck/dispatch"""

    def test_create_dispatch_order_no_format_and_pending_status(self):
        """正常创建调拨单：单号格式 CK-YYYYMMDD-XXXX，初始状态 pending，含明细。"""
        tid = _fresh_tid()
        headers = {"X-Tenant-ID": tid}
        to_store = str(uuid.uuid4())
        dish_id = str(uuid.uuid4())

        body = {
            "to_store_id": to_store,
            "dispatch_date": "2026-04-15",
            "driver_name": "张三",
            "vehicle_no": "湘A12345",
            "items": [
                {"dish_id": dish_id, "planned_qty": 30.0, "unit": "份"},
            ],
        }

        resp = client.post("/api/v1/supply/ck/dispatch", json=body, headers=headers)
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["status"] == "pending"
        assert data["dispatch_no"].startswith("CK-20260415-")
        assert len(data["dispatch_no"]) == len("CK-20260415-XXXX")
        assert len(data["items"]) == 1
        assert data["to_store_id"] == to_store
