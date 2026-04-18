"""Feature Flags 查询 API — Follow-up PR B

端点:
  GET /api/v1/flags?domain={trade|agents|edge|growth|member|org|supply|all}

供 web-pos / web-kds / web-admin 等前端启动时远程拉取灰度配置，
覆盖 featureFlags.ts 的 DEFAULTS 常量。

设计要点:
  - 从 X-Tenant-ID header 提取 tenant_id（独立于 TenantMiddleware，便于测试）
  - 可选 X-User-Role header 提供 role_code 维度
  - 构造 FlagContext 后遍历 domain 下所有 flag，调用 is_enabled(ctx) 逐个评估
  - 进程内 TTL LRU 缓存 60 秒：key = f"{domain}:{tenant_id}:{role_code}"
  - X-Request-Id UUID v4 放 body + header
  - 错误码: 400 INVALID_DOMAIN / 401 AUTH_MISSING / 500 INTERNAL_ERROR
  - 新代码禁用 except Exception（§XIV）
"""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Optional

import structlog
import yaml
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shared.feature_flags.flag_client import FlagContext, get_flag_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/flags", tags=["feature-flags"])


# ────────────────────────────────────────────────────────────────────
# 常量
# ────────────────────────────────────────────────────────────────────

# 允许的 domain 白名单 — 新增 domain 时需在此注册
ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "trade",
    "agents",
    "edge",
    "growth",
    "member",
    "org",
    "supply",
    "all",
})

# 缓存配置：60 秒 TTL，最多 256 条（防止恶意构造 tenant_id 导致内存膨胀）
_CACHE_TTL_SECONDS: float = 60.0
_CACHE_MAX_ENTRIES: int = 256


# ────────────────────────────────────────────────────────────────────
# 进程内 TTL LRU 缓存
# ────────────────────────────────────────────────────────────────────

class _TTLCache:
    """极简 TTL LRU 缓存 — 无第三方依赖。

    - 命中且未过期：返回缓存值并将 key 移到 LRU 尾部
    - 命中但过期：淘汰并返回 None
    - 未命中：返回 None
    - 超过容量：淘汰最老条目
    """

    def __init__(self, ttl: float, max_entries: int) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._store: OrderedDict[str, tuple[float, dict[str, bool]]] = OrderedDict()

    def get(self, key: str) -> Optional[dict[str, bool]]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            # 过期，淘汰
            self._store.pop(key, None)
            return None
        # LRU：移到尾部
        self._store.move_to_end(key)
        # 返回副本防止外部修改污染缓存
        return dict(value)

    def set(self, key: str, value: dict[str, bool]) -> None:
        expires_at = time.monotonic() + self._ttl
        # 存副本，防止外部修改污染缓存
        self._store[key] = (expires_at, dict(value))
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def keys(self) -> list[str]:
        return list(self._store.keys())


_CACHE = _TTLCache(ttl=_CACHE_TTL_SECONDS, max_entries=_CACHE_MAX_ENTRIES)


# ────────────────────────────────────────────────────────────────────
# Pydantic 响应模型
# ────────────────────────────────────────────────────────────────────

class FlagsData(BaseModel):
    flags: dict[str, bool] = Field(
        default_factory=dict,
        description="Flag 名称 → 是否开启 的字典（已按当前 tenant/role 评估）",
    )


class FlagsErrorBody(BaseModel):
    code: str
    message: str


class FlagsResponse(BaseModel):
    ok: bool
    data: Optional[FlagsData] = None
    error: Optional[FlagsErrorBody] = None
    request_id: str = Field(..., description="本次请求唯一 ID（UUID v4）")


# ────────────────────────────────────────────────────────────────────
# 辅助函数
# ────────────────────────────────────────────────────────────────────

def _new_request_id() -> str:
    return str(uuid.uuid4())


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    body = {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message},
        "request_id": request_id,
    }
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"X-Request-Id": request_id},
    )


def _extract_tenant_id(request: Request) -> Optional[str]:
    """优先读 TenantMiddleware 注入的 state，回退到 X-Tenant-ID header。"""
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant:
        return str(state_tenant)
    header_tenant = request.headers.get("X-Tenant-ID")
    if header_tenant:
        return header_tenant.strip() or None
    return None


def _extract_role_code(request: Request) -> Optional[str]:
    """角色从 AuthMiddleware 注入的 request.state.role 或 X-User-Role header 获取。"""
    state_role = getattr(request.state, "role", None)
    if state_role:
        return str(state_role)
    header_role = request.headers.get("X-User-Role")
    if header_role:
        return header_role.strip() or None
    return None


def _build_context(request: Request, tenant_id: str) -> FlagContext:
    """从请求头构造 FlagContext（tenant_id/brand_id/store_id/role_code）。"""
    return FlagContext(
        tenant_id=tenant_id,
        brand_id=request.headers.get("X-Brand-ID") or None,
        store_id=request.headers.get("X-Store-ID") or None,
        role_code=_extract_role_code(request),
        app_version=request.headers.get("X-App-Version") or None,
    )


def _collect_flag_names(domain: str) -> list[str]:
    """根据 domain 返回对应 flag 名称列表。

    domain=all 时聚合所有 ALLOWED_DOMAINS（除 all 自身）。
    可能抛出 yaml.YAMLError / FileNotFoundError / OSError — 由上层捕获转 500。
    """
    client = get_flag_client()
    if domain == "all":
        all_names: set[str] = set()
        for d in ALLOWED_DOMAINS:
            if d == "all":
                continue
            all_names.update(client.list_by_domain(d))
        return sorted(all_names)
    return client.list_by_domain(domain)


def _evaluate_flags(domain: str, context: FlagContext) -> dict[str, bool]:
    """对 domain 下所有 flag 逐个评估，返回 {name: bool} 字典。"""
    client = get_flag_client()
    names = _collect_flag_names(domain)
    result: dict[str, bool] = {}
    for name in names:
        result[name] = client.is_enabled(name, context)
    return result


def _cache_key(domain: str, context: FlagContext) -> str:
    """缓存 key 包含 domain + tenant_id + role_code（灰度规则最常依赖这两维度）。"""
    return f"{domain}:{context.tenant_id or '-'}:{context.role_code or '-'}"


# ────────────────────────────────────────────────────────────────────
# 路由
# ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="按 domain 拉取灰度配置（供前端启动时覆盖 DEFAULTS）",
    response_model=FlagsResponse,
)
async def get_flags_by_domain(
    request: Request,
    domain: str = Query(
        ...,
        description="业务域：trade / agents / edge / growth / member / org / supply / all",
    ),
) -> JSONResponse:
    """返回指定 domain 下所有 flag 经当前 tenant/role 评估后的值。

    响应示例::

        {
          "ok": true,
          "data": {
            "flags": {
              "trade.pos.settle.hardening.enable": true,
              "trade.pos.toast.enable": true,
              "trade.pos.errorBoundary.enable": true
            }
          },
          "error": null,
          "request_id": "9b1a..."
        }
    """
    request_id = _new_request_id()

    # 1. domain 白名单校验
    if domain not in ALLOWED_DOMAINS:
        return _error_response(
            400,
            "INVALID_DOMAIN",
            f"domain must be one of {sorted(ALLOWED_DOMAINS)}",
            request_id,
        )

    # 2. 租户身份校验（未带 X-Tenant-ID 也未被 TenantMiddleware 注入 → 401）
    tenant_id = _extract_tenant_id(request)
    if not tenant_id:
        return _error_response(
            401,
            "AUTH_MISSING",
            "X-Tenant-ID header is required",
            request_id,
        )

    # 3. 构造 FlagContext
    context = _build_context(request, tenant_id)
    cache_key = _cache_key(domain, context)

    # 4. 缓存命中
    cached = _CACHE.get(cache_key)
    if cached is not None:
        logger.debug(
            "flags_cache_hit",
            request_id=request_id,
            domain=domain,
            tenant_id=tenant_id,
            flag_count=len(cached),
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "data": {"flags": cached},
                "error": None,
                "request_id": request_id,
            },
            headers={"X-Request-Id": request_id},
        )

    # 5. 缓存未命中：执行评估
    try:
        flags = _evaluate_flags(domain, context)
    except (yaml.YAMLError, FileNotFoundError, OSError, KeyError) as exc:
        logger.error(
            "flags_evaluate_error",
            request_id=request_id,
            domain=domain,
            tenant_id=tenant_id,
            error=str(exc),
            exc_info=True,
        )
        return _error_response(
            500,
            "INTERNAL_ERROR",
            f"flag evaluation failed: {exc.__class__.__name__}",
            request_id,
        )

    _CACHE.set(cache_key, flags)

    logger.info(
        "flags_evaluated",
        request_id=request_id,
        domain=domain,
        tenant_id=tenant_id,
        role_code=context.role_code,
        flag_count=len(flags),
    )

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "data": {"flags": flags},
            "error": None,
            "request_id": request_id,
        },
        headers={"X-Request-Id": request_id},
    )
