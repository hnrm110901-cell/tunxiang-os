"""test_saga_idempotency.py — Saga 编排器 + 幂等保护单元测试

测试策略：
  - PaymentSaga：Mock db session 和 channel，验证 execute 流程和补偿逻辑
  - IdempotencyGuard：Mock db session，验证 check/record 方法
  - 不涉及 HTTP，纯单元测试

mock_db 约定（来自 conftest.py）：
  - db.execute 为 async 函数，返回 MagicMock
  - 设 db._fetchone_result 控制 fetchone() 返回值
  - 设 db._fetchall_result 控制 fetchall() 返回值
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.channels.base import (
    BasePaymentChannel,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    TradeType,
)
from src.orchestrator.idempotency import IdempotencyGuard
from src.orchestrator.saga import PaymentSaga, SagaStep

# ─── 公共 fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_channel():
    """AsyncMock 模拟 BasePaymentChannel"""
    channel = AsyncMock(spec=BasePaymentChannel)
    channel.channel_name = "mock_channel"
    channel.pay = AsyncMock()
    channel.refund = AsyncMock()
    channel.query = AsyncMock()
    return channel


@pytest.fixture
def payment_request():
    """标准 PaymentRequest"""
    return PaymentRequest(
        tenant_id="00000000-0000-0000-0000-000000000001",
        store_id="store-001",
        order_id="order-saga-001",
        amount_fen=8800,
        method=PayMethod.WECHAT,
        trade_type=TradeType.B2C,
        idempotency_key="test-idem-key-001",
    )


# ─── Saga 编排器 ─────────────────────────────────────────────────────────────


class TestPaymentSaga:
    """PaymentSaga — 支付 Saga 执行与补偿"""

    @pytest.mark.asyncio
    async def test_saga_execute_success(self, mock_db, mock_channel, payment_request):
        """完整 Saga 成功完成：S1 validate → S2 execute → S3 confirm → DONE"""
        mock_channel.pay.return_value = PaymentResult(
            payment_id="pay_saga_001",
            status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT,
            amount_fen=8800,
            trade_no="txn_saga_001",
        )

        saga = PaymentSaga(mock_db, mock_channel)
        result = await saga.execute(payment_request)

        assert result.payment_id == "pay_saga_001"
        assert result.status == PayStatus.SUCCESS
        assert result.amount_fen == 8800

        # DB execute 应该被调用多次（S1/S2/S3 各一次）
        assert mock_db.execute.call_count >= 3

    @pytest.mark.asyncio
    async def test_saga_execute_with_on_success(self, mock_db, mock_channel, payment_request):
        """Saga 执行时 on_success 回调被正确调用"""
        mock_channel.pay.return_value = PaymentResult(
            payment_id="pay_saga_002",
            status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT,
            amount_fen=8800,
        )

        on_success_called = False

        async def on_success(result: PaymentResult) -> None:
            nonlocal on_success_called
            on_success_called = True
            assert result.payment_id == "pay_saga_002"

        saga = PaymentSaga(mock_db, mock_channel)
        await saga.execute(payment_request, on_success=on_success)

        assert on_success_called is True

    @pytest.mark.asyncio
    async def test_saga_rollback_on_channel_failure(self, mock_db, mock_channel, payment_request):
        """渠道 pay() 抛出异常 → Saga step = FAILED，不补偿"""
        mock_channel.pay.side_effect = ValueError("渠道扣款失败")

        saga = PaymentSaga(mock_db, mock_channel)
        with pytest.raises(ValueError, match="渠道扣款失败"):
            await saga.execute(payment_request)

        # 不应该调用 refund
        mock_channel.refund.assert_not_called()

    @pytest.mark.asyncio
    async def test_saga_rollback_on_channel_declined(self, mock_db, mock_channel, payment_request):
        """渠道返回 FAILED 状态（非异常）→ 直接返回 result，不补偿"""
        mock_channel.pay.return_value = PaymentResult(
            payment_id="pay_saga_fail_001",
            status=PayStatus.FAILED,
            method=PayMethod.WECHAT,
            amount_fen=8800,
            error_msg="余额不足",
        )

        saga = PaymentSaga(mock_db, mock_channel)
        result = await saga.execute(payment_request)

        assert result.status == PayStatus.FAILED
        assert result.error_msg == "余额不足"
        # 不应触发退款
        mock_channel.refund.assert_not_called()

    @pytest.mark.asyncio
    async def test_saga_compensate_on_confirm_failure(self, mock_db, mock_channel, payment_request):
        """S3 confirm 回调失败 → 补偿退款 → COMPENSATED"""
        mock_channel.pay.return_value = PaymentResult(
            payment_id="pay_saga_comp_001",
            status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT,
            amount_fen=8800,
        )
        mock_channel.refund.return_value = MagicMock()

        async def failing_callback(result):
            raise RuntimeError("业务方确认失败")

        saga = PaymentSaga(mock_db, mock_channel)
        with pytest.raises(RuntimeError, match="业务方确认失败"):
            await saga.execute(payment_request, on_success=failing_callback)

        # 应该调用 refund 进行补偿
        mock_channel.refund.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_saga_recover_stale(self, mock_db, mock_channel):
        """恢复挂起的 Saga（executing 步骤超时）→ 查询渠道确认"""
        mock_db._fetchall_result = [
            ("saga-stale-001", "order-stale-001", SagaStep.EXECUTING,
             "pay_stale_001", None, "wechat", 8800),
        ]
        mock_channel.query.return_value = PaymentResult(
            payment_id="pay_stale_001",
            status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT,
            amount_fen=8800,
        )

        saga = PaymentSaga(mock_db, mock_channel)
        recovered = await saga.recover_stale()

        assert recovered == 1
        mock_channel.query.assert_awaited_once_with("pay_stale_001", None)


# ─── 幂等保护 ─────────────────────────────────────────────────────────────────


class TestIdempotencyGuard:
    """IdempotencyGuard — 幂等键检查与记录"""

    @pytest.mark.asyncio
    async def test_check_new_key(self, mock_db):
        """新幂等键 → check 返回 None"""
        mock_db._fetchone_result = None

        guard = IdempotencyGuard(mock_db)
        result = await guard.check("new-key-001", "00000000-0000-0000-0000-000000000001")

        assert result is None

    @pytest.mark.asyncio
    async def test_check_existing_key(self, mock_db):
        """已存在的幂等键 → 返回支付结果 dict"""
        mock_db._fetchone_result = (
            "pay_existing_001",  # payment_id
            "success",           # status
            "txn_existing_001",  # trade_no
            8800,                # amount_fen
            {"mock": True},      # channel_data
        )

        guard = IdempotencyGuard(mock_db)
        result = await guard.check("existing-key-001", "00000000-0000-0000-0000-000000000001")

        assert result is not None
        assert result["payment_id"] == "pay_existing_001"
        assert result["status"] == "success"
        assert result["amount_fen"] == 8800

    @pytest.mark.asyncio
    async def test_record_success(self, mock_db):
        """记录幂等结果 → DB execute 被调用"""
        guard = IdempotencyGuard(mock_db)
        await guard.record(
            idempotency_key="record-key-001",
            tenant_id="00000000-0000-0000-0000-000000000001",
            payment_id="pay_record_001",
            status="success",
            trade_no="txn_record_001",
            amount_fen=8800,
        )

        # execute 被 await（mock_db.execute 是 async 函数）
        assert mock_db.execute.call_count >= 1
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_different_keys_allowed(self, mock_db):
        """不同幂等键可正常通过"""
        guard = IdempotencyGuard(mock_db)

        # 第一次：新键
        mock_db._fetchone_result = None
        r1 = await guard.check("key-a", "00000000-0000-0000-0000-000000000001")
        assert r1 is None

        # 第二次：也不同
        mock_db._fetchone_result = None
        r2 = await guard.check("key-b", "00000000-0000-0000-0000-000000000001")
        assert r2 is None

        # 第三次：已有记录
        mock_db._fetchone_result = (
            "pay_existing_001", "success", "txn_existing_001", 5000, {},
        )
        r3 = await guard.check("key-a", "00000000-0000-0000-0000-000000000001")
        assert r3 is not None
        assert r3["payment_id"] == "pay_existing_001"
