"""支付中枢服务层 — 串联路由、编排、幂等、事件

这是 tx-pay 对外暴露的核心服务类。
API 路由 → PaymentNexusService → RoutingEngine → Channel

职责：
  1. 幂等检查
  2. 路由到渠道
  3. Saga 编排
  4. 发射支付事件
  5. 日汇总查询
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .channels.base import (
    PaymentRequest,
    PaymentResult,
    PayMethod,
    PayStatus,
    RefundResult,
    TradeType,
)
from .orchestrator.idempotency import IdempotencyGuard
from .orchestrator.saga import PaymentSaga
from .orchestrator.split_pay import SplitEntry, SplitPayEngine, SplitPayResult
from .routing.engine import PaymentRoutingEngine

logger = structlog.get_logger(__name__)

# 手续费率千分比
_FEE_RATES: dict[str, int] = {
    "wechat": 6,
    "alipay": 6,
    "unionpay": 5,
    "cash": 0,
    "member_balance": 0,
    "credit_account": 0,
    "coupon": 0,
    "digital_rmb": 0,
}


class PaymentNexusService:
    """支付中枢服务"""

    def __init__(
        self,
        db: AsyncSession,
        routing: PaymentRoutingEngine,
    ) -> None:
        self._db = db
        self._routing = routing
        self._idempotency = IdempotencyGuard(db)

    async def create_payment(
        self,
        tenant_id: str,
        store_id: str,
        order_id: str,
        amount_fen: int,
        method: PayMethod,
        trade_type: TradeType = TradeType.B2C,
        auth_code: Optional[str] = None,
        openid: Optional[str] = None,
        description: str = "",
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> PaymentResult:
        """发起支付"""
        idem_key = idempotency_key or f"{store_id[:8]}-{order_id[:8]}-{int(datetime.now(timezone.utc).timestamp())}"

        # 1. 幂等检查
        existing = await self._idempotency.check(idem_key, tenant_id)
        if existing:
            logger.info("payment_idempotency_hit", key=idem_key)
            return PaymentResult(
                payment_id=existing["payment_id"],
                status=PayStatus(existing["status"]),
                method=method,
                amount_fen=existing["amount_fen"],
                trade_no=existing.get("trade_no"),
                channel_data=existing.get("channel_data", {}),
            )

        # 2. 路由到渠道
        channel = await self._routing.resolve(self._db, tenant_id, store_id, method, trade_type)

        # 3. 构造请求
        request = PaymentRequest(
            tenant_id=tenant_id,
            store_id=store_id,
            order_id=order_id,
            amount_fen=amount_fen,
            method=method,
            trade_type=trade_type,
            auth_code=auth_code,
            openid=openid,
            description=description,
            idempotency_key=idem_key,
            metadata=metadata or {},
        )

        # 4. Saga 执行
        saga = PaymentSaga(self._db, channel)
        result = await saga.execute(request)

        # 5. 记录幂等
        await self._idempotency.record(
            idempotency_key=idem_key,
            tenant_id=tenant_id,
            payment_id=result.payment_id,
            status=result.status.value,
            trade_no=result.trade_no,
            amount_fen=result.amount_fen,
            channel_data=result.channel_data,
        )

        # 6. 持久化支付记录
        await self._persist_payment(tenant_id, store_id, order_id, result, method)

        # 7. 发射事件
        if result.status == PayStatus.SUCCESS:
            await self._emit_event(tenant_id, store_id, order_id, result)

        await self._db.commit()
        return result

    async def query_payment(
        self,
        payment_id: str,
        trade_no: Optional[str] = None,
    ) -> PaymentResult:
        """查询支付状态（先查本地DB，再查渠道）"""
        row = await self._db.execute(
            text("SELECT method, status, amount_fen, trade_no, channel_data FROM payments WHERE payment_no = :pid"),
            {"pid": payment_id},
        )
        r = row.fetchone()
        if r:
            return PaymentResult(
                payment_id=payment_id,
                status=PayStatus(r[1]),
                method=PayMethod(r[0]),
                amount_fen=r[2],
                trade_no=r[3],
                channel_data=r[4] or {},
            )

        # 本地无记录 → 返回 PENDING
        return PaymentResult(
            payment_id=payment_id,
            status=PayStatus.PENDING,
            method=PayMethod.WECHAT,
            amount_fen=0,
        )

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
        refund_id: Optional[str] = None,
    ) -> RefundResult:
        """退款 — 依次：验存在/验额度 → 调渠道 → 持久化 → 更新net_amount → 发射事件"""
        import uuid as _uuid

        from .events import emit_payment_refunded

        # 查询原支付记录（FOR UPDATE 防止并发退款 TOCTOU）
        row = await self._db.execute(
            text(
                """SELECT method, amount_fen, trade_no, tenant_id, store_id
                   FROM payments WHERE payment_no = :pid FOR UPDATE"""
            ),
            {"pid": payment_id},
        )
        r = row.fetchone()
        if not r:
            raise ValueError(f"支付记录不存在: {payment_id}")

        method, original_fen, trade_no, tenant_id, store_id = r
        if refund_amount_fen > original_fen:
            raise ValueError(f"退款金额({refund_amount_fen})超过原支付金额({original_fen})")

        channel = await self._routing.resolve(
            self._db,
            str(tenant_id),
            str(store_id),
            PayMethod(method),
        )
        _refund_id = refund_id or str(_uuid.uuid4())
        result = await channel.refund(
            payment_id=payment_id,
            refund_amount_fen=refund_amount_fen,
            reason=reason,
            refund_id=_refund_id,
        )

        # 持久化退款记录到 payments 表（记录退款流水 + 更新净额）
        if result.status == "success":
            await self._db.execute(
                text(
                    """UPDATE payments
                       SET status = CASE
                             WHEN :refund_fen >= amount_fen THEN 'refunded'
                             ELSE 'partial_refund'
                           END,
                           net_amount_fen = COALESCE(net_amount_fen, amount_fen) - :refund_fen
                       WHERE payment_no = :pid"""
                ),
                {
                    "refund_fen": refund_amount_fen,
                    "pid": payment_id,
                },
            )
            # 发射退款事件
            await emit_payment_refunded(
                payment_id=payment_id,
                refund_id=_refund_id,
                amount_fen=refund_amount_fen,
                tenant_id=str(tenant_id) if tenant_id else "",
            )
            logger.info(
                "refund_persisted_and_event_emitted",
                payment_id=payment_id,
                refund_id=_refund_id,
                refund_amount_fen=refund_amount_fen,
                method=method,
            )

        await self._db.commit()
        return result

    async def close_payment(self, payment_id: str) -> bool:
        """关闭未支付交易"""
        return True

    async def split_payment(
        self,
        tenant_id: str,
        store_id: str,
        order_id: str,
        entries: list[SplitEntry],
    ) -> SplitPayResult:
        """多方式拆单支付"""

        async def resolve_channel(method: PayMethod, trade_type: TradeType):
            return await self._routing.resolve(self._db, tenant_id, store_id, method, trade_type)

        engine = SplitPayEngine(resolve_channel)
        result = await engine.execute(tenant_id, store_id, order_id, entries)

        await self._db.commit()
        return result

    async def daily_summary(
        self,
        tenant_id: str,
        store_id: str,
        summary_date: date,
    ) -> dict:
        """按支付方式汇总当日收款"""
        result = await self._db.execute(
            text("""
                SELECT method,
                       COUNT(*) AS count,
                       SUM(amount_fen) AS total_fen
                FROM payments
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND DATE(created_at) = :summary_date
                  AND status = 'paid'
                GROUP BY method
            """),
            {"tenant_id": tenant_id, "store_id": store_id, "summary_date": summary_date},
        )
        rows = result.fetchall()
        summary = {
            "date": summary_date.isoformat(),
            "store_id": store_id,
            "methods": {r[0]: {"count": r[1], "total_fen": r[2]} for r in rows},
            "grand_total_fen": sum(r[2] for r in rows),
        }
        # 计算手续费
        for method_name, data in summary["methods"].items():
            rate = _FEE_RATES.get(method_name, 0)
            data["fee_fen"] = data["total_fen"] * rate // 1000
        return summary

    async def _persist_payment(
        self,
        tenant_id: str,
        store_id: str,
        order_id: str,
        result: PaymentResult,
        method: PayMethod,
    ) -> None:
        """持久化支付记录到 payments 表"""
        status_map = {
            PayStatus.SUCCESS: "paid",
            PayStatus.PENDING: "pending",
            PayStatus.FAILED: "failed",
        }
        await self._db.execute(
            text("""
                INSERT INTO payments (
                    payment_no, tenant_id, store_id, order_id,
                    method, amount_fen, status, trade_no,
                    channel_data, created_at
                ) VALUES (
                    :payment_no, :tenant_id::UUID, :store_id::UUID, :order_id::UUID,
                    :method, :amount_fen, :status, :trade_no,
                    :channel_data::JSONB, NOW()
                )
                ON CONFLICT (payment_no) DO NOTHING
            """),
            {
                "payment_no": result.payment_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "order_id": order_id,
                "method": method.value,
                "amount_fen": result.amount_fen,
                "status": status_map.get(result.status, "pending"),
                "trade_no": result.trade_no,
                "channel_data": "{}",
            },
        )

    async def _emit_event(
        self,
        tenant_id: str,
        store_id: str,
        order_id: str,
        result: PaymentResult,
    ) -> None:
        """发射支付确认事件到事件总线"""
        try:
            import asyncio

            from shared.events.src.emitter import emit_event
            from shared.events.src.event_types import PaymentEventType

            asyncio.create_task(
                emit_event(
                    event_type=PaymentEventType.CONFIRMED,
                    tenant_id=tenant_id,
                    stream_id=order_id,
                    payload={
                        "payment_id": result.payment_id,
                        "amount_fen": result.amount_fen,
                        "method": result.method.value,
                        "trade_no": result.trade_no,
                    },
                    store_id=store_id,
                    source_service="tx-pay",
                )
            )
        except ImportError:
            logger.debug("event_emitter_not_available")
