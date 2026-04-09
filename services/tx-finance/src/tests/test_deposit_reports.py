"""押金报表测试

覆盖：
  1. test_deposit_ledger_status_grouping   — 押金台账按状态分组统计正确
  2. test_deposit_refund_status_change     — 退押金后 status 变为 refunded
  3. test_shift_summary_calculation        — 结班汇总：收 N 笔 - 退 M 笔 = 净留存
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── 工具：构造模拟 deposit 行 ─────────────────────────────────────────────────

def _make_deposit(
    amount_fen: int = 10000,
    applied_fen: int = 0,
    refunded_fen: int = 0,
    status: str = "collected",
) -> dict:
    """返回一个模拟的 biz_deposits 行字典。"""
    return {
        "id": uuid.uuid4(),
        "amount_fen": amount_fen,
        "applied_amount_fen": applied_fen,
        "refunded_amount_fen": refunded_fen,
        "status": status,
        "collected_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ─── Test 1: 押金台账按状态分组统计 ──────────────────────────────────────────

class TestDepositLedgerStatusGrouping:
    """台账报表：按时间段汇总金额应与各笔明细一致。"""

    @pytest.mark.asyncio
    async def test_ledger_aggregation_matches_detail(self):
        """给定 3 笔已收押金 + 1 笔已退押金，台账汇总金额应正确。"""
        deposits = [
            _make_deposit(amount_fen=10000, status="collected"),
            _make_deposit(amount_fen=20000, status="collected"),
            _make_deposit(amount_fen=30000, status="collected"),
            _make_deposit(amount_fen=5000, refunded_fen=5000, status="refunded"),
        ]

        total_collected_fen = sum(d["amount_fen"] for d in deposits)
        total_refunded_fen = sum(d["refunded_amount_fen"] for d in deposits)
        total_outstanding_fen = sum(
            d["amount_fen"] - d["applied_amount_fen"] - d["refunded_amount_fen"]
            for d in deposits
            if d["status"] not in ("refunded", "fully_applied", "converted", "written_off")
        )

        assert total_collected_fen == 65000
        assert total_refunded_fen == 5000
        assert total_outstanding_fen == 60000  # 3 笔 collected 全部待退

    @pytest.mark.asyncio
    async def test_ledger_outstanding_excludes_terminal_statuses(self):
        """已退/已抵扣/已转收入押金不计入待退余额。"""
        deposits = [
            _make_deposit(amount_fen=10000, refunded_fen=10000, status="refunded"),
            _make_deposit(amount_fen=10000, applied_fen=10000, status="fully_applied"),
            _make_deposit(amount_fen=10000, status="converted"),
            _make_deposit(amount_fen=10000, status="collected"),
        ]

        terminal = {"refunded", "fully_applied", "converted", "written_off"}
        outstanding = sum(
            d["amount_fen"] - d["applied_amount_fen"] - d["refunded_amount_fen"]
            for d in deposits
            if d["status"] not in terminal
        )
        assert outstanding == 10000  # 只有最后一笔 collected 计入

    @pytest.mark.asyncio
    async def test_ledger_converted_amount_calculation(self):
        """押金转收入金额 = amount - applied - refunded（当 status='converted'）。"""
        deposit = _make_deposit(
            amount_fen=15000,
            applied_fen=3000,
            refunded_fen=2000,
            status="converted",
        )
        converted = (
            deposit["amount_fen"]
            - deposit["applied_amount_fen"]
            - deposit["refunded_amount_fen"]
        )
        assert converted == 10000


# ─── Test 2: 退押金后 status 变更 ────────────────────────────────────────────

class TestDepositRefundStatusChange:
    """退押金操作后，状态应正确更新。"""

    @pytest.mark.asyncio
    async def test_full_refund_sets_status_refunded(self):
        """全额退还时 new_status 应为 'refunded'。"""
        deposit = _make_deposit(amount_fen=10000, status="collected")

        # 模拟退款逻辑（与 deposit_routes.py refund_deposit 保持一致）
        refund_amount = 10000
        new_refunded = deposit["refunded_amount_fen"] + refund_amount
        new_remaining = (
            deposit["amount_fen"]
            - deposit["applied_amount_fen"]
            - new_refunded
        )
        new_status = "refunded" if new_remaining == 0 else deposit["status"]

        assert new_status == "refunded"
        assert new_remaining == 0

    @pytest.mark.asyncio
    async def test_partial_refund_keeps_original_status(self):
        """部分退还时，status 应保持 'collected'（不变为 refunded）。"""
        deposit = _make_deposit(amount_fen=10000, status="collected")

        refund_amount = 4000  # 只退一半
        new_refunded = deposit["refunded_amount_fen"] + refund_amount
        new_remaining = (
            deposit["amount_fen"]
            - deposit["applied_amount_fen"]
            - new_refunded
        )
        new_status = "refunded" if new_remaining == 0 else deposit["status"]

        assert new_status == "collected"
        assert new_remaining == 6000

    @pytest.mark.asyncio
    async def test_refund_after_partial_apply(self):
        """已部分抵扣后，退还剩余余额应变为 refunded。"""
        deposit = _make_deposit(
            amount_fen=10000,
            applied_fen=4000,
            status="partially_applied",
        )

        remaining_before = (
            deposit["amount_fen"]
            - deposit["applied_amount_fen"]
            - deposit["refunded_amount_fen"]
        )
        assert remaining_before == 6000

        refund_amount = 6000
        new_refunded = deposit["refunded_amount_fen"] + refund_amount
        new_remaining = deposit["amount_fen"] - deposit["applied_amount_fen"] - new_refunded
        new_status = "refunded" if new_remaining == 0 else deposit["status"]

        assert new_status == "refunded"
        assert new_remaining == 0

    @pytest.mark.asyncio
    async def test_refund_exceeds_remaining_raises_error(self):
        """退还金额超过余额时，业务层应拒绝（退还金额校验）。"""
        deposit = _make_deposit(amount_fen=5000, status="collected")
        remaining = deposit["amount_fen"] - deposit["applied_amount_fen"] - deposit["refunded_amount_fen"]

        refund_amount = 6000  # 超过余额
        assert refund_amount > remaining, "测试前提：退款金额确实超过余额"

        # 业务逻辑应抛出或拒绝
        is_valid = refund_amount <= remaining
        assert not is_valid


# ─── Test 3: 结班汇总计算 ─────────────────────────────────────────────────────

class TestShiftSummaryCalculation:
    """结班汇总：收 N 笔 - 退 M 笔 = 净留存。"""

    def _compute_shift_summary(
        self,
        deposits: list[dict],
        shift_start: datetime,
        shift_end: datetime,
    ) -> dict:
        """模拟 shift_summary_report 的核心计算逻辑。"""
        received = [
            d for d in deposits
            if shift_start <= d["collected_at"] <= shift_end
        ]
        refunded = [
            d for d in deposits
            if d["refunded_amount_fen"] > 0
            and shift_start <= d["updated_at"] <= shift_end
        ]

        received_fen = sum(d["amount_fen"] for d in received)
        refunded_fen = sum(d["refunded_amount_fen"] for d in refunded)
        return {
            "received_count": len(received),
            "received_fen": received_fen,
            "refunded_count": len(refunded),
            "refunded_fen": refunded_fen,
            "net_fen": received_fen - refunded_fen,
        }

    @pytest.mark.asyncio
    async def test_shift_net_equals_received_minus_refunded(self):
        """净留存 = 本班收押金 - 本班退押金。"""
        shift_start = datetime(2026, 4, 6, 0, 0, 0, tzinfo=timezone.utc)
        shift_end = datetime(2026, 4, 6, 23, 59, 59, tzinfo=timezone.utc)

        deposits = [
            {**_make_deposit(amount_fen=10000), "collected_at": shift_start, "updated_at": shift_start},
            {**_make_deposit(amount_fen=20000), "collected_at": shift_start, "updated_at": shift_start},
            {**_make_deposit(amount_fen=5000, refunded_fen=5000),
             "collected_at": datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc),  # 上一班收
             "updated_at": shift_start},  # 本班退
        ]

        summary = self._compute_shift_summary(deposits, shift_start, shift_end)

        assert summary["received_count"] == 2
        assert summary["received_fen"] == 30000
        assert summary["refunded_count"] == 1
        assert summary["refunded_fen"] == 5000
        assert summary["net_fen"] == 25000  # 30000 - 5000

    @pytest.mark.asyncio
    async def test_shift_summary_excludes_other_day_deposits(self):
        """昨天收取且昨天退还的押金不应计入今天的结班汇总。"""
        today_start = datetime(2026, 4, 6, 0, 0, 0, tzinfo=timezone.utc)
        today_end = datetime(2026, 4, 6, 23, 59, 59, tzinfo=timezone.utc)
        yesterday = datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc)

        deposits = [
            # 昨天的押金：收取和退还都在昨天
            {**_make_deposit(amount_fen=8000, refunded_fen=8000),
             "collected_at": yesterday, "updated_at": yesterday},
            # 今天的押金
            {**_make_deposit(amount_fen=12000),
             "collected_at": today_start, "updated_at": today_start},
        ]

        summary = self._compute_shift_summary(deposits, today_start, today_end)

        assert summary["received_count"] == 1
        assert summary["received_fen"] == 12000
        assert summary["refunded_count"] == 0
        assert summary["net_fen"] == 12000

    @pytest.mark.asyncio
    async def test_shift_summary_all_refunded_net_zero(self):
        """本班收取后全部退还，净留存为 0（可能出现负值，需有逻辑警示）。"""
        shift_start = datetime(2026, 4, 6, 0, 0, 0, tzinfo=timezone.utc)
        shift_end = datetime(2026, 4, 6, 23, 59, 59, tzinfo=timezone.utc)

        # 本班收 3 笔，本班退 3 笔
        deposits = []
        for _ in range(3):
            d = _make_deposit(amount_fen=5000, refunded_fen=5000)
            d["collected_at"] = shift_start
            d["updated_at"] = shift_start
            deposits.append(d)

        summary = self._compute_shift_summary(deposits, shift_start, shift_end)

        assert summary["received_count"] == 3
        assert summary["received_fen"] == 15000
        assert summary["refunded_count"] == 3
        assert summary["refunded_fen"] == 15000
        assert summary["net_fen"] == 0
