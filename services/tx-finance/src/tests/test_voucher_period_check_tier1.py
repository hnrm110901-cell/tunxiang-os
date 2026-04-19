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
    async def test_period_check_runs_after_idempotency_miss(self):
        """[W2.B 顺序反转] 原名 test_period_check_rejects_before_idempotency_fetch.

        W1.4b 当时的断言: "账期 closed 时幂等预查不执行" (账期先于幂等).
        W2.B 修复后反转: event_id 非空必须先走幂等预查.
          - 命中: 返回既存凭证 (外卖 T+N webhook 不丢单)
          - miss: 继续账期校验, 新凭证写 closed 期仍拒

        本测试验证 miss 路径: ValueError + 幂等预查确实跑了 + 账期校验也跑了.
        命中路径由 TestW2BIdempotencyBeforePeriodCheck (下方) 覆盖.
        """
        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(status=STATUS_CLOSED)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()

        # 2 次 execute: B5 tenant 断言豁免 + 幂等预查 miss → 继续走 period_service 账期校验
        tenant_mock = MagicMock()
        tenant_mock.scalar = MagicMock(return_value=None)
        idempotency_miss = MagicMock()
        idempotency_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(side_effect=[tenant_mock, idempotency_miss])

        payload = _balanced_payload(event_id=uuid.uuid4())  # 有 event_id 但 miss

        with pytest.raises(ValueError, match="账期"):
            await svc.create(payload, session=session)

        # 幂等预查 miss (2 次 execute: tenant 断言 + _find_by_event)
        assert session.execute.await_count == 2
        # 账期校验走到了 (miss 后继续执行)
        period_service.is_date_writable.assert_awaited_once()

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


# ─── W2.B: 幂等预查优先于账期校验 ─────────────────────────────────────
#
# 业务背景 (徐记海鲜 × 美团外卖):
#   4/30 下单 → 5/2 美团 T+2 到账 webhook. 如果 2026-04 已月结 (closed),
#   原 W1 代码先走账期校验直接 raise, 外卖流水年化百万级丢单.
#
# W2.B 修复: event_id 非空时先做幂等预查.
#   - 命中 (该凭证在 open 期已写入): 返回既存凭证, 跳过账期校验 ✅
#   - miss  (全新 event_id):         继续账期校验, closed 仍拒 ✅
#   - event_id=None (手工凭证):      跳过幂等, 直接账期校验, closed 仍拒 ✅


def _meituan_payload(
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    voucher_date: date,
    voucher_no: str = "V_MT_TEST",
) -> VoucherCreateInput:
    """美团外卖 T+N webhook 场景凭证 — event_type='order.paid' 明确业务语义."""
    return VoucherCreateInput(
        tenant_id=tenant_id,
        store_id=uuid.uuid4(),
        voucher_no=voucher_no,
        voucher_date=voucher_date,
        voucher_type="sales",
        event_type="order.paid",
        event_id=event_id,
        lines=[
            VoucherLineInput(account_code="1002", account_name="美团代收款",
                             debit_fen=8800),
            VoucherLineInput(account_code="6001", account_name="外卖收入",
                             credit_fen=8800),
        ],
    )


def _b5_exempt_execute() -> MagicMock:
    """B5 tenant 断言豁免: execute 返回 scalar()=None (视为特权路径, 跳过断言)."""
    r = MagicMock()
    r.scalar = MagicMock(return_value=None)
    return r


def _idempotent_hit_execute(existing: FinancialVoucher) -> MagicMock:
    """幂等命中: execute 返回 scalar_one_or_none()=existing (已处理过本 event_id)."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=existing)
    return r


def _idempotent_miss_execute() -> MagicMock:
    """幂等 miss: execute 返回 scalar_one_or_none()=None (首次处理)."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=None)
    return r


def _existing_voucher(tenant_id: uuid.UUID) -> FinancialVoucher:
    """模拟 4/30 在 open 期已成功写入的外卖凭证."""
    return FinancialVoucher(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        voucher_no="V_MT_20260430_001",
        voucher_type="sales",
        status="confirmed",
        entries=[],
        voided=False,
    )


class TestW2BIdempotencyBeforePeriodCheck:
    """W2.B: 幂等预查在账期校验之前 — 外卖 T+N webhook 月结后不再丢单.

    场景全部基于徐记海鲜 × 美团外卖真实业务路径.
    每个测试独立, 不依赖执行顺序.
    """

    # ── 场景 1: 美团 webhook 重发, 账期已关, 命中幂等返回既存凭证 ──────

    @pytest.mark.asyncio
    async def test_webhook_retry_in_closed_period_returns_existing_voucher(self):
        """4/30 外卖凭证已写入, 5/2 美团重发 webhook 时账期 2026-04 已 closed.
        幂等命中 → 返回既存凭证, is_date_writable 从未被调用."""
        tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        event_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        existing = _existing_voucher(tenant_id)

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(
            side_effect=AssertionError("账期校验不应被调用 — 幂等命中应提前 return")
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        # B5 execute → 豁免; _find_by_event execute → 命中
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_hit_execute(existing),
        ])

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 4, 30),
        )
        result = await svc.create(payload, session=session)

        assert result is existing
        period_service.is_date_writable.assert_not_called()
        session.add.assert_not_called()
        session.flush.assert_not_called()

    # ── 场景 2: 全新 event_id + 账期 closed → 账期保护仍然生效 ─────────

    @pytest.mark.asyncio
    async def test_new_event_id_in_closed_period_still_rejected(self):
        """全新 event_id (幂等 miss), voucher_date 在已 closed 的 2026-04.
        账期保护仍然生效 — ValueError '账期 2026-04 状态=closed'."""
        tenant_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        event_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(year=2026, month=4, status=STATUS_CLOSED,
                                 tenant_id=tenant_id)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        # B5 豁免; _find_by_event miss (全新 event_id)
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_miss_execute(),
        ])

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 4, 30),
        )

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        msg = str(exc_info.value)
        assert "2026-04" in msg
        assert "closed" in msg
        session.add.assert_not_called()

    # ── 场景 3: event_id=None 手工凭证 + closed → 幂等 skip, 账期拒 ──

    @pytest.mark.asyncio
    async def test_manual_voucher_event_id_none_in_closed_period_rejected(self):
        """手工凭证 event_id=None, 账期 closed.
        跳过幂等预查, 直接走账期校验, ValueError."""
        tenant_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(year=2026, month=4, status=STATUS_CLOSED,
                                 tenant_id=tenant_id)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        # event_id=None: 只有 B5 的 1 次 execute, 不走幂等预查
        session.execute = AsyncMock(return_value=_b5_exempt_execute())

        payload = VoucherCreateInput(
            tenant_id=tenant_id,
            store_id=uuid.uuid4(),
            voucher_no="V_MANUAL_001",
            voucher_date=date(2026, 4, 15),
            voucher_type="cost",
            event_type=None,
            event_id=None,  # 手工凭证
            lines=[
                VoucherLineInput(account_code="5401", account_name="原材料成本",
                                 debit_fen=50000),
                VoucherLineInput(account_code="1001", account_name="现金",
                                 credit_fen=50000),
            ],
        )

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        assert "2026-04" in str(exc_info.value)
        # execute 只调 1 次 (B5), 没有第 2 次幂等预查
        assert session.execute.await_count == 1

    # ── 场景 4: 账期 open + event_id 命中 → 正常幂等 (W2.B 排序下验证) ──

    @pytest.mark.asyncio
    async def test_webhook_retry_in_open_period_returns_existing(self):
        """账期 open + event_id 命中 — W2.B 排序变化后, 正常幂等路径仍然正确."""
        tenant_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        event_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
        existing = _existing_voucher(tenant_id)

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(
            side_effect=AssertionError("幂等命中不应走账期校验")
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_hit_execute(existing),
        ])

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 5, 2),
        )
        result = await svc.create(payload, session=session)

        assert result is existing
        period_service.is_date_writable.assert_not_called()

    # ── 场景 5: 账期 locked (年结) + webhook 重发 → 幂等命中返回既存 ──

    @pytest.mark.asyncio
    async def test_webhook_retry_in_locked_period_also_returns_existing(self):
        """账期 2026-12 年结 locked, 历史外卖凭证 webhook 重发.
        幂等命中 → 返回既存, 年结后历史凭证不因重发变'账面新增'."""
        tenant_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
        event_id = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
        existing = _existing_voucher(tenant_id)

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(
            side_effect=AssertionError("年结 locked, 幂等命中不应走账期校验")
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_hit_execute(existing),
        ])

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 12, 30),
        )
        result = await svc.create(payload, session=session)

        assert result is existing
        period_service.is_date_writable.assert_not_called()

    # ── 场景 6: 调用顺序验证 — execute 在 is_date_writable 之前 ─────────

    @pytest.mark.asyncio
    async def test_idempotency_check_uses_execute_before_period_service(self):
        """验证调用顺序: session.execute (幂等预查) 在 is_date_writable 之前.
        通过 call_order 列表验证因果顺序."""
        tenant_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
        event_id = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

        call_order: list[str] = []

        async def _execute_spy(stmt):
            call_order.append("execute")
            r = MagicMock()
            # 第 1 次: B5 豁免; 第 2 次: 幂等 miss → 继续走账期校验
            if len(call_order) == 1:
                r.scalar = MagicMock(return_value=None)
            else:
                r.scalar_one_or_none = MagicMock(return_value=None)
            return r

        async def _is_date_writable_spy(**_kwargs):
            call_order.append("is_date_writable")
            return True

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(
            side_effect=_is_date_writable_spy
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=_execute_spy)
        session.flush = AsyncMock()

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 5, 15),
        )
        await svc.create(payload, session=session)

        # execute 调 2 次 (B5 + 幂等预查), 两次均在 is_date_writable 之前
        execute_indices = [i for i, v in enumerate(call_order) if v == "execute"]
        writable_indices = [i for i, v in enumerate(call_order) if v == "is_date_writable"]
        assert execute_indices, "execute 应被调用"
        assert writable_indices, "is_date_writable 应被调用 (幂等 miss 路径)"
        assert max(execute_indices) < min(writable_indices), (
            f"幂等预查 execute 应在账期校验之前, 实际调用顺序: {call_order}"
        )

    # ── 场景 7: event_id miss + 账期 open → INSERT 路径全走到 ─────────

    @pytest.mark.asyncio
    async def test_new_event_id_miss_then_open_period_succeeds(self):
        """全新 event_id + 账期 open → 幂等 miss → 账期通过 → INSERT 成功.
        验证: is_date_writable 调用, session.add 调用, session.flush 调用."""
        tenant_id = uuid.UUID("77777777-7777-7777-7777-777777777777")
        event_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=True)

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_miss_execute(),
        ])
        session.flush = AsyncMock()

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 5, 2),
        )
        result = await svc.create(payload, session=session)

        period_service.is_date_writable.assert_awaited_once()
        assert period_service.is_date_writable.call_args.kwargs["auto_ensure"] is True
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert isinstance(result, FinancialVoucher)

    # ── 场景 8: event_id miss + closed → ValueError, DB 不写入 ──────────

    @pytest.mark.asyncio
    async def test_event_id_miss_and_period_closed_rejects_without_db_write(self):
        """event_id miss (全新凭证) + 账期 closed → ValueError, session.add 从不调用.
        fail-fast: 账期拒绝后不执行任何 DB 写入操作."""
        tenant_id = uuid.UUID("88888888-8888-8888-8888-888888888888")
        event_id = uuid.UUID("12345678-1234-1234-1234-123456789012")

        period_service = AsyncMock(spec=AccountingPeriodService)
        period_service.is_date_writable = AsyncMock(return_value=False)
        period_service.find_period_for_date = AsyncMock(
            return_value=_period(year=2026, month=4, status=STATUS_CLOSED,
                                 tenant_id=tenant_id)
        )

        svc = FinancialVoucherService(period_service=period_service)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[
            _b5_exempt_execute(),
            _idempotent_miss_execute(),
        ])

        payload = _meituan_payload(
            tenant_id=tenant_id,
            event_id=event_id,
            voucher_date=date(2026, 4, 28),
            voucher_no="V_MT_NEW_CLOSED",
        )

        with pytest.raises(ValueError) as exc_info:
            await svc.create(payload, session=session)

        assert "closed" in str(exc_info.value)
        session.add.assert_not_called()
        session.flush.assert_not_called()
