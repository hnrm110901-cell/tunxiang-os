"""tx-agent — 域H Agent OS 微服务

Master Agent 编排 + 9 个 Skill Agent + 三条硬约束
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from .agents.domain_event_consumer import DomainEventConsumer
from .api.agent_monitor_routes import router as agent_monitor_router
from .api.daily_review_routes import router as daily_review_router
from .api.master_agent_routes import router as master_agent_router
from .api.projector_routes import router as projector_router
from .api.dashboard_routes import router as dashboard_router
from .api.health_routes import router as health_router
from .api.inventory_routes import router as inventory_router
from .api.notification_routes import router as notification_router
from .api.observability import router as observability_router
from .api.operation_plan_routes import router as operation_plan_router
from .api.orchestrator_routes import router as orchestrator_router
from .api.planner import router as planner_router
from .api.specials_routes import router as specials_router
from .api.store_clone_routes import router as store_clone_router
from .api.store_health_routes import router as store_health_router
from .api.stream_routes import router as stream_router
from .api.voice_routes import router as voice_router
from .api.skill_registry_routes import router as skill_registry_router
from .api.skill_context_routes import router as skill_context_router
from .api.discount_guard_enhanced_routes import router as discount_guard_enhanced_router
from .api.agent_hub_routes import router as agent_hub_router
from .routers.diagnosis_router import router as diagnosis_router
from .routers.pilot_router import router as pilot_router


async def get_db_with_tenant_factory(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    """依赖工厂：从 X-Tenant-ID header 提取租户 ID，返回带 RLS 隔离的 DB session。"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期：启动时运行 DomainEventConsumer 后台任务，关闭时优雅停止。"""
    from .agents.handler_factory import AgentEventHandlerFactory
    from .agents.master import MasterAgent
    from .agents.skills import ALL_SKILL_AGENTS

    # 创建 MasterAgent 并注册所有 Skill Agents（无 DB/ModelRouter，事件驱动场景）
    # 需要 DB 的 Agent 在具体 action 中自行处理降级；ModelRouter 按需在 execute() 内初始化
    master = MasterAgent(tenant_id="system")
    for cls in ALL_SKILL_AGENTS:
        master.register(cls(tenant_id="system"))

    # 用真实 handler 创建 EventBus（替代占位 handler）
    factory = AgentEventHandlerFactory(master)
    event_bus = factory.build_event_bus()

    consumer = DomainEventConsumer(event_bus, master_agent=master)
    consumer_task = asyncio.create_task(consumer.run())

    # ── Skill-aware EventBus（并行运行，与 DomainEventConsumer 互不干扰）──
    import os as _os2
    from shared.skill_registry import SkillRegistry
    from shared.skill_registry.src.skill_event_consumer import SkillEventConsumer
    from .agents.skill_handlers import (
        handle_order_skill_events,
        handle_member_skill_events,
        handle_inventory_skill_events,
        handle_safety_skill_events,
        handle_finance_skill_events,
        handle_approval_skill_events,
    )

    # 扫描所有 Skill（services/ 目录）
    _skills_root = _os2.path.join(
        _os2.path.dirname(_os2.path.dirname(_os2.path.dirname(_os2.path.dirname(__file__)))),
        "services",
    )
    skill_registry = SkillRegistry([_skills_root])
    skill_registry.scan()

    redis_url = _os2.getenv("REDIS_URL", "redis://localhost:6379")
    skill_consumer = SkillEventConsumer(redis_url=redis_url, registry=skill_registry)

    # 注册 handlers（按 Skill 名称注册）
    skill_consumer.register_handler("order-core", handle_order_skill_events)
    skill_consumer.register_handler("member-core", handle_member_skill_events)
    skill_consumer.register_handler("inventory-core", handle_inventory_skill_events)
    skill_consumer.register_handler("safety-compliance", handle_safety_skill_events)
    skill_consumer.register_handler("deposit-management", handle_finance_skill_events)
    skill_consumer.register_handler("wine-storage", handle_finance_skill_events)
    skill_consumer.register_handler("credit-account", handle_finance_skill_events)
    skill_consumer.register_handler("approval-flow", handle_approval_skill_events)

    skill_consumer_task = asyncio.create_task(skill_consumer.start())

    # ── Phase 2 投影器启动（Event Sourcing → 物化视图）──
    # 从 PROJECTOR_TENANT_IDS 环境变量读取需要运行投影器的租户列表
    # 格式：逗号分隔的 UUID 字符串，如 "uuid1,uuid2"
    import os as _os
    from .services.projector_runner import get_runner

    projector_tenant_ids = [
        t.strip() for t in _os.getenv("PROJECTOR_TENANT_IDS", "").split(",")
        if t.strip()
    ]
    runner = get_runner()
    if projector_tenant_ids:
        await runner.start(tenant_ids=projector_tenant_ids)

    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        await skill_consumer.stop()
        skill_consumer_task.cancel()
        try:
            await skill_consumer_task
        except asyncio.CancelledError:
            pass
        # 停止所有投影器
        await runner.stop()


app = FastAPI(
    title="TunxiangOS tx-agent",
    version="3.0.0",
    description="Agent OS 微服务",
    lifespan=lifespan,
)

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:5176,http://localhost:5180").split(","), allow_methods=["*"], allow_headers=["*"])
app.include_router(planner_router)
app.include_router(observability_router)
app.include_router(voice_router)
app.include_router(orchestrator_router)
app.include_router(operation_plan_router)
app.include_router(notification_router)
app.include_router(stream_router)
app.include_router(health_router)
app.include_router(store_clone_router)
app.include_router(diagnosis_router)
app.include_router(pilot_router)
app.include_router(daily_review_router)
app.include_router(dashboard_router)
app.include_router(specials_router)
app.include_router(inventory_router)
app.include_router(agent_monitor_router)
app.include_router(store_health_router)
app.include_router(master_agent_router)
app.include_router(projector_router)
app.include_router(skill_registry_router)
app.include_router(skill_context_router)
app.include_router(discount_guard_enhanced_router)
app.include_router(agent_hub_router)


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
