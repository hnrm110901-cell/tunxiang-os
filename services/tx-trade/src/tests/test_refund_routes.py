"""退款申请 API 路由测试 — refund_routes.py DB版

覆盖场景（共 6 个）：
1. POST /api/v1/trade/refunds         — submit_refund 正常提交，返回 refund_id
2. POST /api/v1/trade/refunds         — refund_amount_fen=0 → 400
3. POST /api/v1/trade/refunds         — DB 抛 SQLAlchemyError → 500
4. GET  /api/v1/trade/refunds/{id}    — get_refund_status 正常查询，status=pending
5. GET  /api/v1/trade/refunds/{id}    — 退款申请不存在 → 404
6. GET  /api/v1/trade/refunds/{id}    — refund_id 非 UUID 格式 → 400
"""
import datetime
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


_ensure_pkg("src",      _SRC_DIR)
_ensure_pkg("src.api",  os.path.join(_SRC_DIR, "api"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

import pytest  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from src.api.refund_routes import router as refund_router  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID  = "11111111-1111-1111-1111-111111111111"
ORDER_ID   = "33333333-3333-3333-3333-333333333333"
REFUND_ID  = "44444444-4444-4444-4444-444444444444"

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _fake_row(mapping: dict) -> MagicMock:
    """创建带 _mapping 属性的假行对象，同时支持键式访问。"""
    row = MagicMock()
    row._mapping = mapping
    row.__getitem__ = lambda self, key: self._mapping[key]
    return row


def _mappings_one(row) -> MagicMock:
    """辅助：result.mappings().one() = row。"""
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    return result


def _mappings_one_or_none(row) -> MagicMock:
    """辅助：result.mappings().one_or_none() = row。"""
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    return result


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。
    refund_router 自带 prefix=/api/v1/trade/refunds，不需额外注入。
    """
    app = FastAPI()
    app.include_router(refund_router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


def _submit_payload(**kwargs) -> dict:
    """生成提交退款的基准请求体，可用 kwargs 覆盖字段。"""
    base = {
        "order_id":          ORDER_ID,
        "refund_type":       "partial",
        "refund_amount_fen": 2000,
        "reasons":           ["菜品与描述不符"],
        "description":       "牛肉面里没有牛肉",
        "items":             [],
        "image_urls":        [],
    }
    base.update(kwargs)
    return base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /api/v1/trade/refunds — 正常提交退款申请
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_submit_refund_success():
    """正常提交退款，DB INSERT 返回新 refund_id 和 created_at。"""
    db = _make_mock_db()

    set_cfg   = MagicMock()
    new_row   = _fake_row({
        "id":         REFUND_ID,
        "created_at": datetime.datetime(2026, 4, 4, 12, 0, 0),
    })
    insert_result = _mappings_one(new_row)

    db.execute = AsyncMock(side_effect=[set_cfg, insert_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/trade/refunds",
        json=_submit_payload(),
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "refund_id" in data["data"]
    assert data["data"]["status"] == "pending"
    assert data["data"]["refund_amount_fen"] == 2000
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /api/v1/trade/refunds — refund_amount_fen=0 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_submit_refund_invalid_amount():
    """退款金额为 0 时路由层应提前校验并返回 400。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/trade/refunds",
        json=_submit_payload(refund_amount_fen=0),
        headers=HEADERS,
    )
    assert resp.status_code == 400
    # DB 不应被调用
    db.execute.assert_not_called()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /api/v1/trade/refunds — DB 抛 SQLAlchemyError → 500
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_submit_refund_db_error():
    """DB 写入失败时应回滚并返回 500。"""
    db = _make_mock_db()

    set_cfg = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            set_cfg,
            SQLAlchemyError("connection lost"),
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        "/api/v1/trade/refunds",
        json=_submit_payload(),
        headers=HEADERS,
    )

    assert resp.status_code == 500
    db.rollback.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /api/v1/trade/refunds/{id} — 正常查询，status=pending
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_refund_status_success():
    """存在的退款申请应返回完整字段，status=pending。"""
    db = _make_mock_db()

    set_cfg = MagicMock()
    row     = _fake_row({
        "id":                REFUND_ID,
        "order_id":          ORDER_ID,
        "status":            "pending",
        "refund_amount_fen": 2000,
        "refund_type":       "partial",
        "review_note":       None,
        "reviewed_at":       None,
        "created_at":        datetime.datetime(2026, 4, 4, 12, 0, 0),
    })
    select_result = _mappings_one_or_none(row)

    db.execute = AsyncMock(side_effect=[set_cfg, select_result])

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/trade/refunds/{REFUND_ID}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "pending"
    assert data["data"]["refund_amount_fen"] == 2000
    assert data["data"]["refund_id"] == REFUND_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /api/v1/trade/refunds/{id} — 退款申请不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_refund_status_not_found():
    """查询不存在的退款申请时应返回 404。"""
    db = _make_mock_db()

    set_cfg       = MagicMock()
    select_result = _mappings_one_or_none(None)

    db.execute = AsyncMock(side_effect=[set_cfg, select_result])

    # 使用一个合法但不存在的 UUID
    nonexistent = "99999999-9999-9999-9999-999999999999"
    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/trade/refunds/{nonexistent}",
        headers=HEADERS,
    )

    assert resp.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /api/v1/trade/refunds/{id} — 非 UUID 格式 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_refund_status_invalid_uuid():
    """refund_id 不是合法 UUID 格式时路由应返回 400。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        "/api/v1/trade/refunds/not-a-valid-uuid",
        headers=HEADERS,
    )
    assert resp.status_code == 400
    # UUID 校验在 DB 调用前，DB 不应被调用
    db.execute.assert_not_called()
