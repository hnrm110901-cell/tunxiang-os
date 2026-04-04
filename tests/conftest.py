"""P0 集成测试 — 公共 fixtures 和工具函数

提供:
  - mock_tenant_id / mock_store_id / mock_customer_id 等常用 UUID
  - mock_db_session — AsyncSession 替身（不连真实数据库）
  - 各服务的 httpx.AsyncClient fixtures（直接调用 FastAPI app）
  - 通用断言工具
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ─── 常量 ──────────────────────────────────────────────────────────────────────

MOCK_TENANT_ID = "a0000000-0000-0000-0000-000000000001"
MOCK_STORE_ID = "s0000000-0000-0000-0000-000000000001"
MOCK_CUSTOMER_ID = "c0000000-0000-0000-0000-000000000001"
MOCK_USER_ID = "u0000000-0000-0000-0000-000000000001"
OTHER_TENANT_ID = "a0000000-0000-0000-0000-000000000099"

DEFAULT_HEADERS: dict[str, str] = {
    "X-Tenant-ID": MOCK_TENANT_ID,
    "Content-Type": "application/json",
}


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_tenant_id() -> str:
    """返回统一的 mock 租户 UUID 字符串。"""
    return MOCK_TENANT_ID


@pytest.fixture
def mock_store_id() -> str:
    """返回统一的 mock 门店 UUID 字符串。"""
    return MOCK_STORE_ID


@pytest.fixture
def mock_customer_id() -> str:
    """返回统一的 mock 顾客 UUID 字符串。"""
    return MOCK_CUSTOMER_ID


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """返回一个 AsyncSession 替身，execute / commit / refresh 均为 async no-op。"""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


# ─── 通用工具函数 ──────────────────────────────────────────────────────────────


def assert_ok(response_json: dict, *, has_data: bool = True) -> dict:
    """断言标准成功响应格式 {"ok": true, "data": ...}。

    Args:
        response_json: API 响应 JSON
        has_data: 是否要求 data 不为 None

    Returns:
        data 字段内容
    """
    assert response_json["ok"] is True, f"expected ok=True, got {response_json}"
    if has_data:
        assert response_json["data"] is not None, "expected data to be non-None"
    return response_json.get("data")


def assert_err(response_json: dict) -> dict:
    """断言标准错误响应格式 {"ok": false, "error": {...}}。

    Returns:
        error 字段内容
    """
    assert response_json["ok"] is False, f"expected ok=False, got {response_json}"
    assert response_json.get("error") is not None, "expected error field"
    return response_json["error"]


def make_order_data(
    *,
    order_id: str | None = None,
    store_id: str | None = None,
    order_type: str = "dine_in",
    table_no: str = "A1",
) -> dict:
    """生成标准订单请求体。"""
    return {
        "store_id": store_id or MOCK_STORE_ID,
        "order_type": order_type,
        "table_no": table_no,
        "customer_id": MOCK_CUSTOMER_ID,
        "waiter_id": MOCK_USER_ID,
    }


def make_item_data(
    *,
    dish_id: str = "dish-001",
    dish_name: str = "宫保鸡丁",
    quantity: int = 1,
    unit_price_fen: int = 3800,
) -> dict:
    """生成标准菜品请求体。"""
    return {
        "dish_id": dish_id,
        "dish_name": dish_name,
        "quantity": quantity,
        "unit_price_fen": unit_price_fen,
    }


def make_payment_data(
    *,
    method: str = "wechat",
    amount_fen: int = 3800,
) -> dict:
    """生成标准支付请求体。"""
    return {
        "method": method,
        "amount_fen": amount_fen,
    }
