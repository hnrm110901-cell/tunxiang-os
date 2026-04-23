"""会员等级运营 API 测试 — api/member_level_routes.py

覆盖场景：
1.  GET  /api/v1/member/level-configs              — mock SELECT 返回2条配置 → 200，data.items 长度=2
2.  POST /api/v1/member/level-configs              — mock 重复检查（无重复）+ INSERT → 200，data 含 id
3.  POST /api/v1/member/level-configs              — mock 重复检查返回已存在 → 409
4.  PUT  /api/v1/member/level-configs/{id}         — mock UPDATE RETURNING 1行 → 200
5.  PUT  /api/v1/member/level-configs/{id}         — mock UPDATE RETURNING 空 → 404
6.  POST /api/v1/members/{mid}/check-upgrade       — 积分=500，年消费=0，只有 normal(min=0) → upgraded=False
7.  POST /api/v1/members/{mid}/check-upgrade       — 积分=5000 超过 silver 阈值 → upgraded=True，to_level=silver
8.  POST /api/v1/members/{mid}/points/earn         — mock 积分规则1条 + UPSERT → 200，earned_points>0
9.  GET  /api/v1/member/points-rules               — mock SELECT 返回2条规则 → 200
10. POST /api/v1/member/points-rules               — mock INSERT RETURNING → 200，data 含 id
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── sys.modules 注入存根，避免 shared.ontology 真实数据库连接 ───────────────


def _inject_stubs():
    """注入所需的存根模块，阻止真实 DB 初始化。"""
    # shared 包
    for mod_name in [
        "shared",
        "shared.ontology",
        "shared.ontology.src",
        "shared.ontology.src.database",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # get_db_with_tenant 存根（async generator，实际会被 override 掉）
    db_mod = sys.modules["shared.ontology.src.database"]

    async def _fake_get_db_with_tenant(tenant_id: str):
        db = AsyncMock(spec=AsyncSession)
        yield db

    db_mod.get_db_with_tenant = _fake_get_db_with_tenant

    # structlog 存根
    if "structlog" not in sys.modules:
        structlog_mod = types.ModuleType("structlog")
        structlog_mod.get_logger = lambda *a, **kw: MagicMock()
        sys.modules["structlog"] = structlog_mod


_inject_stubs()

# ─── 加载路由 ────────────────────────────────────────────────────────────────

from api.member_level_routes import _get_tenant_db, router  # noqa: E402

app = FastAPI()
app.include_router(router)

# ─── 测试工具 ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
CONFIG_ID = str(uuid.uuid4())

_HEADERS = {"X-Tenant-ID": TENANT_ID}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class _FakeMappings:
    """模拟 result.mappings() 返回对象，支持 .all()、.one()、.fetchone()。"""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        if not self._rows:
            raise Exception("No row found")
        return self._rows[0]

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeResult:
    """模拟 db.execute() 返回的结果对象。"""

    def __init__(self, rows=None, scalar_val=None, fetchone_val=None):
        self._rows = rows or []
        self._scalar_val = scalar_val
        self._fetchone_val = fetchone_val

    def mappings(self):
        return _FakeMappings(self._rows)

    def scalar(self):
        return self._scalar_val

    def fetchone(self):
        # 优先使用显式指定的 fetchone_val
        if self._fetchone_val is not None:
            return self._fetchone_val
        return self._rows[0] if self._rows else None


def _make_db(*results):
    """创建按顺序返回结果的 mock db session。"""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=list(results))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _override_db(db):
    """返回可直接作为 dependency_overrides 值的函数（同步 generator）。"""

    def _dep():
        return db

    return _dep


def _level_config_row(
    level_code="normal",
    level_name="普通",
    min_points=0,
    min_annual_spend_fen=0,
):
    """构造等级配置 mock 行（dict-like）。"""
    now = datetime.now(tz=timezone.utc)
    row = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(TENANT_ID),
        "level_code": level_code,
        "level_name": level_name,
        "min_points": min_points,
        "min_annual_spend_fen": min_annual_spend_fen,
        "discount_rate": 1.0,
        "birthday_bonus_multiplier": 1.0,
        "priority_queue": False,
        "free_delivery": False,
        "sort_order": 0,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    # 让 dict(row) 可用
    return row


def _points_rule_row():
    """构造积分规则 mock 行。"""
    now = datetime.now(tz=timezone.utc)
    return {
        "id": uuid.uuid4(),
        "tenant_id": uuid.UUID(TENANT_ID),
        "store_id": None,
        "rule_name": "消费积分",
        "earn_type": "consumption",
        "points_per_100fen": 1,
        "fixed_points": 0,
        "multiplier": 1.0,
        "valid_from": None,
        "valid_until": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /api/v1/member/level-configs — 返回2条配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_level_configs_success():
    """mock SELECT 返回2条配置 → 200，data.items 长度=2"""
    rows = [
        _level_config_row("normal", "普通", 0, 0),
        _level_config_row("silver", "银卡", 1000, 0),
    ]
    db = _make_db(_FakeResult(rows=rows))
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.get(
        f"/api/v1/member/level-configs?tenant_id={TENANT_ID}",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /api/v1/member/level-configs — 创建成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_level_config_success():
    """mock 重复检查（无重复）+ INSERT RETURNING → 200，data 含 id"""
    check_result = _FakeResult(rows=[])  # fetchone() → None（无重复）
    insert_result = _FakeResult(rows=[_level_config_row("gold", "金卡", 5000, 0)])

    db = _make_db(check_result, insert_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/level-configs",
        headers=_HEADERS,
        json={
            "level_code": "gold",
            "level_name": "金卡",
            "min_points": 5000,
            "min_annual_spend_fen": 0,
            "discount_rate": 0.9,
            "birthday_bonus_multiplier": 2.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "id" in body["data"]
    assert body["data"]["level_code"] == "gold"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /api/v1/member/level-configs — 重复 level_code → 409
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_level_config_duplicate():
    """mock SELECT 检查返回已存在记录 → 409"""
    # fetchone() 需要返回非 None，模拟已存在
    existing_row = (str(uuid.uuid4()),)  # tuple 模拟 DB row
    check_result = _FakeResult(fetchone_val=existing_row)

    db = _make_db(check_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/level-configs",
        headers=_HEADERS,
        json={
            "level_code": "silver",
            "level_name": "银卡",
            "min_points": 1000,
            "min_annual_spend_fen": 0,
            "discount_rate": 0.95,
            "birthday_bonus_multiplier": 1.5,
        },
    )
    assert resp.status_code == 409
    assert "已存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: PUT /api/v1/member/level-configs/{id} — 更新成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_update_level_config_success():
    """mock UPDATE RETURNING 1行 → 200，data 含更新后的字段"""
    updated_row = _level_config_row("silver", "银卡Plus", 1500, 0)
    update_result = _FakeResult(rows=[updated_row])

    db = _make_db(update_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.put(
        f"/api/v1/member/level-configs/{CONFIG_ID}",
        headers=_HEADERS,
        json={"level_name": "银卡Plus", "min_points": 1500},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "id" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: PUT /api/v1/member/level-configs/{id} — 配置不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_update_level_config_not_found():
    """mock UPDATE RETURNING 空 → 404"""
    update_result = _FakeResult(rows=[])  # mappings().fetchone() → None

    db = _make_db(update_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.put(
        f"/api/v1/member/level-configs/{CONFIG_ID}",
        headers=_HEADERS,
        json={"level_name": "不存在的配置"},
    )
    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /check-upgrade — 积分=500，只有 normal(min=0) → upgraded=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_check_upgrade_no_change():
    """积分500，年消费0，等级配置只有 normal(min=0) → upgraded=False"""
    # execute 调用顺序：
    # 1. 查积分余额 → fetchone() → (500,)
    # 2. 查年度消费 → fetchone() → (0,)
    # 3. 查等级配置 → mappings().all() → [normal]
    # 4. 查当前等级 → fetchone() → ("normal",)  （当前已是 normal，不升级）

    pts_result = _FakeResult(fetchone_val=(500,))
    spend_result = _FakeResult(fetchone_val=(0,))
    normal_config = {
        "level_code": "normal",
        "min_points": 0,
        "min_annual_spend_fen": 0,
    }
    configs_result = _FakeResult(rows=[normal_config])
    cur_level_result = _FakeResult(fetchone_val=("normal",))

    db = _make_db(pts_result, spend_result, configs_result, cur_level_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/check-upgrade",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["upgraded"] is False
    assert body["data"]["to_level"] == "normal"
    assert body["data"]["current_points"] == 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /check-upgrade — 积分=5000 超过 silver 阈值 → upgraded=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_check_upgrade_promoted():
    """积分5000超过 silver 阈值(1000) → upgraded=True，to_level=silver"""
    # execute 调用顺序：
    # 1. 查积分余额 → (5000,)
    # 2. 查年度消费 → (0,)
    # 3. 查等级配置（ORDER BY min_points DESC） → [silver(1000), normal(0)]
    # 4. 查当前等级 → ("normal",)
    # 5. UPDATE customers（容错，不影响结果）
    # 6. INSERT member_level_history

    pts_result = _FakeResult(fetchone_val=(5000,))
    spend_result = _FakeResult(fetchone_val=(0,))
    # 按 min_points DESC 排列
    configs_result = _FakeResult(
        rows=[
            {"level_code": "silver", "min_points": 1000, "min_annual_spend_fen": 0},
            {"level_code": "normal", "min_points": 0, "min_annual_spend_fen": 0},
        ]
    )
    cur_level_result = _FakeResult(fetchone_val=("normal",))
    update_customers_result = _FakeResult()  # UPDATE customers（容错）
    insert_history_result = _FakeResult()  # INSERT history

    db = _make_db(
        pts_result,
        spend_result,
        configs_result,
        cur_level_result,
        update_customers_result,
        insert_history_result,
    )
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/check-upgrade",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["upgraded"] is True
    assert body["data"]["to_level"] == "silver"
    assert body["data"]["from_level"] == "normal"
    assert body["data"]["current_points"] == 5000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /members/{mid}/points/earn — 积分规则存在 → earned_points>0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_earn_points_success():
    """mock 积分规则返回1条（points_per_100fen=1），mock UPSERT → 200，earned_points>0"""
    # execute 调用顺序：
    # 1. 查积分规则 → mappings().fetchone() → rule row
    # 2. UPSERT 积分余额 → fetchone() → (total_pts,)

    rule_row = {
        "points_per_100fen": 1,
        "fixed_points": 0,
        "multiplier": 1.0,
    }
    # amount_fen=1000 → base = (1000/100)*1 = 10，multiplier=1 → earned=10
    rules_result = _FakeResult(rows=[rule_row])  # mappings().fetchone() 取第一条
    upsert_result = _FakeResult(fetchone_val=(510,))  # 原500 + 10 = 510

    db = _make_db(rules_result, upsert_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/members/{MEMBER_ID}/points/earn",
        headers=_HEADERS,
        json={
            "earn_type": "consumption",
            "amount_fen": 1000,
            "order_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["earned_points"] > 0
    assert body["data"]["total_points"] == 510


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /api/v1/member/points-rules — 返回2条规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_points_rules_success():
    """mock SELECT 返回2条规则 → 200，data.items 长度=2"""
    rows = [_points_rule_row(), _points_rule_row()]
    rows[1]["earn_type"] = "birthday"
    rules_result = _FakeResult(rows=rows)

    db = _make_db(rules_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.get(
        "/api/v1/member/points-rules",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["items"]) == 2
    assert body["data"]["total"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: POST /api/v1/member/points-rules — 创建积分规则成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_create_points_rule_success():
    """mock INSERT RETURNING → 200，data 含 id"""
    new_row = _points_rule_row()
    new_row["rule_name"] = "生日双倍积分"
    new_row["earn_type"] = "birthday"
    new_row["fixed_points"] = 200
    new_row["multiplier"] = 2.0
    insert_result = _FakeResult(rows=[new_row])

    db = _make_db(insert_result)
    app.dependency_overrides[_get_tenant_db] = _override_db(db)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/member/points-rules",
        headers=_HEADERS,
        json={
            "rule_name": "生日双倍积分",
            "earn_type": "birthday",
            "points_per_100fen": 0,
            "fixed_points": 200,
            "multiplier": 2.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "id" in body["data"]
    assert body["data"]["earn_type"] == "birthday"
