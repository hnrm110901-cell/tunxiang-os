"""场景化 Agent API 路由 — 基于 V1 八层架构

提供：
1. 会话管理（创建/查询）
2. 自然语言输入处理（L1→L2→L3 全链路）
3. 结构化调度（直接指定 Agent + Action）
4. 工具确认执行
5. 业务流矩阵查询
6. 状态机查询
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..layers.orchestrator import create_dispatcher
from ..layers.scene_session import SceneSessionManager, UserRole
from ..layers.flow_matrix import BUSINESS_FLOWS, FLOW_INDEX, get_agent_led_flows

router = APIRouter(prefix="/api/v1/scene", tags=["scene-agent"])


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_role: str = Field(default="store_manager", description="用户角色")
    store_id: Optional[str] = Field(default=None, description="门店ID")
    brand_id: Optional[str] = Field(default=None, description="品牌ID")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    device_type: str = Field(default="browser", description="设备类型")


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    text: str = Field(..., description="用户输入")


class DispatchRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    agent_id: str = Field(..., description="目标Agent ID")
    action: str = Field(..., description="动作名称")
    params: dict = Field(default_factory=dict, description="动作参数")


class ConfirmToolRequest(BaseModel):
    session_id: str = Field(..., description="会话ID")
    tool_name: str = Field(..., description="工具名称")
    params: dict = Field(default_factory=dict, description="工具参数")


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_session_manager = SceneSessionManager()


def _get_dispatcher(model_router=None):
    """获取 Dispatcher 实例"""
    return create_dispatcher(model_router=model_router)


# ── API 路由 ──────────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(
    req: CreateSessionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """创建场景会话"""
    try:
        role = UserRole(req.user_role)
    except ValueError:
        return {"ok": False, "error": {"message": f"无效角色: {req.user_role}"}}

    ctx = _session_manager.create_session(
        tenant_id=x_tenant_id,
        user_role=role,
        store_id=req.store_id,
        brand_id=req.brand_id,
        user_id=req.user_id,
        device_type=req.device_type,
    )
    return {
        "ok": True,
        "data": {
            "session_id": ctx.session_id,
            "shift_period": ctx.shift_period.value,
            "context": ctx.to_prompt_context(),
        },
    }


@router.post("/chat")
async def chat(
    req: ChatRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """自然语言对话入口 — L1→L2→L3 全链路"""
    ctx = _session_manager.get_session(req.session_id)
    if not ctx:
        return {"ok": False, "error": {"message": f"会话不存在: {req.session_id}"}}

    # 尝试获取 ModelRouter（无 API Key 时降级）
    model_router = None
    try:
        from ..services.model_router import ModelRouter
        model_router = ModelRouter()
    except ValueError:
        pass

    dispatcher = _get_dispatcher(model_router)
    result = await dispatcher.process_input(req.text, ctx)

    return {
        "ok": result.success,
        "data": {
            "message": result.message,
            "agent_id": result.agent_id,
            "action": result.action,
            "data": result.data,
            "confidence": result.confidence,
            "constraints_passed": result.constraints_passed,
            "pending_confirmations": result.pending_tool_calls,
            "execution_ms": result.execution_ms,
        },
        "error": {"message": result.error} if result.error else None,
    }


@router.post("/dispatch")
async def dispatch(
    req: DispatchRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """结构化调度 — 直接指定 Agent + Action"""
    ctx = _session_manager.get_session(req.session_id)
    if not ctx:
        return {"ok": False, "error": {"message": f"会话不存在: {req.session_id}"}}

    dispatcher = _get_dispatcher()
    result = await dispatcher.dispatch(req.agent_id, req.action, req.params, ctx)

    return {
        "ok": result.success,
        "data": {
            "message": result.message,
            "agent_id": result.agent_id,
            "action": result.action,
            "data": result.data,
            "confidence": result.confidence,
            "pending_confirmations": result.pending_tool_calls,
            "execution_ms": result.execution_ms,
        },
        "error": {"message": result.error} if result.error else None,
    }


@router.post("/confirm")
async def confirm_tool(
    req: ConfirmToolRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """确认并执行待确认的工具调用"""
    ctx = _session_manager.get_session(req.session_id)
    if not ctx:
        return {"ok": False, "error": {"message": f"会话不存在: {req.session_id}"}}

    dispatcher = _get_dispatcher()
    result = await dispatcher.confirm_tool_call(req.tool_name, req.params, ctx)
    return {
        "ok": result.success,
        "data": {"message": result.message, "data": result.data},
        "error": {"message": result.error} if result.error else None,
    }


# ── 查询接口 ──────────────────────────────────────────────────────────────────

@router.get("/specialists")
async def list_specialists(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """列出所有专业 Agent"""
    dispatcher = _get_dispatcher()
    return {"ok": True, "data": dispatcher.list_specialists()}


@router.get("/flows")
async def list_flows(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询业务流适配矩阵"""
    return {
        "ok": True,
        "data": [
            {
                "flow_id": f.flow_id,
                "name": f.name,
                "name_en": f.name_en,
                "mode": f.mode.value,
                "agent_value": f.agent_value,
                "system_control": f.system_control,
                "primary_agents": f.primary_agents,
                "recommended_terminals": f.recommended_terminals,
                "priority": f.priority,
            }
            for f in BUSINESS_FLOWS
        ],
    }


@router.get("/flows/agent-led")
async def list_agent_led_flows(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询 Agent 主导的业务流（优先开发）"""
    flows = get_agent_led_flows()
    return {
        "ok": True,
        "data": [
            {"flow_id": f.flow_id, "name": f.name, "priority": f.priority}
            for f in flows
        ],
    }
