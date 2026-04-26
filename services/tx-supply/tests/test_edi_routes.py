"""供应商EDI对接 API 测试（v217）

覆盖端点（edi_routes.py）：
  POST /api/v1/supply/edi/order-push       — 电子采购订单推送
  POST /api/v1/supply/edi/delivery-confirm  — 供应商确认发货
  POST /api/v1/supply/edi/receive-confirm   — 门店确认收货
  GET  /api/v1/supply/edi/order-status      — EDI订单状态追踪

测试用例：
  1. test_edi_full_lifecycle      — 完整生命周期：推送→发货→收货
  2. test_edi_order_status_query  — 状态追踪查询
  3. test_edi_delivery_invalid_status — 非法状态发货拒绝
  4. test_edi_receive_requires_shipped — 收货必须在已发货后
"""
import os
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

TENANT_ID = "00000000-0000-0000-0000-000000000001"
HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "Content-Type": "application/json",
}

# ─── 内存 DB 模拟 ─────────────────────────────────────────────────────────────

_EDI_STORE: dict[str, dict] = {}


def _reset_stores():
    _EDI_STORE.clear()


class DictRow(dict):
    """dict that also supports attribute access, mimicking SQLAlchemy RowMapping."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = [DictRow(r) for r in rows]

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        if self._rows:
            vals = list(self._rows[0].values())
            return vals[0] if vals else 0
        return 0


class FakeAsyncSession:
    def __init__(self):
        self._committed = False

    async def execute(self, stmt, params=None):
        sql = str(stmt.text if hasattr(stmt, 'text') else stmt).strip().lower()
        params = params or {}

        if "set_config" in sql:
            return FakeResult([])

        # INSERT edi_orders
        if "insert into edi_orders" in sql:
            row = {
                "id": params.get("id", str(uuid.uuid4())),
                "tenant_id": params.get("tenant_id", TENANT_ID),
                "edi_no": params.get("edi_no", "EDI-TEST"),
                "po_id": params.get("po_id"),
                "supplier_id": params.get("supplier_id", ""),
                "supplier_name": params.get("supplier_name", ""),
                "store_id": params.get("store_id", ""),
                "store_name": params.get("store_name", ""),
                "items": params.get("items", "[]"),
                "total_amount_fen": params.get("total_amount_fen", 0),
                "status": "pushed",
                "pushed_at": "2026-04-09T00:00:00+00:00",
                "supplier_confirmed_at": None,
                "shipped_at": None,
                "received_at": None,
                "tracking_no": None,
                "delivery_notes": None,
                "receive_notes": None,
                "notes": params.get("notes"),
                "is_deleted": False,
                "created_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:00+00:00",
            }
            _EDI_STORE[row["id"]] = row
            return FakeResult([])

        # SELECT from edi_orders
        if "from edi_orders" in sql:
            rows = [r for r in _EDI_STORE.values() if not r.get("is_deleted")]

            if "id = :edi_order_id" in sql or "id = :id" in sql:
                eid = params.get("edi_order_id") or params.get("id")
                rows = [r for r in rows if r["id"] == eid]
            if "supplier_id = :supplier_id" in sql and "supplier_id" in params:
                rows = [r for r in rows if r["supplier_id"] == params["supplier_id"]]
            if "store_id = :store_id" in sql and "store_id" in params:
                rows = [r for r in rows if r["store_id"] == params["store_id"]]
            if "edi_no = :edi_no" in sql and "edi_no" in params:
                rows = [r for r in rows if r["edi_no"] == params["edi_no"]]

            # status filter (parameterized)
            if "status = :status" in sql and "status" in params:
                rows = [r for r in rows if r["status"] == params["status"]]

            if "count(*)" in sql:
                return FakeResult([{"count": len(rows)}])

            if "group by status" in sql:
                by_s: dict[str, dict] = {}
                for r in rows:
                    s = r["status"]
                    if s not in by_s:
                        by_s[s] = {"status": s, "cnt": 0, "amount_fen": 0}
                    by_s[s]["cnt"] += 1
                    by_s[s]["amount_fen"] += r.get("total_amount_fen", 0)
                return FakeResult(list(by_s.values()))

            return FakeResult(rows)

        # UPDATE edi_orders
        if "update edi_orders" in sql:
            eid = params.get("edi_order_id")
            if eid and eid in _EDI_STORE:
                if "status = 'shipped'" in sql:
                    _EDI_STORE[eid]["status"] = "shipped"
                    _EDI_STORE[eid]["shipped_at"] = "2026-04-09T12:00:00+00:00"
                if "status = 'received'" in sql:
                    _EDI_STORE[eid]["status"] = "received"
                    _EDI_STORE[eid]["received_at"] = "2026-04-10T08:00:00+00:00"
                if "tracking_no" in params:
                    _EDI_STORE[eid]["tracking_no"] = params["tracking_no"]
                if "delivery_notes" in params:
                    _EDI_STORE[eid]["delivery_notes"] = params["delivery_notes"]
                if "receive_notes" in params:
                    _EDI_STORE[eid]["receive_notes"] = params["receive_notes"]
            return FakeResult([])

        return FakeResult([])

    async def commit(self):
        self._committed = True

    async def rollback(self):
        pass


async def _fake_get_db_with_tenant(tenant_id: str = TENANT_ID):
    yield FakeAsyncSession()


# ─── 测试 App ─────────────────────────────────────────────────────────────────

with patch("shared.ontology.src.database.get_db_with_tenant", _fake_get_db_with_tenant):
    from api.edi_routes import router as edi_router

app = FastAPI()
app.include_router(edi_router)

from shared.ontology.src.database import get_db_with_tenant

app.dependency_overrides[get_db_with_tenant] = _fake_get_db_with_tenant


# ─── 测试用例 1: 完整生命周期 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edi_full_lifecycle():
    """EDI完整流程：推送订单 → 供应商确认发货 → 门店确认收货。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Step 1: 推送订单
        push_resp = await client.post(
            "/api/v1/supply/edi/order-push",
            json={
                "supplier_id": "sup-001",
                "supplier_name": "张记海鲜",
                "store_id": "store-001",
                "store_name": "长沙五一广场店",
                "items": [
                    {"ingredient_id": "ing-001", "name": "鲈鱼", "qty": 50,
                     "unit": "kg", "unit_price_fen": 3500},
                    {"ingredient_id": "ing-002", "name": "基围虾", "qty": 30,
                     "unit": "kg", "unit_price_fen": 6000},
                ],
                "notes": "EDI测试订单",
            },
            headers=HEADERS,
        )
        assert push_resp.status_code == 200, f"推送失败: {push_resp.text}"
        push_body = push_resp.json()
        assert push_body["ok"] is True
        edi_id = push_body["data"]["id"]
        assert push_body["data"]["edi_no"].startswith("EDI-")
        assert push_body["data"]["status"] == "pushed"
        assert push_body["data"]["total_amount_fen"] == 50 * 3500 + 30 * 6000

        # Step 2: 供应商确认发货
        deliver_resp = await client.post(
            "/api/v1/supply/edi/delivery-confirm",
            json={
                "edi_order_id": edi_id,
                "tracking_no": "SF1234567890",
                "delivery_notes": "冷链运输",
            },
            headers=HEADERS,
        )
        assert deliver_resp.status_code == 200, f"确认发货失败: {deliver_resp.text}"
        deliver_body = deliver_resp.json()
        assert deliver_body["ok"] is True
        assert deliver_body["data"]["status"] == "shipped"
        assert deliver_body["data"]["tracking_no"] == "SF1234567890"

        # Step 3: 门店确认收货
        receive_resp = await client.post(
            "/api/v1/supply/edi/receive-confirm",
            json={
                "edi_order_id": edi_id,
                "receive_notes": "品质合格，已入库",
            },
            headers=HEADERS,
        )
        assert receive_resp.status_code == 200, f"确认收货失败: {receive_resp.text}"
        receive_body = receive_resp.json()
        assert receive_body["ok"] is True
        assert receive_body["data"]["status"] == "received"


# ─── 测试用例 2: 状态追踪查询 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edi_order_status_query():
    """推送多个订单后查询状态追踪。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 推送两个订单
        for i in range(2):
            await client.post(
                "/api/v1/supply/edi/order-push",
                json={
                    "supplier_id": "sup-001",
                    "store_id": f"store-{i + 1:03d}",
                    "items": [
                        {"ingredient_id": f"ing-{i}", "name": f"食材{i}",
                         "qty": 10, "unit": "kg", "unit_price_fen": 1000},
                    ],
                },
                headers=HEADERS,
            )

        # 查询全部
        status_resp = await client.get(
            "/api/v1/supply/edi/order-status",
            headers=HEADERS,
        )
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 2
        assert len(body["data"]["items"]) == 2
        assert "status_summary" in body["data"]

        # 按供应商过滤
        filter_resp = await client.get(
            "/api/v1/supply/edi/order-status",
            params={"supplier_id": "sup-001"},
            headers=HEADERS,
        )
        assert filter_resp.status_code == 200
        assert filter_resp.json()["data"]["total"] == 2

        # 按门店过滤
        store_resp = await client.get(
            "/api/v1/supply/edi/order-status",
            params={"store_id": "store-001"},
            headers=HEADERS,
        )
        assert store_resp.status_code == 200
        assert store_resp.json()["data"]["total"] == 1


# ─── 测试用例 3: 非法状态发货拒绝 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edi_delivery_invalid_status():
    """已收货的订单不可再次确认发货。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 推送 + 发货 + 收货
        push_resp = await client.post(
            "/api/v1/supply/edi/order-push",
            json={
                "supplier_id": "sup-001",
                "store_id": "store-001",
                "items": [
                    {"ingredient_id": "ing-001", "name": "鲈鱼", "qty": 10,
                     "unit": "kg", "unit_price_fen": 3500},
                ],
            },
            headers=HEADERS,
        )
        edi_id = push_resp.json()["data"]["id"]

        # 发货
        await client.post(
            "/api/v1/supply/edi/delivery-confirm",
            json={"edi_order_id": edi_id},
            headers=HEADERS,
        )
        # 收货
        await client.post(
            "/api/v1/supply/edi/receive-confirm",
            json={"edi_order_id": edi_id},
            headers=HEADERS,
        )

        # 再次尝试发货 — 应被拒绝
        dup_resp = await client.post(
            "/api/v1/supply/edi/delivery-confirm",
            json={"edi_order_id": edi_id},
            headers=HEADERS,
        )
        assert dup_resp.status_code == 400, f"已收货订单不应允许再发货，实际: {dup_resp.status_code}"
        detail = dup_resp.json().get("detail", dup_resp.json())
        assert detail.get("error", {}).get("code") == "INVALID_STATUS"


# ─── 测试用例 4: 收货必须在已发货后 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_edi_receive_requires_shipped():
    """未发货的订单不可确认收货。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 推送订单（状态: pushed）
        push_resp = await client.post(
            "/api/v1/supply/edi/order-push",
            json={
                "supplier_id": "sup-001",
                "store_id": "store-001",
                "items": [
                    {"ingredient_id": "ing-001", "name": "鲈鱼", "qty": 10,
                     "unit": "kg", "unit_price_fen": 3500},
                ],
            },
            headers=HEADERS,
        )
        edi_id = push_resp.json()["data"]["id"]

        # 直接尝试收货 — 应被拒绝
        receive_resp = await client.post(
            "/api/v1/supply/edi/receive-confirm",
            json={"edi_order_id": edi_id},
            headers=HEADERS,
        )
        assert receive_resp.status_code == 400, f"未发货不应允许收货，实际: {receive_resp.status_code}"
        detail = receive_resp.json().get("detail", receive_resp.json())
        assert detail.get("error", {}).get("code") == "INVALID_STATUS"
