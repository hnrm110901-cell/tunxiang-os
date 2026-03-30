"""厨房综合异常监控 API 测试

覆盖场景：
1. 综合面板返回三类异常（overtime + shortage + remake）
2. 无异常时各列为空列表，summary 全 0
3. 超时工单正确计算 elapsed_min 和 overtime_min
4. 各类单独过滤端点（overtime / shortage / remake）
5. 今日趋势按小时分桶，数据结构正确
6. 租户隔离：set_config 携带正确 tenant_id，不混用
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI


# ─── 工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()


class FakeRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _make_db(execute_results=None):
    db = AsyncMock()
    if execute_results:
        db.execute = AsyncMock(side_effect=execute_results)
    else:
        db.execute = AsyncMock(return_value=FakeResult())
    return db


# ─── 加载路由 ───

from api.kitchen_monitor_routes import router, _get_overtime_tasks, _get_shortage_alerts, _get_remake_tasks, _get_hourly_trend

app = FastAPI()
app.include_router(router, prefix="/api/v1/kitchen-monitor")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 1: 综合面板返回三类异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_dashboard_returns_all_three_anomaly_types():
    """dashboard 端点返回 overtime_tasks, shortage_alerts, remake_tasks"""
    overtime = [
        {"task_id": "t1", "table_no": "A01", "dish_name": "红烧肉",
         "elapsed_min": 25.0, "standard_min": 15, "overtime_min": 10.0,
         "status": "warning", "dept": "热菜"}
    ]
    shortage = [
        {"dish_id": "d1", "dish_name": "三文鱼", "shortage_count": 2,
         "latest_at": "2026-03-30T12:00:00+00:00"}
    ]
    remake = [
        {"task_id": "r1", "table_no": "B02", "dish_name": "小炒肉",
         "reason": "顾客不满", "created_at": "2026-03-30T11:30:00+00:00"}
    ]

    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_overtime_tasks", AsyncMock(return_value=overtime)), \
         patch("api.kitchen_monitor_routes._get_shortage_alerts", AsyncMock(return_value=shortage)), \
         patch("api.kitchen_monitor_routes._get_remake_tasks", AsyncMock(return_value=remake)):

        from fastapi.testclient import TestClient as SyncClient

        def _override_db():
            return db

        app.dependency_overrides = {}
        from api.kitchen_monitor_routes import _get_db
        app.dependency_overrides[_get_db] = _override_db

        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/dashboard/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["overtime_tasks"]) == 1
    assert len(data["shortage_alerts"]) == 1
    assert len(data["remake_tasks"]) == 1
    assert data["summary"]["total_anomalies"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 2: 无异常时各列为空列表，summary 全 0
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_dashboard_empty_when_no_anomalies():
    """无异常时面板返回空列表，summary 全为 0"""
    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_overtime_tasks", AsyncMock(return_value=[])), \
         patch("api.kitchen_monitor_routes._get_shortage_alerts", AsyncMock(return_value=[])), \
         patch("api.kitchen_monitor_routes._get_remake_tasks", AsyncMock(return_value=[])):

        from fastapi.testclient import TestClient as SyncClient
        from api.kitchen_monitor_routes import _get_db

        def _override_db():
            return db

        app.dependency_overrides[_get_db] = _override_db
        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/dashboard/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["overtime_tasks"] == []
    assert data["shortage_alerts"] == []
    assert data["remake_tasks"] == []
    summary = data["summary"]
    assert summary["overtime_count"] == 0
    assert summary["shortage_count"] == 0
    assert summary["remake_count"] == 0
    assert summary["total_anomalies"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 3: 超时工单正确计算 elapsed_min 和 overtime_min
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_overtime_elapsed_and_overtime_min_calculation():
    """_get_overtime_tasks 返回正确的 elapsed_min 和 overtime_min"""
    # check_timeouts 返回原始数据
    timeout_items = [
        {
            "order_item_id": "oi1",
            "order_no": "ORD001",
            "table_number": "A05",
            "dish": "剁椒鱼头",
            "dish_id": "d1",
            "dept": "热菜档口",
            "wait_minutes": 35.0,
            "threshold": 20,  # standard_min
            "status": "critical",
        }
    ]

    db = _make_db()

    with patch(
        "services.cooking_timeout.check_timeouts",
        AsyncMock(return_value=timeout_items),
    ):
        result = await _get_overtime_tasks(STORE_ID, TENANT_ID, db)

    assert len(result) == 1
    item = result[0]
    assert item["elapsed_min"] == 35.0
    assert item["standard_min"] == 20
    assert item["overtime_min"] == pytest.approx(15.0)
    assert item["status"] == "critical"
    assert item["table_no"] == "A05"
    assert item["dish_name"] == "剁椒鱼头"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 4: 各类单独过滤端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_individual_overtime_endpoint():
    """GET /overtime/{store_id} 只返回超时工单"""
    overtime = [
        {"task_id": "t1", "table_no": "A01", "dish_name": "外婆鸡",
         "elapsed_min": 30.0, "standard_min": 20, "overtime_min": 10.0,
         "status": "warning", "dept": "热菜"}
    ]
    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_overtime_tasks", AsyncMock(return_value=overtime)):
        from fastapi.testclient import TestClient as SyncClient
        from api.kitchen_monitor_routes import _get_db

        app.dependency_overrides[_get_db] = lambda: db
        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/overtime/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["dish_name"] == "外婆鸡"


@pytest.mark.asyncio
async def test_individual_shortage_endpoint():
    """GET /shortage/{store_id} 只返回沽清告警"""
    shortage = [
        {"dish_id": "d1", "dish_name": "象拔蚌", "shortage_count": 3,
         "latest_at": "2026-03-30T14:00:00+00:00"}
    ]
    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_shortage_alerts", AsyncMock(return_value=shortage)):
        from fastapi.testclient import TestClient as SyncClient
        from api.kitchen_monitor_routes import _get_db

        app.dependency_overrides[_get_db] = lambda: db
        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/shortage/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["alerts"][0]["dish_name"] == "象拔蚌"


@pytest.mark.asyncio
async def test_individual_remake_endpoint():
    """GET /remake/{store_id} 只返回退菜工单"""
    remake = [
        {"task_id": "r1", "table_no": "C03", "dish_name": "鱼香肉丝",
         "reason": "咸了", "created_at": "2026-03-30T13:00:00+00:00"}
    ]
    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_remake_tasks", AsyncMock(return_value=remake)):
        from fastapi.testclient import TestClient as SyncClient
        from api.kitchen_monitor_routes import _get_db

        app.dependency_overrides[_get_db] = lambda: db
        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/remake/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["tasks"][0]["reason"] == "咸了"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 5: 今日趋势按小时分桶
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_trend_hourly_bucketing():
    """GET /trend/{store_id} 返回按小时分桶的趋势数据"""
    db = AsyncMock()

    with patch("api.kitchen_monitor_routes._get_hourly_trend", AsyncMock(return_value=[
        {"hour": 0, "overtime_count": 0, "shortage_count": 0, "remake_count": 0},
        {"hour": 1, "overtime_count": 1, "shortage_count": 0, "remake_count": 0},
        {"hour": 2, "overtime_count": 0, "shortage_count": 2, "remake_count": 1},
    ])):
        from fastapi.testclient import TestClient as SyncClient
        from api.kitchen_monitor_routes import _get_db

        app.dependency_overrides[_get_db] = lambda: db
        client = SyncClient(app)
        resp = client.get(
            f"/api/v1/kitchen-monitor/trend/{STORE_ID}",
            headers={"X-Tenant-ID": TENANT_ID},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "trend" in data
    trend = data["trend"]
    assert len(trend) == 3

    # 验证小时桶结构
    for entry in trend:
        assert "hour" in entry
        assert "overtime_count" in entry
        assert "shortage_count" in entry
        assert "remake_count" in entry

    # 验证时序数据
    assert trend[1]["overtime_count"] == 1
    assert trend[2]["shortage_count"] == 2
    assert trend[2]["remake_count"] == 1


@pytest.mark.asyncio
async def test_trend_internal_query_structure():
    """_get_hourly_trend 内部调用三类异常分别查询，结构正确"""
    executed_sqls = []

    async def _capture(stmt, params=None, **kwargs):
        executed_sqls.append(str(stmt))
        return FakeResult(rows=[])

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_capture)

    await _get_hourly_trend(STORE_ID, TENANT_ID, db)

    # set_config + 超时查询 + 沽清查询 + 退菜查询 = 4 次调用
    assert len(executed_sqls) >= 4


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  场景 6: 租户隔离
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_tenant_isolation_in_shortage_query():
    """_get_shortage_alerts 查询参数中必须包含正确的 tenant_id"""
    TENANT_X = _uid()
    captured_params = []

    async def _capture(stmt, params=None, **kwargs):
        if params:
            captured_params.append(dict(params))
        return FakeResult(rows=[])

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_capture)

    await _get_shortage_alerts(STORE_ID, TENANT_X, db)

    tenant_params = [
        p for p in captured_params
        if "tenant_id" in p or "tid" in p
    ]
    assert len(tenant_params) > 0, "应有 tenant_id 参数传入查询"

    # 所有 tenant_id/tid 参数必须是 TENANT_X，不能是别的租户
    for p in tenant_params:
        if "tid" in p:
            assert p["tid"] == TENANT_X, f"set_config 应传 TENANT_X，实际: {p['tid']}"
        if "tenant_id" in p:
            assert p["tenant_id"] == TENANT_X, f"查询应用 TENANT_X，实际: {p['tenant_id']}"


@pytest.mark.asyncio
async def test_missing_tenant_id_header_returns_400():
    """缺少 X-Tenant-ID header 时返回 400"""
    db = AsyncMock()
    from api.kitchen_monitor_routes import _get_db

    app.dependency_overrides[_get_db] = lambda: db
    from fastapi.testclient import TestClient as SyncClient

    client = SyncClient(app)
    resp = client.get(f"/api/v1/kitchen-monitor/dashboard/{STORE_ID}")
    # 缺少 header 应返回 400 或 422
    assert resp.status_code in (400, 422)
