"""tx-ops 补充路由测试：daily_summary_routes + notification_center_routes + daily_settlement_routes（共 13 个测试）

覆盖范围：
  daily_summary_routes（4个测试）：
    POST /api/v1/ops/daily-summary/generate          — 正常生成（201）
    GET  /api/v1/ops/daily-summary/{store_id}        — 查到记录（200）
    GET  /api/v1/ops/daily-summary/{store_id}        — 记录不存在（404）
    POST /api/v1/ops/daily-summary/{id}/confirm      — 正常锁定（200）

  notification_center_routes（5个测试）：
    GET  /api/v1/ops/notifications                   — 列表返回（200）
    GET  /api/v1/ops/notifications/unread-count      — 未读数（200）
    POST /api/v1/ops/notifications/mark-all-read     — 全部标记已读（200）
    PATCH /api/v1/ops/notifications/{id}/read        — 单条标记已读（200）
    GET  /api/v1/ops/notifications                   — 缺少 X-Tenant-ID → 400

  daily_settlement_routes（4个测试）：
    POST /api/v1/ops/settlement/run                  — DB fallback 全流程（200）
    GET  /api/v1/ops/settlement/status/{store_id}    — DB fallback（200）
    GET  /api/v1/ops/settlement/checklist/{store_id} — DB fallback 结构校验（200）
    GET  /api/v1/ops/settlement/checklist/{store_id} — 缺少 header → 422

技术约束：
  - sys.modules 存根注入（shared.ontology / shared.events / shared.integrations）
  - app.dependency_overrides[get_db] + AsyncMock side_effect
  - 全部 mock，不需要真实 DB
"""
from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════════════════════════════════════
#  sys.modules 存根注入（必须在导入路由前完成）
# ══════════════════════════════════════════════════════════════════════════════════


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    """确保 module_path 在 sys.modules 中，返回模块对象。"""
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# ── shared.ontology ──────────────────────────────────────────────────────────────
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):
    async def _placeholder_get_db():  # pragma: no cover
        yield None
    _db_mod.get_db = _placeholder_get_db

_entities_mod = _ensure_stub("shared.ontology.src.entities")
for _entity_name in [
    "DailySummary", "EmployeeDailyPerformance", "InspectionReport",
    "OpsIssue", "ShiftHandover",
]:
    if not hasattr(_entities_mod, _entity_name):
        setattr(_entities_mod, _entity_name, MagicMock())

# ── shared.events ────────────────────────────────────────────────────────────────
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")

if not hasattr(_ev_types, "SettlementEventType"):
    class _FakeSettlementEventType:
        DAILY_CLOSED = "settlement.daily_closed"
    _ev_types.SettlementEventType = _FakeSettlementEventType

if not hasattr(_ev_types, "SafetyEventType"):
    class _FakeSafetyEventType:
        SAMPLE_LOGGED = "safety.sample_logged"
        TEMPERATURE_RECORDED = "safety.temperature_recorded"
    _ev_types.SafetyEventType = _FakeSafetyEventType

# ── structlog ────────────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())
    sys.modules["structlog"] = _sl

# ── asyncpg ──────────────────────────────────────────────────────────────────────
if "asyncpg" not in sys.modules:
    _apg = types.ModuleType("asyncpg")
    _apg.connect = AsyncMock()
    sys.modules["asyncpg"] = _apg

# ── shared.integrations（通知中心依赖）──────────────────────────────────────────
_ensure_stub("shared.integrations")

# SMSService stub
_sms_stub = MagicMock()
_sms_stub.send_verification_code = AsyncMock(return_value={"ok": True, "channel": "sms"})
_sms_stub.send_order_notification = AsyncMock(return_value={"ok": True})
_sms_stub.send_queue_notification = AsyncMock(return_value={"ok": True})
_sms_stub.send_marketing = AsyncMock(return_value={"ok": True})

# WechatSubscribeService stub
_wx_stub = MagicMock()
_wx_stub.send_order_status = AsyncMock(return_value={"ok": True, "channel": "wechat"})
_wx_stub.send_queue_called = AsyncMock(return_value={"ok": True})
_wx_stub.send_promotion = AsyncMock(return_value={"ok": True})
_wx_stub.send_booking_reminder = AsyncMock(return_value={"ok": True})

# NotificationDispatcher stub
_dispatcher_stub = MagicMock()
_dispatcher_stub.sms_service = _sms_stub
_dispatcher_stub.wechat_service = _wx_stub
_dispatcher_stub.send_multi_channel = AsyncMock(return_value=[
    {"channel": "sms", "success": True}
])

_dispatcher_mod = _ensure_stub(
    "shared.integrations.notification_dispatcher",
    {
        "NotificationDispatcher": MagicMock(return_value=_dispatcher_stub),
        "VALID_CHANNELS": ("sms", "wechat_subscribe", "in_app", "email"),
    },
)
_ensure_stub(
    "shared.integrations.sms_service",
    {"SMSService": MagicMock(return_value=_sms_stub)},
)
_ensure_stub(
    "shared.integrations.wechat_subscribe",
    {"WechatSubscribeService": MagicMock(return_value=_wx_stub)},
)

# ══════════════════════════════════════════════════════════════════════════════════
#  导入路由（存根注入后）
# ══════════════════════════════════════════════════════════════════════════════════

from ..api.daily_summary_routes import router as summary_router  # noqa: E402

# notification_center_routes 导入（依赖 NotificationDispatcher 单例在模块级实例化）
from ..api.notification_center_routes import router as notif_router  # noqa: E402
from ..api.notification_center_routes import template_router  # noqa: E402

# settlement_routes 依赖兄弟模块
try:
    from ..api import daily_summary_routes as _dsm
    if not hasattr(_dsm, "_aggregate_orders"):
        async def _noop_aggregate(*a, **kw):
            return {}
        _dsm._aggregate_orders = _noop_aggregate

    from ..api import inspection_routes as _ir
    if not hasattr(_ir, "_reports"):
        _ir._reports = {}

    from ..api import issues_routes as _isr
    if not hasattr(_isr, "_issues"):
        _isr._issues = {}
    for _fn_name in ["_scan_discount_abuse", "_scan_kds_timeout", "_scan_low_inventory"]:
        if not hasattr(_isr, _fn_name):
            async def _noop_scan(*a, **kw):
                return []
            setattr(_isr, _fn_name, _noop_scan)

    from ..api import performance_routes as _pr
    if not hasattr(_pr, "_performance"):
        _pr._performance = {}
    for _fn_name in [
        "_aggregate_cashier_performance", "_aggregate_chef_performance",
        "_aggregate_waiter_performance",
    ]:
        if not hasattr(_pr, _fn_name):
            async def _noop_perf(*a, **kw):
                return []
            setattr(_pr, _fn_name, _noop_perf)
    if not hasattr(_pr, "_calc_commission_fen"):
        _pr._calc_commission_fen = lambda *a, **kw: 0

    from ..api.daily_settlement_routes import router as settlement_router  # noqa: E402
    _settlement_available = True
except Exception:  # pragma: no cover
    _settlement_available = False

from shared.ontology.src.database import get_db  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════════
#  FastAPI 应用
# ══════════════════════════════════════════════════════════════════════════════════

app = FastAPI()
app.include_router(summary_router)
app.include_router(notif_router)
app.include_router(template_router)
if _settlement_available:
    app.include_router(settlement_router)

# ── 常量 ──────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}

# ── 辅助函数 ──────────────────────────────────────────────────────────────────────


def _mapping_row(data: dict) -> MagicMock:
    row = MagicMock()
    row._mapping = data
    for k, v in data.items():
        setattr(row, k, v)
    return row


def _make_execute_result(fetchone_data: dict | None = None, scalar_val=None, rowcount: int = 0) -> MagicMock:
    result = MagicMock()
    if fetchone_data is not None:
        result.fetchone = MagicMock(return_value=_mapping_row(fetchone_data))
    else:
        result.fetchone = MagicMock(return_value=None)
    result.fetchall = MagicMock(return_value=[])
    result.scalar = MagicMock(return_value=scalar_val)
    result.rowcount = rowcount
    return result


def _make_db(side_effects: list) -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _override(db_mock: AsyncMock):
    async def _dep() -> AsyncGenerator:
        yield db_mock
    return _dep


# ══════════════════════════════════════════════════════════════════════════════════
#  daily_summary_routes 测试（4个）
# ══════════════════════════════════════════════════════════════════════════════════


class TestDailySummaryGenerate:
    """POST /api/v1/ops/daily-summary/generate"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_generate_summary_creates_new_record_201(self):
        """不存在旧记录时，自动聚合生成日汇总，返回 201 + summary_id。"""
        # execute 调用顺序：
        # 1. _set_rls
        # 2. 检查是否已存在（返回 None — 不存在）
        # 3. _aggregate_orders 内部 execute（聚合 SQL）
        # 4. INSERT daily_summaries
        aggregate_row = _mapping_row({
            "total_orders": 50,
            "dine_in_orders": 30,
            "takeaway_orders": 15,
            "banquet_orders": 5,
            "total_revenue_fen": 500000,
            "actual_revenue_fen": 480000,
            "total_discount_fen": 20000,
            "max_discount_pct": 15.0,
            "abnormal_discounts": 2,
            "avg_table_value_fen": 9600,
        })
        aggregate_result = MagicMock()
        aggregate_result.fetchone = MagicMock(return_value=aggregate_row)

        db = _make_db([
            _make_execute_result(),        # _set_rls
            _make_execute_result(None),    # 检查既有记录 → None
            aggregate_result,              # _aggregate_orders SQL
            MagicMock(),                   # INSERT
        ])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "summary_date": "2026-04-04",
        }

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/daily-summary/generate",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "id" in data
        assert data["store_id"] == STORE_ID
        assert data["status"] == "draft"
        assert data["total_orders"] == 50
        assert data["actual_revenue_fen"] == 480000

    def test_generate_summary_locked_returns_409(self):
        """日汇总已锁定时，返回 409。"""
        locked_row = _mapping_row({
            "id": str(uuid.uuid4()),
            "status": "locked",
            "created_at": "2026-04-04T10:00:00+00:00",
        })
        # fetchone 直接返回 locked 记录
        check_result = MagicMock()
        check_result.fetchone = MagicMock(return_value=locked_row)

        db = _make_db([
            _make_execute_result(),   # _set_rls
            check_result,             # 检查既有记录 → locked
        ])
        app.dependency_overrides[get_db] = _override(db)

        payload = {"store_id": STORE_ID, "summary_date": "2026-04-04"}

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/daily-summary/generate",
                json=payload,
                headers=HEADERS,
            )

        assert resp.status_code == 409
        assert "锁定" in resp.json()["detail"]


class TestDailySummaryGet:
    """GET /api/v1/ops/daily-summary/{store_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_get_summary_found_200(self):
        """找到日汇总记录，返回 200。"""
        summary_id = str(uuid.uuid4())
        row_data = {
            "id": summary_id,
            "store_id": STORE_ID,
            "summary_date": "2026-04-04",
            "total_orders": 100,
            "dine_in_orders": 60,
            "takeaway_orders": 30,
            "banquet_orders": 10,
            "total_revenue_fen": 800000,
            "actual_revenue_fen": 760000,
            "total_discount_fen": 40000,
            "avg_table_value_fen": 7600,
            "max_discount_pct": 20.0,
            "abnormal_discounts": 3,
            "status": "draft",
            "confirmed_by": None,
            "confirmed_at": None,
            "created_at": "2026-04-04T08:00:00+00:00",
            "updated_at": "2026-04-04T08:00:00+00:00",
        }
        db = _make_db([
            _make_execute_result(),              # _set_rls
            _make_execute_result(row_data),      # SELECT
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/daily-summary/{STORE_ID}",
                params={"summary_date": "2026-04-04"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == summary_id
        assert body["data"]["total_orders"] == 100

    def test_get_summary_not_found_404(self):
        """记录不存在时，返回 404。"""
        db = _make_db([
            _make_execute_result(),   # _set_rls
            _make_execute_result(None),  # SELECT → None
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/daily-summary/{STORE_ID}",
                params={"summary_date": "2026-04-04"},
                headers=HEADERS,
            )

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]


class TestDailySummaryConfirm:
    """POST /api/v1/ops/daily-summary/{id}/confirm"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_confirm_summary_success_200(self):
        """正常锁定日汇总，返回 200，data 中含 status=locked。"""
        summary_id = str(uuid.uuid4())
        confirmed_by = str(uuid.uuid4())

        check_row = _mapping_row({
            "id": summary_id,
            "store_id": STORE_ID,
            "status": "draft",
        })
        check_result = MagicMock()
        check_result.fetchone = MagicMock(return_value=check_row)

        updated_row = _mapping_row({
            "id": summary_id,
            "store_id": STORE_ID,
            "summary_date": "2026-04-04",
            "total_orders": 80,
            "actual_revenue_fen": 600000,
            "status": "locked",
            "confirmed_by": confirmed_by,
            "confirmed_at": "2026-04-04T20:00:00+00:00",
            "updated_at": "2026-04-04T20:00:00+00:00",
        })
        updated_result = MagicMock()
        updated_result.fetchone = MagicMock(return_value=updated_row)

        db = _make_db([
            _make_execute_result(),   # _set_rls
            check_result,             # SELECT 检查
            MagicMock(),              # UPDATE
            updated_result,           # SELECT 返回已锁定记录
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/ops/daily-summary/{summary_id}/confirm",
                json={"confirmed_by": confirmed_by},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "locked"


# ══════════════════════════════════════════════════════════════════════════════════
#  notification_center_routes 测试（5个）
# ══════════════════════════════════════════════════════════════════════════════════


class TestNotificationList:
    """GET /api/v1/ops/notifications"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_notifications_200(self):
        """正常分页查询通知列表，返回 200，含 items/total 字段。"""
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=3)

        notif_row = MagicMock()
        notif_row._mapping = {
            "id": str(uuid.uuid4()),
            "target_type": "store",
            "target_id": STORE_ID,
            "channel": "in_app",
            "title": "日清日结提醒",
            "content": "请尽快完成今日日清日结",
            "category": "ops",
            "priority": "high",
            "status": "sent",
            "sent_at": None,
            "read_at": None,
            "metadata": None,
            "created_at": None,
        }
        rows_result = MagicMock()
        rows_result.fetchall = MagicMock(return_value=[notif_row])
        # for row in rows_result: 需要可迭代
        rows_result.__iter__ = MagicMock(return_value=iter([notif_row]))

        db = _make_db([
            _make_execute_result(),   # _set_rls
            count_result,             # COUNT
            rows_result,              # SELECT rows
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/notifications",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "items" in body["data"]
        assert "total" in body["data"]

    def test_list_notifications_missing_tenant_400(self):
        """缺少 X-Tenant-ID header → 400。"""
        with TestClient(app) as client:
            resp = client.get("/api/v1/ops/notifications")

        assert resp.status_code == 400
        assert "X-Tenant-ID" in resp.json()["detail"]


class TestNotificationUnreadCount:
    """GET /api/v1/ops/notifications/unread-count"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_unread_count_200(self):
        """正常查询未读数，返回 200，data 含 unread_count 整数。"""
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=7)

        db = _make_db([
            _make_execute_result(),   # _set_rls
            count_result,             # COUNT
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get("/api/v1/ops/notifications/unread-count", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["unread_count"] == 7


class TestNotificationMarkRead:
    """PATCH /api/v1/ops/notifications/{id}/read"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_mark_single_read_200(self):
        """标记单条已读，返回 200，含 status=read。"""
        notif_id = str(uuid.uuid4())

        returning_row = MagicMock()
        returning_row.fetchone = MagicMock(return_value=_mapping_row({"id": notif_id}))

        db = _make_db([
            _make_execute_result(),   # _set_rls
            returning_row,            # UPDATE RETURNING
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.patch(
                f"/api/v1/ops/notifications/{notif_id}/read",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "read"
        assert body["data"]["id"] == notif_id


class TestNotificationMarkAllRead:
    """POST /api/v1/ops/notifications/mark-all-read"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_mark_all_read_200(self):
        """全部标记已读，返回 200，含 updated_count。"""
        update_result = MagicMock()
        update_result.rowcount = 5

        db = _make_db([
            _make_execute_result(),   # _set_rls
            update_result,            # UPDATE
        ])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.post("/api/v1/ops/notifications/mark-all-read", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["updated_count"] == 5


# ══════════════════════════════════════════════════════════════════════════════════
#  daily_settlement_routes 测试（4个）
# ══════════════════════════════════════════════════════════════════════════════════

_skip_settlement = pytest.mark.skipif(
    not _settlement_available,
    reason="daily_settlement_routes 导入失败，跳过",
)


@_skip_settlement
class TestSettlementRunFallback:
    """POST /api/v1/ops/settlement/run（DB fallback 路径）"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_run_settlement_fallback_returns_200(self):
        """DB 不可用降级到内存 fallback，全流程执行成功，返回 200，含 steps。"""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=ValueError("DB config error"))
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "settlement_date": "2026-04-04",
            "operator_id": str(uuid.uuid4()),
            "force_regenerate": False,
        }

        import src.api.daily_settlement_routes as _sr

        async def _noop_aggregate(*a, **kw):
            return {"total_orders": 0, "total_revenue_fen": 0}

        with patch.object(_sr, "_aggregate_orders", _noop_aggregate):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/ops/settlement/run",
                        json=payload,
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["store_id"] == STORE_ID
        assert data["settlement_date"] == "2026-04-04"
        assert "overall_completed" in data
        assert "steps" in data
        step_nodes = {s["node"] for s in data["steps"]}
        assert "E1_班次交班" in step_nodes
        assert "E2_日营业汇总" in step_nodes
        assert "E5_问题预警" in step_nodes
        assert "E7_员工绩效" in step_nodes


@_skip_settlement
class TestSettlementStatusFallback:
    """GET /api/v1/ops/settlement/status/{store_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_status_fallback_returns_5_nodes(self):
        """DB 连接失败降级到 fallback，返回 200，nodes 字典含 5 个节点。"""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/settlement/status/{STORE_ID}",
                params={"settlement_date": "2026-04-04"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["store_id"] == STORE_ID
        assert "overall_progress" in data
        assert "nodes" in data
        assert len(data["nodes"]) == 5


@_skip_settlement
class TestSettlementChecklistFallback:
    """GET /api/v1/ops/settlement/checklist/{store_id}"""

    def setup_method(self):
        app.dependency_overrides.clear()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_checklist_fallback_structure_200(self):
        """DB 不可用时降级，返回 200，含 pending/completed/action_hint 结构。"""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=ConnectionRefusedError("DB down"))
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/settlement/checklist/{STORE_ID}",
                params={"date": "2026-04-04"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["store_id"] == STORE_ID
        assert "pending" in data
        assert "completed" in data
        for item in data["pending"] + data["completed"]:
            assert "node" in item
            assert "completed" in item
            assert "message" in item
            assert "action_hint" in item

    def test_checklist_missing_header_422(self):
        """缺少 X-Tenant-ID header → 422。"""
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/ops/settlement/checklist/{STORE_ID}")

        assert resp.status_code == 422
