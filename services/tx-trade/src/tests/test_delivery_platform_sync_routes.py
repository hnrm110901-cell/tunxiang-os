"""外卖平台集成同步路由测试 — delivery_platform_sync_routes.py

覆盖场景（共 7 个）：
1. POST /menu-sync/{platform} — 正常菜单推送到美团，返回 pending 任务
2. POST /menu-sync/{platform} — 不支持的平台返回 400
3. GET  /menu-sync/status     — 菜单同步状态查询，包含未同步平台
4. POST /soldout-sync         — 估清同步到多平台，返回批次信息
5. POST /soldout-sync         — 指定无效平台返回 400
6. GET  /soldout-sync/log     — 估清同步日志分页查询
7. GET  /reconciliation       — 对账汇总查询，返回按平台分组的统计
"""
import os
import sys
import types
import uuid
from collections import namedtuple
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 路径准备 ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(pkg_name: str, pkg_path: str) -> None:
    if pkg_name not in sys.modules:
        mod = types.ModuleType(pkg_name)
        mod.__path__ = [pkg_path]
        mod.__package__ = pkg_name
        sys.modules[pkg_name] = mod


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))

from shared.ontology.src.database import get_db_with_tenant  # noqa: E402
from src.api.delivery_platform_sync_routes import router, _get_db  # type: ignore[import]  # noqa: E402


# ─── 工具 ──────────────────────────────────────────────────────────────────────

TENANT_ID = "test-tenant-sync-001"
_BASE_HEADERS = {"X-Tenant-ID": TENANT_ID}


class _FakeResult:
    """模拟 SQLAlchemy execute 返回的 Result 对象"""

    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar = scalar_value

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar


def _make_row(**kwargs):
    """构造一个 namedtuple 行模拟 SQLAlchemy Row"""
    Row = namedtuple("Row", kwargs.keys())  # noqa: PYI024
    row = Row(**kwargs)
    row._mapping = kwargs  # type: ignore[attr-defined]
    return row


def _make_mock_db(execute_side_effects=None):
    """创建 mock DB session"""
    db = AsyncMock()
    if execute_side_effects:
        db.execute = AsyncMock(side_effect=execute_side_effects)
    else:
        db.execute = AsyncMock(return_value=_FakeResult())
    db.commit = AsyncMock()
    return db


def _make_app(db_mock):
    app = FastAPI()
    app.include_router(router)

    async def _override_db():
        yield db_mock

    app.dependency_overrides[_get_db] = lambda: db_mock
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. POST /menu-sync/meituan — 正常菜单推送
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_menu_sync_meituan_ok():
    """推送 POS 菜单到美团 → 创建 pending 任务"""
    db = _make_mock_db()
    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": "store-001",
        "items": [
            {"dish_id": "d1", "dish_name": "剁椒鱼头", "price_fen": 12800, "category": "湘菜", "is_available": True},
            {"dish_id": "d2", "dish_name": "小炒肉", "price_fen": 4800, "category": "湘菜", "is_available": True},
        ],
        "sync_mode": "full",
    }

    resp = client.post(
        "/api/v1/delivery/platform-sync/menu-sync/meituan",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["platform"] == "meituan"
    assert data["data"]["platform_label"] == "美团外卖"
    assert data["data"]["items_count"] == 2
    assert data["data"]["sync_mode"] == "full"
    assert data["data"]["status"] == "pending"
    assert "task_id" in data["data"]

    # 验证 DB 写入被调用
    db.execute.assert_called_once()
    db.commit.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. POST /menu-sync/{platform} — 不支持的平台
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_menu_sync_unsupported_platform():
    """推送到不支持的平台 → 400"""
    db = _make_mock_db()
    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": "store-001",
        "items": [{"dish_id": "d1", "dish_name": "测试菜", "price_fen": 1000}],
        "sync_mode": "incremental",
    }

    resp = client.post(
        "/api/v1/delivery/platform-sync/menu-sync/kuaishou",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 400
    assert "不支持的平台" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. GET /menu-sync/status — 菜单同步状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_menu_sync_status():
    """查询菜单同步状态 → 返回所有平台（含未同步过的）"""
    now = datetime.now(timezone.utc)
    mt_row = _make_row(
        id=str(uuid.uuid4()),
        store_id="store-001",
        platform="meituan",
        sync_mode="full",
        items_count=10,
        status="success",
        error_message=None,
        created_at=now,
        completed_at=now,
    )

    db = _make_mock_db(execute_side_effects=[_FakeResult(rows=[mt_row])])
    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/delivery/platform-sync/menu-sync/status?store_id=store-001",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    platforms = data["data"]["platforms"]
    # 应该有 3 个平台（1 个已同步 + 2 个 never_synced）
    assert len(platforms) == 3
    platform_map = {p["platform"]: p for p in platforms}
    assert platform_map["meituan"]["status"] == "success"
    assert platform_map["meituan"]["items_count"] == 10
    assert platform_map["eleme"]["status"] == "never_synced"
    assert platform_map["douyin"]["status"] == "never_synced"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. POST /soldout-sync — 估清同步到多平台
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_soldout_sync_multi_platform():
    """估清同步到美团+饿了么 → 每个平台各一条日志"""
    db = _make_mock_db()
    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": "store-001",
        "soldout_items": [
            {"dish_id": "d1", "dish_name": "剁椒鱼头", "reason": "食材售罄"},
            {"dish_id": "d2", "dish_name": "小炒肉", "reason": "临时缺货"},
        ],
        "platforms": ["meituan", "eleme"],
    }

    resp = client.post(
        "/api/v1/delivery/platform-sync/soldout-sync",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total_platforms"] == 2
    assert data["data"]["total_soldout_items"] == 2
    assert "batch_id" in data["data"]

    platforms = data["data"]["platforms"]
    assert len(platforms) == 2
    platform_names = {p["platform"] for p in platforms}
    assert platform_names == {"meituan", "eleme"}
    for p in platforms:
        assert p["status"] == "pending"
        assert p["items_count"] == 2

    # DB 被调用 2 次（每个平台一次 INSERT）+ 1 次 commit
    assert db.execute.call_count == 2
    db.commit.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. POST /soldout-sync — 无效平台
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_soldout_sync_invalid_platform():
    """指定无效平台 → 400"""
    db = _make_mock_db()
    app = _make_app(db)
    client = TestClient(app)

    payload = {
        "store_id": "store-001",
        "soldout_items": [{"dish_id": "d1", "dish_name": "测试菜"}],
        "platforms": ["meituan", "kuaishou"],
    }

    resp = client.post(
        "/api/v1/delivery/platform-sync/soldout-sync",
        json=payload,
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 400
    assert "不支持的平台" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. GET /soldout-sync/log — 估清同步日志
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_soldout_sync_log():
    """估清同步日志查询 → 分页返回"""
    now = datetime.now(timezone.utc)
    log_row = _make_row(
        id=str(uuid.uuid4()),
        store_id="store-001",
        platform="meituan",
        batch_id=str(uuid.uuid4()),
        items_count=3,
        status="success",
        error_message=None,
        created_at=now,
        completed_at=now,
    )

    # 第一次 execute = COUNT(*)，第二次 = 列表查询
    db = _make_mock_db(execute_side_effects=[
        _FakeResult(scalar_value=1),
        _FakeResult(rows=[log_row]),
    ])
    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/delivery/platform-sync/soldout-sync/log?store_id=store-001&platform=meituan&page=1&size=10",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["total"] == 1
    assert len(data["data"]["items"]) == 1
    assert data["data"]["items"][0]["platform"] == "meituan"
    assert data["data"]["items"][0]["platform_label"] == "美团外卖"
    assert data["data"]["page"] == 1
    assert data["data"]["size"] == 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. GET /reconciliation — 对账汇总
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_reconciliation_overview():
    """跨平台对账汇总 → 按平台分组，含差异金额"""
    mt_row = _make_row(
        platform="meituan",
        total_orders=50,
        completed_count=45,
        cancelled_count=3,
        refunded_count=2,
        total_amount_fen=500000,
        total_commission_fen=90000,
        total_merchant_receive_fen=410000,
        total_actual_revenue_fen=408000,
        discrepancy_fen=-2000,
    )
    el_row = _make_row(
        platform="eleme",
        total_orders=30,
        completed_count=28,
        cancelled_count=2,
        refunded_count=0,
        total_amount_fen=300000,
        total_commission_fen=54000,
        total_merchant_receive_fen=246000,
        total_actual_revenue_fen=246000,
        discrepancy_fen=0,
    )

    db = _make_mock_db(execute_side_effects=[_FakeResult(rows=[mt_row, el_row])])
    app = _make_app(db)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/delivery/platform-sync/reconciliation?date_from=2026-04-01&date_to=2026-04-07",
        headers=_BASE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["grand_total_orders"] == 80
    assert data["data"]["grand_total_amount_fen"] == 800000
    assert data["data"]["grand_discrepancy_fen"] == -2000
    assert data["data"]["date_from"] == "2026-04-01"
    assert data["data"]["date_to"] == "2026-04-07"

    by_platform = data["data"]["by_platform"]
    assert len(by_platform) == 2

    mt = next(p for p in by_platform if p["platform"] == "meituan")
    assert mt["total_orders"] == 50
    assert mt["completed_count"] == 45
    assert mt["platform_label"] == "美团外卖"
    assert mt["discrepancy_fen"] == -2000

    el = next(p for p in by_platform if p["platform"] == "eleme")
    assert el["discrepancy_fen"] == 0
