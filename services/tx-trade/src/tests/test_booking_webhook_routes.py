"""预订渠道 Webhook 路由测试 — booking_webhook_routes.py

覆盖场景（共 8 个）：
1. POST /webhook/meituan — 正常路径：新建预订成功
2. POST /webhook/meituan — 取消已存在预订
3. POST /webhook/dianping — 正常路径：新建预订成功
4. POST /webhook/wechat — 正常路径：微信小程序新建预订
5. POST /webhook/meituan — DB 抛 ValueError 返回 400
6. POST /mock/new-reservation — 正常路径：从 DB 取样客户信息创建 mock 预订
7. POST /mock/new-reservation — DB 取样失败回退到占位符，仍成功
8. POST /webhook/meituan — 缺少 X-Tenant-ID header 返回 400
"""
import os
import sys
import types

# ─── 路径准备 ──────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─── 建立 src 包层级 ─────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod

_ensure_pkg("src",           _SRC_DIR)
_ensure_pkg("src.api",       os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services",  os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models",    os.path.join(_SRC_DIR, "models"))
_ensure_pkg("src.repositories", os.path.join(_SRC_DIR, "repositories"))

# ─── Stub 掉 ReservationService（其依赖链太深，避免 ORM 全量初始化）──────────

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

_stub_svc_mod = types.ModuleType("src.services.reservation_service")
_stub_svc_mod.ReservationService = MagicMock  # 占位，测试中会用 patch 替换
sys.modules["src.services.reservation_service"] = _stub_svc_mod

import uuid                          # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

import pytest                        # noqa: E402
from fastapi import FastAPI          # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.booking_webhook_routes import router, _get_db_session  # type: ignore[import]  # noqa: E402
from shared.ontology.src.database import get_db_with_tenant         # noqa: E402


# ─── 工具 ──────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID  = str(uuid.uuid4())

_BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Store-ID":  STORE_ID,
}


def _make_db():
    """返回基础 AsyncMock DB session"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=AsyncMock(fetchone=MagicMock(return_value=None)))
    db.commit  = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _override_db(db):
    """dependency_overrides 覆盖 _get_db_session（生成器形式）"""
    async def _dep():
        yield db
    return _dep


def _make_app(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[_get_db_session] = _override_db(db)
    return app


# ─── 公用美团 Payload ──────────────────────────────────────────────────────────

def _meituan_payload(**kwargs) -> dict:
    base = {
        "order_id":        f"MT{uuid.uuid4().hex[:12]}",
        "shop_id":         "shop_001",
        "customer_name":   "张三",
        "customer_phone":  "13800138000",
        "party_size":      4,
        "arrive_time":     "2026-06-15T18:30:00",
        "table_type":      "大厅",
        "special_request": "",
        "status":          "confirmed",
        "created_at":      "2026-06-15T10:00:00",
    }
    base.update(kwargs)
    return base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: POST /webhook/meituan — 正常路径：新建预订成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_meituan_create_ok():
    """新订单（未存在）应调用 create_reservation 并返回 code=0"""
    db = _make_db()
    new_res = {"id": str(uuid.uuid4()), "status": "confirmed", "customer_name": "张三"}

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value=new_res)

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/meituan",
            json=_meituan_payload(),
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["customer_name"] == "张三"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: POST /webhook/meituan — 取消已存在预订
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_meituan_cancel_existing():
    """已存在的预订状态=cancelled 时应调用 cancel_reservation"""
    db = _make_db()
    existing = {"id": str(uuid.uuid4()), "status": "confirmed"}
    cancelled = {"id": existing["id"], "status": "cancelled"}

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=existing)
    mock_svc.cancel_reservation = AsyncMock(return_value=cancelled)

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/meituan",
            json=_meituan_payload(status="cancelled"),
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "cancelled"
    mock_svc.cancel_reservation.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: POST /webhook/dianping — 正常路径：新建预订
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_dianping_create_ok():
    """大众点评新预订正常落库，返回 code=0 + message=success"""
    db = _make_db()
    new_res = {"id": str(uuid.uuid4()), "status": "confirmed", "customer_name": "李四"}

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value=new_res)

    dianping_payload = {
        "deal_id":      f"DP{uuid.uuid4().hex[:12]}",
        "poi_id":       "poi_001",
        "user_name":    "李四",
        "user_phone":   "13912345678",
        "guest_num":    2,
        "visit_time":   "2026-06-20T12:00:00",
        "room_type":    "大厅",
        "remark":       "",
        "order_status": "CONFIRMED",
        "create_time":  "2026-06-15T09:00:00",
    }

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/dianping",
            json=dianping_payload,
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "success"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: POST /webhook/wechat — 微信小程序新建预订
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_wechat_create_ok():
    """微信小程序预订 Webhook 成功落库，返回 ok=True"""
    db = _make_db()
    new_res = {"id": str(uuid.uuid4()), "status": "confirmed", "customer_name": "王五"}

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value=new_res)

    wechat_payload = {
        "booking_id":        str(uuid.uuid4()),
        "openid":            "oABCDEFGH1234567",
        "customer_name":     "王五",
        "customer_phone":    "13600000001",
        "party_size":        3,
        "arrive_time":       "2026-07-01T19:00:00",
        "table_preference":  "靠窗",
        "notes":             "安静位置",
        "store_id":          STORE_ID,
        "status":            "confirmed",
    }

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/wechat",
            json=wechat_payload,
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["customer_name"] == "王五"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: POST /webhook/meituan — ReservationService 抛 ValueError → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_meituan_value_error_returns_400():
    """create_reservation 抛 ValueError 时应返回 HTTP 400"""
    db = _make_db()

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(side_effect=ValueError("party_size 超过上限"))

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/meituan",
            json=_meituan_payload(),
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: POST /mock/new-reservation — 从 DB 取样客户信息创建 mock 预订
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_mock_new_reservation_with_db_customer():
    """DB 中有历史客户时 mock 端点应创建预订并返回 ok=True"""
    db = _make_db()

    # 模拟 DB 查询返回一个历史客户行
    fake_row = MagicMock()
    fake_row.customer_name = "测试老客户"
    fake_row.phone = "13711112222"
    db_result = MagicMock()
    db_result.fetchone = MagicMock(return_value=fake_row)
    db.execute = AsyncMock(return_value=db_result)

    new_res = {"id": str(uuid.uuid4()), "status": "confirmed", "customer_name": "测试老客户"}
    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value=new_res)

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/booking/mock/new-reservation?store_id=store_001",
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "reservation" in body["data"]
    assert "mock_channel" in body["data"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: POST /mock/new-reservation — DB 取样失败回退到占位符仍成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_mock_new_reservation_db_sample_failure_fallback():
    """DB 查询客户失败时应使用匿名占位符，端点仍返回 ok=True"""
    db = _make_db()
    db.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("conn error"))
    )

    new_res = {"id": str(uuid.uuid4()), "status": "confirmed", "customer_name": "测试客户"}
    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value=new_res)

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/mock/new-reservation?store_id=store_001",
            headers=_BASE_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: POST /webhook/meituan — 缺少 X-Tenant-ID header → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_webhook_meituan_missing_tenant_header():
    """缺少 X-Tenant-ID 时 _get_tenant_id 应抛出 400"""
    db = _make_db()

    mock_svc = AsyncMock()
    mock_svc.find_by_platform_order_id = AsyncMock(return_value=None)
    mock_svc.create_reservation = AsyncMock(return_value={"id": "x"})

    with patch("src.api.booking_webhook_routes.ReservationService", return_value=mock_svc):
        app = _make_app(db)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/booking/webhook/meituan",
            json=_meituan_payload(),
            # 不传 X-Tenant-ID
        )

    assert resp.status_code == 400
