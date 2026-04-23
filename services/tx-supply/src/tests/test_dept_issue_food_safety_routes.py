"""部门领用 + 食安合规路由测试 — test_dept_issue_food_safety_routes.py

覆盖路由：
  dept_issue_routes.py  (7 端点)
    POST /api/v1/supply/dept-issue/orders
    POST /api/v1/supply/dept-issue/orders/{issue_id}/return
    POST /api/v1/supply/dept-issue/transfers
    POST /api/v1/supply/dept-issue/yield-check
    POST /api/v1/supply/dept-issue/sales-outbound
    GET  /api/v1/supply/dept-issue/flow/{store_id}/{dept_id}
    GET  /api/v1/supply/dept-issue/summary/{store_id}/{month}

  food_safety_routes.py (8 端点)
    POST /api/v1/supply/food-safety/block-expired
    POST /api/v1/supply/food-safety/check-banned
    GET  /api/v1/supply/food-safety/trace/{batch_no}
    POST /api/v1/supply/food-safety/sample
    POST /api/v1/supply/food-safety/temperature
    GET  /api/v1/supply/food-safety/checklist/{store_id}
    POST /api/v1/supply/food-safety/event
    POST /api/v1/supply/food-safety/responsibility-chain

测试数: 30
"""

from __future__ import annotations

import sys
import types
import uuid

# ── fake src.db stub ──────────────────────────────────────────────────────────
fake_db_mod = types.ModuleType("src.db")


async def fake_get_db():
    yield None


fake_db_mod.get_db = fake_get_db
sys.modules.setdefault("src", types.ModuleType("src"))
sys.modules.setdefault("src.db", fake_db_mod)

# ── 标准导入 ──────────────────────────────────────────────────────────────────
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

# ── dept_issue_routes 不依赖 shared.ontology，直接导入 ────────────────────────
from api.dept_issue_routes import router as dept_issue_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── food_safety_routes 依赖 shared.ontology.src.database.get_db ───────────────
# 需要预先 stub 相关模块
_shared_ont = types.ModuleType("shared")
_shared_ont_src = types.ModuleType("shared.ontology")
_shared_ont_src_src = types.ModuleType("shared.ontology.src")
_shared_ont_db = types.ModuleType("shared.ontology.src.database")
_fake_session = MagicMock()


async def _fake_shared_get_db():
    yield _fake_session


_shared_ont_db.get_db = _fake_shared_get_db
sys.modules.setdefault("shared", _shared_ont)
sys.modules.setdefault("shared.ontology", _shared_ont_src)
sys.modules.setdefault("shared.ontology.src", _shared_ont_src_src)
sys.modules.setdefault("shared.ontology.src.database", _shared_ont_db)

# stub food_safety service
_food_safety_svc = types.ModuleType("services.food_safety")
sys.modules.setdefault("services", types.ModuleType("services"))
sys.modules.setdefault("services.food_safety", _food_safety_svc)

# relative import path used by food_safety_routes: ..services.food_safety
# We need to provide it under the package path the route module uses
_pkg_services = types.ModuleType("api")
sys.modules.setdefault("api", _pkg_services)

from api.food_safety_routes import router as food_safety_router  # noqa: E402

# ── App 组装 ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(dept_issue_router)
app.include_router(food_safety_router)

# Override food_safety_routes 的 DB Dependency
from shared.ontology.src.database import get_db as _shared_get_db  # noqa: E402


async def _override_get_db():
    yield _fake_session


app.dependency_overrides[_shared_get_db] = _override_get_db

client = TestClient(app)

# ── 公共常量 ──────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DEPT_ID = "kitchen"
HEADERS = {"X-Tenant-ID": TENANT}
_DI_MOD = "api.dept_issue_routes"
_FS_MOD = "api.food_safety_routes"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ═══════════════════════════════════════════════════════════════════════════════
# Part A: 部门领用路由
# ═══════════════════════════════════════════════════════════════════════════════


class TestCreateIssueOrder:
    """POST /api/v1/supply/dept-issue/orders"""

    def test_create_issue_ok(self):
        """正常创建领用单。"""
        issue_id = f"issue_{_uid()}"
        mock_ret = {"issue_id": issue_id, "status": "confirmed", "total_cost_fen": 42000}
        with patch(f"{_DI_MOD}.create_issue_order", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "store_id": STORE_ID,
                "dept_id": DEPT_ID,
                "operator_id": "emp_001",
                "items": [
                    {"ingredient_id": "i1", "name": "猪肉", "quantity": 5.0, "unit": "kg", "unit_cost_fen": 3500},
                    {"ingredient_id": "i2", "name": "白菜", "quantity": 10.0, "unit": "kg", "unit_cost_fen": 700},
                ],
            }
            resp = client.post("/api/v1/supply/dept-issue/orders", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["data"]["issue_id"] == issue_id

    def test_create_issue_zero_quantity_rejected(self):
        """quantity=0 不符合 gt=0，返回 422。"""
        body = {
            "store_id": STORE_ID,
            "dept_id": DEPT_ID,
            "operator_id": "emp_001",
            "items": [{"ingredient_id": "i1", "quantity": 0.0}],
        }
        resp = client.post("/api/v1/supply/dept-issue/orders", json=body, headers=HEADERS)
        assert resp.status_code == 422

    def test_create_issue_missing_header(self):
        """缺少 X-Tenant-ID 返回 422。"""
        body = {
            "store_id": STORE_ID,
            "dept_id": DEPT_ID,
            "operator_id": "emp_001",
            "items": [{"ingredient_id": "i1", "quantity": 1.0}],
        }
        resp = client.post("/api/v1/supply/dept-issue/orders", json=body)
        assert resp.status_code == 422

    def test_create_issue_value_error_returns_400(self):
        """Service 层 ValueError 时返回 400。"""
        with patch(
            f"{_DI_MOD}.create_issue_order",
            new_callable=AsyncMock,
            side_effect=ValueError("库存不足"),
        ):
            body = {
                "store_id": STORE_ID,
                "dept_id": DEPT_ID,
                "operator_id": "emp_001",
                "items": [{"ingredient_id": "i1", "quantity": 999.0}],
            }
            resp = client.post("/api/v1/supply/dept-issue/orders", json=body, headers=HEADERS)
        assert resp.status_code == 400
        assert "库存不足" in resp.json()["detail"]


class TestCreateReturnOrder:
    """POST /api/v1/supply/dept-issue/orders/{issue_id}/return"""

    def test_return_ok(self):
        """正常创建退回单。"""
        issue_id = f"issue_{_uid()}"
        ret_id = f"ret_{_uid()}"
        mock_ret = {"return_id": ret_id, "issue_id": issue_id, "status": "confirmed"}
        with patch(f"{_DI_MOD}.create_return_order", new_callable=AsyncMock, return_value=mock_ret):
            body = {"items": [{"ingredient_id": "i1", "quantity": 2.0, "reason": "过量领取"}]}
            resp = client.post(
                f"/api/v1/supply/dept-issue/orders/{issue_id}/return",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["return_id"] == ret_id

    def test_return_value_error_returns_400(self):
        """领用单不存在时返回 400。"""
        issue_id = f"issue_{_uid()}"
        with patch(
            f"{_DI_MOD}.create_return_order",
            new_callable=AsyncMock,
            side_effect=ValueError("领用单不存在"),
        ):
            body = {"items": [{"ingredient_id": "i1", "quantity": 1.0}]}
            resp = client.post(
                f"/api/v1/supply/dept-issue/orders/{issue_id}/return",
                json=body,
                headers=HEADERS,
            )
        assert resp.status_code == 400


class TestCreateDeptTransfer:
    """POST /api/v1/supply/dept-issue/transfers"""

    def test_transfer_ok(self):
        """部门间调拨成功。"""
        transfer_id = f"dt_{_uid()}"
        mock_ret = {"transfer_id": transfer_id, "from_dept": "kitchen", "to_dept": "bar", "status": "confirmed"}
        with patch(f"{_DI_MOD}.create_dept_transfer", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "from_dept": "kitchen",
                "to_dept": "bar",
                "items": [{"ingredient_id": "i1", "name": "柠檬", "quantity": 5.0, "unit": "个"}],
            }
            resp = client.post("/api/v1/supply/dept-issue/transfers", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["transfer_id"] == transfer_id

    def test_transfer_value_error_returns_400(self):
        """同部门调拨时 Service 抛出 ValueError，返回 400。"""
        with patch(
            f"{_DI_MOD}.create_dept_transfer",
            new_callable=AsyncMock,
            side_effect=ValueError("不能调拨给自己"),
        ):
            body = {
                "from_dept": "kitchen",
                "to_dept": "kitchen",
                "items": [{"ingredient_id": "i1", "quantity": 1.0}],
            }
            resp = client.post("/api/v1/supply/dept-issue/transfers", json=body, headers=HEADERS)
        assert resp.status_code == 400


class TestCheckYieldRate:
    """POST /api/v1/supply/dept-issue/yield-check"""

    def test_yield_check_ok(self):
        """出料率抽检返回合格结果。"""
        mock_ret = {
            "dish_id": "dish_001",
            "actual_output": 4.8,
            "theoretical_output": 5.0,
            "yield_rate": 0.96,
            "status": "ok",
        }
        with patch(f"{_DI_MOD}.check_yield_rate", new_callable=AsyncMock, return_value=mock_ret):
            body = {
                "dish_id": "dish_001",
                "store_id": STORE_ID,
                "actual_output": 4.8,
                "theoretical_output": 5.0,
            }
            resp = client.post("/api/v1/supply/dept-issue/yield-check", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["yield_rate"] == pytest.approx(0.96)

    def test_yield_check_theoretical_zero_rejected(self):
        """theoretical_output=0 不符合 gt=0，Pydantic 返回 422。"""
        body = {
            "dish_id": "dish_001",
            "store_id": STORE_ID,
            "actual_output": 4.8,
            "theoretical_output": 0.0,
        }
        resp = client.post("/api/v1/supply/dept-issue/yield-check", json=body, headers=HEADERS)
        assert resp.status_code == 422


class TestSalesOutbound:
    """POST /api/v1/supply/dept-issue/sales-outbound"""

    def test_sales_outbound_ok(self):
        """销售转出库成功。"""
        mock_ret = {"store_id": STORE_ID, "date": "2026-04-06", "outbound_count": 5}
        with patch(f"{_DI_MOD}.sales_to_inventory", new_callable=AsyncMock, return_value=mock_ret):
            body = {"store_id": STORE_ID, "date": "2026-04-06"}
            resp = client.post("/api/v1/supply/dept-issue/sales-outbound", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["outbound_count"] == 5


class TestGetIssueFlow:
    """GET /api/v1/supply/dept-issue/flow/{store_id}/{dept_id}"""

    def test_get_flow_ok(self):
        """正常返回领用流水。"""
        mock_ret = {
            "store_id": STORE_ID,
            "dept_id": DEPT_ID,
            "items": [
                {"ingredient_id": "i1", "name": "猪肉", "total_qty": 20.0},
            ],
        }
        with patch(f"{_DI_MOD}.get_issue_flow", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(
                f"/api/v1/supply/dept-issue/flow/{STORE_ID}/{DEPT_ID}",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(resp.json()["data"]["items"]) == 1

    def test_get_flow_with_date_range(self):
        """带日期范围参数查询。"""
        mock_ret = {"store_id": STORE_ID, "dept_id": DEPT_ID, "items": []}
        with patch(f"{_DI_MOD}.get_issue_flow", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(
                f"/api/v1/supply/dept-issue/flow/{STORE_ID}/{DEPT_ID}?start_date=2026-04-01&end_date=2026-04-06",
                headers=HEADERS,
            )
        assert resp.status_code == 200


class TestGetMonthlySummary:
    """GET /api/v1/supply/dept-issue/summary/{store_id}/{month}"""

    def test_get_summary_ok(self):
        """月度汇总返回正确数据。"""
        mock_ret = {
            "store_id": STORE_ID,
            "month": "2026-04",
            "total_cost_fen": 350000,
            "dept_breakdown": [{"dept_id": "kitchen", "cost_fen": 350000}],
        }
        with patch(f"{_DI_MOD}.get_monthly_summary", new_callable=AsyncMock, return_value=mock_ret):
            resp = client.get(
                f"/api/v1/supply/dept-issue/summary/{STORE_ID}/2026-04",
                headers=HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_cost_fen"] == 350000


# ═══════════════════════════════════════════════════════════════════════════════
# Part B: 食安合规路由
# ═══════════════════════════════════════════════════════════════════════════════


class TestBlockExpiredIngredient:
    """POST /api/v1/supply/food-safety/block-expired"""

    def test_block_expired_ok(self):
        """成功禁用过期原料。"""
        mock_ret = {"ingredient_id": "i1", "store_id": STORE_ID, "blocked": True}
        with patch(f"{_FS_MOD}.food_safety.block_expired_ingredient", new_callable=AsyncMock, return_value=mock_ret):
            body = {"ingredient_id": "i1", "store_id": STORE_ID}
            resp = client.post("/api/v1/supply/food-safety/block-expired", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["blocked"] is True

    def test_block_expired_missing_header(self):
        """缺少 tenant header 返回 422。"""
        body = {"ingredient_id": "i1", "store_id": STORE_ID}
        resp = client.post("/api/v1/supply/food-safety/block-expired", json=body)
        assert resp.status_code == 422


class TestCheckBannedIngredients:
    """POST /api/v1/supply/food-safety/check-banned"""

    def test_check_passed(self):
        """无禁用食材时返回 passed=True。"""
        mock_ret = {"passed": True, "banned_items": []}
        with patch(
            f"{_FS_MOD}.food_safety.check_banned_ingredients",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            body = {
                "store_id": STORE_ID,
                "order_items": [{"ingredient_id": "i1", "name": "猪肉"}],
            }
            resp = client.post("/api/v1/supply/food-safety/check-banned", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["passed"] is True

    def test_check_banned_returns_422(self):
        """含禁用食材时路由抛出 422。"""
        mock_ret = {"passed": False, "banned_items": [{"ingredient_id": "i99", "name": "违禁品"}]}
        with patch(
            f"{_FS_MOD}.food_safety.check_banned_ingredients",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            body = {
                "store_id": STORE_ID,
                "order_items": [{"ingredient_id": "i99", "name": "违禁品"}],
            }
            resp = client.post("/api/v1/supply/food-safety/check-banned", json=body, headers=HEADERS)
        assert resp.status_code == 422


class TestTraceBatch:
    """GET /api/v1/supply/food-safety/trace/{batch_no}"""

    def test_trace_found(self):
        """批次追溯成功。"""
        mock_ret = {
            "found": True,
            "batch_no": "B001",
            "supplier": "鲜生供应商",
            "chain": ["采购", "入库", "领用", "出品"],
        }
        with patch(
            f"{_FS_MOD}.food_safety.trace_batch",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            resp = client.get("/api/v1/supply/food-safety/trace/B001", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["found"] is True
        assert resp.json()["data"]["batch_no"] == "B001"

    def test_trace_not_found_returns_404(self):
        """批次不存在时返回 404。"""
        mock_ret = {"found": False}
        with patch(
            f"{_FS_MOD}.food_safety.trace_batch",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            resp = client.get("/api/v1/supply/food-safety/trace/NO_SUCH_BATCH", headers=HEADERS)
        assert resp.status_code == 404


class TestRecordSample:
    """POST /api/v1/supply/food-safety/sample"""

    def test_record_sample_ok(self):
        """留样记录创建成功。"""
        sample_id = f"smp_{_uid()}"
        mock_ret = {"sample_id": sample_id, "store_id": STORE_ID, "retention_until": "2026-04-08T12:00:00"}
        with patch(f"{_FS_MOD}.food_safety.record_sample", return_value=mock_ret):
            body = {
                "store_id": STORE_ID,
                "dish_id": "dish_001",
                "sample_time": "2026-04-06T12:00:00",
                "photo_url": "https://cdn.example.com/sample.jpg",
                "operator_id": "emp_001",
            }
            resp = client.post("/api/v1/supply/food-safety/sample", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["sample_id"] == sample_id


class TestRecordTemperature:
    """POST /api/v1/supply/food-safety/temperature"""

    def test_record_temp_ok(self):
        """温控记录创建成功。"""
        mock_ret = {"location": "cold_storage", "temperature": 3.2, "status": "normal"}
        with patch(f"{_FS_MOD}.food_safety.record_temperature", return_value=mock_ret):
            body = {
                "store_id": STORE_ID,
                "location": "cold_storage",
                "temperature": 3.2,
                "operator_id": "emp_001",
            }
            resp = client.post("/api/v1/supply/food-safety/temperature", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "normal"


class TestGetComplianceChecklist:
    """GET /api/v1/supply/food-safety/checklist/{store_id}"""

    def test_get_checklist_ok(self):
        """获取合规检查表。"""
        mock_ret = {
            "store_id": STORE_ID,
            "check_date": "2026-04-06",
            "items": [
                {"item": "冷藏温度", "status": "ok"},
                {"item": "留样记录", "status": "ok"},
            ],
        }
        with patch(f"{_FS_MOD}.food_safety.get_compliance_checklist", return_value=mock_ret):
            resp = client.get(f"/api/v1/supply/food-safety/checklist/{STORE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 2


class TestReportFoodSafetyEvent:
    """POST /api/v1/supply/food-safety/event"""

    def test_report_event_ok(self):
        """食安事件上报成功。"""
        event_id = f"evt_{_uid()}"
        mock_ret = {"event_id": event_id, "severity": "high", "notified_region_manager": True}
        with patch(
            f"{_FS_MOD}.food_safety.report_food_safety_event",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            body = {
                "store_id": STORE_ID,
                "event_type": "temperature_violation",
                "detail": "冷藏温度超过 4°C",
                "severity": "high",
            }
            resp = client.post("/api/v1/supply/food-safety/event", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["data"]["event_id"] == event_id


class TestGetResponsibilityChain:
    """POST /api/v1/supply/food-safety/responsibility-chain"""

    def test_get_chain_ok(self):
        """责任追踪链查询成功。"""
        mock_ret = {
            "event_id": "evt_001",
            "chain": [
                {"role": "采购", "employee_id": "emp_001", "action": "purchase", "timestamp": "2026-04-01"},
                {"role": "验收", "employee_id": "emp_002", "action": "receive", "timestamp": "2026-04-02"},
            ],
        }
        with patch(
            f"{_FS_MOD}.food_safety.get_responsibility_chain",
            new_callable=AsyncMock,
            return_value=mock_ret,
        ):
            body = {
                "event_id": "evt_001",
                "batch_no": "B001",
                "ingredient_id": "i1",
                "store_id": STORE_ID,
            }
            resp = client.post("/api/v1/supply/food-safety/responsibility-chain", json=body, headers=HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["data"]["chain"]) == 2

    def test_chain_missing_tenant_returns_422(self):
        """缺少 X-Tenant-ID 返回 422。"""
        body = {"event_id": "evt_001"}
        resp = client.post("/api/v1/supply/food-safety/responsibility-chain", json=body)
        assert resp.status_code == 422
