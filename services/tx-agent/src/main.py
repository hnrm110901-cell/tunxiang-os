"""tx-agent — 域H Agent OS 微服务

Master Agent 编排 + 9 个 Skill Agent + 三条硬约束
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.planner import router as planner_router
from .api.observability import router as observability_router
from .api.voice_routes import router as voice_router
from .routers.diagnosis_router import router as diagnosis_router

app = FastAPI(title="TunxiangOS tx-agent", version="3.0.0", description="Agent OS 微服务")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(planner_router)
app.include_router(observability_router)
app.include_router(voice_router)
app.include_router(diagnosis_router)


@app.get("/health")
async def health():
    return {"ok": True, "data": {"service": "tx-agent", "version": "3.0.0"}}


@app.get("/api/v1/agent/agents")
async def list_agents():
    """列出所有注册的 Agent"""
    from .agents.skills import ALL_SKILL_AGENTS
    return {"ok": True, "data": [
        {"agent_id": a.agent_id, "agent_name": a.agent_name, "priority": a.priority, "run_location": a.run_location}
        for a in ALL_SKILL_AGENTS
    ]}


@app.post("/api/v1/agent/dispatch")
async def dispatch_agent(agent_id: str, action: str, params: dict = {}):
    """调度指定 Agent 执行"""
    from .agents.master import MasterAgent
    from .agents.skills import ALL_SKILL_AGENTS

    master = MasterAgent(tenant_id="default")
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id="default"))

    result = await master.dispatch(agent_id, action, params)
    return {"ok": result.success, "data": {
        "action": result.action,
        "data": result.data,
        "reasoning": result.reasoning,
        "confidence": result.confidence,
        "constraints_passed": result.constraints_passed,
        "execution_ms": result.execution_ms,
    }, "error": result.error}
