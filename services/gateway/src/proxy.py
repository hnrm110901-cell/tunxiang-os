"""域路由代理 — Strangler Fig 模式，全域切换到新微服务

M4a: Gateway 路由 100% 切换到 tunxiang-os 域微服务。
通用 legacy 回退机制（LEGACY_API_URL）保留，用于未来迁移过渡场景。
（R1 dedup 2026-05-06: 旧 tunxiang-api 单体已删除，LEGACY_URL 当前应留空。）
"""

import os

import httpx
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()
router = APIRouter()

# 全局连接池 — 复用 TCP 连接，避免每次请求新建连接（省 8-25ms）
_http_pool = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30),
    follow_redirects=False,
)

# 域服务注册表 — 全部指向新微服务
DOMAIN_ROUTES = {
    "trade": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    "menu": os.getenv("TX_MENU_URL", "http://localhost:8002"),
    "member": os.getenv("TX_MEMBER_URL", "http://localhost:8003"),
    "growth": os.getenv("TX_GROWTH_URL", "http://localhost:8004"),
    "ops": os.getenv("TX_OPS_URL", "http://localhost:8005"),
    "supply": os.getenv("TX_SUPPLY_URL", "http://localhost:8006"),
    "finance": os.getenv("TX_FINANCE_URL", "http://localhost:8007"),
    "agent": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "analytics": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "brain": os.getenv("TX_BRAIN_URL", "http://localhost:8010"),
    "intel": os.getenv("TX_INTEL_URL", "http://localhost:8011"),
    "org": os.getenv("TX_ORG_URL", "http://localhost:8012"),
    "civic": os.getenv("TX_CIVIC_URL", "http://localhost:8014"),
    "expense": os.getenv("TX_EXPENSE_URL", "http://localhost:8015"),
    # 别名路由：print/* 和 kds/* 均转发到 tx-trade
    "print": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    "kds": os.getenv("TX_TRADE_URL", "http://localhost:8001"),
    # Agent 子域路由（tx-agent:8008）
    "agent-hub": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "agent-monitor": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "stream": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "daily-review": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "master-agent": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    # Analytics 子域路由（tx-analytics:8009）
    "nlq": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "anomaly": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "store-analysis": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "knowledge-query": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "narrative": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "dashboard": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "boss-bi": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    "analysis": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    # Agent 额外子域路由（tx-agent:8008）
    "store-health": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    "orchestrate": os.getenv("TX_AGENT_URL", "http://localhost:8008"),
    # Supply 子域路由（tx-supply:8006）
    "procurement-recommend": os.getenv("TX_SUPPLY_URL", "http://localhost:8006"),
    # Insights routes (tx-analytics:8009)
    "insights": os.getenv("TX_ANALYTICS_URL", "http://localhost:8009"),
    # 支付中枢（tx-pay:8016）
    "pay": os.getenv("TX_PAY_URL", "http://localhost:8016"),
    # DevForge 内部研发运维平台（tx-devforge:8017）
    # 与 tx-forge（外部 ISV 市场）严格区分
    "devforge": os.getenv("TX_DEVFORGE_URL", "http://localhost:8017"),
    # Forge 外部 ISV 应用市场（tx-forge:8013）
    # 与 tx-devforge（内部研发平台 :8017）严格区分
    # 端口：8013 容器内（Docker DNS 隔离，与 tx-predict 同号不冲突）
    "forge": os.getenv("TX_FORGE_URL", "http://localhost:8013"),
}

# 旧单体回退（M4a 后可移除）
LEGACY_URL = os.getenv("LEGACY_API_URL", "")


async def _proxy(request: Request, target_url: str) -> JSONResponse:
    """转发请求到目标服务"""
    if not target_url:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "data": None,
                "error": {"code": "SERVICE_UNAVAILABLE", "message": "Target service not configured"},
            },
        )

    try:
        url = f"{target_url}{request.url.path}"
        # 审计 S-02（P0）：剥客户端可控的认证 header，从 request.state 重注入。
        # AuthMiddleware 已在 request.state.{tenant_id,user_id,role} 写入受信值；
        # 任何客户端传入的 X-Tenant-ID / X-Internal-* 都视为伪造直接覆盖，
        # 防止经 gateway 后伪造租户绕 RLS。
        # Authorization 仍透传（下游 ApiKey 中间件 / 审计日志可能需要原 JWT），
        # 但下游应优先信任由 gateway 重注入的 X-Tenant-ID / X-Internal-JWT。
        #
        # 独立 review P0-3：exempt 路径（/health / /docs / /api/v1/auth/* 等）
        # AuthMiddleware 不会设 request.state.tenant_id —— 此时若按上述逻辑剥
        # 客户端 X-Tenant-ID 后发现 state 上没有受信值，X-Tenant-ID header 会
        # 静默丢失，下游收到空头反而比之前更糟。
        # 处理：以 auth_method 是否被设值（非 None / 非空）作为"已认证"信号；
        # 未认证（exempt 路径）一律透传原 headers，不引入新的隐患。
        auth_method = getattr(request.state, "auth_method", None)
        is_authenticated = bool(auth_method)
        if not is_authenticated:
            # Exempt / 未认证路径：保持向后兼容（透传原 headers，不剥不注入）。
            #
            # 独立 review P0-3 安全论证：当前 exempt 路径（_is_exempt 列表）含
            # /health, /docs, /api/v1/auth/*, /api/v1/wecom/callback 等。这些路径
            # 由 gateway 自身路由处理（auth_router / wecom_router 在 FastAPI 路由
            # 优先级上先于 proxy_router 的 catch-all `/api/v1/{domain}/{path:path}`），
            # 不会经过本 _proxy 函数转发到下游 tx-* 服务，因此透传客户端
            # X-Tenant-ID 不构成下游伪造攻击面。
            #
            # ⚠️ 维护风险：若将来新增"经 proxy 转发的 exempt 路径"
            # （例如某个公开 API 走 domain 路由 + 加入 exempt），透传会再次
            # 打开 S-02 攻击面。新增此类路径必须同步审计本逻辑。
            headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        else:
            _STRIP = {
                "host",
                "content-length",
                "x-tenant-id",
                "x-internal-user-id",
                "x-internal-role",
                "x-internal-jwt",
            }
            headers = {k: v for k, v in request.headers.items() if k.lower() not in _STRIP}
            trusted_tenant_id = getattr(request.state, "tenant_id", "") or ""
            if trusted_tenant_id:
                headers["X-Tenant-ID"] = str(trusted_tenant_id)
            trusted_user_id = getattr(request.state, "user_id", "") or ""
            if trusted_user_id:
                headers["X-Internal-User-Id"] = str(trusted_user_id)
            trusted_role = getattr(request.state, "role", "") or ""
            if trusted_role:
                headers["X-Internal-Role"] = str(trusted_role)
            # 短期 HS256 内部 JWT —— 下游服务可挂 InternalJwtMiddleware 校验
            # （独立 review P1-4：当前下游中间件未部署，本 token 仅签不验，
            #  S-02 完成度 50%；follow-up tracker 在 docs/security/）
            try:
                from shared.security.src.internal_jwt import mint_internal_jwt

                internal_jwt = mint_internal_jwt(
                    tenant_id=str(trusted_tenant_id),
                    user_id=str(trusted_user_id),
                    role=str(trusted_role),
                )
                if internal_jwt:
                    headers["X-Internal-JWT"] = internal_jwt
            except ImportError:
                # helper 尚未部署到环境时降级 — 不阻塞 proxy
                pass
        body = await request.body()

        resp = await _http_pool.request(
            method=request.method,
            url=url,
            headers=headers,
            params=dict(request.query_params),
            content=body if body else None,
        )
        try:
            body_json = resp.json()
        except (ValueError, UnicodeDecodeError):
            # 下游返回非 JSON body（nginx 502 plain-text / KDS ESC/POS 二进制 / 异常文本）
            # 保留下游 status code（不强制 502），log 原始 body 前 200 字节 + upstream URL
            body_preview = resp.content[:200].decode("utf-8", errors="replace") if resp.content else ""
            logger.warning(
                "proxy_non_json_response",
                target=target_url,
                path=request.url.path,
                upstream_status=resp.status_code,
                body_preview=body_preview,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content={
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "UPSTREAM_NON_JSON",
                        "message": "Upstream returned non-JSON response",
                        "upstream_status": resp.status_code,
                    },
                },
            )
        return JSONResponse(status_code=resp.status_code, content=body_json)
    except httpx.ConnectError:
        logger.warning("service_unreachable", target=target_url, path=request.url.path)
        # 回退到旧单体
        if LEGACY_URL:
            return await _proxy(request, LEGACY_URL)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "data": None, "error": {"code": "SERVICE_DOWN", "message": "Service unreachable"}},
        )
    except httpx.TimeoutException as e:
        logger.warning("proxy_timeout", target=target_url, path=request.url.path, error=str(e))
        return JSONResponse(
            status_code=504,
            content={
                "ok": False,
                "data": None,
                "error": {"code": "PROXY_TIMEOUT", "message": "Upstream service timeout"},
            },
        )
    except httpx.HTTPError as e:
        logger.error("proxy_http_error", target=target_url, error=str(e))
        return JSONResponse(
            status_code=502,
            content={"ok": False, "data": None, "error": {"code": "PROXY_ERROR", "message": str(e)}},
        )
    except (ValueError, KeyError, UnicodeDecodeError, OSError) as e:
        logger.error("proxy_unexpected_error", error=str(e), error_type=type(e).__name__, exc_info=True)
        return JSONResponse(
            status_code=502,
            content={"ok": False, "data": None, "error": {"code": "PROXY_ERROR", "message": "Internal proxy error"}},
        )


@router.api_route("/api/v1/{domain}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def domain_proxy(request: Request, domain: str, path: str):
    """按域路由到对应微服务"""
    target = DOMAIN_ROUTES.get(domain, "")
    if not target and LEGACY_URL:
        target = LEGACY_URL
    return await _proxy(request, target)
