"""交易支撑路由测试 — review + service_bell + store_management + dish_practice + approval

覆盖路由文件（5个）：
  review_routes.py            — 评价管理（纯 mock，无 DB）
  service_bell_routes.py      — 服务铃（依赖 get_db + service_bell_service 函数）
  store_management_routes.py  — 门店/桌台管理（纯 mock，无 DB）
  dish_practice_routes.py     — 菜品做法（依赖 dish_practice_service 模块）
  approval_routes.py          — 折扣审批（依赖 get_db + ApprovalService 类）

测试策略：
  - TestClient + app.dependency_overrides[get_db] + AsyncMock
  - sys.modules stub 解决相对导入
  - 每个路由文件 >= 3 个测试，合计 20 个
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


# ─── 包层级注册 ───────────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))


# ─── stub 工具 ────────────────────────────────────────────────────────────────

def _stub_module(full_name: str, **attrs):
    """注入最小存根模块到 sys.modules，避免真实导入失败。"""
    if full_name in sys.modules:
        return sys.modules[full_name]
    mod = types.ModuleType(full_name)
    mod.__package__ = full_name.rsplit(".", 1)[0] if "." in full_name else full_name
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[full_name] = mod
    return mod


# ─── stub: service_bell_service（被 service_bell_routes 导入）────────────────
_stub_module(
    "src.services.service_bell_service",
    create_call=None,
    get_call_history=None,
    get_pending_calls=None,
    respond_call=None,
)

# ─── stub: dish_practice_service（被 dish_practice_routes 导入）──────────────
_stub_module(
    "src.services.dish_practice_service",
    get_practice_templates=None,
    get_dish_practices=None,
    add_dish_practice=None,
    remove_dish_practice=None,
)

# ─── stub: approval_service（被 approval_routes 导入）────────────────────────
# ApprovalService 必须作为真实类存在，否则 approval_routes 的 import 会失败

class _FakeApprovalService:
    """ApprovalService 最小化存根，供 approval_routes import 时使用。
    测试时通过 patch('src.api.approval_routes.ApprovalService') 替换实例。
    """
    def __init__(self, db=None, tenant_id: str = "", store_id: str = ""):
        self.db = db
        self.tenant_id = tenant_id
        self.store_id = store_id

    async def create_approval(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def approve(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def reject(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def list_approvals(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def get_approval(self, approval_id: str):  # pragma: no cover
        raise NotImplementedError


_approval_svc_stub = _stub_module("src.services.approval_service")
_approval_svc_stub.ApprovalService = _FakeApprovalService  # type: ignore[attr-defined]

# ─── stub: src.db（被 service_bell_routes 用 ..db.get_db 导入）───────────────
# get_db 必须是真实可调用，才能作为 dependency_overrides 的 key

async def _src_db_get_db_placeholder():  # noqa: D401
    """src.db.get_db 占位符，测试时通过 dependency_overrides 替换。"""
    yield None  # pragma: no cover


_stub_module("src.db", get_db=_src_db_get_db_placeholder)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.ontology.src.database import get_db as shared_get_db  # noqa: E402

# ─── 各路由导入 ───────────────────────────────────────────────────────────────
from src.api.review_routes import router as review_router               # type: ignore
from src.api.service_bell_routes import router as service_bell_router   # type: ignore
import src.db as _src_db_mod                                            # type: ignore
from src.api.store_management_routes import router as store_mgmt_router # type: ignore
from src.api.dish_practice_routes import router as dish_practice_router # type: ignore
from src.api.approval_routes import router as approval_router           # type: ignore

# service_bell_routes 使用 src.db.get_db（..db），approval_routes 使用 shared.ontology.src.database.get_db
# 两者是不同对象，需要分别 override
_src_get_db    = _src_db_mod.get_db   # service_bell 使用的依赖 key
_shared_get_db = shared_get_db        # approval 使用的依赖 key

# ─── 常量 ─────────────────────────────────────────────────────────────────────
TENANT_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID    = "s1"
ORDER_ID    = "ord-001"
APPROVAL_ID = "apv-001"
CALL_ID     = "cccccccc-cccc-cccc-cccc-cccccccccccc"
DISH_ID     = "dddddddd-dddd-dddd-dddd-dddddddddddd"
PRACTICE_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()
    db.execute  = AsyncMock(return_value=MagicMock())
    return db


def _make_app(*routers, db: AsyncMock | None = None, use_src_db: bool = False) -> FastAPI:
    """构建测试 FastAPI 应用。

    db:          要注入的 mock DB session
    use_src_db:  True 时 override src.db.get_db（service_bell_routes 使用）
                 False 时 override shared.ontology.src.database.get_db（approval_routes 使用）
    """
    app = FastAPI()
    for r in routers:
        app.include_router(r)

    if db is not None:
        async def _override():
            yield db
        if use_src_db:
            app.dependency_overrides[_src_get_db] = _override
        else:
            app.dependency_overrides[_shared_get_db] = _override

    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  review_routes 测试（4 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_review_list_default():
    """评价列表默认查询：返回 ok=True 且包含 items/total/avg_rating。"""
    app = _make_app(review_router)
    client = TestClient(app)
    resp = client.get("/api/v1/trade/reviews", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert "total" in data
    assert "avg_rating" in data
    assert data["_is_mock"] is True


def test_review_list_filter_by_rating():
    """评价列表按星级筛选：只返回5星评价。"""
    app = _make_app(review_router)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/trade/reviews",
        params={"rating_filter": 5},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    for item in data["items"]:
        assert item["overall_rating"] == 5


def test_review_create_high_rating():
    """高分评价（>=3）创建后状态为 published。"""
    app = _make_app(review_router)
    client = TestClient(app)
    payload = {
        "order_id": ORDER_ID,
        "overall_rating": 5,
        "sub_ratings": {"food": 5, "service": 5, "environment": 4, "speed": 5},
        "content": "非常棒",
        "tags": ["味道棒极了"],
        "image_urls": [],
        "is_anonymous": False,
    }
    resp = client.post("/api/v1/trade/reviews", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "published"
    assert data["order_id"] == ORDER_ID


def test_review_create_low_rating_pending():
    """低分评价（<3）创建后状态为 pending_review（差评人工审核）。"""
    app = _make_app(review_router)
    client = TestClient(app)
    payload = {
        "order_id": "ord-bad",
        "overall_rating": 1,
        "sub_ratings": {"food": 1, "service": 1, "environment": 1, "speed": 1},
        "content": "太差了",
        "tags": [],
        "image_urls": [],
        "is_anonymous": True,
    }
    resp = client.post("/api/v1/trade/reviews", json=payload, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "pending_review"


def test_review_merchant_reply():
    """商家回复：返回 ok=True 且含 merchant_reply 字段。"""
    app = _make_app(review_router)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/trade/reviews/rev001/reply",
        json={"content": "感谢您的好评！"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == "rev001"
    assert data["merchant_reply"] == "感谢您的好评！"


def test_review_stats():
    """评价统计接口：返回 avg_rating、rating_distribution、top_tags。"""
    app = _make_app(review_router)
    client = TestClient(app)
    resp = client.get("/api/v1/trade/reviews/stats", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "avg_rating" in data
    assert "rating_distribution" in data
    assert "top_tags" in data
    assert data["_is_mock"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  service_bell_routes 测试（4 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_fake_call():
    """构造服务铃呼叫 mock 对象。"""
    from unittest.mock import MagicMock
    from datetime import datetime, timezone
    call = MagicMock()
    call.id            = CALL_ID
    call.store_id      = STORE_ID
    call.table_no      = "A01"
    call.call_type     = "water"
    call.call_type_label = "加水"
    call.status        = "pending"
    call.operator_id   = None
    call.called_at     = datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc)
    call.responded_at  = None
    return call


def test_service_bell_create_call_success():
    """顾客呼叫成功：call_type 合法且 X-Tenant-ID 存在，返回 ok=True。"""
    db = _make_mock_db()
    fake_call = _make_fake_call()

    with patch(
        "src.api.service_bell_routes.create_call",
        new=AsyncMock(return_value=fake_call),
    ):
        app = _make_app(service_bell_router, db=db, use_src_db=True)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/service-bell",
            json={
                "store_id": STORE_ID,
                "table_no": "A01",
                "call_type": "water",
                "call_type_label": "加水",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["call_id"] == CALL_ID
    assert body["data"]["call_type"] == "water"


def test_service_bell_create_call_invalid_type():
    """非法 call_type 应返回 400。"""
    db = _make_mock_db()
    app = _make_app(service_bell_router, db=db, use_src_db=True)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/service-bell",
        json={"store_id": STORE_ID, "table_no": "A01", "call_type": "unknown_type"},
        headers=HEADERS,
    )
    assert resp.status_code == 400
    assert "call_type" in resp.json()["detail"]


def test_service_bell_create_call_missing_tenant():
    """缺少 X-Tenant-ID header 应返回 400。"""
    db = _make_mock_db()
    app = _make_app(service_bell_router, db=db, use_src_db=True)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/service-bell",
        json={"store_id": STORE_ID, "table_no": "A01", "call_type": "water"},
        # 故意不传 X-Tenant-ID
    )
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


def test_service_bell_get_pending():
    """获取待响应列表：返回 ok=True 和 items 数组。"""
    db = _make_mock_db()
    fake_call = _make_fake_call()

    with patch(
        "src.api.service_bell_routes.get_pending_calls",
        new=AsyncMock(return_value=[fake_call]),
    ):
        app = _make_app(service_bell_router, db=db, use_src_db=True)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/service-bell/pending",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["status"] == "pending"


def test_service_bell_respond_call_success():
    """服务员响应呼叫成功：返回 ok=True 且 status 变为 responded。"""
    db = _make_mock_db()
    fake_call = _make_fake_call()
    from datetime import datetime, timezone
    fake_call.status       = "responded"
    fake_call.operator_id  = "op-001"
    fake_call.responded_at = datetime(2026, 4, 5, 10, 5, 0, tzinfo=timezone.utc)

    with patch(
        "src.api.service_bell_routes.respond_call",
        new=AsyncMock(return_value=fake_call),
    ):
        app = _make_app(service_bell_router, db=db, use_src_db=True)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/service-bell/{CALL_ID}/respond",
            json={"operator_id": "op-001"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "responded"
    assert data["responded_at"] is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  store_management_routes 测试（4 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_store_list_all():
    """门店列表默认查询：返回 ok=True，items 包含 id/name 字段。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    resp = client.get("/api/v1/trade/stores", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    assert "id" in data["items"][0]
    assert "name" in data["items"][0]


def test_store_list_filter_by_status():
    """门店列表按 status 筛选：只返回 active 门店。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/trade/stores",
        params={"status": "active"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    for item in data["items"]:
        assert item["status"] == "active"


def test_store_create_success():
    """新增门店：返回 201 且返回数据含 id/name/status。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    payload = {
        "name": "测试新店",
        "type": "direct",
        "city": "长沙",
        "address": "测试地址123号",
        "status": "active",
        "manager": "测试经理",
    }
    resp = client.post("/api/v1/trade/stores", json=payload, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "测试新店"
    assert "id" in data
    assert data["status"] == "active"


def test_store_get_not_found():
    """门店详情：不存在的 store_id 返回 404。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    resp = client.get("/api/v1/trade/stores/nonexistent-id-999", headers=HEADERS)
    assert resp.status_code == 404
    assert "Store not found" in resp.json()["detail"]


def test_table_list_by_store():
    """桌台列表按 store_id 过滤：只返回指定门店的桌台。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/trade/tables",
        params={"store_id": "s1"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    for item in data["items"]:
        assert item["store_id"] == "s1"


def test_table_get_not_found():
    """桌台详情：不存在的 table_id 返回 404。"""
    app = _make_app(store_mgmt_router)
    client = TestClient(app)
    resp = client.get("/api/v1/trade/tables/table-not-exist", headers=HEADERS)
    assert resp.status_code == 404
    assert "Table not found" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  dish_practice_routes 测试（3 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_dish_practice_get_templates():
    """获取通用做法模板：返回 ok=True 且 data 包含模板列表。"""
    fake_templates = [
        {"template_id": "tpl-spicy-mild", "category": "spicy", "name": "微辣"},
        {"template_id": "tpl-sweet-none", "category": "sweetness", "name": "不甜"},
    ]
    with patch(
        "src.api.dish_practice_routes.svc.get_practice_templates",
        new=AsyncMock(return_value=fake_templates),
    ):
        app = _make_app(dish_practice_router)
        client = TestClient(app)
        resp = client.get("/api/v1/practices/templates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 2
    assert body["data"][0]["category"] == "spicy"


def test_dish_practice_get_dish_practices():
    """获取菜品做法列表：返回 ok=True 且 data 为做法数组。"""
    fake_practices = [
        {
            "practice_id": PRACTICE_ID,
            "dish_id": DISH_ID,
            "name": "微辣",
            "additional_price_fen": 0,
            "category": "spicy",
        }
    ]
    with patch(
        "src.api.dish_practice_routes.svc.get_dish_practices",
        new=AsyncMock(return_value=fake_practices),
    ):
        app = _make_app(dish_practice_router)
        client = TestClient(app)
        resp = client.get(
            f"/api/v1/dishes/{DISH_ID}/practices",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["name"] == "微辣"


def test_dish_practice_add_success():
    """添加菜品做法成功：返回 ok=True 且 data 含新 practice_id。"""
    fake_result = {
        "practice_id": PRACTICE_ID,
        "dish_id": DISH_ID,
        "name": "不要香菜",
        "additional_price_fen": 0,
        "category": "avoid",
    }
    with patch(
        "src.api.dish_practice_routes.svc.add_dish_practice",
        new=AsyncMock(return_value=fake_result),
    ):
        app = _make_app(dish_practice_router)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/dishes/{DISH_ID}/practices",
            json={
                "name": "不要香菜",
                "additional_price_fen": 0,
                "materials": [],
                "category": "avoid",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "不要香菜"
    assert body["data"]["practice_id"] == PRACTICE_ID


def test_dish_practice_get_missing_tenant():
    """获取菜品做法：缺少 X-Tenant-ID 应返回 400。"""
    app = _make_app(dish_practice_router)
    client = TestClient(app)
    resp = client.get(f"/api/v1/dishes/{DISH_ID}/practices")
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  approval_routes 测试（4 个）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _make_mock_approval_svc() -> MagicMock:
    """构造 ApprovalService mock 实例，所有方法为 AsyncMock。"""
    svc = MagicMock()
    svc.create_approval  = AsyncMock()
    svc.approve          = AsyncMock()
    svc.reject           = AsyncMock()
    svc.list_approvals   = AsyncMock()
    svc.get_approval     = AsyncMock()
    return svc


def test_approval_create_success():
    """创建审批单：ApprovalService.create_approval 返回审批数据。"""
    db = _make_mock_db()
    fake_result = {
        "approval_id": APPROVAL_ID,
        "order_id": ORDER_ID,
        "status": "pending",
        "reason": "折扣超过毛利底线",
    }

    mock_svc_instance = _make_mock_approval_svc()
    mock_svc_instance.create_approval = AsyncMock(return_value=fake_result)

    with patch(
        "src.api.approval_routes.ApprovalService",
        return_value=mock_svc_instance,
    ):
        app = _make_app(approval_router, db=db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/approvals",
            json={
                "order_id": ORDER_ID,
                "discount_info": {
                    "discount_type": "percent",
                    "discount_value": 80,
                    "discount_fen": 2000,
                    "current_margin": 0.15,
                    "margin_floor": 0.20,
                },
                "reason": "折扣超过毛利底线",
                "requester_id": "emp-001",
                "store_id": STORE_ID,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["approval_id"] == APPROVAL_ID
    assert body["data"]["status"] == "pending"


def test_approval_approve_success():
    """批准审批单：返回 ok=True 且 status 为 approved。"""
    db = _make_mock_db()
    fake_result = {
        "approval_id": APPROVAL_ID,
        "status": "approved",
        "approver_id": "mgr-001",
    }

    mock_svc_instance = _make_mock_approval_svc()
    mock_svc_instance.approve = AsyncMock(return_value=fake_result)

    with patch(
        "src.api.approval_routes.ApprovalService",
        return_value=mock_svc_instance,
    ):
        app = _make_app(approval_router, db=db)
        client = TestClient(app)
        resp = client.put(
            f"/api/v1/approvals/{APPROVAL_ID}/approve",
            json={"approver_id": "mgr-001"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "approved"


def test_approval_reject_success():
    """拒绝审批单：返回 ok=True 且 status 为 rejected。"""
    db = _make_mock_db()
    fake_result = {
        "approval_id": APPROVAL_ID,
        "status": "rejected",
        "approver_id": "mgr-001",
        "reject_reason": "折扣幅度过大",
    }

    mock_svc_instance = _make_mock_approval_svc()
    mock_svc_instance.reject = AsyncMock(return_value=fake_result)

    with patch(
        "src.api.approval_routes.ApprovalService",
        return_value=mock_svc_instance,
    ):
        app = _make_app(approval_router, db=db)
        client = TestClient(app)
        resp = client.put(
            f"/api/v1/approvals/{APPROVAL_ID}/reject",
            json={"approver_id": "mgr-001", "reason": "折扣幅度过大"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "rejected"


def test_approval_list_with_status_filter():
    """审批列表按 status 过滤：返回 ok=True 且分页结构正确。"""
    db = _make_mock_db()
    fake_result = {
        "items": [{"approval_id": APPROVAL_ID, "status": "pending"}],
        "total": 1,
        "page": 1,
        "size": 20,
    }

    mock_svc_instance = _make_mock_approval_svc()
    mock_svc_instance.list_approvals = AsyncMock(return_value=fake_result)

    with patch(
        "src.api.approval_routes.ApprovalService",
        return_value=mock_svc_instance,
    ):
        app = _make_app(approval_router, db=db)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/approvals",
            params={"status": "pending", "page": 1, "size": 20},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["status"] == "pending"


def test_approval_get_not_found():
    """审批详情：不存在的 approval_id 应返回 404。"""
    db = _make_mock_db()

    mock_svc_instance = _make_mock_approval_svc()
    mock_svc_instance.get_approval = AsyncMock(return_value=None)

    with patch(
        "src.api.approval_routes.ApprovalService",
        return_value=mock_svc_instance,
    ):
        app = _make_app(approval_router, db=db)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/approvals/no-such-approval",
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "Approval not found" in resp.json()["detail"]


def test_approval_create_missing_tenant():
    """创建审批单：缺少 X-Tenant-ID 应返回 400。"""
    db = _make_mock_db()
    app = _make_app(approval_router, db=db)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/approvals",
        json={
            "order_id": ORDER_ID,
            "discount_info": {"discount_type": "percent"},
            "reason": "test",
        },
        # 故意不传 X-Tenant-ID
    )
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]
