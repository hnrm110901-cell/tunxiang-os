"""KDS 显示规则配置 API 测试 — kds_display_rules_routes.py

覆盖场景（共 5 个）：
1. GET  /display-rules/{store_id} — 无配置时返回默认值
2. PUT  /display-rules/{store_id} — 首次创建配置
3. PUT  /display-rules/{store_id} — 更新已有配置
4. GET  /display-rules/{store_id} — 缺少 X-Tenant-ID → 400
5. PUT  /display-rules/{store_id} — timeout_warning_seconds 校验失败 → 422
"""
import os
import sys
import types
import json

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
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


# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.kds_display_rules_routes import router  # type: ignore[import]
from shared.ontology.src.database import get_db  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID  = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
HEADERS   = {"X-Tenant-ID": TENANT_ID}


# ─── 测试辅助 ──────────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/kds")
    return app


def _make_mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.execute  = AsyncMock(return_value=MagicMock())
    return db


# ─── 测试用例 ──────────────────────────────────────────────────────────────────

class TestGetDisplayRulesDefault:
    """1. 无配置时返回默认值"""

    def test_returns_defaults_when_no_config(self):
        app = _make_app()
        mock_db = _make_mock_db()

        # execute 返回空结果
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        resp = client.get(f"/api/v1/kds/display-rules/{STORE_ID}", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["timeout_warning_seconds"] == 600
        assert body["data"]["timeout_critical_seconds"] == 900
        assert body["data"]["rush_order_flash"] is True
        assert body["data"]["channel_colors"]["dine_in"] == "#2ECC71"


class TestPutDisplayRulesCreate:
    """2. 首次创建配置"""

    def test_creates_new_config(self):
        app = _make_app()
        mock_db = _make_mock_db()

        # SELECT 返回 None（不存在记录）
        mock_select = MagicMock()
        mock_select.fetchone.return_value = None
        # 第一次 execute = GET（空），第二次 = INSERT
        mock_db.execute = AsyncMock(return_value=mock_select)

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        payload = {
            "timeout_warning_seconds": 300,
            "timeout_warning_color": "#FFAA00",
            "timeout_critical_seconds": 600,
            "timeout_critical_color": "#FF0000",
            "rush_order_flash": False,
            "rush_order_color": "#FF4444",
            "gift_item_color": "#9B59B6",
            "takeout_highlight_color": "#3498DB",
            "channel_colors": {
                "dine_in": "#00FF00",
                "meituan": "#FFD700",
                "eleme": "#0088FF",
                "douyin": "#111111",
            },
        }
        resp = client.put(
            f"/api/v1/kds/display-rules/{STORE_ID}",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["timeout_warning_seconds"] == 300
        assert body["data"]["rush_order_flash"] is False
        # INSERT 被调用
        assert mock_db.execute.await_count >= 2
        assert mock_db.commit.await_count == 1


class TestPutDisplayRulesUpdate:
    """3. 更新已有配置"""

    def test_updates_existing_config(self):
        app = _make_app()
        mock_db = _make_mock_db()

        existing_id = str(uuid.uuid4())
        # SELECT 返回已有记录
        mock_existing = MagicMock()
        mock_existing.fetchone.return_value = (existing_id,)
        mock_db.execute = AsyncMock(return_value=mock_existing)

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        payload = {"timeout_warning_seconds": 120}
        resp = client.put(
            f"/api/v1/kds/display-rules/{STORE_ID}",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["timeout_warning_seconds"] == 120
        assert mock_db.commit.await_count == 1


class TestMissingTenantId:
    """4. 缺少 X-Tenant-ID 返回 400"""

    def test_get_without_tenant_returns_400(self):
        app = _make_app()
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        resp = client.get(f"/api/v1/kds/display-rules/{STORE_ID}")
        assert resp.status_code == 400


class TestValidationError:
    """5. timeout_warning_seconds 超出范围 → 422"""

    def test_invalid_timeout_returns_422(self):
        app = _make_app()
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)

        payload = {"timeout_warning_seconds": 10}  # 最小 60
        resp = client.put(
            f"/api/v1/kds/display-rules/{STORE_ID}",
            json=payload,
            headers=HEADERS,
        )
        assert resp.status_code == 422
