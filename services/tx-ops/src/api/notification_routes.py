"""通知服务 API 路由 — 发送通知 + 历史查询

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.notification_service import NotificationService

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class SendSmsReq(BaseModel):
    phone: str
    template_id: str
    params: dict[str, str] = Field(default_factory=dict)
    store_id: Optional[str] = None


class SendWechatReq(BaseModel):
    openid: str
    template_id: str
    data: dict = Field(default_factory=dict)
    url: Optional[str] = None
    store_id: Optional[str] = None


class SendWecomReq(BaseModel):
    webhook_url: str
    content: str
    msg_type: str = "text"
    mentioned_list: Optional[list[str]] = None
    store_id: Optional[str] = None


class SendNotificationReq(BaseModel):
    """统一发送接口"""
    channel: str = Field(..., pattern="^(sms|wechat|wecom)$")
    # SMS 字段
    phone: Optional[str] = None
    # 微信字段
    openid: Optional[str] = None
    # 企业微信字段
    webhook_url: Optional[str] = None
    # 通用字段
    template_id: Optional[str] = None
    params: dict = Field(default_factory=dict)
    content: Optional[str] = None
    store_id: Optional[str] = None


# ─── 端点 ───


@router.post("/send")
async def send_notification(
    req: SendNotificationReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/notifications/send — 发送通知（统一入口）"""
    tenant_id = _get_tenant_id(request)
    svc = NotificationService(db, tenant_id)

    try:
        if req.channel == "sms":
            if not req.phone:
                raise HTTPException(status_code=400, detail="SMS requires 'phone' field")
            result = await svc.send_sms(
                phone=req.phone,
                template_id=req.template_id or "",
                params=req.params,
                store_id=req.store_id,
            )
        elif req.channel == "wechat":
            if not req.openid:
                raise HTTPException(status_code=400, detail="WeChat requires 'openid' field")
            result = await svc.send_wechat(
                openid=req.openid,
                template_id=req.template_id or "",
                data=req.params,
                store_id=req.store_id,
            )
        elif req.channel == "wecom":
            if not req.webhook_url:
                raise HTTPException(status_code=400, detail="WeCom requires 'webhook_url' field")
            result = await svc.send_wecom(
                webhook_url=req.webhook_url,
                content=req.content or "",
                store_id=req.store_id,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported channel: {req.channel}")

        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_notifications(
    request: Request,
    channel: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/notifications — 通知历史"""
    tenant_id = _get_tenant_id(request)
    svc = NotificationService(db, tenant_id)

    result = await svc.list_notifications(
        channel=channel,
        store_id=store_id,
        page=page,
        size=size,
    )
    return _ok(result)
