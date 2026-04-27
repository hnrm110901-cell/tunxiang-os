"""会员生命周期测试 — address_routes + invite_routes + lifecycle_routes + lifecycle_router

覆盖场景（共 15 个）：

address_routes.py（5个）：
1.  GET  /api/v1/member/addresses         — 正常获取列表
2.  POST /api/v1/member/addresses         — 缺少必填字段 → 422
3.  GET  /api/v1/member/addresses/{id}    — 地址不存在 → ok=False
4.  DELETE /api/v1/member/addresses/{id} — 正常软删除
5.  PUT  /api/v1/member/addresses/{id}/default — 地址不存在 → 404

invite_routes.py（4个）：
6.  GET  /api/v1/member/invite/my-code   — 已有邀请码
7.  GET  /api/v1/member/invite/records   — 正常分页
8.  POST /api/v1/member/invite/claim     — 邀请码无效 → 404
9.  POST /api/v1/member/invite/claim     — 重复使用 → 409

lifecycle_routes.py（3个）：
10. GET  /api/v1/lifecycle/stats          — 正常统计（LifecycleService mock）
11. GET  /api/v1/lifecycle/members?stage=active — 正常列表
12. GET  /api/v1/lifecycle/members?stage=bad  — 无效 stage → 400

lifecycle_router.py（3个）：
13. GET  /api/v1/members/lifecycle/distribution — 正常分布
14. GET  /api/v1/members/lifecycle/at-risk      — 正常风险列表
15. GET  /api/v1/members/{id}/lifecycle         — 会员不存在 → 404
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── sys.path ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── 共享存根注入（在 import 路由前） ─────────────────────────────────────


def _inject_stubs():
    # shared.ontology.src.database
    db_mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    db_mod.get_db_with_tenant = _fake_get_db_with_tenant
    db_mod.get_db = MagicMock()
    sys.modules.setdefault("shared", types.ModuleType("shared"))
    sys.modules.setdefault("shared.ontology", types.ModuleType("shared.ontology"))
    sys.modules.setdefault("shared.ontology.src", types.ModuleType("shared.ontology.src"))
    sys.modules["shared.ontology.src.database"] = db_mod

    # structlog
    structlog_mod = types.ModuleType("structlog")
    structlog_mod.get_logger = MagicMock(return_value=MagicMock())
    sys.modules.setdefault("structlog", structlog_mod)

    # shared.events.src.emitter
    emitter_mod = types.ModuleType("shared.events.src.emitter")
    emitter_mod.emit_event = AsyncMock(return_value=None)
    sys.modules.setdefault("shared.events", types.ModuleType("shared.events"))
    sys.modules.setdefault("shared.events.src", types.ModuleType("shared.events.src"))
    sys.modules["shared.events.src.emitter"] = emitter_mod

    # shared.events.src.event_types
    event_types_mod = types.ModuleType("shared.events.src.event_types")
    for name in ("MemberEventType", "SettlementEventType", "OrderEventType"):
        cls = MagicMock()
        setattr(event_types_mod, name, cls)
    sys.modules["shared.events.src.event_types"] = event_types_mod

    # src / api 路径别名（相对导入用）
    sys.modules.setdefault("src", types.ModuleType("src"))
    sys.modules.setdefault("src.services", types.ModuleType("src.services"))
    sys.modules.setdefault("api", types.ModuleType("api"))

    # lifecycle_service stub（供 lifecycle_routes 和 lifecycle_router 的相对导入）
    _lc_svc_mod = types.ModuleType("services.lifecycle_service")
    _mock_lc_svc = MagicMock()
    _mock_lc_svc.DEFAULT_THRESHOLDS = {"new": 30, "active": 30, "dormant": 60}
    _mock_lc_svc.get_lifecycle_stats = AsyncMock(
        return_value={"new": 5, "active": 20, "dormant": 3, "churned": 1, "reactivated": 2, "total": 31}
    )
    _mock_lc_svc.batch_reclassify = AsyncMock(
        return_value={"new": 5, "active": 20, "dormant": 3, "churned": 1, "reactivated": 2, "changed": 4}
    )
    _lc_svc_mod.LifecycleService = MagicMock(return_value=_mock_lc_svc)
    sys.modules["services.lifecycle_service"] = _lc_svc_mod
    sys.modules["src.services.lifecycle_service"] = _lc_svc_mod

    # api.services.lifecycle_service（相对导入解析）
    sys.modules.setdefault("api.services", types.ModuleType("api.services"))
    _api_lc_mod = types.ModuleType("api.services.lifecycle_service")
    _api_lc_mod.LifecycleService = MagicMock(return_value=_mock_lc_svc)
    sys.modules["api.services.lifecycle_service"] = _api_lc_mod

    # ..services.lifecycle_service 以 "api.api.services.lifecycle_service" 形式解析
    sys.modules.setdefault("api.api", types.ModuleType("api.api"))
    sys.modules.setdefault("api.api.services", types.ModuleType("api.api.services"))
    _aa_lc_mod = types.ModuleType("api.api.services.lifecycle_service")
    _aa_lc_mod.LifecycleService = MagicMock(return_value=_mock_lc_svc)
    sys.modules["api.api.services.lifecycle_service"] = _aa_lc_mod

    return _mock_lc_svc


_MOCK_LC_SVC = _inject_stubs()


# ─── 辅助 ─────────────────────────────────────────────────────────────────


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 加载路由模块 ─────────────────────────────────────────────────────────
import importlib  # noqa: E402

# --- address_routes ---
addr_mod = importlib.import_module("api.address_routes")
addr_app = FastAPI()
addr_app.include_router(addr_mod.router)


def _addr_override(db_mock):
    async def _dep():
        return db_mock

    addr_app.dependency_overrides[addr_mod.get_db] = _dep


# --- invite_routes ---
invite_mod = importlib.import_module("api.invite_routes")
invite_app = FastAPI()
invite_app.include_router(invite_mod.router)


def _invite_override(db_mock):
    async def _dep():
        return db_mock

    invite_app.dependency_overrides[invite_mod.get_db] = _dep


# --- lifecycle_routes (相对导入 ..services.lifecycle_service) ---
# 需要通过 patch 注入服务单例
with patch.dict(
    sys.modules,
    {
        "services.lifecycle_service": sys.modules["services.lifecycle_service"],
    },
):
    lc_mod = importlib.import_module("api.lifecycle_routes")

lc_app = FastAPI()
lc_app.include_router(lc_mod.router)
# 注入模块级 _service 单例
lc_mod._service = _MOCK_LC_SVC


def _lc_override(db_mock):
    async def _dep():
        return db_mock

    lc_app.dependency_overrides[lc_mod.get_db] = _dep


# --- lifecycle_router ---
with patch.dict(
    sys.modules,
    {
        "services.lifecycle_service": sys.modules["services.lifecycle_service"],
    },
):
    lcr_mod = importlib.import_module("api.lifecycle_router")

lcr_app = FastAPI()
lcr_app.include_router(lcr_mod.router)
lcr_mod._service = _MOCK_LC_SVC


def _lcr_override(db_mock):
    async def _dep():
        return db_mock

    lcr_app.dependency_overrides[lcr_mod.get_db] = _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ address_routes — 5 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 1: GET /addresses — 正常列表
def test_addr_list_ok():
    """正常查询地址列表，返回 ok=True 和空列表。"""
    db = AsyncMock()
    fake_result = MagicMock()
    fake_result.all.return_value = []
    db.execute = AsyncMock(return_value=fake_result)
    _addr_override(db)

    client = TestClient(addr_app)
    resp = client.get(
        "/api/v1/member/addresses",
        params={"customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# 场景 2: POST /addresses — 缺少必填字段 → 422
def test_addr_create_missing_fields():
    """创建地址缺少 name 和 phone 时，Pydantic 返回 422。"""
    client = TestClient(addr_app)
    resp = client.post(
        "/api/v1/member/addresses",
        json={"customer_id": _uid()},  # 缺少 name, phone
        headers=HEADERS,
    )
    assert resp.status_code == 422


# 场景 3: GET /addresses/{id} — 地址不存在 → ok=False
def test_addr_get_not_found():
    """地址不存在时返回 ok=False，消息包含"地址不存在"。"""
    db = AsyncMock()
    fake_result = MagicMock()
    fake_result.first.return_value = None
    db.execute = AsyncMock(return_value=fake_result)
    _addr_override(db)

    client = TestClient(addr_app)
    resp = client.get(
        f"/api/v1/member/addresses/{_uid()}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "地址不存在" in body["error"]["message"]


# 场景 4: DELETE /addresses/{id} — 正常软删除
def test_addr_delete_ok():
    """软删除地址成功，返回 ok=True。"""
    db = AsyncMock()
    fake_result = MagicMock()
    db.execute = AsyncMock(return_value=fake_result)
    _addr_override(db)

    client = TestClient(addr_app)
    resp = client.delete(
        f"/api/v1/member/addresses/{_uid()}",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# 场景 5: PUT /addresses/{id}/default — 地址不存在 → 404
def test_addr_set_default_not_found():
    """设置默认地址时地址不存在应返回 404。"""
    db = AsyncMock()
    # _set_rls 调用（第1次） + _clear_default（第2次） + 更新查询（第3次 → first()=None）
    clear_result = MagicMock()
    not_found_result = MagicMock()
    not_found_result.first.return_value = None
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            clear_result,  # _clear_default
            not_found_result,  # UPDATE ... RETURNING id
        ]
    )
    _addr_override(db)

    client = TestClient(addr_app)
    resp = client.put(
        f"/api/v1/member/addresses/{_uid()}/default",
        params={"customer_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "地址不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ invite_routes — 4 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 6: GET /invite/my-code — 已有邀请码
def test_invite_my_code_existing():
    """会员已有邀请码时直接返回，不需写入新记录。"""
    db = AsyncMock()
    existing_row = MagicMock()
    existing_row.__getitem__ = lambda self, i: ["TXABC123", 3, 150][i]
    select_result = MagicMock()
    select_result.first.return_value = existing_row
    db.execute = AsyncMock(side_effect=[MagicMock(), select_result])  # _set_rls + SELECT
    _invite_override(db)

    client = TestClient(invite_app)
    resp = client.get(
        "/api/v1/member/invite/my-code",
        params={"member_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["code"] == "TXABC123"
    assert body["data"]["invited_count"] == 3


# 场景 7: GET /invite/records — 正常分页返回
def test_invite_records_ok():
    """邀请记录正常分页，返回 ok=True 和 summary。"""
    db = AsyncMock()
    summary_mock = MagicMock()
    summary_mock.__getitem__ = lambda self, i: [5, 250, 0][i]
    summary_result = MagicMock()
    summary_result.first.return_value = summary_mock

    cnt_result = MagicMock()
    cnt_result.scalar.return_value = 5

    rows_result = MagicMock()
    rows_result.all.return_value = []

    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            summary_result,  # summary 汇总
            cnt_result,  # COUNT(*)
            rows_result,  # 明细
        ]
    )
    _invite_override(db)

    client = TestClient(invite_app)
    resp = client.get(
        "/api/v1/member/invite/records",
        params={"member_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "summary" in body["data"]
    assert body["data"]["total"] == 5


# 场景 8: POST /invite/claim — 邀请码无效 → 404
def test_invite_claim_invalid_code():
    """邀请码不存在时返回 404。"""
    db = AsyncMock()
    code_result = MagicMock()
    code_result.first.return_value = None
    db.execute = AsyncMock(side_effect=[MagicMock(), code_result])  # _set_rls + SELECT code

    _invite_override(db)

    client = TestClient(invite_app)
    resp = client.post(
        "/api/v1/member/invite/claim",
        json={"invite_code": "TXNOTEXIST", "new_member_id": _uid()},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "邀请码无效" in resp.json()["detail"]


# 场景 9: POST /invite/claim — 重复使用 → 409
def test_invite_claim_duplicate():
    """同一用户重复使用邀请码，IntegrityError → 409。"""
    from sqlalchemy.exc import IntegrityError

    member_id = _uid()
    inviter_id = _uid()

    db = AsyncMock()
    code_rec = MagicMock()
    code_rec.__getitem__ = lambda self, i: [uuid.UUID(inviter_id), uuid.UUID(inviter_id)][i]
    code_result = MagicMock()
    code_result.first.return_value = code_rec

    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            code_result,  # SELECT invite_codes
            IntegrityError("", None, None),  # INSERT invite_records 冲突
        ]
    )

    _invite_override(db)

    client = TestClient(invite_app)
    resp = client.post(
        "/api/v1/member/invite/claim",
        json={"invite_code": "TXABC123", "new_member_id": member_id},
        headers=HEADERS,
    )

    assert resp.status_code == 409
    assert "已使用过邀请码" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ lifecycle_routes — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 10: GET /lifecycle/stats — 正常统计
def test_lifecycle_stats_ok():
    """stats 接口正常调用 LifecycleService，返回各阶段数量。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    _lc_override(db)
    _MOCK_LC_SVC.get_lifecycle_stats = AsyncMock(
        return_value={"new": 5, "active": 20, "dormant": 3, "churned": 1, "reactivated": 2, "total": 31}
    )

    client = TestClient(lc_app)
    resp = client.get(
        "/api/v1/lifecycle/stats",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 31
    assert "as_of" in body["data"]


# 场景 11: GET /lifecycle/members?stage=active — 正常列表
def test_lifecycle_members_active_ok():
    """查询 active 阶段会员，返回 ok=True 和分页数据。"""
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(),  # _set_rls
            count_result,  # COUNT(*)
            rows_result,  # SELECT list
        ]
    )
    _lc_override(db)

    client = TestClient(lc_app)
    resp = client.get(
        "/api/v1/lifecycle/members",
        params={"stage": "active"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# 场景 12: GET /lifecycle/members?stage=invalid — 无效 stage → 400
def test_lifecycle_members_invalid_stage():
    """无效 stage 参数返回 400。"""
    client = TestClient(lc_app)
    resp = client.get(
        "/api/v1/lifecycle/members",
        params={"stage": "zombie"},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "stage" in resp.json()["detail"].lower() or "stage" in resp.json().get("detail", "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ★ lifecycle_router — 3 个测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# 场景 13: GET /members/lifecycle/distribution — 正常分布
def test_lcr_distribution_ok():
    """生命周期分布接口正常返回各阶段数量。"""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.fetchall.return_value = [("active", 30), ("churned", 5)]
    db.execute = AsyncMock(side_effect=[MagicMock(), rows_result])  # _set_rls + SELECT
    _lcr_override(db)

    client = TestClient(lcr_app)
    resp = client.get(
        "/api/v1/members/lifecycle/distribution",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 35
    stage_names = [s["stage"] for s in body["data"]["stages"]]
    assert "active" in stage_names


# 场景 14: GET /members/lifecycle/at-risk — 正常风险列表
def test_lcr_at_risk_ok():
    """流失风险会员列表接口正常返回（空列表）。"""
    db = AsyncMock()
    rows_result = MagicMock()
    rows_result.fetchall.return_value = []
    db.execute = AsyncMock(side_effect=[MagicMock(), rows_result])
    _lcr_override(db)

    client = TestClient(lcr_app)
    resp = client.get(
        "/api/v1/members/lifecycle/at-risk",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0


# 场景 15: GET /members/{id}/lifecycle — 会员不存在 → 404
def test_lcr_member_lifecycle_not_found():
    """查询不存在的会员生命周期应返回 404。"""
    db = AsyncMock()
    not_found_result = MagicMock()
    not_found_result.fetchone.return_value = None
    db.execute = AsyncMock(side_effect=[MagicMock(), not_found_result])  # _set_rls + SELECT
    _lcr_override(db)

    client = TestClient(lcr_app)
    resp = client.get(
        f"/api/v1/members/{_uid()}/lifecycle",
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "会员不存在" in resp.json()["detail"]
