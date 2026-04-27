"""AI智能路由 — Agent/分析/增长/情报

Sprint 5+ 逐步填充真实逻辑。
"""

from fastapi import APIRouter

from ...shared.response import ok

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


@router.get("/agents")
async def list_agents():
    """Agent列表"""
    return ok(
        {
            "agents": [
                {"id": "discount_guard", "name": "折扣守护", "status": "ready"},
                {"id": "smart_menu", "name": "智能排菜", "status": "ready"},
                {"id": "serve_dispatch", "name": "出餐调度", "status": "ready"},
            ]
        }
    )


@router.get("/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    """Agent健康度"""
    return ok({"agent_id": agent_id, "status": "healthy", "last_run": None})
