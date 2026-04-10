"""
tx-finance 核心路由测试
覆盖 settlement_routes 和 payroll_routes 最关键的 CRUD 操作。

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_finance_core.py -v
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 注入缺失的存根模块 ──────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# structlog 存根
if "structlog" not in sys.modules:
    stub_log = MagicMock()
    stub_log.get_logger.return_value = MagicMock(
        info=MagicMock(), error=MagicMock(), warning=MagicMock()
    )
    sys.modules["structlog"] = stub_log

# shared.ontology.src.database 存根
_db_stub = _make_stub(
    "shared.ontology.src.database",
    get_db=AsyncMock(),
    get_db_with_tenant=AsyncMock(),
)
sys.modules.setdefault("shared", _make_stub("shared"))
sys.modules.setdefault("shared.ontology", _make_stub("shared.ontology"))
sys.modules.setdefault("shared.ontology.src", _make_stub("shared.ontology.src"))
sys.modules["shared.ontology.src.database"] = _db_stub

# services.channel_pl_calculator 存根
_calc_cls = MagicMock()
sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.channel_pl_calculator"] = _make_stub(
    "services.channel_pl_calculator", ChannelPLCalculator=_calc_cls
)

# sqlalchemy 系列存根（text / AsyncSession / SQLAlchemyError）
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s)
    sa_exc_stub = _make_stub(
        "sqlalchemy.exc", SQLAlchemyError=type("SQLAlchemyError", (Exception,), {})
    )
    sa_ext_stub = _make_stub("sqlalchemy.ext")
    sa_ext_async = _make_stub("sqlalchemy.ext.asyncio", AsyncSession=MagicMock())
    sys.modules["sqlalchemy"] = sa_stub
    sys.modules["sqlalchemy.exc"] = sa_exc_stub
    sys.modules["sqlalchemy.ext"] = sa_ext_stub
    sys.modules["sqlalchemy.ext.asyncio"] = sa_ext_async
else:
    from sqlalchemy.exc import SQLAlchemyError  # noqa: F401  (already present)

# 取得 SQLAlchemyError（从存根或真实库）
SQLAlchemyError = sys.modules["sqlalchemy.exc"].SQLAlchemyError

# ─── 加载被测路由模块 ─────────────────────────────────────────────────────────

from src.api import settlement_routes, payroll_routes  # noqa: E402

# ─── FastAPI TestClient ───────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.testclient import TestClient  # noqa: E402

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
EMPLOYEE_ID = str(uuid.uuid4())
RECORD_ID = str(uuid.uuid4())
BILL_ID = str(uuid.uuid4())
DISCREPANCY_ID = str(uuid.uuid4())

TENANT_HEADER = {"X-Tenant-ID": TENANT_ID}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(settlement_routes.router)
    app.include_router(payroll_routes.router)
    return app


# ─── mock DB session 工厂 ─────────────────────────────────────────────────────


def _mock_db(
    scalar_val: Any = 0,
    first_val: Any = None,
    all_val: list | None = None,
) -> AsyncMock:
    """返回一个模拟 AsyncSession，execute() 返回可链式调用的结果对象。"""
    session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = scalar_val

    items_result = MagicMock()
    mappings_mock = MagicMock()
    mappings_mock.first.return_value = first_val
    mappings_mock.all.return_value = all_val or []
    mappings_mock.fetchall.return_value = all_val or []
    items_result.mappings.return_value = mappings_mock

    # 第一次 execute → count，后续 → items
    session.execute = AsyncMock(side_effect=[count_result, items_result])
    session.commit = AsyncMock()
    return session


# ════════════════════════════════════════════════════════════════════════════
# settlement_routes 测试（5个）
# ════════════════════════════════════════════════════════════════════════════


class TestSettlementRoutes:
    """settlement_routes.py 的 5 个核心测试"""

    # ── 1. POST /bills/import — 正常导入账单 ──────────────────────────────

    def test_import_bill_success(self):
        """正常导入美团账单，应返回 bill_id 和 imported 状态。"""
        bill_row = {
            "id": uuid.UUID(BILL_ID),
            "status": "imported",
            "created_at": datetime(2026, 3, 1),
        }
        mock_sess = AsyncMock()
        exec_result = MagicMock()
        exec_result.mappings.return_value.first.return_value = bill_row
        mock_sess.execute = AsyncMock(return_value=exec_result)
        mock_sess.commit = AsyncMock()

        app = _build_app()
        app.dependency_overrides[settlement_routes._get_tenant_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/finance/bills/import",
                json={
                    "store_id": STORE_ID,
                    "platform": "meituan",
                    "bill_period": "2026-03",
                    "gross_amount_fen": 100000,
                    "commission_fen": 8000,
                    "actual_receive_fen": 92000,
                },
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["bill_id"] == BILL_ID
        assert body["data"]["status"] == "imported"

    # ── 2. POST /bills/import — 非法平台 400 ──────────────────────────────

    def test_import_bill_invalid_platform(self):
        """platform 不合法时应返回 400，不触碰 DB。"""
        app = _build_app()
        app.dependency_overrides[settlement_routes._get_tenant_db] = lambda: AsyncMock()

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/finance/bills/import",
                json={
                    "store_id": STORE_ID,
                    "platform": "wechat_pay",  # 非法
                    "bill_period": "2026-03",
                },
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 400
        assert "platform" in resp.json()["detail"]

    # ── 3. GET /bills/{bill_id} — 账单详情正常返回 ────────────────────────

    def test_get_bill_success(self):
        """按 bill_id 查询存在的账单，应返回完整详情。"""
        bill_row = {
            "id": uuid.UUID(BILL_ID),
            "store_id": uuid.UUID(STORE_ID),
            "platform": "eleme",
            "bill_period": "2026-03",
            "bill_type": "monthly",
            "total_orders": 200,
            "gross_amount_fen": 200000,
            "commission_fen": 16000,
            "subsidy_fen": 0,
            "other_deductions_fen": 0,
            "actual_receive_fen": 184000,
            "bill_file_url": None,
            "raw_data": {},
            "status": "imported",
            "created_at": datetime(2026, 3, 1),
            "updated_at": datetime(2026, 3, 1),
        }
        mock_sess = AsyncMock()
        exec_result = MagicMock()
        exec_result.mappings.return_value.first.return_value = bill_row
        mock_sess.execute = AsyncMock(return_value=exec_result)

        app = _build_app()
        app.dependency_overrides[settlement_routes._get_tenant_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/finance/bills/{BILL_ID}",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["platform"] == "eleme"
        assert body["data"]["id"] == BILL_ID

    # ── 4. GET /bills/{bill_id} — 账单不存在 404 ─────────────────────────

    def test_get_bill_not_found(self):
        """DB 查询返回 None 时，应返回 404。"""
        mock_sess = AsyncMock()
        exec_result = MagicMock()
        exec_result.mappings.return_value.first.return_value = None
        mock_sess.execute = AsyncMock(return_value=exec_result)

        app = _build_app()
        app.dependency_overrides[settlement_routes._get_tenant_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/finance/bills/{BILL_ID}",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    # ── 5. GET /bills — DB 异常时返回 500 ────────────────────────────────

    def test_list_bills_db_error(self):
        """DB execute 抛出异常时，list_bills 应返回 500。"""
        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(side_effect=Exception("connection refused"))

        app = _build_app()
        app.dependency_overrides[settlement_routes._get_tenant_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/finance/bills",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 500
        assert "失败" in resp.json()["detail"]


# ════════════════════════════════════════════════════════════════════════════
# payroll_routes 测试（5个）
# ════════════════════════════════════════════════════════════════════════════


class TestPayrollRoutes:
    """payroll_routes.py 的 5 个核心测试"""

    # ── 6. GET /payroll/summary — 正常查询月度汇总 ────────────────────────

    def test_get_payroll_summary_success(self):
        """正常月度汇总，返回 headcount / gross_total / pending_approval。"""
        summary_row = MagicMock()
        summary_row.__getitem__ = lambda self, k: {
            "headcount": 12,
            "gross_total": 480000,
            "paid_total": 480000,
            "pending_approval": 0,
        }[k]

        mock_sess = AsyncMock()
        exec_result = MagicMock()
        exec_result.mappings.return_value.first.return_value = summary_row
        mock_sess.execute = AsyncMock(return_value=exec_result)

        app = _build_app()
        app.dependency_overrides[payroll_routes.get_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/finance/payroll/summary?month=2026-03",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["headcount"] == 12
        assert body["data"]["gross_total"] == 480000

    # ── 7. POST /payroll/records — 正常创建草稿薪资单 ────────────────────

    def test_create_payroll_record_success(self):
        """创建薪资单成功，返回草稿记录含 gross_pay_fen / net_pay_fen。"""
        new_row = {
            "id": uuid.UUID(RECORD_ID),
            "store_id": uuid.UUID(STORE_ID),
            "employee_id": uuid.UUID(EMPLOYEE_ID),
            "pay_period_start": date(2026, 3, 1),
            "pay_period_end": date(2026, 3, 31),
            "gross_pay_fen": 600000,
            "net_pay_fen": 550000,
            "status": "draft",
            "created_at": datetime(2026, 4, 1),
        }
        # execute 被调用两次：_set_rls + INSERT
        set_rls_result = MagicMock()
        insert_result = MagicMock()
        insert_result.mappings.return_value.first.return_value = new_row

        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(side_effect=[set_rls_result, insert_result])
        mock_sess.commit = AsyncMock()

        app = _build_app()
        app.dependency_overrides[payroll_routes.get_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/finance/payroll/records",
                json={
                    "store_id": STORE_ID,
                    "employee_id": EMPLOYEE_ID,
                    "pay_period_start": "2026-03-01",
                    "pay_period_end": "2026-03-31",
                    "base_pay_fen": 600000,
                    "tax_fen": 50000,
                },
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "draft"
        assert body["data"]["gross_pay_fen"] == 600000

    # ── 8. GET /payroll/records/{record_id} — 薪资单不存在 404 ───────────

    def test_get_payroll_record_not_found(self):
        """薪资单 ID 不存在时应返回 404。"""
        set_rls_result = MagicMock()
        select_result = MagicMock()
        select_result.mappings.return_value.first.return_value = None

        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(side_effect=[set_rls_result, select_result])

        app = _build_app()
        app.dependency_overrides[payroll_routes.get_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/finance/payroll/records/{RECORD_ID}",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    # ── 9. PATCH /payroll/records/{id}/approve — 正常审批通过 ─────────────

    def test_approve_payroll_record_success(self):
        """draft 状态薪资单审批，应返回 approved 状态。"""
        fetch_row = MagicMock()
        fetch_row.__getitem__ = lambda self, k: {"id": RECORD_ID, "status": "draft"}[k]

        updated_row = {
            "id": uuid.UUID(RECORD_ID),
            "status": "approved",
            "approved_at": datetime(2026, 4, 4),
            "updated_at": datetime(2026, 4, 4),
        }
        update_result = MagicMock()
        update_result.mappings.return_value.first.return_value = updated_row

        set_rls_result = MagicMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row

        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(
            side_effect=[set_rls_result, fetch_result, update_result]
        )
        mock_sess.commit = AsyncMock()

        app = _build_app()
        app.dependency_overrides[payroll_routes.get_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/finance/payroll/records/{RECORD_ID}/approve",
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "approved"

    # ── 10. POST /payroll/records — DB 异常时返回 503 ─────────────────────

    def test_create_payroll_record_db_error(self):
        """DB INSERT 抛出 SQLAlchemyError 时，应返回 503 而非 500。"""
        set_rls_result = MagicMock()

        mock_sess = AsyncMock()
        mock_sess.execute = AsyncMock(
            side_effect=[set_rls_result, SQLAlchemyError("DB down")]
        )

        app = _build_app()
        app.dependency_overrides[payroll_routes.get_db] = lambda: mock_sess

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/finance/payroll/records",
                json={
                    "store_id": STORE_ID,
                    "employee_id": EMPLOYEE_ID,
                    "pay_period_start": "2026-03-01",
                    "pay_period_end": "2026-03-31",
                    "base_pay_fen": 600000,
                    "tax_fen": 50000,
                },
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 503
        assert "数据库" in resp.json()["detail"]
