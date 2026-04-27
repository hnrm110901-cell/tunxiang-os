"""成本核算 Agent HTTP 路由

prefix: /api/v1/agent/cost

10 个端点对应 CostDiagnosisAgent 的 10 个 action：
  POST /diagnose             — Top10高偏差菜品
  POST /root-cause           — 原料根因分析（5因素）
  POST /suggest-fix          — 改进建议（含预期节省金额）
  POST /dish-margin          — 菜品毛利四象限
  POST /stocktake-gap        — 盘点闭环差异
  POST /contribution-margin  — 边际贡献率
  POST /break-even           — 保本点分析
  POST /scenario-simulate    — What-If 场景模拟
  POST /price-trend-alert    — 采购价趋势预警
  POST /channel-cost-compare — 渠道成本对比
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from ..agents.skills.cost_diagnosis import CostDiagnosisAgent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agent/cost", tags=["cost-diagnosis-agent"])


# ─── 通用请求/响应模型 ─────────────────────────────────────────────────────────


class CostAgentRequest(BaseModel):
    store_id: str = Field(default="", description="门店ID")
    params: dict = Field(default_factory=dict, description="action参数")


class CostAgentResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 0.0
    error: dict | None = None


# ─── 辅助函数 ──────────────────────────────────────────────────────────────────


async def _run(
    action: str,
    tenant_id: str,
    store_id: str,
    params: dict,
) -> CostAgentResponse:
    agent = CostDiagnosisAgent(tenant_id=tenant_id, store_id=store_id)
    result = await agent.run(action, {**params, "store_id": store_id})
    return CostAgentResponse(
        ok=result.success,
        data={
            **result.data,
            "action": result.action,
            "inference_layer": result.inference_layer,
            "execution_ms": result.execution_ms,
            "constraints_passed": result.constraints_passed,
        },
        reasoning=result.reasoning,
        confidence=result.confidence,
        error={"message": result.error} if result.error else None,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 端点定义
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/diagnose", response_model=CostAgentResponse)
async def diagnose_cost_variance(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """找出成本偏差最大的菜品 Top10，含严重度分级"""
    return await _run("diagnose", x_tenant_id, req.store_id, req.params)


@router.post("/root-cause", response_model=CostAgentResponse)
async def analyze_root_cause(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """原料级根因分析：5因素归因（份量超标/出成率偏差/报废损耗/盗损/BOM不准）"""
    return await _run("root_cause", x_tenant_id, req.store_id, req.params)


@router.post("/suggest-fix", response_model=CostAgentResponse)
async def suggest_cost_fix(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """生成改进建议，含预期月度/年度节省金额"""
    return await _run("suggest_fix", x_tenant_id, req.store_id, req.params)


@router.post("/dish-margin", response_model=CostAgentResponse)
async def analyze_dish_margin(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """菜品毛利四象限分析：明星/耕马/谜题/狗骨，支持渠道佣金扣减"""
    return await _run("dish_margin", x_tenant_id, req.store_id, req.params)


@router.post("/stocktake-gap", response_model=CostAgentResponse)
async def analyze_stocktake_gap(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """盘点闭环差异分析：实际消耗 vs 理论消耗，5因素归因（GAP-2修复）"""
    return await _run("stocktake_gap", x_tenant_id, req.store_id, req.params)


@router.post("/contribution-margin", response_model=CostAgentResponse)
async def analyze_contribution_margin(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """边际贡献率分析：菜品CM率 + 门店加权平均CM率 + 营业利润"""
    return await _run("contribution_margin", x_tenant_id, req.store_id, req.params)


@router.post("/break-even", response_model=CostAgentResponse)
async def analyze_break_even(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """保本点分析：月度保本营业额、保本桌次、安全边际率（GAP-7修复）"""
    return await _run("break_even", x_tenant_id, req.store_id, req.params)


@router.post("/scenario-simulate", response_model=CostAgentResponse)
async def simulate_scenario(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """What-If 场景模拟：原料涨价/菜品调价/关闭时段/人力增减（Phase 2B）"""
    return await _run("scenario_simulate", x_tenant_id, req.store_id, req.params)


@router.post("/price-trend-alert", response_model=CostAgentResponse)
async def detect_price_trend_alert(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """采购价趋势预警：连续涨价检测、价格漂移识别（Phase 2C）"""
    return await _run("price_trend_alert", x_tenant_id, req.store_id, req.params)


@router.post("/channel-cost-compare", response_model=CostAgentResponse)
async def compare_channel_cost(
    req: CostAgentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """渠道成本对比：堂食 vs 外卖毛利差异，平台佣金影响分析"""
    return await _run("channel_cost_compare", x_tenant_id, req.store_id, req.params)


# ─── 信息查询端点 ──────────────────────────────────────────────────────────────


@router.get("/info", response_model=CostAgentResponse)
async def get_agent_info(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询成本核算Agent支持的所有action"""
    agent = CostDiagnosisAgent(tenant_id=x_tenant_id)
    return CostAgentResponse(
        ok=True,
        data={
            "agent_id": agent.agent_id,
            "agent_name": agent.agent_name,
            "description": agent.description,
            "priority": agent.priority,
            "run_location": agent.run_location,
            "supported_actions": agent.get_supported_actions(),
        },
    )
