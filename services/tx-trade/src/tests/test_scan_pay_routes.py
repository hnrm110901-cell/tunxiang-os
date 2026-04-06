"""扫码付款码收款 API 路由测试 — scan_pay_routes.py DB版

覆盖场景（共 8 个）：
1.  POST /api/v1/payments/scan-pay               — 正常扫码，auth_code 10开头 → channel=wechat
2.  POST /api/v1/payments/scan-pay               — auth_code 25开头 → channel=alipay
3.  POST /api/v1/payments/scan-pay               — amount_fen=0 → 422（Pydantic gt=0 校验）
4.  POST /api/v1/payments/scan-pay               — SQLAlchemyError → 500
5.  GET  /api/v1/payments/scan-pay/{id}/status   — 正常查询，返回 status=pending
6.  GET  /api/v1/payments/scan-pay/{id}/status   — payment_id 不存在 → 404
7.  POST /api/v1/payments/scan-pay/{id}/cancel   — UPDATE RETURNING 成功，返回 status=cancelled
8.  POST /api/v1/payments/scan-pay/{id}/cancel   — UPDATE RETURNING None → 400
"""
import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级 ──────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",     _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

import datetime  # noqa: E402
import pytest    # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from src.api.scan_pay_routes import router  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID  = "11111111-1111-1111-1111-111111111111"
STORE_ID   = "22222222-2222-2222-2222-222222222222"
PAYMENT_ID = "SPY-ABCDEF123456"

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _fake_row(mapping: dict) -> MagicMock:
    """创建带 _mapping 属性的假行对象，支持键式访问。"""
    row = MagicMock()
    row._mapping = mapping
    row.__getitem__ = lambda self, key: self._mapping[key]
    return row


def _mappings_one_or_none(row) -> MagicMock:
    """辅助：result.mappings().one_or_none() = row。"""
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    return result


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。"""
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


def _scan_pay_payload(**kwargs) -> dict:
    """生成扫码支付基准请求体，可用 kwargs 覆盖字段。"""
    base = {
        "auth_code":   "10123456789012345678",  # 微信前缀 10
        "amount_fen":  5800,
        "store_id":    STORE_ID,
        "cashier_id":  "cashier-001",
        "description": "测试支付",
    }
    base.update(kwargs)
    return base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /scan-pay — auth_code 10开头 → channel=wechat
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scan_pay_success():
    """正常扫码（微信前缀10），DB INSERT 成功，返回 payment_id 和 channel=wechat。"""
    db = _make_mock_db()
    # execute 调用两次：set_config + INSERT
    db.execute = AsyncMock(side_effect=[MagicMock(), MagicMock()])

    with patch("src.api.scan_pay_routes.asyncio.create_task"):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            "/api/v1/payments/scan-pay",
            json=_scan_pay_payload(auth_code="10123456789012345678"),
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "payment_id" in data
    assert data["channel"] == "wechat"
    assert data["status"] == "pending"
    assert data["amount_fen"] == 5800
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /scan-pay — auth_code 25开头 → channel=alipay
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scan_pay_alipay_channel():
    """支付宝前缀25，渠道识别为 alipay。"""
    db = _make_mock_db()
    db.execute = AsyncMock(side_effect=[MagicMock(), MagicMock()])

    with patch("src.api.scan_pay_routes.asyncio.create_task"):
        client = TestClient(_make_app_with_db(db))
        resp = client.post(
            "/api/v1/payments/scan-pay",
            json=_scan_pay_payload(auth_code="25987654321098765432"),
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["channel"] == "alipay"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /scan-pay — amount_fen=0 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scan_pay_invalid_amount():
    """amount_fen=0 违反 Pydantic Field(gt=0) 约束，FastAPI 返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/payments/scan-pay",
        json=_scan_pay_payload(amount_fen=0),
        headers=HEADERS,
    )
    assert resp.status_code == 422
    # DB 不应被调用
    db.execute.assert_not_called()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /scan-pay — SQLAlchemyError → 500
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scan_pay_db_error():
    """DB INSERT 抛 SQLAlchemyError，端点返回 500 并回滚事务。"""
    db = _make_mock_db()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),                            # set_config 成功
            SQLAlchemyError("connection lost"),     # INSERT 失败
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/payments/scan-pay",
        json=_scan_pay_payload(),
        headers=HEADERS,
    )

    assert resp.status_code == 500
    db.rollback.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /scan-pay/{id}/status — 正常查询，返回 status=pending
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_payment_status_success():
    """DB 返回支付记录，验证 status=pending 和各字段存在。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    pay_row = _fake_row({
        "payment_id":        PAYMENT_ID,
        "channel":           "wechat",
        "amount_fen":        5800,
        "status":            "pending",
        "merchant_order_id": None,
        "paid_at":           None,
        "created_at":        datetime.datetime(2026, 4, 4, 10, 0, 0),
    })
    select_result = _mappings_one_or_none(pay_row)

    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/payments/scan-pay/{PAYMENT_ID}/status",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["payment_id"] == PAYMENT_ID
    assert data["status"] == "pending"
    assert data["channel"] == "wechat"
    assert data["amount_fen"] == 5800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /scan-pay/{id}/status — payment_id 不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_payment_status_not_found():
    """DB SELECT 返回 None → 404。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    select_result  = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/payments/scan-pay/SPY-NONEXISTENT/status",
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /scan-pay/{id}/cancel — UPDATE RETURNING 成功，返回 status=cancelled
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_payment_success():
    """UPDATE RETURNING 返回行，支付取消成功，响应 status=cancelled。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    cancel_row     = _fake_row({"payment_id": PAYMENT_ID, "status": "cancelled"})
    update_result  = _mappings_one_or_none(cancel_row)

    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/payments/scan-pay/{PAYMENT_ID}/cancel",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["payment_id"] == PAYMENT_ID
    assert body["data"]["status"] == "cancelled"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /scan-pay/{id}/cancel — UPDATE RETURNING None → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_cancel_payment_not_found():
    """UPDATE RETURNING None（记录不存在或已非 pending）→ 400。"""
    db = _make_mock_db()

    set_cfg_result = MagicMock()
    update_result  = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg_result, update_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/payments/scan-pay/SPY-GHOST0000/cancel",
        headers=HEADERS,
    )

    assert resp.status_code == 400
