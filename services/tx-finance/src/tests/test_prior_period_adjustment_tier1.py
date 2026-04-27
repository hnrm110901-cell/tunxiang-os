"""Tier 1 测试: W2.A 以前年度损益调整 (v278 + service + 6901 科目)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期合规 (CFO P0-1 跨期漏账场景)

测试边界:
  场景 1. 2027-03 发现 2026-12 漏账 → create_prior_period_adjustment 成功
  场景 2. source_period 越界 (2019 年, 13 月) → ValueError
  场景 3. source_period 两列一空一填 → ValueError
  场景 4. source_period 在未来 (晚于 voucher_date) → ValueError
  场景 5. ORM is_prior_period_adjustment 属性 + to_dict 字段
  场景 6. ACCOUNT_MAPPING['prior_period_adjustment'] 6901 科目存在
  迁移 7. v278 CHECK / 字段 / partial index 完备

运行:
  pytest src/tests/test_prior_period_adjustment_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher  # type: ignore  # noqa: E402
from services.financial_voucher_service import (  # type: ignore  # noqa: E402
    FinancialVoucherService,
    VoucherCreateInput,
    VoucherLineInput,
)


def _prior_period_payload(
    voucher_date: date = date(2027, 3, 10),
    source_year: int | None = 2026,
    source_month: int | None = 12,
) -> VoucherCreateInput:
    """徐记海鲜 2027-03-10 补录 2026-12 漏记采购 ¥15,000."""
    return VoucherCreateInput(
        tenant_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        voucher_no=f"V_PPA_{uuid.uuid4().hex[:6]}",
        voucher_date=voucher_date,
        voucher_type="prior_period_adjustment",
        source_type="manual_adjustment",
        source_period_year=source_year,
        source_period_month=source_month,
        lines=[
            VoucherLineInput(
                account_code="1403", account_name="原材料",
                debit_fen=1500000, summary="补录 2026-12 漏入库 ¥15,000",
            ),
            VoucherLineInput(
                account_code="6901", account_name="以前年度损益调整",
                credit_fen=1500000, summary="冲减 2026 年度利润",
            ),
        ],
    )


def _tenant_assertion_mock() -> MagicMock:
    """B5 tenant 断言豁免."""
    m = MagicMock()
    m.scalar = MagicMock(return_value=None)
    return m


class TestCreatePriorPeriodAdjustment:
    """W2.A 核心路径: 跨期漏账合法补录."""

    @pytest.mark.asyncio
    async def test_success_path_2027_fixing_2026_12(self):
        """徐记海鲜场景: 2027-03-10 补录 2026-12 漏账 ¥15,000."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_tenant_assertion_mock())
        session.flush = AsyncMock()

        payload = _prior_period_payload()
        voucher = await svc.create_prior_period_adjustment(
            payload, session=session,
        )

        assert voucher.source_period_year == 2026
        assert voucher.source_period_month == 12
        assert voucher.voucher_date == date(2027, 3, 10)
        assert voucher.is_prior_period_adjustment is True
        # 金额: ¥15,000 = 1,500,000 fen
        assert voucher.total_amount_fen == 1500000

    @pytest.mark.asyncio
    async def test_rejects_missing_source_year(self):
        """source_period_year=None + source_period_month 填 → 拒 (两者必须同时非空)."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = _prior_period_payload(source_year=None, source_month=12)
        with pytest.raises(ValueError, match="source_period_year.*source_period_month"):
            await svc.create_prior_period_adjustment(payload, session=session)

    @pytest.mark.asyncio
    async def test_rejects_missing_source_month(self):
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = _prior_period_payload(source_year=2026, source_month=None)
        with pytest.raises(ValueError, match="两者必填"):
            await svc.create_prior_period_adjustment(payload, session=session)

    @pytest.mark.asyncio
    async def test_rejects_year_out_of_range(self):
        """source_period_year=2019 (< 2020) → 拒."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = _prior_period_payload(source_year=2019)
        with pytest.raises(ValueError, match="source_period_year 越界"):
            await svc.create_prior_period_adjustment(payload, session=session)

    @pytest.mark.asyncio
    async def test_rejects_month_out_of_range(self):
        """source_period_month=13 → 拒."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = _prior_period_payload(source_month=13)
        with pytest.raises(ValueError, match="source_period_month 越界"):
            await svc.create_prior_period_adjustment(payload, session=session)

    @pytest.mark.asyncio
    async def test_rejects_future_source_period(self):
        """source_period 在未来 (> voucher_date 月) → 拒.

        语义: 以前年度调整的"以前"必须真的在过去.
        """
        svc = FinancialVoucherService()
        session = AsyncMock()

        # voucher_date = 2026-03-10, source_period = 2027-01 (未来)
        payload = _prior_period_payload(
            voucher_date=date(2026, 3, 10),
            source_year=2027, source_month=1,
        )
        with pytest.raises(ValueError, match="source_period.*在过去"):
            await svc.create_prior_period_adjustment(payload, session=session)

    @pytest.mark.asyncio
    async def test_same_period_edge_case_allowed(self):
        """source_period = voucher_date 月 (边界, 同期补录) → 允许."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_tenant_assertion_mock())
        session.flush = AsyncMock()

        # voucher_date = 2027-03-10, source_period = 2027-03 (同月)
        payload = _prior_period_payload(
            voucher_date=date(2027, 3, 10),
            source_year=2027, source_month=3,
        )
        voucher = await svc.create_prior_period_adjustment(payload, session=session)
        assert voucher.source_period_year == 2027
        assert voucher.source_period_month == 3


class TestOrmPriorPeriodAttributes:
    """ORM 属性 + to_dict 字段."""

    def test_is_prior_period_adjustment_false_by_default(self):
        v = FinancialVoucher(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            voucher_no="V_NORMAL", voucher_type="sales",
            entries=[], voided=False,
        )
        assert v.is_prior_period_adjustment is False

    def test_is_prior_period_adjustment_true_when_source_year_set(self):
        v = FinancialVoucher(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            voucher_no="V_PPA", voucher_type="prior_period_adjustment",
            entries=[], voided=False,
            source_period_year=2026, source_period_month=12,
        )
        assert v.is_prior_period_adjustment is True

    def test_to_dict_exposes_source_period_fields(self):
        v = FinancialVoucher(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            voucher_no="V_TO_DICT", voucher_type="prior_period_adjustment",
            entries=[], voided=False,
            source_period_year=2026, source_period_month=11,
        )
        d = v.to_dict()
        assert d["source_period_year"] == 2026
        assert d["source_period_month"] == 11
        assert d["is_prior_period_adjustment"] is True


class TestAccountMapping6901:
    """ACCOUNT_MAPPING 新 6901 科目场景."""

    def test_prior_period_adjustment_scene_exists(self):
        from services.voucher_generator import ACCOUNT_MAPPING  # type: ignore

        assert "prior_period_adjustment" in ACCOUNT_MAPPING
        scene = ACCOUNT_MAPPING["prior_period_adjustment"]
        assert "debit" in scene
        assert "credit" in scene

    def test_6901_is_credit_account_in_mapping(self):
        """6901 "以前年度损益调整" 默认配置为贷方科目 (冲减利润)."""
        from services.voucher_generator import ACCOUNT_MAPPING  # type: ignore

        credit_acc = ACCOUNT_MAPPING["prior_period_adjustment"]["credit"]
        assert credit_acc["code"] == "6901"
        assert "以前年度损益调整" in credit_acc["name"]


class TestV278Migration:
    """v278 migration 结构断言."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v278_prior_period_adjustment.py"
        )
        assert path.exists(), f"v278 迁移不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_is_v278(self):
        assert re.search(r'^revision\s*=\s*"v278"', self.migration_src, re.M)

    def test_down_revision_is_v276(self):
        assert re.search(r'^down_revision\s*=\s*"v276"', self.migration_src, re.M)

    def test_adds_source_period_columns(self):
        for col in ("source_period_year", "source_period_month"):
            assert re.search(
                rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{col}\b",
                self.migration_src, re.I,
            )

    def test_check_source_period_consistency(self):
        """CHECK: 两列同时 NULL 或同时非空."""
        assert "chk_fv_source_period" in self.migration_src
        # 必须同时 NULL 分支
        assert re.search(
            r"source_period_year\s+IS\s+NULL\s+AND\s+source_period_month\s+IS\s+NULL",
            self.migration_src, re.I,
        )
        # 非空分支 + 范围 CHECK
        assert re.search(
            r"source_period_year\s+BETWEEN\s+2020\s+AND\s+2100",
            self.migration_src, re.I,
        )
        assert re.search(
            r"source_period_month\s+BETWEEN\s+1\s+AND\s+12",
            self.migration_src, re.I,
        )

    def test_partial_index_for_audit_query(self):
        """partial index WHERE source_period_year IS NOT NULL (审计查询)."""
        assert "ix_fv_source_period" in self.migration_src
        assert re.search(
            r"CREATE\s+INDEX\s+CONCURRENTLY.*ix_fv_source_period.*"
            r"WHERE\s+source_period_year\s+IS\s+NOT\s+NULL",
            self.migration_src, re.S | re.I,
        )

    def test_orm_has_check_constraint_mirror(self):
        """ORM __table_args__ 必须镜像 DB CHECK."""
        orm_path = (
            Path(__file__).resolve().parents[1] / "models" / "voucher.py"
        )
        orm_src = orm_path.read_text(encoding="utf-8")
        assert "chk_fv_source_period" in orm_src

    def test_raise_notice_markers(self):
        # step 可以是 1a/4 或 1/3 这种格式
        notices = re.findall(
            r"RAISE NOTICE\s+'v278\s+step\s+\w+/\d+",
            self.migration_src,
        )
        assert len(notices) >= 3

    def test_migration_documents_cfo_risk(self):
        """docstring 关联 §19 CFO P0-1."""
        assert re.search(
            r"(CFO\s*P0-1|§19|漏账|6901|以前年度损益|金税四期)",
            self.migration_src,
        )
