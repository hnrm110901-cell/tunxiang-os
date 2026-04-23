"""energy_routes.py DB 端点单元测试 — 预算与告警规则

覆盖范围（8 个测试，专注改造后的 DB 端点）：

  GET  /budgets        — 返回2条记录 / 空列表
  POST /budgets        — UPSERT 成功含 id / SQLAlchemyError → 500
  GET  /alert-rules    — 返回2条规则
  POST /alert-rules    — INSERT 成功含 id
  DELETE /alert-rules/{rule_id} — 软删除成功 / RETURNING 空 → 404

技术约束：
  - sys.modules 存根注入隔离 shared.ontology / shared.events / services.tx_brain
  - app.dependency_overrides[get_db] 注入 mock AsyncSession
  - db.execute side_effect 列表按顺序消费（index-0 = _set_tenant 的 set_config）
  - list 端点使用 r._mapping 模式；upsert/create/delete 使用 fetchone()._mapping
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

# ── sys.modules 存根注入（必须在导入路由之前） ─────────────────────────────────


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    """确保 module_path 在 sys.modules 中存在，返回模块对象。"""
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.ontology.src.database
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# shared.events.*
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")
# EnergyEventType 枚举存根
if not hasattr(_ev_types, "EnergyEventType"):

    class _FakeEnergyEventType:
        READING_CAPTURED = "energy.reading_captured"
        ANOMALY_DETECTED = "energy.anomaly_detected"
        BENCHMARK_SET = "energy.benchmark_set"
        BUDGET_SET = "energy.budget_set"
        ALERT_RULE_CREATED = "energy.alert_rule_created"

    _ev_types.EnergyEventType = _FakeEnergyEventType

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# services.tx_brain 存根（snapshot/budget-vs-actual 端点使用，本文件不测试）
_ensure_stub("services")
_ensure_stub("services.tx_brain")
_ensure_stub("services.tx_brain.src")
_ensure_stub("services.tx_brain.src.agents")
_monitor_mock = AsyncMock()
_ensure_stub("services.tx_brain.src.agents.energy_monitor", {"energy_monitor": _monitor_mock})

# ── 导入路由（存根注入之后） ──────────────────────────────────────────────────

from shared.ontology.src.database import get_db  # noqa: E402

from ..api.energy_routes import router as energy_router  # noqa: E402

# ── FastAPI 应用 ───────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(energy_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── Mock 工具函数 ──────────────────────────────────────────────────────────────


def _mapping_row(data: dict) -> MagicMock:
    """构造带 _mapping 属性的行 mock，模拟 SQLAlchemy Row。"""
    row = MagicMock()
    row._mapping = data
    return row


def _make_fetchall_result(rows: list[dict]) -> MagicMock:
    """构造 list 端点使用的 execute 返回值（fetchall → 含 _mapping 的行列表）。"""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=[_mapping_row(r) for r in rows])
    result.fetchone = MagicMock(return_value=None)
    return result


def _make_fetchone_result(row: dict | None) -> MagicMock:
    """构造 upsert/create/delete 端点使用的 execute 返回值（fetchone）。"""
    result = MagicMock()
    if row is not None:
        result.fetchone = MagicMock(return_value=_mapping_row(row))
    else:
        result.fetchone = MagicMock(return_value=None)
    result.fetchall = MagicMock(return_value=[])
    return result


def _set_tenant_result() -> MagicMock:
    """_set_tenant 调用消耗的空结果。"""
    return MagicMock()


def _make_db(side_effects: list) -> AsyncMock:
    """构造 AsyncSession mock，execute 按 side_effects 列表依次返回。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _override(db_mock: AsyncMock):
    """返回 get_db dependency_overrides 覆盖函数。"""

    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


# ── 预算行数据工厂 ─────────────────────────────────────────────────────────────


def _budget_row(idx: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "period_type": "monthly",
        "period_value": f"2026-0{idx}",
        "electricity_budget_kwh": 5000.0 * idx,
        "gas_budget_m3": 200.0,
        "water_budget_ton": 80.0,
        "cost_budget_fen": 60000,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }


def _alert_rule_row(idx: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "rule_name": f"规则{idx}",
        "metric": "electricity_kwh",
        "threshold": 90.0,
        "comparison": "budget_pct",
        "alert_level": "warning",
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  GET /budgets — 列出月度预算
# ══════════════════════════════════════════════════════════════════════════════


class TestListEnergyBudgets:
    """GET /api/v1/ops/energy/budgets"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_budgets_success(self):
        """mock SELECT 返回2条预算 → 200，data.items 长度=2。"""
        rows = [_budget_row(1), _budget_row(2)]
        db = _make_db(
            [
                _set_tenant_result(),  # _set_tenant
                _make_fetchall_result(rows),  # SELECT energy_budgets
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/budgets",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["items"]) == 2
        assert body["data"]["total"] == 2
        # 验证第一条含预期字段
        first = body["data"]["items"][0]
        assert "id" in first
        assert first["electricity_budget_kwh"] == 5000.0

    def test_list_budgets_empty(self):
        """mock SELECT 返回空 → 200，data.items=[]。"""
        db = _make_db(
            [
                _set_tenant_result(),
                _make_fetchall_result([]),
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/budgets",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  POST /budgets — 设置月度预算（UPSERT）
# ══════════════════════════════════════════════════════════════════════════════

_BUDGET_PAYLOAD = {
    "store_id": STORE_ID,
    "budget_year": 2026,
    "budget_month": 5,
    "electricity_kwh_budget": 4800.0,
    "gas_m3_budget": 180.0,
    "water_ton_budget": 75.0,
    "total_cost_budget_fen": 55000,
}


class TestUpsertEnergyBudget:
    """POST /api/v1/ops/energy/budgets"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_upsert_budget_success(self):
        """mock INSERT/UPSERT RETURNING → 200，data 含 id。"""
        returned_row = {
            **_budget_row(5),
            "period_value": "2026-05",
            "electricity_budget_kwh": 4800.0,
            "gas_budget_m3": 180.0,
            "water_budget_ton": 75.0,
            "cost_budget_fen": 55000,
        }
        db = _make_db(
            [
                _set_tenant_result(),  # _set_tenant
                _make_fetchone_result(returned_row),  # INSERT ... RETURNING
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/budgets",
                    json=_BUDGET_PAYLOAD,
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]
        assert body["data"]["electricity_budget_kwh"] == 4800.0
        assert body["data"]["period_value"] == "2026-05"

    def test_upsert_budget_db_error(self):
        """mock SQLAlchemyError → 500 错误响应。"""
        db = _make_db(
            [
                _set_tenant_result(),  # _set_tenant
                SQLAlchemyError("connection reset"),  # INSERT 失败
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/energy/budgets",
                json=_BUDGET_PAYLOAD,
                headers=HEADERS,
            )

        assert resp.status_code == 500
        body = resp.json()
        # FastAPI HTTPException 返回 {"detail": "..."}
        assert "detail" in body


# ══════════════════════════════════════════════════════════════════════════════
#  GET /alert-rules — 列出告警规则
# ══════════════════════════════════════════════════════════════════════════════


class TestListAlertRules:
    """GET /api/v1/ops/energy/alert-rules"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_alert_rules_success(self):
        """mock SELECT 返回2条规则 → 200，data.items 长度=2。"""
        rows = [_alert_rule_row(1), _alert_rule_row(2)]
        db = _make_db(
            [
                _set_tenant_result(),
                _make_fetchall_result(rows),
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/energy/alert-rules",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["items"]) == 2
        assert body["data"]["total"] == 2
        # 验证字段
        first = body["data"]["items"][0]
        assert first["metric"] == "electricity_kwh"
        assert first["threshold"] == 90.0


# ══════════════════════════════════════════════════════════════════════════════
#  POST /alert-rules — 创建告警规则
# ══════════════════════════════════════════════════════════════════════════════

_RULE_PAYLOAD = {
    "store_id": STORE_ID,
    "rule_name": "燃气超用警告",
    "metric": "gas_m3",
    "threshold_type": "budget_pct",
    "threshold_value": 85.0,
    "severity": "warning",
}


class TestCreateAlertRule:
    """POST /api/v1/ops/energy/alert-rules"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_alert_rule_success(self):
        """mock INSERT RETURNING → 200，data 含 id。"""
        returned_row = {
            **_alert_rule_row(1),
            "rule_name": "燃气超用警告",
            "metric": "gas_m3",
            "threshold": 85.0,
            "comparison": "budget_pct",
            "alert_level": "warning",
            "is_active": True,
        }
        db = _make_db(
            [
                _set_tenant_result(),
                _make_fetchone_result(returned_row),
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with patch("asyncio.create_task"):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/energy/alert-rules",
                    json=_RULE_PAYLOAD,
                    headers=HEADERS,
                )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]
        assert body["data"]["metric"] == "gas_m3"
        assert body["data"]["threshold"] == 85.0
        assert body["data"]["is_active"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE /alert-rules/{rule_id} — 软删除告警规则
# ══════════════════════════════════════════════════════════════════════════════


class TestDeleteAlertRule:
    """DELETE /api/v1/ops/energy/alert-rules/{rule_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_alert_rule_success(self):
        """mock UPDATE SET is_deleted=TRUE RETURNING → 200，data.deleted=True。"""
        # RETURNING id 返回一行
        deleted_row = {"id": RULE_ID}
        db = _make_db(
            [
                _set_tenant_result(),
                _make_fetchone_result(deleted_row),
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/ops/energy/alert-rules/{RULE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["deleted"] is True
        assert body["data"]["rule_id"] == RULE_ID

    def test_delete_alert_rule_not_found(self):
        """mock UPDATE RETURNING 空（规则不存在或已删除）→ 404。"""
        db = _make_db(
            [
                _set_tenant_result(),
                _make_fetchone_result(None),  # RETURNING 返回空
            ]
        )
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.delete(
                f"/api/v1/ops/energy/alert-rules/{RULE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
