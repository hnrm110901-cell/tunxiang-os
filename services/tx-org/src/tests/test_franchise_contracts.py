"""加盟商合同+收费管理 API 测试

覆盖端点（franchise_contract_routes.py）：
  GET  /api/v1/org/franchise/contracts           - 合同列表
  GET  /api/v1/org/franchise/contracts/expiring  - 即将到期合同
  POST /api/v1/org/franchise/contracts           - 创建合同
  GET  /api/v1/org/franchise/contracts/{id}      - 合同详情
  PUT  /api/v1/org/franchise/contracts/{id}      - 更新合同
  POST /api/v1/org/franchise/contracts/{id}/send-alert - 发送到期提醒
  GET  /api/v1/org/franchise/fees                - 收费记录列表
  POST /api/v1/org/franchise/fees                - 新增收费记录
  PUT  /api/v1/org/franchise/fees/{id}/pay       - 标记付款
  GET  /api/v1/org/franchise/fees/overdue        - 逾期记录
  GET  /api/v1/org/franchise/fees/stats          - 收费统计

测试用例：
  1. test_get_contracts_list
  2. test_expiring_contracts_alert
  3. test_fee_payment_flow
  4. test_fee_overdue_stats
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.franchise_contract_routes import router as franchise_contract_router

# ─── 测试 App ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(franchise_contract_router)

TENANT_ID = "test-tenant-00000000-0000-0000-0000-000000000001"
HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "Content-Type": "application/json",
}


# ─── 测试用例 1: 获取合同列表 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_contracts_list():
    """合同列表返回正确，包含 days_to_expire 字段，mock 数据至少有 3 条。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/org/franchise/contracts",
            headers=HEADERS,
        )

    assert resp.status_code == 200, f"期望200，实际：{resp.status_code}"
    body = resp.json()
    assert body["ok"] is True, "响应 ok 字段应为 True"

    data = body["data"]
    assert "items" in data, "响应 data 中缺少 items 字段"
    assert "total" in data, "响应 data 中缺少 total 字段"
    assert data["total"] >= 3, f"mock 数据应至少有3条合同，实际：{data['total']}"

    for contract in data["items"]:
        assert "days_to_expire" in contract, (
            f"合同 {contract.get('id')} 缺少 days_to_expire 字段"
        )
        assert isinstance(contract["days_to_expire"], int), (
            f"days_to_expire 应为 int，实际：{type(contract['days_to_expire'])}"
        )

    # 验证必要字段存在
    first = data["items"][0]
    required_fields = [
        "id", "contract_no", "contract_type", "franchisee_id",
        "sign_date", "end_date", "status",
    ]
    for field in required_fields:
        assert field in first, f"合同数据缺少字段：{field}"


# ─── 测试用例 2: 即将到期合同预警 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expiring_contracts_alert():
    """即将到期查询：武汉光谷店合同29天后到期，应出现在30天内到期列表。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/org/franchise/contracts/expiring",
            params={"days": 30},
            headers=HEADERS,
        )

    assert resp.status_code == 200, f"期望200，实际：{resp.status_code}"
    body = resp.json()
    assert body["ok"] is True

    items = body["data"]["items"]
    assert len(items) >= 1, "30天内应至少有1份即将到期合同"

    # 验证武汉光谷店合同（days_to_expire=29）在列表中
    wuhan_contracts = [
        c for c in items
        if c.get("franchisee_name") == "武汉光谷店"
        or c.get("franchisee_id") == "fr-002"
    ]
    assert len(wuhan_contracts) >= 1, (
        "武汉光谷店合同（29天到期）应出现在expiring列表中"
    )

    wuhan = wuhan_contracts[0]
    assert wuhan["days_to_expire"] <= 30, (
        f"武汉光谷店合同 days_to_expire={wuhan['days_to_expire']}，应 <= 30"
    )
    assert wuhan.get("warning") is True, "即将到期合同应有 warning=True 标记"

    # 验证列表按剩余天数升序排列（第一个应最先到期）
    if len(items) > 1:
        for i in range(len(items) - 1):
            assert items[i]["days_to_expire"] <= items[i + 1]["days_to_expire"], (
                "expiring 列表应按 days_to_expire 升序排列"
            )

    # 长沙五一广场店（695天）和深圳南山店（786天）不应出现在30天内到期列表
    non_expiring_ids = {"fc-001", "fc-003"}
    expiring_ids = {c["id"] for c in items}
    overlap = non_expiring_ids & expiring_ids
    assert not overlap, (
        f"不应出现在30天到期列表中的合同ID：{overlap}"
    )


# ─── 测试用例 3: 收费付款完整流程 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fee_payment_flow():
    """收费付款流程：创建收费记录 → 标记付款 → 状态变 paid。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Step 1: 创建收费记录
        create_resp = await client.post(
            "/api/v1/org/franchise/fees",
            json={
                "franchisee_id": "fr-001",
                "franchisee_name": "长沙五一广场店",
                "contract_id": "fc-001",
                "fee_type": "royalty",
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "amount_fen": 200000,
                "due_date": "2026-04-15",
                "notes": "测试收费记录",
            },
            headers=HEADERS,
        )
        assert create_resp.status_code == 200, (
            f"创建收费记录失败：{create_resp.status_code}"
        )
        create_body = create_resp.json()
        assert create_body["ok"] is True
        fee_id = create_body["data"]["id"]
        assert create_body["data"]["status"] == "unpaid", (
            "新建收费记录初始状态应为 unpaid"
        )
        assert create_body["data"]["paid_fen"] == 0, (
            "新建收费记录 paid_fen 应为 0"
        )

        # Step 2: 部分付款（先付一半）
        partial_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 100000, "receipt_no": "RCP-TEST-0001"},
            headers=HEADERS,
        )
        assert partial_resp.status_code == 200, (
            f"标记部分付款失败：{partial_resp.status_code}"
        )
        partial_body = partial_resp.json()
        assert partial_body["ok"] is True
        assert partial_body["data"]["status"] == "partial", (
            f"部分付款后状态应为 partial，实际：{partial_body['data']['status']}"
        )
        assert partial_body["data"]["paid_fen"] == 100000, (
            f"paid_fen 应为 100000，实际：{partial_body['data']['paid_fen']}"
        )
        assert partial_body["data"]["receipt_no"] == "RCP-TEST-0001"

        # Step 3: 全额付款（付剩余一半）
        full_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 100000, "receipt_no": "RCP-TEST-0002"},
            headers=HEADERS,
        )
        assert full_resp.status_code == 200, (
            f"标记全额付款失败：{full_resp.status_code}"
        )
        full_body = full_resp.json()
        assert full_body["ok"] is True
        assert full_body["data"]["status"] == "paid", (
            f"全额付款后状态应为 paid，实际：{full_body['data']['status']}"
        )
        assert full_body["data"]["paid_fen"] == 200000, (
            f"paid_fen 应为 200000，实际：{full_body['data']['paid_fen']}"
        )

        # Step 4: 验证超额付款被拒绝
        # 注：FastAPI HTTPException 将 detail 包在 {"detail": ...} 中
        overpay_resp = await client.put(
            f"/api/v1/org/franchise/fees/{fee_id}/pay",
            json={"paid_fen": 1},
            headers=HEADERS,
        )
        assert overpay_resp.status_code == 422, (
            f"超额付款应返回422，实际：{overpay_resp.status_code}"
        )
        overpay_body = overpay_resp.json()
        # FastAPI 将 HTTPException.detail 放在 {"detail": ...} 键下
        detail = overpay_body.get("detail", overpay_body)
        assert detail.get("ok") is False, f"超额付款响应 ok 应为 False，实际：{detail}"
        assert detail.get("error", {}).get("code") == "OVERPAYMENT", (
            f"超额付款错误码应为 OVERPAYMENT，实际：{detail.get('error')}"
        )


# ─── 测试用例 4: 逾期统计 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fee_overdue_stats():
    """逾期统计：过了 due_date 未付的记录应出现在 overdue 列表，并计入 stats 逾期金额。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 查询逾期列表
        overdue_resp = await client.get(
            "/api/v1/org/franchise/fees/overdue",
            headers=HEADERS,
        )
        assert overdue_resp.status_code == 200, (
            f"逾期查询失败：{overdue_resp.status_code}"
        )
        overdue_body = overdue_resp.json()
        assert overdue_body["ok"] is True

        overdue_data = overdue_body["data"]
        assert "items" in overdue_data
        assert "total" in overdue_data
        assert "total_overdue_fen" in overdue_data

        # mock数据中 fee-003（武汉光谷店管理费，due_date=2026-03-31）状态为 overdue
        assert overdue_data["total"] >= 1, (
            "应至少有1条逾期记录（fee-003 武汉光谷店管理费）"
        )

        overdue_ids = {r["id"] for r in overdue_data["items"]}
        assert "fee-003" in overdue_ids, (
            "fee-003（武汉光谷店管理费，due_date=2026-03-31）应在逾期列表中"
        )

        # 验证所有逾期记录 status == overdue
        for r in overdue_data["items"]:
            assert r["status"] == "overdue", (
                f"逾期列表中出现非overdue记录：{r['id']} status={r['status']}"
            )

        assert overdue_data["total_overdue_fen"] > 0, (
            "total_overdue_fen 应 > 0"
        )

        # 查询统计数据，验证逾期金额一致
        stats_resp = await client.get(
            "/api/v1/org/franchise/fees/stats",
            headers=HEADERS,
        )
        assert stats_resp.status_code == 200, (
            f"收费统计查询失败：{stats_resp.status_code}"
        )
        stats_body = stats_resp.json()
        assert stats_body["ok"] is True

        stats = stats_body["data"]
        assert stats["total_overdue_fen"] == overdue_data["total_overdue_fen"], (
            f"stats 中 total_overdue_fen={stats['total_overdue_fen']} "
            f"与 overdue 列表汇总 {overdue_data['total_overdue_fen']} 不一致"
        )

        # 验证 total_amount_fen = total_paid_fen + total_unpaid_fen
        assert stats["total_amount_fen"] == stats["total_paid_fen"] + stats["total_unpaid_fen"], (
            "total_amount_fen 应等于 total_paid_fen + total_unpaid_fen"
        )

        # 验证 by_type 结构
        assert "by_type" in stats
        assert isinstance(stats["by_type"], list)
        for entry in stats["by_type"]:
            assert "fee_type" in entry
            assert "amount_fen" in entry
            assert "paid_fen" in entry
            assert "overdue_fen" in entry
