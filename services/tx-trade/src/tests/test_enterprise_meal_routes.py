"""企业订餐路由测试 — enterprise_meal_routes.py

覆盖场景（共 8 个）：
1. GET  /api/v1/trade/enterprise/weekly-menu — 返回2条 menu 记录，data.days 长度=2
2. GET  /api/v1/trade/enterprise/weekly-menu — 返回空列表，data.days=[]
3. GET  /api/v1/trade/enterprise/account     — 返回账户记录，data 含 balance_fen 字段
4. GET  /api/v1/trade/enterprise/account     — 账户不存在时返回零值，不返回 404
5. POST /api/v1/trade/enterprise/order       — INSERT RETURNING id 成功，data 含 id 字段
6. POST /api/v1/trade/enterprise/order       — DB 抛 SQLAlchemyError，路由兜底返回 ok=True + rollback
7. GET  /api/v1/trade/enterprise/meal-orders — 返回2条订单，data.items 长度=2
8. GET  /api/v1/trade/enterprise/meal-orders — 返回空列表，data.items=[]
"""

import os
import sys

# Sprint A4：RBAC 装饰器在 TX_AUTH_ENABLED=false 时注入 mock 用户
os.environ["TX_AUTH_ENABLED"] = "false"

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 确保 src 包层级可用，使相对导入正常工作 ──────────────────────────────────
import types

# ─── 建立 src 包层级，使相对导入正常工作 ──────────────────────────────────────


def _ensure_pkg(pkg_name: str, pkg_path: str) -> None:
    if pkg_name not in sys.modules:
        mod = types.ModuleType(pkg_name)
        mod.__path__ = [pkg_path]
        mod.__package__ = pkg_name
        sys.modules[pkg_name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

# ─── 在导入路由之前，先把 shared.ontology.src.database 装入 sys.modules，
#     再创建 src.db 存根指向同一个 get_db，满足 `from ..db import get_db` ────────

from shared.ontology.src.database import get_db  # noqa: E402

_db_stub = types.ModuleType("src.db")
_db_stub.get_db = get_db  # type: ignore[attr-defined]
sys.modules["src.db"] = _db_stub

# ─── 正式导入 ─────────────────────────────────────────────────────────────────
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.enterprise_meal_routes import router  # type: ignore[import]  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT = str(uuid.uuid4())
EMPLOYEE_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
WEEK_START = "2026-03-30"

# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def _make_result_all(rows: list) -> MagicMock:
    """构造支持 .mappings().all() 的 execute 返回值"""
    mappings_obj = MagicMock()
    mappings_obj.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.mappings = MagicMock(return_value=mappings_obj)
    return result


def _make_result_first(row) -> MagicMock:
    """构造支持 .mappings().first() 的 execute 返回值"""
    mappings_obj = MagicMock()
    mappings_obj.first = MagicMock(return_value=row)
    result = MagicMock()
    result.mappings = MagicMock(return_value=mappings_obj)
    return result


def _make_result_first_raw(row) -> MagicMock:
    """构造支持 .first() （非 mappings）的 execute 返回值 — 用于 INSERT RETURNING"""
    result = MagicMock()
    result.first = MagicMock(return_value=row)
    return result


def make_mock_db() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _override_db(db: AsyncMock):
    def _dep():
        return db

    return _dep


def _make_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _override_db(db)
    return app


# ─── 菜单行工厂 ───────────────────────────────────────────────────────────────


def _menu_row(weekday: int = 1) -> dict:
    return {
        "id": uuid.uuid4(),
        "store_id": uuid.UUID(STORE_ID),
        "weekday": weekday,
        "meal_type": "lunch",
        "dish_ids": ["dish-001", "dish-002"],  # 已是 list，无需 json.loads
        "is_published": True,
    }


# ─── 订单行工厂 ───────────────────────────────────────────────────────────────


def _order_row() -> dict:
    return {
        "id": uuid.uuid4(),
        "store_id": uuid.UUID(STORE_ID),
        "employee_id": uuid.UUID(EMPLOYEE_ID),
        "meal_date": date(2026, 3, 31),
        "meal_type": "lunch",
        "dish_ids": ["dish-001"],  # 已是 list
        "amount_fen": 2800,
        "payment_method": "account",
        "status": "confirmed",
        "created_at": datetime(2026, 3, 31, 9, 0, 0, tzinfo=timezone.utc),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /weekly-menu — SELECT 返回2条记录，data.days 长度=2
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_weekly_menu_success():
    """SELECT 返回2条 menu 记录 → 200，data.menu.days 长度为2"""
    row1 = _menu_row(weekday=1)
    row2 = _menu_row(weekday=2)

    # execute 被调用两次：_set_tenant（SELECT set_config）+ 主查询
    set_cfg_result = MagicMock()
    main_result = _make_result_all([row1, row2])

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/weekly-menu?company_id={TENANT}&store_id={STORE_ID}&week={WEEK_START}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    days = body["data"]["menu"]["days"]
    assert len(days) == 2
    assert days[0]["weekday"] == 1
    assert days[1]["weekday"] == 2
    assert isinstance(days[0]["dish_ids"], list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /weekly-menu — SELECT 返回空列表，data.days=[]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_weekly_menu_empty():
    """SELECT 返回空 → 200，data.menu.days=[]"""
    set_cfg_result = MagicMock()
    main_result = _make_result_all([])

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/weekly-menu?company_id={TENANT}&week={WEEK_START}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["menu"]["days"] == []
    assert body["data"]["menu"]["week_start"] == WEEK_START


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /account — SELECT 返回账户记录，data 含 balance_fen
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_account_success():
    """SELECT 返回账户行 → 200，data.balance_fen=5000, data.meal_count_remaining=10"""
    account_row = {"balance_fen": 5000, "meal_count_remaining": 10}

    set_cfg_result = MagicMock()
    main_result = _make_result_first(account_row)

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/account?company_id={TENANT}&member_id={EMPLOYEE_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "balance_fen" in data
    assert data["balance_fen"] == 5000
    assert data["meal_count_remaining"] == 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /account — SELECT 返回空（账户不存在）→ 200，data.balance_fen=0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_account_not_exists():
    """账户不存在时返回零值对象，不返回 404"""
    set_cfg_result = MagicMock()
    main_result = _make_result_first(None)  # row is None → 走 empty 分支

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/account?company_id={TENANT}&member_id={EMPLOYEE_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["balance_fen"] == 0
    assert data["meal_count_remaining"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /order — INSERT RETURNING id 成功，data 含 order_id 字段
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_post_order_success():
    """正常下单：INSERT RETURNING 返回 id → 200，data.order_id 非空"""
    new_order_id = uuid.uuid4()

    # result.first() 返回包含 id 的行（RETURNING id）
    set_cfg_result = MagicMock()
    insert_result = _make_result_first_raw((new_order_id,))

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, insert_result])

    payload = {
        "company_id": TENANT,
        "store_id": STORE_ID,
        "employee_id": EMPLOYEE_ID,
        "meal_date": "2026-03-31",
        "meal_type": "lunch",
        "total_fen": 2800,
        "items": [
            {
                "dish_id": "dish-001",
                "dish_name": "红烧肉",
                "qty": 1,
                "unit_price_fen": 2800,
                "date": "2026-03-31",
                "meal_type": "lunch",
            }
        ],
    }

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post("/api/v1/trade/enterprise/order", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "order_id" in data
    assert data["order_id"] == str(new_order_id)
    assert data["status"] == "accepted"
    assert data["total_fen"] == 2800
    assert data["items_count"] == 1
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /order — DB 抛 SQLAlchemyError，路由兜底返回 ok=True + 调用 rollback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_post_order_db_error():
    """INSERT 抛 SQLAlchemyError → 路由 except 兜底，仍返回 200/ok=True，并调用 rollback"""
    set_cfg_result = MagicMock()

    db = make_mock_db()
    # 第一次 execute（_set_tenant）成功，第二次（INSERT）抛异常
    db.execute = AsyncMock(side_effect=[set_cfg_result, SQLAlchemyError("connection lost")])

    payload = {
        "company_id": TENANT,
        "store_id": STORE_ID,
        "employee_id": EMPLOYEE_ID,
        "meal_date": "2026-03-31",
        "meal_type": "lunch",
        "total_fen": 1500,
        "items": [
            {
                "dish_id": "dish-002",
                "dish_name": "蒸鱼",
                "qty": 1,
                "unit_price_fen": 1500,
                "date": "2026-03-31",
                "meal_type": "lunch",
            }
        ],
    }

    app = _make_app(db)
    client = TestClient(app)
    resp = client.post("/api/v1/trade/enterprise/order", json=payload)

    # 路由 except SQLAlchemyError 分支：不抛异常，仍返回 ok=True
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "accepted"
    assert data["total_fen"] == 1500
    # rollback 必须被调用
    db.rollback.assert_awaited_once()
    # commit 不应被调用
    db.commit.assert_not_awaited()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /meal-orders — SELECT 返回2条订单，data.items 长度=2
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_meal_orders_success():
    """SELECT 返回2条订单 → 200，data.items 长度为2"""
    row1 = _order_row()
    row2 = _order_row()

    set_cfg_result = MagicMock()
    main_result = _make_result_all([row1, row2])

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/meal-orders?company_id={TENANT}&member_id={EMPLOYEE_ID}&month=2026-03")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert len(data["items"]) == 2
    assert data["total"] == 2
    # 验证订单字段结构
    item = data["items"][0]
    assert "id" in item
    assert "meal_date" in item
    assert "amount_fen" in item
    assert item["amount_fen"] == 2800
    assert item["status"] == "confirmed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /meal-orders — SELECT 返回空列表，data.items=[]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_get_meal_orders_empty():
    """SELECT 返回空 → 200，data.items=[]，data.total=0"""
    set_cfg_result = MagicMock()
    main_result = _make_result_all([])

    db = make_mock_db()
    db.execute = AsyncMock(side_effect=[set_cfg_result, main_result])

    app = _make_app(db)
    client = TestClient(app)
    resp = client.get(f"/api/v1/trade/enterprise/meal-orders?company_id={TENANT}&month=2026-03")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["items"] == []
    assert data["total"] == 0
