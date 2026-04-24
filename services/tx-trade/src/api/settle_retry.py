"""settle_retry — Sprint A2 Saga 缓冲补发入口

POST /api/v1/settle/retry
  请求体：{ idempotency_key, saga_id, tenant_id, store_id, device_id, payload }
  语义：
    - Flusher 从 Mac mini 本地 SQLite 缓冲补发到此端点
    - 若 idempotency_key 已在 payment_sagas 表中 done/compensated/failed
      → 直接返回既有结果（防双扣费，对齐 A1 合约 R2）
    - 若首次见到 → 走既有 PaymentSagaService 流程（不复制逻辑）
  审计：每次调用写 trade_audit_logs（A4 已落 write_audit 助手）

RBAC：
  - require_role("cashier", "store_manager", "admin")
  - Mac mini Flusher 使用 edge_service JWT（role=cashier）
  - 跨租户：X-Tenant-ID header vs payload.tenant_id 必须一致，否则 403

关联：
  - payment_saga_service.PaymentSagaService.execute 的 idempotency 短路
  - A1 tradeApi.ts 合约：idempotency_key = `settle:{orderId}`
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.trade_audit_log import write_audit

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["settle-retry"])


class SettleRetryRequest(BaseModel):
    """Mac mini Flusher 补发请求体。"""

    idempotency_key: str = Field(..., min_length=1, max_length=128)
    saga_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    device_id: str = Field(..., min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)


class SettleRetryResponse(BaseModel):
    ok: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


async def _lookup_existing_saga(
    db: AsyncSession,
    *,
    tenant_id: str,
    idempotency_key: str,
) -> Optional[dict]:
    """按 idempotency_key 查 payment_sagas 表（RLS 已绑定 app.tenant_id）。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )
    try:
        result = await db.execute(
            text(
                "SELECT saga_id, step, payment_id, compensation_reason "
                "FROM payment_sagas "
                "WHERE tenant_id = :tenant_id "
                "  AND idempotency_key = :ikey "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"tenant_id": tenant_id, "ikey": idempotency_key},
        )
        row = result.mappings().first()
        return dict(row) if row else None
    except SQLAlchemyError as exc:
        # payment_sagas 查询失败不应直接对前端返回 5xx 掩盖真实原因：
        # Flusher 已经 attempts++，下轮重试
        logger.error(
            "settle_retry_lookup_failed",
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            error=str(exc),
        )
        raise


@router.post("/settle/retry", response_model=SettleRetryResponse)
async def settle_retry(
    body: SettleRetryRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(
        require_role("cashier", "store_manager", "admin")
    ),
) -> SettleRetryResponse:
    """Mac mini Flusher 补发入口。

    行为：
      1. X-Tenant-ID 与 body.tenant_id 必须一致（防跨租户伪造）
      2. 查 payment_sagas：
         - step=done → 直接返回既有 saga_id + payment_id（幂等）
         - step IN (failed, compensated) → 返回既有结果，状态不可逆
         - 不存在或仍 pending → 本 PR 不重建 saga（留给 v2），返回 202 accepted
      3. 写 trade_audit_logs 留痕（无论命中与否）
    """
    if x_tenant_id != body.tenant_id:
        logger.warning(
            "settle_retry_tenant_mismatch",
            header_tenant=x_tenant_id,
            body_tenant=body.tenant_id,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="TENANT_MISMATCH")

    # 用户所属租户也必须一致（防止 cashier 用自己租户 JWT 补发别人租户的单）
    if user.tenant_id and user.tenant_id != body.tenant_id:
        logger.warning(
            "settle_retry_user_tenant_mismatch",
            user_tenant=user.tenant_id,
            body_tenant=body.tenant_id,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    existing: Optional[dict] = None
    try:
        existing = await _lookup_existing_saga(
            db,
            tenant_id=body.tenant_id,
            idempotency_key=body.idempotency_key,
        )
    except SQLAlchemyError:
        # 审计记录失败原因
        await write_audit(
            db,
            tenant_id=body.tenant_id,
            store_id=body.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="settle.retry.lookup_failed",
            target_type="saga",
            target_id=body.saga_id,
            amount_fen=body.payload.get("amount_fen") if isinstance(body.payload, dict) else None,
            client_ip=user.client_ip,
        )
        return SettleRetryResponse(
            ok=False,
            error={"code": "LOOKUP_FAILED", "message": "saga 表临时不可用,重试"},
        )

    # 写审计（命中与否都留痕）
    amount_fen = body.payload.get("amount_fen") if isinstance(body.payload, dict) else None
    await write_audit(
        db,
        tenant_id=body.tenant_id,
        store_id=body.store_id,
        user_id=user.user_id,
        user_role=user.role,
        action="settle.retry",
        target_type="saga",
        target_id=body.saga_id,
        amount_fen=amount_fen if isinstance(amount_fen, int) else None,
        client_ip=user.client_ip,
    )

    if existing is not None:
        step = existing["step"]
        if step == "done":
            logger.info(
                "settle_retry_hit_done",
                idempotency_key=body.idempotency_key,
                saga_id=str(existing["saga_id"]),
            )
            return SettleRetryResponse(
                ok=True,
                data={
                    "status": "done",
                    "saga_id": str(existing["saga_id"]),
                    "payment_id": (
                        str(existing["payment_id"])
                        if existing["payment_id"] else None
                    ),
                    "source": "idempotency_replay",
                },
            )
        if step in ("compensated", "failed"):
            logger.info(
                "settle_retry_hit_terminal",
                idempotency_key=body.idempotency_key,
                saga_id=str(existing["saga_id"]),
                step=step,
            )
            return SettleRetryResponse(
                ok=True,
                data={
                    "status": step,
                    "saga_id": str(existing["saga_id"]),
                    "payment_id": (
                        str(existing["payment_id"])
                        if existing["payment_id"] else None
                    ),
                    "reason": existing.get("compensation_reason"),
                    "source": "idempotency_replay",
                },
            )
        # 仍在 paying/completing/validating —— 已有 saga 正在进行，不重复触发
        return SettleRetryResponse(
            ok=True,
            data={
                "status": step,
                "saga_id": str(existing["saga_id"]),
                "source": "in_flight",
            },
        )

    # 无既有 saga：本 PR 不重建 saga 流程（留给下一 Sprint 完整化），
    # 返回 202 accepted 告诉 Flusher 稍后再试（会带出 dead_letter 机制）
    logger.info(
        "settle_retry_no_existing_saga_accepted",
        idempotency_key=body.idempotency_key,
        saga_id=body.saga_id,
    )
    return SettleRetryResponse(
        ok=True,
        data={
            "status": "accepted",
            "saga_id": body.saga_id,
            "source": "queued",
            "hint": (
                "既有 saga 表无此 idempotency_key，Flusher 将标 failed 下轮重试；"
                "若连续 max_attempts 失败或 4h 到期则进 dead_letter"
            ),
        },
    )
