"""
抖音团购核销路由测试 — Y-I2
验证：
  1. test_verify_voucher_success     — 正常核销：success=True，order_id 非空
  2. test_verify_already_used        — 已核销券（DY_USED_ 前缀）：success=False，error 含"已核销"
  3. test_reconciliation_report      — 对账报表：返回必要字段，discrepancy_amount_fen 为整数
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../.."))

from services.tx_trade.src.api.douyin_voucher_routes import router, _RETRY_QUEUE, _AUTHORIZED_STORES

# ──────────────────────────────────────────────────────────────────────────────
# 测试 App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

TENANT_HEADER = {"X-Tenant-ID": "test-tenant-001"}
STORE_ID = "store-001"  # 已授权门店


def _clear_retry_queue():
    """每次测试前清空重试队列，确保测试隔离"""
    _RETRY_QUEUE.clear()


# ──────────────────────────────────────────────────────────────────────────────
# 测试 1：正常核销 — success=True，order_id 非空
# ──────────────────────────────────────────────────────────────────────────────

class TestVerifyVoucherSuccess:
    def setup_method(self):
        _clear_retry_queue()

    def test_verify_voucher_success_basic(self):
        """
        正常券码（非 DY_USED_/DY_EXP_/DY_FAIL_ 前缀）核销成功：
        - success=True
        - order_id 非空
        - voucher_info 包含 product_name / amount_fen / expire_at
        """
        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY20260406ABC001",
                "store_id": STORE_ID,
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )

        assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data["ok"] is True
        assert data["success"] is True, f"核销应成功，实际: {data}"
        assert data["order_id"], "order_id 不能为空"
        assert data["order_id"].startswith("dy-order-"), (
            f"order_id 格式错误：{data['order_id']}"
        )

        vi = data["voucher_info"]
        assert "product_name" in vi, "voucher_info 缺少 product_name"
        assert "amount_fen" in vi, "voucher_info 缺少 amount_fen"
        assert "expire_at" in vi, "voucher_info 缺少 expire_at"
        assert isinstance(vi["amount_fen"], int), "amount_fen 应为整数（分）"
        assert vi["amount_fen"] > 0, "amount_fen 应大于 0"

    def test_verify_voucher_success_order_id_unique(self):
        """多次核销不同券码，order_id 应各不相同"""
        order_ids = set()
        for i in range(3):
            resp = client.post(
                "/api/v1/trade/douyin-voucher/verify",
                json={
                    "voucher_code": f"DY20260406UNIQUE{i:03d}",
                    "store_id": STORE_ID,
                    "operator_id": "op-001",
                },
                headers=TENANT_HEADER,
            )
            data = resp.json()
            if data.get("success"):
                order_ids.add(data["order_id"])

        assert len(order_ids) == 3, f"order_id 应唯一，实际 {order_ids}"

    def test_verify_voucher_success_with_verify_time(self):
        """带 verify_time 参数的核销"""
        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY20260406WITHTIME001",
                "store_id": STORE_ID,
                "operator_id": "op-002",
                "verify_time": "2026-04-06T12:00:00+08:00",
            },
            headers=TENANT_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "verify_time" in data

    def test_verify_voucher_unregistered_store_returns_400(self):
        """未授权门店核销应返回 400"""
        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY20260406XYZ001",
                "store_id": "store-unregistered",
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "STORE_NOT_AUTHORIZED"


# ──────────────────────────────────────────────────────────────────────────────
# 测试 2：已核销券（DY_USED_ 前缀）— success=False，error 含"已核销"
# ──────────────────────────────────────────────────────────────────────────────

class TestVerifyAlreadyUsed:
    def setup_method(self):
        _clear_retry_queue()

    def test_verify_already_used_basic(self):
        """
        DY_USED_ 前缀券码：
        - success=False
        - error.code = "VOUCHER_ALREADY_USED"
        - error.message 包含"已核销"
        """
        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY_USED_ABC001",
                "store_id": STORE_ID,
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )

        assert resp.status_code == 200, f"已核销券应返回 200（业务失败），实际 {resp.status_code}"
        data = resp.json()

        assert data["ok"] is True, "HTTP 层面请求成功"
        assert data["success"] is False, f"已核销券 success 应为 False，实际: {data}"
        assert "error" in data, "应返回 error 字段"

        error = data["error"]
        assert "已核销" in error["message"], (
            f"错误信息应包含'已核销'，实际: '{error['message']}'"
        )
        assert error["code"] == "VOUCHER_ALREADY_USED", (
            f"错误码应为 VOUCHER_ALREADY_USED，实际: '{error['code']}'"
        )

    def test_verify_already_used_not_added_to_retry_queue(self):
        """已核销券失败不应进入重试队列（是业务拒绝，不是平台错误）"""
        initial_queue_size = len(_RETRY_QUEUE)

        client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY_USED_NORETRY001",
                "store_id": STORE_ID,
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )

        assert len(_RETRY_QUEUE) == initial_queue_size, (
            "已核销券不应被加入重试队列"
        )

    def test_verify_expired_voucher(self):
        """DY_EXP_ 前缀：已过期券"""
        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY_EXP_001",
                "store_id": STORE_ID,
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "VOUCHER_EXPIRED"

    def test_verify_platform_error_enqueues_retry(self):
        """DY_FAIL_ 前缀：平台错误 → 必须写入重试队列，不丢弃"""
        initial_queue_size = len(_RETRY_QUEUE)

        resp = client.post(
            "/api/v1/trade/douyin-voucher/verify",
            json={
                "voucher_code": "DY_FAIL_SERVER001",
                "store_id": STORE_ID,
                "operator_id": "op-001",
            },
            headers=TENANT_HEADER,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "PLATFORM_ERROR"
        assert "retry_task_id" in data, "平台错误应返回 retry_task_id"
        assert data["retry_task_id"], "retry_task_id 不能为空"

        # 验证确实写入了重试队列
        assert len(_RETRY_QUEUE) > initial_queue_size, (
            "平台错误必须写入重试队列，不能丢弃"
        )

        task_id = data["retry_task_id"]
        assert task_id in _RETRY_QUEUE, f"task_id {task_id} 应在重试队列中"
        assert _RETRY_QUEUE[task_id]["voucher_code"] == "DY_FAIL_SERVER001"


# ──────────────────────────────────────────────────────────────────────────────
# 测试 3：对账报表 — 返回必要字段，discrepancy_amount_fen 为整数
# ──────────────────────────────────────────────────────────────────────────────

class TestReconciliationReport:
    def test_reconciliation_report_required_fields(self):
        """
        对账报表必须返回：
        local_count / platform_count / matched / unmatched / discrepancy_amount_fen
        """
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-01", "date_to": "2026-04-06"},
            headers=TENANT_HEADER,
        )

        assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["ok"] is True

        report = data["data"]
        required_fields = {
            "local_count", "platform_count", "matched",
            "unmatched", "discrepancy_amount_fen",
        }
        missing = required_fields - set(report.keys())
        assert not missing, f"对账报表缺少必要字段: {missing}"

    def test_reconciliation_discrepancy_amount_is_integer(self):
        """discrepancy_amount_fen 必须为整数（分，不能是浮点数）"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-01", "date_to": "2026-04-06"},
            headers=TENANT_HEADER,
        )

        data = resp.json()
        report = data["data"]

        assert isinstance(report["discrepancy_amount_fen"], int), (
            f"discrepancy_amount_fen 应为整数，实际类型: {type(report['discrepancy_amount_fen'])}"
        )

    def test_reconciliation_counts_consistency(self):
        """local_count/matched/unmatched 数值应保持一致性"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-01", "date_to": "2026-04-06"},
            headers=TENANT_HEADER,
        )

        data = resp.json()
        report = data["data"]

        local = report["local_count"]
        matched = report["matched"]
        unmatched = report["unmatched"]

        assert local >= matched, f"local_count({local}) 不能小于 matched({matched})"
        assert unmatched == local - matched, (
            f"unmatched({unmatched}) 应等于 local_count({local}) - matched({matched})"
        )
        assert matched >= 0
        assert unmatched >= 0

    def test_reconciliation_invalid_date_range_returns_400(self):
        """date_from > date_to 应返回 400"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-30", "date_to": "2026-04-01"},
            headers=TENANT_HEADER,
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "INVALID_DATE_RANGE"

    def test_reconciliation_with_store_filter(self):
        """带门店过滤的对账报表应正常返回"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={
                "date_from": "2026-04-01",
                "date_to": "2026-04-06",
                "store_id": STORE_ID,
            },
            headers=TENANT_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["store_id"] == STORE_ID

    def test_reconciliation_discrepancy_nonnegative(self):
        """discrepancy_amount_fen 不能为负数"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-01", "date_to": "2026-04-06"},
            headers=TENANT_HEADER,
        )
        data = resp.json()
        assert data["data"]["discrepancy_amount_fen"] >= 0, (
            "discrepancy_amount_fen 不能为负数"
        )

    def test_reconciliation_unmatched_records_present_when_unmatched_gt0(self):
        """unmatched > 0 时，unmatched_records 不能为空列表"""
        resp = client.get(
            "/api/v1/trade/douyin-voucher/reconciliation",
            params={"date_from": "2026-04-01", "date_to": "2026-04-06"},
            headers=TENANT_HEADER,
        )
        data = resp.json()
        report = data["data"]

        if report["unmatched"] > 0:
            assert len(report["unmatched_records"]) > 0, (
                "unmatched > 0 时，unmatched_records 不应为空"
            )
        else:
            # unmatched == 0 → unmatched_records 可以为空
            assert report["discrepancy_amount_fen"] == 0
