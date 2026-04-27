"""test_billing_rules.py — billing_rules 账单规则引擎单元测试

覆盖范围：
  POST /api/v1/orders/{order_id}/apply-billing-rules

必须覆盖的4个场景：
  1. test_apply_service_fee            — 服务费计算（percentage，8800分 × 0.1 = 880分）
  2. test_apply_min_spend_shortfall    — 最低消费不足（18000 < 20000，差额2000分）
  3. test_apply_min_spend_satisfied    — 最低消费已满足（25000 >= 20000，差额0）
  4. test_exempt_member_tier           — VIP会员等级豁免，服务费不计

DB 层通过 app.dependency_overrides[_get_tenant_db] 注入 AsyncMock，
不依赖真实数据库连接。
"""
from __future__ import annotations

import os
import sys

# 确保 shared/ 和 src/ 在 Python path 中
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
)
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import src.api.billing_rules_routes as billing_module
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from src.api.billing_rules_routes import router as billing_rules_router

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}
STORE_UUID = "00000000-0000-0000-0000-000000000099"
ORDER_UUID = "00000000-0000-0000-0000-000000000088"
RULE_UUID = "00000000-0000-0000-0000-000000000077"

# ─── 测试 App ──────────────────────────────────────────────────────────────────

_app = FastAPI(title="billing-rules-test")
_app.include_router(billing_rules_router)


# ─── Mock DB 工厂 ─────────────────────────────────────────────────────────────


def _make_db() -> AsyncMock:
    """构建一个干净的 mock AsyncSession。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


def _make_rule_row(
    rule_type: str,
    calc_method: str,
    threshold_fen: int = 0,
    service_fee_rate: float = 0.0,
    exempt_member_tiers: list[str] | None = None,
    exempt_agreement_units: list[str] | None = None,
    rule_id: str | None = None,
) -> MagicMock:
    """构造一条 billing_rules 行的 MagicMock。"""
    row = MagicMock()
    row.id = rule_id or RULE_UUID
    row.rule_type = rule_type
    row.calc_method = calc_method
    row.threshold_fen = threshold_fen
    row.service_fee_rate = service_fee_rate
    row.exempt_member_tiers = exempt_member_tiers or []
    row.exempt_agreement_units = exempt_agreement_units or []
    return row


def _db_returns_rows(db: AsyncMock, rows: list[Any]) -> None:
    """配置 mock DB execute 返回指定行列表（.fetchall()）。"""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    db.execute.return_value = result


def _make_db_override(db: AsyncMock):
    """返回一个 async generator，直接 yield mock db，覆盖 _get_tenant_db 依赖。
    必须使用 Request 类型注解，否则 FastAPI 会将参数解析为 query param。
    """
    async def _dep(request: Request):
        yield db

    return _dep


# ─── 测试用例 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_service_fee() -> None:
    """服务费（percentage）：订单8800分，费率0.1，期望服务费880分。"""
    db = _make_db()
    rule = _make_rule_row(
        rule_type="service_fee",
        calc_method="percentage",
        service_fee_rate=0.1,
    )
    _db_returns_rows(db, [rule])

    _app.dependency_overrides[billing_module._get_tenant_db] = _make_db_override(db)

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/orders/{ORDER_UUID}/apply-billing-rules",
            json={
                "store_id": STORE_UUID,
                "order_amount_fen": 8800,
                "guest_count": 1,
            },
            headers=TENANT_HEADERS,
        )

    _app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["service_fee_fen"] == 880
    assert data["data"]["exempted"] is False
    assert len(data["data"]["service_fee_items"]) == 1
    assert data["data"]["service_fee_items"][0]["fee_fen"] == 880


@pytest.mark.asyncio
async def test_apply_min_spend_shortfall() -> None:
    """最低消费不足：订单18000分，最低消费20000分，期望差额2000分。"""
    db = _make_db()
    rule = _make_rule_row(
        rule_type="min_spend",
        calc_method="fixed",
        threshold_fen=20000,
    )
    _db_returns_rows(db, [rule])

    _app.dependency_overrides[billing_module._get_tenant_db] = _make_db_override(db)

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/orders/{ORDER_UUID}/apply-billing-rules",
            json={
                "store_id": STORE_UUID,
                "order_amount_fen": 18000,
                "guest_count": 2,
            },
            headers=TENANT_HEADERS,
        )

    _app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["min_spend_required_fen"] == 20000
    assert data["data"]["min_spend_shortfall_fen"] == 2000
    assert data["data"]["total_extra_fen"] == 2000
    assert data["data"]["exempted"] is False


@pytest.mark.asyncio
async def test_apply_min_spend_satisfied() -> None:
    """最低消费已满足：订单25000分，最低消费20000分，期望差额为0。"""
    db = _make_db()
    rule = _make_rule_row(
        rule_type="min_spend",
        calc_method="fixed",
        threshold_fen=20000,
    )
    _db_returns_rows(db, [rule])

    _app.dependency_overrides[billing_module._get_tenant_db] = _make_db_override(db)

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/orders/{ORDER_UUID}/apply-billing-rules",
            json={
                "store_id": STORE_UUID,
                "order_amount_fen": 25000,
                "guest_count": 2,
            },
            headers=TENANT_HEADERS,
        )

    _app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["min_spend_required_fen"] == 20000
    assert data["data"]["min_spend_shortfall_fen"] == 0
    assert data["data"]["total_extra_fen"] == 0
    assert data["data"]["exempted"] is False


@pytest.mark.asyncio
async def test_exempt_member_tier() -> None:
    """VIP会员等级豁免：服务费规则存在，但VIP会员不收服务费，服务费应为0。"""
    db = _make_db()
    rule = _make_rule_row(
        rule_type="service_fee",
        calc_method="percentage",
        service_fee_rate=0.1,
        exempt_member_tiers=["vip", "platinum"],
    )
    _db_returns_rows(db, [rule])

    _app.dependency_overrides[billing_module._get_tenant_db] = _make_db_override(db)

    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/orders/{ORDER_UUID}/apply-billing-rules",
            json={
                "store_id": STORE_UUID,
                "order_amount_fen": 8800,
                "guest_count": 2,
                "member_tier": "vip",
            },
            headers=TENANT_HEADERS,
        )

    _app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["data"]["exempted"] is True
    assert data["data"]["service_fee_fen"] == 0
    assert data["data"]["total_extra_fen"] == 0
    assert "vip" in data["data"]["exemption_reason"]
