"""P0 报表路由单元测试

覆盖文件：api/reports_router.py（8 个端点，最多端点数路由）
测试 5 个端点/场景：

  1. GET /api/v1/analytics/reports/daily-revenue       — 正常返回多店汇总
  2. GET /api/v1/analytics/reports/payment-discount     — 缺少 store_id → 400
  3. GET /api/v1/analytics/reports/cashflow-by-store    — 正常返回现金流
  4. GET /api/v1/analytics/reports/billing-audit        — P0Reports 抛出 RuntimeError → 503
  5. GET /api/v1/analytics/daily-summary               — 缺少 X-Tenant-ID header → 400

技术说明：
  - reports_router 使用模块级单例 _p0 = P0Reports()，方法调用时传 db=None
  - 通过 unittest.mock.patch 替换 _p0 的各方法为 AsyncMock
  - 路由不依赖 get_db（传 db=None），无需 dependency_overrides
  - shared.* 模块通过 sys.modules 注入存根，避免循环导入
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 路径设置 ──────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── shared.* / structlog 存根注入（必须在导入路由模块前完成）──────────────────


def _make_analytics_stubs():
    """注入 shared.* 和 structlog 等外部依赖存根。"""

    # structlog
    sl = types.ModuleType("structlog")
    sl.get_logger = MagicMock(return_value=MagicMock(
        info=MagicMock(), warning=MagicMock(), error=MagicMock(),
    ))
    sys.modules.setdefault("structlog", sl)

    # shared
    shared = types.ModuleType("shared")
    sys.modules.setdefault("shared", shared)

    # shared.ontology
    ont = types.ModuleType("shared.ontology")
    sys.modules.setdefault("shared.ontology", ont)

    # shared.ontology.src
    ont_src = types.ModuleType("shared.ontology.src")
    sys.modules.setdefault("shared.ontology.src", ont_src)

    # shared.ontology.src.database
    db_mod = types.ModuleType("shared.ontology.src.database")
    db_mod.get_db = lambda: None  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.ontology.src.database", db_mod)

    # shared.events
    ev = types.ModuleType("shared.events")
    sys.modules.setdefault("shared.events", ev)
    ev_src = types.ModuleType("shared.events.src")
    sys.modules.setdefault("shared.events.src", ev_src)
    emitter = types.ModuleType("shared.events.src.emitter")
    emitter.emit_event = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    sys.modules.setdefault("shared.events.src.emitter", emitter)


_make_analytics_stubs()

# ─── 存根 P0Reports（在路由模块导入前先占位，防止真实 DB 连接）─────────────────

_mock_p0_class = MagicMock()
_mock_p0_instance = MagicMock()
_mock_p0_class.return_value = _mock_p0_instance

# reports 包存根
_reports_pkg = types.ModuleType("reports")
sys.modules.setdefault("reports", _reports_pkg)

_p0_mod = types.ModuleType("reports.p0_reports")
_p0_mod.P0Reports = _mock_p0_class  # type: ignore[attr-defined]
sys.modules["reports.p0_reports"] = _p0_mod

# ─── 导入路由模块 ──────────────────────────────────────────────────────────────

from api.reports_router import router  # noqa: E402
import api.reports_router as _rr_module  # noqa: E402

# ─── 公共常量 ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
TODAY = date.today()
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── FastAPI 应用工厂 ───────────────────────────────────────────────────────────


def _make_app() -> TestClient:
    """创建独立的 FastAPI 实例（reports_router 不依赖 get_db）。"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ─── 结果 Pydantic 存根（model_dump 返回可序列化字典）──────────────────────────


def _result_stub(**kwargs) -> MagicMock:
    stub = MagicMock()
    stub.model_dump = MagicMock(return_value={"ok": True, **kwargs})
    return stub


# ══════════════════════════════════════════════════════════════════════════════
# 一、营业收入汇总 — GET /api/v1/analytics/reports/daily-revenue
# ══════════════════════════════════════════════════════════════════════════════


def test_daily_revenue_ok():
    """正常传入 X-Tenant-ID，P0Reports.daily_revenue_summary 返回结构化数据。"""
    result_stub = _result_stub(
        tenant_id=TENANT_ID,
        biz_date=str(TODAY),
        total_revenue_fen=128800,
        total_orders=42,
        store_lines=[],
    )
    _rr_module._p0.daily_revenue_summary = AsyncMock(return_value=result_stub)

    client = _make_app()
    resp = client.get(
        "/api/v1/analytics/reports/daily-revenue",
        headers=HEADERS,
        params={"date": str(TODAY)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_revenue_fen"] == 128800
    assert body["data"]["total_orders"] == 42


# ══════════════════════════════════════════════════════════════════════════════
# 二、付款折扣表 — GET /api/v1/analytics/reports/payment-discount
#     缺少 store_id → 400
# ══════════════════════════════════════════════════════════════════════════════


def test_payment_discount_missing_store_id_400():
    """payment-discount 要求 store_id，缺省时应返回 400。"""
    client = _make_app()
    # 故意不传 store_id
    resp = client.get(
        "/api/v1/analytics/reports/payment-discount",
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "store_id" in resp.json().get("detail", "").lower()


# ══════════════════════════════════════════════════════════════════════════════
# 三、收款分门店 — GET /api/v1/analytics/reports/cashflow-by-store
# ══════════════════════════════════════════════════════════════════════════════


def test_cashflow_by_store_ok():
    """正常传入 tenant_id，cashflow_by_store 返回 ok=True 及数据体。"""
    result_stub = _result_stub(
        tenant_id=TENANT_ID,
        biz_date=str(TODAY),
        total_net_fen=98000,
        store_cashflows=[],
    )
    _rr_module._p0.cashflow_by_store = AsyncMock(return_value=result_stub)

    client = _make_app()
    resp = client.get(
        "/api/v1/analytics/reports/cashflow-by-store",
        headers=HEADERS,
        params={"date": str(TODAY)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_net_fen"] == 98000


# ══════════════════════════════════════════════════════════════════════════════
# 四、账单稽核 — GET /api/v1/analytics/reports/billing-audit
#     P0Reports 抛出 RuntimeError → 503
# ══════════════════════════════════════════════════════════════════════════════


def test_billing_audit_runtime_error_503():
    """P0Reports.billing_audit 抛出 RuntimeError（DB 不可用）时路由应返回 503。"""
    _rr_module._p0.billing_audit = AsyncMock(
        side_effect=RuntimeError("DB connection timeout")
    )

    client = _make_app()
    resp = client.get(
        "/api/v1/analytics/reports/billing-audit",
        headers=HEADERS,
        params={"store_id": STORE_ID, "date": str(TODAY)},
    )

    assert resp.status_code == 503
    assert "DB connection timeout" in resp.json().get("detail", "")


# ══════════════════════════════════════════════════════════════════════════════
# 五、日汇总（Agent 接口）— GET /api/v1/analytics/daily-summary
#     缺少 X-Tenant-ID header → 400
# ══════════════════════════════════════════════════════════════════════════════


def test_daily_summary_missing_tenant_id_400():
    """daily-summary 要求 X-Tenant-ID，缺省时路由应返回 400。"""
    client = _make_app()
    # 故意不传 X-Tenant-ID header，但传 store_id
    resp = client.get(
        "/api/v1/analytics/daily-summary",
        params={"store_id": STORE_ID},
    )

    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "X-Tenant-ID" in detail or "tenant" in detail.lower()
