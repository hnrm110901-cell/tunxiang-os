"""Tool Bus API 路由 — 统一工具注册、发现与调用

端点:
  GET    /api/v1/tools/                — 列出所有已注册工具（可按 agent_id 过滤）
  GET    /api/v1/tools/search          — 按关键词搜索工具
  GET    /api/v1/tools/llm-schema      — 导出 LLM function-calling 格式
  GET    /api/v1/tools/{tool_id}       — 获取工具定义详情
  POST   /api/v1/tools/{tool_id}/invoke — 调用工具（需 X-Tenant-ID）
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.tool_caller import ToolCallError, ToolCaller
from ..services.tool_registry import ToolDefinition, ToolRegistry

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


# ── Request / Response Models ─────────────────────────────────────────────


class InvokeToolRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict, description="工具调用参数")
    caller_agent_id: str = Field(default="api_caller", description="调用方 Agent ID")
    session_id: str | None = Field(default=None, description="可选会话 ID")


class ToolResponse(BaseModel):
    tool_id: str
    agent_id: str
    action: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    requires_auth: bool
    risk_level: str


# ── Helpers ────────────────────────────────────────────────────────────────


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "tool_id": tool.tool_id,
        "agent_id": tool.agent_id,
        "action": tool.action,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "requires_auth": tool.requires_auth,
        "risk_level": tool.risk_level,
    }


def _get_registry() -> ToolRegistry:
    return ToolRegistry.get_instance()


# ── Dependency ─────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/")
async def list_tools(
    agent_id: str | None = Query(default=None, description="按 Agent ID 过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """列出所有已注册工具（支持按 agent_id 过滤）"""
    registry = _get_registry()
    tools = registry.list_tools(agent_id=agent_id)
    return {
        "ok": True,
        "data": {
            "items": [_tool_to_dict(t) for t in tools],
            "total": len(tools),
            "agent_ids": registry.get_agent_ids(),
        },
    }


@router.get("/search")
async def search_tools(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    agent_id: str | None = Query(default=None, description="限定 Agent ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """按关键词搜索工具（匹配 tool_id 和 description）"""
    registry = _get_registry()
    results = registry.search_tools(query=q, agent_id=agent_id)
    return {
        "ok": True,
        "data": {
            "items": [_tool_to_dict(t) for t in results],
            "total": len(results),
            "query": q,
        },
    }


@router.get("/llm-schema")
async def get_llm_schema(
    agent_id: str | None = Query(default=None, description="限定 Agent ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """导出 LLM function-calling 格式的工具定义"""
    registry = _get_registry()
    schema = registry.get_tools_for_llm(agent_id=agent_id)
    return {
        "ok": True,
        "data": {
            "tools": schema,
            "total": len(schema),
        },
    }


@router.get("/{tool_id:path}")
async def get_tool(
    tool_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """获取工具定义详情"""
    registry = _get_registry()
    tool = registry.get_tool(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    return {"ok": True, "data": _tool_to_dict(tool)}


@router.post("/{tool_id:path}/invoke")
async def invoke_tool(
    tool_id: str,
    body: InvokeToolRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """调用工具（通过 MasterAgent.dispatch 路由到目标 Agent）"""
    from ..agents.master import MasterAgent
    from ..agents.skills import ALL_SKILL_AGENTS
    from ..services.model_router import ModelRouter

    # 检查工具是否存在及权限
    registry = _get_registry()
    tool_def = registry.get_tool(tool_id)
    if tool_def is None:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    if tool_def.requires_auth:
        logger.warning("tool_invoke_requires_auth", tool_id=tool_id, tenant_id=x_tenant_id)

    # 创建带租户隔离的 MasterAgent
    try:
        model_router = ModelRouter()
    except ValueError:
        logger.warning("tool_invoke_no_model_router", tool_id=tool_id, reason="ANTHROPIC_API_KEY unset")
        model_router = None

    master = MasterAgent(tenant_id=x_tenant_id)
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id=x_tenant_id, db=db, model_router=model_router))

    caller = ToolCaller(master=master, registry=registry, db=db)

    try:
        result = await caller.call_tool(
            tool_id=tool_id,
            params=body.params,
            caller_agent_id=body.caller_agent_id,
            tenant_id=x_tenant_id,
            session_id=body.session_id,
        )
    except ToolCallError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "ok": result.get("success", False),
        "data": result,
        "error": result.get("error"),
    }
