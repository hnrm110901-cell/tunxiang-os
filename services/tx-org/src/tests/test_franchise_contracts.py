"""加盟商合同+收费管理 API 测试（DB持久化版，v217）

覆盖端点（franchise_contract_routes.py）：
  ─ 合同管理 ─
  GET  /api/v1/org/franchise/contracts           - 合同列表
  GET  /api/v1/org/franchise/contracts/expiring  - 即将到期合同
  POST /api/v1/org/franchise/contracts           - 创建合同
  GET  /api/v1/org/franchise/contracts/{id}      - 合同详情
  PUT  /api/v1/org/franchise/contracts/{id}      - 更新合同
  POST /api/v1/org/franchise/contracts/{id}/send-alert - 发送到期提醒

  ─ 收费收缴 ─
  POST /api/v1/org/franchise/contracts/{id}/fee-schedule - 设置收费计划
  GET  /api/v1/org/franchise/contracts/{id}/fees         - 合同费用明细
  POST /api/v1/org/franchise/contracts/{id}/collect      - 记录收款
  GET  /api/v1/org/franchise/fee-summary                 - 收缴汇总报表

  ─ 旧收费端点 ─
  GET  /api/v1/org/franchise/fees                - 收费记录列表
  POST /api/v1/org/franchise/fees                - 新增收费记录
  PUT  /api/v1/org/franchise/fees/{id}/pay       - 标记付款
  GET  /api/v1/org/franchise/fees/overdue        - 逾期记录
  GET  /api/v1/org/franchise/fees/stats          - 收费统计

测试用例：
  1. test_contract_create_and_detail       — 创建合同 + 查看详情
  2. test_fee_schedule_and_collect         — 设置收费计划 + 收款
  3. test_fee_summary_report               — 收缴汇总报表
  4. test_collect_overpayment_rejected     — 超额收款拒绝
  5. test_contract_list_and_update         — 合同列表 + 更新
  6. test_fee_create_and_pay               — 旧端点：创建收费 + 付款
"""
import os
import sys
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
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

_CONTRACTS_STORE: dict[str, dict] = {}
_FEES_STORE: dict[str, dict] = {}


def _reset_stores():
    _CONTRACTS_STORE.clear()
    _FEES_STORE.clear()


class DictRow(dict):
    """dict that also supports attribute access, mimicking SQLAlchemy RowMapping."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class FakeResult:
    """模拟 SQLAlchemy 查询结果。"""

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
    """内存中模拟 AsyncSession — 拦截 SQL 并操作 in-memory stores。"""

    def __init__(self):
        self._committed = False

    async def execute(self, stmt, params=None):
        sql = str(stmt.text if hasattr(stmt, 'text') else stmt).strip().lower()
        params = params or {}

        # set_config — ignore
        if "set_config" in sql:
            return FakeResult([])

        # INSERT franchise_contracts
        if "insert into franchise_contracts" in sql:
            row = {
                "id": params.get("id", str(uuid.uuid4())),
                "tenant_id": params.get("tenant_id", TENANT_ID),
                "contract_no": params.get("contract_no", "FC-TEST"),
                "contract_type": params.get("contract_type", "initial"),
                "franchisee_id": params.get("franchisee_id", ""),
                "franchisee_name": params.get("franchisee_name", ""),
                "sign_date": params.get("sign_date"),
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date"),
                "contract_amount_fen": params.get("contract_amount_fen", 0),
                "file_url": params.get("file_url"),
                "status": "active",
                "alert_days_before": params.get("alert_days_before", 30),
                "notes": params.get("notes"),
                "created_by": None,
                "is_deleted": False,
                "created_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:00+00:00",
            }
            end_dt = date.fromisoformat(str(row["end_date"]))
            row["days_to_expire"] = (end_dt - date.today()).days
            _CONTRACTS_STORE[row["id"]] = row
            return FakeResult([])

        # SELECT from franchise_contracts
        if "from franchise_contracts" in sql:
            rows = list(_CONTRACTS_STORE.values())
            rows = [r for r in rows if not r.get("is_deleted")]

            if "id = :contract_id" in sql or "id = :id" in sql:
                cid = params.get("contract_id") or params.get("id")
                rows = [r for r in rows if r["id"] == cid]
            if "franchisee_id = :franchisee_id" in sql and "franchisee_id" in params:
                rows = [r for r in rows if r["franchisee_id"] == params["franchisee_id"]]
            if "status = :status" in sql and "status" in params:
                rows = [r for r in rows if r["status"] == params["status"]]

            if "count(*)" in sql:
                return FakeResult([{"count": len(rows)}])
            return FakeResult(rows)

        # UPDATE franchise_contracts
        if "update franchise_contracts" in sql:
            cid = params.get("id")
            if cid and cid in _CONTRACTS_STORE:
                for k, v in params.items():
                    if k != "id" and k in _CONTRACTS_STORE[cid]:
                        _CONTRACTS_STORE[cid][k] = v
                _CONTRACTS_STORE[cid]["updated_at"] = "2026-04-09T01:00:00+00:00"
            return FakeResult([])

        # INSERT franchise_fee_records
        if "insert into franchise_fee_records" in sql:
            row = {
                "id": params.get("id", str(uuid.uuid4())),
                "tenant_id": params.get("tenant_id", TENANT_ID),
                "contract_id": params.get("contract_id"),
                "franchisee_id": params.get("franchisee_id", ""),
                "franchisee_name": params.get("franchisee_name", ""),
                "fee_type": params.get("fee_type", ""),
                "period_start": params.get("period_start"),
                "period_end": params.get("period_end"),
                "amount_fen": params.get("amount_fen", 0),
                "paid_fen": 0,
                "due_date": params.get("due_date"),
                "status": "unpaid",
                "receipt_no": None,
                "receipt_url": None,
                "notes": params.get("notes"),
                "is_deleted": False,
                "created_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:00+00:00",
            }
            _FEES_STORE[row["id"]] = row
            return FakeResult([])

        # SELECT from franchise_fee_records
        if "from franchise_fee_records" in sql:
            rows = list(_FEES_STORE.values())
            rows = [r for r in rows if not r.get("is_deleted")]

            if "id = :fee_id" in sql or "id = :id" in sql:
                fid = params.get("fee_id") or params.get("id")
                rows = [r for r in rows if r["id"] == fid]
            if "contract_id = :contract_id" in sql and "contract_id" in params:
                rows = [r for r in rows if r.get("contract_id") == params["contract_id"]]
            if "status = :status" in sql and "status" in params:
                rows = [r for r in rows if r["status"] == params["status"]]
            # Only filter by overdue if it's a WHERE clause, not a CASE WHEN
            if "where" in sql and "status = 'overdue'" in sql and "case when" not in sql:
                rows = [r for r in rows if r["status"] == "overdue"]
            if "fee_type = :fee_type" in sql and "fee_type" in params:
                rows = [r for r in rows if r["fee_type"] == params["fee_type"]]
            if "franchisee_id = :franchisee_id" in sql and "franchisee_id" in params:
                rows = [r for r in rows if r["franchisee_id"] == params["franchisee_id"]]

            # SUM aggregations (check before count(*) since some queries have both)
            if "sum(amount_fen)" in sql and "group by" not in sql:
                total_a = sum(r["amount_fen"] for r in rows)
                total_p = sum(r["paid_fen"] for r in rows)
                total_o = sum(
                    r["amount_fen"] - r["paid_fen"]
                    for r in rows if r["status"] == "overdue"
                )
                return FakeResult([{
                    "total_amount_fen": total_a,
                    "total_paid_fen": total_p,
                    "total_overdue_fen": total_o,
                    "total_records": len(rows),
                }])

            if "group by fee_type" in sql:
                by_type: dict[str, dict] = {}
                for r in rows:
                    ft = r["fee_type"]
                    if ft not in by_type:
                        by_type[ft] = {"fee_type": ft, "amount_fen": 0, "paid_fen": 0,
                                       "overdue_fen": 0, "record_count": 0}
                    by_type[ft]["amount_fen"] += r["amount_fen"]
                    by_type[ft]["paid_fen"] += r["paid_fen"]
                    by_type[ft]["record_count"] += 1
                    if r["status"] == "overdue":
                        by_type[ft]["overdue_fen"] += r["amount_fen"] - r["paid_fen"]
                return FakeResult(list(by_type.values()))

            if "group by franchisee_id" in sql:
                by_f: dict[str, dict] = {}
                for r in rows:
                    fid = r["franchisee_id"]
                    if fid not in by_f:
                        by_f[fid] = {"franchisee_id": fid,
                                     "franchisee_name": r["franchisee_name"],
                                     "amount_fen": 0, "paid_fen": 0,
                                     "overdue_fen": 0, "record_count": 0}
                    by_f[fid]["amount_fen"] += r["amount_fen"]
                    by_f[fid]["paid_fen"] += r["paid_fen"]
                    by_f[fid]["record_count"] += 1
                    if r["status"] == "overdue":
                        by_f[fid]["overdue_fen"] += r["amount_fen"] - r["paid_fen"]
                return FakeResult(list(by_f.values()))

            if "group by status" in sql:
                by_s: dict[str, dict] = {}
                for r in rows:
                    s = r["status"]
                    if s not in by_s:
                        by_s[s] = {"status": s, "cnt": 0, "amount_fen": 0}
                    by_s[s]["cnt"] += 1
                    by_s[s]["amount_fen"] += r["amount_fen"]
                return FakeResult(list(by_s.values()))

            # Plain COUNT (no SUM)
            if "count(*)" in sql:
                return FakeResult([{"count": len(rows)}])

            return FakeResult(rows)

        # UPDATE franchise_fee_records
        if "update franchise_fee_records" in sql:
            fid = params.get("fee_id")
            if fid and fid in _FEES_STORE:
                if "paid_fen" in params:
                    _FEES_STORE[fid]["paid_fen"] = params["paid_fen"]
                if "status" in params:
                    _FEES_STORE[fid]["status"] = params["status"]
                if "receipt_no" in params:
                    _FEES_STORE[fid]["receipt_no"] = params["receipt_no"]
                if "receipt_url" in params:
                    _FEES_STORE[fid]["receipt_url"] = params["receipt_url"]
                if "notes" in params:
                    _FEES_STORE[fid]["notes"] = params["notes"]
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
    from api.franchise_contract_routes import router as franchise_contract_router

app = FastAPI()
app.include_router(franchise_contract_router)
app.dependency_overrides = {}

# Override the dependency
from shared.ontology.src.database import get_db_with_tenant
app.dependency_overrides[get_db_with_tenant] = _fake_get_db_with_tenant


# ─── 测试用例 1: 创建合同 + 查看详情 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_contract_create_and_detail():
    """创建合同并查看详情，验证字段正确。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建合同
        end_date = (date.today() + timedelta(days=365)).isoformat()
        resp = await client.post(
            "/api/v1/org/franchise/contracts",
            json={
                "franchisee_id": "fr-test-001",
                "franchisee_name": "测试加盟店A",
                "contract_type": "initial",
                "sign_date": date.today().isoformat(),
                "start_date": date.today().isoformat(),
                "end_date": end_date,
                "contract_amount_fen": 30000000,
                "alert_days_before": 30,
                "notes": "测试合同",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 200, f"创建合同失败: {resp.text}"
        body = resp.json()
        assert body["ok"] is True
        contract_id = body["data"]["id"]
        assert body["data"]["contract_no"].startswith("FC-")
        assert body["data"]["franchisee_name"] == "测试加盟店A"

        # 查看详情
        detail_resp = await client.get(
            f"/api/v1/org/franchise/contracts/{contract_id}",
            headers=HEADERS,
        )
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["ok"] is True
        assert detail["data"]["id"] == contract_id
        assert "days_to_expire" in detail["data"]


# ─── 测试用例 2: 设置收费计划 + 收款 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_fee_schedule_and_collect():
    """为合同设置收费计划，然后通过 collect 端点收款。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建合同
        end_date = (date.today() + timedelta(days=365)).isoformat()
        create_resp = await client.post(
            "/api/v1/org/franchise/contracts",
            json={
                "franchisee_id": "fr-test-002",
                "franchisee_name": "测试加盟店B",
                "contract_type": "initial",
                "sign_date": date.today().isoformat(),
                "start_date": date.today().isoformat(),
                "end_date": end_date,
                "contract_amount_fen": 20000000,
            },
            headers=HEADERS,
        )
        contract_id = create_resp.json()["data"]["id"]

        # 设置收费计划（加盟费 + 管理费）
        schedule_resp = await client.post(
            f"/api/v1/org/franchise/contracts/{contract_id}/fee-schedule",
            json={
                "items": [
                    {
                        "fee_type": "joining_fee",
                        "amount_fen": 10000000,
                        "due_date": (date.today() + timedelta(days=15)).isoformat(),
                        "notes": "加盟费一次性",
                    },
                    {
                        "fee_type": "management_fee",
                        "amount_fen": 500000,
                        "period_start": "2026-04-01",
                        "period_end": "2026-06-30",
                        "due_date": "2026-06-30",
                        "notes": "Q2管理费",
                    },
                ],
            },
            headers=HEADERS,
        )
        assert schedule_resp.status_code == 200, f"设置收费计划失败: {schedule_resp.text}"
        schedule_body = schedule_resp.json()
        assert schedule_body["ok"] is True
        assert schedule_body["data"]["created_count"] == 2
        fee_ids = schedule_body["data"]["fee_ids"]
        assert len(fee_ids) == 2

        # 查看合同下的费用明细
        fees_resp = await client.get(
            f"/api/v1/org/franchise/contracts/{contract_id}/fees",
            headers=HEADERS,
        )
        assert fees_resp.status_code == 200
        fees_body = fees_resp.json()
        assert fees_body["data"]["total"] == 2
        assert fees_body["data"]["summary"]["total_amount_fen"] == 10500000

        # 收款（对第一笔加盟费收款）
        collect_resp = await client.post(
            f"/api/v1/org/franchise/contracts/{contract_id}/collect",
            json={
                "fee_id": fee_ids[0],
                "paid_fen": 10000000,
                "receipt_no": "RCP-TEST-001",
            },
            headers=HEADERS,
        )
        assert collect_resp.status_code == 200, f"收款失败: {collect_resp.text}"
        collect_body = collect_resp.json()
        assert collect_body["ok"] is True
        assert collect_body["data"]["status"] == "paid"
        assert collect_body["data"]["paid_fen"] == 10000000


# ─── 测试用例 3: 收缴汇总报表 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fee_summary_report():
    """创建多笔收费记录后，验证汇总报表数据正确。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建两笔收费记录
        for i, (ftype, amount) in enumerate([
            ("joining_fee", 10000000),
            ("management_fee", 500000),
        ]):
            await client.post(
                "/api/v1/org/franchise/fees",
                json={
                    "franchisee_id": "fr-summary-001",
                    "franchisee_name": "汇总测试店",
                    "fee_type": ftype,
                    "amount_fen": amount,
                    "due_date": "2026-04-30",
                },
                headers=HEADERS,
            )

        # 查询汇总报表
        summary_resp = await client.get(
            "/api/v1/org/franchise/fee-summary",
            headers=HEADERS,
        )
        assert summary_resp.status_code == 200, f"汇总报表失败: {summary_resp.text}"
        body = summary_resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_amount_fen"] == 10500000
        assert data["total_paid_fen"] == 0
        assert data["total_unpaid_fen"] == 10500000
        assert len(data["by_type"]) == 2
        assert len(data["by_franchisee"]) == 1


# ─── 测试用例 4: 超额收款拒绝 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_overpayment_rejected():
    """收款金额超出应收时应被拒绝。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建合同
        end_date = (date.today() + timedelta(days=365)).isoformat()
        create_resp = await client.post(
            "/api/v1/org/franchise/contracts",
            json={
                "franchisee_id": "fr-test-overpay",
                "contract_type": "initial",
                "sign_date": date.today().isoformat(),
                "start_date": date.today().isoformat(),
                "end_date": end_date,
                "contract_amount_fen": 100000,
            },
            headers=HEADERS,
        )
        contract_id = create_resp.json()["data"]["id"]

        # 创建收费计划
        schedule_resp = await client.post(
            f"/api/v1/org/franchise/contracts/{contract_id}/fee-schedule",
            json={
                "items": [
                    {"fee_type": "joining_fee", "amount_fen": 100000},
                ],
            },
            headers=HEADERS,
        )
        fee_id = schedule_resp.json()["data"]["fee_ids"][0]

        # 超额收款应被拒绝
        collect_resp = await client.post(
            f"/api/v1/org/franchise/contracts/{contract_id}/collect",
            json={
                "fee_id": fee_id,
                "paid_fen": 200000,
            },
            headers=HEADERS,
        )
        assert collect_resp.status_code == 422, f"超额收款应返回422，实际: {collect_resp.status_code}"
        detail = collect_resp.json().get("detail", collect_resp.json())
        assert detail.get("ok") is False
        assert detail.get("error", {}).get("code") == "OVERPAYMENT"


# ─── 测试用例 5: 合同列表 + 更新 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contract_list_and_update():
    """创建多个合同后验证列表和更新功能。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建两个合同
        for name in ["测试店X", "测试店Y"]:
            await client.post(
                "/api/v1/org/franchise/contracts",
                json={
                    "franchisee_id": f"fr-{name}",
                    "franchisee_name": name,
                    "contract_type": "initial",
                    "sign_date": "2026-04-01",
                    "start_date": "2026-04-01",
                    "end_date": "2029-03-31",
                    "contract_amount_fen": 15000000,
                },
                headers=HEADERS,
            )

        # 列表
        list_resp = await client.get(
            "/api/v1/org/franchise/contracts",
            headers=HEADERS,
        )
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert list_body["data"]["total"] == 2

        # 更新第一个
        cid = list_body["data"]["items"][0]["id"]
        update_resp = await client.put(
            f"/api/v1/org/franchise/contracts/{cid}",
            json={"notes": "已更新备注"},
            headers=HEADERS,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["notes"] == "已更新备注"


# ─── 测试用例 6: 旧端点：创建收费 + 付款 ────────────────────────────────────

@pytest.mark.asyncio
async def test_fee_create_and_pay():
    """通过旧端点创建收费记录并标记付款。"""
    _reset_stores()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 创建收费记录
        create_resp = await client.post(
            "/api/v1/org/franchise/fees",
            json={
                "franchisee_id": "fr-pay-test",
                "franchisee_name": "付款测试店",
                "fee_type": "royalty",
                "amount_fen": 200000,
                "due_date": "2026-05-01",
            },
            headers=HEADERS,
        )
        assert create_resp.status_code == 200
        fee_id = create_resp.json()["data"]["id"]
        assert create_resp.json()["data"]["status"] == "unpaid"
        assert create_resp.json()["data"]["paid_fen"] == 0

        # 部分付款
        partial_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 100000, "receipt_no": "RCP-001"},
            headers=HEADERS,
        )
        assert partial_resp.status_code == 200
        assert partial_resp.json()["data"]["status"] == "partial"
        assert partial_resp.json()["data"]["paid_fen"] == 100000

        # 全额付款
        full_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 100000, "receipt_no": "RCP-002"},
            headers=HEADERS,
        )
        assert full_resp.status_code == 200
        assert full_resp.json()["data"]["status"] == "paid"
        assert full_resp.json()["data"]["paid_fen"] == 200000

        # 超额拒绝
        over_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 1},
            headers=HEADERS,
        )
        assert over_resp.status_code == 422
