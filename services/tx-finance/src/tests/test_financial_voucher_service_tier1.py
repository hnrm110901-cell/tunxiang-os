"""Tier 1 测试: FinancialVoucherService (W1.3, 双写 + 幂等)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期链路

测试策略:
  - dataclass 输入前置校验用纯 Python 单元测试 (秒级)
  - service 流程用 AsyncMock(AsyncSession) 测试幂等 / 双写 / 作废 (tx-finance 惯例)
  - 实际 DB 写入 (真 PG 事务 / partial UNIQUE 并发) 走 DEV Postgres 手动验证
    (与 W1.0-W1.2 策略一致, 避免 pytest-postgres fixture 依赖)

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. 日结凭证: 借 8600 现金/微信/支付宝 / 贷 8600 营业收入 → 幂等写入
  场景 2. 订单支付 Celery 重试 3 次 → 只生成 1 张凭证 (event_id 相同)
  场景 3. 采购入库借贷不平衡 → 前置 ValueError
  场景 4. 误生成凭证 operator 作废 → voided=TRUE + 审计留痕
  场景 5. 已 exported 凭证 operator 尝试作废 → 拒绝 (红冲引导)
  场景 6. VoucherLineInput dataclass 守 DB CHECK 前置 (借贷互斥非负)

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_financial_voucher_service_tier1.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher  # type: ignore  # noqa: E402
from services.financial_voucher_service import (  # type: ignore  # noqa: E402
    FinancialVoucherService,
    VoucherCreateInput,
    VoucherLineInput,
)


# ─── 输入校验: VoucherLineInput dataclass 守 DB CHECK 前置 ────────────


class TestVoucherLineInputValidation:
    """dataclass 前置校验 — 用户体验: DB 层报错太晚, 应用层尽早反馈."""

    def test_valid_debit_only(self):
        line = VoucherLineInput(
            account_code="1122", account_name="应收账款",
            debit_fen=10000, credit_fen=0, summary="堂食应收",
        )
        assert line.debit_fen == 10000

    def test_valid_credit_only(self):
        line = VoucherLineInput(
            account_code="6001", account_name="主营业务收入",
            debit_fen=0, credit_fen=10000,
        )
        assert line.credit_fen == 10000

    def test_rejects_both_zero(self):
        with pytest.raises(ValueError, match="借贷互斥"):
            VoucherLineInput(
                account_code="1122", account_name="应收账款",
                debit_fen=0, credit_fen=0,
            )

    def test_rejects_both_nonzero(self):
        with pytest.raises(ValueError, match="借贷互斥"):
            VoucherLineInput(
                account_code="1122", account_name="应收账款",
                debit_fen=5000, credit_fen=5000,
            )

    def test_rejects_negative_debit(self):
        with pytest.raises(ValueError, match="借贷必须非负"):
            VoucherLineInput(
                account_code="1122", account_name="应收账款",
                debit_fen=-100, credit_fen=0,
            )

    def test_rejects_negative_credit(self):
        with pytest.raises(ValueError, match="借贷必须非负"):
            VoucherLineInput(
                account_code="6001", account_name="主营业务收入",
                debit_fen=0, credit_fen=-100,
            )


# ─── 幂等写入场景 ────────────────────────────────────────────────────


def _daily_settlement_payload(
    tenant_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    voucher_no: str = "V_XJ_20260419_001",
) -> VoucherCreateInput:
    """徐记海鲜 S001 门店日结 ¥86.00 凭证 (用于多个测试复用)."""
    return VoucherCreateInput(
        tenant_id=tenant_id or uuid.uuid4(),
        store_id=uuid.uuid4(),
        voucher_no=voucher_no,
        voucher_date=date(2026, 4, 19),
        voucher_type="sales",
        event_type="daily_settlement.closed",
        event_id=event_id,
        lines=[
            VoucherLineInput(
                account_code="1001", account_name="库存现金",
                debit_fen=3000, summary="堂食现金",
            ),
            VoucherLineInput(
                account_code="1002.01", account_name="银行存款-微信",
                debit_fen=4000, summary="堂食微信",
            ),
            VoucherLineInput(
                account_code="1002.02", account_name="银行存款-支付宝",
                debit_fen=1600, summary="堂食支付宝",
            ),
            VoucherLineInput(
                account_code="6001", account_name="主营业务收入-餐饮",
                credit_fen=8600, summary="2026-04-19 营业收入",
            ),
        ],
    )


class TestCreateIdempotency:
    """场景: Celery 任务重试 / order.paid 事件重发 → 不生成重复凭证."""

    @pytest.mark.asyncio
    async def test_create_without_event_id_skips_idempotency_check(self):
        """event_id=None: 不查预存在, 直接 INSERT (靠 voucher_no UNIQUE 兜底)."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=None)
        result = await svc.create(payload, session=session)

        # 没走 _find_by_event (SELECT)
        session.execute.assert_not_called()
        # add + flush 调用
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert isinstance(result, FinancialVoucher)

    @pytest.mark.asyncio
    async def test_create_with_event_id_checks_idempotency_first(self):
        """event_id != None: 先 SELECT, 若存在则直接返回 (不 flush)."""
        svc = FinancialVoucherService()

        existing = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_EXISTING_001",
            voucher_type="sales",
            entries=[],
            voided=False,
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=mock_result)

        event_id = uuid.uuid4()
        payload = _daily_settlement_payload(event_id=event_id)

        result = await svc.create(payload, session=session)

        # 走了 _find_by_event (SELECT), 拿到 existing
        session.execute.assert_awaited_once()
        # 没 add 新凭证 (直接复用)
        session.add.assert_not_called()
        session.flush.assert_not_called()
        assert result is existing

    @pytest.mark.asyncio
    async def test_create_with_event_id_misses_then_inserts(self):
        """event_id != None 但 SELECT 未命中: 走 INSERT (add + flush)."""
        svc = FinancialVoucherService()

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)  # 未命中
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=uuid.uuid4())

        result = await svc.create(payload, session=session)

        session.execute.assert_awaited_once()  # 幂等预查
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert isinstance(result, FinancialVoucher)

    @pytest.mark.asyncio
    async def test_concurrent_race_catches_unique_violation_and_refetches(self):
        """并发场景: 两 worker 同 event_id, 后者撞 partial UNIQUE → refetch 返回前者."""
        from sqlalchemy.exc import IntegrityError

        svc = FinancialVoucherService()

        winner = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_WINNER",
            voucher_type="sales",
            entries=[],
            voided=False,
        )

        # 第一次 execute (预查) 返回 None, flush 触发 IntegrityError,
        # 第二次 execute (refetch) 返回 winner
        mock_result_miss = MagicMock()
        mock_result_miss.scalar_one_or_none = MagicMock(return_value=None)
        mock_result_hit = MagicMock()
        mock_result_hit.scalar_one_or_none = MagicMock(return_value=winner)

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_result_miss, mock_result_hit])

        # IntegrityError 的 orig 字符串必须含 uq_fv_tenant_event (service 识别线索)
        fake_orig = Exception(
            'duplicate key value violates unique constraint "uq_fv_tenant_event"'
        )
        session.flush = AsyncMock(
            side_effect=IntegrityError("INSERT ...", {}, fake_orig)
        )
        session.rollback = AsyncMock()

        payload = _daily_settlement_payload(event_id=uuid.uuid4())
        result = await svc.create(payload, session=session)

        # 预查 miss → add → flush 报错 → rollback → refetch hit
        assert session.execute.await_count == 2
        session.rollback.assert_awaited_once()
        assert result is winner

    @pytest.mark.asyncio
    async def test_non_idempotency_integrity_error_reraised(self):
        """非 event_id 冲突 (e.g. voucher_no UNIQUE) 的 IntegrityError 上抛."""
        from sqlalchemy.exc import IntegrityError

        svc = FinancialVoucherService()
        session = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)

        # voucher_no 冲突 (非 partial UNIQUE)
        fake_orig = Exception(
            'duplicate key value violates unique constraint "financial_vouchers_voucher_no_key"'
        )
        session.flush = AsyncMock(
            side_effect=IntegrityError("INSERT ...", {}, fake_orig)
        )

        payload = _daily_settlement_payload(event_id=uuid.uuid4())
        with pytest.raises(IntegrityError):
            await svc.create(payload, session=session)


# ─── 双写 entries + lines ────────────────────────────────────────────


class TestDoubleWrite:
    """双写: entries JSONB (向后兼容) + lines 子表 (SSOT) 同事务同数据."""

    @pytest.mark.asyncio
    async def test_entries_jsonb_and_lines_match(self):
        """entries 分录与 lines 子表金额/科目一一对应."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=None)
        voucher = await svc.create(payload, session=session)

        # lines 子表: 4 行 (与 payload.lines 对齐)
        assert len(voucher.lines) == 4
        # entries JSONB: 也是 4 条
        assert len(voucher.entries) == 4

        # lines.debit_fen 与 entries.debit (元) 一致
        lines_by_account = {l.account_code: l for l in voucher.lines}
        for entry in voucher.entries:
            line = lines_by_account[entry["account_code"]]
            # 元 = 分 / 100
            assert entry["debit"] == line.debit_fen / 100
            assert entry["credit"] == line.credit_fen / 100
            assert entry["account_name"] == line.account_name

    @pytest.mark.asyncio
    async def test_total_amount_fen_is_sum_of_debit(self):
        """total_amount_fen = sum(lines.debit_fen) — 凭证总金额约定."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=None)
        voucher = await svc.create(payload, session=session)

        # 3000 + 4000 + 1600 = 8600
        assert voucher.total_amount_fen == 8600
        # 元字段也同步 (W2 GENERATED 前过渡)
        assert voucher.total_amount == 86.00

    @pytest.mark.asyncio
    async def test_lines_have_sequential_line_no(self):
        """lines.line_no 从 1 开始递增 (凭证内序号)."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=None)
        voucher = await svc.create(payload, session=session)

        assert [l.line_no for l in voucher.lines] == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_lines_tenant_id_synced_with_voucher(self):
        """lines.tenant_id 与 voucher.tenant_id 同步 (防跨租户 JOIN 攻击)."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        tenant = uuid.uuid4()
        payload = _daily_settlement_payload(tenant_id=tenant, event_id=None)
        voucher = await svc.create(payload, session=session)

        for line in voucher.lines:
            assert line.tenant_id == tenant

    @pytest.mark.asyncio
    async def test_is_balanced_from_lines_true(self):
        """服务生成的凭证通过 is_balanced_from_lines() 断言."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _daily_settlement_payload(event_id=None)
        voucher = await svc.create(payload, session=session)

        assert voucher.is_balanced_from_lines() is True


# ─── 借贷平衡前置校验 ──────────────────────────────────────────────


class TestEventIdRequiresEventType:
    """[BLOCKER-B3]: event_id 非空时 event_type 必填 (幂等键完整性)."""

    @pytest.mark.asyncio
    async def test_event_id_without_event_type_rejected(self):
        """event_id 非空但 event_type=None → ValueError, 不调 DB."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_NO_ETYPE",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            event_type=None,           # 未填
            event_id=uuid.uuid4(),     # 但 event_id 非空
            lines=[
                VoucherLineInput(account_code="1001", account_name="现金",
                                 debit_fen=10000),
                VoucherLineInput(account_code="6001", account_name="收入",
                                 credit_fen=10000),
            ],
        )
        with pytest.raises(ValueError, match="event_id 非空时 event_type 必填"):
            await svc.create(payload, session=session)

        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_id_with_empty_event_type_rejected(self):
        """event_type='' 或纯空白同样拒 (strip 后空)."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_BLANK_ETYPE",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            event_type="   ",          # 纯空白
            event_id=uuid.uuid4(),
            lines=[
                VoucherLineInput(account_code="1001", debit_fen=10000,
                                 account_name="现金"),
                VoucherLineInput(account_code="6001", credit_fen=10000,
                                 account_name="收入"),
            ],
        )
        with pytest.raises(ValueError, match="event_id 非空时 event_type 必填"):
            await svc.create(payload, session=session)

    @pytest.mark.asyncio
    async def test_event_id_none_with_event_type_ok(self):
        """event_id=None 时 event_type 任何值都可 (手工凭证场景)."""
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_MANUAL_OK",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            event_type=None,
            event_id=None,
            lines=[
                VoucherLineInput(account_code="1001", debit_fen=10000,
                                 account_name="现金"),
                VoucherLineInput(account_code="6001", credit_fen=10000,
                                 account_name="收入"),
            ],
        )
        result = await svc.create(payload, session=session)
        assert isinstance(result, FinancialVoucher)


class TestBalanceValidation:
    """借贷不平衡在 service 层前置拦截 (比 DB CHECK 更早, UX 更好)."""

    @pytest.mark.asyncio
    async def test_unbalanced_payload_rejected_before_db(self):
        """借 ¥100 贷 ¥99 → ValueError, 不调用 session."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_UNBAL",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            lines=[
                VoucherLineInput(account_code="1122", account_name="应收",
                                 debit_fen=10000),
                VoucherLineInput(account_code="6001", account_name="收入",
                                 credit_fen=9900),  # 少 1 分!
            ],
        )

        with pytest.raises(ValueError, match="借贷不平衡.*fen 整数零容忍"):
            await svc.create(payload, session=session)

        session.add.assert_not_called()
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_lines_rejected(self):
        """无分录 → ValueError."""
        svc = FinancialVoucherService()
        session = AsyncMock()

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_EMPTY",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            lines=[],
        )

        with pytest.raises(ValueError, match="至少一条分录"):
            await svc.create(payload, session=session)

    @pytest.mark.asyncio
    async def test_zero_total_rejected(self):
        """借贷都为 0 (尽管 dataclass 已防, 双保险) → ValueError.

        场景: 如果 lines 被绕过 dataclass 校验 (e.g. 测试桩)
        service 层仍然拦.
        """
        svc = FinancialVoucherService()
        session = AsyncMock()

        # 绕过 dataclass 校验构造 0/0 lines (用 object.__setattr__)
        # 正常用户不会这么做, 但防御编程.
        bad_line = VoucherLineInput(
            account_code="1001", account_name="现金", debit_fen=100,
        )
        object.__setattr__(bad_line, "debit_fen", 0)  # 强制置 0

        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_ZERO",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            lines=[bad_line],
        )

        with pytest.raises(ValueError, match="借贷总额均为 0"):
            await svc.create(payload, session=session)


# ─── 作废状态机 ────────────────────────────────────────────────────


class TestVoidViaService:
    """service.void() 转发到 ORM void() — 审计留痕 + 状态机守护."""

    @pytest.mark.asyncio
    async def test_void_draft_voucher(self):
        """draft 凭证 void → 设审计 4 字段 + flush."""
        svc = FinancialVoucherService()

        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_DRAFT_001",
            voucher_type="sales",
            status="draft",
            entries=[],
            voided=False,
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=voucher)
        session.flush = AsyncMock()

        operator = uuid.uuid4()
        result = await svc.void(
            voucher.id,
            operator_id=operator,
            reason="重复扫码",
            session=session,
        )

        assert result.voided is True
        assert result.voided_by == operator
        assert result.voided_reason == "重复扫码"
        assert result.voided_at is not None
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_void_nonexistent_voucher_raises(self):
        svc = FinancialVoucherService()
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="凭证不存在"):
            await svc.void(
                uuid.uuid4(),
                operator_id=uuid.uuid4(),
                reason="test",
                session=session,
            )

    @pytest.mark.asyncio
    async def test_void_exported_voucher_rejected(self):
        """exported 凭证禁止 void, 引导红冲."""
        svc = FinancialVoucherService()

        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_EXPORTED",
            voucher_type="sales",
            status="exported",
            entries=[],
            voided=False,
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=voucher)

        with pytest.raises(ValueError, match=r"红冲|red_flush"):
            await svc.void(
                voucher.id,
                operator_id=uuid.uuid4(),
                reason="纠错",
                session=session,
            )

    @pytest.mark.asyncio
    async def test_void_accepts_custom_timestamp(self):
        """支持传入历史时间戳 (补录场景)."""
        svc = FinancialVoucherService()

        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_RETRO",
            voucher_type="sales",
            status="draft",
            entries=[],
            voided=False,
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=voucher)
        session.flush = AsyncMock()

        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = await svc.void(
            voucher.id,
            operator_id=uuid.uuid4(),
            reason="历史补录",
            session=session,
            voided_at=t,
        )

        assert result.voided_at == t


# ─── 幂等查询 get_by_event ──────────────────────────────────────────


class TestGetByEvent:
    """调用方预检查 (e.g. 不确定是否已处理过事件时)."""

    @pytest.mark.asyncio
    async def test_get_by_event_returns_existing(self):
        svc = FinancialVoucherService()

        existing = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_BY_EVENT",
            voucher_type="sales",
            entries=[],
            voided=False,
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_by_event(
            tenant_id=uuid.uuid4(),
            event_type="order.paid",
            event_id=uuid.uuid4(),
            session=session,
        )
        assert result is existing

    @pytest.mark.asyncio
    async def test_get_by_event_returns_none_when_missing(self):
        svc = FinancialVoucherService()

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_by_event(
            tenant_id=uuid.uuid4(),
            event_type="order.paid",
            event_id=uuid.uuid4(),
            session=session,
        )
        assert result is None


# ─── Module-level asyncio marker ───────────────────────────────────


# tx-finance 的 pytest-asyncio mode=auto (pyproject.toml), 所以 @pytest.mark.asyncio
# 技术上不必要, 但显式标注为 readability (审查时一眼看出异步测试).
