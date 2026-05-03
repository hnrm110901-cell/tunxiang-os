"""Sprint E3 — 小红书核销 API

端点：
  POST /api/v1/trade/delivery/xhs/webhook
    小红书核销推送入口；校验签名 + 转 canonical

  POST /api/v1/trade/delivery/xhs/oauth/callback
    OAuth 授权回调（code → token）

  POST /api/v1/trade/delivery/xhs/oauth/{binding_id}/refresh
    手动刷新 token

  POST /api/v1/trade/delivery/xhs/bindings
    创建 store ↔ xhs shop 绑定（预绑定 webhook_secret）

  GET  /api/v1/trade/delivery/xhs/bindings
    列出绑定

  DELETE /api/v1/trade/delivery/xhs/bindings/{id}
    解绑（软删）

  GET  /api/v1/trade/delivery/xhs/events
    查询 webhook 事件历史（含签名失败/transform 失败）
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.xiaohongshu.src.oauth_token_service import (
    TokenPair,
    XhsOAuthError,
    XhsOAuthTokenService,
)
from shared.ontology.src.database import get_db

from ..services.xiaohongshu_verification_service import XhsVerificationService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/trade/delivery/xhs",
    tags=["trade-delivery-xhs"],
)

# XHS OAuth credentials — must be injected via environment variables
_XHS_APP_SECRET = os.getenv("XHS_APP_SECRET", "")


# ── 请求模型 ─────────────────────────────────────────────────────


class BindingCreateRequest(BaseModel):
    store_id: str = Field(..., description="内部门店 UUID")
    brand_id: Optional[str] = None
    xhs_shop_code: str = Field(..., min_length=1, max_length=64)
    xhs_merchant_id: str = Field(..., min_length=1, max_length=64)
    xhs_shop_name: Optional[str] = Field(default=None, max_length=200)
    webhook_secret: Optional[str] = Field(
        default=None,
        description="留空则自动生成 32 位随机密钥；否则使用商家自定义",
        max_length=128,
    )
    webhook_url: Optional[str] = None


class OAuthCallbackRequest(BaseModel):
    binding_id: str = Field(..., description="binding UUID")
    code: str = Field(..., min_length=1)
    redirect_uri: Optional[str] = None


# ── 端点 ────────────────────────────────────────────────────────


@router.post("/webhook", response_model=dict)
async def receive_webhook(
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """小红书 webhook 推送入口

    注意：小红书平台不会主动带 X-Tenant-ID；实际部署时由 nginx / gateway
    根据 shop_code 映射到 tenant_id 后再转发。本 PR 保持 X-Tenant-ID 显式传入，
    保持与其他端点契约一致，gateway 层做映射。
    """
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    body_bytes = await request.body()
    # 把 headers 规范化成 lowercase dict（FastAPI header case-insensitive）
    headers = {k.lower(): v for k, v in request.headers.items()}
    source_ip = request.client.host if request.client else None

    service = XhsVerificationService(db, tenant_id=x_tenant_id)
    try:
        outcome = await service.process_webhook(
            body=body_bytes, headers=headers, source_ip=source_ip
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("xhs_webhook_db_error")
        raise HTTPException(
            status_code=500, detail=f"DB 错误: {exc}"
        ) from exc

    # 即便签名校验失败也返回 200，避免平台重试（事件已归档）
    return {"ok": True, "data": outcome.to_dict()}


@router.post("/oauth/callback", response_model=dict)
async def oauth_callback(
    req: OAuthCallbackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """OAuth 授权回调：code → token"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(req.binding_id, "binding_id")

    if not _XHS_APP_SECRET:
        logger.warning("xhs_oauth_not_configured", extra={"reason": "XHS_APP_SECRET not set"})
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "XHS integration not configured"},
        )

    binding = await _fetch_binding(db, x_tenant_id, req.binding_id)
    if not binding:
        raise HTTPException(status_code=404, detail="binding 不存在")

    # 从 env / config 读取 app_id / app_secret（当前用占位）
    # 真实部署：KMS 解密 + 单租户 app 凭证
    oauth_service = XhsOAuthTokenService(
        app_id=binding.get("xhs_merchant_id", "stub_app_id"),
        app_secret=_XHS_APP_SECRET,  # injected from XHS_APP_SECRET env var
    )

    try:
        token_pair: TokenPair = await oauth_service.exchange_code_for_token(
            code=req.code, redirect_uri=req.redirect_uri
        )
    except XhsOAuthError as exc:
        logger.warning("xhs_oauth_exchange_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=400, detail=f"OAuth 失败: {exc}"
        ) from exc

    # 更新 binding：status=active + token
    try:
        await db.execute(
            text("""
                UPDATE xiaohongshu_shop_bindings SET
                    access_token = :access,
                    refresh_token = :refresh,
                    token_expires_at = :expires_at,
                    scope = :scope,
                    status = 'active',
                    consecutive_auth_errors = 0,
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {
                "access": token_pair.access_token,
                "refresh": token_pair.refresh_token,
                "expires_at": token_pair.expires_at,
                "scope": token_pair.scope,
                "id": req.binding_id,
                "tenant_id": x_tenant_id,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("xhs_binding_update_failed")
        raise HTTPException(
            status_code=500, detail=f"binding 更新失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "binding_id": req.binding_id,
            "status": "active",
            "token_expires_at": token_pair.expires_at.isoformat(),
            "scope": token_pair.scope,
        },
    }


@router.post("/oauth/{binding_id}/refresh", response_model=dict)
async def refresh_oauth_token(
    binding_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动刷新 access_token（定时 worker 也可调）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(binding_id, "binding_id")

    if not _XHS_APP_SECRET:
        logger.warning("xhs_oauth_not_configured", extra={"reason": "XHS_APP_SECRET not set"})
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "XHS integration not configured"},
        )

    binding = await _fetch_binding(db, x_tenant_id, binding_id)
    if not binding:
        raise HTTPException(status_code=404, detail="binding 不存在")
    if not binding.get("refresh_token"):
        raise HTTPException(
            status_code=400, detail="refresh_token 缺失，需重新走 OAuth"
        )

    oauth_service = XhsOAuthTokenService(
        app_id=binding.get("xhs_merchant_id", "stub_app_id"),
        app_secret=_XHS_APP_SECRET,  # injected from XHS_APP_SECRET env var
    )
    try:
        token_pair = await oauth_service.refresh_access_token(
            refresh_token=binding["refresh_token"]
        )
    except XhsOAuthError as exc:
        # 刷新失败 → 标记 expired
        await db.execute(
            text("""
                UPDATE xiaohongshu_shop_bindings SET
                    status = 'expired',
                    consecutive_auth_errors = consecutive_auth_errors + 1,
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": binding_id},
        )
        await db.commit()
        raise HTTPException(
            status_code=400, detail=f"刷新失败: {exc}"
        ) from exc

    await db.execute(
        text("""
            UPDATE xiaohongshu_shop_bindings SET
                access_token = :access,
                refresh_token = :refresh,
                token_expires_at = :expires_at,
                scope = :scope,
                status = 'active',
                consecutive_auth_errors = 0,
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
        """),
        {
            "access": token_pair.access_token,
            "refresh": token_pair.refresh_token,
            "expires_at": token_pair.expires_at,
            "scope": token_pair.scope,
            "id": binding_id,
        },
    )
    await db.commit()

    return {
        "ok": True,
        "data": {
            "binding_id": binding_id,
            "token_expires_at": token_pair.expires_at.isoformat(),
        },
    }


@router.post("/bindings", response_model=dict, status_code=201)
async def create_binding(
    req: BindingCreateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建 store ↔ xhs shop 绑定（预绑定，需走 OAuth 后 status='active'）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(req.store_id, "store_id")
    if req.brand_id:
        _parse_uuid(req.brand_id, "brand_id")

    webhook_secret = req.webhook_secret or secrets.token_urlsafe(32)

    try:
        row = await db.execute(
            text("""
                INSERT INTO xiaohongshu_shop_bindings (
                    tenant_id, store_id, brand_id, xhs_shop_code,
                    xhs_merchant_id, xhs_shop_name, webhook_secret,
                    webhook_url, status
                ) VALUES (
                    CAST(:tenant_id AS uuid), CAST(:store_id AS uuid),
                    CAST(:brand_id AS uuid), :shop_code,
                    :merchant_id, :shop_name, :secret,
                    :webhook_url, 'pending'
                )
                RETURNING id
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": req.store_id,
                "brand_id": req.brand_id,
                "shop_code": req.xhs_shop_code,
                "merchant_id": req.xhs_merchant_id,
                "shop_name": req.xhs_shop_name,
                "secret": webhook_secret,
                "webhook_url": req.webhook_url,
            },
        )
        binding_id = str(row.scalar_one())
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("xhs_binding_create_failed")
        raise HTTPException(
            status_code=500, detail=f"binding 创建失败（可能重复 store/shop_code）: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "binding_id": binding_id,
            "xhs_shop_code": req.xhs_shop_code,
            "status": "pending",
            # 仅首次返回 webhook_secret；前端存到小红书后台
            "webhook_secret": webhook_secret,
        },
    }


@router.get("/bindings", response_model=dict)
async def list_bindings(
    status: Optional[str] = None,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出本租户所有 xhs 绑定"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")

    conditions = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    try:
        rows = await db.execute(
            text(f"""
                SELECT id, store_id, brand_id, xhs_shop_code, xhs_merchant_id,
                       xhs_shop_name, status, token_expires_at,
                       last_webhook_at, consecutive_auth_errors,
                       created_at, updated_at
                FROM xiaohongshu_shop_bindings
                WHERE {where}
                ORDER BY created_at DESC
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("xhs_bindings_list_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {"items": items, "total": len(items)},
    }


@router.delete("/bindings/{binding_id}", response_model=dict)
async def unbind(
    binding_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删 binding（status='unbound' + is_deleted=true）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(binding_id, "binding_id")

    try:
        row = await db.execute(
            text("""
                UPDATE xiaohongshu_shop_bindings SET
                    status = 'unbound',
                    is_deleted = true,
                    access_token = NULL,
                    refresh_token = NULL,
                    updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
                RETURNING id
            """),
            {"id": binding_id, "tenant_id": x_tenant_id},
        )
        result = row.mappings().first()
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("xhs_binding_unbind_failed")
        raise HTTPException(
            status_code=500, detail=f"解绑失败: {exc}"
        ) from exc

    if not result:
        raise HTTPException(status_code=404, detail="binding 不存在或已解绑")

    return {
        "ok": True,
        "data": {"binding_id": binding_id, "status": "unbound"},
    }


@router.get("/events", response_model=dict)
async def list_events(
    binding_id: Optional[str] = None,
    transform_status: Optional[str] = None,
    signature_valid: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=500),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询 webhook 事件历史（审计 + 故障排查）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if binding_id:
        _parse_uuid(binding_id, "binding_id")

    conditions = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict[str, Any] = {"tenant_id": x_tenant_id, "limit": limit}
    if binding_id:
        conditions.append("binding_id = CAST(:binding_id AS uuid)")
        params["binding_id"] = binding_id
    if transform_status:
        conditions.append("transform_status = :t_status")
        params["t_status"] = transform_status
    if signature_valid is not None:
        conditions.append("signature_valid = :sig_valid")
        params["sig_valid"] = signature_valid

    where = " AND ".join(conditions)

    try:
        rows = await db.execute(
            text(f"""
                SELECT id, binding_id, event_type, verify_code, xhs_shop_code,
                       xhs_order_id, signature_valid, signature_error,
                       transform_status, canonical_order_id, transform_error,
                       received_at, processed_at
                FROM xiaohongshu_verify_events
                WHERE {where}
                ORDER BY received_at DESC
                LIMIT :limit
            """),
            params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("xhs_events_list_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {"items": items, "count": len(items)},
    }


# ── 辅助 ─────────────────────────────────────────────────────────


async def _fetch_binding(
    db: AsyncSession, tenant_id: str, binding_id: str
) -> Optional[dict[str, Any]]:
    row = await db.execute(
        text("""
            SELECT id, store_id, brand_id, xhs_shop_code, xhs_merchant_id,
                   webhook_secret, access_token, refresh_token, status
            FROM xiaohongshu_shop_bindings
            WHERE id = CAST(:id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
              AND is_deleted = false
            LIMIT 1
        """),
        {"id": binding_id, "tenant_id": tenant_id},
    )
    rec = row.mappings().first()
    return dict(rec) if rec else None


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
