"""后厨管理路由测试 — production_dept + discount_audit + expo + runner

覆盖场景（共 20 个测试）：

production_dept_routes（5个）：
1.  POST /api/v1/production-depts                      — 创建档口成功
2.  GET  /api/v1/production-depts                      — 列出档口成功
3.  GET  /api/v1/production-depts/{dept_id}            — 获取单个档口，不存在→404
4.  DELETE /api/v1/production-depts/{dept_id}          — 删除档口成功
5.  POST /api/v1/production-depts/dish-mappings/batch  — 批量超500条→400

discount_audit_routes（5个）：
6.  GET  /api/v1/discount/audit-log                    — 正常返回审计记录列表
7.  GET  /api/v1/discount/audit-log/summary            — 今日汇总返回统计
8.  GET  /api/v1/discount/audit-log/high-risk          — 高风险折扣记录列表
9.  GET  /api/v1/discount/audit-log                    — 缺少 X-Tenant-ID → 400
10. GET  /api/v1/discount/audit-log/summary            — 非法period参数 → 422

expo_routes（5个）：
11. GET  /api/v1/expo/{store_id}/overview              — 传菜督导主视图正常返回
12. POST /api/v1/expo/{plan_id}/served                 — 确认传菜完成成功
13. POST /api/v1/expo/{plan_id}/served                 — 计划不存在→404
14. GET  /api/v1/expo/{plan_id}/status                 — 单桌状态查询（mock DB）
15. POST /api/v1/expo/dispatch/{order_id}/fire         — 分单并创建TableFire成功

runner_routes（5个）：
16. GET  /api/v1/runner/{store_id}/queue               — 传菜员待取菜列表
17. GET  /api/v1/runner/{store_id}/history             — 今日传菜记录
18. POST /api/v1/runner/task/{task_id}/ready           — 标记ready成功
19. POST /api/v1/runner/task/{task_id}/pickup          — 领取菜品失败→400
20. POST /api/v1/runner/task/register                  — 注册传菜任务成功
"""

import os
import sys
import types

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级 ──────────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))
_ensure_pkg("src.models", os.path.join(_SRC_DIR, "models"))


# ─── stub 工具函数 ─────────────────────────────────────────────────────────────


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


# ─── structlog stub ───────────────────────────────────────────────────────────
_structlog_mod = _stub_module("structlog")

import logging as _logging  # noqa: E402

_fake_logger = _logging.getLogger("structlog_stub")


class _BoundLogger:
    def bind(self, **_kw):
        return self

    def info(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass


_structlog_mod.get_logger = lambda: _BoundLogger()

# ─── production_dept_service stub ────────────────────────────────────────────
_stub_module(
    "src.services.production_dept_service",
    create_production_dept=None,
    get_production_depts=None,
    get_production_dept_by_id=None,
    update_production_dept=None,
    delete_production_dept=None,
    get_dept_by_kds_device_id=None,
    set_dish_dept_mapping=None,
    get_dish_dept_mapping=None,
    batch_set_dish_dept_mappings=None,
    remove_dish_dept_mapping=None,
    list_dish_mappings_for_dept=None,
)

# ─── discount_audit_service stub ──────────────────────────────────────────────


class _FakeDiscountAuditService:
    def __init__(self, db, tenant_id):
        self.db = db
        self.tenant_id = tenant_id

    async def get_audit_log(self, **_kw):
        return {"items": [], "total": 0}

    async def get_high_risk_summary(self, **_kw):
        return {"summary": []}


_svc_stub = _stub_module("src.services.discount_audit_service")
_svc_stub.DiscountAuditService = _FakeDiscountAuditService

# ─── TableProductionPlan model stub ──────────────────────────────────────────
from sqlalchemy import Boolean, Integer, String  # noqa: E402
from sqlalchemy.orm import DeclarativeBase, mapped_column  # noqa: E402


class _TestBase(DeclarativeBase):
    pass


class _FakeTableProductionPlan(_TestBase):
    __tablename__ = "table_production_plans"
    id = mapped_column(Integer, primary_key=True)
    tenant_id = mapped_column(Integer)
    order_id = mapped_column(Integer)
    store_id = mapped_column(Integer)
    table_no = mapped_column(String)
    status = mapped_column(String)
    dept_readiness = mapped_column(String)
    dept_delays = mapped_column(String)
    target_completion = mapped_column(String)
    is_deleted = mapped_column(Boolean)


_tpp_mod = _stub_module("src.models.table_production_plan")
_tpp_mod.TableProductionPlan = _FakeTableProductionPlan  # type: ignore[attr-defined]

# ─── cooking_scheduler stub ───────────────────────────────────────────────────
_stub_module(
    "src.services.cooking_scheduler",
    calculate_cooking_order=None,
    get_dept_load=None,
    create_table_fire_plan=None,
)

# ─── kds_dispatch stub ───────────────────────────────────────────────────────
_stub_module(
    "src.services.kds_dispatch",
    dispatch_order_to_kds=None,
    get_dept_queue=None,
    get_kds_tasks_by_dept=None,
    get_store_kds_overview=None,
    resolve_dept_for_dish=None,
)

# ─── table_production_plan service stub ──────────────────────────────────────


class _FakeTableFireCoordinator:
    async def get_expo_view(self, store_id, tenant_id, db):
        return []

    async def mark_served(self, plan_id, tenant_id, db):
        return True


_tpp_svc_mod = _stub_module("src.services.table_production_plan")
_tpp_svc_mod.TableFireCoordinator = _FakeTableFireCoordinator  # type: ignore[attr-defined]

# ─── runner_service stub ──────────────────────────────────────────────────────
_stub_module(
    "src.services.runner_service",
    get_runner_queue=None,
    get_runner_history=None,
    mark_ready=None,
    pickup_dish=None,
    confirm_served=None,
    register_runner_task=None,
)

# ─── 正式导入 ──────────────────────────────────────────────────────────────────
import uuid  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.discount_audit_routes import router as discount_audit_router  # noqa: E402
from src.api.expo_routes import router as expo_router  # noqa: E402
from src.api.production_dept_routes import router as production_dept_router  # noqa: E402
from src.api.runner_routes import router as runner_router  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEPT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ORDER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
TASK_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
PLAN_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
DISH_ID = "11111111-1111-1111-1111-111111111111"
BRAND_ID = "22222222-2222-2222-2222-222222222222"

HEADERS = {"X-Tenant-ID": TENANT_ID}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


def _make_app_with_db(db: AsyncMock, router) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


def _make_fake_dept():
    """构建最小档口 mock 对象。"""
    dept = MagicMock()
    dept.id = uuid.UUID(DEPT_ID)
    dept.dept_name = "热菜间"
    dept.dept_code = "hot"
    dept.brand_id = uuid.UUID(BRAND_ID)
    dept.store_id = uuid.UUID(STORE_ID)
    dept.printer_address = "192.168.1.100:9100"
    dept.printer_type = "network"
    dept.kds_device_id = "KDS-001"
    dept.display_color = "blue"
    dept.fixed_fee_type = None
    dept.default_timeout_minutes = 15
    dept.sort_order = 0
    dept.is_active = True
    dept.created_at = None
    dept.updated_at = None
    return dept


def _make_fake_mapping():
    """构建最小菜品-档口映射 mock 对象。"""
    m = MagicMock()
    m.id = uuid.uuid4()
    m.dish_id = uuid.UUID(DISH_ID)
    m.production_dept_id = uuid.UUID(DEPT_ID)
    m.is_primary = True
    m.printer_id = None
    m.sort_order = 0
    m.created_at = None
    return m


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ▌ PRODUCTION DEPT ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景1: POST /api/v1/production-depts — 创建档口成功


def test_create_production_dept_success():
    """创建档口：正常传参，服务层返回档口对象，API 返回 ok+data。"""
    db = _make_mock_db()
    fake_dept = _make_fake_dept()

    with patch(
        "src.api.production_dept_routes.create_production_dept",
        new=AsyncMock(return_value=fake_dept),
    ):
        client = TestClient(_make_app_with_db(db, production_dept_router))
        resp = client.post(
            "/api/v1/production-depts",
            json={
                "brand_id": BRAND_ID,
                "store_id": STORE_ID,
                "dept_name": "热菜间",
                "dept_code": "hot",
                "printer_address": "192.168.1.100:9100",
                "printer_type": "network",
                "kds_device_id": "KDS-001",
                "display_color": "blue",
                "default_timeout_minutes": 15,
                "sort_order": 0,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dept_name"] == "热菜间"
    assert body["data"]["dept_code"] == "hot"
    assert body["data"]["kds_device_id"] == "KDS-001"


# 场景2: GET /api/v1/production-depts — 列出档口成功


def test_list_production_depts_success():
    """列出档口：返回 items+total，items 数量与服务层返回一致。"""
    db = _make_mock_db()
    fake_dept = _make_fake_dept()

    with patch(
        "src.api.production_dept_routes.get_production_depts",
        new=AsyncMock(return_value=[fake_dept, fake_dept]),
    ):
        client = TestClient(_make_app_with_db(db, production_dept_router))
        resp = client.get(
            "/api/v1/production-depts",
            params={"store_id": STORE_ID},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2
    assert body["data"]["items"][0]["dept_name"] == "热菜间"


# 场景3: GET /api/v1/production-depts/{dept_id} — 档口不存在→404


def test_get_production_dept_not_found():
    """查询单个档口：服务层返回 None，API 应返回 404。"""
    db = _make_mock_db()

    with patch(
        "src.api.production_dept_routes.get_production_dept_by_id",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(_make_app_with_db(db, production_dept_router))
        resp = client.get(
            f"/api/v1/production-depts/{DEPT_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# 场景4: DELETE /api/v1/production-depts/{dept_id} — 删除档口成功


def test_delete_production_dept_success():
    """删除档口：服务层正常返回（不抛异常），API 返回 deleted=True。"""
    db = _make_mock_db()

    with patch(
        "src.api.production_dept_routes.delete_production_dept",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(_make_app_with_db(db, production_dept_router))
        resp = client.delete(
            f"/api/v1/production-depts/{DEPT_ID}",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["deleted"] is True
    assert body["data"]["dept_id"] == DEPT_ID


# 场景5: POST /api/v1/production-depts/dish-mappings/batch — 超500条→400


def test_batch_set_dish_mappings_too_many():
    """批量映射：超过500条限制时应返回 400（无需到服务层）。"""
    db = _make_mock_db()

    # 501 条映射
    mappings = [{"dish_id": str(uuid.uuid4()), "dept_id": DEPT_ID, "is_primary": True} for _ in range(501)]

    client = TestClient(_make_app_with_db(db, production_dept_router))
    resp = client.post(
        "/api/v1/production-depts/dish-mappings/batch",
        json={"mappings": mappings},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "500" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ▌ DISCOUNT AUDIT ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景6: GET /api/v1/discount/audit-log — 正常返回列表


def test_get_audit_log_success():
    """审计日志列表：正常请求，返回 ok=True，data 含 items+total。"""
    db = _make_mock_db()

    fake_items = [
        {
            "id": str(uuid.uuid4()),
            "operator_id": "op_001",
            "action_type": "manual_discount",
            "discount_amount": "50.00",
            "original_amount": "200.00",
        }
    ]

    class _MockSvc:
        def __init__(self, db, tenant_id):
            pass

        async def get_audit_log(self, **_kw):
            return {"items": fake_items, "total": 1}

        async def get_high_risk_summary(self, **_kw):
            return {"summary": []}

    with patch("src.api.discount_audit_routes.DiscountAuditService", _MockSvc):
        client = TestClient(_make_app_with_db(db, discount_audit_router))
        resp = client.get(
            "/api/v1/discount/audit-log",
            params={"store_id": STORE_ID, "page": 1, "size": 20},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["action_type"] == "manual_discount"


# 场景7: GET /api/v1/discount/audit-log/summary — today 汇总


def test_get_audit_summary_today():
    """今日汇总：period=today，返回 total_count / total_discount_amount / high_risk_count。"""
    db = _make_mock_db()

    fake_items = [
        {
            "operator_id": "op_001",
            "discount_amount": "30.00",
            "original_amount": "100.00",
        }
    ]

    class _MockSvc:
        def __init__(self, db, tenant_id):
            pass

        async def get_audit_log(self, **_kw):
            return {"items": fake_items, "total": 1}

        async def get_high_risk_summary(self, **_kw):
            return {"summary": [{"operator_id": "op_001", "high_risk_count": 2}]}

    with patch("src.api.discount_audit_routes.DiscountAuditService", _MockSvc):
        client = TestClient(_make_app_with_db(db, discount_audit_router))
        resp = client.get(
            "/api/v1/discount/audit-log/summary",
            params={"period": "today"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["period"] == "today"
    assert data["total_count"] == 1
    assert data["total_discount_amount"] == 30.0
    assert data["high_risk_count"] == 2


# 场景8: GET /api/v1/discount/audit-log/high-risk — 高风险记录


def test_get_high_risk_discount_records():
    """高风险折扣：返回折扣率超阈值的记录和操作员汇总。"""
    db = _make_mock_db()

    fake_items = [
        {
            "id": str(uuid.uuid4()),
            "operator_id": "op_002",
            "discount_amount": "80.00",
            "original_amount": "100.00",
        }
    ]

    class _MockSvc:
        def __init__(self, db, tenant_id):
            pass

        async def get_audit_log(self, **_kw):
            return {"items": fake_items, "total": 1}

        async def get_high_risk_summary(self, **_kw):
            return {"summary": [{"operator_id": "op_002", "high_risk_count": 1}]}

    with patch("src.api.discount_audit_routes.DiscountAuditService", _MockSvc):
        client = TestClient(_make_app_with_db(db, discount_audit_router))
        resp = client.get(
            "/api/v1/discount/audit-log/high-risk",
            params={"threshold_pct": 30},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["threshold_pct"] == 30
    assert len(data["items"]) == 1  # 80/100=80% > 30%，属于高风险
    assert len(data["operator_summary"]) == 1


# 场景9: GET /api/v1/discount/audit-log — 缺少 X-Tenant-ID → 400


def test_audit_log_missing_tenant_id():
    """缺少 X-Tenant-ID 时，应返回 400。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db, discount_audit_router))

    resp = client.get("/api/v1/discount/audit-log")

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


# 场景10: GET /api/v1/discount/audit-log/summary — 非法 period → 422


def test_audit_summary_invalid_period():
    """period 参数不在 (today|week|month) 范围内，FastAPI 应返回 422。"""
    db = _make_mock_db()
    client = TestClient(_make_app_with_db(db, discount_audit_router))

    resp = client.get(
        "/api/v1/discount/audit-log/summary",
        params={"period": "invalid_period"},
        headers=HEADERS,
    )

    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ▌ EXPO ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景11: GET /expo/{store_id}/overview — 传菜督导主视图


def test_expo_overview_success():
    """传菜督导主视图：返回活跃桌位票据列表，含 all_ready_count。"""
    db = _make_mock_db()

    fake_tickets = [
        {"plan_id": PLAN_ID, "table_no": "A01", "status": "all_ready"},
        {"plan_id": str(uuid.uuid4()), "table_no": "B02", "status": "coordinating"},
    ]

    class _MockCoordinator:
        async def get_expo_view(self, store_id, tenant_id, db):
            return fake_tickets

        async def mark_served(self, plan_id, tenant_id, db):
            return True

    with patch("src.api.expo_routes.TableFireCoordinator", _MockCoordinator):
        client = TestClient(_make_app_with_db(db, expo_router))
        resp = client.get(
            f"/api/v1/expo/{STORE_ID}/overview",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 2
    assert data["all_ready_count"] == 1
    assert len(data["tickets"]) == 2


# 场景12: POST /expo/{plan_id}/served — 确认传菜完成成功


def test_expo_mark_served_success():
    """确认传菜：coordinator.mark_served 返回 True，API 返回 status=served。"""
    db = _make_mock_db()

    class _MockCoordinator:
        async def get_expo_view(self, **_kw):
            return []

        async def mark_served(self, plan_id, tenant_id, db):
            return True

    with patch("src.api.expo_routes.TableFireCoordinator", _MockCoordinator):
        client = TestClient(_make_app_with_db(db, expo_router))
        resp = client.post(
            f"/api/v1/expo/{PLAN_ID}/served",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "served"
    assert body["data"]["plan_id"] == PLAN_ID


# 场景13: POST /expo/{plan_id}/served — 计划不存在→404


def test_expo_mark_served_not_found():
    """确认传菜：coordinator.mark_served 返回 False（计划不存在），API 返回 404。"""
    db = _make_mock_db()

    class _MockCoordinator:
        async def get_expo_view(self, **_kw):
            return []

        async def mark_served(self, plan_id, tenant_id, db):
            return False  # 不存在

    with patch("src.api.expo_routes.TableFireCoordinator", _MockCoordinator):
        client = TestClient(_make_app_with_db(db, expo_router))
        resp = client.post(
            f"/api/v1/expo/{PLAN_ID}/served",
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "不存在" in resp.json()["detail"]


# 场景14: GET /expo/{plan_id}/status — 单桌状态查询


def test_expo_plan_status_success():
    """单桌协调状态查询：从 DB 拿到 plan，返回 dept_readiness / ready_depts 等。"""
    db = _make_mock_db()

    import datetime

    fake_plan = MagicMock()
    fake_plan.id = uuid.UUID(PLAN_ID)
    fake_plan.order_id = uuid.UUID(ORDER_ID)
    fake_plan.table_no = "A01"
    fake_plan.store_id = uuid.UUID(STORE_ID)
    fake_plan.status = "coordinating"
    fake_plan.dept_readiness = {DEPT_ID: True, str(uuid.uuid4()): False}
    fake_plan.dept_delays = {}
    fake_plan.target_completion = datetime.datetime(2026, 4, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = fake_plan

    # _set_tenant 是 execute 的第一次调用，plan 查询是第二次
    db.execute = AsyncMock(return_value=scalar_result)

    client = TestClient(_make_app_with_db(db, expo_router))
    resp = client.get(
        f"/api/v1/expo/{PLAN_ID}/status",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["plan_id"] == PLAN_ID
    assert data["status"] == "coordinating"
    assert data["total_depts"] == 2
    assert data["ready_depts"] == 1


# 场景15: POST /expo/dispatch/{order_id}/fire — 分单+TableFire成功


def test_expo_dispatch_and_fire_success():
    """分单并建 TableFire 计划：两个服务调用均成功，返回 dept_tasks+table_fire。"""
    db = _make_mock_db()

    fake_dept_tasks = [{"dept_id": DEPT_ID, "dept_name": "热菜间", "items": []}]
    fake_dispatch_result = {"dept_tasks": fake_dept_tasks}
    fake_table_fire = {
        "plan_id": PLAN_ID,
        "dept_delays": {},
        "target_completion": "2026-04-05T12:00:00+00:00",
    }

    with (
        patch(
            "src.api.expo_routes.dispatch_order_to_kds",
            new=AsyncMock(return_value=fake_dispatch_result),
        ),
        patch(
            "src.api.expo_routes.create_table_fire_plan",
            new=AsyncMock(return_value=fake_table_fire),
        ),
    ):
        client = TestClient(_make_app_with_db(db, expo_router))
        resp = client.post(
            f"/api/v1/expo/dispatch/{ORDER_ID}/fire",
            json={
                "items": [
                    {
                        "dish_id": DISH_ID,
                        "item_name": "红烧肉",
                        "quantity": 1,
                    }
                ],
                "table_number": "A01",
                "order_no": "T20260405001",
                "store_id": STORE_ID,
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["dept_tasks"]) == 1
    assert body["data"]["table_fire"]["plan_id"] == PLAN_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ▌ RUNNER ROUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景16: GET /runner/{store_id}/queue — 传菜员待取菜列表


def test_runner_queue_success():
    """传菜员待取菜列表：返回 items+total，items 中含菜品信息。"""
    db = _make_mock_db()

    fake_items = [
        {
            "task_id": TASK_ID,
            "dish_name": "红烧肉",
            "table_number": "A01",
            "status": "ready",
        }
    ]

    with patch(
        "src.api.runner_routes.get_runner_queue",
        new=AsyncMock(return_value=fake_items),
    ):
        client = TestClient(_make_app_with_db(db, runner_router))
        resp = client.get(
            f"/api/v1/runner/{STORE_ID}/queue",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["dish_name"] == "红烧肉"
    assert body["data"]["items"][0]["status"] == "ready"


# 场景17: GET /runner/{store_id}/history — 今日传菜记录


def test_runner_history_success():
    """今日传菜记录：返回今日所有 served 菜品，含送达时间。"""
    db = _make_mock_db()

    fake_items = [
        {
            "task_id": TASK_ID,
            "dish_name": "宫保鸡丁",
            "table_number": "B03",
            "status": "served",
            "served_at": "2026-04-05T11:30:00+00:00",
        }
    ]

    with patch(
        "src.api.runner_routes.get_runner_history",
        new=AsyncMock(return_value=fake_items),
    ):
        client = TestClient(_make_app_with_db(db, runner_router))
        resp = client.get(
            f"/api/v1/runner/{STORE_ID}/history",
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["status"] == "served"


# 场景18: POST /runner/task/{task_id}/ready — 标记ready成功


def test_runner_mark_ready_success():
    """KDS 完成出品后标记 ready：服务层返回 ok=True，API 透传返回。"""
    db = _make_mock_db()

    fake_result = {
        "ok": True,
        "data": {"task_id": TASK_ID, "status": "ready"},
    }

    with patch(
        "src.api.runner_routes.mark_ready",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db, runner_router))
        resp = client.post(
            f"/api/v1/runner/task/{TASK_ID}/ready",
            headers={**HEADERS, "X-Operator-ID": "chef_001"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ready"


# 场景19: POST /runner/task/{task_id}/pickup — 领取失败→400


def test_runner_pickup_failure():
    """传菜员领取：服务层返回 ok=False（任务已被领取），API 应返回 400。"""
    db = _make_mock_db()

    fake_result = {
        "ok": False,
        "error": "任务已被其他传菜员领取",
    }

    with patch(
        "src.api.runner_routes.pickup_dish",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db, runner_router))
        resp = client.post(
            f"/api/v1/runner/task/{TASK_ID}/pickup",
            headers={**HEADERS, "X-Operator-ID": "runner_002"},
        )

    assert resp.status_code == 400
    assert "已被" in resp.json()["detail"]


# 场景20: POST /runner/task/register — 注册传菜任务成功


def test_runner_register_task_success():
    """注册传菜任务：KDS分单时调用，服务层返回成功结果。"""
    db = _make_mock_db()

    fake_result = {
        "ok": True,
        "data": {
            "task_id": TASK_ID,
            "status": "pending",
            "dish_name": "红烧肉",
        },
    }

    with patch(
        "src.api.runner_routes.register_runner_task",
        new=AsyncMock(return_value=fake_result),
    ):
        client = TestClient(_make_app_with_db(db, runner_router))
        resp = client.post(
            "/api/v1/runner/task/register",
            json={
                "task_id": TASK_ID,
                "store_id": STORE_ID,
                "table_number": "A01",
                "order_id": ORDER_ID,
                "dish_name": "红烧肉",
            },
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["task_id"] == TASK_ID
    assert body["data"]["status"] == "pending"
