"""宴席菜单 API 路由测试

覆盖 banquet_menu_routes.py 的主要端点：
  - GET  /api/v1/menu/banquet-menus              宴席菜单列表
  - POST /api/v1/menu/banquet-menus              创建宴席菜单档次
  - GET  /api/v1/menu/banquet-menus/{id}         宴席菜单详情（含分节和菜品）
  - POST /api/v1/menu/banquet-menus/{id}/sections              添加分节
  - POST /api/v1/menu/banquet-menus/{id}/sections/{sid}/items  添加菜品到分节
  - POST /api/v1/menu/banquet-sessions           创建宴席场次
  - GET  /api/v1/menu/banquet-sessions           查询场次列表
  - POST /api/v1/menu/banquet-sessions/{id}/action 场次状态操作
  - GET  /api/v1/menu/banquet-sessions/{id}/print-notice 获取通知单

使用 FastAPI TestClient + dependency_overrides，mock DB，不连真实数据库。
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from shared.ontology.src.database import get_db
from api.banquet_menu_routes import router

# ─── 构建测试用 App ───────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
MENU_ID = str(uuid.uuid4())
SECTION_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── Mock 工厂 ────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """返回不连接真实数据库的 AsyncSession mock"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.close = AsyncMock()
    return db


def _empty_result() -> MagicMock:
    """模拟空查询结果"""
    r = MagicMock()
    r.fetchone.return_value = None
    r.fetchall.return_value = []
    return r


def _rows_result(rows: list) -> MagicMock:
    """模拟多行查询结果"""
    r = MagicMock()
    r.fetchone.return_value = rows[0] if rows else None
    r.fetchall.return_value = rows
    return r


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    db = _make_mock_db()
    db.execute.return_value = _empty_result()
    return db


@pytest.fixture(autouse=True)
def override_db(mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. 宴席菜单列表 ──────────────────────────────────────────────────────────


class TestListBanquetMenus:
    def test_list_returns_200_with_empty_list(self, client, mock_db):
        """GET /api/v1/menu/banquet-menus 返回 200，无菜单时 items 为空"""
        mock_db.execute.return_value = _rows_result([])

        resp = client.get("/api/v1/menu/banquet-menus", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    def test_list_returns_banquet_menus(self, client, mock_db):
        """GET /api/v1/menu/banquet-menus 返回已有宴席菜单"""
        menu_uuid = uuid.UUID(MENU_ID)
        # 模拟数据库返回一行（按 SQL 列序）
        row = (
            menu_uuid,          # id
            "BQ-288",           # menu_code
            "精品宴288元/位",    # menu_name
            "premium",          # tier
            28800,              # per_person_fen
            20,                 # min_persons
            2,                  # min_tables
            "精品宴席",         # description
            ["时令活鲜", "私厨服务"],  # highlights
            True,               # is_active
            None,               # valid_from
            None,               # valid_until
            0,                  # sort_order
        )
        mock_db.execute.return_value = _rows_result([row])

        resp = client.get("/api/v1/menu/banquet-menus", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        menu = body["data"]["items"][0]
        assert menu["menu_code"] == "BQ-288"
        assert menu["tier"] == "premium"
        assert menu["tier_display"] == "精品宴"
        assert menu["per_person_fen"] == 28800

    def test_list_with_tier_filter(self, client, mock_db):
        """GET /api/v1/menu/banquet-menus?tier=luxury 带档次筛选"""
        mock_db.execute.return_value = _rows_result([])

        resp = client.get(
            "/api/v1/menu/banquet-menus",
            params={"tier": "luxury"},
            headers=HEADERS,
        )
        assert resp.status_code == 200

    def test_list_without_tenant_id_returns_400(self, client):
        """缺少 X-Tenant-ID header 返回 400"""
        resp = client.get("/api/v1/menu/banquet-menus")
        assert resp.status_code == 400


# ─── 2. 创建宴席菜单 ──────────────────────────────────────────────────────────


class TestCreateBanquetMenu:
    def test_create_returns_201(self, client, mock_db):
        """POST /api/v1/menu/banquet-menus 创建成功返回 201"""
        mock_db.execute.return_value = _empty_result()

        resp = client.post(
            "/api/v1/menu/banquet-menus",
            json={
                "menu_code": "BQ-388",
                "menu_name": "豪华宴388元/位",
                "tier": "luxury",
                "per_person_fen": 38800,
                "min_persons": 30,
                "min_tables": 3,
                "description": "豪华宴席体验",
                "highlights": ["顶级活鲜", "专属服务"],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert "menu_id" in body["data"]
        assert body["data"]["tier"] == "luxury"

    def test_create_with_invalid_tier_returns_422(self, client):
        """POST 无效档次返回 422（Pydantic pattern 校验）"""
        resp = client.post(
            "/api/v1/menu/banquet-menus",
            json={
                "menu_code": "BQ-999",
                "menu_name": "无效档次",
                "tier": "invalid_tier",
                "per_person_fen": 10000,
            },
            headers=HEADERS,
        )
        assert resp.status_code == 422

    def test_create_missing_required_fields_returns_422(self, client):
        """POST 缺少必填字段返回 422"""
        resp = client.post(
            "/api/v1/menu/banquet-menus",
            json={"menu_code": "BQ-100"},  # 缺少 menu_name / tier / per_person_fen
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ─── 3. 宴席菜单详情 ──────────────────────────────────────────────────────────


class TestGetBanquetMenuDetail:
    def test_get_detail_not_found_returns_404(self, client, mock_db):
        """GET /api/v1/menu/banquet-menus/{id} 菜单不存在时返回 404"""
        mock_db.execute.return_value = _rows_result([])  # fetchone() -> None

        resp = client.get(
            f"/api/v1/menu/banquet-menus/{MENU_ID}",
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_get_detail_success(self, client, mock_db):
        """GET /api/v1/menu/banquet-menus/{id} 菜单存在时返回 200 及完整结构"""
        menu_uuid = uuid.UUID(MENU_ID)
        menu_row = (
            menu_uuid, "BQ-288", "精品宴288元/位",
            "premium", 28800, 20, 2, "精品宴席", [],
        )
        sections_result = _rows_result([])
        items_result = _rows_result([])

        # 三次 execute：menu查询 / sections查询 / items查询
        mock_db.execute.side_effect = [
            _rows_result([menu_row]),
            sections_result,
            items_result,
        ]

        resp = client.get(
            f"/api/v1/menu/banquet-menus/{MENU_ID}",
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["menu_name"] == "精品宴288元/位"
        assert body["data"]["tier_display"] == "精品宴"
        assert "sections" in body["data"]


# ─── 4. 分节管理 ──────────────────────────────────────────────────────────────


class TestAddSection:
    def test_add_section_returns_201(self, client, mock_db):
        """POST /api/v1/menu/banquet-menus/{id}/sections 添加分节返回 201"""
        mock_db.execute.return_value = _empty_result()

        resp = client.post(
            f"/api/v1/menu/banquet-menus/{MENU_ID}/sections",
            json={
                "section_name": "热菜",
                "serve_sequence": 2,
                "serve_delay_minutes": 20,
                "sort_order": 2,
            },
            headers=HEADERS,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["section_name"] == "热菜"
        assert "section_id" in body["data"]

    def test_add_item_to_section_returns_201(self, client, mock_db):
        """POST /api/v1/menu/banquet-menus/{id}/sections/{sid}/items 添加菜品返回 201"""
        # 第一次 execute：查询菜品名
        dish_result = _rows_result([("剁椒鱼头",)])
        # 第二次 execute：INSERT item
        insert_result = _empty_result()
        mock_db.execute.side_effect = [dish_result, insert_result]

        resp = client.post(
            f"/api/v1/menu/banquet-menus/{MENU_ID}/sections/{SECTION_ID}/items",
            json={
                "dish_id": DISH_ID,
                "quantity_per_table": 1,
                "is_mandatory": True,
                "extra_price_fen": 0,
            },
            headers=HEADERS,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dish_id"] == DISH_ID


# ─── 5. 宴席场次 ──────────────────────────────────────────────────────────────


class TestBanquetSessions:
    def test_create_session_returns_201(self, client, mock_db):
        """POST /api/v1/menu/banquet-sessions 创建场次返回 201"""
        mock_db.execute.return_value = _empty_result()

        resp = client.post(
            "/api/v1/menu/banquet-sessions",
            json={
                "store_id": STORE_ID,
                "banquet_menu_id": MENU_ID,
                "session_name": "张先生婚宴2026-06-01",
                "scheduled_at": "2026-06-01T18:00:00",
                "guest_count": 200,
                "table_count": 20,
                "notes": "新人要求不上羊肉",
            },
            headers=HEADERS,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "scheduled"
        assert "session_id" in body["data"]

    def test_list_sessions_returns_200(self, client, mock_db):
        """GET /api/v1/menu/banquet-sessions 返回 200 和场次列表"""
        mock_db.execute.return_value = _rows_result([])

        resp = client.get(
            "/api/v1/menu/banquet-sessions",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []

    def test_list_sessions_missing_store_id_returns_422(self, client):
        """GET /api/v1/menu/banquet-sessions 缺少必填 store_id 返回 422"""
        resp = client.get("/api/v1/menu/banquet-sessions", headers=HEADERS)
        assert resp.status_code == 422

    def test_session_action_prepare_returns_200(self, client, mock_db):
        """POST /api/v1/menu/banquet-sessions/{id}/action prepare 开始备餐"""
        session_uuid = uuid.UUID(SESSION_ID)
        menu_uuid = uuid.UUID(MENU_ID)
        session_row = (
            "scheduled",    # status
            menu_uuid,      # banquet_menu_id
            "[]",           # table_ids
            None,           # scheduled_at
            None,           # current_section_id
        )
        update_result = _empty_result()
        mock_db.execute.side_effect = [
            _rows_result([session_row]),
            update_result,
        ]

        resp = client.post(
            f"/api/v1/menu/banquet-sessions/{SESSION_ID}/action",
            json={"action": "prepare"},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["action"] == "prepare"
        assert body["data"]["current_status"] == "preparing"

    def test_session_action_session_not_found_returns_404(self, client, mock_db):
        """POST session action 场次不存在时返回 404"""
        mock_db.execute.return_value = _rows_result([])  # fetchone() -> None

        resp = client.post(
            f"/api/v1/menu/banquet-sessions/{SESSION_ID}/action",
            json={"action": "prepare"},
            headers=HEADERS,
        )

        assert resp.status_code == 404

    def test_session_action_invalid_action_returns_422(self, client):
        """POST session action 无效 action 值返回 422（Pydantic pattern 校验）"""
        resp = client.post(
            f"/api/v1/menu/banquet-sessions/{SESSION_ID}/action",
            json={"action": "invalid_action"},
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ─── 6. 宴席通知单 ───────────────────────────────────────────────────────────


class TestBanquetNoticePrint:
    def test_get_print_notice_not_found_returns_404(self, client, mock_db):
        """GET /api/v1/menu/banquet-sessions/{id}/print-notice 场次不存在返回 404"""
        mock_db.execute.return_value = _rows_result([])

        resp = client.get(
            f"/api/v1/menu/banquet-sessions/{SESSION_ID}/print-notice",
            headers=HEADERS,
        )

        assert resp.status_code == 404

    def test_get_print_notice_success(self, client, mock_db):
        """GET /api/v1/menu/banquet-sessions/{id}/print-notice 正常返回打印数据"""
        from datetime import datetime

        session_uuid = uuid.UUID(SESSION_ID)
        session_row = (
            session_uuid,               # id
            "张先生婚宴",                # session_name
            datetime(2026, 6, 1, 18),   # scheduled_at
            200,                        # guest_count
            20,                         # table_count
            "新人要求不上羊肉",           # notes
            "scheduled",                # status
            "精品宴288元/位",            # menu_name
            28800,                      # per_person_fen
            "premium",                  # tier
        )
        menu_items_result = _rows_result([])  # 无菜品分节（空宴席菜单）

        mock_db.execute.side_effect = [
            _rows_result([session_row]),
            menu_items_result,
        ]

        resp = client.get(
            f"/api/v1/menu/banquet-sessions/{SESSION_ID}/print-notice",
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["print_type"] == "banquet_notice"
        assert body["data"]["header"]["session_name"] == "张先生婚宴"
        assert body["data"]["event_info"]["guest_count"] == 200
        assert body["data"]["event_info"]["table_count"] == 20
