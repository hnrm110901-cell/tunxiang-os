"""TunxiangOS API Gateway — 统一入口，按域路由到各微服务"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.observability import setup_metrics

from shared.middleware.src.metrics_auth import MetricsAuthMiddleware

from .api.config_health_routes import router as config_health_router
from .api.demo_healthcheck_routes import router as demo_healthcheck_router  # Week 3 演示巡检
from .api.flags_routes import router as flags_router  # Follow-up PR B — 灰度配置下发
from .api.migration_routes import router as migration_router
from .api.onboarding_routes import router as onboarding_router
from .api.open_api_routes import router as open_api_router
from .auth import router as auth_router
from .gdpr_routes import router as gdpr_router
from .group_ops_routes import router as group_ops_router
from .growth_intel_relay import router as relay_router
from .hub_api import router as hub_router
from .material_routes import router as material_router
from .middleware import AuthMiddleware, RequestLogMiddleware, TenantMiddleware
from .middleware.api_key_middleware import ApiKeyMiddleware
from .middleware.audit_middleware import AuditMiddleware
from .middleware.domain_authz_middleware import DomainAuthzMiddleware
from .personalization_middleware import PersonalizationMiddleware
from .proxy import router as proxy_router
from .response import ok
from .sync_scheduler import sync_router as sync_health_router
from .wecom_bot_routes import router as wecom_bot_router
from .wecom_group_routes import router as wecom_group_router
from .wecom_internal import router as wecom_internal_router
from .wecom_jssdk import router as wecom_jssdk_router
from .wecom_notify_routes import router as wecom_notify_router
from .wecom_routes import router as wecom_router
from .wecom_scrm_routes import router as wecom_scrm_router

app = FastAPI(
    title="TunxiangOS Gateway",
    version="3.0.0",
    description="AI-Native Restaurant Chain Operating System",
)

# Phase C.3 (#820) — 统一 metrics 入口, 22 service 渐进迁移 (follow-up #820-I)
setup_metrics(app, service_name="gateway")

# 中间件：先 add 的层更靠近路由；最后 add 的层最先收到请求。
# 目标入站链：CORS → MetricsAuth → Audit → 日志 → ApiKey → Auth → DomainAuthz → Tenant → Personalization → 路由
# CORSMiddleware 必须最后 add（最外层），OPTIONS preflight 在此直接 204 返回，不进认证链。
# MetricsAuthMiddleware 紧靠 CORS 内侧 (issue #825): /metrics 走 Bearer + IP allowlist;
# AuthMiddleware AUTH_EXEMPT_PREFIXES 已加 "/metrics" 双保险, 即便 MetricsAuth 绕过也不会 401.
app.add_middleware(PersonalizationMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(DomainAuthzMiddleware)  # 域级授权 + MFA（必须在 Auth 内侧，认证完成后执行）
app.add_middleware(AuthMiddleware)
app.add_middleware(ApiKeyMiddleware)  # ApiKey 必须外于 Auth（先处理 X-API-Key 再进入 JWT 校验）
app.add_middleware(RequestLogMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(MetricsAuthMiddleware)  # /metrics Bearer + IP allowlist (issue #825)
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

# 社群运营工具 API（标签管理 + 群发任务）
app.include_router(group_ops_router)
# 企业素材库 API（分组 + 素材 CRUD + 时段匹配）
app.include_router(material_router)

# GDPR 个人信息保护合规 API
app.include_router(gdpr_router)
# 企微群管理与通知推送 API（群创建/列表/发消息/通知/状态）
app.include_router(wecom_notify_router)
# 企微机器人对话入口 API（接收企微消息→NLQ引擎→回答）
app.include_router(wecom_bot_router)
# 品智POS 同步健康检查 API（GET /api/v1/sync/health）
app.include_router(sync_health_router)
# 演示前一键巡检 API（GET /api/v1/demo/health-check）— Week 3 P0
app.include_router(demo_healthcheck_router)

# Feature Flags 下发 API（GET /api/v1/flags?domain=xxx）— Follow-up PR B
app.include_router(flags_router)

# C-04: 演示监控面板
from .api.demo_monitor_routes import router as demo_monitor_router

app.include_router(demo_monitor_router)  # C-04: 演示监控面板

# 上线交付 API（DeliveryAgent 20问 + 配置包导入）
app.include_router(onboarding_router)

# 配置健康度检查 API（上线前门控，score ≥ 90 才允许上线）
app.include_router(config_health_router)

# 天财商龙迁移 API（菜品/会员/配置映射 + 储值审核）
app.include_router(migration_router)

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
