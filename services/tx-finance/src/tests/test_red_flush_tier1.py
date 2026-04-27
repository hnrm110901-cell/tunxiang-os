"""Tier 1 测试: 红冲 (red_flush) + v272 migration 结构 (W1.5)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期审计红线

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. 已推 ERP 的日结凭证发现科目错误, 财务总监红冲
  场景 2. 红冲绕过账期校验 (闭账凭证的唯一合法修正路径)
  场景 3. 借贷对调 + 凭证级金额取负 (红字) + 分录级保持正 (DB CHECK)
  场景 4. 双向 link 双方写入
  场景 5. 拒绝: draft / confirmed 凭证不应红冲 (应 void)
  场景 6. 拒绝: 已被红冲 (最多一次)
  场景 7. 拒绝: 红冲凭证本身不可再红冲 (防递归)
  场景 8. 拒绝: 已作废凭证不可红冲
  迁移结构 9. v272 文件: 2 FK / 1 CHECK 互斥 / 1 UNIQUE partial / 1 partial index

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_red_flush_tier1.py -v
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

from models.voucher import FinancialVoucher, FinancialVoucherLine  # type: ignore  # noqa: E402
from services.financial_voucher_service import (  # type: ignore  # noqa: E402
    FinancialVoucherService,
)


def _exported_voucher(
    tenant_id: uuid.UUID | None = None,
    voucher_no: str = "V_XJ_20260419_001",
) -> FinancialVoucher:
    """徐记海鲜门店 ¥100 销售凭证 — 已推 ERP (status=exported)."""
    t = tenant_id or uuid.uuid4()
    v = FinancialVoucher(
        id=uuid.uuid4(),
        tenant_id=t,
        store_id=uuid.uuid4(),
        voucher_no=voucher_no,
        voucher_date=date(2026, 4, 19),
        voucher_type="sales",
        total_amount_fen=10000,
        total_amount=100.00,
        entries=[
            {"account_code": "1001", "account_name": "现金",
             "debit": 100.00, "credit": 0.00, "summary": "堂食现金"},
            {"account_code": "6001", "account_name": "主营业务收入",
             "debit": 0.00, "credit": 100.00, "summary": "堂食收入"},
        ],
        status="exported",
        voided=False,
    )
    v.lines = [
        FinancialVoucherLine(
            id=uuid.uuid4(), tenant_id=t, line_no=1,
            account_code="1001", account_name="现金",
            debit_fen=10000, credit_fen=0, summary="堂食现金",
        ),
        FinancialVoucherLine(
            id=uuid.uuid4(), tenant_id=t, line_no=2,
            account_code="6001", account_name="主营业务收入",
            debit_fen=0, credit_fen=10000, summary="堂食收入",
        ),
    ]
    return v


# ─── ORM 属性 ──────────────────────────────────────────────────────


class TestRedFlushProperties:
    """is_red_flush_voucher / has_been_red_flushed 属性."""

    def test_normal_voucher_neither(self):
        v = _exported_voucher()
        assert v.is_red_flush_voucher is False
        assert v.has_been_red_flushed is False

    def test_red_flush_voucher_flag(self):
        v = _exported_voucher()
        v.red_flush_of_voucher_id = uuid.uuid4()
        assert v.is_red_flush_voucher is True
        assert v.has_been_red_flushed is False

    def test_flushed_by_flag(self):
        v = _exported_voucher()
        v.red_flushed_by_voucher_id = uuid.uuid4()
        assert v.is_red_flush_voucher is False
        assert v.has_been_red_flushed is True


# ─── Service red_flush 场景 ──────────────────────────────────────


class TestRedFlushGeneration:
    """生成红字凭证: 借贷对调 + 凭证级金额取负 + 分录级保持正."""

    @pytest.mark.asyncio
    async def test_red_flush_generates_reverse_entries(self):
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id,
            operator_id=uuid.uuid4(),
            reason="科目误记",
            session=session,
        )

        # 凭证级金额取负 (红字)
        assert red.total_amount_fen == -10000
        assert red.total_amount == -100.00
        # 分录级借贷对调, 金额保持正 (DB CHECK 要求)
        assert len(red.lines) == 2
        # 原: 1001 借 10000 → 红冲: 1001 贷 10000
        line_1001 = next(l for l in red.lines if l.account_code == "1001")
        assert line_1001.debit_fen == 0
        assert line_1001.credit_fen == 10000
        # 原: 6001 贷 10000 → 红冲: 6001 借 10000
        line_6001 = next(l for l in red.lines if l.account_code == "6001")
        assert line_6001.debit_fen == 10000
        assert line_6001.credit_fen == 0

    @pytest.mark.asyncio
    async def test_red_flush_entries_jsonb_also_reversed(self):
        """entries JSONB (ERP 推送契约) 也要借贷对调."""
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )

        entries_by_code = {e["account_code"]: e for e in red.entries}
        assert entries_by_code["1001"]["debit"] == 0
        assert entries_by_code["1001"]["credit"] == 100.00
        assert entries_by_code["6001"]["debit"] == 100.00
        assert entries_by_code["6001"]["credit"] == 0

    @pytest.mark.asyncio
    async def test_red_flush_summary_prefix(self):
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )

        for line in red.lines:
            assert line.summary.startswith("红冲:")

    @pytest.mark.asyncio
    async def test_red_flush_bidirectional_link(self):
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )

        # 双向 link
        assert red.red_flush_of_voucher_id == original.id
        assert original.red_flushed_by_voucher_id == red.id

    @pytest.mark.asyncio
    async def test_red_flush_voucher_no_auto_suffix(self):
        """默认红字凭证编号 = 原 + '-R'."""
        svc = FinancialVoucherService()
        original = _exported_voucher(voucher_no="V_XJ_20260419_001")

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )
        assert red.voucher_no == "V_XJ_20260419_001-R"

    @pytest.mark.asyncio
    async def test_red_flush_custom_voucher_no(self):
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
            new_voucher_no="V_CUSTOM_RED_001",
        )
        assert red.voucher_no == "V_CUSTOM_RED_001"

    @pytest.mark.asyncio
    async def test_red_flush_sets_draft_status(self):
        """红字凭证重新走 draft → confirmed → exported 流程 (再推 ERP)."""
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )
        assert red.status == "draft"

    @pytest.mark.asyncio
    async def test_red_flush_event_type_set(self):
        """红冲凭证 event_type='red_flush.voucher', event_id=None (手工不幂等)."""
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )
        assert red.event_type == "red_flush.voucher"
        assert red.event_id is None


# ─── Service 拒绝路径 ─────────────────────────────────────────────


class TestRedFlushRejections:
    """拒绝: 非 exported / 已作废 / 已被红冲 / 本身是红冲 / reason 空."""

    async def _service_with_voucher(self, voucher: FinancialVoucher):
        session = AsyncMock()
        session.get = AsyncMock(return_value=voucher)
        # [W2.D] pre-check (red_flush_of_voucher_id 查孤儿) 默认返 None
        pre_miss = MagicMock()
        pre_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=pre_miss)
        return FinancialVoucherService(), session

    @pytest.mark.asyncio
    async def test_reject_draft_voucher(self):
        """draft 凭证应走 void 而非 red_flush."""
        v = _exported_voucher()
        v.status = "draft"
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="draft.*void"):
            await svc.red_flush(v.id, operator_id=uuid.uuid4(),
                                reason="test", session=session)

    @pytest.mark.asyncio
    async def test_reject_confirmed_voucher(self):
        v = _exported_voucher()
        v.status = "confirmed"
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="confirmed.*void"):
            await svc.red_flush(v.id, operator_id=uuid.uuid4(),
                                reason="test", session=session)

    @pytest.mark.asyncio
    async def test_reject_nonexistent_voucher(self):
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="凭证不存在"):
            await svc.red_flush(
                uuid.uuid4(), operator_id=uuid.uuid4(),
                reason="test", session=session,
            )

    @pytest.mark.asyncio
    async def test_reject_empty_reason(self):
        v = _exported_voucher()
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="红冲原因必填"):
            await svc.red_flush(
                v.id, operator_id=uuid.uuid4(),
                reason="   ", session=session,
            )

    @pytest.mark.asyncio
    async def test_reject_voided_voucher(self):
        v = _exported_voucher()
        # 模拟手工改 voided=True + status=exported (理论上不应并存, 但 DB 层不禁)
        v.voided = True
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="已作废"):
            await svc.red_flush(v.id, operator_id=uuid.uuid4(),
                                reason="test", session=session)

    @pytest.mark.asyncio
    async def test_reject_already_red_flushed(self):
        """一张凭证只能被红冲一次."""
        v = _exported_voucher()
        v.red_flushed_by_voucher_id = uuid.uuid4()
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="已被红冲.*不可重复"):
            await svc.red_flush(v.id, operator_id=uuid.uuid4(),
                                reason="test", session=session)

    @pytest.mark.asyncio
    async def test_reject_is_red_flush_voucher_itself(self):
        """红冲凭证本身不可再被红冲 (防递归)."""
        v = _exported_voucher()
        v.red_flush_of_voucher_id = uuid.uuid4()  # 本身是红冲凭证
        svc, session = await self._service_with_voucher(v)

        with pytest.raises(ValueError, match="本身是红冲凭证.*防递归"):
            await svc.red_flush(v.id, operator_id=uuid.uuid4(),
                                reason="test", session=session)


# ─── 账期校验绕过 ──────────────────────────────────────────────────


class TestRedFlushBypassesPeriodCheck:
    """红冲必须能对 closed/locked 账期凭证生效 (金税四期红线)."""

    @pytest.mark.asyncio
    async def test_red_flush_ignores_period_service(self):
        """即便 period_service.is_date_writable 会 raise, red_flush 不调用它."""
        from unittest.mock import AsyncMock

        period_service = AsyncMock()
        period_service.is_date_writable = AsyncMock(
            side_effect=RuntimeError("不该被调用")
        )

        svc = FinancialVoucherService(period_service=period_service)
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        # [W2.D] pre-check 默认返 None (无孤儿)
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="闭账月错账修正", session=session,
        )

        # 成功生成, 且 period_service.is_date_writable 未被调用
        assert red.red_flush_of_voucher_id == original.id
        period_service.is_date_writable.assert_not_called()


# ─── v272 迁移文件结构 ────────────────────────────────────────────


class TestW2FRedFlushAuditFields:
    """[W2.F §19 安全 P1-4 + CFO P1-7] red_flush 审计字段入 DB, 不只 log."""

    @pytest.mark.asyncio
    async def test_red_flush_writes_operator_id_to_db(self):
        """红字凭证 red_flush_operator_id 字段持久化."""
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        operator = uuid.uuid4()
        reason = "2026-04 科目误记"

        red = await svc.red_flush(
            original.id, operator_id=operator, reason=reason,
            session=session,
        )

        assert red.red_flush_operator_id == operator
        assert red.red_flush_reason == reason
        assert red.red_flushed_at is not None

    @pytest.mark.asyncio
    async def test_red_flush_reason_stripped(self):
        """reason 首尾空白被 strip (存储规范)."""
        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="  带空白的原因  ", session=session,
        )
        assert red.red_flush_reason == "带空白的原因"

    @pytest.mark.asyncio
    async def test_red_flush_audit_timestamp_recent(self):
        """red_flushed_at 应为当前 UTC 时间."""
        from datetime import datetime as _datetime, timezone as _tz

        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        session.flush = AsyncMock()
        _pre = MagicMock()
        _pre.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=_pre)

        before = _datetime.now(_tz.utc)
        red = await svc.red_flush(
            original.id, operator_id=uuid.uuid4(),
            reason="test", session=session,
        )
        after = _datetime.now(_tz.utc)

        assert before <= red.red_flushed_at <= after

    def test_to_dict_exposes_red_flush_audit_fields(self):
        v = _exported_voucher()
        v.red_flush_of_voucher_id = uuid.uuid4()
        v.red_flush_operator_id = uuid.uuid4()
        v.red_flush_reason = "科目调整"
        from datetime import datetime as _dt, timezone as _tz
        v.red_flushed_at = _dt(2027, 3, 10, 12, 0, tzinfo=_tz.utc)

        d = v.to_dict()
        assert d["red_flush_operator_id"] == str(v.red_flush_operator_id)
        assert d["red_flush_reason"] == "科目调整"
        assert d["red_flushed_at"] == "2027-03-10T12:00:00+00:00"


class TestV280RedFlushAuditMigration:
    """v280 migration 结构断言."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v280_red_flush_audit_fields.py"
        )
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_is_v280(self):
        assert re.search(r'^revision\s*=\s*"v280"', self.migration_src, re.M)

    def test_down_revision_is_v278(self):
        assert re.search(r'^down_revision\s*=\s*"v278"', self.migration_src, re.M)

    def test_adds_three_audit_columns(self):
        for col in ("red_flush_operator_id", "red_flush_reason", "red_flushed_at"):
            assert re.search(
                rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{col}",
                self.migration_src, re.I,
            )

    def test_check_audit_with_not_valid(self):
        """CHECK 红字必须有审计 + NOT VALID (跳过历史行)."""
        assert "chk_voucher_red_flush_audit" in self.migration_src
        # 表达式: red_flush_of IS NULL OR (operator + at IS NOT NULL)
        assert re.search(
            r"red_flush_of_voucher_id\s+IS\s+NULL\s+OR\s+\(\s*"
            r"red_flush_operator_id\s+IS\s+NOT\s+NULL\s+AND\s+"
            r"red_flushed_at\s+IS\s+NOT\s+NULL",
            self.migration_src, re.I,
        )
        # NOT VALID (历史行豁免)
        assert re.search(r"\)\s*NOT\s+VALID", self.migration_src, re.I)

    def test_orm_has_check_mirror(self):
        orm_path = Path(__file__).resolve().parents[1] / "models" / "voucher.py"
        orm_src = orm_path.read_text(encoding="utf-8")
        assert "chk_voucher_red_flush_audit" in orm_src


class TestW2DRedFlushOrphanProtection:
    """[W2.D §19 DBA P1-5] 孤儿红字凭证防护 (应用层 pre-check + DB UNIQUE 兜底)."""

    @pytest.mark.asyncio
    async def test_red_flush_rejects_when_orphan_red_exists(self):
        """已有红字凭证指向 original (孤儿) → 应用层 pre-check 拒.

        场景: W1.5 红冲 flush #1 成功 + flush #2 失败 (连接断+误 commit) →
        红字凭证已落 DB, 原凭证 red_flushed_by_voucher_id=NULL.
        此时重试 red_flush(original) 必须拒绝 (防生成第二张红字孤儿).
        """
        svc = FinancialVoucherService()
        original = _exported_voucher()

        # 模拟已有孤儿红字凭证
        orphan_red = FinancialVoucher(
            id=uuid.uuid4(), tenant_id=original.tenant_id,
            voucher_no="V_ORPHAN_RED", voucher_type="sales",
            status="draft", entries=[], voided=False,
            red_flush_of_voucher_id=original.id,
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        # pre-check 返孤儿
        pre_hit = MagicMock()
        pre_hit.scalar_one_or_none = MagicMock(return_value=orphan_red)
        session.execute = AsyncMock(return_value=pre_hit)

        with pytest.raises(ValueError, match="孤儿|DBA 手工修复"):
            await svc.red_flush(
                original.id, operator_id=uuid.uuid4(),
                reason="重试", session=session,
            )

    @pytest.mark.asyncio
    async def test_red_flush_db_unique_violation_raises_clear_error(self):
        """[W2.D DB 兜底] v276 UNIQUE 并发触发 → 明确"并发红冲冲突"消息."""
        from sqlalchemy.exc import IntegrityError

        svc = FinancialVoucherService()
        original = _exported_voucher()

        session = AsyncMock()
        session.get = AsyncMock(return_value=original)
        # pre-check miss (两 worker 都过 pre-check)
        pre_miss = MagicMock()
        pre_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=pre_miss)
        # flush 撞 v276 UNIQUE
        fake_orig = Exception(
            'duplicate key value violates unique constraint "ix_fv_red_flush_of"'
        )
        session.flush = AsyncMock(
            side_effect=IntegrityError("INSERT ...", {}, fake_orig)
        )

        with pytest.raises(ValueError, match="并发红冲冲突"):
            await svc.red_flush(
                original.id, operator_id=uuid.uuid4(),
                reason="并发", session=session,
            )


class TestV276RedFlushOfUniqueMigration:
    """[W2.D] v276 migration 结构断言."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v276_red_flush_of_unique.py"
        )
        assert path.exists(), f"v276 迁移不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_is_v276(self):
        assert re.search(r'^revision\s*=\s*"v276"', self.migration_src, re.M)

    def test_down_revision_is_v274(self):
        assert re.search(r'^down_revision\s*=\s*"v274"', self.migration_src, re.M)

    def test_drops_old_non_unique_index(self):
        """step 1: DROP INDEX IF EXISTS 老 ix_fv_red_flush_of."""
        assert re.search(
            r"DROP\s+INDEX\s+CONCURRENTLY\s+IF\s+EXISTS\s+ix_fv_red_flush_of",
            self.migration_src, re.I,
        )

    def test_creates_unique_partial_index(self):
        """step 2: CREATE UNIQUE INDEX CONCURRENTLY partial."""
        assert re.search(
            r"CREATE\s+UNIQUE\s+INDEX\s+CONCURRENTLY.*?ix_fv_red_flush_of"
            r".*?WHERE\s+red_flush_of_voucher_id\s+IS\s+NOT\s+NULL",
            self.migration_src, re.S | re.I,
        )

    def test_uses_autocommit_block(self):
        """CONCURRENTLY 必须在 autocommit_block."""
        assert "autocommit_block" in self.migration_src

    def test_migration_documents_orphan_risk(self):
        """docstring 说明 W1.5 孤儿风险 + §19 P1-5 关联."""
        assert re.search(
            r"(W1\.5|孤儿|P1-5|§19|flush.*#2)",
            self.migration_src,
        )


class TestV272MigrationFileStructure:
    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v272_financial_vouchers_red_flush.py"
        )
        assert path.exists(), f"v272 不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_is_v272(self):
        assert re.search(r'^revision\s*=\s*"v272"', self.migration_src, re.M)

    def test_down_revision_chains_from_v270(self):
        assert re.search(r'^down_revision\s*=\s*"v270"', self.migration_src, re.M)

    def test_adds_two_red_flush_columns(self):
        for col in ("red_flush_of_voucher_id", "red_flushed_by_voucher_id"):
            assert re.search(
                rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{col}",
                self.migration_src, re.I,
            ), f"v272 缺 ADD COLUMN {col}"

    def test_fk_with_on_delete_restrict(self):
        """两 FK 必须 ON DELETE RESTRICT (不能级联删除红冲凭证引用)."""
        assert "fk_fv_red_flush_of" in self.migration_src
        assert "fk_fv_red_flushed_by" in self.migration_src
        # 两个 FK 都应 ON DELETE RESTRICT
        restrict_count = len(re.findall(r"ON\s+DELETE\s+RESTRICT", self.migration_src))
        assert restrict_count >= 2, (
            f"两个 FK 都需 ON DELETE RESTRICT, 实际 {restrict_count}"
        )

    def test_check_red_flush_exclusive(self):
        """CHECK: 一张凭证不能既是红冲又被红冲 (防递归)."""
        assert "chk_voucher_red_flush_exclusive" in self.migration_src
        assert re.search(
            r"red_flush_of_voucher_id\s+IS\s+NULL\s+OR\s+red_flushed_by_voucher_id\s+IS\s+NULL",
            self.migration_src, re.I,
        )

    def test_unique_red_flushed_by_partial(self):
        """UNIQUE partial: 一张凭证最多被红冲一次."""
        assert "uq_fv_red_flushed_by" in self.migration_src
        assert re.search(
            r"CREATE\s+UNIQUE\s+INDEX\s+CONCURRENTLY.*?uq_fv_red_flushed_by"
            r".*?WHERE\s+red_flushed_by_voucher_id\s+IS\s+NOT\s+NULL",
            self.migration_src, re.S | re.I,
        )

    def test_partial_index_for_red_flush_of(self):
        """ix_fv_red_flush_of partial: 查'这张原凭证是否被红冲过'."""
        assert "ix_fv_red_flush_of" in self.migration_src
        assert re.search(
            r"CREATE\s+INDEX\s+CONCURRENTLY.*?ix_fv_red_flush_of"
            r".*?WHERE\s+red_flush_of_voucher_id\s+IS\s+NOT\s+NULL",
            self.migration_src, re.S | re.I,
        )

    def test_all_indexes_concurrently(self):
        """老表加索引必须 CONCURRENTLY."""
        create_index_stmts = re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            self.migration_src, re.I,
        )
        concurrent_count = len(re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY", self.migration_src, re.I,
        ))
        assert concurrent_count == len(create_index_stmts), (
            f"老表 {len(create_index_stmts)} 个 CREATE INDEX 全需 CONCURRENTLY"
        )

    def test_orm_has_check_constraint_mirror(self):
        """ORM __table_args__ 必须镜像 DB CHECK (flush 前校验)."""
        orm_path = (
            Path(__file__).resolve().parents[1]
            / "models" / "voucher.py"
        )
        orm_src = orm_path.read_text(encoding="utf-8")
        assert "chk_voucher_red_flush_exclusive" in orm_src

    def test_raise_notice_markers(self):
        notices = re.findall(r"RAISE NOTICE\s+'v272\s+step\s+\d+/\d+", self.migration_src)
        assert len(notices) >= 3
