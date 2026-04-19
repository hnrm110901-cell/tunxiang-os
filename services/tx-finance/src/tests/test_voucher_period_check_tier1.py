"""Tier 1 测试: FinancialVoucherService + AccountingPeriodService 集成 (W1.4b)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期审计红线

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. 默认构造 (不传 period_service): 写凭证不做账期校验 (向前兼容 W1.4 前)
  场景 2. 注入 period_service, 账期 open: 写凭证成功
  场景 3. 注入 period_service, 账期 closed: ValueError, 错误消息引导红冲
  场景 4. 注入 period_service, 账期 locked: ValueError, 年结锁定不可写
  场景 5. 注入 period_service, 账期不存在: auto_ensure 懒建 open, 写凭证成功
  场景 6. 账期校验失败时, 幂等预查不执行 (成本控制 + 防撞 session)
  场景 7. 账期校验发生在借贷平衡之后 (失败快路径: 非 DB 错误先出)

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_voucher_period_check_tier1.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher  # type: ignore  # noqa: E402
from models.accounting_period import (  # type: ignore  # noqa: E402
    STATUS_CLOSED,
    STATUS_LOCKED,
    STATUS_OPEN,
    AccountingPeriod,
    month_range,
)
from services.accounting_period_service import (  # type: ignore  # noqa: E402
    AccountingPeriodService,
)
from services.financial_voucher_service import (  # type: ignore  # noqa: E402
    FinancialVoucherService,
    VoucherCreateInput,
    VoucherLineInput,
)


# ─── 构造辅助 ───────────────────────────────────────────────────────


def _balanced_payload(
    tenant_id: uuid.UUID | None = None,
    voucher_date: date | None = None,
    voucher_no: str = "V_TEST",
    event_id: uuid.UUID | None = None,
) -> VoucherCreateInput:
    return VoucherCreateInput(
        tenant_id=tenant_id or uuid.uuid4(),
        store_id=uuid.uuid4(),
        voucher_no=voucher_no,
        voucher_date=voucher_date or date(2026, 4, 19),
        voucher_type="sales",
        event_type="daily_settlement.closed" if event_id else None,
        event_id=event_id,
        lines=[
            VoucherLineInput(account_code="1001", account_name="现金",
                             debit_fen=10000),
            VoucherLineInput(account_code="6001", account_name="主营业务收入",
                             credit_fen=10000),
        ],
    )


def _period(year: int = 2026, month: int = 4, status: str = STATUS_OPEN,
            tenant_id: uuid.UUID | None = None) -> AccountingPeriod:
    start, end = month_range(year, month)
    return AccountingPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        period_year=year,
        period_month=month,
        period_start=start,
        period_end=end,
        status=status,
    )


# ─── 场景 #1: 不注入 period_service, W1.3 行为保留 ──────────────────


class TestBackwardCompatibilityWithoutPeriodService:
    """向前兼容: 不传 period_service 时, W1.3 行为完全保留."""

    @pytest.mark.asyncio
    async def test_create_without_period_service_skips_period_check(self):
        """默认构造不校验账期 — W1.3 路径."""
        svc = FinancialVoucherService()  # 不传 period_service
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _balanced_payload(voucher_date=date(2026, 4, 19), event_id=None)
        result = await svc.create(payload, session=session)

        assert isinstance(result, FinancialVoucher)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()


# ─── 场景 #2-5: 注入 period_service 后的校验行为 ───────────────────


class TestWithPeriodServiceOpenPeriod:
    """账期 open: 写凭证成功."""

    @pytest.mark.asyncio
    async def test_create_succeeds_when_period_open(self):
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=True)

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _balanced_payload(event_id=None)
        result = await svc.create(payload, session=session)

        # 走了 is_date_writable 校验
        period_service.is_date_writable.assert_awaited_once()
        call_kwargs = period_service.is_date_writable.call_args.kwargs
        assert call_kwargs["tenant_id"] == payload.tenant_id
        assert call_kwargs["biz_date"] == payload.voucher_date
        assert call_kwargs["auto_ensure"] is True  # 关键: 懒建 open

        # 后续 add + flush 正常走
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert isinstance(result, FinancialVoucher)


class TestWithPeriodServiceClosedPeriod:
    """账期 closed: 拒绝写入, 错误消息引导红冲."""

    @pytest.mark.asyncio
    async def test_create_rejects_when_period_closed(self):
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(status=STATUS_CLOSED)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()

        payload = _balanced_payload(voucher_date=date(2026, 4, 19))

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        msg = str(exc_info.value)
        assert "2026-04" in msg
        assert "closed" in msg
        # 错误信息必须引导红冲路径
        assert "red_flush" in msg or "红冲" in msg

        # 不应调用 DB add/flush (账期校验是 fail-fast)
        session.add.assert_not_called()
        session.flush.assert_not_called()


class TestWithPeriodServiceLockedPeriod:
    """账期 locked (年结): 更严格拒绝."""

    @pytest.mark.asyncio
    async def test_create_rejects_when_period_locked(self):
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(status=STATUS_LOCKED)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()

        payload = _balanced_payload(voucher_date=date(2026, 4, 19))

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        msg = str(exc_info.value)
        assert "locked" in msg

    @pytest.mark.asyncio
    async def test_create_rejects_when_period_is_none_but_not_writable(self):
        """极端: is_date_writable=False 但 period 查不到 — 兜底 status='unknown'."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(return_value=None)

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()

        payload = _balanced_payload(voucher_date=date(2026, 4, 19))

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        assert "unknown" in str(exc_info.value)


class TestWithPeriodServiceAutoEnsure:
    """账期不存在 + auto_ensure=True: 懒建 open 写凭证成功."""

    @pytest.mark.asyncio
    async def test_create_triggers_auto_ensure_when_period_missing(self):
        """period_service.is_date_writable(auto_ensure=True) 应创建 open period."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        # 简化: is_date_writable 返 True 代表 auto_ensure 已完成
        period_service.is_date_writable = AsyncMock(return_value=True)

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.flush = AsyncMock()

        payload = _balanced_payload(voucher_date=date(2099, 1, 15))
        result = await svc.create(payload, session=session)

        period_service.is_date_writable.assert_awaited_once()
        # auto_ensure=True 由 FinancialVoucherService 固定传入, 不由 caller 控制
        assert period_service.is_date_writable.call_args.kwargs["auto_ensure"] is True
        assert isinstance(result, FinancialVoucher)


# ─── 场景 #6-7: 校验顺序 ─────────────────────────────────────────


class TestValidationOrder:
    """验证借贷平衡 → 账期校验 → 幂等预查 的顺序."""

    @pytest.mark.asyncio
    async def test_period_check_after_balance_but_before_idempotency(self):
        """借贷不平衡时, 账期校验不执行 (优先最便宜的失败路径)."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=True)

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()

        # 借贷不平衡 payload (绕过 dataclass 构造)
        payload = VoucherCreateInput(
            tenant_id=uuid.uuid4(),
            voucher_no="V_UNBAL",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            lines=[
                VoucherLineInput(account_code="1001", account_name="现金",
                                 debit_fen=10000),
                VoucherLineInput(account_code="6001", account_name="收入",
                                 credit_fen=9900),  # 少 1 分
            ],
        )

        with pytest.raises(ValueError, match="借贷不平衡"):
            await svc.create(payload, session=session)

        # 账期校验不应执行 (早失败)
        period_service.is_date_writable.assert_not_called()

    @pytest.mark.asyncio
    async def test_period_check_rejects_before_idempotency_fetch(self):
        """账期 closed 时, 即便有 event_id, 幂等预查 (DB SELECT) 也不执行."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(status=STATUS_CLOSED)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock()  # 幂等预查用

        payload = _balanced_payload(event_id=uuid.uuid4())  # 有 event_id

        with pytest.raises(ValueError, match="账期"):
            await svc.create(payload, session=session)

        # 账期 closed 直接 raise, execute (SELECT 幂等) 不调用
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_lines_rejected_before_period_check(self):
        """lines 空时, 账期校验不执行 (更便宜的校验先走)."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=True)

        svc = FinancialVoucherService(period_service=period_service)
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

        period_service.is_date_writable.assert_not_called()


# ─── void 路径不受账期校验影响 (void 即作废, 不是新写入) ──────────


class TestVoidNotAffectedByPeriodCheck:
    """作废是审计操作, 不写新分录, 不受账期状态影响."""

    @pytest.mark.asyncio
    async def test_void_works_even_with_period_service(self):
        """void() 不走 period 校验 — 误录的凭证应永远可以作废审计."""
        period_service = AsyncMock(spec=AccountingPeriodService)
        # 即便 is_date_writable 会 raise, void 路径不访问它
        period_service.is_date_writable = AsyncMock(
            side_effect=RuntimeError("不该被调用")
        )

        svc = FinancialVoucherService(period_service=period_service)

        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_TO_VOID",
            voucher_type="sales",
            status="draft",
            entries=[],
            voided=False,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=voucher)
        session.flush = AsyncMock()

        result = await svc.void(
            voucher.id,
            operator_id=uuid.uuid4(),
            reason="误录",
            session=session,
        )

        assert result.voided is True
        period_service.is_date_writable.assert_not_called()
