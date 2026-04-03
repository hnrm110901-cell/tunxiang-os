"""开放API平台路由 — ISV接入管理 + OAuth2端点

端点清单:
  POST   /open-api/applications              — 注册ISV应用（需租户认证）
  GET    /open-api/applications              — 列出应用（分页）
  GET    /open-api/applications/{app_id}     — 应用详情
  DELETE /open-api/applications/{app_id}     — 吊销应用
  POST   /open-api/oauth/token               — 颁发access_token (client_credentials)
  POST   /open-api/oauth/revoke              — 吊销token
  POST   /open-api/oauth/rotate              — 轮换app_secret
  GET    /open-api/applications/{app_id}/logs — 请求日志（分页）
"""

import time
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.rate_limiter import RateLimiter
from ..services.oauth2_service import OAuth2Service

logger = structlog.get_logger()

router = APIRouter(prefix="/open-api", tags=["open-api"])

_oauth2_service = OAuth2Service()
_rate_limiter = RateLimiter()


# ── 依赖注入 ───────────────────────────────────────────────────────

async def get_db() -> AsyncSession:  # type: ignore[return]
    """获取DB会话（由实际数据库模块提供，此处为接口占位）"""
    try:
        from ..database import get_async_session  # type: ignore[import]
        async for session in get_async_session():
            yield session
    except ImportError:
        raise HTTPException(status_code=503, detail="数据库模块未配置")


def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    """从X-Tenant-ID header解析租户UUID"""
    try:
        return UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID格式无效，必须为UUID") from exc


async def verify_bearer_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    required_scope: str | None = None,
) -> dict:
    """验证Authorization: Bearer <token>"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少Bearer token")

    raw_token = auth_header[len("Bearer "):]
    token_info = await _oauth2_service.verify_token(raw_token, required_scope, db)
    if not token_info:
        raise HTTPException(status_code=401, detail="token无效、已过期或已吊销")

    # 速率限制检查
    app_id = token_info["app_id"]
    limit_per_min = request.state.__dict__.get("rate_limit", 60)
    allowed, remaining, reset_at = await _rate_limiter.check_rate_limit(app_id, limit_per_min)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="请求频率超限",
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_at),
                "Retry-After": str(reset_at - int(time.time())),
            },
        )

    return token_info


# ── Pydantic请求/响应模型 ──────────────────────────────────────────

class CreateApplicationRequest(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=100, description="应用名称")
    scopes: list[str] = Field(default=[], description="授权范围列表")
    description: Optional[str] = Field(None, description="应用描述")
    contact_email: Optional[str] = Field(None, description="联系邮箱")
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000, description="每分钟限速")


class IssueTokenRequest(BaseModel):
    grant_type: str = Field(default="client_credentials", description="必须为client_credentials")
    app_key: str = Field(..., description="应用的app_key")
    app_secret: str = Field(..., description="应用的app_secret（明文）")
    scope: Optional[str] = Field(None, description="空格分隔的scope列表")


class RevokeTokenRequest(BaseModel):
    token: str = Field(..., description="要吊销的access_token")


class RotateSecretRequest(BaseModel):
    app_id: str = Field(..., description="要轮换secret的应用ID")


# ── 应用管理端点 ──────────────────────────────────────────────────

@router.post("/applications", status_code=201)
async def create_application(
    body: CreateApplicationRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """注册ISV应用。

    返回app_key和app_secret，明文secret只此一次。
    """
    result = await _oauth2_service.create_application(
        tenant_id=tenant_id,
        app_name=body.app_name,
        scopes=body.scopes,
        contact_email=body.contact_email,
        db=db,
        description=body.description,
        rate_limit_per_min=body.rate_limit_per_min,
    )
    return {"ok": True, "data": result}


@router.get("/applications")
async def list_applications(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
    """列出租户的所有ISV应用（分页）"""
    result = await _oauth2_service.list_applications(
        tenant_id=tenant_id,
        db=db,
        page=page,
        size=size,
        status=status,
    )
    return {"ok": True, "data": result}


@router.get("/applications/{app_id}")
async def get_application(
    app_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取单个ISV应用详情"""
    app = await _oauth2_service.get_application(app_id, tenant_id, db)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"ok": True, "data": app}


@router.delete("/applications/{app_id}")
async def revoke_application(
    app_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """吊销ISV应用，同时吊销所有关联token"""
    success = await _oauth2_service.revoke_application(app_id, tenant_id, db)
    if not success:
        raise HTTPException(status_code=404, detail="应用不存在")
    return {"ok": True, "data": {"app_id": str(app_id), "status": "revoked"}}


@router.get("/applications/{app_id}/logs")
async def get_application_logs(
    app_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """获取应用的请求日志（分页，只读审计日志）"""
    offset = (page - 1) * size

    result = await db.execute(
        text("""
            SELECT id, endpoint, method, status_code,
                   request_duration_ms, ip_address, request_id, created_at
            FROM api_request_logs
            WHERE app_id = :app_id
              AND tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "app_id": str(app_id),
            "tenant_id": str(tenant_id),
            "limit": size,
            "offset": offset,
        },
    )
    items = [dict(r) for r in result.mappings().fetchall()]

    count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM api_request_logs
            WHERE app_id = :app_id AND tenant_id = :tenant_id
        """),
        {"app_id": str(app_id), "tenant_id": str(tenant_id)},
    )
    total = count_result.scalar_one()

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
    }


# ── OAuth2端点 ────────────────────────────────────────────────────

@router.post("/oauth/token")
async def issue_token(
    body: IssueTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 client_credentials流程，颁发access_token。

    - grant_type必须为client_credentials
    - 验证app_key + app_secret
    - 验证requested_scopes是应用授权scopes的子集
    """
    if body.grant_type != "client_credentials":
        raise HTTPException(
            status_code=400,
            detail="仅支持grant_type=client_credentials",
        )

    requested_scopes = body.scope.split() if body.scope else []

    try:
        result = await _oauth2_service.issue_token(
            app_key=body.app_key,
            app_secret=body.app_secret,
            requested_scopes=requested_scopes,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        error_msg = str(exc)
        # 区分未激活/已暂停(403) 和 secret错误(401)
        if "suspended" in error_msg or "revoked" in error_msg or "状态" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        if "scope" in error_msg or "超出" in error_msg:
            raise HTTPException(status_code=403, detail=error_msg) from exc
        raise HTTPException(status_code=401, detail=error_msg) from exc

    return {"ok": True, "data": result}


@router.post("/oauth/revoke")
async def revoke_token(
    body: RevokeTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """吊销指定access_token"""
    success = await _oauth2_service.revoke_token(body.token, db)
    return {"ok": True, "data": {"revoked": success}}


@router.post("/oauth/rotate")
async def rotate_secret(
    body: RotateSecretRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """轮换app_secret，同时吊销所有现存token。

    返回新的明文secret，只显示一次。
    """
    try:
        app_uuid = UUID(body.app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="app_id格式无效") from exc

    try:
        result = await _oauth2_service.rotate_secret(app_uuid, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"ok": True, "data": result}
