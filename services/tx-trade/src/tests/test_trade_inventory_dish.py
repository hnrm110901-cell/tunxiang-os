"""库存驱动菜单联动 & 菜品档口映射 API 测试

文件覆盖：
  - api/inventory_menu_routes.py    (5个测试)
  - api/dish_dept_mapping_routes.py (5个测试)

inventory_menu_routes 场景：
  1. POST /ingredient/{id}/stock-update — 正常路径，有自动下架菜品
  2. POST /ingredient/{id}/stock-update — 库存充足，无菜品被下架（空列表）
  3. GET  /soldout-watch              — 正常返回预警列表
  4. POST /ingredient/{id}/restock   — 补货恢复菜品上架
  5. GET  /dashboard                 — 仪表盘正常返回汇总数据

dish_dept_mapping_routes 场景：
  6. GET  /kds/dish-dept-mappings              — 正常分页查询
  7. POST /kds/dish-dept-mappings              — 缺少 X-Tenant-ID → 400
  8. POST /kds/dish-dept-mappings/batch        — 批量导入返回 created/updated 计数
  9. GET  /kds/dish-dept-mappings/by-dish/{id} — 返回某菜品所有映射
  10. DELETE /kds/dish-dept-mappings/{id}       — 映射不存在时返回 404
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── 路径准备 ──────────────────────────────────────────────────────────────────

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级，使相对导入正常工作 ────────────────────────────────────────


def _ensure_pkg(pkg_name: str, pkg_path: str) -> None:
    if pkg_name not in sys.modules:
        mod = types.ModuleType(pkg_name)
        mod.__path__ = [pkg_path]  # type: ignore[attr-defined]
        mod.__package__ = pkg_name
        sys.modules[pkg_name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))


# ─── structlog 存根 ───────────────────────────────────────────────────────────

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _structlog.get_logger = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]
    sys.modules["structlog"] = _structlog


# ─── 共享工具 ─────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
INGREDIENT_ID = _uid()
DISH_ID_1 = _uid()
DEPT_ID_1 = _uid()
MAPPING_ID = _uid()

_BASE_HEADERS = {"X-Tenant-ID": TENANT_ID}


class FakeRow:
    """模拟 SQLAlchemy Row 对象"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    """模拟 SQLAlchemy CursorResult"""

    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar = scalar_value

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._scalar


def _make_db(*execute_results):
    """构造 AsyncMock DB，execute 依次返回 execute_results；commit 空实现。"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    db.commit = AsyncMock(return_value=None)
    return db


def _override_db(db):
    def _dep():
        return db

    return _dep


# ─── 导入路由（必须以 src.api.* 导入，使相对导入可解析）────────────────────────

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.dish_dept_mapping_routes import router as ddm_router  # type: ignore[import]  # noqa: E402

# inventory_menu_routes 通过相对导入引用 src.services.*
from src.api.inventory_menu_routes import router as inv_router  # type: ignore[import]  # noqa: E402

inv_app = FastAPI()
inv_app.include_router(inv_router)

ddm_app = FastAPI()
ddm_app.include_router(ddm_router)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ══ inventory_menu_routes 测试（5个） ═══════════════════════════════════════
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class _ImpactedDish:
    """最小化的 ImpactedDish 存根，供测试构造返回值用"""

    def __init__(self, dish_id: str, dish_name: str, estimated_servings: int = 0):
        self.dish_id = dish_id
        self.dish_name = dish_name
        self.estimated_servings = estimated_servings


# ─── 测试1: stock-update 正常路径，有菜品被自动下架 ───────────────────────────


@pytest.mark.asyncio
async def test_stock_update_triggers_auto_soldout():
    """POST stock-update：库存不足时，服务返回 2 道自动下架菜品"""
    from unittest.mock import patch

    dish1 = _ImpactedDish(DISH_ID_1, "鲍汁捞饭")
    dish2 = _ImpactedDish(_uid(), "牛骨汤锅")

    db = AsyncMock()
    inv_app.dependency_overrides[get_db] = _override_db(db)

    with patch(
        "src.api.inventory_menu_routes.check_and_auto_soldout",
        new=AsyncMock(return_value=[dish1, dish2]),
    ):
        client = TestClient(inv_app)
        resp = client.post(
            f"/api/v1/inventory/ingredient/{INGREDIENT_ID}/stock-update",
            json={"current_stock": 0.0, "unit": "kg", "updated_by": "盘点员A"},
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["auto_soldout_count"] == 2
    assert data["ingredient_id"] == INGREDIENT_ID
    assert data["current_stock"] == 0.0
    assert data["auto_soldout_dishes"][0]["dish_name"] == "鲍汁捞饭"


# ─── 测试2: stock-update 库存充足，无菜品被下架 ──────────────────────────────


@pytest.mark.asyncio
async def test_stock_update_no_soldout_when_sufficient():
    """POST stock-update：库存充足时 auto_soldout_dishes 为空列表"""
    from unittest.mock import patch

    db = AsyncMock()
    inv_app.dependency_overrides[get_db] = _override_db(db)

    with patch(
        "src.api.inventory_menu_routes.check_and_auto_soldout",
        new=AsyncMock(return_value=[]),
    ):
        client = TestClient(inv_app)
        resp = client.post(
            f"/api/v1/inventory/ingredient/{INGREDIENT_ID}/stock-update",
            json={"current_stock": 50.0, "unit": "kg", "updated_by": "采购员"},
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["auto_soldout_count"] == 0
    assert data["auto_soldout_dishes"] == []


# ─── 测试3: soldout-watch 返回预警列表 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_soldout_watch_returns_alert_list():
    """GET /soldout-watch：正常返回低库存预警菜品列表"""
    from unittest.mock import patch

    alert_items = [
        {"dish_id": DISH_ID_1, "dish_name": "招牌红烧肉", "urgency": "critical"},
        {"dish_id": _uid(), "dish_name": "清蒸鲈鱼", "urgency": "warning"},
    ]
    db = AsyncMock()
    inv_app.dependency_overrides[get_db] = _override_db(db)

    with patch(
        "src.api.inventory_menu_routes.get_soldout_watch",
        new=AsyncMock(return_value=alert_items),
    ):
        client = TestClient(inv_app)
        resp = client.get(
            f"/api/v1/inventory/soldout-watch?store_id={STORE_ID}",
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert body["data"]["store_id"] == STORE_ID
    assert body["data"]["items"][0]["urgency"] == "critical"


# ─── 测试4: restock 补货恢复菜品上架 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_restock_restores_dishes():
    """POST /restock：补货后返回已恢复的菜品 ID 列表"""
    from unittest.mock import patch

    restored_ids = [DISH_ID_1, _uid()]
    db = AsyncMock()
    inv_app.dependency_overrides[get_db] = _override_db(db)

    with patch(
        "src.api.inventory_menu_routes.restore_dishes_by_ingredient",
        new=AsyncMock(return_value=restored_ids),
    ):
        client = TestClient(inv_app)
        resp = client.post(
            f"/api/v1/inventory/ingredient/{INGREDIENT_ID}/restock",
            json={"add_stock": 20.0, "unit": "kg"},
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["restored_count"] == 2
    assert data["ingredient_id"] == INGREDIENT_ID
    assert data["add_stock"] == 20.0
    assert DISH_ID_1 in data["restored_dish_ids"]


# ─── 测试5: dashboard 返回汇总仪表盘 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_inventory_dashboard_returns_summary():
    """GET /dashboard：返回 total_ingredients / low_stock_count / soldout_dishes_count"""
    from unittest.mock import patch

    dashboard_data = {
        "total_ingredients": 120,
        "low_stock_count": 5,
        "soldout_dishes_count": 3,
        "alerts": [],
    }
    db = AsyncMock()
    inv_app.dependency_overrides[get_db] = _override_db(db)

    with patch(
        "src.api.inventory_menu_routes.get_inventory_dashboard",
        new=AsyncMock(return_value=dashboard_data),
    ):
        client = TestClient(inv_app)
        resp = client.get(
            f"/api/v1/inventory/dashboard?store_id={STORE_ID}",
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total_ingredients"] == 120
    assert body["data"]["low_stock_count"] == 5
    assert body["data"]["soldout_dishes_count"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ══ dish_dept_mapping_routes 测试（5个） ════════════════════════════════════
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ─── 测试6: GET /dish-dept-mappings 分页查询 ─────────────────────────────────


@pytest.mark.asyncio
async def test_list_dish_dept_mappings_pagination():
    """GET /dish-dept-mappings：正常分页查询，返回 items + total"""
    import datetime

    row = FakeRow(
        id=uuid.UUID(MAPPING_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        dish_id=uuid.UUID(DISH_ID_1),
        dept_id=uuid.UUID(DEPT_ID_1),
        dept_name="热菜档口",
        is_primary=True,
        priority=0,
        created_at=datetime.datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime.datetime(2026, 1, 1, 12, 0, 0),
    )
    # 3次 execute：set_config RLS → COUNT query → list query
    db = _make_db(
        FakeResult(),  # set_config RLS
        FakeResult(scalar_value=1),  # COUNT
        FakeResult(rows=[row]),  # list
    )
    ddm_app.dependency_overrides[get_db] = _override_db(db)

    client = TestClient(ddm_app)
    resp = client.get(
        "/api/v1/kds/dish-dept-mappings?page=1&size=50",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["dept_name"] == "热菜档口"
    assert data["items"][0]["is_primary"] is True


# ─── 测试7: POST /dish-dept-mappings 缺少 X-Tenant-ID → 400 ─────────────────


def test_upsert_mapping_missing_tenant_returns_400():
    """POST /dish-dept-mappings：不传 X-Tenant-ID header 时返回 400"""
    db = AsyncMock()
    ddm_app.dependency_overrides[get_db] = _override_db(db)

    client = TestClient(ddm_app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/kds/dish-dept-mappings",
        json={
            "dish_id": DISH_ID_1,
            "dept_id": DEPT_ID_1,
            "dept_name": "凉菜档口",
        },
        # 故意不传 X-Tenant-ID
    )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json().get("detail", "")


# ─── 测试8: POST /batch 批量导入返回创建计数 ─────────────────────────────────


@pytest.mark.asyncio
async def test_batch_import_returns_created_count():
    """POST /dish-dept-mappings/batch：2条新增，返回 created=2 updated=0"""
    # 执行顺序：set_config → NOW() → check1(空) → insert1 → check2(空) → insert2
    db = _make_db(
        FakeResult(),  # set_config RLS
        FakeResult(scalar_value=None),  # SELECT NOW()
        FakeResult(rows=[]),  # check existing mapping1 → 不存在
        FakeResult(),  # INSERT mapping1
        FakeResult(rows=[]),  # check existing mapping2 → 不存在
        FakeResult(),  # INSERT mapping2
    )
    ddm_app.dependency_overrides[get_db] = _override_db(db)

    client = TestClient(ddm_app)
    resp = client.post(
        "/api/v1/kds/dish-dept-mappings/batch",
        json={
            "mappings": [
                {"dish_id": DISH_ID_1, "dept_id": DEPT_ID_1, "dept_name": "热菜"},
                {"dish_id": _uid(), "dept_id": _uid(), "dept_name": "冷菜"},
            ],
            "store_id": STORE_ID,
            "replace_existing": False,
        },
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["total"] == 2
    assert data["errors"] == []


# ─── 测试9: GET /by-dish/{dish_id} 返回某菜品的所有映射 ──────────────────────


@pytest.mark.asyncio
async def test_get_mappings_by_dish_returns_list():
    """GET /dish-dept-mappings/by-dish/{dish_id}：返回该菜品的映射列表"""
    import datetime

    row1 = FakeRow(
        id=uuid.UUID(MAPPING_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        store_id=uuid.UUID(STORE_ID),
        dish_id=uuid.UUID(DISH_ID_1),
        dept_id=uuid.UUID(DEPT_ID_1),
        dept_name="主厨档口",
        is_primary=True,
        priority=0,
        created_at=datetime.datetime(2026, 2, 1),
        updated_at=datetime.datetime(2026, 2, 1),
    )
    # set_config → list query
    db = _make_db(FakeResult(), FakeResult(rows=[row1]))
    ddm_app.dependency_overrides[get_db] = _override_db(db)

    client = TestClient(ddm_app)
    resp = client.get(
        f"/api/v1/kds/dish-dept-mappings/by-dish/{DISH_ID_1}",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["dish_id"] == DISH_ID_1
    assert data["total"] == 1
    assert data["mappings"][0]["dept_name"] == "主厨档口"
    assert data["mappings"][0]["is_primary"] is True


# ─── 测试10: DELETE /dish-dept-mappings/{id} 映射不存在 → 404 ────────────────


@pytest.mark.asyncio
async def test_delete_mapping_not_found_returns_404():
    """DELETE /dish-dept-mappings/{id}：映射不存在时返回 404"""
    # set_config → check SELECT → 返回空（不存在）
    db = _make_db(
        FakeResult(),  # set_config RLS
        FakeResult(rows=[]),  # SELECT id ... → 不存在
    )
    ddm_app.dependency_overrides[get_db] = _override_db(db)

    non_existent_id = str(uuid.uuid4())
    client = TestClient(ddm_app, raise_server_exceptions=False)
    resp = client.delete(
        f"/api/v1/kds/dish-dept-mappings/{non_existent_id}",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 404
    assert "不存在" in resp.json().get("detail", "")
