"""tx-agent — 域H Agent OS 微服务

Master Agent 编排 + 9 个 Skill Agent + 三条硬约束
"""
from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from .api.planner import router as planner_router
from .api.observability import router as observability_router
from .api.voice_routes import router as voice_router
from .api.scene_routes import router as scene_router
from .routers.diagnosis_router import router as diagnosis_router
from .routers.pilot_router import router as pilot_router


async def get_db_with_tenant_factory(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖工厂：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session

app = FastAPI(title="TunxiangOS tx-agent", version="3.0.0", description="Agent OS 微服务")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(planner_router)
app.include_router(observability_router)
app.include_router(voice_router)
app.include_router(scene_router)
app.include_router(diagnosis_router)
app.include_router(pilot_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-agent", "version": "3.0.0"}}


@app.get("/api/v1/agent/agents")
async def list_agents(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """列出所有注册的 Agent"""
    from .agents.skills import ALL_SKILL_AGENTS
    return {"ok": True, "data": [
        {"agent_id": a.agent_id, "agent_name": a.agent_name, "priority": a.priority, "run_location": a.run_location}
        for a in ALL_SKILL_AGENTS
    ]}


@app.post("/api/v1/agent/dispatch")
async def dispatch_agent(
    agent_id: str,
    action: str,
    params: dict = {},
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant_factory),
):
    """调度指定 Agent 执行（真实租户 + DB + ModelRouter）"""
    from .agents.master import MasterAgent
    from .agents.skills import ALL_SKILL_AGENTS
    from .services.model_router import ModelRouter

    try:
        model_router = ModelRouter()
    except ValueError:
        # ANTHROPIC_API_KEY 未设置时降级，Agent 回退到规则引擎
        model_router = None

    master = MasterAgent(tenant_id=x_tenant_id)
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id=x_tenant_id, db=db, model_router=model_router))

    result = await master.dispatch(agent_id, action, params)
    return {"ok": result.success, "data": {
        "action": result.action,
        "data": result.data,
        "reasoning": result.reasoning,
        "confidence": result.confidence,
        "constraints_passed": result.constraints_passed,
        "execution_ms": result.execution_ms,
    }, "error": result.error}
