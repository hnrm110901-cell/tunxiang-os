"""
tx-finance 扩展路由测试
覆盖 vat_routes (9 端点) 和 wine_storage_routes (8 端点) 的核心场景。
每个路由文件 5 个测试，共 10 个。

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_finance_extended.py -v
"""
from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 存根工具 ────────────────────────────────────────────────────────────────


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
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s)
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

# WineStorageEventType 占位枚举
_wine_evt = types.SimpleNamespace(STORED="wine.stored", RETRIEVED="wine.retrieved")
_evt_types_stub = _make_stub(
    "shared.events.src.event_types",
    WineStorageEventType=_wine_evt,
)
sys.modules.setdefault("shared.events", _events_stub)
sys.modules.setdefault("shared.events.src", _events_src_stub)
sys.modules["shared.events.src.emitter"] = _emitter_stub
sys.modules["shared.events.src.event_types"] = _evt_types_stub

# ── services.vat_service 存根（VATService + 常量）─────────────────────────────
_VATServiceMock = MagicMock()
_vat_svc_stub = _make_stub(
    "services.vat_service",
    VATService=_VATServiceMock,
    DEFAULT_VAT_RATE=0.06,
    VALID_INVOICE_TYPES=("vat_special", "vat_ordinary", "electronic_vat_special"),
)
sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.vat_service"] = _vat_svc_stub

# ─── 加载被测路由模块 ─────────────────────────────────────────────────────────

from src.api import vat_routes, wine_storage_routes  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
CUSTOMER_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
DECL_ID = str(uuid.uuid4())
INV_ID = str(uuid.uuid4())
STORAGE_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}
TENANT_OP_HDR = {"X-Tenant-ID": TENANT_ID, "X-Operator-ID": str(uuid.uuid4())}


# ─── mock DB session 工厂 ─────────────────────────────────────────────────────


def _mock_db_single(first_val: Any = None) -> AsyncMock:
    """单次 execute 返回 mappings().first() = first_val。"""
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = first_val
    result.mappings.return_value.all.return_value = (
        [first_val] if first_val else []
    )
    result.scalar.return_value = 1
    # 第一次 execute 用于 _set_tenant（如有），后续返回 result
    session.execute = AsyncMock(side_effect=[result, result, result, result])
    session.commit = AsyncMock()
    return session


def _mock_db_raises(exc: Exception) -> AsyncMock:
    """execute 第一次成功（_set_tenant），第二次抛出异常。"""
    session = AsyncMock()
    ok_result = MagicMock()
    ok_result.mappings.return_value.first.return_value = None
    ok_result.scalar.return_value = 0
    session.execute = AsyncMock(side_effect=[ok_result, exc])
    session.commit = AsyncMock()
    return session


# ─── VATService mock 实例工厂 ─────────────────────────────────────────────────


def _build_vat_svc_mock(
    create_decl_val=None,
    list_decl_val=None,
    get_detail_val=None,
    submit_val=None,
    mark_paid_val=None,
    add_inv_val=None,
    list_inv_val=None,
    verify_val=None,
    raise_on: str | None = None,
    raise_exc: Exception | None = None,
):
    """返回一个 VATService 实例 mock，按需配置各方法返回值。"""
    svc = AsyncMock()
    svc.create_declaration = AsyncMock(return_value=create_decl_val or {"id": DECL_ID})
    svc.list_declarations = AsyncMock(return_value=list_decl_val or [])
    svc.get_declaration_detail = AsyncMock(return_value=get_detail_val)
    svc.submit_declaration = AsyncMock(return_value=submit_val or {"id": DECL_ID, "status": "filed"})
    svc.mark_paid = AsyncMock(return_value=mark_paid_val or {"id": DECL_ID, "status": "paid"})
    svc.add_input_invoice = AsyncMock(return_value=add_inv_val or {"invoice_id": INV_ID})
    svc.list_input_invoices = AsyncMock(return_value=list_inv_val or [])
    svc.verify_input_invoice = AsyncMock(return_value=verify_val or {"id": INV_ID, "status": "verified"})

    if raise_on and raise_exc:
        getattr(svc, raise_on).side_effect = raise_exc

    return svc


# ════════════════════════════════════════════════════════════════════════════
# vat_routes 测试（5 个）
# ════════════════════════════════════════════════════════════════════════════


class TestVatRoutes:
    """vat_routes.py 的 5 个核心测试"""

    def _build_app(self, db_session: AsyncMock) -> FastAPI:
        app = FastAPI()
        app.include_router(vat_routes.router)
        app.dependency_overrides[vat_routes._get_tenant_db] = lambda: db_session
        return app

    # ── 1. POST /declarations — 正常创建申报单 ────────────────────────────

    def test_create_declaration_success(self):
        """正常传入门店和期间，应以 201 返回申报单 id。"""
        decl_data = {
            "id": DECL_ID,
            "store_id": STORE_ID,
            "period": "2026-03",
            "status": "draft",
            "output_tax_fen": 50000,
            "payable_tax_fen": 50000,
        }

        mock_svc = _build_vat_svc_mock(create_decl_val=decl_data)

        mock_db = AsyncMock()
        # 第一次 execute → _set_tenant（如有），后续不调用
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        app = self._build_app(mock_db)

        with patch.object(vat_routes, "VATService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/finance/vat/declarations",
                    json={
                        "store_id": STORE_ID,
                        "period": "2026-03",
                        "period_type": "monthly",
                        "tax_rate": 0.06,
                    },
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == DECL_ID

    # ── 2. GET /declarations — 列表正常返回 ──────────────────────────────

    def test_list_declarations_success(self):
        """无过滤条件时应返回 ok=True，data.items 为列表。"""
        items = [
            {"id": DECL_ID, "period": "2026-03", "status": "draft"},
        ]
        mock_svc = _build_vat_svc_mock(list_decl_val=items)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        app = self._build_app(mock_db)

        with patch.object(vat_routes, "VATService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/finance/vat/declarations",
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["id"] == DECL_ID

    # ── 3. GET /declarations/{id} — 申报单不存在 404 ─────────────────────

    def test_get_declaration_not_found(self):
        """申报单 ID 不存在时，应返回 404。"""
        mock_svc = _build_vat_svc_mock(get_detail_val=None)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())

        app = self._build_app(mock_db)

        with patch.object(vat_routes, "VATService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/finance/vat/declarations/{DECL_ID}",
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 404
        assert DECL_ID in resp.json()["detail"]

    # ── 4. POST /declarations/{id}/submit — 业务校验失败 400 ─────────────

    def test_submit_declaration_business_error(self):
        """申报单状态不合法时 VATService.submit_declaration 抛 ValueError，应返回 400。"""
        mock_svc = _build_vat_svc_mock(
            raise_on="submit_declaration",
            raise_exc=ValueError("申报单当前状态 paid 不允许提交"),
        )
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        app = self._build_app(mock_db)

        with patch.object(vat_routes, "VATService", return_value=mock_svc):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/finance/vat/declarations/{DECL_ID}/submit",
                    json={},
                    headers=TENANT_HDR,
                )

        assert resp.status_code == 400
        assert "不允许提交" in resp.json()["detail"]

    # ── 5. GET /tax-rates — 税率参考表正常返回 ───────────────────────────

    def test_get_tax_rates_success(self):
        """税率参考端点无需 DB，应直接返回固定税率列表。"""
        app = FastAPI()
        app.include_router(vat_routes.router)
        # 该端点不依赖 DB，无需 override

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/finance/vat/tax-rates",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        rates = body["data"]["rates"]
        assert len(rates) >= 2
        # 默认税率应为 6%
        assert body["data"]["default_rate"] == pytest.approx(0.06)


# ════════════════════════════════════════════════════════════════════════════
# wine_storage_routes 测试（5 个）
# ════════════════════════════════════════════════════════════════════════════


class TestWineStorageRoutes:
    """wine_storage_routes.py 的 5 个核心测试"""

    def _build_app(self, db_session: AsyncMock) -> FastAPI:
        app = FastAPI()
        app.include_router(wine_storage_routes.router)
        app.dependency_overrides[wine_storage_routes._get_tenant_db] = (
            lambda: db_session
        )
        return app

    def _wine_row(self, storage_id: str | None = None) -> dict:
        now = datetime.now(timezone.utc)
        sid = storage_id or STORAGE_ID
        return {
            "id": uuid.UUID(sid),
            "store_id": uuid.UUID(STORE_ID),
            "customer_id": uuid.UUID(CUSTOMER_ID),
            "source_order_id": uuid.UUID(ORDER_ID),
            "wine_name": "茅台飞天",
            "wine_category": "白酒",
            "quantity": 2.0,
            "original_qty": 2.0,
            "unit": "瓶",
            "estimated_value_fen": 360000,
            "cabinet_position": "A-01",
            "status": "stored",
            "stored_at": now,
            "expires_at": now,
            "operator_id": uuid.UUID(str(uuid.uuid4())),
            "photo_url": None,
            "notes": None,
            "created_at": now,
            "updated_at": now,
        }

    # ── 1. POST / — 正常存酒 201 ─────────────────────────────────────────

    def test_store_wine_success(self):
        """合法存酒请求，应返回 ok=True 与 storage_id。"""
        now = datetime.now(timezone.utc)
        insert_row = {
            "id": uuid.UUID(STORAGE_ID),
            "status": "stored",
            "quantity": 2.0,
            "stored_at": now,
            "expires_at": now,
        }

        # DB 调用顺序：
        #   execute[0] → INSERT INTO biz_wine_storage RETURNING ...
        #   execute[1] → INSERT INTO biz_wine_storage_logs
        insert_result = MagicMock()
        insert_result.mappings.return_value.first.return_value = insert_row

        log_result = MagicMock()
        log_result.mappings.return_value.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[insert_result, log_result])
        mock_db.commit = AsyncMock()

        app = self._build_app(mock_db)

        with patch.object(wine_storage_routes.asyncio, "create_task", return_value=None):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/wine-storage/",
                    json={
                        "store_id": STORE_ID,
                        "customer_id": CUSTOMER_ID,
                        "source_order_id": ORDER_ID,
                        "wine_name": "茅台飞天",
                        "wine_category": "白酒",
                        "quantity": 2.0,
                        "expires_days": 180,
                    },
                    headers=TENANT_OP_HDR,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["storage_id"] == STORAGE_ID
        assert body["data"]["status"] == "stored"

    # ── 2. POST / — 非法 wine_category 400 ───────────────────────────────

    def test_store_wine_invalid_category(self):
        """wine_category 不在允许集合内，应返回 400，不写 DB。"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        app = self._build_app(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/wine-storage/",
                json={
                    "store_id": STORE_ID,
                    "customer_id": CUSTOMER_ID,
                    "source_order_id": ORDER_ID,
                    "wine_name": "可乐",
                    "wine_category": "饮料",  # 非法
                    "quantity": 1.0,
                },
                headers=TENANT_OP_HDR,
            )

        assert resp.status_code == 400
        assert "wine_category" in resp.json()["detail"]
        # 非法校验在 DB 写入前，DB.execute 不应被调用
        mock_db.execute.assert_not_called()

    # ── 3. POST /{id}/retrieve — 记录不存在 404 ──────────────────────────

    def test_retrieve_wine_not_found(self):
        """storage_id 对应记录不存在时，应返回 404。"""
        # execute[0] → SELECT（返回 None → 404）
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=fetch_result)

        app = self._build_app(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/wine-storage/{STORAGE_ID}/retrieve",
                json={"quantity": 1.0},
                headers=TENANT_OP_HDR,
            )

        assert resp.status_code == 404
        assert STORAGE_ID in resp.json()["detail"]

    # ── 4. POST /{id}/retrieve — DB 错误 500 ─────────────────────────────

    def test_retrieve_wine_db_error(self):
        """DB SELECT 抛出通用异常时，应返回 500。"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("connection reset"))

        app = self._build_app(mock_db)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/wine-storage/{STORAGE_ID}/retrieve",
                json={"quantity": 1.0},
                headers=TENANT_OP_HDR,
            )

        assert resp.status_code == 500
        assert "失败" in resp.json()["detail"]

    # ── 5. GET /{id} — 存酒详情正常返回 ─────────────────────────────────

    def test_get_storage_success(self):
        """按 storage_id 查询存在的存酒，应返回 ok=True 与 wine_name。"""
        wine_row = self._wine_row()

        # execute[0] → SELECT biz_wine_storage
        # execute[1] → SELECT biz_wine_storage_logs
        detail_result = MagicMock()
        detail_result.mappings.return_value.first.return_value = wine_row

        logs_result = MagicMock()
        logs_result.mappings.return_value.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[detail_result, logs_result])

        app = self._build_app(mock_db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/wine-storage/{STORAGE_ID}",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["wine_name"] == "茅台飞天"
        assert body["data"]["wine_category"] == "白酒"
        assert body["data"]["logs"] == []
