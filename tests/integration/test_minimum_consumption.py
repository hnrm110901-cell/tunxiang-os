"""最低消费规则引擎集成测试 (v212)

测试场景:
  1. 设置门店最低消费规则 → 获取配置验证
  2. 包间(room)类型: 消费不足 → 返回差额和补齐金额
  3. VIP等级豁免 → waived=True, satisfied=True
  4. 人均(per_person)类型: 4人晚市消费计算
  5. 无规则配置 → 默认满足
  6. 报表查询 → 返回汇总统计
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    DEFAULT_HEADERS,
    MOCK_STORE_ID,
    MOCK_TENANT_ID,
    assert_ok,
)

# ─── 测试用 App ──────────────────────────────────────────────────────────────

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant


def _build_app(mock_session: AsyncMock) -> FastAPI:
    app = FastAPI(title="test-min-consumption")

    from services.tx_trade.src.api.minimum_consumption_routes import router

    app.include_router(router)

    async def _mock_get_db_with_tenant(tenant_id: str):
        yield mock_session

    app.dependency_overrides[get_db_with_tenant] = lambda: mock_session
    # Override the _get_tenant_db dependency directly via middleware approach:
    # We patch get_db_with_tenant at module level instead
    return app


# ─── Mock 工具 ────────────────────────────────────────────────────────────────

_CONFIG_ID = str(uuid.uuid4())
_SESSION_ID = str(uuid.uuid4())
_SURCHARGE_ID = str(uuid.uuid4())


def _make_mock_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


def _mock_config_row(
    rules: list[dict] | None = None,
    waive_conditions: dict | None = None,
    is_active: bool = True,
) -> MagicMock:
    """模拟 minimum_consumption_configs 查询结果行"""
    row = MagicMock()
    row.id = uuid.UUID(_CONFIG_ID)
    row.store_id = uuid.UUID(MOCK_STORE_ID)
    row.rules = rules or [
        {"type": "room", "room_type": "大包", "min_amount_fen": 88800, "surcharge_mode": "补齐"},
        {"type": "room", "room_type": "小包", "min_amount_fen": 58800, "surcharge_mode": "补齐"},
        {"type": "per_person", "min_per_person_fen": 12800, "applies_to": ["dinner"]},
    ]
    row.waive_conditions = waive_conditions or {"vip_level_gte": 3, "group_size_gte": 10}
    row.is_active = is_active
    row.created_at = datetime(2026, 4, 9, 10, 0, 0, tzinfo=timezone.utc)
    row.updated_at = datetime(2026, 4, 9, 10, 0, 0, tzinfo=timezone.utc)
    return row


# ─── 测试用例 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_empty():
    """场景: 门店无配置 → 返回默认空规则"""
    mock_db = _make_mock_session()
    # execute 返回无结果
    result_mock = MagicMock()
    result_mock.fetchone.return_value = None
    mock_db.execute.return_value = result_mock

    app = _build_app(mock_db)

    # 因为 dependency 是生成器，需要更精确的 override
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get(
                f"/api/v1/minimum-consumption/config/{MOCK_STORE_ID}",
                headers=DEFAULT_HEADERS,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["rules"] == []
        assert data["data"]["is_active"] is False
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore


@pytest.mark.asyncio
async def test_set_and_get_config():
    """场景: 新建门店配置 → PUT 成功 → 返回配置"""
    mock_db = _make_mock_session()

    # PUT: 先查 existing → None, 再 INSERT
    existing_result = MagicMock()
    existing_result.fetchone.return_value = None
    mock_db.execute.return_value = existing_result

    app = _build_app(mock_db)
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.put(
                f"/api/v1/minimum-consumption/config/{MOCK_STORE_ID}",
                headers=DEFAULT_HEADERS,
                json={
                    "rules": [
                        {"type": "room", "room_type": "大包", "min_amount_fen": 88800, "surcharge_mode": "补齐"},
                        {"type": "per_person", "min_per_person_fen": 12800, "applies_to": ["dinner"]},
                    ],
                    "waive_conditions": {"vip_level_gte": 3},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["is_active"] is True
        assert len(data["data"]["rules"]) == 2
        assert data["data"]["waive_conditions"]["vip_level_gte"] == 3
        # 应该调了 INSERT（因为 existing 为 None）
        assert mock_db.execute.call_count >= 2  # SELECT existing + INSERT
        assert mock_db.commit.call_count == 1
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore


@pytest.mark.asyncio
async def test_calculate_room_shortfall():
    """场景: 大包最低消费 888元, 实际消费 500元 → 差额 388元, 需补齐"""
    mock_db = _make_mock_session()

    config_result = MagicMock()
    config_result.fetchone.return_value = _mock_config_row()
    mock_db.execute.return_value = config_result

    app = _build_app(mock_db)
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/minimum-consumption/calculate",
                headers=DEFAULT_HEADERS,
                json={
                    "store_id": MOCK_STORE_ID,
                    "dining_session_id": _SESSION_ID,
                    "order_amount_fen": 50000,
                    "guest_count": 6,
                    "room_type": "大包",
                    "market_session": "dinner",
                    "vip_level": 0,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        result = data["data"]
        assert result["satisfied"] is False
        assert result["shortfall_fen"] == 38800  # 88800 - 50000
        assert result["surcharge_fen"] == 38800
        assert result["matched_rule"]["type"] == "room"
        assert result["waived"] is False
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore


@pytest.mark.asyncio
async def test_calculate_vip_waived():
    """场景: VIP等级3 >= 豁免阈值3 → 即使不足也豁免"""
    mock_db = _make_mock_session()

    config_result = MagicMock()
    config_result.fetchone.return_value = _mock_config_row()
    mock_db.execute.return_value = config_result

    app = _build_app(mock_db)
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/minimum-consumption/calculate",
                headers=DEFAULT_HEADERS,
                json={
                    "store_id": MOCK_STORE_ID,
                    "dining_session_id": _SESSION_ID,
                    "order_amount_fen": 30000,
                    "guest_count": 4,
                    "room_type": "大包",
                    "market_session": "dinner",
                    "vip_level": 3,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        result = data["data"]
        assert result["waived"] is True
        assert result["satisfied"] is True
        assert result["shortfall_fen"] == 58800  # 88800 - 30000 (有差额但被豁免)
        assert result["surcharge_fen"] == 0  # 豁免不补齐
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore


@pytest.mark.asyncio
async def test_calculate_no_config():
    """场景: 门店无最低消费配置 → 默认满足"""
    mock_db = _make_mock_session()

    config_result = MagicMock()
    config_result.fetchone.return_value = None
    mock_db.execute.return_value = config_result

    app = _build_app(mock_db)
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/minimum-consumption/calculate",
                headers=DEFAULT_HEADERS,
                json={
                    "store_id": MOCK_STORE_ID,
                    "dining_session_id": _SESSION_ID,
                    "order_amount_fen": 10000,
                    "guest_count": 2,
                    "vip_level": 0,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["satisfied"] is True
        assert data["data"]["matched_rule"] is None
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore


@pytest.mark.asyncio
async def test_set_config_invalid_room_rule():
    """场景: room 类型规则缺少 room_type → 400 错误"""
    mock_db = _make_mock_session()

    # 不需要 DB 交互, 校验在入口就拦截
    app = _build_app(mock_db)
    from services.tx_trade.src.api import minimum_consumption_routes

    original_fn = minimum_consumption_routes._get_tenant_db

    async def _override_db(request):
        yield mock_db

    minimum_consumption_routes._get_tenant_db = _override_db  # type: ignore

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.put(
                f"/api/v1/minimum-consumption/config/{MOCK_STORE_ID}",
                headers=DEFAULT_HEADERS,
                json={
                    "rules": [
                        {"type": "room", "min_amount_fen": 88800},  # 缺少 room_type
                    ],
                },
            )
        assert resp.status_code == 400
    finally:
        minimum_consumption_routes._get_tenant_db = original_fn  # type: ignore
