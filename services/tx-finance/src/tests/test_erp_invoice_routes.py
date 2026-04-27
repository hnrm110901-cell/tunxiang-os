"""
ERP 路由 + 电子发票路由测试

覆盖文件：
  erp_routes.py       — 6 端点（POST /vouchers/purchase/{id}、POST /vouchers/daily-revenue、
                         GET /accounts、GET /health、GET /queue、POST /queue/drain）
  e_invoice_routes.py — 6 端点（POST /request、GET /{id}/status、POST /{id}/retry、
                         POST /{id}/reprint、GET ""、POST /{id}/cancel）

共计 12 个测试用例（每文件 6 个）

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_erp_invoice_routes.py -v
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

# ─── 存根工具 ────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _stub_log = MagicMock()
    _stub_log.get_logger.return_value = MagicMock(info=MagicMock(), error=MagicMock(), warning=MagicMock())
    sys.modules["structlog"] = _stub_log

# ── httpx 存根 ────────────────────────────────────────────────────────────────
if "httpx" not in sys.modules:
    _httpx_stub = _make_stub("httpx")
    _httpx_stub.HTTPError = type("HTTPError", (Exception,), {})
    sys.modules["httpx"] = _httpx_stub

# ── sqlalchemy 系列存根 ───────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s, select=MagicMock())
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
    if "sqlalchemy.select" not in dir(sys.modules["sqlalchemy"]):
        sys.modules["sqlalchemy"].select = MagicMock()

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

# ── shared.adapters.erp.src 存根 ─────────────────────────────────────────────
_ERPType = types.SimpleNamespace(
    KINGDEE="kingdee",
    YONYOU="yonyou",
    value="kingdee",
)


class _FakeERPType:
    KINGDEE = "kingdee"
    YONYOU = "yonyou"

    def __init__(self, v):
        self.value = v

    @classmethod
    def __iter__(cls):
        return iter([cls.KINGDEE, cls.YONYOU])


# 最简单的 ERPType enum 模拟
_ERPTypeEnum = MagicMock()
_ERPTypeEnum.__iter__ = MagicMock(
    return_value=iter(
        [
            MagicMock(value="kingdee"),
            MagicMock(value="yonyou"),
        ]
    )
)

_erp_adapter_mock = AsyncMock()
_erp_adapter_mock.sync_chart_of_accounts = AsyncMock(return_value=[])
_erp_adapter_mock.health_check = AsyncMock(return_value=True)
_erp_adapter_mock.close = AsyncMock()

_get_erp_adapter_mock = MagicMock(return_value=_erp_adapter_mock)

_erp_src_stub = _make_stub(
    "shared.adapters.erp.src",
    ERPType=_ERPTypeEnum,
    get_erp_adapter=_get_erp_adapter_mock,
)
sys.modules.setdefault("shared.adapters", _make_stub("shared.adapters"))
sys.modules.setdefault("shared.adapters.erp", _make_stub("shared.adapters.erp"))
sys.modules["shared.adapters.erp.src"] = _erp_src_stub

# ── YonyouAdapter 存根（供 erp_routes queue 端点使用）──────────────────────────
_yonyou_adapter_mock = MagicMock()
_yonyou_adapter_mock.queue_size = MagicMock(return_value=3)
_yonyou_adapter_mock.drain_queue = AsyncMock(return_value=[])
_yonyou_adapter_mock.close = AsyncMock()

_erp_src_stub.YonyouAdapter = MagicMock(return_value=_yonyou_adapter_mock)
_erp_src_stub.YonyouAdapter.__new__ = MagicMock(return_value=_yonyou_adapter_mock)

# ── services.voucher_generator 存根 ──────────────────────────────────────────
_voucher_mock = MagicMock()
_voucher_mock.voucher_id = str(uuid.uuid4())
_voucher_mock.total_yuan = "1000.00"
_voucher_mock.business_date = date(2026, 4, 1)
_voucher_mock.entries = [MagicMock(), MagicMock()]

_push_result_mock = MagicMock()
_push_result_mock.status = MagicMock(value="success")
_push_result_mock.erp_voucher_id = "KD-001"
_push_result_mock.error_message = None

_VoucherGeneratorMock = MagicMock()
_VoucherGeneratorMock.return_value.generate_from_purchase_order = AsyncMock(return_value=_voucher_mock)
_VoucherGeneratorMock.return_value.generate_from_daily_revenue = AsyncMock(return_value=_voucher_mock)
_VoucherGeneratorMock.return_value.push_to_erp = AsyncMock(return_value=_push_result_mock)

_voucher_gen_stub = _make_stub(
    "services.voucher_generator",
    VoucherGenerator=_VoucherGeneratorMock,
)
sys.modules.setdefault("services", sys.modules.get("services", _make_stub("services")))
sys.modules["services.voucher_generator"] = _voucher_gen_stub

# ── services.invoice_service 存根 ────────────────────────────────────────────
_invoice_mock = MagicMock()
_invoice_mock.id = uuid.uuid4()
_invoice_mock.order_id = uuid.uuid4()
_invoice_mock.status = "issued"
_invoice_mock.invoice_type = "electronic"
_invoice_mock.amount = Decimal("100.00")

_InvoiceNotFoundError = type("InvoiceNotFoundError", (Exception,), {})
_InvoiceAmountMismatchError = type("InvoiceAmountMismatchError", (Exception,), {})
_InvoiceStatusError = type("InvoiceStatusError", (Exception,), {})


def _invoice_to_dict(inv):
    return {
        "id": str(inv.id),
        "order_id": str(inv.order_id),
        "status": inv.status,
        "invoice_type": inv.invoice_type,
        "amount": str(inv.amount),
    }


_InvoiceServiceMock = MagicMock()
_invoice_svc_inst = AsyncMock()
_invoice_svc_inst.request_invoice = AsyncMock(return_value=_invoice_mock)
_invoice_svc_inst.get_invoice_status = AsyncMock(return_value={"id": str(uuid.uuid4()), "status": "issued"})
_invoice_svc_inst.retry_failed = AsyncMock(return_value=_invoice_mock)
_invoice_svc_inst.reprint = AsyncMock(return_value={"pdf_url": "https://example.com/invoice.pdf"})
_invoice_svc_inst.cancel_invoice = AsyncMock(return_value=_invoice_mock)
_InvoiceServiceMock.return_value = _invoice_svc_inst

_invoice_svc_stub = _make_stub(
    "services.invoice_service",
    InvoiceService=_InvoiceServiceMock,
    InvoiceNotFoundError=_InvoiceNotFoundError,
    InvoiceAmountMismatchError=_InvoiceAmountMismatchError,
    InvoiceStatusError=_InvoiceStatusError,
    _invoice_to_dict=_invoice_to_dict,
)
sys.modules["services.invoice_service"] = _invoice_svc_stub

# ── models.invoice 存根 ───────────────────────────────────────────────────────
_Invoice = MagicMock()
_Invoice.order_id = MagicMock()
_Invoice.tenant_id = MagicMock()
_models_stub = _make_stub("models")
_models_invoice_stub = _make_stub("models.invoice", Invoice=_Invoice)
sys.modules.setdefault("models", _models_stub)
sys.modules["models.invoice"] = _models_invoice_stub

# ─── 加载被测路由模块 ─────────────────────────────────────────────────────────
import importlib.util
import pathlib

_api_base = pathlib.Path(__file__).parent.parent / "api"

# 加载 erp_routes
_erp_spec = importlib.util.spec_from_file_location("erp_routes_mod", _api_base / "erp_routes.py")
_erp_routes = importlib.util.module_from_spec(_erp_spec)
_erp_spec.loader.exec_module(_erp_routes)

# 加载 e_invoice_routes
_inv_spec = importlib.util.spec_from_file_location("e_invoice_routes_mod", _api_base / "e_invoice_routes.py")
_e_invoice_routes = importlib.util.module_from_spec(_inv_spec)
_inv_spec.loader.exec_module(_e_invoice_routes)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INVOICE_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}


def _mock_db() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


# ════════════════════════════════════════════════════════════════════════════
# erp_routes 测试（6 个）
# ════════════════════════════════════════════════════════════════════════════


class TestErpRoutes:
    """erp_routes.py 的 6 个测试"""

    def _build_app(self, db_session: AsyncMock) -> FastAPI:
        app = FastAPI()
        app.include_router(_erp_routes.router)
        app.dependency_overrides[_erp_routes._get_tenant_db] = lambda: db_session
        return app

    # ── 1. POST /erp/vouchers/purchase/{order_id} — 正常推送采购凭证 ──────────

    def test_push_purchase_voucher_success(self):
        """正常请求应返回凭证 ID 和推送状态。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_erp_routes, "_generator") as gen_mock:
            gen_mock.generate_from_purchase_order = AsyncMock(return_value=_voucher_mock)
            gen_mock.push_to_erp = AsyncMock(return_value=_push_result_mock)
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/erp/vouchers/purchase/{ORDER_ID}",
                params={"erp_type": "kingdee"},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "voucher_id" in body["data"]
        assert body["data"]["push_status"] == "success"

    # ── 2. POST /erp/vouchers/purchase/{id} — 不支持的 ERP 类型 400 ──────────

    def test_push_purchase_voucher_invalid_erp_type_400(self):
        """传入不支持的 erp_type 应返回 400。"""
        db = _mock_db()
        app = self._build_app(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/erp/vouchers/purchase/{ORDER_ID}",
            params={"erp_type": "sap"},
            headers=TENANT_HDR,
        )
        assert resp.status_code == 400
        assert "ERP" in resp.json()["detail"] or "不支持" in resp.json()["detail"]

    # ── 3. POST /erp/vouchers/daily-revenue — 正常推送日收入凭证 ─────────────

    def test_push_daily_revenue_voucher_success(self):
        """正常请求日收入凭证应返回 entry_count 和推送状态。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_erp_routes, "_generator") as gen_mock:
            gen_mock.generate_from_daily_revenue = AsyncMock(return_value=_voucher_mock)
            gen_mock.push_to_erp = AsyncMock(return_value=_push_result_mock)
            client = TestClient(app)
            resp = client.post(
                "/api/v1/erp/vouchers/daily-revenue",
                params={
                    "erp_type": "kingdee",
                    "store_id": STORE_ID,
                    "business_date": "2026-04-01",
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "entry_count" in body["data"]
        assert body["data"]["erp_type"] == "kingdee"

    # ── 4. GET /erp/accounts — 正常同步科目表 ────────────────────────────────

    def test_sync_chart_of_accounts_success(self):
        """正常同步科目表应返回 count 和 accounts 列表。"""
        mock_account = MagicMock()
        mock_account.model_dump = MagicMock(return_value={"code": "1001", "name": "现金", "type": "asset"})
        adapter = AsyncMock()
        adapter.sync_chart_of_accounts = AsyncMock(return_value=[mock_account])
        adapter.close = AsyncMock()

        with patch.object(_erp_routes, "get_erp_adapter", return_value=adapter):
            app = FastAPI()
            app.include_router(_erp_routes.router)
            client = TestClient(app)
            resp = client.get(
                "/api/v1/erp/accounts",
                params={"erp_type": "kingdee"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["count"] == 1

    # ── 5. GET /erp/health — ERP 连通性检查 ──────────────────────────────────

    def test_erp_health_check_reachable(self):
        """ERP 连通时应返回 reachable=True。"""
        adapter = AsyncMock()
        adapter.health_check = AsyncMock(return_value=True)
        adapter.close = AsyncMock()

        with patch.object(_erp_routes, "get_erp_adapter", return_value=adapter):
            app = FastAPI()
            app.include_router(_erp_routes.router)
            client = TestClient(app)
            resp = client.get("/api/v1/erp/health", params={"erp_type": "yonyou"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["reachable"] is True

    # ── 6. GET /erp/queue — 用友队列大小 ────────────────────────────────────

    def test_get_push_queue_size(self):
        """查询用友离线队列应返回 pending_count。"""
        queue_mock = MagicMock()
        queue_mock.queue_size = MagicMock(return_value=5)

        with patch.object(_erp_routes, "YonyouAdapter") as ya_cls:
            ya_cls.__new__ = MagicMock(return_value=queue_mock)
            app = FastAPI()
            app.include_router(_erp_routes.router)
            client = TestClient(app)
            resp = client.get("/api/v1/erp/queue")

        # queue 端点不需要 tenant header（无 DB 依赖）
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "pending_count" in body["data"]


# ════════════════════════════════════════════════════════════════════════════
# e_invoice_routes 测试（6 个）
# ════════════════════════════════════════════════════════════════════════════


class TestEInvoiceRoutes:
    """e_invoice_routes.py 的 6 个测试"""

    def _build_app(self, db_session: AsyncMock) -> FastAPI:
        app = FastAPI()
        app.include_router(_e_invoice_routes.router)
        app.dependency_overrides[_e_invoice_routes._get_tenant_db] = lambda: db_session
        return app

    # ── 1. POST /request — 正常申请电子发票 ──────────────────────────────────

    def test_request_invoice_success(self):
        """正常申请发票应返回 201 和发票数据。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.request_invoice = AsyncMock(return_value=_invoice_mock)
            client = TestClient(app)
            resp = client.post(
                "/request",
                json={
                    "order_id": str(uuid.uuid4()),
                    "invoice_type": "electronic",
                    "amount": "100.00",
                    "invoice_title": "测试公司",
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "id" in body["data"]

    # ── 2. POST /request — 金额不匹配返回 422 ────────────────────────────────

    def test_request_invoice_amount_mismatch_422(self):
        """开票金额与订单金额不符应返回 422。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.request_invoice = AsyncMock(side_effect=_InvoiceAmountMismatchError("金额不匹配"))
            client = TestClient(app)
            resp = client.post(
                "/request",
                json={
                    "order_id": str(uuid.uuid4()),
                    "invoice_type": "electronic",
                    "amount": "999.00",
                    "order_amount": "100.00",
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 422

    # ── 3. GET /{invoice_id}/status — 查询发票状态 ───────────────────────────

    def test_get_invoice_status_success(self):
        """查询存在的发票状态，应返回 status 字段。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.get_invoice_status = AsyncMock(return_value={"id": INVOICE_ID, "status": "issued"})
            client = TestClient(app)
            resp = client.get(
                f"/{INVOICE_ID}/status",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "issued"

    # ── 4. GET /{invoice_id}/status — 发票不存在时 404 ───────────────────────

    def test_get_invoice_status_not_found_404(self):
        """查询不存在的发票应返回 404。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.get_invoice_status = AsyncMock(side_effect=_InvoiceNotFoundError("发票不存在"))
            client = TestClient(app)
            resp = client.get(
                f"/{INVOICE_ID}/status",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 404

    # ── 5. POST /{invoice_id}/retry — 重试失败发票 ───────────────────────────

    def test_retry_invoice_success(self):
        """重试失败发票应返回更新后的发票数据。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.retry_failed = AsyncMock(return_value=_invoice_mock)
            client = TestClient(app)
            resp = client.post(f"/{INVOICE_ID}/retry", headers=TENANT_HDR)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    # ── 6. POST /{invoice_id}/cancel — 红冲作废发票 ──────────────────────────

    def test_cancel_invoice_success(self):
        """红冲作废已开票发票应返回作废后的数据。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_e_invoice_routes, "_invoice_service") as svc:
            svc.cancel_invoice = AsyncMock(return_value=_invoice_mock)
            client = TestClient(app)
            resp = client.post(
                f"/{INVOICE_ID}/cancel",
                json={"reason": "顾客要求作废"},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
