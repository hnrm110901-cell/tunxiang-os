"""Agent 支付 API 路由

端点：
  POST /api/v1/pay/agent/prepare     — Agent 准备支付（不扣款）
  POST /api/v1/pay/agent/confirm     — 人类确认后执行支付
  POST /api/v1/pay/agent/reject      — 人类拒绝 Agent 发起的支付
  GET  /api/v1/pay/agent/pending     — 列出待确认的 Agent 支付

安全：
  - prepare 不需要人类确认（只预冻结，不扣款）
  - confirm 需要人类生物识别/密码
  - 所有操作留痕
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..channels.base import PayMethod

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pay/agent", tags=["Agent支付"])

# 模块级单例（由 main.py lifespan 初始化）
_protocol = None


def set_protocol(protocol) -> None:
    global _protocol
    _protocol = protocol


def _get_protocol():
    if _protocol is None:
        from ..protocols.agent_payment import AgentPaymentProtocol
        from ..deps import get_payment_service
        import asyncio
        # 延迟初始化
        raise RuntimeError("AgentPaymentProtocol 未初始化")
    return _protocol


# ─── 请求模型 ───────────────────────────────────────────────────────

class PrepareReq(BaseModel):
    order_id: str
    amount_fen: int = Field(..., gt=0)
    method: PayMethod
    description: str = ""
    reason: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    store_id: str = ""
    metadata: dict = Field(default_factory=dict)


class ConfirmReq(BaseModel):
    prepared_id: str
    operator_id: str
    auth_type: str = "biometric"
    auth_token: str = ""


class RejectReq(BaseModel):
    prepared_id: str
    reason: str = ""


# ─── 端点 ───────────────────────────────────────────────────────────

@router.post("/prepare")
async def prepare_payment(
    req: PrepareReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """Agent 准备支付（不扣款）

    生成 prepared_id，推送到 POS 前端等待人类确认。
    """
    from ..protocols.agent_payment import PaymentIntent

    protocol = _get_protocol()
    intent = PaymentIntent(
        order_id=req.order_id,
        amount_fen=req.amount_fen,
        method=req.method,
        description=req.description,
        reason=req.reason,
        confidence=req.confidence,
        metadata=req.metadata,
    )

    prepared = await protocol.prepare_payment(
        agent_id=req.metadata.get("agent_id", "unknown"),
        tenant_id=x_tenant_id,
        store_id=req.store_id,
        intent=intent,
    )

    return {
        "ok": True,
        "data": {
            "prepared_id": prepared.prepared_id,
            "agent_id": prepared.agent_id,
            "status": prepared.status.value,
            "amount_fen": req.amount_fen,
            "method": req.method.value,
            "created_at": prepared.created_at.isoformat(),
        },
    }


@router.post("/confirm")
async def confirm_payment(
    req: ConfirmReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """人类确认后执行实际支付"""
    from ..protocols.agent_payment import HumanAuthProof

    protocol = _get_protocol()
    auth = HumanAuthProof(
        auth_type=req.auth_type,
        auth_token=req.auth_token,
        operator_id=req.operator_id,
    )

    result = await protocol.confirm_payment(
        prepared_id=req.prepared_id,
        human_auth=auth,
    )

    return {"ok": True, "data": result}


@router.post("/reject")
async def reject_payment(req: RejectReq):
    """人类拒绝 Agent 发起的支付"""
    protocol = _get_protocol()
    await protocol.reject_payment(
        prepared_id=req.prepared_id,
        reason=req.reason,
    )
    return {"ok": True, "data": {"message": "已拒绝"}}


@router.get("/pending")
async def list_pending(agent_id: Optional[str] = None):
    """列出待确认的 Agent 支付"""
    protocol = _get_protocol()
    pending = await protocol.list_pending(agent_id=agent_id)
    return {
        "ok": True,
        "data": [
            {
                "prepared_id": p.prepared_id,
                "agent_id": p.agent_id,
                "amount_fen": p.intent.amount_fen,
                "method": p.intent.method.value,
                "reason": p.intent.reason,
                "confidence": p.intent.confidence,
                "created_at": p.created_at.isoformat(),
            }
            for p in pending
        ],
    }
