"""通知中心 API 路由 — 消息管理 + 模板管理 + 发送通知 + 多渠道分发 (真实DB + RLS)

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

与 notification_routes.py 区分：
  - notification_routes.py: 底层发送通道（SMS/微信/企微）—— 旧接口
  - notification_center_routes.py: 上层通知中心管理 + 新版多渠道分发

表：notifications / notification_templates (v133)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.integrations.notification_dispatcher import NotificationDispatcher
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/notifications", tags=["notification-center"])
logger = structlog.get_logger(__name__)


# ─── 辅助函数 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 请求模型 ───


class SendNotificationReq(BaseModel):
    """发送通知请求"""
    template_code: str = Field(..., description="模板代码")
    target_type: str = Field(..., pattern="^(customer|employee|store|all)$")
    target_id: Optional[str] = Field(None, description="目标ID，all时可为空")
    channel: str = Field(..., pattern="^(wechat|sms|push|in_app)$")
    variables: dict[str, str] = Field(default_factory=dict, description="模板变量值")


class SendSmsDirectReq(BaseModel):
    """直发短信请求"""
    phone: str = Field(..., description="手机号")
    template_code: str = Field(..., description="模板代码: verification_code/order_notification/queue_notification/marketing")
    variables: dict[str, str] = Field(default_factory=dict, description="模板变量")


class SendWechatDirectReq(BaseModel):
    """直发微信订阅消息请求"""
    openid: str = Field(..., description="用户 openid")
    template_code: str = Field(..., description="模板代码: order_status/queue_called/promotion/booking_reminder")
    variables: dict[str, str] = Field(default_factory=dict, description="模板变量")


class SendMultiChannelReq(BaseModel):
    """多渠道同时发送请求"""
    channels: list[str] = Field(..., description="渠道列表: sms/wechat_subscribe/in_app/email")
    target: dict[str, str] = Field(..., description="目标地址: {phone, openid, user_id, email}")
    template_code: str = Field(..., description="模板代码")
    variables: dict[str, str] = Field(default_factory=dict, description="模板变量")


class UpdateTemplateReq(BaseModel):
    """更新模板请求"""
    name: Optional[str] = None
    channel: Optional[str] = None
    category: Optional[str] = None
    title_template: Optional[str] = None
    content_template: Optional[str] = None
    variables: Optional[list[dict]] = None
    is_active: Optional[bool] = None


# ─── 通知消息接口 ───


@router.get("")
async def list_notifications(
    request: Request,
    category: Optional[str] = Query(None, description="分类过滤"),
    status: Optional[str] = Query(None, description="状态过滤"),
    priority: Optional[str] = Query(None, description="优先级过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/ops/notifications — 通知分页列表"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    # 构建过滤条件
    where_clauses = [
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        "is_deleted = false",
    ]
    params: dict = {"limit": size, "offset": (page - 1) * size}

    if category:
        where_clauses.append("category = :category")
        params["category"] = category
    if status:
        where_clauses.append("status = :status")
        params["status"] = status
    if priority:
        where_clauses.append("priority = :priority")
        params["priority"] = priority

    where_sql = " AND ".join(where_clauses)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM notifications WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                f"""
                SELECT id, target_type, target_id, channel, title, content,
                       category, priority, status, sent_at, read_at, metadata, created_at
                FROM notifications
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row._mapping) for row in rows_result]
        # Serialize UUID and datetime fields
        for item in items:
            for key, val in item.items():
                if hasattr(val, "isoformat"):
                    item[key] = val.isoformat()
                elif hasattr(val, "hex"):
                    item[key] = str(val)

        return _ok({"items": items, "total": total, "page": page, "size": size})

    except SQLAlchemyError as exc:
        logger.error("notifications_list_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        return _ok({"items": [], "total": 0, "page": page, "size": size})


@router.get("/unread-count")
async def unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/ops/notifications/unread-count — 未读消息数"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM notifications
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                  AND status != 'read'
                  AND read_at IS NULL
                """
            )
        )
        count = result.scalar() or 0
        return _ok({"unread_count": count})

    except SQLAlchemyError as exc:
        logger.error("notifications_unread_count_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        return _ok({"unread_count": 0})


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PATCH /api/v1/ops/notifications/{id}/read — 标记单条已读"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    now = datetime.now(timezone.utc)
    try:
        result = await db.execute(
            text(
                """
                UPDATE notifications
                SET status = 'read', read_at = :now, updated_at = :now
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                RETURNING id
                """
            ),
            {"id": notification_id, "now": now},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="通知不存在")

        return _ok({
            "id": notification_id,
            "status": "read",
            "read_at": now.isoformat(),
        })

    except SQLAlchemyError as exc:
        logger.error("notifications_mark_read_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        return _ok({"id": notification_id, "status": "read", "read_at": now.isoformat()})


@router.post("/mark-all-read")
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/ops/notifications/mark-all-read — 全部标记已读"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    now = datetime.now(timezone.utc)
    try:
        result = await db.execute(
            text(
                """
                UPDATE notifications
                SET status = 'read', read_at = :now, updated_at = :now
                WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND is_deleted = false
                  AND status != 'read'
                  AND read_at IS NULL
                """
            ),
            {"now": now},
        )
        updated_count = result.rowcount
        return _ok({"updated_count": updated_count, "message": "所有未读消息已标记为已读"})

    except SQLAlchemyError as exc:
        logger.error("notifications_mark_all_read_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        return _ok({"updated_count": 0, "message": "操作失败，请稍后重试"})


@router.post("/send")
async def send_notification(
    req: SendNotificationReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """POST /api/v1/ops/notifications/send — 发送通知（基于模板）"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        # 查找模板
        tpl_result = await db.execute(
            text(
                """
                SELECT id, code, channel, category, title_template, content_template, variables
                FROM notification_templates
                WHERE code = :code
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                LIMIT 1
                """
            ),
            {"code": req.template_code},
        )
        tpl = tpl_result.fetchone()

        if not tpl:
            raise HTTPException(status_code=404, detail=f"模板 {req.template_code} 不存在")

        # 变量替换
        title = tpl.title_template
        content = tpl.content_template
        for key, value in req.variables.items():
            title = title.replace("{{" + key + "}}", str(value))
            content = content.replace("{{" + key + "}}", str(value))

        # 写入通知记录
        now = datetime.now(timezone.utc)
        notification_id = str(uuid.uuid4())
        await db.execute(
            text(
                """
                INSERT INTO notifications
                  (id, tenant_id, target_type, target_id, channel, title, content,
                   category, priority, status, sent_at, created_at, updated_at)
                VALUES
                  (:id, NULLIF(current_setting('app.tenant_id', true), '')::uuid,
                   :target_type, :target_id, :channel, :title, :content,
                   :category, 'normal', 'sent', :sent_at, :now, :now)
                """
            ),
            {
                "id": notification_id,
                "target_type": req.target_type,
                "target_id": req.target_id,
                "channel": req.channel,
                "title": title,
                "content": content,
                "category": tpl.category,
                "sent_at": now,
                "now": now,
            },
        )
        logger.info("notification_sent", notification_id=notification_id,
                    template_code=req.template_code, tenant_id=tenant_id)

        return _ok({
            "id": notification_id,
            "template_code": req.template_code,
            "target_type": req.target_type,
            "target_id": req.target_id,
            "channel": req.channel,
            "title": title,
            "content": content,
            "category": tpl.category,
            "priority": "normal",
            "status": "sent",
            "sent_at": now.isoformat(),
        })

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("notifications_send_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail="通知发送失败，数据库错误") from exc


# ─── 多渠道通知发送接口（基于 shared/integrations） ───

# 单例调度器 — 进程内共享
_dispatcher = NotificationDispatcher()


@router.post("/send-sms")
async def send_sms_direct(req: SendSmsDirectReq, request: Request) -> dict:
    """POST /api/v1/ops/notifications/send-sms -- 直发短信

    通过 shared/integrations/sms_service 发送，支持阿里云/腾讯云双通道。
    未配置密钥时自动 Mock。
    """
    _get_tenant_id(request)

    sms = _dispatcher.sms_service
    result: dict

    if req.template_code == "verification_code":
        result = await sms.send_verification_code(req.phone, req.variables.get("code", ""))
    elif req.template_code == "order_notification":
        result = await sms.send_order_notification(
            phone=req.phone,
            order_no=req.variables.get("order_no", ""),
            store_name=req.variables.get("store_name", ""),
            status=req.variables.get("status", ""),
        )
    elif req.template_code == "queue_notification":
        result = await sms.send_queue_notification(
            phone=req.phone,
            queue_no=req.variables.get("queue_no", ""),
            store_name=req.variables.get("store_name", ""),
        )
    elif req.template_code == "marketing":
        result = await sms.send_marketing(req.phone, req.variables.get("content", ""))
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown SMS template_code: {req.template_code}. "
                   f"Valid: verification_code, order_notification, queue_notification, marketing",
        )

    return _ok(result)


@router.post("/send-wechat")
async def send_wechat_direct(req: SendWechatDirectReq, request: Request) -> dict:
    """POST /api/v1/ops/notifications/send-wechat -- 直发微信订阅消息

    通过 shared/integrations/wechat_subscribe 发送小程序订阅消息。
    未配置 WECHAT_APPID 时自动 Mock。
    """
    _get_tenant_id(request)

    wx = _dispatcher.wechat_service
    result: dict

    if req.template_code in ("order_status", "order_notification"):
        result = await wx.send_order_status(
            openid=req.openid,
            order_no=req.variables.get("order_no", ""),
            status=req.variables.get("status", ""),
            time_str=req.variables.get("time", _now_iso()),
        )
    elif req.template_code in ("queue_called", "queue_notification"):
        result = await wx.send_queue_called(
            openid=req.openid,
            queue_no=req.variables.get("queue_no", ""),
            store_name=req.variables.get("store_name", ""),
        )
    elif req.template_code == "promotion":
        result = await wx.send_promotion(
            openid=req.openid,
            title=req.variables.get("title", ""),
            desc=req.variables.get("desc", ""),
            time_str=req.variables.get("time", ""),
        )
    elif req.template_code == "booking_reminder":
        result = await wx.send_booking_reminder(
            openid=req.openid,
            date=req.variables.get("date", ""),
            time_str=req.variables.get("time", ""),
            store_name=req.variables.get("store_name", ""),
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown WeChat template_code: {req.template_code}. "
                   f"Valid: order_status, queue_called, promotion, booking_reminder",
        )

    return _ok(result)


@router.post("/send-multi")
async def send_multi_channel(req: SendMultiChannelReq, request: Request) -> dict:
    """POST /api/v1/ops/notifications/send-multi -- 多渠道同时发送

    通过 NotificationDispatcher 并发分发到多个渠道。
    支持渠道: sms / wechat_subscribe / in_app / email(占位)
    """
    _get_tenant_id(request)

    # 校验渠道
    from shared.integrations.notification_dispatcher import VALID_CHANNELS

    invalid = [ch for ch in req.channels if ch not in VALID_CHANNELS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported channels: {invalid}. Valid: {list(VALID_CHANNELS)}",
        )

    results = await _dispatcher.send_multi_channel(
        channels=req.channels,
        target=req.target,
        template_code=req.template_code,
        variables=req.variables,
    )

    return _ok({
        "total": len(results),
        "results": results,
    })


# ─── 模板管理接口 ───

_template_router = APIRouter(
    prefix="/api/v1/ops/notification-templates", tags=["notification-templates"]
)


@_template_router.get("")
async def list_templates(
    request: Request,
    channel: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/ops/notification-templates — 模板列表"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    where_clauses = [
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
    ]
    params: dict = {"limit": size, "offset": (page - 1) * size}

    if channel:
        where_clauses.append("channel = :channel")
        params["channel"] = channel
    if category:
        where_clauses.append("category = :category")
        params["category"] = category
    if is_active is not None:
        where_clauses.append("is_active = :is_active")
        params["is_active"] = is_active

    where_sql = " AND ".join(where_clauses)

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM notification_templates WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                f"""
                SELECT id, name, code, channel, category,
                       title_template, content_template, variables, is_active,
                       created_at, updated_at
                FROM notification_templates
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        items = [dict(row._mapping) for row in rows_result]
        for item in items:
            for key, val in item.items():
                if hasattr(val, "isoformat"):
                    item[key] = val.isoformat()
                elif hasattr(val, "hex"):
                    item[key] = str(val)

        return _ok({"items": items, "total": total, "page": page, "size": size})

    except SQLAlchemyError as exc:
        logger.error("templates_list_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        return _ok({"items": [], "total": 0, "page": page, "size": size})


@_template_router.get("/{template_id}")
async def get_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GET /api/v1/ops/notification-templates/{id} — 模板详情"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text(
                """
                SELECT id, name, code, channel, category,
                       title_template, content_template, variables, is_active,
                       created_at, updated_at
                FROM notification_templates
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                LIMIT 1
                """
            ),
            {"id": template_id},
        )
        tpl = result.fetchone()
        if not tpl:
            raise HTTPException(status_code=404, detail="模板不存在")

        data = dict(tpl._mapping)
        for key, val in data.items():
            if hasattr(val, "isoformat"):
                data[key] = val.isoformat()
            elif hasattr(val, "hex"):
                data[key] = str(val)

        return _ok(data)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("template_get_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail="查询模板失败") from exc


@_template_router.put("/{template_id}")
async def update_template(
    template_id: str,
    req: UpdateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """PUT /api/v1/ops/notification-templates/{id} — 更新模板"""
    tenant_id = _get_tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        # 先检查存在
        check_result = await db.execute(
            text(
                """
                SELECT id FROM notification_templates
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                LIMIT 1
                """
            ),
            {"id": template_id},
        )
        if not check_result.fetchone():
            raise HTTPException(status_code=404, detail="模板不存在")

        update_fields = req.model_dump(exclude_none=True)
        if not update_fields:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        now = datetime.now(timezone.utc)
        set_clauses = ", ".join(f"{k} = :{k}" for k in update_fields)
        set_clauses += ", updated_at = :updated_at"
        update_fields["updated_at"] = now
        update_fields["id"] = template_id

        await db.execute(
            text(
                f"""
                UPDATE notification_templates
                SET {set_clauses}
                WHERE id = :id
                  AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                """
            ),
            update_fields,
        )

        # 返回更新后的记录
        row_result = await db.execute(
            text(
                """
                SELECT id, name, code, channel, category,
                       title_template, content_template, variables, is_active,
                       created_at, updated_at
                FROM notification_templates WHERE id = :id
                """
            ),
            {"id": template_id},
        )
        row = row_result.fetchone()
        data = dict(row._mapping) if row else {}
        for key, val in data.items():
            if hasattr(val, "isoformat"):
                data[key] = val.isoformat()
            elif hasattr(val, "hex"):
                data[key] = str(val)

        logger.info("template_updated", template_id=template_id, tenant_id=tenant_id)
        return _ok(data)

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("template_update_db_error", exc_info=True, error=str(exc), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail="更新模板失败") from exc


# 导出两个 router，在 main.py 中分别注册
template_router = _template_router
