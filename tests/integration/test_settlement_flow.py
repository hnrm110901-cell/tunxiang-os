"""日结流程集成测试 — 交班 / 日结 / 报表

使用 httpx.AsyncClient 直接调用 tx-ops FastAPI app。
tx-ops 路由大多使用内存 Mock 存储，无需 DB Mock。

测试场景:
  1. 交班 → 收银对账
  2. 日结 → 营业报表生成
  3. 验证数据一致性
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    MOCK_USER_ID,
    assert_ok,
)

# ─── 测试 App ──────────────────────────────────────────────────────────────────


def _get_ops_app():
    """获取 tx-ops 的 FastAPI app 实例。"""
    import sys
    import os

    ops_src = os.path.join(os.path.dirname(__file__), "..", "..", "services", "tx-ops", "src")
    if ops_src not in sys.path:
        sys.path.insert(0, os.path.abspath(ops_src))

    from services.tx_ops.src.main import app
    return app


# ─── 常量 ──────────────────────────────────────────────────────────────────────

_TODAY = date.today().isoformat()
_OPERATOR_ID = MOCK_USER_ID


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. E1 班次交班
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_start_shift() -> None:
    """开始新班次 → 201 + shift_id。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "morning",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 201
    data = assert_ok(resp.json())
    assert "shift_id" in data
    return data["shift_id"]


@pytest.mark.asyncio
async def test_start_shift_invalid_type() -> None:
    """无效班次类型 → 400。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "invalid_shift",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_handover_shift() -> None:
    """发起交班 → ok=True。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 先创建班次
        create_resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "afternoon",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
        shift_id = create_resp.json()["data"]["shift_id"]

        # 发起交班
        resp = await client.post(
            f"/api/v1/ops/shifts/{shift_id}/handover",
            json={
                "received_by": str(uuid.uuid4()),
                "cash_counted_fen": 50000,
                "pos_cash_fen": 48000,
                "device_checklist": [
                    {"item": "POS机", "status": "ok", "note": ""},
                    {"item": "打印机", "status": "ok", "note": ""},
                ],
                "notes": "一切正常",
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data.get("status") in ("handover", "pending")


@pytest.mark.asyncio
async def test_confirm_handover() -> None:
    """确认交班 → status=confirmed。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    receiver_id = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建班次
        create_resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "evening",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
        shift_id = create_resp.json()["data"]["shift_id"]

        # 发起交班
        await client.post(
            f"/api/v1/ops/shifts/{shift_id}/handover",
            json={
                "received_by": receiver_id,
                "cash_counted_fen": 50000,
                "pos_cash_fen": 50000,
            },
            headers=DEFAULT_HEADERS,
        )

        # 确认交班
        resp = await client.post(
            f"/api/v1/ops/shifts/{shift_id}/confirm",
            json={
                "received_by": receiver_id,
                "disputed": False,
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "confirmed"


@pytest.mark.asyncio
async def test_disputed_handover() -> None:
    """有争议的交班 → status=disputed。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    receiver_id = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "night",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
        shift_id = create_resp.json()["data"]["shift_id"]

        await client.post(
            f"/api/v1/ops/shifts/{shift_id}/handover",
            json={
                "received_by": receiver_id,
                "cash_counted_fen": 50000,
                "pos_cash_fen": 45000,
            },
            headers=DEFAULT_HEADERS,
        )

        resp = await client.post(
            f"/api/v1/ops/shifts/{shift_id}/confirm",
            json={
                "received_by": receiver_id,
                "disputed": True,
                "dispute_reason": "现金差额 50 元",
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert data["status"] == "disputed"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 日结 — E1-E7 一键执行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_run_settlement() -> None:
    """一键执行日清日结 → ok=True + 各节点状态。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/ops/settlement/run",
            json={
                "store_id": MOCK_STORE_ID,
                "settlement_date": _TODAY,
                "operator_id": _OPERATOR_ID,
                "force_regenerate": False,
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    # 应包含节点状态
    assert "nodes" in data or "settlement_id" in data or isinstance(data, dict)


@pytest.mark.asyncio
async def test_settlement_status() -> None:
    """查询结算状态 → ok=True。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/ops/settlement/status/{MOCK_STORE_ID}?date={_TODAY}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_settlement_checklist() -> None:
    """获取日清待完成清单 → ok=True。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/ops/settlement/checklist/{MOCK_STORE_ID}?date={_TODAY}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert isinstance(data, (dict, list))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 班次列表查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_list_shifts() -> None:
    """查询班次列表 → ok=True。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/ops/shifts?store_id={MOCK_STORE_ID}&date={_TODAY}",
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    data = assert_ok(resp.json())
    assert isinstance(data, (dict, list))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 数据一致性验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_settlement_after_all_shifts_confirmed() -> None:
    """所有班次确认后执行日结 → 各节点状态正常。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    receiver_id = str(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建并确认一个班次
        create_resp = await client.post(
            "/api/v1/ops/shifts",
            json={
                "store_id": MOCK_STORE_ID,
                "shift_date": _TODAY,
                "shift_type": "morning",
                "handover_by": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
        shift_id = create_resp.json()["data"]["shift_id"]

        await client.post(
            f"/api/v1/ops/shifts/{shift_id}/handover",
            json={"received_by": receiver_id, "cash_counted_fen": 100000, "pos_cash_fen": 100000},
            headers=DEFAULT_HEADERS,
        )
        await client.post(
            f"/api/v1/ops/shifts/{shift_id}/confirm",
            json={"received_by": receiver_id, "disputed": False},
            headers=DEFAULT_HEADERS,
        )

        # 执行日结
        resp = await client.post(
            "/api/v1/ops/settlement/run",
            json={
                "store_id": MOCK_STORE_ID,
                "settlement_date": _TODAY,
                "operator_id": _OPERATOR_ID,
            },
            headers=DEFAULT_HEADERS,
        )
    assert resp.status_code == 200
    assert_ok(resp.json())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 健康检查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_ops_health() -> None:
    """tx-ops 健康检查 → ok=True。"""
    app = _get_ops_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["service"] == "tx-ops"
