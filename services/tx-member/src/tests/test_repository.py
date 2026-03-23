"""CustomerRepository 单元测试 — 使用 mock AsyncSession"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.repository import CustomerRepository


TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())


def _make_customer(**overrides):
    c = MagicMock()
    c.id = overrides.get("id", uuid.uuid4())
    c.tenant_id = uuid.UUID(TENANT_ID)
    c.primary_phone = overrides.get("primary_phone", "13800138000")
    c.display_name = overrides.get("display_name", "张三")
    c.gender = overrides.get("gender", "male")
    c.source = overrides.get("source", "pos")
    c.rfm_level = overrides.get("rfm_level", "S1")
    c.rfm_recency_days = overrides.get("rfm_recency_days", 5)
    c.rfm_frequency = overrides.get("rfm_frequency", 12)
    c.rfm_monetary_fen = overrides.get("rfm_monetary_fen", 500000)
    c.total_order_count = overrides.get("total_order_count", 12)
    c.total_order_amount_fen = overrides.get("total_order_amount_fen", 500000)
    c.first_order_at = overrides.get("first_order_at", datetime.now(timezone.utc))
    c.last_order_at = overrides.get("last_order_at", datetime.now(timezone.utc))
    c.tags = overrides.get("tags", ["VIP"])
    c.wechat_nickname = overrides.get("wechat_nickname", None)
    c.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    return c


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ─── Tests ───


@pytest.mark.asyncio
async def test_list_customers_paginated():
    """list_customers 应返回分页格式"""
    session = _mock_session()
    customers = [_make_customer(display_name="张三"), _make_customer(display_name="李四")]

    count_result = MagicMock()
    count_result.scalar.return_value = 2

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = customers
    items_result = MagicMock()
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        count_result,
        items_result,
    ]

    repo = CustomerRepository(session, TENANT_ID)
    result = await repo.list_customers(STORE_ID, page=1, size=20)

    assert result["total"] == 2
    assert result["page"] == 1
    assert len(result["items"]) == 2
    assert result["items"][0]["display_name"] == "张三"


@pytest.mark.asyncio
async def test_get_customer_found():
    """get_customer 找到时返回 dict"""
    session = _mock_session()
    customer = _make_customer(display_name="王五", primary_phone="13900139000")
    cid = str(customer.id)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = customer

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = CustomerRepository(session, TENANT_ID)
    result = await repo.get_customer(cid)

    assert result is not None
    assert result["display_name"] == "王五"
    assert result["primary_phone"] == "13900139000"


@pytest.mark.asyncio
async def test_get_customer_not_found():
    """get_customer 找不到返回 None"""
    session = _mock_session()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        result_mock,
    ]

    repo = CustomerRepository(session, TENANT_ID)
    result = await repo.get_customer(str(uuid.uuid4()))

    assert result is None


@pytest.mark.asyncio
async def test_create_customer():
    """create_customer 应添加到 session 并返回 dict"""
    session = _mock_session()
    session.execute.return_value = None

    repo = CustomerRepository(session, TENANT_ID)
    data = {"phone": "13700137000", "display_name": "赵六", "source": "wechat"}
    result = await repo.create_customer(data)

    assert result["primary_phone"] == "13700137000"
    assert result["display_name"] == "赵六"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_rfm_segments():
    """get_rfm_segments 应返回分层统计"""
    session = _mock_session()

    rows = [("S1", 50), ("S2", 30), ("S3", 80), ("S4", 20), ("S5", 10)]
    query_result = MagicMock()
    query_result.all.return_value = rows

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        query_result,
    ]

    repo = CustomerRepository(session, TENANT_ID)
    result = await repo.get_rfm_segments(STORE_ID)

    assert result["total"] == 190
    assert result["segments"]["S1"] == 50
    assert result["segments"]["S5"] == 10


@pytest.mark.asyncio
async def test_get_at_risk():
    """get_at_risk 应返回流失风险客户列表"""
    session = _mock_session()
    at_risk = [
        _make_customer(display_name="流失A", rfm_recency_days=90, rfm_level="S4"),
        _make_customer(display_name="流失B", rfm_recency_days=75, rfm_level="S5"),
    ]

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = at_risk
    items_result = MagicMock()
    items_result.scalars.return_value = scalars_mock

    session.execute.side_effect = [
        AsyncMock(return_value=None)(),  # set_config
        items_result,
    ]

    repo = CustomerRepository(session, TENANT_ID)
    result = await repo.get_at_risk(STORE_ID, threshold=0.5)

    assert len(result) == 2
    assert result[0]["display_name"] == "流失A"
    assert result[0]["rfm_recency_days"] == 90
