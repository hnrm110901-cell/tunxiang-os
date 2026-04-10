"""意见反馈 API 测试 — api/suggestion_routes.py

覆盖场景：
1.  POST /api/v1/member/suggestions — INSERT 成功 → 200，data 含 id
2.  POST /api/v1/member/suggestions — 缺少 content → 422
3.  POST /api/v1/member/suggestions — mock SQLAlchemyError → 500
4.  GET  /api/v1/member/suggestions — SELECT 返回2条 → 200，data.items 长度=2
5.  GET  /api/v1/member/suggestions — SELECT 返回空 → 200，data.items=[]
6.  GET  /api/v1/member/suggestions?store_id=... — 带 store_id 过滤 → 200

注意：suggestion_routes.py 使用 `from ..db import get_db`（相对导入），
需要将 services/tx-member 目录加入 sys.path 并注入假 src.db 模块，
然后通过 src.api.suggestion_routes 导入。
"""
import os
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# ── sys.path 设置 ─────────────────────────────────────────────────────────────
# 将 services/tx-member 加入路径，使 `src` 成为可识别的包
_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
# _SERVICE_DIR = .../services/tx-member
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# 同时保留 src/ 以便其他辅助模块可按原有方式导入
_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ── 注入假的 src.db 模块（满足 `from ..db import get_db`） ───────────────────
_fake_get_db = MagicMock(name="get_db_placeholder")

if "src.db" not in sys.modules:
    _fake_db_mod = types.ModuleType("src.db")
    _fake_db_mod.get_db = _fake_get_db
    sys.modules["src.db"] = _fake_db_mod
else:
    _fake_get_db = sys.modules["src.db"].get_db

# ── 导入路由（相对导入解析为 src.db） ─────────────────────────────────────────
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

import src.api.suggestion_routes as _suggestion_mod

router = _suggestion_mod.router
get_db = _suggestion_mod.get_db  # 指向 src.db.get_db（我们注入的 mock 占位符）

# ── 常量 ──────────────────────────────────────────────────────────────────────

TENANT = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT}

# ── 工具函数 ──────────────────────────────────────────────────────────────────


def make_mock_db():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_insert_row(suggestion_id: str | None = None):
    """构造模拟 INSERT RETURNING 行"""
    row = MagicMock()
    row.id = uuid.UUID(suggestion_id) if suggestion_id else uuid.uuid4()
    row.created_at = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    return row


def _make_list_row(idx: int = 0, store_id: str | None = None):
    """构造模拟 SELECT 行（list_suggestions 用）"""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.category = "suggestion"
    row.content = f"测试内容{idx}"
    row.contact_phone = None
    row.store_id = uuid.UUID(store_id) if store_id else None
    row.customer_id = None
    row.status = "pending"
    row.reply = None
    row.replied_at = None
    row.created_at = datetime(2026, 4, 4, 12, idx, 0, tzinfo=timezone.utc)
    return row


# ── FastAPI 应用 ───────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)


def _override(db):
    def _dep():
        return db
    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /suggestions — INSERT RETURNING 成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_suggestion_success():
    """INSERT RETURNING 成功 → 200，data 含 id 和 created_at"""
    db = make_mock_db()
    suggestion_id = str(uuid.uuid4())

    # execute 被调用两次：第一次 set_config，第二次 INSERT RETURNING
    insert_result = MagicMock()
    insert_result.fetchone.return_value = _make_insert_row(suggestion_id)
    db.execute = AsyncMock(side_effect=[MagicMock(), insert_result])

    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/suggestions",
        json={"content": "菜品太咸了", "type": "complaint"},
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["id"] == suggestion_id
    assert "created_at" in body["data"]
    db.commit.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /suggestions — 缺少 content → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_suggestion_missing_content():
    """content 为必填字段，缺少时 FastAPI 应返回 422"""
    db = make_mock_db()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/suggestions",
        json={"type": "suggestion"},  # 没有 content
        headers=_HEADERS,
    )

    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /suggestions — SQLAlchemyError → 500
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_suggestion_db_error():
    """INSERT 抛 SQLAlchemyError → HTTP 500，并回滚事务"""
    db = make_mock_db()

    # 第一次 execute → set_config 成功；第二次 execute → 模拟数据库故障
    db.execute = AsyncMock(
        side_effect=[MagicMock(), SQLAlchemyError("connection refused")]
    )

    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        "/api/v1/member/suggestions",
        json={"content": "触发数据库错误"},
        headers=_HEADERS,
    )

    assert resp.status_code == 500
    db.rollback.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /suggestions — SELECT 返回2条
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_suggestions_success():
    """SELECT 返回2行 → 200，data.items 长度=2，total=2"""
    db = make_mock_db()
    rows = [_make_list_row(0), _make_list_row(1)]

    list_result = MagicMock()
    list_result.fetchall.return_value = rows
    db.execute = AsyncMock(side_effect=[MagicMock(), list_result])

    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/suggestions", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /suggestions — SELECT 返回空
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_suggestions_empty():
    """DB 没有记录 → 200，data.items=[]，total=0"""
    db = make_mock_db()

    list_result = MagicMock()
    list_result.fetchall.return_value = []
    db.execute = AsyncMock(side_effect=[MagicMock(), list_result])

    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get("/api/v1/member/suggestions", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /suggestions?store_id=... — 带门店过滤
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_suggestions_with_store_filter():
    """带 store_id query param → 走 store_id 分支，正常返回该门店记录"""
    db = make_mock_db()
    store_id = str(uuid.uuid4())

    row = _make_list_row(0, store_id=store_id)

    list_result = MagicMock()
    list_result.fetchall.return_value = [row]
    db.execute = AsyncMock(side_effect=[MagicMock(), list_result])

    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/suggestions?store_id={store_id}",
        headers=_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["store_id"] == store_id
