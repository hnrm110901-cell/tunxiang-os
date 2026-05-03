"""第三方开发者 API — API Key 管理 + Webhook 订阅

供 ISV/开发者自助管理集成凭证。
需要 JWT 认证（管理员或开发者角色）。
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_async_session
from shared.apikeys.src.key_service import APIKeyService, APIKeyNotFoundError, APIKeyPermissionError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/developer", tags=["developer"])


# ── 依赖注入 ──────────────────────────────────────────────────────────────

async def _get_tenant_id() -> str:
    """从请求上下文获取 tenant_id（由网关 AuthMiddleware 注入）。"""
    from starlette.requests import Request
    from starlette.routing import request as req_ctx

    request: Request = req_ctx.get()
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")
    return tenant_id


# ── API Key 管理 ──────────────────────────────────────────────────────────


@router.post("/api-keys", summary="创建 API 密钥")
async def create_api_key(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """创建新的 API 密钥。full_key 仅在创建时返回一次。"""
    service = APIKeyService(db, tenant_id)
    try:
        result = await service.create_key(
            name=body.get("name", "My App"),
            permissions=body.get("permissions"),
            rate_limit_rps=body.get("rate_limit_rps", 10),
            expires_at=(
                datetime.fromisoformat(body["expires_at"])
                if body.get("expires_at")
                else None
            ),
        )
        return {"ok": True, "data": result, "error": None}
    except APIKeyPermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api-keys", summary="列出 API 密钥")
async def list_api_keys(
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """列出租户下所有 API 密钥（不返回完整密钥）。"""
    service = APIKeyService(db, tenant_id)
    keys = await service.list_keys()
    return {"ok": True, "data": {"items": keys}, "error": None}


@router.delete("/api-keys/{key_id}", summary="吊销 API 密钥")
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """吊销指定的 API 密钥。"""
    service = APIKeyService(db, tenant_id)
    try:
        await service.revoke_key(key_id)
        return {"ok": True, "data": {"id": str(key_id), "status": "revoked"}, "error": None}
    except APIKeyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Webhook 订阅管理 ──────────────────────────────────────────────────────


@router.post("/webhooks", summary="创建 Webhook 订阅")
async def create_webhook(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """注册 Webhook 订阅。"""
    from shared.apikeys.src.webhook_service import WebhookService

    service = WebhookService(db, tenant_id)
    sub = await service.create_subscription(
        url=body["url"],
        events=body.get("events", ["*"]),
        secret=body.get("secret"),
        api_key_id=(
            uuid.UUID(body["api_key_id"]) if body.get("api_key_id") else None
        ),
        retry_count=body.get("retry_count", 3),
        timeout_ms=body.get("timeout_ms", 5000),
    )
    return {"ok": True, "data": sub, "error": None}


@router.get("/webhooks", summary="列出 Webhook 订阅")
async def list_webhooks(
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """列出租户下所有 Webhook 订阅。"""
    from shared.apikeys.src.webhook_service import WebhookService

    service = WebhookService(db, tenant_id)
    subs = await service.list_subscriptions()
    return {"ok": True, "data": {"items": subs}, "error": None}


@router.delete("/webhooks/{sub_id}", summary="删除 Webhook 订阅")
async def delete_webhook(
    sub_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """删除 Webhook 订阅。"""
    from shared.apikeys.src.webhook_service import WebhookService

    service = WebhookService(db, tenant_id)
    await service.delete_subscription(sub_id)
    return {"ok": True, "data": {"id": str(sub_id), "status": "deleted"}, "error": None}


# ── Webhook 投递日志 ──────────────────────────────────────────────────────


@router.get("/webhooks/logs", summary="Webhook 投递日志")
async def list_delivery_logs(
    status: str = Query(None, description="筛选状态"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_async_session),
    tenant_id: str = Depends(_get_tenant_id),
) -> dict[str, Any]:
    """查询 Webhook 投递记录。"""
    from shared.apikeys.src.webhook_service import WebhookService

    service = WebhookService(db, tenant_id)
    logs = await service.get_delivery_logs(status_filter=status, limit=limit)
    return {"ok": True, "data": {"items": logs}, "error": None}
