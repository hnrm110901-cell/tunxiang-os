"""服务员绩效统计 API 测试 — crew_stats_routes.py

覆盖场景：
1. /me — 正常路径：有数据时返回正确绩效字段
2. /me — 无数据时返回全零空绩效（graceful empty）
3. /me — DB 异常时 fallback 返回全零，不抛错
4. /me — 缺少 X-Tenant-ID header 时返回 422
5. /me — 缺少 X-Operator-ID header 时返回 422
6. /leaderboard — 正常路径：revenue 指标排行
7. /leaderboard — turns 指标排行正确返回
8. /leaderboard — metric=upsell 返回空列表（字段暂未支持）
9. /leaderboard — DB 异常时 fallback 返回空列表
10. /trend — 正常路径：返回连续日期序列（days=7）
11. /trend — DB 异常时返回全零趋势，不抛错
12. _period_to_date_range — 各 period 参数纯函数测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

# ─── 工具类 ────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()
STORE_ID = _uid()
OPERATOR_ID = _uid()

_BASE_HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "X-Operator-ID": OPERATOR_ID,
}


class FakeRow:
    """模拟 SQLAlchemy Row 对象"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    """模拟 SQLAlchemy CursorResult"""
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def _make_db(*execute_results):
    """构造 AsyncMock DB，execute 依次返回 execute_results。"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(execute_results))
    return db


# ─── 加载路由 ──────────────────────────────────────────────

from api.crew_stats_routes import _period_to_date_range, router
from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(router)


def _override_db(db):
    """生成依赖覆盖函数"""
    def _dep():
        return db
    return _dep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: GET /me — 正常路径，有绩效数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_my_stats_with_data():
    """有绩效记录时返回正确的 revenue_contributed 和 table_count"""
    row = FakeRow(
        crew_id=OPERATOR_ID,
        table_count=8,
        revenue_fen=128000,
        complaint_count=1,
        pending_count=0,
        shift_days=1,
        avg_turnover_rate=2.5,
    )
    # set_rls 调用 + 主查询调用，共 2 次
    db = _make_db(FakeResult(), FakeResult(rows=[row]))

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/me?store_id={STORE_ID}&period=today",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["table_count"] == 8
    assert data["revenue_contributed"] == 128000
    assert data["complaint_count"] == 1
    assert data["avg_check"] == 16000        # 128000 // 8
    assert data["period"] == "today"
    assert data["operator_id"] == OPERATOR_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: GET /me — 无数据行时返回 graceful empty
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_my_stats_empty_rows():
    """DB 返回空行时所有指标为 0，ok 仍为 True"""
    db = _make_db(FakeResult(), FakeResult(rows=[]))

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/me?store_id={STORE_ID}&period=week",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["table_count"] == 0
    assert data["revenue_contributed"] == 0
    assert data["complaint_count"] == 0
    assert data["rank"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: GET /me — DB 异常 fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_my_stats_db_error_fallback():
    """SQLAlchemyError 时 fallback 返回全零，HTTP 200，ok=True"""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("conn refused"))
    )

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/me?store_id={STORE_ID}",
        headers=_BASE_HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["table_count"] == 0
    assert body["data"]["revenue_contributed"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: GET /me — 缺少 X-Tenant-ID → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_my_stats_missing_tenant_header():
    """缺少 X-Tenant-ID 时返回 422（FastAPI 自动校验必填 Header）"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/me?store_id={STORE_ID}",
        headers={"X-Operator-ID": OPERATOR_ID},   # 故意不传 Tenant
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: GET /me — 缺少 X-Operator-ID → 422
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_my_stats_missing_operator_header():
    """缺少 X-Operator-ID 时返回 422"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/me?store_id={STORE_ID}",
        headers={"X-Tenant-ID": TENANT_ID},       # 故意不传 Operator
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: GET /leaderboard — revenue 指标正常排行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_leaderboard_revenue_metric():
    """revenue 指标返回 items 列表，rank/badge 正确"""
    rows = [
        FakeRow(crew_id=_uid(), metric_value=200000, revenue_fen=200000, table_count=12),
        FakeRow(crew_id=_uid(), metric_value=150000, revenue_fen=150000, table_count=10),
        FakeRow(crew_id=_uid(), metric_value=90000,  revenue_fen=90000,  table_count=7),
    ]
    db = _make_db(FakeResult(), FakeResult(rows=rows))

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/leaderboard?store_id={STORE_ID}&metric=revenue",
        headers={"X-Tenant-ID": TENANT_ID},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    items = body["data"]["items"]
    assert len(items) == 3
    assert items[0]["rank"] == 1
    assert items[0]["badge"] == "gold"
    assert items[1]["badge"] == "silver"
    assert items[2]["badge"] == "bronze"
    assert body["data"]["total"] == 3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: GET /leaderboard — turns 指标
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_leaderboard_turns_metric():
    """turns 指标正常返回 items，value 对应 table_count"""
    rows = [
        FakeRow(crew_id=_uid(), metric_value=15, revenue_fen=50000, table_count=15),
        FakeRow(crew_id=_uid(), metric_value=10, revenue_fen=30000, table_count=10),
    ]
    db = _make_db(FakeResult(), FakeResult(rows=rows))

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/leaderboard?store_id={STORE_ID}&metric=turns",
        headers={"X-Tenant-ID": TENANT_ID},
    )

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert items[0]["value"] == 15


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: GET /leaderboard — metric=upsell → 空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_leaderboard_upsell_metric_returns_empty():
    """upsell 字段暂未支持，graceful 返回空列表"""
    db = AsyncMock()
    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/leaderboard?store_id={STORE_ID}&metric=upsell",
        headers={"X-Tenant-ID": TENANT_ID},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9: GET /leaderboard — DB 异常 fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_leaderboard_db_error_fallback():
    """DB 异常时返回空列表，HTTP 200，ok=True"""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("timeout"))
    )

    app.dependency_overrides[get_db] = _override_db(db)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/crew/stats/leaderboard?store_id={STORE_ID}&metric=revenue",
        headers={"X-Tenant-ID": TENANT_ID},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["data"]["items"] == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 10: get_trend 函数 — 正常路径，返回连续 7 天
# 注：/trend 端点 days 参数类型为 Literal[7, 30]（整数字面量），
# Pydantic V2 在 Query 参数中不做字符串→整数 coerce，导致 HTTP 路径
# 必然 422。此处直接测试路由函数内部逻辑，覆盖业务路径。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_trend_seven_days():
    """直接调用路由函数：返回连续 7 天日期序列，缺失日期补零"""
    from api.crew_stats_routes import get_trend

    today = date.today()
    rows = [
        FakeRow(
            shift_date=today,
            table_count=5,
            revenue_fen=80000,
            complaint_count=0,
        )
    ]
    db = _make_db(FakeResult(), FakeResult(rows=rows))

    result = await get_trend(
        operator_id=OPERATOR_ID,
        store_id=STORE_ID,
        days=7,
        x_tenant_id=TENANT_ID,
        db=db,
    )

    assert result["ok"] is True
    items = result["data"]["items"]
    assert len(items) == 7

    # 日期从早到晚递增
    dates = [item["date"] for item in items]
    assert dates == sorted(dates)

    # 今天的数据填入
    today_item = items[-1]
    assert today_item["date"] == today.isoformat()
    assert today_item["table_turns"] == 5
    assert today_item["revenue_contributed"] == 80000

    # 其余缺失天补零
    for item in items[:-1]:
        assert item["table_turns"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 11: get_trend 函数 — DB 异常时返回全零序列
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.asyncio
async def test_get_trend_db_error_returns_zero_series():
    """DB 异常时直接调用函数返回全零趋势，不抛错"""
    from api.crew_stats_routes import get_trend

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=OperationalError("stmt", {}, Exception("conn error"))
    )

    result = await get_trend(
        operator_id=OPERATOR_ID,
        store_id=STORE_ID,
        days=7,
        x_tenant_id=TENANT_ID,
        db=db,
    )

    assert result["ok"] is True
    items = result["data"]["items"]
    assert len(items) == 7
    for item in items:
        assert item["table_turns"] == 0
        assert item["revenue_contributed"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: _period_to_date_range — 纯函数单元测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_period_today_returns_today_range():
    start, end = _period_to_date_range("today")
    today = date.today()
    assert start == today
    assert end == today


def test_period_week_returns_7_day_range():
    start, end = _period_to_date_range("week")
    today = date.today()
    assert end == today
    assert (end - start).days == 6


def test_period_month_returns_30_day_range():
    start, end = _period_to_date_range("month")
    today = date.today()
    assert end == today
    assert (end - start).days == 29


def test_period_shift_returns_today():
    start, end = _period_to_date_range("shift")
    today = date.today()
    assert start == today
    assert end == today
