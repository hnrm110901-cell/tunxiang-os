"""KDS 预制量推荐 + 沽清同步路由测试

覆盖场景（共 12 个）：

kds_prep_routes（使用 src.db.get_db）：
1.  GET  /api/v1/kds/prep/recommendations?store_id=xxx          — 正常返回全店推荐
2.  GET  /api/v1/kds/prep/recommendations?store_id=xxx&dept_id= — 按档口过滤
3.  GET  /api/v1/kds/prep/recommendations?store_id=xxx&target_date= — 指定目标日期
4.  GET  /api/v1/kds/prep/recommendations                       — 缺少 X-Tenant-ID → 422
5.  GET  /api/v1/kds/prep/recommendations                       — 缺少 store_id → 422

kds_soldout_routes（使用 src.db.get_db）：
6.  POST /api/v1/kds/soldout                                    — 标记沽清成功
7.  POST /api/v1/kds/soldout                                    — ValueError → 400
8.  DELETE /api/v1/kds/soldout                                  — 恢复沽清成功
9.  DELETE /api/v1/kds/soldout                                  — ValueError → 400
10. GET  /api/v1/kds/soldout?store_id=xxx                       — 查询沽清列表（有数据）
11. GET  /api/v1/kds/soldout?store_id=xxx                       — 查询沽清列表（空列表）
12. POST /api/v1/kds/soldout                                    — 缺少必填字段 → 422
"""
import os
import sys
import types

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


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models",   os.path.join(_SRC_DIR, "models"))


# ─── stub helper ──────────────────────────────────────────────────────────────

def _stub_module(full_name: str, **attrs):
    """注入一个最小存根模块，避免真实导入失败。"""
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# ─── stub src.db（kds_prep_routes / kds_soldout_routes 使用 from ..db import get_db）
_db_mod = _stub_module("src.db", get_db=lambda: None)

# ─── stub kds_prep 服务层 ─────────────────────────────────────────────────────
_stub_module(
    "src.services.kds_prep_recommendation",
    get_prep_recommendations=None,
)

# ─── stub kds_soldout 服务层 ──────────────────────────────────────────────────
_stub_module(
    "src.services.kds_soldout_sync",
    mark_soldout=None,
    restore_soldout=None,
    get_active_soldout=None,
)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import json as _json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.kds_prep_routes import router as prep_router          # type: ignore[import]
from src.api.kds_soldout_routes import router as soldout_router    # type: ignore[import]
from src.db import get_db as src_get_db                            # type: ignore[import]


# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID  = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEPT_ID   = "cccccccc-cccc-cccc-cccc-cccccccccccc"
DISH_ID   = "dddddddd-dddd-dddd-dddd-dddddddddddd"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.execute  = AsyncMock(return_value=MagicMock())
    return db


def _make_prep_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(prep_router)

    async def _override():
        yield db

    app.dependency_overrides[src_get_db] = _override
    return app


def _make_soldout_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(soldout_router)

    async def _override():
        yield db

    app.dependency_overrides[src_get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /recommendations?store_id=xxx — 正常返回全店推荐
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_prep_recommendations_all_depts():
    """全店备料推荐：不传 dept_id，返回所有档口所有菜品的推荐份数。"""
    db = _make_mock_db()

    fake_items = [
        {"dish_id": DISH_ID, "dish_name": "红烧肉", "dept_id": DEPT_ID, "recommended_qty": 12},
        {"dish_id": str(uuid.uuid4()), "dish_name": "宫保鸡丁", "dept_id": DEPT_ID, "recommended_qty": 8},
    ]

    with patch(
        "src.api.kds_prep_routes.get_prep_recommendations",
        new=AsyncMock(return_value=fake_items),
    ):
        client = TestClient(_make_prep_app(db))
        resp = client.get(
            "/api/v1/kds/prep/recommendations",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2
    assert body["data"]["items"][0]["dish_name"] == "红烧肉"
    assert body["data"]["items"][0]["recommended_qty"] == 12


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /recommendations?store_id=xxx&dept_id=xxx — 按档口过滤
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_prep_recommendations_filtered_by_dept():
    """按档口过滤备料推荐：传入 dept_id，服务层接收到正确参数。"""
    db = _make_mock_db()

    fake_items = [
        {"dish_id": DISH_ID, "dish_name": "烤鸭", "dept_id": DEPT_ID, "recommended_qty": 5},
    ]

    captured_kwargs = {}

    async def _fake_get_recommendations(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_items

    with patch(
        "src.api.kds_prep_routes.get_prep_recommendations",
        new=_fake_get_recommendations,
    ):
        client = TestClient(_make_prep_app(db))
        resp = client.get(
            "/api/v1/kds/prep/recommendations",
            params={"store_id": STORE_ID, "dept_id": DEPT_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] == 1
    # 验证服务层收到了正确的 dept_id 参数
    assert captured_kwargs.get("dept_id") == DEPT_ID
    assert captured_kwargs.get("tenant_id") == TENANT_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /recommendations?store_id=xxx&target_date=xxx — 指定目标日期
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_prep_recommendations_with_target_date():
    """指定目标日期：返回的 target_date 与请求参数一致。"""
    db = _make_mock_db()

    target = "2026-04-06"
    fake_items = [
        {"dish_id": DISH_ID, "dish_name": "清蒸鱼", "dept_id": DEPT_ID, "recommended_qty": 3},
    ]

    with patch(
        "src.api.kds_prep_routes.get_prep_recommendations",
        new=AsyncMock(return_value=fake_items),
    ):
        client = TestClient(_make_prep_app(db))
        resp = client.get(
            "/api/v1/kds/prep/recommendations",
            params={"store_id": STORE_ID, "target_date": target},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["target_date"] == target


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /recommendations — 缺少 X-Tenant-ID → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_prep_recommendations_missing_tenant_id():
    """X-Tenant-ID 是必填 Header（alias），缺少时 FastAPI 返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_prep_app(db))

    resp = client.get(
        "/api/v1/kds/prep/recommendations",
        params={"store_id": STORE_ID},
        # 不传 headers
    )

    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /recommendations — 缺少 store_id → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_prep_recommendations_missing_store_id():
    """store_id 是必填查询参数，缺少时 FastAPI 返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_prep_app(db))

    resp = client.get(
        "/api/v1/kds/prep/recommendations",
        headers=HEADERS,
        # 不传 store_id
    )

    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /soldout — 标记沽清成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mark_soldout_success():
    """标记菜品沽清：返回 ok=True 及 soldout_id、synced_at 等字段。"""
    db = _make_mock_db()

    fake_result = {
        "soldout_id": str(uuid.uuid4()),
        "dish_id": DISH_ID,
        "dish_name": "招牌烤鱼",
        "store_id": STORE_ID,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "synced_channels": ["pos", "miniapp", "kds"],
    }

    with patch(
        "src.api.kds_soldout_routes.mark_soldout",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.post(
            "/api/v1/kds/soldout",
            json={
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "dish_name": "招牌烤鱼",
                "reason": "食材用完",
                "reported_by": "chef_001",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dish_id"] == DISH_ID
    assert "kds" in body["data"]["synced_channels"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /soldout — ValueError → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mark_soldout_already_soldout():
    """菜品已经沽清，重复标记时服务层抛 ValueError，端点透传 400。"""
    db = _make_mock_db()

    async def _raise(**kwargs):
        raise ValueError("菜品已在沽清状态，请勿重复标记")

    with patch(
        "src.api.kds_soldout_routes.mark_soldout",
        new=_raise,
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.post(
            "/api/v1/kds/soldout",
            json={
                "store_id": STORE_ID,
                "dish_id": DISH_ID,
                "dish_name": "招牌烤鱼",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "重复标记" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: DELETE /soldout — 恢复沽清成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_restore_soldout_success():
    """恢复沽清：菜品重新可售，全链路同步恢复，返回 ok=True。"""
    db = _make_mock_db()

    fake_result = {
        "dish_id": DISH_ID,
        "store_id": STORE_ID,
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "synced_channels": ["pos", "miniapp", "kds"],
    }

    with patch(
        "src.api.kds_soldout_routes.restore_soldout",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.request(
            "DELETE",
            "/api/v1/kds/soldout",
            json={"store_id": STORE_ID, "dish_id": DISH_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dish_id"] == DISH_ID
    assert "pos" in body["data"]["synced_channels"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: DELETE /soldout — ValueError → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_restore_soldout_not_found():
    """恢复沽清：菜品不在沽清状态时服务层抛 ValueError，端点返回 400。"""
    db = _make_mock_db()

    async def _raise(**kwargs):
        raise ValueError("菜品未处于沽清状态，无需恢复")

    with patch(
        "src.api.kds_soldout_routes.restore_soldout",
        new=_raise,
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.request(
            "DELETE",
            "/api/v1/kds/soldout",
            json={"store_id": STORE_ID, "dish_id": DISH_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "无需恢复" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /soldout?store_id=xxx — 查询沽清列表（有数据）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_active_soldout_with_items():
    """沽清列表：当前有 2 道菜沽清，返回 items 和 total=2。"""
    db = _make_mock_db()

    fake_items = [
        {
            "dish_id": DISH_ID,
            "dish_name": "招牌烤鱼",
            "soldout_at": datetime.now(timezone.utc).isoformat(),
            "reason": "食材用完",
        },
        {
            "dish_id": str(uuid.uuid4()),
            "dish_name": "清蒸石斑鱼",
            "soldout_at": datetime.now(timezone.utc).isoformat(),
            "reason": None,
        },
    ]

    with patch(
        "src.api.kds_soldout_routes.get_active_soldout",
        new=AsyncMock(return_value=fake_items),
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.get(
            "/api/v1/kds/soldout",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2
    assert body["data"]["items"][0]["dish_name"] == "招牌烤鱼"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: GET /soldout?store_id=xxx — 查询沽清列表（空列表）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_active_soldout_empty():
    """沽清列表：当前无沽清菜品，返回空 items 和 total=0。"""
    db = _make_mock_db()

    with patch(
        "src.api.kds_soldout_routes.get_active_soldout",
        new=AsyncMock(return_value=[]),
    ):
        client = TestClient(_make_soldout_app(db))
        resp = client.get(
            "/api/v1/kds/soldout",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: POST /soldout — 缺少必填字段 → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_mark_soldout_missing_required_field():
    """MarkSoldoutRequest 中 dish_name 是必填字段，缺少时 FastAPI 返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_soldout_app(db))

    resp = client.post(
        "/api/v1/kds/soldout",
        json={
            "store_id": STORE_ID,
            "dish_id": DISH_ID,
            # 故意缺少 dish_name
        },
        headers=HEADERS,
    )

    assert resp.status_code == 422
