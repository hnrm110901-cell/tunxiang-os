"""短信/推送触达 API — prefix /api/v1/growth/notifications

端点:
1. POST /api/v1/growth/notifications/send-campaign   发送营销推送（创建异步任务）
2. GET  /api/v1/growth/notifications/tasks           查询发送任务列表及状态
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/notifications", tags=["growth-notifications"])

_VALID_CHANNELS = {"sms", "wechat_template", "miniapp_push"}


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok_response(data: Any) -> dict:
    return {"ok": True, "data": data}


def error_response(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class SendCampaignRequest(BaseModel):
    campaign_id: str
    channel: str  # sms|wechat_template|miniapp_push
    message_template: str
    target_customer_ids: list[str]  # 目标客户 ID 列表


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _is_table_missing(exc: SQLAlchemyError) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or ("relation" in msg and "exist" in msg)


def _row_to_task(row) -> dict:
    return {
        "task_id": str(row.id),
        "campaign_id": str(row.campaign_id),
        "channel": row.channel,
        "status": row.status,
        "total_count": row.total_count,
        "sent_count": row.sent_count,
        "failed_count": row.failed_count,
        "message_template": row.message_template,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("/send-campaign")
async def send_campaign_notification(
    req: SendCampaignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发送营销推送（异步任务）

    仅创建发送任务记录，返回 task_id。
    实际消息投递由后台 Worker 异步执行，通过轮询 /tasks 查询进度。
    """
    if req.channel not in _VALID_CHANNELS:
        return error_response("INVALID_CHANNEL", f"channel 须为 {_VALID_CHANNELS} 之一")

    if not req.target_customer_ids:
        return error_response("EMPTY_TARGETS", "target_customer_ids 不能为空")

    if not req.message_template.strip():
        return error_response("EMPTY_TEMPLATE", "message_template 不能为空")

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        campaign_id = uuid.UUID(req.campaign_id)

        # 校验活动是否存在（active 状态才允许发送）
        campaign_result = await db.execute(
            text("""
                SELECT id, name, status FROM campaigns
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"cid": campaign_id, "tid": tid},
        )
        campaign = campaign_result.fetchone()
        if not campaign:
            return error_response("CAMPAIGN_NOT_FOUND", f"活动不存在: {req.campaign_id}")
        if campaign.status not in {"active", "draft"}:
            return error_response(
                "CAMPAIGN_NOT_ACTIVE",
                f"活动当前状态为 {campaign.status}，只有 active/draft 活动可以发送推送",
            )

        # 创建发送任务
        task_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        total = len(req.target_customer_ids)

        await db.execute(
            text("""
                INSERT INTO notification_tasks
                    (id, tenant_id, campaign_id, channel,
                     message_template, target_customer_ids,
                     status, total_count, sent_count, failed_count,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :cid, :channel,
                     :tmpl, :targets::jsonb,
                     'pending', :total, 0, 0,
                     :now, :now)
            """),
            {
                "id": task_id,
                "tid": tid,
                "cid": campaign_id,
                "channel": req.channel,
                "tmpl": req.message_template,
                "targets": str(req.target_customer_ids).replace("'", '"'),
                "total": total,
                "now": now,
            },
        )
        await db.commit()

        logger.info(
            "notification_task.created",
            task_id=str(task_id),
            campaign_id=str(campaign_id),
            channel=req.channel,
            total_count=total,
            tenant_id=x_tenant_id,
        )
        return ok_response(
            {
                "task_id": str(task_id),
                "campaign_id": str(campaign_id),
                "channel": req.channel,
                "status": "pending",
                "total_count": total,
                "_note": "发送任务已创建，实际投递由后台异步执行，请通过 GET /tasks 查询进度",
            }
        )

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        await db.rollback()
        if _is_table_missing(exc):
            logger.warning("notification.table_not_ready", error=str(exc))
            # TABLE_NOT_READY 降级：写入 hub_notifications 表留存记录
            task_id = uuid.uuid4()
            now_fallback = datetime.now(timezone.utc)
            try:
                tenant_uuid = uuid.UUID(x_tenant_id)
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": x_tenant_id},
                )
                await db.execute(
                    text("""
                        INSERT INTO hub_notifications (
                            id, tenant_id, store_ids, notification_type,
                            title, content, priority, status, created_at, updated_at
                        ) VALUES (
                            :id, :tenant_id, :store_ids::jsonb, :notification_type,
                            :title, :content, 'normal', 'pending', :now, :now
                        )
                    """),
                    {
                        "id": task_id,
                        "tenant_id": tenant_uuid,
                        "store_ids": "[]",
                        "notification_type": "campaign_notification",
                        "title": f"营销推送任务 ({req.channel})",
                        "content": req.message_template,
                        "now": now_fallback,
                    },
                )
                await db.commit()
                logger.info(
                    "notification_task.created",
                    task_id=str(task_id),
                    campaign_id=req.campaign_id,
                    channel=req.channel,
                    total_count=len(req.target_customer_ids),
                    fallback_table="hub_notifications",
                )
            except SQLAlchemyError as hub_exc:
                logger.warning(
                    "notification.hub_fallback_failed",
                    error=str(hub_exc),
                    original_error=str(exc),
                )
                await db.rollback()
            return ok_response(
                {
                    "task_id": str(task_id),
                    "campaign_id": req.campaign_id,
                    "channel": req.channel,
                    "status": "pending",
                    "total_count": len(req.target_customer_ids),
                    "_note": "TABLE_NOT_READY: notification_tasks 表尚未创建，已降级写入 hub_notifications",
                }
            )
        logger.error("notification.send_campaign_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "创建发送任务失败")


@router.get("/tasks")
async def list_notification_tasks(
    campaign_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询发送任务列表及状态"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        tid = uuid.UUID(x_tenant_id)
        offset = (page - 1) * size

        where_parts = ["tenant_id = :tid"]
        params: dict = {"tid": tid, "limit": size, "offset": offset}

        if campaign_id:
            where_parts.append("campaign_id = :cid")
            params["cid"] = uuid.UUID(campaign_id)
        if status:
            where_parts.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(where_parts)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM notification_tasks WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text(f"""
                SELECT id, campaign_id, channel, status,
                       total_count, sent_count, failed_count,
                       message_template, created_at, updated_at
                FROM notification_tasks
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()
        items = [_row_to_task(r) for r in rows]
        return ok_response({"items": items, "total": total, "page": page, "size": size})

    except ValueError as exc:
        return error_response("INVALID_PARAM", f"参数格式错误: {exc}")
    except SQLAlchemyError as exc:
        if _is_table_missing(exc):
            logger.warning("notification.table_not_ready", error=str(exc))
            return ok_response({"items": [], "total": 0, "page": page, "size": size, "_note": "TABLE_NOT_READY"})
        logger.error("notification.list_tasks_error", error=str(exc), exc_info=True)
        return error_response("DB_ERROR", "查询任务列表失败")
