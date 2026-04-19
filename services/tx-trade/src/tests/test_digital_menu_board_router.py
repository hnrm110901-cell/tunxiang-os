"""数字菜单展示屏 API 测试 — digital_menu_board_router.py

覆盖场景：
1.  GET  /board-data       — 正常路径：查询返回菜品列表，结构正确
2.  GET  /board-data       — 空菜单时返回空 dishes 列表
3.  GET  /board-data       — 缺少 X-Tenant-ID → 422
4.  GET  /board-config     — 正常路径：Store 存在时返回 store_name
5.  GET  /board-config     — Store 不存在时返回默认值"屯象餐厅"
6.  GET  /digital-menu/dishes  — 正常路径
7.  GET  /digital-menu/dishes  — DB 异常 fallback 返回空列表
8.  GET  /digital-menu/config  — 正常路径：store 存在返回真实数据
9.  GET  /digital-menu/config  — store 不存在返回默认配置
10. GET  /digital-menu/config  — DB 异常 fallback 返回默认配置
11. POST /board-announcement   — 正常路径：公告写入 + 广播
12. POST /board-announcement   — 空公告字符串返回 400
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ─── 工具类 ────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()

_HEADERS = {"X-Tenant-ID": TENANT_ID}


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeMappingsResult:
    """模拟 result.mappings().all() 或 .one_or_none()"""

    def __init__(self, rows=None, single=None):
        self._rows = rows or []
        self._single = single  # 用于 one_or_none()

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._single


class FakeExecuteResult:
    """模拟 result.all() 行列表 / .one_or_none() / .mappings()"""

    def __init__(self, rows=None, single=None, mapping_rows=None, mapping_single=None):
        self._rows = rows or []
        self._single = single
        self._mapping_rows = mapping_rows or []
        self._mapping_single = mapping_single

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._single

    def mappings(self):
        return FakeMappingsResult(
            rows=self._mapping_rows,
            single=self._mapping_single,
        )


def _seq_db(*results):
    """构造按顺序依次返回 results 的 AsyncMock DB"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    return db


# ─── 加载路由 ──────────────────────────────────────────────

from api.digital_menu_board_router import router

from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(router)


def _override(db):
    def _dep():
        return db

    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /board-data — 正常路径，菜品列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_board_data_returns_dish_list():
    """查询返回 2 道菜，结构字段完整"""
    import uuid as _uuid

    dish1_id = _uuid.uuid4()
    dish2_id = _uuid.uuid4()

    # board-data 路由：set_config + select(Dish, DishCategory.name)
    # result.all() 返回 [(dish_obj, category_name), ...]
    # 我们用 FakeRow 模拟 dish 属性
    dish1 = FakeRow(
        id=dish1_id,
        dish_name="红烧肉",
        price_fen=6800,
        original_price_fen=None,
        image_url="http://img/1.jpg",
        is_available=True,
        tags=["新品"],
    )
    dish2 = FakeRow(
        id=dish2_id,
        dish_name="清蒸鲈鱼",
        price_fen=12800,
        original_price_fen=15000,
        image_url=None,
        is_available=True,
        tags=["特价"],
    )

    # set_config 调用返回任意，第二次返回菜品列表
    set_cfg_result = AsyncMock()
    dish_result = FakeExecuteResult(rows=[(dish1, "热菜"), (dish2, "海鲜")])

    db = _seq_db(set_cfg_result, dish_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/board-data?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    dishes = body["data"]["dishes"]
    assert len(dishes) == 2
    assert dishes[0]["name"] == "红烧肉"
    assert dishes[0]["category"] == "热菜"
    assert dishes[0]["is_new"] is True
    assert dishes[1]["is_special"] is True
    assert body["data"]["store_id"] == STORE_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /board-data — 空菜单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_board_data_empty_menu():
    """无菜品时返回空列表，ok=True"""
    set_cfg_result = AsyncMock()
    dish_result = FakeExecuteResult(rows=[])

    db = _seq_db(set_cfg_result, dish_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/board-data?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["data"]["dishes"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /board-data — 缺少 X-Tenant-ID → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_board_data_missing_tenant_header():
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/menu/board-data?store_id={STORE_ID}")  # 不带 header
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /board-config — store 存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_board_config_with_store():
    """store 存在时返回真实 store_name 和 announcement"""
    set_cfg = AsyncMock()
    store_result = FakeExecuteResult(single=("屯象旗舰店", {"board_announcement": "欢迎光临"}))
    cat_result = FakeExecuteResult(rows=[("热菜",), ("海鲜",), ("凉菜",)])
    special_result = FakeExecuteResult(rows=[])
    featured_result = FakeExecuteResult(rows=[])

    db = _seq_db(set_cfg, store_result, cat_result, special_result, featured_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/board-config?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["store_name"] == "屯象旗舰店"
    assert data["announcement"] == "欢迎光临"
    assert "热菜" in data["category_order"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /board-config — store 不存在时默认值
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_board_config_store_not_found_uses_defaults():
    """门店不存在时 store_name 返回 '屯象餐厅'"""
    set_cfg = AsyncMock()
    store_result = FakeExecuteResult(single=None)  # one_or_none() → None
    cat_result = FakeExecuteResult(rows=[])  # 无分类
    special_result = FakeExecuteResult(rows=[])
    featured_result = FakeExecuteResult(rows=[])

    db = _seq_db(set_cfg, store_result, cat_result, special_result, featured_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/board-config?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["store_name"] == "屯象餐厅"
    # 无分类时返回默认分类列表
    assert len(data["category_order"]) > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /digital-menu/dishes — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_digital_menu_dishes_normal():
    """返回菜品列表，字段包含 price_fen"""
    dish_id = str(uuid.uuid4())
    cat_id = str(uuid.uuid4())
    mapping_rows = [
        {
            "id": dish_id,
            "name": "酸菜鱼",
            "category_id": cat_id,
            "price_fen": 5800,
            "description": "经典酸菜鱼",
            "image_url": None,
            "is_available": True,
        }
    ]

    set_cfg = AsyncMock()
    dishes_result = FakeExecuteResult(mapping_rows=mapping_rows)

    db = _seq_db(set_cfg, dishes_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/digital-menu/dishes?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    dishes = body["data"]["dishes"]
    assert len(dishes) == 1
    assert dishes[0]["name"] == "酸菜鱼"
    assert dishes[0]["price_fen"] == 5800


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /digital-menu/dishes — DB 异常 fallback
# 注：set_config 调用（第 1 次 execute）需正常返回；
# 第 2 次 execute（实际查询）再抛 OperationalError，才能触发 fallback。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_digital_menu_dishes_db_error_fallback():
    """DB 查询异常时 graceful 返回空列表，ok=True"""
    db = _seq_db(
        AsyncMock(),  # set_config 正常
        OperationalError("stmt", {}, Exception("timeout")),  # 实际查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/digital-menu/dishes?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["data"]["dishes"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /digital-menu/config — store 存在
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_digital_menu_config_with_store():
    """store 存在时返回真实配置字段"""
    store_mapping = {
        "id": uuid.UUID(STORE_ID),
        "name": "测试分店",
        "logo_url": "http://img/logo.png",
        "announcement_text": "今日特惠",
        "theme_color": "#123456",
    }

    set_cfg = AsyncMock()
    store_result = FakeExecuteResult(mapping_single=store_mapping)

    db = _seq_db(set_cfg, store_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/digital-menu/config?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["store_name"] == "测试分店"
    assert data["announcement_text"] == "今日特惠"
    assert data["theme_color"] == "#123456"
    assert data["logo_url"] == "http://img/logo.png"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /digital-menu/config — store 不存在，默认配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_digital_menu_config_store_not_found():
    """store 不存在时返回默认 store_name 和 theme_color"""
    set_cfg = AsyncMock()
    store_result = FakeExecuteResult(mapping_single=None)

    db = _seq_db(set_cfg, store_result)
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/digital-menu/config?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["store_name"] == "屯象餐厅"
    assert data["theme_color"] == "#FF6B35"
    assert data["announcement_text"] == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: GET /digital-menu/config — DB 异常 fallback
# 注：同场景 7，set_config（第 1 次）正常，第 2 次查询抛异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_digital_menu_config_db_error_fallback():
    """DB 查询异常时返回默认配置，不抛错"""
    db = _seq_db(
        AsyncMock(),  # set_config 正常
        OperationalError("stmt", {}, Exception("conn refused")),  # 查询抛异常
    )
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.get(f"/api/v1/menu/digital-menu/config?store_id={STORE_ID}", headers=_HEADERS)

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["store_name"] == "屯象餐厅"
    assert data["theme_color"] == "#FF6B35"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: POST /board-announcement — 正常路径
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_update_board_announcement_success():
    """公告更新成功，broadcast_ok 字段存在，channel 格式正确"""
    set_cfg = AsyncMock()
    update_result = AsyncMock()

    db = _seq_db(set_cfg, update_result)
    db.commit = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    with patch(
        "api.digital_menu_board_router._publish_to_redis",
        AsyncMock(return_value=True),
    ):
        resp = client.post(
            "/api/v1/menu/board-announcement",
            json={"store_id": STORE_ID, "announcement": "今日活动：买一送一"},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["announcement"] == "今日活动：买一送一"
    assert data["broadcast_ok"] is True
    assert TENANT_ID in data["channel"]
    assert STORE_ID in data["channel"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: POST /board-announcement — 空内容 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_update_board_announcement_empty_body():
    """公告内容为空字符串时返回 400"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/menu/board-announcement",
        json={"store_id": STORE_ID, "announcement": "   "},  # 全空白
        headers=_HEADERS,
    )
    assert resp.status_code == 400
