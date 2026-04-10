"""crew_schedule / patrol / menu_engineering / shift_summary 路由测试

覆盖场景（共 16 个）：

crew_schedule_router.py（4个）：
1.  POST /api/v1/crew/checkin        — 正常上班打卡，返回 record + in_window=True
2.  POST /api/v1/crew/checkin        — 下班打卡，window 外时 warning 非空
3.  GET  /api/v1/crew/schedule       — 本周排班（current），返回 7 条记录
4.  POST /api/v1/crew/shift-swap     — 正常创建换班申请，返回 status=pending
5.  GET  /api/v1/crew/shift-swaps    — 查询全部换班申请列表，返回 items

patrol_router.py（4个）：
6.  POST /api/v1/crew/patrol-checkin  — 正常巡台记录，返回 checkin_id
7.  POST /api/v1/crew/patrol-checkin  — 5 分钟内重复巡台同一桌 → 429
8.  GET  /api/v1/crew/patrol-summary  — 返回今日巡台统计
9.  GET  /api/v1/crew/patrol-summary  — date 非法格式 → 400

menu_engineering_router.py（4个）：
10. GET  /api/v1/menu/engineering-analysis — DB不可用时返回空列表+ok=True
11. GET  /api/v1/menu/engineering-analysis — 含 Mock 数据时返回四象限分类结果
12. PATCH /api/v1/dishes/{dish_id}         — body={status: soldout}，DB不可用乐观成功
13. PATCH /api/v1/dishes/{dish_id}         — status 非 soldout → ok=False

shift_summary_router.py（3个）：
14. POST /api/v1/crew/generate-shift-summary — 返回 StreamingResponse (text/event-stream)
15. GET  /api/v1/crew/shift-summary-history  — 返回历史摘要列表，含 3 条记录
16. GET  /api/v1/crew/shift-summary-history  — 额外：crew_id 正确传播到历史数据
"""
import os
import sys
import types
import uuid
from datetime import date, timedelta

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 包层级建立 ───────────────────────────────────────────────────────────────

def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.routers",  os.path.join(_SRC_DIR, "routers"))


# ─── 正式导入 ──────────────────────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.crew_schedule_router import router as crew_schedule_router   # type: ignore
from src.routers.patrol_router import router as patrol_router                 # type: ignore
from src.routers.menu_engineering_router import router as menu_engineering_router  # type: ignore
from src.routers.shift_summary_router import router as shift_summary_router   # type: ignore

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STORE_ID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DISH_ID     = str(uuid.uuid4())
OPERATOR_ID = "op-crew-001"
HEADERS     = {
    "X-Tenant-ID":  TENANT_ID,
    "X-Operator-ID": OPERATOR_ID,
}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _app(*routers) -> FastAPI:
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# crew_schedule_router 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 1: 正常上班打卡（09:00 模拟）

def test_checkin_clock_in_success():
    """POST /crew/checkin（clock_in）：在合法时间窗口内打卡，返回 in_window=True。"""
    from datetime import datetime
    import src.routers.crew_schedule_router as _mod

    client = TestClient(_app(crew_schedule_router))

    # 强制 _validate_clock_window 返回 True（无论当前真实时间）
    with patch.object(_mod, "_validate_clock_window", return_value=True):
        resp = client.post(
            "/api/v1/crew/checkin",
            json={"type": "clock_in", "lat": 28.2, "lng": 112.9, "device_id": "dev-001"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["record"]["type"] == "clock_in"
    assert body["data"]["record"]["in_window"] is True
    assert body["data"]["warning"] is None


# 场景 2: 下班打卡，窗口外返回 warning

def test_checkin_clock_out_out_of_window():
    """POST /crew/checkin（clock_out 窗口外）：打卡成功但 warning 非空。"""
    import src.routers.crew_schedule_router as _mod

    client = TestClient(_app(crew_schedule_router))

    with patch.object(_mod, "_validate_clock_window", return_value=False):
        resp = client.post(
            "/api/v1/crew/checkin",
            json={"type": "clock_out"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["record"]["in_window"] is False
    assert body["data"]["warning"] is not None


# 场景 3: GET /crew/schedule — 本周排班返回 7 条

def test_get_schedule_current_week():
    """GET /crew/schedule?week=current：返回本周 7 天排班数据。"""
    client = TestClient(_app(crew_schedule_router))
    resp = client.get(
        "/api/v1/crew/schedule",
        params={"week": "current"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["week"] == "current"
    assert data["total"] == 7
    assert len(data["items"]) == 7
    # 每条记录含必要字段
    first = data["items"][0]
    assert "date" in first
    assert "weekday" in first
    assert "shift" in first


# 场景 4: POST /crew/shift-swap — 正常换班申请

def test_create_shift_swap_success():
    """POST /crew/shift-swap：创建换班申请，返回 status=pending + swap_id。"""
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    client = TestClient(_app(crew_schedule_router))
    resp = client.post(
        "/api/v1/crew/shift-swap",
        json={
            "from_date": tomorrow,
            "to_crew_id": "crew-009",
            "reason": "陪父母看病",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "pending"
    assert data["to_crew_id"] == "crew-009"
    assert data["id"].startswith("sw-")


# 场景 5: GET /crew/shift-swaps — 查询换班申请列表

def test_get_shift_swaps():
    """GET /crew/shift-swaps：返回我的换班申请（含 pending 和 approved）。"""
    client = TestClient(_app(crew_schedule_router))
    resp = client.get(
        "/api/v1/crew/shift-swaps",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert data["total"] >= 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# patrol_router 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 每次测试前清空 dedup_cache，避免测试间互相影响
import src.routers.patrol_router as _patrol_mod


def _clear_patrol_state():
    _patrol_mod._dedup_cache.clear()
    _patrol_mod._patrol_logs.clear()


# 场景 6: 正常巡台记录

def test_patrol_checkin_success():
    """POST /crew/patrol-checkin：首次巡台记录成功，返回 checkin_id 与 table_no。"""
    _clear_patrol_state()

    client = TestClient(_app(patrol_router))
    resp = client.post(
        "/api/v1/crew/patrol-checkin",
        json={"table_no": "A03", "beacon_id": "beacon-07", "signal_strength": -65},
        headers={**HEADERS, "X-Store-ID": STORE_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["table_no"] == "A03"
    assert "checkin_id" in data
    assert "checked_at" in data


# 场景 7: 5 分钟内重复巡台同一桌 → 429

def test_patrol_checkin_dedup():
    """同一 crew 5 分钟内重复巡台同一桌台，应返回 429 Too Many Requests。"""
    _clear_patrol_state()

    # 手动写入 dedup_cache，模拟 30 秒前刚刚记录过
    import time
    key = (TENANT_ID, OPERATOR_ID, "B02")
    _patrol_mod._dedup_cache[key] = time.time() - 30  # 30 秒前

    client = TestClient(_app(patrol_router))
    resp = client.post(
        "/api/v1/crew/patrol-checkin",
        json={"table_no": "B02"},
        headers={**HEADERS, "X-Store-ID": STORE_ID},
    )
    assert resp.status_code == 429
    assert "分钟" in resp.json()["detail"]


# 场景 8: GET /crew/patrol-summary — 返回今日统计

def test_patrol_summary_today():
    """GET /crew/patrol-summary：返回当日巡台统计（表数、时间线）。"""
    _clear_patrol_state()
    # 预写入 2 条 log（同一桌 + 不同桌）
    today = date.today().isoformat()
    _patrol_mod._patrol_logs.extend([
        {
            "id": "log-001",
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "crew_id": OPERATOR_ID,
            "table_no": "C01",
            "beacon_id": None,
            "signal_strength": None,
            "checked_at": f"{today}T10:00:00+00:00",
            "created_at": f"{today}T10:00:00+00:00",
        },
        {
            "id": "log-002",
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "crew_id": OPERATOR_ID,
            "table_no": "C02",
            "beacon_id": None,
            "signal_strength": None,
            "checked_at": f"{today}T11:00:00+00:00",
            "created_at": f"{today}T11:00:00+00:00",
        },
    ])

    client = TestClient(_app(patrol_router))
    resp = client.get(
        "/api/v1/crew/patrol-summary",
        params={"date": today},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["tables_visited_count"] == 2
    assert len(data["timeline"]) == 2


# 场景 9: date 非法格式 → 400

def test_patrol_summary_invalid_date():
    """patrol-summary 传入非法 date 格式，应返回 400 Bad Request。"""
    _clear_patrol_state()

    client = TestClient(_app(patrol_router))
    resp = client.get(
        "/api/v1/crew/patrol-summary",
        params={"date": "not-a-date"},
        headers=HEADERS,
    )
    assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# menu_engineering_router 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 10: DB 不可用时返回空列表

def test_menu_engineering_db_unavailable():
    """DB 不可用（import 失败/异常）时，应返回空列表而非 500 报错。"""
    client = TestClient(_app(menu_engineering_router))
    resp = client.get(
        "/api/v1/menu/engineering-analysis",
        params={"period": "week", "store_id": STORE_ID},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # 无 DB 时 dishes 为空列表
    assert body["data"]["dishes"] == []
    assert body["data"]["summary"]["star"] == 0


# 场景 11: 含 Mock 数据时返回四象限分析

def test_menu_engineering_with_mock_data():
    """直接调用 _build_analysis 业务函数验证四象限逻辑。"""
    from src.routers.menu_engineering_router import _build_analysis  # type: ignore

    raw = [
        {"id": "d1", "name": "宫保鸡丁", "price": 4800, "cost": 1200, "sales_count": 100},
        {"id": "d2", "name": "红烧肉",   "price": 6800, "cost": 1500, "sales_count": 20},
        {"id": "d3", "name": "水煮鱼",   "price": 5800, "cost": 3000, "sales_count": 80},
        {"id": "d4", "name": "青菜",     "price": 1800, "cost": 500,  "sales_count": 10},
    ]
    result = _build_analysis(raw)
    dishes = result["dishes"]
    summary = result["summary"]

    # 四道菜各归入不同象限，汇总总数 = 4
    total_quadrant = sum(summary.values())
    assert total_quadrant == 4

    # 宫保鸡丁：高销量+高毛利 → star
    d1 = next(d for d in dishes if d["id"] == "d1")
    assert d1["quadrant"] == "star"

    # 检查所有菜品都有 quadrant 字段
    for d in dishes:
        assert d["quadrant"] in ("star", "cash_cow", "plowshare", "dog")


# 场景 12: PATCH /dishes/{dish_id} — DB 不可用时乐观成功

def test_patch_dish_soldout_db_unavailable():
    """DB 不可用时，PATCH 菜品下架应乐观返回 ok=True（Mock 模式）。"""
    client = TestClient(_app(menu_engineering_router))
    resp = client.patch(
        f"/api/v1/dishes/{DISH_ID}",
        json={"status": "soldout"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["dish_id"] == DISH_ID
    assert body["data"]["status"] == "soldout"


# 场景 13: PATCH /dishes/{dish_id} — status 非 soldout 时报错

def test_patch_dish_invalid_status():
    """PATCH /dishes/{dish_id} 传入 status 非 soldout，应返回 ok=False 并含错误信息。"""
    client = TestClient(_app(menu_engineering_router))
    resp = client.patch(
        f"/api/v1/dishes/{DISH_ID}",
        json={"status": "active"},
        headers=HEADERS,
    )
    assert resp.status_code == 200  # 路由返回 200 但 ok=False
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_STATUS"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# shift_summary_router 测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 场景 14: POST /crew/generate-shift-summary — SSE 流式响应

async def _instant_mock_stream():
    """无 sleep 的即时 mock 流，避免 TestClient 阻塞。"""
    import json as _json
    payload = _json.dumps({"chunk": "测试摘要内容", "done": False}, ensure_ascii=False)
    yield f"data: {payload}\n\n"
    yield f"data: {_json.dumps({'chunk': '', 'done': True})}\n\n"


def test_generate_shift_summary_sse():
    """POST /crew/generate-shift-summary：返回 text/event-stream，包含 SSE 格式 chunk。"""
    import src.routers.shift_summary_router as _ss_mod

    client = TestClient(_app(shift_summary_router))

    # patch _stream_claude 为无延迟的即时版本，避免 asyncio.sleep 阻塞
    with patch.object(_ss_mod, "_stream_claude", return_value=_instant_mock_stream()):
        resp = client.post(
            "/api/v1/crew/generate-shift-summary",
            json={
                "crew_id": "crew-001",
                "shift_data": {
                    "table_count": 12,
                    "revenue_fen": 456700,
                    "turnover_rate": 2.3,
                    "satisfaction": 92,
                    "pending_count": 1,
                    "complaint_count": 0,
                },
            },
            headers=HEADERS,
        )
    assert resp.status_code == 200
    # 响应类型为 SSE
    assert "text/event-stream" in resp.headers.get("content-type", "")
    # 响应体含 SSE data: 格式
    content = resp.text
    assert "data:" in content
    assert '"chunk"' in content


# 场景 15: GET /crew/shift-summary-history — 历史摘要列表

def test_get_shift_summary_history():
    """GET /crew/shift-summary-history：返回历史班次摘要列表，含 3 条 Mock 数据。"""
    client = TestClient(_app(shift_summary_router))
    resp = client.get(
        "/api/v1/crew/shift-summary-history",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 3
    # 每条记录含必要字段
    first = data["items"][0]
    assert "id" in first
    assert "summary" in first
    assert "shift_date" in first


# 场景 16: 历史摘要 crew_id 传播验证

def test_shift_summary_history_crew_id_propagated():
    """GET /crew/shift-summary-history：历史数据中的 crew_id 应与 X-Operator-ID 一致。"""
    custom_operator = "crew-special-777"
    client = TestClient(_app(shift_summary_router))
    resp = client.get(
        "/api/v1/crew/shift-summary-history",
        headers={
            "X-Tenant-ID": TENANT_ID,
            "X-Operator-ID": custom_operator,
        },
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    # Mock 实现应将 crew_id 填为传入的 operator_id
    for item in items:
        assert item["crew_id"] == custom_operator
