"""幂等保护 — 防止重复扣款

基于 idempotency_key 去重（24小时窗口）。
重复请求直接返回已有结果，不再调用渠道。

存储：payment_idempotency 表
格式：{device_id}-{order_id[:8]}-{unix_ts}
"""
from __future__ import annotations

from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 幂等窗口（小时）
_IDEMPOTENCY_WINDOW_HOURS = 24


class IdempotencyGuard:
    """幂等保护器"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check(self, idempotency_key: str, tenant_id: str) -> Optional[dict]:
        """检查幂等键是否已存在

        Returns:
            已有支付结果（dict）或 None（首次请求）
        """
        result = await self._db.execute(
            text("""
                SELECT payment_id, status, trade_no, amount_fen, channel_data
                FROM payment_idempotency
                WHERE idempotency_key = :key
                  AND tenant_id = :tenant_id::UUID
                  AND created_at > NOW() - INTERVAL ':hours hours'
            """.replace(":hours", str(_IDEMPOTENCY_WINDOW_HOURS))),
            {"key": idempotency_key, "tenant_id": tenant_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        logger.info(
            "idempotency_hit",
            idempotency_key=idempotency_key,
            payment_id=row[0],
        )
        return {
            "payment_id": row[0],
            "status": row[1],
            "trade_no": row[2],
            "amount_fen": row[3],
            "channel_data": row[4] or {},
        }

    async def record(
        self,
        idempotency_key: str,
        tenant_id: str,
        payment_id: str,
        status: str,
        trade_no: Optional[str],
        amount_fen: int,
        channel_data: Optional[dict] = None,
    ) -> None:
        """记录幂等结果"""
        await self._db.execute(
            text("""
                INSERT INTO payment_idempotency (
                    idempotency_key, tenant_id, payment_id,
                    status, trade_no, amount_fen, channel_data,
                    created_at
                ) VALUES (
                    :key, :tenant_id::UUID, :payment_id,
                    :status, :trade_no, :amount_fen,
                    :channel_data::JSONB, NOW()
                )
                ON CONFLICT (idempotency_key, tenant_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    trade_no = COALESCE(EXCLUDED.trade_no, payment_idempotency.trade_no),
                    channel_data = COALESCE(EXCLUDED.channel_data, payment_idempotency.channel_data),
                    updated_at = NOW()
            """),
            {
                "key": idempotency_key,
                "tenant_id": tenant_id,
                "payment_id": payment_id,
                "status": status,
                "trade_no": trade_no,
                "amount_fen": amount_fen,
                "channel_data": str(channel_data or {}),
            },
        )
        await self._db.flush()
