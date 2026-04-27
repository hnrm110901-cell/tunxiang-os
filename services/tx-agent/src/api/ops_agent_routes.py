"""运营专项Agent路由 — 排位/后厨超时/收银异常/闭店

prefix: /api/v1/agent/ops

4个专项运营Agent的HTTP API端点，供前端直接调用。
每个Agent也通过EventBus事件自动触发（见event_bus.py DEFAULT_EVENT_HANDLERS）。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agent/ops", tags=["ops-agents"])


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────────


class AgentActionRequest(BaseModel):
    store_id: str
    action: str
    params: dict = Field(default_factory=dict)


class AgentActionResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)
    error: dict | None = None


# ─── 辅助：实例化并执行 Agent ──────────────────────────────────────────────────


async def _run_agent(agent_cls: type, tenant_id: str, store_id: str, action: str, params: dict) -> dict:
    """实例化SkillAgent并执行指定action"""
    agent = agent_cls(tenant_id=tenant_id, store_id=store_id)
    result = await agent.run(action, {**params, "store_id": store_id})
    return {
        "success": result.success,
        "action": result.action,
        "data": result.data,
        "reasoning": result.reasoning,
        "confidence": result.confidence,
        "inference_layer": result.inference_layer,
        "execution_ms": result.execution_ms,
        "constraints_passed": result.constraints_passed,
        "error": result.error,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 排位Agent
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/queue/predict-wait", response_model=AgentActionResponse)
async def queue_predict_wait(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """预测排队等位时间"""
    from ..agents.skills.queue_seating import QueueSeatingAgent

    result = await _run_agent(QueueSeatingAgent, x_tenant_id, req.store_id, "predict_wait_time", req.params)
    return AgentActionResponse(data=result)


@router.post("/queue/suggest-seating", response_model=AgentActionResponse)
async def queue_suggest_seating(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """推荐最优桌位"""
    from ..agents.skills.queue_seating import QueueSeatingAgent

    result = await _run_agent(QueueSeatingAgent, x_tenant_id, req.store_id, "suggest_seating", req.params)
    return AgentActionResponse(data=result)


@router.post("/queue/auto-call", response_model=AgentActionResponse)
async def queue_auto_call(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """自动叫号下一位"""
    from ..agents.skills.queue_seating import QueueSeatingAgent

    result = await _run_agent(QueueSeatingAgent, x_tenant_id, req.store_id, "auto_call_next", req.params)
    return AgentActionResponse(data=result)


# ═══════════════════════════════════════════════════════════════════════════════
# 后厨超时Agent
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/kitchen/scan-overtime", response_model=AgentActionResponse)
async def kitchen_scan_overtime(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """扫描超时出餐项"""
    from ..agents.skills.kitchen_overtime import KitchenOvertimeAgent

    result = await _run_agent(KitchenOvertimeAgent, x_tenant_id, req.store_id, "scan_overtime_items", req.params)
    return AgentActionResponse(data=result)


@router.post("/kitchen/analyze-cause", response_model=AgentActionResponse)
async def kitchen_analyze_cause(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """分析超时根因"""
    from ..agents.skills.kitchen_overtime import KitchenOvertimeAgent

    result = await _run_agent(KitchenOvertimeAgent, x_tenant_id, req.store_id, "analyze_overtime_cause", req.params)
    return AgentActionResponse(data=result)


@router.post("/kitchen/rush", response_model=AgentActionResponse)
async def kitchen_rush_notify(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """自动催菜"""
    from ..agents.skills.kitchen_overtime import KitchenOvertimeAgent

    result = await _run_agent(KitchenOvertimeAgent, x_tenant_id, req.store_id, "auto_rush_notify", req.params)
    return AgentActionResponse(data=result)


@router.post("/kitchen/bottleneck", response_model=AgentActionResponse)
async def kitchen_bottleneck(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """识别瓶颈档口"""
    from ..agents.skills.kitchen_overtime import KitchenOvertimeAgent

    result = await _run_agent(KitchenOvertimeAgent, x_tenant_id, req.store_id, "get_station_bottleneck", req.params)
    return AgentActionResponse(data=result)


# ═══════════════════════════════════════════════════════════════════════════════
# 收银异常Agent
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/billing/detect-reverse", response_model=AgentActionResponse)
async def billing_detect_reverse(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """反结账异常检测"""
    from ..agents.skills.billing_anomaly import BillingAnomalyAgent

    result = await _run_agent(
        BillingAnomalyAgent, x_tenant_id, req.store_id, "detect_reverse_settle_anomaly", req.params
    )
    return AgentActionResponse(data=result)


@router.post("/billing/scan-missing", response_model=AgentActionResponse)
async def billing_scan_missing(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """漏单检测"""
    from ..agents.skills.billing_anomaly import BillingAnomalyAgent

    result = await _run_agent(BillingAnomalyAgent, x_tenant_id, req.store_id, "scan_missing_orders", req.params)
    return AgentActionResponse(data=result)


@router.post("/billing/risk-summary", response_model=AgentActionResponse)
async def billing_risk_summary(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """收银风险汇总"""
    from ..agents.skills.billing_anomaly import BillingAnomalyAgent

    result = await _run_agent(BillingAnomalyAgent, x_tenant_id, req.store_id, "get_risk_summary", req.params)
    return AgentActionResponse(data=result)


# ═══════════════════════════════════════════════════════════════════════════════
# 闭店Agent
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/closing/pre-check", response_model=AgentActionResponse)
async def closing_pre_check(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """闭店预检"""
    from ..agents.skills.closing_agent import ClosingAgent

    result = await _run_agent(ClosingAgent, x_tenant_id, req.store_id, "pre_closing_check", req.params)
    return AgentActionResponse(data=result)


@router.post("/closing/validate-settlement", response_model=AgentActionResponse)
async def closing_validate_settlement(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """日结数据校验"""
    from ..agents.skills.closing_agent import ClosingAgent

    result = await _run_agent(ClosingAgent, x_tenant_id, req.store_id, "validate_daily_settlement", req.params)
    return AgentActionResponse(data=result)


@router.post("/closing/report", response_model=AgentActionResponse)
async def closing_report(
    req: AgentActionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """生成闭店报告"""
    from ..agents.skills.closing_agent import ClosingAgent

    result = await _run_agent(ClosingAgent, x_tenant_id, req.store_id, "generate_closing_report", req.params)
    return AgentActionResponse(data=result)


# ═══════════════════════════════════════════════════════════════════════════════
# 通用执行端点（通过 agent_id + action 调用任意运营Agent）
# ═══════════════════════════════════════════════════════════════════════════════


class GenericOpsRequest(BaseModel):
    agent_id: str  # queue_seating | kitchen_overtime | billing_anomaly | closing_ops
    action: str
    store_id: str
    params: dict = Field(default_factory=dict)


AGENT_REGISTRY = {
    "queue_seating": "..agents.skills.queue_seating.QueueSeatingAgent",
    "kitchen_overtime": "..agents.skills.kitchen_overtime.KitchenOvertimeAgent",
    "billing_anomaly": "..agents.skills.billing_anomaly.BillingAnomalyAgent",
    "closing_ops": "..agents.skills.closing_agent.ClosingAgent",
}


@router.post("/execute", response_model=AgentActionResponse)
async def ops_execute(
    req: GenericOpsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """通用运营Agent执行端点"""
    from ..agents.skills.billing_anomaly import BillingAnomalyAgent
    from ..agents.skills.closing_agent import ClosingAgent
    from ..agents.skills.kitchen_overtime import KitchenOvertimeAgent
    from ..agents.skills.queue_seating import QueueSeatingAgent

    agents = {
        "queue_seating": QueueSeatingAgent,
        "kitchen_overtime": KitchenOvertimeAgent,
        "billing_anomaly": BillingAnomalyAgent,
        "closing_ops": ClosingAgent,
    }

    agent_cls = agents.get(req.agent_id)
    if not agent_cls:
        return AgentActionResponse(
            ok=False, error={"message": f"Unknown agent: {req.agent_id}", "code": "UNKNOWN_AGENT"}
        )

    result = await _run_agent(agent_cls, x_tenant_id, req.store_id, req.action, req.params)
    return AgentActionResponse(data=result)
