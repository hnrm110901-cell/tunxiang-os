"""Tier 1 测试: VoucherGenerator.persist_to_db / persist_and_push (W1.7)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期链路

测试边界:
  场景 1. ERPVoucher pydantic → VoucherCreateInput 字段转换 (voucher_type 中英映射)
  场景 2. persist_to_db: 写 financial_vouchers + lines (via FinancialVoucherService)
  场景 3. 幂等 event_id 传入: 重复 persist 返回同一凭证
  场景 4. persist_and_push 成功路径: push 成功 → status='exported' + exported_at
  场景 5. persist_and_push 失败路径: push failed → status 仍为 draft
  场景 6. source_id 非 UUID 字符串: 置 None 防 UUID() 报错
  场景 7. 账期校验: 注入 period_service, closed 月 ERPVoucher → ValueError

运行:
  pytest src/tests/test_voucher_generator_persist_tier1.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# shared.adapters.erp 走 repo root sys.path
sys.path.insert(0, "/Users/lichun/Documents/GitHub/zhilian-os")

from shared.adapters.erp.src.base import (  # type: ignore  # noqa: E402
    ERPPushResult,
    ERPType,
    ERPVoucher,
    ERPVoucherEntry,
    PushStatus,
    VoucherType,
)
from services.voucher_generator import VoucherGenerator  # type: ignore  # noqa: E402
from services.financial_voucher_service import (  # type: ignore  # noqa: E402
    FinancialVoucherService,
)


# ─── 构造辅助 ───────────────────────────────────────────────────────


def _build_erp_voucher(
    voucher_type: VoucherType = VoucherType.RECEIPT,
    source_type: str = "daily_revenue",
    source_id: str | None = None,
    tenant_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
) -> ERPVoucher:
    return ERPVoucher(
        voucher_type=voucher_type,
        business_date=date(2026, 4, 19),
        entries=[
            ERPVoucherEntry(
                account_code="1001", account_name="现金",
                debit_fen=10000, summary="堂食现金",
            ),
            ERPVoucherEntry(
                account_code="6001", account_name="主营业务收入",
                credit_fen=10000, summary="营业收入",
            ),
        ],
        source_type=source_type,
        source_id=source_id or str(uuid.uuid4()),
        tenant_id=str(tenant_id or uuid.uuid4()),
        store_id=str(store_id or uuid.uuid4()),
        memo="日收入凭证 86.00 元",
    )


# ─── VoucherType 中英映射 ──────────────────────────────────────────


class TestVoucherTypeMapping:
    """_VOUCHER_TYPE_ERP_TO_DB: 中文 ERP → 英文 DB."""

    def test_receipt_maps_to_receipt(self):
        from services.voucher_generator import _VOUCHER_TYPE_ERP_TO_DB
        assert _VOUCHER_TYPE_ERP_TO_DB["收"] == "receipt"

    def test_payment_maps_to_payment(self):
        from services.voucher_generator import _VOUCHER_TYPE_ERP_TO_DB
        assert _VOUCHER_TYPE_ERP_TO_DB["付"] == "payment"

    def test_memo_maps_to_cost(self):
        from services.voucher_generator import _VOUCHER_TYPE_ERP_TO_DB
        assert _VOUCHER_TYPE_ERP_TO_DB["记"] == "cost"

    def test_transfer_maps_to_cost(self):
        from services.voucher_generator import _VOUCHER_TYPE_ERP_TO_DB
        assert _VOUCHER_TYPE_ERP_TO_DB["转"] == "cost"


# ─── persist_to_db: 字段转换 + 持久化 ────────────────────────────


class TestPersistToDb:
    @pytest.mark.asyncio
    async def test_persist_to_db_transforms_fields(self):
        """ERPVoucher → VoucherCreateInput 字段转换完整."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        tenant = uuid.uuid4()
        store = uuid.uuid4()
        erp = _build_erp_voucher(
            voucher_type=VoucherType.RECEIPT,
            tenant_id=tenant,
            store_id=store,
        )

        session = AsyncMock()
        session.flush = AsyncMock()

        result = await gen.persist_to_db(
            erp,
            voucher_service=voucher_svc,
            session=session,
        )

        # tenant_id / store_id 转 UUID
        assert result.tenant_id == tenant
        assert result.store_id == store
        # voucher_type 中 → 英
        assert result.voucher_type == "receipt"
        # 金额 fen 保持
        assert result.total_amount_fen == 10000
        # lines 2 行
        assert len(result.lines) == 2
        assert result.lines[0].debit_fen == 10000
        assert result.lines[1].credit_fen == 10000

    @pytest.mark.asyncio
    async def test_persist_to_db_voucher_no_auto_default(self):
        """voucher_no 未传时默认 AUTO_{voucher_id[:8]}."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        session.flush = AsyncMock()

        result = await gen.persist_to_db(
            erp, voucher_service=voucher_svc, session=session,
        )
        assert result.voucher_no.startswith("AUTO_")
        assert len(result.voucher_no) == len("AUTO_") + 8  # 8 位 hex 前缀

    @pytest.mark.asyncio
    async def test_persist_to_db_custom_voucher_no(self):
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        session.flush = AsyncMock()

        result = await gen.persist_to_db(
            erp, voucher_service=voucher_svc, session=session,
            voucher_no="V_XJ_20260419_001",
        )
        assert result.voucher_no == "V_XJ_20260419_001"

    @pytest.mark.asyncio
    async def test_persist_to_db_non_uuid_source_id_becomes_none(self):
        """source_id='S001_2026-04-19' (非 UUID 字符串) → None 不爆."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher(source_id="S001_2026-04-19")
        session = AsyncMock()
        session.flush = AsyncMock()

        result = await gen.persist_to_db(
            erp, voucher_service=voucher_svc, session=session,
        )
        assert result.source_id is None

    @pytest.mark.asyncio
    async def test_persist_to_db_idempotency_with_event_id(self):
        """同 event_id 二次调用 → 返回同一凭证 (走 FinancialVoucherService 幂等)."""
        from models.voucher import FinancialVoucher  # type: ignore

        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        existing = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_EXISTING",
            voucher_type="receipt",
            entries=[],
            voided=False,
        )

        # FinancialVoucherService._find_by_event 命中 → 直接返 existing
        session = AsyncMock()
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=mock_hit)

        erp = _build_erp_voucher()
        event_id = uuid.uuid4()

        result = await gen.persist_to_db(
            erp, voucher_service=voucher_svc, session=session,
            event_type="daily_revenue", event_id=event_id,
        )
        # 命中: 不 add, 不 flush
        assert result is existing
        session.add.assert_not_called()


# ─── persist_and_push 端到端编排 ─────────────────────────────────


class TestRecordPushResultNoCommit:
    """[BLOCKER-B1]: _record_push_result 不能调 db.commit() 破坏事务边界."""

    @pytest.mark.asyncio
    async def test_record_push_result_does_not_commit(self):
        """直接调 _record_push_result 不应触发 session.commit().

        原 bug: 内部 db.commit() 把调用方事务提前提交, 后续 persist_and_push
        的 "改 status=exported" flush 失败时造成 DB/ERP 永久分裂.
        """
        gen = VoucherGenerator()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()

        erp = _build_erp_voucher()
        result = ERPPushResult(
            voucher_id=erp.voucher_id,
            status=PushStatus.SUCCESS,
            erp_type=ERPType.KINGDEE,
            erp_voucher_id="kingdee_001",
            pushed_at=datetime.now(timezone.utc),
        )

        await gen._record_push_result(erp, result, session)

        # 铁律: _record_push_result 不调 commit (破坏事务边界)
        session.commit.assert_not_called()
        # 应改为 flush (保原子性, 事务边界交还调用方)
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_source_code_does_not_contain_db_commit_in_record_push(self):
        """静态验证: voucher_generator.py 中 _record_push_result 函数体无 db.commit() 调用.

        防回归: 防止后续重构误加回去.
        只检实际 await 调用, 注释里提到 "db.commit" 不算.
        """
        import inspect as _inspect
        import re as _re

        from services.voucher_generator import VoucherGenerator as _VG  # type: ignore

        source = _inspect.getsource(_VG._record_push_result)
        # 去掉 # 开头的注释行 (Python 行注释)
        code_only_lines = [
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        ]
        code_only = "\n".join(code_only_lines)

        # 检查: 实际调用 (await db.commit() / await session.commit() 等)
        assert not _re.search(
            r"await\s+(?:db|session)\.commit\s*\(", code_only
        ), "_record_push_result 代码体不应 await db.commit() (破坏事务边界)"

        # 应改为 flush
        assert _re.search(
            r"await\s+(?:db|session)\.flush\s*\(", code_only
        ), "_record_push_result 应用 await db.flush() 替代 commit"


class TestPersistAndPush:
    @pytest.mark.asyncio
    async def test_persist_and_push_success_path_marks_exported(self):
        """推 ERP 成功 → status='exported' + exported_at 非空."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        # mock push_to_erp 成功
        gen.push_to_erp = AsyncMock(return_value=ERPPushResult(
            voucher_id=erp.voucher_id,
            status=PushStatus.SUCCESS,
            erp_type=ERPType.KINGDEE,
            erp_voucher_id="kingdee_001",
            pushed_at=datetime.now(timezone.utc),
        ))

        financial_voucher, push_result = await gen.persist_and_push(
            erp,
            voucher_service=voucher_svc,
            erp_type="kingdee",
            session=session,
        )

        assert financial_voucher.status == "exported"
        assert financial_voucher.exported_at is not None
        assert push_result.status == PushStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_persist_and_push_failure_keeps_draft(self):
        """推 ERP 失败 → status 仍 draft, 已记 erp_push_log."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        session.flush = AsyncMock()

        gen.push_to_erp = AsyncMock(return_value=ERPPushResult(
            voucher_id=erp.voucher_id,
            status=PushStatus.FAILED,
            erp_type=ERPType.KINGDEE,
            error_message="HTTP timeout",
            pushed_at=datetime.now(timezone.utc),
        ))

        financial_voucher, push_result = await gen.persist_and_push(
            erp,
            voucher_service=voucher_svc,
            erp_type="kingdee",
            session=session,
        )

        # status 没改 (默认 draft)
        assert financial_voucher.status == "draft"
        assert financial_voucher.exported_at is None
        assert push_result.status == PushStatus.FAILED

    @pytest.mark.asyncio
    async def test_persist_and_push_queued_treats_as_not_exported(self):
        """推 QUEUED (用友离线) → status 仍 draft, 待后续 drain 再标 exported."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        session.flush = AsyncMock()

        gen.push_to_erp = AsyncMock(return_value=ERPPushResult(
            voucher_id=erp.voucher_id,
            status=PushStatus.QUEUED,
            erp_type=ERPType.YONYOU,
            pushed_at=datetime.now(timezone.utc),
        ))

        financial_voucher, push_result = await gen.persist_and_push(
            erp,
            voucher_service=voucher_svc,
            erp_type="yonyou",
            session=session,
        )

        assert financial_voucher.status == "draft"
        assert push_result.status == PushStatus.QUEUED

    @pytest.mark.asyncio
    async def test_persist_and_push_order_persist_first_then_push(self):
        """顺序: 先 persist_to_db (DB), 再 push_to_erp. 若 DB 失败则 ERP 不推."""
        gen = VoucherGenerator()
        voucher_svc = FinancialVoucherService()

        erp = _build_erp_voucher()
        session = AsyncMock()
        # 让 persist 阶段爆 (模拟借贷不平衡等)
        voucher_svc.create = AsyncMock(side_effect=ValueError("模拟 DB 持久化失败"))
        gen.push_to_erp = AsyncMock()

        with pytest.raises(ValueError, match="模拟 DB 持久化失败"):
            await gen.persist_and_push(
                erp, voucher_service=voucher_svc,
                erp_type="kingdee", session=session,
            )

        # DB 失败 → ERP 推送未被调用
        gen.push_to_erp.assert_not_called()


# ─── 与 FinancialVoucherService 账期校验的集成 ───────────────────


class TestPersistRespectsPeriodCheck:
    """persist_to_db 继承 FinancialVoucherService 的账期校验."""

    @pytest.mark.asyncio
    async def test_persist_rejects_when_period_closed(self):
        """注入 period_service, closed 月 → persist 拒."""
        from unittest.mock import AsyncMock as AM
        from services.accounting_period_service import AccountingPeriodService
        from models.accounting_period import AccountingPeriod, STATUS_CLOSED

        period_svc = AM(spec=AccountingPeriodService)
        period_svc.is_date_writable = AM(return_value=False)
        period_svc.find_period_for_date = AM(return_value=AccountingPeriod(
            id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            period_year=2026, period_month=4,
            period_start=date(2026, 4, 1), period_end=date(2026, 4, 30),
            status=STATUS_CLOSED,
        ))

        voucher_svc = FinancialVoucherService(period_service=period_svc)
        gen = VoucherGenerator()

        erp = _build_erp_voucher()
        session = AsyncMock()

        with pytest.raises(ValueError, match="账期.*closed"):
            await gen.persist_to_db(
                erp, voucher_service=voucher_svc, session=session,
            )


# ─── _looks_like_uuid 辅助 ──────────────────────────────────────


class TestLooksLikeUuid:
    def test_valid_uuid_string(self):
        assert VoucherGenerator._looks_like_uuid(str(uuid.uuid4())) is True

    def test_non_uuid_string(self):
        assert VoucherGenerator._looks_like_uuid("S001_2026-04-19") is False

    def test_empty_string(self):
        assert VoucherGenerator._looks_like_uuid("") is False

    def test_random_hex(self):
        """纯 hex 可能被 uuid 解析 (32 位 hex = valid UUID)."""
        # 32 位 hex → uuid.UUID 接受
        assert VoucherGenerator._looks_like_uuid("a" * 32) is True
        # 31 位 → 不行
        assert VoucherGenerator._looks_like_uuid("a" * 31) is False
