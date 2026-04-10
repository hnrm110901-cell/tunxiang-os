"""central_kitchen_routes.py — 中央厨房 API 路由测试

测试范围（16个测试）：
  - GET  /api/v1/supply/central-kitchen/kitchens              — 厨房列表（正常 / ValueError→400）
  - POST /api/v1/supply/central-kitchen/kitchens              — 新建厨房（HTTP201 / ValueError→400）
  - GET  /api/v1/supply/central-kitchen/kitchens/{id}/dashboard — 厨房看板（正常 / ValueError→400）
  - GET  /api/v1/supply/central-kitchen/plans                 — 计划列表（正常）
  - POST /api/v1/supply/central-kitchen/plans                 — 创建计划（ValueError→400）
  - GET  /api/v1/supply/central-kitchen/plans/{id}            — 计划详情（正常 / ValueError→404）
  - POST /api/v1/supply/central-kitchen/plans/{id}/confirm    — 确认计划（正常 / ValueError→400）
  - PUT  /api/v1/supply/central-kitchen/plans/{id}/start      — 开始生产（正常）
  - GET  /api/v1/supply/central-kitchen/production-orders     — 工单列表（正常）
  - PUT  /api/v1/supply/central-kitchen/orders/{id}/complete  — 完成工单（正常 / ValueError→400）
  - PUT  /api/v1/supply/central-kitchen/production-orders/{id}/progress — 更新进度（正常）
  - GET  /api/v1/supply/central-kitchen/distribution          — 配送单列表（正常）
  - POST /api/v1/supply/central-kitchen/distribution          — 创建配送单（HTTP201 / ValueError→400）
  - POST /api/v1/supply/central-kitchen/distribution/{id}/deliver — 标记已发出（正常）
  - POST /api/v1/supply/central-kitchen/distribution/{id}/receive — 门店收货（正常）
  - PUT  /api/v1/supply/central-kitchen/distribution/{id}/confirm — 确认收货PUT别名（正常）
  - GET  /api/v1/supply/central-kitchen/dashboard             — 日看板（正常 / ValueError→400）
  - GET  /api/v1/supply/central-kitchen/demand-forecast       — 需求预测（正常 / ValueError→400）

Mock 模式：
  - shared.ontology.src.database 通过 sys.modules 注入 fake_get_db
  - CentralKitchenService 通过 unittest.mock.patch 拦截，避免真实 DB 依赖
"""
from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Mock shared.ontology.src.database（必须在 import routes 之前）──────────────

_fake_shared = types.ModuleType("shared")
_fake_ontology = types.ModuleType("shared.ontology")
_fake_ontology_src = types.ModuleType("shared.ontology.src")
_fake_db_mod = types.ModuleType("shared.ontology.src.database")


async def _fake_get_db():
    yield None


_fake_db_mod.get_db = _fake_get_db

sys.modules.setdefault("shared", _fake_shared)
sys.modules.setdefault("shared.ontology", _fake_ontology)
sys.modules.setdefault("shared.ontology.src", _fake_ontology_src)
sys.modules.setdefault("shared.ontology.src.database", _fake_db_mod)

# structlog mock
_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = lambda *a, **kw: MagicMock()
sys.modules.setdefault("structlog", _fake_structlog)

# sqlalchemy.ext.asyncio mock
_fake_sa = types.ModuleType("sqlalchemy")
_fake_sa_ext = types.ModuleType("sqlalchemy.ext")
_fake_sa_ext_async = types.ModuleType("sqlalchemy.ext.asyncio")
_fake_sa_ext_async.AsyncSession = object
sys.modules.setdefault("sqlalchemy", _fake_sa)
sys.modules.setdefault("sqlalchemy.ext", _fake_sa_ext)
sys.modules.setdefault("sqlalchemy.ext.asyncio", _fake_sa_ext_async)

import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.central_kitchen_routes import router as ck_router

# ─── App 组装 ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(ck_router)
client = TestClient(app)

# ─── 路径常量 ─────────────────────────────────────────────────────────────────

_BASE = "/api/v1/supply/central-kitchen"
_SVC_PATCH = "api.central_kitchen_routes.CentralKitchenService"


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _tid() -> str:
    return str(uuid.uuid4())


def _headers(tid: str | None = None) -> dict:
    return {"X-Tenant-ID": tid or _tid()}


def _mock_obj(**fields) -> MagicMock:
    """生成带有 model_dump() 的 mock 领域对象。"""
    obj = MagicMock()
    obj.model_dump.return_value = {"id": str(uuid.uuid4()), **fields}
    return obj


# ─── 测试：厨房档案 ──────────────────────────────────────────────────────────


class TestListKitchens:
    """GET /kitchens — 中央厨房列表"""

    def test_list_kitchens_returns_ok(self):
        """正常返回 ok=True，items 为列表。"""
        kitchen = _mock_obj(name="测试厨房", status="active")
        svc = MagicMock()
        svc.list_kitchens = AsyncMock(return_value=[kitchen])

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(f"{_BASE}/kitchens", headers=_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert len(body["data"]["items"]) == 1

    def test_list_kitchens_service_error_returns_400(self):
        """service 抛 ValueError → HTTP 400。"""
        svc = MagicMock()
        svc.list_kitchens = AsyncMock(side_effect=ValueError("租户无效"))

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(f"{_BASE}/kitchens", headers=_headers())

        assert resp.status_code == 400
        assert "租户无效" in resp.json()["detail"]


class TestCreateKitchen:
    """POST /kitchens — 新建中央厨房档案"""

    _body = {
        "name": "中央厨房A",
        "address": "长沙市岳麓区XX路1号",
        "capacity_daily": 500.0,
        "manager_id": "emp-001",
        "contact_phone": "13800138000",
    }

    def test_create_kitchen_returns_201(self):
        """正常创建：HTTP 201，返回厨房数据。"""
        kitchen = _mock_obj(name="中央厨房A")
        svc = MagicMock()
        svc.create_kitchen = AsyncMock(return_value=kitchen)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/kitchens",
                json=self._body,
                headers=_headers(),
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]

    def test_create_kitchen_value_error_returns_400(self):
        """名称重复等 ValueError → HTTP 400。"""
        svc = MagicMock()
        svc.create_kitchen = AsyncMock(side_effect=ValueError("名称已存在"))

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/kitchens",
                json=self._body,
                headers=_headers(),
            )

        assert resp.status_code == 400
        assert "名称已存在" in resp.json()["detail"]

    def test_create_kitchen_missing_name_returns_422(self):
        """缺少必填字段 name → Pydantic 校验失败 422。"""
        resp = client.post(
            f"{_BASE}/kitchens",
            json={"address": "XX路"},
            headers=_headers(),
        )
        assert resp.status_code == 422


# ─── 测试：生产计划 ──────────────────────────────────────────────────────────


class TestListProductionPlans:
    """GET /plans — 生产计划列表"""

    def test_list_plans_returns_ok(self):
        """正常返回 ok=True，data 含分页结果。"""
        svc = MagicMock()
        svc.list_production_plans = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "size": 20}
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(f"{_BASE}/plans", headers=_headers())

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestGetProductionPlan:
    """GET /plans/{id} — 生产计划详情"""

    def test_get_plan_found(self):
        """存在的计划返回 200 + ok=True。"""
        plan = _mock_obj(status="draft", kitchen_id="ck-001")
        svc = MagicMock()
        svc.get_production_plan = AsyncMock(return_value=plan)

        plan_id = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(f"{_BASE}/plans/{plan_id}", headers=_headers())

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_plan_not_found_returns_404(self):
        """不存在的计划 → ValueError → HTTP 404。"""
        svc = MagicMock()
        svc.get_production_plan = AsyncMock(side_effect=ValueError("计划不存在"))

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/plans/{uuid.uuid4()}",
                headers=_headers(),
            )

        assert resp.status_code == 404
        assert "计划不存在" in resp.json()["detail"]


class TestConfirmProductionPlan:
    """POST /plans/{id}/confirm — 确认生产计划"""

    def test_confirm_plan_returns_ok(self):
        """正常确认：返回 200，ok=True。"""
        plan = _mock_obj(status="confirmed")
        svc = MagicMock()
        svc.confirm_production_plan = AsyncMock(return_value=plan)

        plan_id = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/plans/{plan_id}/confirm",
                json={"operator_id": "emp-001"},
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_confirm_plan_value_error_returns_400(self):
        """非 draft 状态确认 → ValueError → 400。"""
        svc = MagicMock()
        svc.confirm_production_plan = AsyncMock(
            side_effect=ValueError("只有草稿状态可确认")
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/plans/{uuid.uuid4()}/confirm",
                json={"operator_id": "emp-001"},
                headers=_headers(),
            )

        assert resp.status_code == 400


class TestStartProduction:
    """PUT /plans/{id}/start — 开始生产"""

    def test_start_production_returns_ok(self):
        """confirmed → in_progress 正常流转，返回 200。"""
        plan = _mock_obj(status="in_progress")
        svc = MagicMock()
        svc.start_production = AsyncMock(return_value=plan)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.put(
                f"{_BASE}/plans/{uuid.uuid4()}/start",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── 测试：生产工单 ──────────────────────────────────────────────────────────


class TestListProductionOrders:
    """GET /production-orders — 生产工单列表"""

    def test_list_orders_returns_ok(self):
        """正常返回工单列表。"""
        svc = MagicMock()
        svc.list_production_orders = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "size": 20}
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(f"{_BASE}/production-orders", headers=_headers())

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestCompleteProductionOrder:
    """PUT /orders/{id}/complete — 完成生产工单"""

    def test_complete_order_returns_ok(self):
        """记录实际产量，返回 200。"""
        order = _mock_obj(status="completed", actual_qty=98.5)
        svc = MagicMock()
        svc.complete_production_order = AsyncMock(return_value=order)

        order_id = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.put(
                f"{_BASE}/orders/{order_id}/complete?actual_qty=98.5",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_complete_order_value_error_returns_400(self):
        """工单已完成重复提交 → ValueError → 400。"""
        svc = MagicMock()
        svc.complete_production_order = AsyncMock(
            side_effect=ValueError("工单已完成，不可重复操作")
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.put(
                f"{_BASE}/orders/{uuid.uuid4()}/complete?actual_qty=10.0",
                headers=_headers(),
            )

        assert resp.status_code == 400


class TestUpdateProductionProgress:
    """PUT /production-orders/{id}/progress — 更新工单进度"""

    def test_update_progress_to_in_progress(self):
        """将工单状态推进为 in_progress，返回 200。"""
        order = _mock_obj(status="in_progress")
        svc = MagicMock()
        svc.update_production_progress = AsyncMock(return_value=order)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.put(
                f"{_BASE}/production-orders/{uuid.uuid4()}/progress",
                json={"status": "in_progress"},
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── 测试：配送单 ─────────────────────────────────────────────────────────────


class TestListDistributionOrders:
    """GET /distribution — 配送单列表"""

    def test_list_distribution_returns_ok(self):
        """正常返回配送单列表，支持按门店过滤。"""
        svc = MagicMock()
        svc.list_distribution_orders = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "size": 20}
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/distribution?store_id={uuid.uuid4()}",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestCreateDistributionOrder:
    """POST /distribution — 创建配送单"""

    _body = {
        "kitchen_id": str(uuid.uuid4()),
        "target_store_id": str(uuid.uuid4()),
        "scheduled_at": "2026-04-10T08:00:00",
        "driver_name": "李师傅",
        "driver_phone": "13900139000",
        "items": [
            {
                "dish_id": str(uuid.uuid4()),
                "dish_name": "红烧肉",
                "quantity": 50.0,
                "unit": "份",
            }
        ],
    }

    def test_create_distribution_returns_201(self):
        """正常创建配送单，返回 HTTP 201。"""
        order = _mock_obj(status="pending", kitchen_id=self._body["kitchen_id"])
        svc = MagicMock()
        svc.create_distribution_order = AsyncMock(return_value=order)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/distribution",
                json=self._body,
                headers=_headers(),
            )

        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    def test_create_distribution_value_error_returns_400(self):
        """厨房不存在等 ValueError → 400。"""
        svc = MagicMock()
        svc.create_distribution_order = AsyncMock(
            side_effect=ValueError("中央厨房不存在")
        )

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/distribution",
                json=self._body,
                headers=_headers(),
            )

        assert resp.status_code == 400
        assert "中央厨房不存在" in resp.json()["detail"]


class TestMarkDispatched:
    """POST /distribution/{id}/deliver — 标记已发出"""

    def test_mark_dispatched_returns_ok(self):
        """pending → dispatched，返回 200。"""
        order = _mock_obj(status="dispatched")
        svc = MagicMock()
        svc.mark_dispatched = AsyncMock(return_value=order)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/distribution/{uuid.uuid4()}/deliver",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestStoreReceive:
    """POST /distribution/{id}/receive — 门店确认收货（POST 版）"""

    _receive_body = {
        "store_id": str(uuid.uuid4()),
        "confirmed_by": "emp-002",
        "notes": "货品完好",
        "items": [
            {
                "dish_id": str(uuid.uuid4()),
                "dish_name": "红烧肉",
                "received_qty": 48.0,
                "unit": "份",
                "variance_notes": None,
            }
        ],
    }

    def test_store_receive_returns_ok(self):
        """门店签收，返回 200 + 确认记录。"""
        confirmation = _mock_obj(store_id=self._receive_body["store_id"])
        svc = MagicMock()
        svc.confirm_store_receiving = AsyncMock(return_value=confirmation)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.post(
                f"{_BASE}/distribution/{uuid.uuid4()}/receive",
                json=self._receive_body,
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestStoreReceiveConfirm:
    """PUT /distribution/{id}/confirm — 门店确认收货（PUT 别名）"""

    _receive_body = {
        "store_id": str(uuid.uuid4()),
        "confirmed_by": "emp-003",
        "notes": None,
        "items": [
            {
                "dish_id": str(uuid.uuid4()),
                "dish_name": "清蒸鱼",
                "received_qty": 20.0,
                "unit": "份",
                "variance_notes": None,
            }
        ],
    }

    def test_put_confirm_returns_ok(self):
        """PUT 别名功能与 POST /receive 相同，返回 200。"""
        confirmation = _mock_obj(store_id=self._receive_body["store_id"])
        svc = MagicMock()
        svc.confirm_store_receiving = AsyncMock(return_value=confirmation)

        with patch(_SVC_PATCH, return_value=svc):
            resp = client.put(
                f"{_BASE}/distribution/{uuid.uuid4()}/confirm",
                json=self._receive_body,
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─── 测试：看板与预测 ─────────────────────────────────────────────────────────


class TestDashboard:
    """GET /dashboard — 日看板（query-param 版）"""

    def test_dashboard_returns_ok(self):
        """按 kitchen_id + date 查询，返回 200。"""
        dashboard = _mock_obj(
            plan_count=3,
            order_summary={"pending": 2, "completed": 1},
            distribution_summary={"pending": 1, "dispatched": 2},
        )
        svc = MagicMock()
        svc.get_daily_dashboard = AsyncMock(return_value=dashboard)

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/dashboard?kitchen_id={kid}&date=2026-04-06",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_dashboard_value_error_returns_400(self):
        """日期格式错误 → ValueError → 400。"""
        svc = MagicMock()
        svc.get_daily_dashboard = AsyncMock(side_effect=ValueError("日期格式错误"))

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/dashboard?kitchen_id={kid}&date=invalid-date",
                headers=_headers(),
            )

        assert resp.status_code == 400


class TestDemandForecast:
    """GET /demand-forecast — 需求预测"""

    def test_demand_forecast_returns_ok(self):
        """正常预测：返回 200 + 预测数据。"""
        forecast = _mock_obj(
            kitchen_id="ck-001",
            target_date="2026-04-10",
            items=[{"dish_id": "dish-001", "forecast_qty": 120.0}],
        )
        svc = MagicMock()
        svc.forecast_demand = AsyncMock(return_value=forecast)

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/demand-forecast?kitchen_id={kid}&target_date=2026-04-10",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_demand_forecast_value_error_returns_400(self):
        """厨房不存在 → ValueError → 400。"""
        svc = MagicMock()
        svc.forecast_demand = AsyncMock(side_effect=ValueError("厨房不存在"))

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/demand-forecast?kitchen_id={kid}&target_date=2026-04-10",
                headers=_headers(),
            )

        assert resp.status_code == 400
        assert "厨房不存在" in resp.json()["detail"]


class TestKitchenDashboard:
    """GET /kitchens/{id}/dashboard — 厨房看板（path-param 版）"""

    def test_kitchen_dashboard_returns_ok(self):
        """路径参数版看板，返回 200。"""
        dashboard = _mock_obj(plan_count=5)
        svc = MagicMock()
        svc.get_daily_dashboard = AsyncMock(return_value=dashboard)

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/kitchens/{kid}/dashboard?date=2026-04-06",
                headers=_headers(),
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_kitchen_dashboard_value_error_returns_400(self):
        """service 抛 ValueError → 400。"""
        svc = MagicMock()
        svc.get_daily_dashboard = AsyncMock(side_effect=ValueError("日期超出范围"))

        kid = str(uuid.uuid4())
        with patch(_SVC_PATCH, return_value=svc):
            resp = client.get(
                f"{_BASE}/kitchens/{kid}/dashboard?date=invalid",
                headers=_headers(),
            )

        assert resp.status_code == 400
