"""支付Saga编排器 — 分布式事务补偿

Saga 步骤：
  S1: validate — 校验订单/金额/幂等（无副作用）
  S2: execute  — 调用渠道 pay()（有副作用：扣款）
  S3: confirm  — 通知业务方支付成功（有副作用：变更订单状态）

补偿逻辑：
  S3 失败 → refund() 退款 → 标记 compensated
  S2 失败 → 无需补偿（未扣款）
  S1 失败 → 无需补偿

崩溃恢复：
  启动时扫描 step IN ('executing', 'confirming') 且 updated_at < now()-5min
  executing → 查询渠道确认是否已扣款 → 已扣则继续 S3 或补偿
  confirming → 重试 S3 → 失败则补偿
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import (
    BasePaymentChannel,
    PaymentRequest,
    PaymentResult,
    PayStatus,
)

logger = structlog.get_logger(__name__)

# 挂起 Saga 超时（分钟）
_PENDING_TIMEOUT_MINUTES = 5


class SagaStep:
    VALIDATING = "validating"
    EXECUTING = "executing"
    CONFIRMING = "confirming"
    DONE = "done"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class PaymentSaga:
    """支付Saga编排器

    使用方式：
        saga = PaymentSaga(db, channel)
        result = await saga.execute(request, on_success_callback)
    """

    def __init__(self, db: AsyncSession, channel: BasePaymentChannel) -> None:
        self._db = db
        self._channel = channel

    async def execute(
        self,
        request: PaymentRequest,
        on_success: Optional[object] = None,
    ) -> PaymentResult:
        """执行支付 Saga

        Args:
            request: 统一支付请求
            on_success: 支付成功后的回调（异步可调用对象，接收 PaymentResult）

        Returns:
            PaymentResult
        """
        saga_id = str(uuid.uuid4())
        log = logger.bind(saga_id=saga_id, order_id=request.order_id)

        # S1: validate（无副作用）
        await self._update_step(saga_id, request, SagaStep.VALIDATING)
        log.info("saga_s1_validate")

        # S2: execute（有副作用：扣款）
        await self._update_step(saga_id, request, SagaStep.EXECUTING)
        try:
            result = await self._channel.pay(request)
        except Exception as exc:
            log.error("saga_s2_payment_failed", error=str(exc))
            await self._update_step(saga_id, request, SagaStep.FAILED)
            raise

        if result.status == PayStatus.FAILED:
            log.warning("saga_s2_payment_declined", error=result.error_msg)
            await self._update_step(saga_id, request, SagaStep.FAILED)
            return result

        # S3: confirm（通知业务方）
        await self._update_step(
            saga_id, request, SagaStep.CONFIRMING,
            payment_id=result.payment_id,
            trade_no=result.trade_no,
        )
        try:
            if on_success and callable(on_success):
                await on_success(result)
        except Exception as exc:
            # S3 失败 → 补偿：退款
            log.error("saga_s3_confirm_failed_compensating", error=str(exc))
            await self._update_step(saga_id, request, SagaStep.COMPENSATING)
            try:
                await self._channel.refund(
                    payment_id=result.payment_id,
                    refund_amount_fen=request.amount_fen,
                    reason=f"Saga补偿: S3确认失败 ({exc})",
                )
                await self._update_step(saga_id, request, SagaStep.COMPENSATED)
            except Exception as refund_exc:
                log.error(
                    "saga_compensation_refund_failed",
                    error=str(refund_exc),
                    payment_id=result.payment_id,
                )
            raise

        await self._update_step(saga_id, request, SagaStep.DONE)
        log.info("saga_completed", payment_id=result.payment_id)
        return result

    async def _update_step(
        self,
        saga_id: str,
        request: PaymentRequest,
        step: str,
        payment_id: Optional[str] = None,
        trade_no: Optional[str] = None,
    ) -> None:
        """更新 Saga 步骤到 DB（用于崩溃恢复）"""
        await self._db.execute(
            text("""
                INSERT INTO payment_sagas (
                    id, tenant_id, order_id, step, amount_fen,
                    method, payment_id, trade_no, idempotency_key,
                    created_at, updated_at
                ) VALUES (
                    :saga_id::UUID, :tenant_id::UUID, :order_id,
                    :step, :amount_fen, :method, :payment_id,
                    :trade_no, :idempotency_key, NOW(), NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    step = EXCLUDED.step,
                    payment_id = COALESCE(EXCLUDED.payment_id, payment_sagas.payment_id),
                    trade_no = COALESCE(EXCLUDED.trade_no, payment_sagas.trade_no),
                    updated_at = NOW()
            """),
            {
                "saga_id": saga_id,
                "tenant_id": request.tenant_id,
                "order_id": request.order_id,
                "step": step,
                "amount_fen": request.amount_fen,
                "method": request.method.value,
                "payment_id": payment_id,
                "trade_no": trade_no,
                "idempotency_key": request.idempotency_key,
            },
        )
        await self._db.flush()

    async def recover_stale(self) -> int:
        """恢复挂起的 Saga（启动时调用）

        Returns:
            恢复的 Saga 数量
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_PENDING_TIMEOUT_MINUTES)
        result = await self._db.execute(
            text("""
                SELECT id, order_id, step, payment_id, trade_no, method, amount_fen
                FROM payment_sagas
                WHERE step IN (:s_executing, :s_confirming)
                  AND updated_at < :cutoff
            """),
            {
                "s_executing": SagaStep.EXECUTING,
                "s_confirming": SagaStep.CONFIRMING,
                "cutoff": cutoff,
            },
        )
        rows = result.fetchall()
        recovered = 0
        for row in rows:
            saga_id, order_id, step, payment_id, trade_no, method, amount_fen = row
            log = logger.bind(saga_id=str(saga_id), order_id=order_id, step=step)

            if step == SagaStep.EXECUTING and payment_id:
                # 查询渠道确认扣款状态
                try:
                    query_result = await self._channel.query(payment_id, trade_no)
                    if query_result.status == PayStatus.SUCCESS:
                        log.info("saga_recover_payment_confirmed")
                        recovered += 1
                    else:
                        log.info("saga_recover_payment_not_confirmed")
                except Exception as exc:
                    log.error("saga_recover_query_failed", error=str(exc))
            elif step == SagaStep.CONFIRMING and payment_id:
                # 补偿退款
                log.warning("saga_recover_compensating_stale")
                try:
                    await self._channel.refund(
                        payment_id=payment_id,
                        refund_amount_fen=amount_fen,
                        reason="Saga崩溃恢复: 确认步骤超时",
                    )
                    recovered += 1
                except Exception as exc:
                    log.error("saga_recover_refund_failed", error=str(exc))

        return recovered
