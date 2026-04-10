"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
import asyncio
import os

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import AuthMiddleware, TenantMiddleware, RequestLogMiddleware
from .proxy import router as proxy_router
from .api.open_api_routes import router as open_api_router
from .auth import router as auth_router
from .growth_intel_relay import router as relay_router
from .hub_api import router as hub_router
from .middleware import RequestLogMiddleware, TenantMiddleware
from .middleware.audit_middleware import AuditMiddleware
from .proxy import router as proxy_router
from .response import ok
from .wecom_group_routes import router as wecom_group_router
from .wecom_internal import router as wecom_internal_router
from .wecom_jssdk import router as wecom_jssdk_router
from .wecom_notify_routes import router as wecom_notify_router
from .wecom_routes import router as wecom_router
from .wecom_scrm_routes import router as wecom_scrm_router
from .wecom_jssdk import router as wecom_jssdk_router
from .wecom_internal import router as wecom_internal_router
from .wecom_group_routes import router as wecom_group_router
from .gdpr_routes import router as gdpr_router
from .sync_scheduler import create_sync_scheduler, sync_router as sync_health_router
from .wecom_bot_routes import router as wecom_bot_router
from .response import ok

app = FastAPI(title="TunxiangOS Gateway", version="3.0.0", description="AI-Native Restaurant Chain Operating System")

from .personalization_middleware import PersonalizationMiddleware

app.add_middleware(RequestLogMiddleware)
app.add_middleware(PersonalizationMiddleware)  # 千人千面：注入X-User-Segment/Prefs/Subscription
app.add_middleware(TenantMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="TunxiangOS Gateway",
    version="3.0.0",
    description="AI-Native Restaurant Chain Operating System",
)

from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)

# ── APScheduler 定时任务 ──────────────────────────────────────────

_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def _run_daily_sop() -> None:
    """每天 9:00 扫描所有租户的 active 群，执行 daily SOP

    注意：此函数从数据库获取所有活跃租户列表后逐个执行。
    实际部署时需注入数据库会话，此处为集成占位符。
    """
    log = logger.bind(task="wecom_group_daily_sop")
    log.info("wecom_group_daily_sop_job_start")

    try:
        from sqlalchemy import distinct, select

        from .database import get_async_session  # type: ignore[import]
        from .models.wecom_group import WecomGroupConfig
        from .wecom_group_service import WecomGroupService

        service = WecomGroupService()

        async for db in get_async_session():
            # 获取所有有 active 群配置的租户
            stmt = select(distinct(WecomGroupConfig.tenant_id)).where(
                WecomGroupConfig.status == "active"
            )
            result = await db.execute(stmt)
            tenant_ids = result.scalars().all()

            for tenant_id in tenant_ids:
                try:
                    sop_result = await service.scan_and_execute_daily_sop(tenant_id, db)
                    log.info(
                        "wecom_group_daily_sop_tenant_done",
                        tenant_id=str(tenant_id),
                        result=sop_result,
                    )
                except Exception as exc:  # noqa: BLE001 — 单租户失败不阻塞其他租户
                    log.error(
                        "wecom_group_daily_sop_tenant_error",
                        tenant_id=str(tenant_id),
                        error=str(exc),
                        exc_info=True,
                    )
    except ImportError:
        log.warning("wecom_group_daily_sop_db_not_configured")
    except Exception as exc:  # noqa: BLE001 — 最外层兜底，定时任务不能崩溃
        log.error("wecom_group_daily_sop_job_error", error=str(exc), exc_info=True)


@app.on_event("startup")
async def _startup() -> None:
    _scheduler.add_job(
        lambda: asyncio.create_task(_run_daily_sop()),
        "cron",
        hour=9,
        minute=0,
        id="wecom_group_daily_sop",
        replace_existing=True,
    )

    # 品智POS 三商户数据同步调度（czyz/zqx/sgc）
    _sync_scheduler = create_sync_scheduler()
    for job in _sync_scheduler.get_jobs():
        _scheduler.add_job(
            job.func,
            trigger=job.trigger,
            id=job.id,
            replace_existing=True,
            misfire_grace_time=getattr(job, "misfire_grace_time", None),
        )

    _scheduler.start()
    logger.info(
        "gateway_scheduler_started",
        jobs=[
            "wecom_group_daily_sop @ 09:00 Asia/Shanghai",
            "daily_dishes_sync @ 02:00 Asia/Shanghai",
            "daily_master_data_sync @ 03:00 Asia/Shanghai",
            "hourly_orders_incremental_sync",
            "quarter_members_incremental_sync",
        ],
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("gateway_scheduler_stopped")

# Middleware（执行顺序：后添加先执行）
# AuditMiddleware 在 RateLimiter 之后执行（先添加先执行），记录所有敏感路径和4xx/5xx
app.add_middleware(AuditMiddleware)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 认证 API（必须在 proxy 之前注册，否则被通配路由拦截）
app.include_router(auth_router)

app.include_router(hub_router)
app.include_router(relay_router)

# 开放 API（ISV 应用 + OAuth2 client_credentials；依赖 DB 未配置时相关端点返回 503）
app.include_router(open_api_router)

# 企业微信回调 API
app.include_router(wecom_router)

# 企业微信 SCRM 管理 API
app.include_router(wecom_scrm_router)

# 企微 JS-SDK 签名接口（供侧边栏 H5 调用）
app.include_router(wecom_jssdk_router)

# 企微内部发送端点（仅内网微服务调用，不对外暴露）
app.include_router(wecom_internal_router)

# 企微群运营 SOP API
app.include_router(wecom_group_router)

# GDPR 个人信息保护合规 API
app.include_router(gdpr_router)
# 企微群管理与通知推送 API（群创建/列表/发消息/通知/状态）
app.include_router(wecom_notify_router)
# 企微机器人对话入口 API（接收企微消息→NLQ引擎→回答）
app.include_router(wecom_bot_router)
# 品智POS 同步健康检查 API（GET /api/v1/sync/health）
app.include_router(sync_health_router)

# 域路由代理（通配路由 /api/v1/{domain}/{path}，放最后）
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return ok({"service": "gateway", "version": "3.0.0"})


@app.get("/api/v1/domains")
async def list_domains():
    from .proxy import DOMAIN_ROUTES
    domains = {k: {"configured": bool(v), "url": v or "not configured"} for k, v in DOMAIN_ROUTES.items()}
    return ok(domains)


@app.get("/api/v1/menu-config")
async def get_menu_config(role: str = "admin"):
    from .menu_config import generate_menu_for_tenant
    all_domains = ["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent"]
    modules = generate_menu_for_tenant(all_domains, role)
    return ok(modules)
