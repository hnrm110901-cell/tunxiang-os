"""扩展路由测试 — group_routes.py (8端点) + gdpr_routes.py (7端点)

选取端点最多、尚无测试的两个路由文件，各覆盖5个场景（共10个）：

group_routes.py (8 端点):
1.  POST /api/v1/member/groups                          — 正常创建品牌组
2.  POST /api/v1/member/groups                          — 无 X-Group-Admin header → 403
3.  GET  /api/v1/member/groups/{group_id}               — 正常获取，返回详情
4.  GET  /api/v1/member/groups/{group_id}               — 组不存在 → 404
5.  POST /api/v1/member/groups/{group_id}/stored-value-interop — operator_id 格式非法 → 422

gdpr_routes.py (7 端点):
6.  POST /api/v1/member/gdpr/requests                   — 正常提交 erasure 申请 → 201
7.  POST /api/v1/member/gdpr/requests                   — request_type 非法 → 422
8.  GET  /api/v1/member/gdpr/requests                   — 正常列表查询
9.  GET  /api/v1/member/gdpr/requests/{id}              — 请求不存在 → 404
10. POST /api/v1/member/gdpr/requests/{id}/review       — GDPRService 抛 ValueError → 400
"""

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# sys.path: 指向 src/ 目录
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# 全局存根注入（必须在 import 路由前完成）
# ---------------------------------------------------------------------------


def _inject_stubs():
    """向 sys.modules 注入路由文件依赖的第三方/内部存根。"""

    # --- structlog ---
    if "structlog" not in sys.modules:
        structlog_mod = types.ModuleType("structlog")
        structlog_mod.get_logger = MagicMock(return_value=MagicMock())
        sys.modules["structlog"] = structlog_mod

    # --- shared.ontology.src.database ---
    db_mod = types.ModuleType("shared.ontology.src.database")

    async def _fake_get_db_with_tenant(tenant_id):  # noqa: ARG001
        yield AsyncMock()

    db_mod.get_db_with_tenant = _fake_get_db_with_tenant
    db_mod.get_db_session = MagicMock()  # group_routes 用 get_db_session
    db_mod.get_db = MagicMock()
    for key in ("shared", "shared.ontology", "shared.ontology.src"):
        sys.modules.setdefault(key, types.ModuleType(key))
    sys.modules["shared.ontology.src.database"] = db_mod

    # --- models.group_config (BrandGroup ORM model stub) ---
    group_config_mod = types.ModuleType("models.group_config")
    # BrandGroup 是被 db.add() 用到的 ORM 对象，用 MagicMock 充当构造器
    BrandGroupStub = MagicMock()
    group_config_mod.BrandGroup = BrandGroupStub
    sys.modules.setdefault("models", types.ModuleType("models"))
    sys.modules["models.group_config"] = group_config_mod

    # --- services.group_analytics ---
    group_analytics_mod = types.ModuleType("services.group_analytics")
    _analytics_svc = MagicMock()
    _analytics_svc.get_group_rfm_dashboard = AsyncMock(return_value={"summary": "ok"})
    _analytics_svc.get_group_member_profile = AsyncMock(return_value={})
    _analytics_svc.get_group_churn_risk = AsyncMock(return_value={})
    _analytics_svc.find_cross_brand_customers = AsyncMock(return_value=[])
    _analytics_svc.configure_stored_value_interop = AsyncMock(return_value={"interop": True})
    GroupAnalyticsServiceStub = MagicMock(return_value=_analytics_svc)
    group_analytics_mod.GroupAnalyticsService = GroupAnalyticsServiceStub
    sys.modules.setdefault("services", types.ModuleType("services"))
    sys.modules["services.group_analytics"] = group_analytics_mod

    # --- api.services.gdpr_service (相对导入 ..services.gdpr_service) ---
    # gdpr_routes 使用 `from ..services.gdpr_service import REQUEST_TYPES, GDPRService`
    # 注入到 `api.services.gdpr_service` 和 `services.gdpr_service` 两个路径
    gdpr_svc_mod = types.ModuleType("services.gdpr_service")
    gdpr_svc_mod.REQUEST_TYPES = ("erasure", "portability", "restriction")
    gdpr_svc_mod.GDPRService = MagicMock()
    sys.modules["services.gdpr_service"] = gdpr_svc_mod
    # 相对导入展开后会被解析为 api.services.gdpr_service
    sys.modules.setdefault("api", types.ModuleType("api"))
    sys.modules.setdefault("api.services", types.ModuleType("api.services"))
    api_gdpr_mod = types.ModuleType("api.services.gdpr_service")
    api_gdpr_mod.REQUEST_TYPES = gdpr_svc_mod.REQUEST_TYPES
    api_gdpr_mod.GDPRService = gdpr_svc_mod.GDPRService
    sys.modules["api.services.gdpr_service"] = api_gdpr_mod


_inject_stubs()


# ---------------------------------------------------------------------------
# 导入路由（存根注入完成后）
# ---------------------------------------------------------------------------

import importlib

# gdpr_routes 有相对导入，需要用 importlib 绕开包级别检查
# 先把 api 包的 __package__ 设置好，再 import
# group_routes 使用绝对导入，直接导入即可
from api.group_routes import router as group_router

from shared.ontology.src.database import get_db_session  # group_routes 依赖此函数

# gdpr_routes 使用 from ..services.gdpr_service，需以包方式导入
gdpr_mod = importlib.import_module("api.gdpr_routes")
gdpr_router = gdpr_mod.router
_get_tenant_db = gdpr_mod._get_tenant_db


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

TENANT = str(uuid.uuid4())
GROUP_ADMIN_HEADERS = {
    "X-Group-Admin": "true",
    "X-Tenant-ID": TENANT,
}
GDPR_HEADERS = {"X-Tenant-ID": TENANT}

GROUP_ID = str(uuid.uuid4())


def make_mock_db() -> AsyncMock:
    """构造 AsyncSession mock。"""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def override_db(session: AsyncMock):
    """生成 FastAPI 依赖覆盖函数（async generator）。"""

    async def _dep():
        yield session

    return _dep


# ---------------------------------------------------------------------------
# App: group_routes
# ---------------------------------------------------------------------------

group_app = FastAPI()
group_app.include_router(group_router)


# ---------------------------------------------------------------------------
# App: gdpr_routes
# ---------------------------------------------------------------------------

gdpr_app = FastAPI()
gdpr_app.include_router(gdpr_router)


# ============================================================================
# ★ group_routes.py — 5 个测试
# ============================================================================

# ── 测试1: POST /groups — 正常创建品牌组 ────────────────────────────────────


def test_group_create_success():
    """正常创建品牌组：DB flush/commit 成功，返回 ok=True 含 group_id。"""
    db = make_mock_db()

    # BrandGroup 实例需要有 .id / .group_code / .group_name / .brand_tenant_ids 属性
    fake_group = MagicMock()
    fake_group.id = uuid.uuid4()
    fake_group.group_code = "TX_TEST"
    fake_group.group_name = "测试集团"
    fake_group.brand_tenant_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    # 让 BrandGroup 构造器返回 fake_group
    import api.group_routes as gr_mod

    original_bg = gr_mod.BrandGroup
    gr_mod.BrandGroup = MagicMock(return_value=fake_group)

    group_app.dependency_overrides[get_db_session] = override_db(db)
    client = TestClient(group_app)

    resp = client.post(
        "/api/v1/member/groups",
        json={
            "group_name": "测试集团",
            "group_code": "TX_TEST",
            "brand_tenant_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            "stored_value_interop": False,
            "member_data_shared": True,
            "operator_id": str(uuid.uuid4()),
        },
        headers=GROUP_ADMIN_HEADERS,
    )

    gr_mod.BrandGroup = original_bg  # 还原
    group_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "group_id" in body["data"]
    assert body["data"]["brand_count"] == 2


# ── 测试2: POST /groups — 缺少 X-Group-Admin header → 403 ─────────────────


def test_group_create_missing_admin_header():
    """缺少 X-Group-Admin: true header，鉴权拦截 → 403。"""
    db = make_mock_db()
    group_app.dependency_overrides[get_db_session] = override_db(db)
    client = TestClient(group_app)

    resp = client.post(
        "/api/v1/member/groups",
        json={
            "group_name": "测试集团",
            "group_code": "TX_NOADMIN",
            "brand_tenant_ids": [],
        },
        headers={"X-Tenant-ID": TENANT},  # 故意不传 X-Group-Admin: true
    )

    group_app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert "group_admin_required" in resp.json()["detail"]


# ── 测试3: GET /groups/{group_id} — 正常获取集团详情 ─────────────────────────


def test_group_get_detail_success():
    """正常查询品牌组详情，DB 返回记录 → 200，ok=True。"""
    import datetime

    db = make_mock_db()

    fake_group = MagicMock()
    fake_group.id = uuid.UUID(GROUP_ID)
    fake_group.group_name = "测试集团"
    fake_group.group_code = "TX_TEST"
    fake_group.brand_tenant_ids = [str(uuid.uuid4())]
    fake_group.stored_value_interop = False
    fake_group.member_data_shared = True
    fake_group.status = "active"
    fake_group.created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    fake_group.updated_at = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    # DB execute 调用顺序：set_config → SELECT
    set_cfg_result = MagicMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=fake_group)
    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    group_app.dependency_overrides[get_db_session] = override_db(db)
    client = TestClient(group_app)

    resp = client.get(
        f"/api/v1/member/groups/{GROUP_ID}",
        headers=GROUP_ADMIN_HEADERS,
    )

    group_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["group_code"] == "TX_TEST"
    assert body["data"]["brand_count"] == 1


# ── 测试4: GET /groups/{group_id} — 组不存在 → 404 ──────────────────────────


def test_group_get_detail_not_found():
    """DB 返回 None → HTTPException 404 brand_group_not_found。"""
    db = make_mock_db()

    set_cfg_result = MagicMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(side_effect=[set_cfg_result, select_result])

    group_app.dependency_overrides[get_db_session] = override_db(db)
    client = TestClient(group_app)

    resp = client.get(
        f"/api/v1/member/groups/{GROUP_ID}",
        headers=GROUP_ADMIN_HEADERS,
    )

    group_app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert resp.json()["detail"] == "brand_group_not_found"


# ── 测试5: POST /groups/{group_id}/stored-value-interop — operator_id 格式非法 → 422 ──


def test_group_interop_invalid_operator_id():
    """operator_id 格式非法（非 UUID）→ HTTPException 422。"""
    db = make_mock_db()

    group_app.dependency_overrides[get_db_session] = override_db(db)
    client = TestClient(group_app)

    resp = client.post(
        f"/api/v1/member/groups/{GROUP_ID}/stored-value-interop",
        json={"interop": True, "operator_id": "not-a-uuid"},
        headers=GROUP_ADMIN_HEADERS,
    )

    group_app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert "invalid operator_id" in resp.json()["detail"]


# ============================================================================
# ★ gdpr_routes.py — 5 个测试
# ============================================================================

# ── 测试6: POST /gdpr/requests — 正常提交 erasure 申请 → 201 ────────────────


def test_gdpr_create_request_success():
    """正常提交 erasure 申请，GDPRService.create_request 成功 → 201，ok=True。"""
    db = make_mock_db()
    customer_id = str(uuid.uuid4())

    # 构造 GDPRService mock：create_request 返回模拟结果
    fake_svc = MagicMock()
    fake_svc.create_request = AsyncMock(
        return_value={
            "id": str(uuid.uuid4()),
            "customer_id": customer_id,
            "request_type": "erasure",
            "status": "pending",
        }
    )

    import api.gdpr_routes as gdpr_route_mod

    original_cls = gdpr_route_mod.GDPRService
    gdpr_route_mod.GDPRService = MagicMock(return_value=fake_svc)

    gdpr_app.dependency_overrides[_get_tenant_db] = override_db(db)
    client = TestClient(gdpr_app)

    resp = client.post(
        "/api/v1/member/gdpr/requests",
        json={
            "customer_id": customer_id,
            "request_type": "erasure",
            "requested_by": "李大明",
            "note": "本人申请删除",
        },
        headers=GDPR_HEADERS,
    )

    gdpr_route_mod.GDPRService = original_cls
    gdpr_app.dependency_overrides.clear()

    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["request_type"] == "erasure"


# ── 测试7: POST /gdpr/requests — request_type 非法 → 422 ────────────────────


def test_gdpr_create_request_invalid_type():
    """request_type 不在 (erasure/portability/restriction) → Pydantic 校验失败 → 422。"""
    db = make_mock_db()

    gdpr_app.dependency_overrides[_get_tenant_db] = override_db(db)
    client = TestClient(gdpr_app)

    resp = client.post(
        "/api/v1/member/gdpr/requests",
        json={
            "customer_id": str(uuid.uuid4()),
            "request_type": "deletion",  # 非法类型
        },
        headers=GDPR_HEADERS,
    )

    gdpr_app.dependency_overrides.clear()

    assert resp.status_code == 422


# ── 测试8: GET /gdpr/requests — 正常列表查询 ────────────────────────────────


def test_gdpr_list_requests_success():
    """正常查询 GDPR 请求列表，GDPRService.list_requests 返回2条记录。"""
    db = make_mock_db()
    cid = str(uuid.uuid4())

    fake_items = [
        {"id": str(uuid.uuid4()), "customer_id": cid, "request_type": "erasure", "status": "pending"},
        {"id": str(uuid.uuid4()), "customer_id": cid, "request_type": "portability", "status": "executed"},
    ]
    fake_svc = MagicMock()
    fake_svc.list_requests = AsyncMock(return_value=fake_items)

    import api.gdpr_routes as gdpr_route_mod

    original_cls = gdpr_route_mod.GDPRService
    gdpr_route_mod.GDPRService = MagicMock(return_value=fake_svc)

    gdpr_app.dependency_overrides[_get_tenant_db] = override_db(db)
    client = TestClient(gdpr_app)

    resp = client.get(
        "/api/v1/member/gdpr/requests",
        params={"customer_id": cid},
        headers=GDPR_HEADERS,
    )

    gdpr_route_mod.GDPRService = original_cls
    gdpr_app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2


# ── 测试9: GET /gdpr/requests/{id} — 请求不存在 → 404 ──────────────────────


def test_gdpr_get_request_not_found():
    """GDPRService.get_request 返回 None → HTTPException 404。"""
    db = make_mock_db()
    req_id = str(uuid.uuid4())

    fake_svc = MagicMock()
    fake_svc.get_request = AsyncMock(return_value=None)

    import api.gdpr_routes as gdpr_route_mod

    original_cls = gdpr_route_mod.GDPRService
    gdpr_route_mod.GDPRService = MagicMock(return_value=fake_svc)

    gdpr_app.dependency_overrides[_get_tenant_db] = override_db(db)
    client = TestClient(gdpr_app)

    resp = client.get(
        f"/api/v1/member/gdpr/requests/{req_id}",
        headers=GDPR_HEADERS,
    )

    gdpr_route_mod.GDPRService = original_cls
    gdpr_app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert req_id in resp.json()["detail"]


# ── 测试10: POST /gdpr/requests/{id}/review — ValueError → 400 ──────────────


def test_gdpr_review_request_value_error():
    """GDPRService.review_request 抛 ValueError（如状态机非法转换）→ HTTPException 400。"""
    db = make_mock_db()
    req_id = str(uuid.uuid4())

    fake_svc = MagicMock()
    fake_svc.review_request = AsyncMock(side_effect=ValueError("请求已审核，不可重复操作"))

    import api.gdpr_routes as gdpr_route_mod

    original_cls = gdpr_route_mod.GDPRService
    gdpr_route_mod.GDPRService = MagicMock(return_value=fake_svc)

    gdpr_app.dependency_overrides[_get_tenant_db] = override_db(db)
    client = TestClient(gdpr_app)

    resp = client.post(
        f"/api/v1/member/gdpr/requests/{req_id}/review",
        json={
            "approved": False,
            "reviewed_by": "admin_001",
            "rejection_reason": "信息不完整",
        },
        headers=GDPR_HEADERS,
    )

    gdpr_route_mod.GDPRService = original_cls
    gdpr_app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert "请求已审核" in resp.json()["detail"]
