"""
分账引擎路由测试 — split_routes.py（8 个端点）

覆盖：
  POST   /api/v1/finance/splits/rules           创建/更新分润规则
  GET    /api/v1/finance/splits/rules           查询规则列表
  DELETE /api/v1/finance/splits/rules/{id}      停用规则
  POST   /api/v1/finance/splits/execute         执行分账
  POST   /api/v1/finance/splits/settle          批量结算
  GET    /api/v1/finance/splits/transactions    分润流水
  GET    /api/v1/finance/splits/settlement      分账汇总
  POST   /api/v1/finance/splits/channel-notify  通道异步通知

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_split_routes.py -v
"""
from __future__ import annotations

import sys
import types
import uuid
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

# ── services.split_engine 存根 ───────────────────────────────────────────────
_SplitEngineMock = MagicMock()
_split_engine_stub = _make_stub(
    "services.split_engine",
    SplitEngine=_SplitEngineMock,
    RECIPIENT_TYPES={"brand", "franchise", "supplier", "platform", "custom"},
    SPLIT_METHODS={"percentage", "fixed_fen"},
)
sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.split_engine"] = _split_engine_stub

# ── services.split_notify_security 存根 ──────────────────────────────────────
_split_notify_stub = _make_stub(
    "services.split_notify_security",
    verify_split_channel_notify_signature=MagicMock(return_value=None),
)
sys.modules["services.split_notify_security"] = _split_notify_stub

# ─── 加载被测路由模块 (必须在存根注册后) ──────────────────────────────────────
# 修正导入路径: src.api.split_routes 通过相对导入引用 ..services.split_engine
# 需要确保 src 包结构正确
sys.modules.setdefault("src", _make_stub("src"))
sys.modules.setdefault("src.api", _make_stub("src.api"))
sys.modules.setdefault("src.services", _make_stub("src.services"))
sys.modules["src.services.split_engine"] = _split_engine_stub
sys.modules["src.services.split_notify_security"] = _split_notify_stub

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 直接导入，避免相对导入问题
import importlib.util, pathlib

_routes_path = pathlib.Path(__file__).parent.parent / "api" / "split_routes.py"
_spec = importlib.util.spec_from_file_location("split_routes_mod", _routes_path)
_split_routes = importlib.util.module_from_spec(_spec)

# 在 sys.modules 中注册路由内部导入所需的模块
sys.modules["src.api.split_routes"] = _split_routes
_spec.loader.exec_module(_split_routes)

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
RECORD_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}


# ─── DB mock 工厂 ─────────────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    """返回一个简单的 AsyncSession mock"""
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


# ─── SplitEngine mock 工厂 ───────────────────────────────────────────────────


def _build_engine_mock(
    upsert_rule_val=None,
    list_rules_val=None,
    deactivate_rule_val=True,
    execute_split_val=None,
    settle_records_val=2,
    list_split_records_val=None,
    get_settlement_summary_val=None,
    apply_channel_notification_val=None,
):
    eng = AsyncMock()
    eng.upsert_rule = AsyncMock(
        return_value=upsert_rule_val or {"id": RULE_ID, "name": "测试规则", "is_active": True}
    )
    eng.list_rules = AsyncMock(
        return_value=list_rules_val or [{"id": RULE_ID, "name": "测试规则"}]
    )
    eng.deactivate_rule = AsyncMock(return_value=deactivate_rule_val)
    eng.execute_split = AsyncMock(
        return_value=execute_split_val
        or [{"id": RECORD_ID, "split_amount_fen": 500, "recipient_type": "brand"}]
    )
    eng.settle_records = AsyncMock(return_value=settle_records_val)
    eng.list_split_records = AsyncMock(
        return_value=list_split_records_val or {"items": [], "total": 0}
    )
    eng.get_settlement_summary = AsyncMock(
        return_value=get_settlement_summary_val or {"items": [], "total_fen": 0}
    )
    eng.apply_channel_notification = AsyncMock(
        return_value=apply_channel_notification_val
        or {"updated": 1, "skipped": 0}
    )
    return eng


# ════════════════════════════════════════════════════════════════════════════
# split_routes 测试（12 个）
# ════════════════════════════════════════════════════════════════════════════


class TestSplitRoutes:
    """split_routes.py 的 12 个测试"""

    def _build_app(self, db_session: AsyncMock, engine_mock=None) -> FastAPI:
        app = FastAPI()
        app.include_router(_split_routes.router)
        app.dependency_overrides[_split_routes._get_tenant_db] = lambda: db_session
        # SplitEngine 是在每个路由函数内部实例化的，通过 patch 控制
        return app

    # ── 1. POST /rules — 正常创建百分比分润规则 ───────────────────────────────

    def test_upsert_rule_percentage_success(self):
        """正常传入 percentage 规则，应以 201 返回规则数据。"""
        rule_data = {
            "id": RULE_ID,
            "name": "品牌分润5%",
            "is_active": True,
            "split_method": "percentage",
            "percentage": 0.05,
        }
        eng_mock = _build_engine_mock(upsert_rule_val=rule_data)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/splits/rules",
                json={
                    "name": "品牌分润5%",
                    "recipient_type": "brand",
                    "split_method": "percentage",
                    "percentage": 0.05,
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == RULE_ID

    # ── 2. POST /rules — 缺少 percentage 字段时 400 ──────────────────────────

    def test_upsert_rule_missing_percentage_400(self):
        """split_method=percentage 但未提供 percentage，应返回 400。"""
        db = _mock_db()
        app = self._build_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/finance/splits/rules",
            json={
                "name": "无效规则",
                "recipient_type": "brand",
                "split_method": "percentage",
                # 未提供 percentage
            },
            headers=TENANT_HDR,
        )
        assert resp.status_code == 400
        assert "percentage" in resp.json()["detail"]

    # ── 3. POST /rules — fixed_fen 缺少 fixed_fen 字段时 400 ─────────────────

    def test_upsert_rule_missing_fixed_fen_400(self):
        """split_method=fixed_fen 但未提供 fixed_fen，应返回 400。"""
        db = _mock_db()
        app = self._build_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/finance/splits/rules",
            json={
                "name": "固定分润",
                "recipient_type": "supplier",
                "split_method": "fixed_fen",
                # 未提供 fixed_fen
            },
            headers=TENANT_HDR,
        )
        assert resp.status_code == 400
        assert "fixed_fen" in resp.json()["detail"]

    # ── 4. GET /rules — 正常返回规则列表 ──────────────────────────────────────

    def test_list_rules_success(self):
        """查询规则列表，应返回包含 items 和 total 的数据结构。"""
        rules = [{"id": RULE_ID, "name": "规则A"}, {"id": str(uuid.uuid4()), "name": "规则B"}]
        eng_mock = _build_engine_mock(list_rules_val=rules)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.get("/api/v1/finance/splits/rules", headers=TENANT_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 2
        assert len(body["data"]["items"]) == 2

    # ── 5. DELETE /rules/{rule_id} — 正常停用规则 ────────────────────────────

    def test_deactivate_rule_success(self):
        """停用存在的规则，应返回 is_active=False。"""
        eng_mock = _build_engine_mock(deactivate_rule_val=True)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.delete(
                f"/api/v1/finance/splits/rules/{RULE_ID}",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["is_active"] is False

    # ── 6. DELETE /rules/{rule_id} — 不存在时 404 ────────────────────────────

    def test_deactivate_rule_not_found_404(self):
        """停用不存在的规则，应返回 404。"""
        eng_mock = _build_engine_mock(deactivate_rule_val=False)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.delete(
                f"/api/v1/finance/splits/rules/{RULE_ID}",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 404

    # ── 7. POST /execute — 正常执行分账 ──────────────────────────────────────

    def test_execute_split_success(self):
        """执行分账后应返回分润记录汇总。"""
        records = [
            {"id": RECORD_ID, "split_amount_fen": 500, "recipient_type": "brand"},
            {"id": str(uuid.uuid4()), "split_amount_fen": 300, "recipient_type": "platform"},
        ]
        eng_mock = _build_engine_mock(execute_split_val=records)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/splits/execute",
                json={
                    "order_id": ORDER_ID,
                    "store_id": STORE_ID,
                    "gross_amount_fen": 10000,
                    "channel": "dine_in",
                    "transaction_date": "2026-04-01",
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_split_fen"] == 800
        assert body["data"]["record_count"] == 2
        assert body["data"]["order_id"] == ORDER_ID

    # ── 8. POST /settle — 批量结算 ───────────────────────────────────────────

    def test_settle_records_success(self):
        """批量结算应返回 requested 和 settled 计数。"""
        eng_mock = _build_engine_mock(settle_records_val=2)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/splits/settle",
                json={"record_ids": [RECORD_ID, str(uuid.uuid4())]},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["requested"] == 2
        assert body["data"]["settled"] == 2

    # ── 9. GET /transactions — 查询分润流水 ──────────────────────────────────

    def test_list_transactions_success(self):
        """查询分润流水，应返回分页结构。"""
        result = {"items": [{"id": RECORD_ID, "split_amount_fen": 500}], "total": 1}
        eng_mock = _build_engine_mock(list_split_records_val=result)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/splits/transactions",
                params={"order_id": ORDER_ID, "page": 1, "size": 20},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["page"] == 1

    # ── 10. GET /settlement — 分账汇总 ──────────────────────────────────────

    def test_get_settlement_summary_success(self):
        """分账汇总应返回按收款方聚合数据。"""
        summary = {"items": [{"recipient_type": "brand", "total_fen": 5000}], "total_fen": 5000}
        eng_mock = _build_engine_mock(get_settlement_summary_val=summary)
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/splits/settlement",
                params={"start_date": "2026-04-01", "end_date": "2026-04-30"},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_fen"] == 5000

    # ── 11. POST /channel-notify — 通道通知成功结算 ──────────────────────────

    def test_channel_notify_settled_success(self):
        """通道通知结算成功，应返回 updated 计数。"""
        eng_mock = _build_engine_mock(apply_channel_notification_val={"updated": 1, "skipped": 0})
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_split_routes, "SplitEngine", return_value=eng_mock):
            with patch.object(
                _split_routes, "verify_split_channel_notify_signature", return_value=None
            ):
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/finance/splits/channel-notify",
                    json={
                        "idempotency_key": "idem-key-12345678",
                        "items": [
                            {
                                "record_id": RECORD_ID,
                                "outcome": "settled",
                                "channel_transaction_id": "wx_txn_001",
                            }
                        ],
                    },
                    headers=TENANT_HDR,
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["updated"] == 1

    # ── 12. POST /channel-notify — 签名验证失败返回 401 ──────────────────────

    def test_channel_notify_signature_fail_401(self):
        """签名验证失败时应返回 401。"""
        db = _mock_db()
        app = self._build_app(db)

        with patch.object(
            _split_routes,
            "verify_split_channel_notify_signature",
            side_effect=ValueError("签名不匹配"),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/splits/channel-notify",
                json={
                    "idempotency_key": "idem-key-12345678",
                    "items": [{"record_id": RECORD_ID, "outcome": "settled"}],
                },
                headers={**TENANT_HDR, "X-Split-Notify-Signature": "bad_sig"},
            )
        assert resp.status_code == 401
