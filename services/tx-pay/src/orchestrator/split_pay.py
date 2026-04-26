"""多方式拆单支付引擎 — 混合支付编排

场景：顾客用 500元储值 + 300元微信 结账一笔 800 元订单。
拆单规则：
  1. 按 PaymentEntry 列表顺序逐一扣款
  2. 任一笔失败 → 已成功的全部退款（补偿）
  3. 全部成功 → 返回合并结果
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from pydantic import BaseModel, Field

from ..channels.base import (
    BasePaymentChannel,
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    TradeType,
)

logger = structlog.get_logger(__name__)


class SplitEntry(BaseModel):
    """拆单项"""
    method: PayMethod
    amount_fen: int = Field(..., gt=0)
    auth_code: Optional[str] = None
    openid: Optional[str] = None


class SplitPayResult(BaseModel):
    """拆单支付结果"""
    success: bool
    total_fen: int
    entries: list[PaymentResult]
    failed_entry: Optional[PaymentResult] = None
    compensated: bool = False


class SplitPayEngine:
    """多方式拆单支付引擎

    使用方式：
        engine = SplitPayEngine(resolve_channel_fn)
        result = await engine.execute(
            tenant_id, store_id, order_id,
            entries=[
                SplitEntry(method=PayMethod.MEMBER_BALANCE, amount_fen=50000),
                SplitEntry(method=PayMethod.WECHAT, amount_fen=30000, auth_code="..."),
            ],
        )
    """

    def __init__(
        self,
        resolve_channel: object,
    ) -> None:
        """
        Args:
            resolve_channel: async (method, trade_type) -> BasePaymentChannel
        """
        self._resolve = resolve_channel

    async def execute(
        self,
        tenant_id: str,
        store_id: str,
        order_id: str,
        entries: list[SplitEntry],
        idempotency_prefix: Optional[str] = None,
    ) -> SplitPayResult:
        """执行拆单支付

        按顺序扣款，任一失败则补偿已成功的。
        """
        if not entries:
            raise ValueError("拆单项不能为空")

        prefix = idempotency_prefix or f"{order_id[:8]}-split"
        succeeded: list[tuple[PaymentResult, BasePaymentChannel]] = []
        total_fen = sum(e.amount_fen for e in entries)
        log = logger.bind(order_id=order_id, total_fen=total_fen, split_count=len(entries))

        for idx, entry in enumerate(entries):
            channel = await self._resolve(entry.method, TradeType.B2C)
            request = PaymentRequest(
                tenant_id=tenant_id,
                store_id=store_id,
                order_id=order_id,
                amount_fen=entry.amount_fen,
                method=entry.method,
                auth_code=entry.auth_code,
                openid=entry.openid,
                idempotency_key=f"{prefix}-{idx}",
            )

            try:
                result = await channel.pay(request)
            except Exception as exc:
                log.error("split_pay_entry_error", idx=idx, method=entry.method.value, error=str(exc))
                result = PaymentResult(
                    payment_id=f"failed-{uuid.uuid4().hex[:8]}",
                    status=PayStatus.FAILED,
                    method=entry.method,
                    amount_fen=entry.amount_fen,
                    error_msg=str(exc),
                )

            if result.status in (PayStatus.SUCCESS, PayStatus.PENDING):
                succeeded.append((result, channel))
            else:
                # 失败 → 补偿已成功的
                log.warning(
                    "split_pay_failed_compensating",
                    idx=idx,
                    method=entry.method.value,
                    succeeded_count=len(succeeded),
                )
                await self._compensate(succeeded, order_id)
                return SplitPayResult(
                    success=False,
                    total_fen=total_fen,
                    entries=[r for r, _ in succeeded] + [result],
                    failed_entry=result,
                    compensated=len(succeeded) > 0,
                )

        log.info("split_pay_all_succeeded", count=len(succeeded))
        return SplitPayResult(
            success=True,
            total_fen=total_fen,
            entries=[r for r, _ in succeeded],
        )

    async def _compensate(
        self,
        succeeded: list[tuple[PaymentResult, BasePaymentChannel]],
        order_id: str,
    ) -> None:
        """补偿退款（逆序退款）"""
        for result, channel in reversed(succeeded):
            try:
                await channel.refund(
                    payment_id=result.payment_id,
                    refund_amount_fen=result.amount_fen,
                    reason=f"拆单支付补偿退款 (order={order_id})",
                )
                logger.info(
                    "split_pay_compensated",
                    payment_id=result.payment_id,
                    amount_fen=result.amount_fen,
                )
            except Exception as exc:
                logger.error(
                    "split_pay_compensate_failed",
                    payment_id=result.payment_id,
                    error=str(exc),
                )
