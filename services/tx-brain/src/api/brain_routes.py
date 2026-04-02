"""AI决策API路由 — 折扣守护 & 会员洞察

Endpoints:
  POST /api/v1/brain/discount/analyze  — 折扣分析（event + history）
  POST /api/v1/brain/member/insight    — 会员洞察（member + orders）
  GET  /api/v1/brain/health            — AI服务健康检查（验证Claude API可达）
"""
from __future__ import annotations

from typing import Any

import anthropic
import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..agents.discount_guardian import discount_guardian
from ..agents.member_insight import member_insight

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


# ─── Request Models ──────────────────────────────────────────────


class DiscountAnalyzeRequest(BaseModel):
    event: dict[str, Any] = Field(..., description="折扣事件（含操作员/菜品/折扣信息）")
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近30条同操作员折扣记录（可为空）",
    )


class MemberInsightRequest(BaseModel):
    member: dict[str, Any] = Field(..., description="会员基本信息")
    orders: list[dict[str, Any]] = Field(
        default_factory=list,
        description="近12个月订单列表（含菜品明细）",
    )


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/discount/analyze")
async def analyze_discount(req: DiscountAnalyzeRequest) -> dict[str, Any]:
    """POST /api/v1/brain/discount/analyze

    调用折扣守护Agent分析折扣事件是否合规。
    返回 allow/warn/reject 决策及置信度、风险因素、三条硬约束校验结果。
    """
    try:
        result = await discount_guardian.analyze(req.event, req.history)
    except anthropic.APIConnectionError as exc:
        logger.error("discount_analyze_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "discount_analyze_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.post("/member/insight")
async def member_insight_endpoint(req: MemberInsightRequest) -> dict[str, Any]:
    """POST /api/v1/brain/member/insight

    调用会员洞察Agent分析会员消费行为。
    返回会员分层、关键洞察、推荐菜品及行动建议。
    """
    try:
        result = await member_insight.analyze(req.member, req.orders)
    except anthropic.APIConnectionError as exc:
        logger.error("member_insight_connection_error", error=str(exc))
        return {
            "ok": False,
            "error": {
                "code": "AI_CONNECTION_ERROR",
                "message": "无法连接Claude API，请稍后重试",
            },
        }
    except anthropic.APIError as exc:
        logger.error(
            "member_insight_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        return {
            "ok": False,
            "error": {
                "code": "AI_API_ERROR",
                "message": f"Claude API错误: {exc}",
            },
        }

    return {"ok": True, "data": result}


@router.get("/health")
async def brain_health() -> dict[str, Any]:
    """GET /api/v1/brain/health

    检查AI服务健康状态，验证Claude API是否可达。
    发送一条最小化请求到 claude-haiku 确认连通性。
    """
    import anthropic as _anthropic

    _client = _anthropic.AsyncAnthropic()

    try:
        msg = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        claude_ok = bool(msg.content)
        claude_status = "reachable"
    except _anthropic.APIConnectionError as exc:
        logger.warning("brain_health_connection_error", error=str(exc))
        claude_ok = False
        claude_status = f"connection_error: {exc}"
    except _anthropic.APIError as exc:
        logger.warning(
            "brain_health_api_error",
            status_code=getattr(exc, "status_code", None),
            error=str(exc),
        )
        claude_ok = False
        claude_status = f"api_error: {exc}"

    return {
        "ok": claude_ok,
        "data": {
            "service": "tx-brain",
            "agents": {
                "discount_guardian": "ready",
                "member_insight": "ready",
            },
            "claude_api": claude_status,
        },
    }
