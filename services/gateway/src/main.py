"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""
import asyncio
import os

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware import TenantMiddleware, RequestLogMiddleware
from .middleware.audit_middleware import AuditMiddleware
from .proxy import router as proxy_router
from .auth import router as auth_router
from .hub_api import router as hub_router
from .growth_intel_relay import router as relay_router
from .wecom_routes import router as wecom_router
from .wecom_scrm_routes import router as wecom_scrm_router
from .wecom_jssdk import router as wecom_jssdk_router
from .wecom_internal import router as wecom_internal_router
from .wecom_group_routes import router as wecom_group_router
from .wecom_notify_routes import router as wecom_notify_router
from .response import ok

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="TunxiangOS Gateway",
    version="3.0.0",
    description="AI-Native Restaurant Chain Operating System",
)

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
        from .database import get_async_session  # type: ignore[import]
        from .wecom_group_service import WecomGroupService
        from .models.wecom_group import WecomGroupConfig
        from sqlalchemy import select, distinct

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
    _scheduler.start()
    logger.info("gateway_scheduler_started", jobs=["wecom_group_daily_sop @ 09:00 Asia/Shanghai"])


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

# Hub 运维管理 API（必须在 proxy 之前注册，否则被通配路由拦截）
app.include_router(hub_router)

# 情报→增长自动接力 API
app.include_router(relay_router)

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

# 企微群管理与通知推送 API（群创建/列表/发消息/通知/状态）
app.include_router(wecom_notify_router)

# 域路由代理（通配路由 /api/v1/{domain}/{path}，放最后）
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return ok({"service": "gateway", "version": "3.0.0"})


@app.get("/api/v1/domains")
async def list_domains():
    """列出所有域服务及其状态"""
    from .proxy import DOMAIN_ROUTES
    domains = {k: {"configured": bool(v), "url": v or "not configured"} for k, v in DOMAIN_ROUTES.items()}
    return ok(domains)


@app.get("/api/v1/menu-config")
async def get_menu_config(role: str = "admin"):
    """决策4：菜单配置引擎 — 根据角色动态生成菜单树"""
    from .menu_config import generate_menu_for_tenant
    # 全域签约（demo）
    all_domains = ["tx-trade", "tx-menu", "tx-member", "tx-supply", "tx-finance", "tx-org", "tx-analytics", "tx-agent"]
    modules = generate_menu_for_tenant(all_domains, role)
    return ok(modules)
