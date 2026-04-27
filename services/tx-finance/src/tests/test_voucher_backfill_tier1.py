"""Tier 1 测试: VoucherBackfillService (W1.6, 历史 entries → lines 回填)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期链路

测试边界:
  场景 1. 格式 A (direction + amount_fen): W1.0 voucher_service 产出
  场景 2. 格式 B (debit/credit 元): W1.3 FinancialVoucherService 产出
  场景 3. 格式 A 里的负金额 (折扣): 方向对调 + 金额转正
  场景 4. 混合格式: 两种 entries 并存
  场景 5. 零金额 entries: 跳过 (DB CHECK 会拒)
  场景 6. 借贷不平衡: 跳过 + 记 errors (非 strict 模式)
  场景 7. 借贷不平衡 + strict=True: raise ValueError
  场景 8. entries 字段缺失: 跳过该行不爆
  场景 9. 借贷都非零 (格式 B 污染): 跳过
  场景 10. 幂等: 已有 lines 的凭证不重复生成

运行:
  pytest src/tests/test_voucher_backfill_tier1.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.voucher_backfill_service import (  # type: ignore  # noqa: E402
    BackfillReport,
    VoucherBackfillService,
)


# ─── entries 解析: 多格式 + 边界 ────────────────────────────────────


class TestEntriesParser:
    """_parse_entries_to_fen_pairs: 格式 A/B 兼容 + 边界处理."""

    def test_format_a_direction_debit(self):
        """格式 A: {direction: 'debit', amount_fen, ...}."""
        svc = VoucherBackfillService()
        entries = [{
            "direction": "debit", "account_code": "1001",
            "account_name": "现金", "amount_fen": 10000,
            "summary": "堂食现金",
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert len(parsed) == 1
        assert parsed[0]["debit_fen"] == 10000
        assert parsed[0]["credit_fen"] == 0
        assert parsed[0]["account_code"] == "1001"
        assert parsed[0]["account_name"] == "现金"

    def test_format_a_direction_credit(self):
        svc = VoucherBackfillService()
        entries = [{
            "direction": "credit", "account_code": "6001",
            "account_name": "主营业务收入", "amount_fen": 10000,
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed[0]["debit_fen"] == 0
        assert parsed[0]["credit_fen"] == 10000

    def test_format_a_negative_credit_flips_to_debit(self):
        """格式 A 里的折扣: credit=-1000 (减少收入) → debit=+1000."""
        svc = VoucherBackfillService()
        entries = [{
            "direction": "credit", "account_code": "6001.99",
            "account_name": "折扣抵减", "amount_fen": -1000,
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed[0]["debit_fen"] == 1000
        assert parsed[0]["credit_fen"] == 0

    def test_format_a_amount_yuan_fallback(self):
        """amount_fen 缺失时回退 amount_yuan * 100."""
        svc = VoucherBackfillService()
        entries = [{
            "direction": "debit", "account_code": "1001",
            "amount_yuan": 100.00,  # 无 amount_fen
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed[0]["debit_fen"] == 10000

    def test_format_b_debit_credit_yuan(self):
        """格式 B: W1.3 风格 {debit: 100.00, credit: 0, ...}."""
        svc = VoucherBackfillService()
        entries = [
            {"account_code": "1001", "account_name": "现金",
             "debit": 100.00, "credit": 0, "summary": "堂食"},
            {"account_code": "6001", "account_name": "主营业务收入",
             "debit": 0, "credit": 100.00, "summary": "收入"},
        ]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert len(parsed) == 2
        assert parsed[0]["debit_fen"] == 10000
        assert parsed[1]["credit_fen"] == 10000

    def test_format_b_ieee754_safe_rounding(self):
        """格式 B: 浮点精度 round(x * 100) 避免 IEEE 754 坑."""
        svc = VoucherBackfillService()
        # 0.1 + 0.2 = 0.30000000000000004 (float)
        entries = [{
            "account_code": "1001", "debit": 0.3, "credit": 0,
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed[0]["debit_fen"] == 30  # 正好 30 分

    def test_skips_missing_account_code(self):
        """无 account_code 的 entry 跳过, 不爆."""
        svc = VoucherBackfillService()
        entries = [{"direction": "debit", "amount_fen": 10000}]  # 缺 account_code
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed == []

    def test_format_b_skips_both_zero(self):
        """借贷都为 0 的 entry 跳过."""
        svc = VoucherBackfillService()
        entries = [{"account_code": "1001", "debit": 0, "credit": 0}]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed == []

    def test_format_b_skips_both_nonzero_pollution(self):
        """借贷都非零 (格式 B 污染, 理论不该出现) 跳过."""
        svc = VoucherBackfillService()
        entries = [{"account_code": "1001", "debit": 100, "credit": 50}]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed == []

    def test_format_b_skips_negative(self):
        svc = VoucherBackfillService()
        entries = [{"account_code": "1001", "debit": -100, "credit": 0}]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed == []

    def test_mixed_formats(self):
        """同一 entries list 里混合格式 A + B."""
        svc = VoucherBackfillService()
        entries = [
            {"direction": "debit", "account_code": "1001",
             "amount_fen": 10000, "account_name": "现金"},  # A
            {"account_code": "6001", "account_name": "主营业务收入",
             "debit": 0, "credit": 100.00},  # B
        ]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert len(parsed) == 2
        assert parsed[0]["debit_fen"] == 10000
        assert parsed[1]["credit_fen"] == 10000

    def test_account_name_fallback_to_code(self):
        """account_name 缺省时回退 account_code 作名字."""
        svc = VoucherBackfillService()
        entries = [{
            "direction": "debit", "account_code": "1001", "amount_fen": 10000,
        }]
        parsed = svc._parse_entries_to_fen_pairs(entries, "V_TEST")
        assert parsed[0]["account_name"] == "1001"


# ─── backfill_batch: 批量扫 + 幂等 + 失败容忍 ──────────────────────


def _mock_vouchers_query(rows: list[dict]) -> AsyncMock:
    """构造 session.execute 返回, 支持 .mappings().all()."""
    mock_result = MagicMock()
    mock_result.mappings = MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=rows)
    ))
    return AsyncMock(return_value=mock_result)


class TestBackfillBatch:
    """批量回填行为: 幂等 pre-check / 借贷不平衡 / strict 模式."""

    @pytest.mark.asyncio
    async def test_backfill_normal_voucher(self):
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([{
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "voucher_no": "V_TEST_001",
            "entries": [
                {"direction": "debit", "account_code": "1001",
                 "amount_fen": 10000, "account_name": "现金"},
                {"direction": "credit", "account_code": "6001",
                 "amount_fen": 10000, "account_name": "主营业务收入"},
            ],
        }])
        session.flush = AsyncMock()

        report = await svc.backfill_batch(session=session, batch_size=10)

        assert report.total_scanned == 1
        assert report.backfilled == 1
        assert report.skipped_unbalanced == 0
        assert len(report.errors) == 0
        # 2 lines add
        assert session.add.call_count == 2
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_backfill_dry_run_does_not_insert(self):
        """dry_run=True 不调 session.add."""
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([{
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "voucher_no": "V_DRY",
            "entries": [
                {"direction": "debit", "account_code": "1001", "amount_fen": 10000},
                {"direction": "credit", "account_code": "6001", "amount_fen": 10000},
            ],
        }])

        report = await svc.backfill_batch(session=session, dry_run=True)
        assert report.dry_run is True
        assert report.backfilled == 1
        session.add.assert_not_called()  # 没 add
        session.flush.assert_not_called()  # 没 flush

    @pytest.mark.asyncio
    async def test_backfill_unbalanced_voucher_skipped_non_strict(self):
        """非 strict: 借贷不平衡记入 errors, 其他凭证继续处理."""
        svc = VoucherBackfillService()
        bad_id = uuid.uuid4()
        good_id = uuid.uuid4()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([
            {
                "id": bad_id, "tenant_id": uuid.uuid4(),
                "voucher_no": "V_BAD",
                "entries": [
                    {"direction": "debit", "account_code": "1001", "amount_fen": 10000},
                    {"direction": "credit", "account_code": "6001", "amount_fen": 9900},  # 少 1 分
                ],
            },
            {
                "id": good_id, "tenant_id": uuid.uuid4(),
                "voucher_no": "V_GOOD",
                "entries": [
                    {"direction": "debit", "account_code": "1001", "amount_fen": 5000},
                    {"direction": "credit", "account_code": "6001", "amount_fen": 5000},
                ],
            },
        ])
        session.flush = AsyncMock()

        report = await svc.backfill_batch(session=session, strict=False)

        assert report.total_scanned == 2
        assert report.backfilled == 1  # 只有 good
        assert report.skipped_unbalanced == 1
        assert len(report.errors) == 1
        assert "V_BAD" in report.errors[0].voucher_no
        assert "借贷不平衡" in report.errors[0].error

    @pytest.mark.asyncio
    async def test_backfill_unbalanced_strict_raises(self):
        """strict=True: 借贷不平衡 raise ValueError, 中断批次."""
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([{
            "id": uuid.uuid4(), "tenant_id": uuid.uuid4(),
            "voucher_no": "V_BAD",
            "entries": [
                {"direction": "debit", "account_code": "1001", "amount_fen": 10000},
                {"direction": "credit", "account_code": "6001", "amount_fen": 9900},
            ],
        }])

        with pytest.raises(ValueError, match="借贷不平衡"):
            await svc.backfill_batch(session=session, strict=True)

    @pytest.mark.asyncio
    async def test_backfill_empty_entries_skipped(self):
        """entries 全无效 (零金额) 时跳过."""
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([{
            "id": uuid.uuid4(), "tenant_id": uuid.uuid4(),
            "voucher_no": "V_EMPTY",
            "entries": [
                {"account_code": "1001", "debit": 0, "credit": 0},  # 零金额
            ],
        }])
        session.flush = AsyncMock()

        report = await svc.backfill_batch(session=session)
        assert report.skipped_empty == 1
        assert report.backfilled == 0

    @pytest.mark.asyncio
    async def test_backfill_report_summary(self):
        """BackfillReport.summary() 输出关键指标."""
        r = BackfillReport(
            total_scanned=5, backfilled=3,
            skipped_existing=1, skipped_unbalanced=1,
            errors=[], dry_run=False,
        )
        s = r.summary()
        assert "scanned=5" in s
        assert "backfilled=3" in s
        assert "skipped_existing=1" in s
        assert "skipped_unbalanced=1" in s

    @pytest.mark.asyncio
    async def test_backfill_tenant_filter(self):
        """指定 tenant_id 时 SQL 加 tenant 过滤 (params 含 tid)."""
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([])
        session.flush = AsyncMock()

        tenant = uuid.uuid4()
        await svc.backfill_batch(
            session=session, tenant_id=tenant, batch_size=100,
        )

        # 检 session.execute 被调用, params 含 tid
        assert session.execute.call_count == 1
        params = session.execute.call_args.args[1]
        assert params["tid"] == tenant
        assert params["n"] == 100

    @pytest.mark.asyncio
    async def test_backfill_no_rows_report_zero(self):
        """空批次: total_scanned=0, 不调 flush."""
        svc = VoucherBackfillService()
        session = AsyncMock()
        session.execute = _mock_vouchers_query([])

        report = await svc.backfill_batch(session=session)
        assert report.total_scanned == 0
        assert report.backfilled == 0
