"""
tx-finance 对账与押金路由测试
覆盖：
  - reconciliation_routes (5 个端点): 5 个测试
  - deposit_routes        (8 个端点): 13 个测试
合计: 18 个测试

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_reconciliation_deposit.py -v
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 存根工具 ─────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _stub_log = MagicMock()
    _stub_log.get_logger.return_value = MagicMock(
        info=MagicMock(), error=MagicMock(), warning=MagicMock()
    )
    sys.modules["structlog"] = _stub_log

# ── sqlalchemy 系列存根 ───────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s, update=MagicMock())
    sa_exc_stub = _make_stub(
        "sqlalchemy.exc",
        SQLAlchemyError=type("SQLAlchemyError", (Exception,), {}),
    )
    sa_ext_stub = _make_stub("sqlalchemy.ext")
    sa_ext_async = _make_stub("sqlalchemy.ext.asyncio", AsyncSession=MagicMock())
    sys.modules["sqlalchemy"] = sa_stub
    sys.modules["sqlalchemy.exc"] = sa_exc_stub
    sys.modules["sqlalchemy.ext"] = sa_ext_stub
    sys.modules["sqlalchemy.ext.asyncio"] = sa_ext_async
else:
    from sqlalchemy.exc import SQLAlchemyError  # noqa: F401

SQLAlchemyError = sys.modules["sqlalchemy.exc"].SQLAlchemyError

# ── shared.ontology.src.database 存根 ────────────────────────────────────────
_db_stub = _make_stub(
    "shared.ontology.src.database",
    get_db=AsyncMock(),
    get_db_with_tenant=AsyncMock(),
)
sys.modules.setdefault("shared", _make_stub("shared"))
sys.modules.setdefault("shared.ontology", _make_stub("shared.ontology"))
sys.modules.setdefault("shared.ontology.src", _make_stub("shared.ontology.src"))
sys.modules["shared.ontology.src.database"] = _db_stub

# ── shared.events 存根 ────────────────────────────────────────────────────────
_events_stub = _make_stub("shared.events")
_events_src_stub = _make_stub("shared.events.src")
_emitter_stub = _make_stub("shared.events.src.emitter", emit_event=AsyncMock())

# 事件类型占位
_deposit_evt = types.SimpleNamespace(
    COLLECTED="deposit.collected",
    APPLIED="deposit.applied",
    REFUNDED="deposit.refunded",
    CONVERTED_TO_REVENUE="deposit.converted_to_revenue",
)
_evt_types_stub = _make_stub(
    "shared.events.src.event_types",
    DepositEventType=_deposit_evt,
)
sys.modules.setdefault("shared.events", _events_stub)
sys.modules.setdefault("shared.events.src", _events_src_stub)
sys.modules["shared.events.src.emitter"] = _emitter_stub
sys.modules["shared.events.src.event_types"] = _evt_types_stub

# ── services.three_way_match_engine 存根 ─────────────────────────────────────
_MatchStatus = types.SimpleNamespace(
    MATCHED="matched",
    VARIANCE="variance",
    MISSING="missing",
    RESOLVED="resolved",
)
_PurchaseOrderNotFoundError = type("PurchaseOrderNotFoundError", (Exception,), {})
_ThreeWayMatchError = type("ThreeWayMatchError", (Exception,), {})

_match_engine_mock = MagicMock()
_three_way_stub = _make_stub(
    "services.three_way_match_engine",
    ThreeWayMatchEngine=_match_engine_mock,
    MatchResult=MagicMock(),
    BatchMatchResult=MagicMock(),
    MatchStatus=_MatchStatus,
    PurchaseOrderNotFoundError=_PurchaseOrderNotFoundError,
    ThreeWayMatchError=_ThreeWayMatchError,
    VarianceItem=MagicMock(),
)
sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.three_way_match_engine"] = _three_way_stub

# ── models.three_way_match 存根 ───────────────────────────────────────────────
_models_stub = _make_stub("models")
_match_record_stub = _make_stub(
    "models.three_way_match",
    ThreeWayMatchRecord=MagicMock(),
)
sys.modules.setdefault("models", _models_stub)
sys.modules["models.three_way_match"] = _match_record_stub

# ─── 加载被测路由模块 ─────────────────────────────────────────────────────────

from src.api import reconciliation_routes, deposit_routes  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
PO_ID = str(uuid.uuid4())
VARIANCE_ID = str(uuid.uuid4())
DEPOSIT_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
OPERATOR_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}
OP_HDR = {"X-Tenant-ID": TENANT_ID, "X-Operator-ID": OPERATOR_ID}


# ─── mock DB session 工厂 ─────────────────────────────────────────────────────


def _mock_db_single(first_val: Any = None, scalar_val: Any = 0) -> AsyncMock:
    """多次 execute 均可用，返回 mappings().first()=first_val。"""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = first_val
    result.mappings.return_value.all.return_value = [first_val] if first_val else []
    result.scalar.return_value = scalar_val
    result.scalar_one_or_none.return_value = scalar_val
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def _mock_db_raises(exc: Exception, first_ok: bool = True) -> AsyncMock:
    """第一次 execute 成功（可选），第二次抛出异常。"""
    session = AsyncMock()
    ok_result = MagicMock()
    ok_result.mappings.return_value.first.return_value = None
    ok_result.scalar.return_value = 0
    if first_ok:
        session.execute = AsyncMock(side_effect=[ok_result, exc])
    else:
        session.execute = AsyncMock(side_effect=exc)
    session.commit = AsyncMock()
    return session


# ═══════════════════════════════════════════════════════════════════════════════
#  1. reconciliation_routes 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _make_recon_client():
    app = FastAPI()
    app.include_router(reconciliation_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _build_match_result(po_id: str = PO_ID, status: str = "matched"):
    r = MagicMock()
    r.purchase_order_id = po_id
    r.status = types.SimpleNamespace(value=status)
    r.po_amount_fen = 10000
    r.recv_amount_fen = 10000
    r.inv_amount_fen = 10000
    r.variance_amount_fen = 0
    r.line_variances = []
    r.suggestion = "无差异"
    r.matched_at = datetime.now(timezone.utc)
    return r


def _build_variance_item():
    v = MagicMock()
    v.id = str(uuid.uuid4())
    v.purchase_order_id = str(uuid.uuid4())
    v.supplier_id = str(uuid.uuid4())
    v.status = types.SimpleNamespace(value="variance")
    v.variance_amount_fen = 500
    v.po_amount_fen = 10000
    v.recv_amount_fen = 9500
    v.inv_amount_fen = None
    v.line_variances = []
    v.suggestion = "收货不足"
    v.created_at = datetime.now(timezone.utc)
    return v


class TestReconciliationRoutes:
    """采购三单对账路由测试（5 个测试）"""

    def test_match_single_purchase_order_success(self):
        """POST /reconciliation/match/{po_id} — 正常三单匹配"""
        client = _make_recon_client()
        mock_result = _build_match_result(PO_ID, "matched")
        engine_inst = MagicMock()
        engine_inst.match_purchase_order = AsyncMock(return_value=mock_result)
        mock_db = _mock_db_single()

        with (
            patch.object(reconciliation_routes, "_engine", engine_inst),
            patch.object(
                reconciliation_routes,
                "_get_tenant_db",
                return_value=mock_db,
            ),
        ):
            resp = client.post(
                f"/reconciliation/match/{PO_ID}",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["purchase_order_id"] == PO_ID
        assert data["data"]["status"] == "matched"

    def test_match_single_invalid_uuid(self):
        """POST /reconciliation/match/bad-uuid — 400 格式错误"""
        client = _make_recon_client()
        resp = client.post("/reconciliation/match/not-a-uuid", headers=TENANT_HDR)
        assert resp.status_code == 400

    def test_batch_match_success(self):
        """POST /reconciliation/batch — 批量匹配正常返回"""
        client = _make_recon_client()
        batch = MagicMock()
        batch.tenant_id = TENANT_ID
        batch.total = 3
        batch.matched = 2
        batch.variance_count = 1
        batch.missing_count = 0
        batch.auto_approved = 0
        batch.total_variance_fen = 300
        batch.executed_at = datetime.now(timezone.utc)
        batch.results = [_build_match_result()]

        engine_inst = MagicMock()
        engine_inst.batch_match = AsyncMock(return_value=batch)
        mock_db = _mock_db_single()

        with (
            patch.object(reconciliation_routes, "_engine", engine_inst),
            patch.object(reconciliation_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                "/reconciliation/batch",
                json={"supplier_id": None, "date_from": None, "date_to": None},
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 3
        assert body["data"]["match_rate"] == pytest.approx(2 / 3, rel=1e-3)

    def test_get_variance_report(self):
        """GET /reconciliation/variances — 差异报告"""
        client = _make_recon_client()
        variance = _build_variance_item()
        engine_inst = MagicMock()
        engine_inst.get_variance_report = AsyncMock(return_value=[variance])
        mock_db = _mock_db_single()

        with (
            patch.object(reconciliation_routes, "_engine", engine_inst),
            patch.object(reconciliation_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.get("/reconciliation/variances?days=7", headers=TENANT_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["period_days"] == 7
        assert body["data"]["total_variance_items"] == 1

    def test_auto_approve_small_variances(self):
        """POST /reconciliation/auto-approve — 自动核销小额差异"""
        client = _make_recon_client()
        engine_inst = MagicMock()
        engine_inst.auto_approve_small_variances = AsyncMock(return_value=5)
        mock_db = _mock_db_single()

        with (
            patch.object(reconciliation_routes, "_engine", engine_inst),
            patch.object(reconciliation_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                "/reconciliation/auto-approve",
                json={"max_amount_yuan": 50.0},
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["approved_count"] == 5
        assert body["data"]["max_amount_yuan"] == 50.0


# ═══════════════════════════════════════════════════════════════════════════════
#  2. deposit_routes 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _make_deposit_client():
    app = FastAPI()
    app.include_router(deposit_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _deposit_row(
    deposit_id: str = DEPOSIT_ID,
    status: str = "collected",
    amount_fen: int = 50000,
    applied: int = 0,
    refunded: int = 0,
):
    return {
        "id": uuid.UUID(deposit_id),
        "status": status,
        "amount_fen": amount_fen,
        "applied_amount_fen": applied,
        "refunded_amount_fen": refunded,
        "store_id": uuid.UUID(STORE_ID),
        "customer_id": None,
        "reservation_id": None,
        "order_id": None,
        "payment_method": "wechat",
        "payment_ref": None,
        "collected_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc),
        "operator_id": uuid.UUID(OPERATOR_ID),
        "remark": None,
        "remaining_fen": amount_fen - applied - refunded,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


class TestDepositRoutes:
    """押金管理路由测试（13 个测试）"""

    # ── POST / — 收取押金 ────────────────────────────────────────────────────

    def test_collect_deposit_success(self):
        """POST /api/v1/deposits/ — 正常收取押金"""
        client = _make_deposit_client()
        row = _deposit_row()
        mock_db = _mock_db_single(first_val=row)

        with (
            patch.object(deposit_routes, "_get_tenant_db", return_value=mock_db),
            patch("deposit_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                "/api/v1/deposits/",
                json={
                    "store_id": STORE_ID,
                    "amount_fen": 50000,
                    "payment_method": "wechat",
                    "expires_days": 30,
                },
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "deposit_id" in body["data"]
        assert body["data"]["amount_fen"] == 50000

    def test_collect_deposit_invalid_method(self):
        """POST /api/v1/deposits/ — 400 非法支付方式"""
        client = _make_deposit_client()
        resp = client.post(
            "/api/v1/deposits/",
            json={
                "store_id": STORE_ID,
                "amount_fen": 5000,
                "payment_method": "bitcoin",
                "expires_days": 30,
            },
            headers=OP_HDR,
        )
        assert resp.status_code == 400
        assert "payment_method" in resp.json()["detail"]

    def test_collect_deposit_zero_amount(self):
        """POST /api/v1/deposits/ — 400 金额为0"""
        client = _make_deposit_client()
        resp = client.post(
            "/api/v1/deposits/",
            json={
                "store_id": STORE_ID,
                "amount_fen": 0,
                "payment_method": "cash",
                "expires_days": 30,
            },
            headers=OP_HDR,
        )
        assert resp.status_code == 400

    # ── POST /{id}/apply — 抵扣押金 ─────────────────────────────────────────

    def test_apply_deposit_success(self):
        """POST /api/v1/deposits/{id}/apply — 正常抵扣押金"""
        client = _make_deposit_client()
        order_id = str(uuid.uuid4())
        fetch_row = _deposit_row(amount_fen=50000, applied=0, refunded=0)
        updated_row = _deposit_row(amount_fen=50000, applied=20000, refunded=0, status="partially_applied")

        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        update_result = MagicMock()
        update_result.mappings.return_value.first.return_value = updated_row
        session.execute = AsyncMock(side_effect=[fetch_result, update_result])
        session.commit = AsyncMock()

        with (
            patch.object(deposit_routes, "_get_tenant_db", return_value=session),
            patch("deposit_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/apply",
                json={"order_id": order_id, "apply_amount_fen": 20000},
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "partially_applied"

    def test_apply_deposit_not_found(self):
        """POST /api/v1/deposits/{id}/apply — 404 押金不存在"""
        client = _make_deposit_client()
        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=fetch_result)
        session.commit = AsyncMock()

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/apply",
                json={"order_id": str(uuid.uuid4()), "apply_amount_fen": 1000},
                headers=OP_HDR,
            )
        assert resp.status_code == 404

    def test_apply_deposit_exceed_remaining(self):
        """POST /api/v1/deposits/{id}/apply — 400 抵扣超过余额"""
        client = _make_deposit_client()
        fetch_row = _deposit_row(amount_fen=10000, applied=9000, refunded=0)
        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        session.execute = AsyncMock(return_value=fetch_result)
        session.commit = AsyncMock()

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/apply",
                json={"order_id": str(uuid.uuid4()), "apply_amount_fen": 5000},
                headers=OP_HDR,
            )
        assert resp.status_code == 400

    # ── POST /{id}/refund — 退还押金 ─────────────────────────────────────────

    def test_refund_deposit_success(self):
        """POST /api/v1/deposits/{id}/refund — 正常退还押金"""
        client = _make_deposit_client()
        fetch_row = _deposit_row(amount_fen=50000, applied=0, refunded=0, status="collected")
        updated_row = _deposit_row(amount_fen=50000, applied=0, refunded=50000, status="refunded")

        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        update_result = MagicMock()
        update_result.mappings.return_value.first.return_value = updated_row
        session.execute = AsyncMock(side_effect=[fetch_result, update_result])
        session.commit = AsyncMock()

        with (
            patch.object(deposit_routes, "_get_tenant_db", return_value=session),
            patch("deposit_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/refund",
                json={"refund_amount_fen": 50000},
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "refunded"

    def test_refund_deposit_conflict_status(self):
        """POST /api/v1/deposits/{id}/refund — 409 已退还不能再退"""
        client = _make_deposit_client()
        fetch_row = _deposit_row(status="refunded")
        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        session.execute = AsyncMock(return_value=fetch_result)
        session.commit = AsyncMock()

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/refund",
                json={"refund_amount_fen": 100},
                headers=OP_HDR,
            )
        assert resp.status_code == 409

    # ── POST /{id}/convert — 押金转收入 ──────────────────────────────────────

    def test_convert_deposit_success(self):
        """POST /api/v1/deposits/{id}/convert — 正常转收入"""
        client = _make_deposit_client()
        fetch_row = _deposit_row(amount_fen=50000, applied=10000, refunded=0, status="partially_applied")
        updated_row = _deposit_row(amount_fen=50000, applied=10000, refunded=0, status="converted")

        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        update_result = MagicMock()
        update_result.mappings.return_value.first.return_value = updated_row
        session.execute = AsyncMock(side_effect=[fetch_result, update_result])
        session.commit = AsyncMock()

        with (
            patch.object(deposit_routes, "_get_tenant_db", return_value=session),
            patch("deposit_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                f"/api/v1/deposits/{DEPOSIT_ID}/convert",
                json={},
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "converted"
        assert body["data"]["converted_amount_fen"] == 40000  # 50000 - 10000

    # ── GET /{id} — 押金详情 ──────────────────────────────────────────────────

    def test_get_deposit_success(self):
        """GET /api/v1/deposits/{id} — 正常获取押金详情"""
        client = _make_deposit_client()
        row = _deposit_row()
        session = _mock_db_single(first_val=row)

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.get(f"/api/v1/deposits/{DEPOSIT_ID}", headers=TENANT_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["amount_fen"] == 50000

    def test_get_deposit_not_found(self):
        """GET /api/v1/deposits/{id} — 404 不存在"""
        client = _make_deposit_client()
        session = _mock_db_single(first_val=None)

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.get(f"/api/v1/deposits/{DEPOSIT_ID}", headers=TENANT_HDR)
        assert resp.status_code == 404

    # ── GET /store/{store_id} — 门店押金列表 ─────────────────────────────────

    def test_list_by_store_success(self):
        """GET /api/v1/deposits/store/{store_id} — 正常返回列表"""
        client = _make_deposit_client()
        row = _deposit_row()
        session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        items_result = MagicMock()
        items_result.mappings.return_value.all.return_value = [row]
        session.execute = AsyncMock(side_effect=[count_result, items_result])
        session.commit = AsyncMock()

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/deposits/store/{STORE_ID}?page=1&size=20",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert len(body["data"]["items"]) == 1

    # ── GET /report/ledger — 押金台账 ────────────────────────────────────────

    def test_ledger_report_success(self):
        """GET /api/v1/deposits/report/ledger — 正常台账报表"""
        client = _make_deposit_client()
        ledger_row = {
            "total_count": 5,
            "total_collected_fen": 250000,
            "total_applied_fen": 50000,
            "total_refunded_fen": 30000,
            "total_converted_fen": 10000,
            "total_outstanding_fen": 160000,
        }
        session = _mock_db_single(first_val=ledger_row)

        with patch.object(deposit_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/deposits/report/ledger?store_id={STORE_ID}&start_date=2026-01-01&end_date=2026-03-31",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_collected_fen"] == 250000
