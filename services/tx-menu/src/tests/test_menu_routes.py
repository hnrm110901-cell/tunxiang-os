"""menu_routes.py 路由测试 — 覆盖菜品档案 CRUD、菜单模板、沽清联动

测试策略:
- 菜品 CRUD 端点 (无 DB): mock dish_service 中的同步函数
- 模板端点 (有 DB): 通过 app.dependency_overrides[get_db] 注入 AsyncMock
- 沽清端点 (无 DB): mock stockout_sync 中的同步函数

路径约定: 从 tx-menu 目录导入 src.api.menu_routes（避免相对导入问题）。
"""

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 路径设置 ──────────────────────────────────────────────────────────────────
# 把 tx-menu 目录和 tunxiang-os 根目录加入 sys.path
_tx_menu_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_repo_root = os.path.abspath(os.path.join(_tx_menu_dir, "..", ".."))
for _p in [_tx_menu_dir, _repo_root]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 导入路由 ──────────────────────────────────────────────────────────────────
from src.api.menu_routes import get_db, router  # noqa: E402

# patch 路径前缀
_MOD = "src.api.menu_routes"

# ─── 测试常量 ──────────────────────────────────────────────────────────────────
TENANT = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
TMPL_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT}


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────


def _make_app(db_override=None) -> FastAPI:
    """构建带路由的测试用 FastAPI app，可选注入 DB mock。"""
    app = FastAPI()
    app.include_router(router)
    if db_override is not None:
        app.dependency_overrides[get_db] = db_override
    return app


def _mock_db_session():
    """构建支持 execute / commit / close 的 AsyncMock Session。"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


def _async_dep(session):
    """把 mock session 包装成 FastAPI 异步依赖生成器。"""

    async def _dep():
        yield session

    return _dep


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 1 & 2：创建菜品
# ═══════════════════════════════════════════════════════════════════════════════


def test_create_dish_success():
    """POST /v2/dishes — 成功创建菜品，返回 ok=True 及菜品数据。"""
    expected = {
        "dish_id": DISH_ID,
        "dish_name": "宫保鸡丁",
        "dish_code": "GBCJ001",
        "price_fen": 3800,
        "tenant_id": TENANT,
    }
    with patch(f"{_MOD}.create_dish", return_value=expected) as mock_create:
        client = TestClient(_make_app())
        resp = client.post(
            "/api/v1/menu/v2/dishes",
            json={
                "dish_name": "宫保鸡丁",
                "dish_code": "GBCJ001",
                "price_fen": 3800,
            },
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dish_code"] == "GBCJ001"
    mock_create.assert_called_once()


def test_create_dish_value_error_returns_400():
    """POST /v2/dishes — dish_service 抛出 ValueError 时返回 400。"""
    with patch(f"{_MOD}.create_dish", side_effect=ValueError("编码重复")):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/v1/menu/v2/dishes",
            json={"dish_name": "测试菜", "dish_code": "DUP", "price_fen": 1000},
            headers=HEADERS,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 3 & 4：查询菜品
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_dish_found():
    """GET /v2/dishes/{dish_id} — 菜品存在时返回 200 和菜品详情。"""
    dish_data = {"dish_id": DISH_ID, "dish_name": "麻婆豆腐", "tenant_id": TENANT}
    with patch(f"{_MOD}.get_dish", return_value=dish_data):
        client = TestClient(_make_app())
        resp = client.get(f"/api/v1/menu/v2/dishes/{DISH_ID}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["dish_name"] == "麻婆豆腐"


def test_get_dish_not_found_returns_404():
    """GET /v2/dishes/{dish_id} — 菜品不存在时返回 404，error.message 含"不存在"。"""
    with patch(f"{_MOD}.get_dish", return_value=None):
        client = TestClient(_make_app())
        resp = client.get(f"/api/v1/menu/v2/dishes/{DISH_ID}", headers=HEADERS)
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert "不存在" in detail["error"]["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 5 & 6：更新菜品
# ═══════════════════════════════════════════════════════════════════════════════


def test_update_dish_success():
    """PATCH /v2/dishes/{dish_id} — 正常更新返回最新菜品数据。"""
    updated = {"dish_id": DISH_ID, "dish_name": "新名称", "price_fen": 4000}
    with patch(f"{_MOD}.update_dish", return_value=updated):
        client = TestClient(_make_app())
        resp = client.patch(
            f"/api/v1/menu/v2/dishes/{DISH_ID}",
            json={"dish_name": "新名称", "price_fen": 4000},
            headers=HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["price_fen"] == 4000


def test_update_dish_service_error_returns_400():
    """PATCH /v2/dishes/{dish_id} — service 校验失败返回 400。"""
    with patch(f"{_MOD}.update_dish", side_effect=ValueError("价格不能为负")):
        client = TestClient(_make_app())
        resp = client.patch(
            f"/api/v1/menu/v2/dishes/{DISH_ID}",
            json={"price_fen": -1},
            headers=HEADERS,
        )
    assert resp.status_code == 400
    assert resp.json()["detail"]["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 7 & 8：创建菜单模板（有 DB 依赖）
# ═══════════════════════════════════════════════════════════════════════════════


def test_create_template_success():
    """POST /templates — 正常创建模板，db.commit 被调用一次。"""
    tpl_result = {
        "template_id": TMPL_ID,
        "name": "春季菜单",
        "status": "draft",
        "dishes": [],
    }
    session = _mock_db_session()
    mock_repo = MagicMock()
    mock_repo.create_template = AsyncMock(return_value=tpl_result)

    with patch(f"{_MOD}.MenuTemplateRepository", return_value=mock_repo):
        client = TestClient(_make_app(_async_dep(session)))
        resp = client.post(
            "/api/v1/menu/templates",
            json={
                "name": "春季菜单",
                "dishes": [{"dish_id": DISH_ID, "sort_order": 1}],
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "春季菜单"
    session.commit.assert_awaited_once()


def test_create_template_value_error_returns_400():
    """POST /templates — repo 抛出 ValueError 时返回 400，ok=False。"""
    session = _mock_db_session()
    mock_repo = MagicMock()
    mock_repo.create_template = AsyncMock(side_effect=ValueError("模板名重复"))

    with patch(f"{_MOD}.MenuTemplateRepository", return_value=mock_repo):
        client = TestClient(_make_app(_async_dep(session)))
        resp = client.post(
            "/api/v1/menu/templates",
            json={"name": "重复模板", "dishes": []},
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 9：沽清标记
# ═══════════════════════════════════════════════════════════════════════════════


def test_mark_sold_out_success():
    """POST /stockout/mark — 成功标记沽清，返回沽清记录。"""
    record = {
        "dish_id": DISH_ID,
        "store_id": STORE_ID,
        "reason": "manual",
        "tenant_id": TENANT,
    }
    with patch(f"{_MOD}.mark_sold_out", return_value=record):
        client = TestClient(_make_app())
        resp = client.post(
            "/api/v1/menu/stockout/mark",
            json={"dish_id": DISH_ID, "store_id": STORE_ID, "reason": "manual"},
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["reason"] == "manual"


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 10：门店沽清清单
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_sold_out_list_returns_items():
    """GET /stores/{store_id}/stockout — 返回沽清清单，total 与列表长度一致。"""
    items = [
        {"dish_id": DISH_ID, "store_id": STORE_ID, "reason": "manual"},
        {"dish_id": str(uuid.uuid4()), "store_id": STORE_ID, "reason": "stock_depleted"},
    ]
    with patch(f"{_MOD}.get_sold_out_list", return_value=items):
        client = TestClient(_make_app())
        resp = client.get(
            f"/api/v1/menu/stores/{STORE_ID}/stockout",
            headers=HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2
