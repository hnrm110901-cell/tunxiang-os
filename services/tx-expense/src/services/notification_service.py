"""
统一通知推送服务
负责费控审批相关消息推送：企业微信 Webhook / 钉钉机器人 / 飞书机器人。

推送策略：
- 按 Brand 配置决定使用哪个渠道（WECOM/DINGTALK/FEISHU）
- 渠道配置从环境变量读取（不硬编码 Webhook URL）
- 推送结果写入 expense_notifications 表供审计
- 推送失败不阻塞主业务（异步旁路，最多重试3次）
- 无渠道配置时状态标记为 SKIPPED，不报错

安全约束：
- Webhook URL 必须从环境变量读取，绝不硬编码
- 所有外部 HTTP 调用设置超时（5秒）
- 推送失败记录 failed_reason，不静默吞异常
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expense_enums import NotificationChannel, NotificationEventType, PushStatus
from ..models.notification import ExpenseNotification

logger = structlog.get_logger(__name__)

# 最大重试次数
_MAX_RETRIES = 3
# HTTP 超时（秒）
_HTTP_TIMEOUT = 5.0
# 批量推送最大并发数
_BATCH_CONCURRENCY = 10


# ─────────────────────────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# 渠道配置读取
# ─────────────────────────────────────────────────────────────────────────────

def _get_channel_config(brand_id: str) -> dict[str, Optional[str]]:
    """
    从环境变量读取推送渠道配置。

    环境变量规则：
    - 全局默认渠道：EXPENSE_NOTIFY_CHANNEL（wecom / dingtalk / feishu）
    - 品牌专用渠道：EXPENSE_NOTIFY_CHANNEL_{BRAND_ID_PREFIX}（取 UUID 前8位，大写）
    - Webhook URL：
        EXPENSE_WECOM_WEBHOOK_URL
        EXPENSE_DINGTALK_WEBHOOK_URL
        EXPENSE_FEISHU_WEBHOOK_URL

    优先级：品牌专用 > 全局默认

    返回: {"channel": "wecom", "webhook_url": "https://..."}
    无配置时返回 {"channel": None, "webhook_url": None}
    """
    brand_prefix = str(brand_id).replace("-", "")[:8].upper()
    brand_env_key = f"EXPENSE_NOTIFY_CHANNEL_{brand_prefix}"

    channel = os.environ.get(brand_env_key) or os.environ.get("EXPENSE_NOTIFY_CHANNEL")
    if not channel:
        return {"channel": None, "webhook_url": None}

    channel = channel.strip().lower()

    url_env_map: dict[str, str] = {
        NotificationChannel.WECOM.value: "EXPENSE_WECOM_WEBHOOK_URL",
        NotificationChannel.DINGTALK.value: "EXPENSE_DINGTALK_WEBHOOK_URL",
        NotificationChannel.FEISHU.value: "EXPENSE_FEISHU_WEBHOOK_URL",
    }

    url_env_key = url_env_map.get(channel)
    if not url_env_key:
        logger.warning(
            "notification_unknown_channel",
            channel=channel,
            brand_id=brand_id,
        )
        return {"channel": None, "webhook_url": None}

    webhook_url = os.environ.get(url_env_key)
    if not webhook_url:
        logger.warning(
            "notification_webhook_url_not_set",
            env_key=url_env_key,
            channel=channel,
            brand_id=brand_id,
        )
        return {"channel": None, "webhook_url": None}

    return {"channel": channel, "webhook_url": webhook_url}


# ─────────────────────────────────────────────────────────────────────────────
# 消息模板构建
# ─────────────────────────────────────────────────────────────────────────────

def _build_wecom_message(
    event_type: str,
    title: str,
    body: str,
    application_id: str,
) -> dict[str, Any]:
    """构建企业微信 Webhook Markdown 卡片消息。"""
    short_id = str(application_id).replace("-", "")[:8]
    content = f"## {title}\n{body}\n> 申请单号：{short_id}..."
    return {
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        },
    }


def _build_dingtalk_message(
    event_type: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    """构建钉钉机器人 Markdown 消息。"""
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## {title}\n\n{body}",
        },
        "at": {"isAtAll": False},
    }


def _build_feishu_message(
    event_type: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    """构建飞书机器人富文本（Interactive Card）消息。"""
    return {
        "msg_type": "interactive",
        "card": {
            "elements": [
                {
                    "tag": "div",
                    "text": {"content": body, "tag": "lark_md"},
                }
            ],
            "header": {
                "title": {"content": title, "tag": "plain_text"},
            },
        },
    }


def _build_message_payload(
    channel: str,
    event_type: str,
    title: str,
    body: str,
    application_id: str,
) -> dict[str, Any]:
    """根据渠道分发消息体构建。"""
    if channel == NotificationChannel.WECOM.value:
        return _build_wecom_message(event_type, title, body, application_id)
    if channel == NotificationChannel.DINGTALK.value:
        return _build_dingtalk_message(event_type, title, body)
    if channel == NotificationChannel.FEISHU.value:
        return _build_feishu_message(event_type, title, body)
    raise ValueError(f"不支持的推送渠道: {channel}")


# ─────────────────────────────────────────────────────────────────────────────
# 审批消息内容生成
# ─────────────────────────────────────────────────────────────────────────────

def _generate_approval_message(
    event_type: str,
    application_title: str,
    applicant_name: str,
    total_amount: int,
    store_name: str,
    comment: Optional[str] = None,
) -> tuple[str, str]:
    """
    生成审批消息标题和正文。

    参数：
        total_amount: 分(fen)，方法内部转换为元展示。

    返回：(title, body)
    """
    amount_yuan = f"{total_amount / 100:.2f}元"

    if event_type == NotificationEventType.APPROVAL_REQUESTED.value:
        title = f"[待审批] {application_title}"
        body = (
            f"**申请人**：{applicant_name}\n"
            f"**门店**：{store_name}\n"
            f"**申请金额**：{amount_yuan}\n\n"
            "请及时登录费控系统处理。"
        )

    elif event_type == NotificationEventType.APPROVED.value:
        title = f"[已通过] {application_title}"
        comment_line = f"\n**审批意见**：{comment}" if comment else ""
        body = (
            f"您提交的费用申请已审批通过。\n"
            f"**申请金额**：{amount_yuan}\n"
            f"**门店**：{store_name}"
            f"{comment_line}"
        )

    elif event_type == NotificationEventType.REJECTED.value:
        title = f"[已驳回] {application_title}"
        reason_line = f"\n**驳回原因**：{comment}" if comment else "\n**驳回原因**：未说明"
        body = (
            f"您提交的费用申请已被驳回。\n"
            f"**申请金额**：{amount_yuan}\n"
            f"**门店**：{store_name}"
            f"{reason_line}\n\n"
            "如有疑问，请联系审批人或重新提交申请。"
        )

    elif event_type == NotificationEventType.TRANSFERRED.value:
        title = f"[已转交] {application_title}"
        body = (
            f"该费用申请已被转交给您处理。\n"
            f"**申请人**：{applicant_name}\n"
            f"**门店**：{store_name}\n"
            f"**申请金额**：{amount_yuan}\n\n"
            "请及时登录费控系统处理。"
        )

    elif event_type == NotificationEventType.REMINDER.value:
        title = f"[催办提醒] {application_title}"
        body = (
            f"**申请人**：{applicant_name}\n"
            f"**门店**：{store_name}\n"
            f"**申请金额**：{amount_yuan}\n\n"
            "该申请正在等待您审批，请尽快处理。"
        )

    else:
        title = f"[通知] {application_title}"
        body = (
            f"**申请人**：{applicant_name}\n"
            f"**门店**：{store_name}\n"
            f"**申请金额**：{amount_yuan}"
        )

    return title, body


# ─────────────────────────────────────────────────────────────────────────────
# HTTP 推送（内部，含重试）
# ─────────────────────────────────────────────────────────────────────────────

async def _do_http_post(webhook_url: str, payload: dict[str, Any]) -> tuple[bool, str, str]:
    """
    执行 HTTP POST 推送，最多重试 _MAX_RETRIES 次。

    返回: (success: bool, external_msg_id: str, failed_reason: str)
    """
    last_error = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code == 200:
                    # 尝试提取平台返回的消息 ID（各平台字段不同）
                    try:
                        resp_json = resp.json()
                        msg_id = (
                            str(resp_json.get("msgid", ""))
                            or str(resp_json.get("message_id", ""))
                            or str(resp_json.get("requestId", ""))
                        )
                    except ValueError:
                        msg_id = ""
                    return True, msg_id, ""
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(
                        "notification_http_non_200",
                        attempt=attempt,
                        status_code=resp.status_code,
                        body_preview=resp.text[:200],
                    )
        except httpx.TimeoutException as exc:
            last_error = f"超时（attempt {attempt}）: {exc}"
            logger.warning("notification_http_timeout", attempt=attempt, error=str(exc))
        except httpx.RequestError as exc:
            last_error = f"请求错误（attempt {attempt}）: {exc}"
            logger.warning("notification_http_request_error", attempt=attempt, error=str(exc))

    return False, "", last_error


# ─────────────────────────────────────────────────────────────────────────────
# DB 写入辅助
# ─────────────────────────────────────────────────────────────────────────────

async def _write_notification_record(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_role: str,
    channel: str,
    event_type: str,
    title: str,
    body: str,
    push_status: str,
    sent_at: Optional[datetime] = None,
    failed_reason: Optional[str] = None,
    external_msg_id: Optional[str] = None,
    retry_count: int = 0,
) -> None:
    """写入一条 expense_notifications 记录。失败只记录日志，不向上抛出。"""
    record = ExpenseNotification(
        tenant_id=tenant_id,
        application_id=application_id,
        recipient_id=recipient_id,
        recipient_role=recipient_role,
        channel=channel,
        event_type=event_type,
        message_title=title,
        message_body=body,
        push_status=push_status,
        sent_at=sent_at,
        failed_reason=failed_reason,
        external_msg_id=external_msg_id or None,
        retry_count=retry_count,
    )
    try:
        db.add(record)
        await db.flush()
    except SQLAlchemyError as exc:
        logger.error(
            "notification_db_write_failed",
            application_id=str(application_id),
            recipient_id=str(recipient_id),
            event_type=event_type,
            error=str(exc),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 核心推送方法
# ─────────────────────────────────────────────────────────────────────────────

async def send_notification(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_role: str,
    event_type: str,
    application_title: str,
    applicant_name: str,
    total_amount: int,
    store_name: str,
    brand_id: uuid.UUID,
    comment: Optional[str] = None,
) -> str:
    """
    发送单条通知（异步旁路，失败不抛出异常）。

    流程：
    1. 查找渠道配置（_get_channel_config）
    2. 无配置 → 写 SKIPPED 记录，返回
    3. 生成消息内容（_generate_approval_message）
    4. 构建消息体（_build_message_payload）
    5. 发送 HTTP POST（httpx，超时5秒，最多重试3次）
    6. 写 expense_notifications 记录（sent / failed）

    返回：PushStatus 值字符串（"sent" / "failed" / "skipped"）
    """
    cfg = _get_channel_config(str(brand_id))
    channel = cfg["channel"]
    webhook_url = cfg["webhook_url"]

    title, body = _generate_approval_message(
        event_type=event_type,
        application_title=application_title,
        applicant_name=applicant_name,
        total_amount=total_amount,
        store_name=store_name,
        comment=comment,
    )

    # ── 无渠道配置：SKIPPED ──
    if not channel or not webhook_url:
        logger.info(
            "notification_skipped_no_config",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            event_type=event_type,
            brand_id=str(brand_id),
        )
        await _write_notification_record(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            recipient_id=recipient_id,
            recipient_role=recipient_role,
            channel=channel or "none",
            event_type=event_type,
            title=title,
            body=body,
            push_status=PushStatus.SKIPPED.value,
        )
        return PushStatus.SKIPPED.value

    # ── 构建消息体 ──
    try:
        payload = _build_message_payload(
            channel=channel,
            event_type=event_type,
            title=title,
            body=body,
            application_id=str(application_id),
        )
    except ValueError as exc:
        failed_reason = f"消息体构建失败: {exc}"
        logger.error(
            "notification_build_payload_failed",
            channel=channel,
            event_type=event_type,
            error=str(exc),
        )
        await _write_notification_record(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            recipient_id=recipient_id,
            recipient_role=recipient_role,
            channel=channel,
            event_type=event_type,
            title=title,
            body=body,
            push_status=PushStatus.FAILED.value,
            failed_reason=failed_reason,
        )
        return PushStatus.FAILED.value

    # ── HTTP 推送 ──
    success, external_msg_id, failed_reason = await _do_http_post(webhook_url, payload)

    if success:
        logger.info(
            "notification_sent",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            channel=channel,
            event_type=event_type,
            external_msg_id=external_msg_id,
        )
        await _write_notification_record(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            recipient_id=recipient_id,
            recipient_role=recipient_role,
            channel=channel,
            event_type=event_type,
            title=title,
            body=body,
            push_status=PushStatus.SENT.value,
            sent_at=_now_utc(),
            external_msg_id=external_msg_id,
            retry_count=0,
        )
        return PushStatus.SENT.value
    else:
        logger.error(
            "notification_failed",
            tenant_id=str(tenant_id),
            application_id=str(application_id),
            channel=channel,
            event_type=event_type,
            failed_reason=failed_reason,
        )
        await _write_notification_record(
            db=db,
            tenant_id=tenant_id,
            application_id=application_id,
            recipient_id=recipient_id,
            recipient_role=recipient_role,
            channel=channel,
            event_type=event_type,
            title=title,
            body=body,
            push_status=PushStatus.FAILED.value,
            failed_reason=failed_reason,
            retry_count=_MAX_RETRIES,
        )
        return PushStatus.FAILED.value


# ─────────────────────────────────────────────────────────────────────────────
# 语义化快捷方法
# ─────────────────────────────────────────────────────────────────────────────

async def send_approval_requested(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    approver_id: uuid.UUID,
    approver_role: str,
    application_title: str,
    applicant_name: str,
    total_amount: int,
    store_name: str,
    brand_id: uuid.UUID,
) -> None:
    """
    审批节点创建时：推送给审批人。

    对应事件：approval_requested
    """
    await send_notification(
        db=db,
        tenant_id=tenant_id,
        application_id=application_id,
        recipient_id=approver_id,
        recipient_role=approver_role,
        event_type=NotificationEventType.APPROVAL_REQUESTED.value,
        application_title=application_title,
        applicant_name=applicant_name,
        total_amount=total_amount,
        store_name=store_name,
        brand_id=brand_id,
    )


async def send_approval_result(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    applicant_id: uuid.UUID,
    event_type: str,
    application_title: str,
    applicant_name: str,
    total_amount: int,
    store_name: str,
    brand_id: uuid.UUID,
    comment: Optional[str] = None,
) -> None:
    """
    审批完成/驳回时：推送给申请人。

    event_type 取值：
    - NotificationEventType.APPROVED.value  ("approved")
    - NotificationEventType.REJECTED.value  ("rejected")
    """
    await send_notification(
        db=db,
        tenant_id=tenant_id,
        application_id=application_id,
        recipient_id=applicant_id,
        recipient_role="applicant",
        event_type=event_type,
        application_title=application_title,
        applicant_name=applicant_name,
        total_amount=total_amount,
        store_name=store_name,
        brand_id=brand_id,
        comment=comment,
    )


async def send_reminder(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    approver_id: uuid.UUID,
    application_title: str,
    applicant_name: str,
    total_amount: int,
    store_name: str,
    brand_id: uuid.UUID,
    pending_hours: int,
) -> None:
    """
    催办推送（A1备用金守护等 Agent 触发）。

    pending_hours: 申请已等待审批的小时数
    """
    # 把等待时长拼入 comment，由 _generate_approval_message 在正文中展示
    comment = f"该申请已等待审批 {pending_hours} 小时，请及时处理。"
    await send_notification(
        db=db,
        tenant_id=tenant_id,
        application_id=application_id,
        recipient_id=approver_id,
        recipient_role="approver",
        event_type=NotificationEventType.REMINDER.value,
        application_title=application_title,
        applicant_name=applicant_name,
        total_amount=total_amount,
        store_name=store_name,
        brand_id=brand_id,
        comment=comment,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 批量推送（月末核销催办等）
# ─────────────────────────────────────────────────────────────────────────────

async def send_batch_reminders(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    application_ids: list[uuid.UUID],
    brand_id: uuid.UUID,
    applicant_name: str = "申请人",
    application_title: str = "费用申请",
    total_amount: int = 0,
    store_name: str = "",
    approver_id: Optional[uuid.UUID] = None,
    pending_hours: int = 0,
) -> dict[str, int]:
    """
    批量发送催办通知（A1 Agent 月末核销用）。

    并发发送，最大并发 10。
    返回: {"sent": N, "failed": N, "skipped": N}
    """
    semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)
    results: dict[str, int] = {"sent": 0, "failed": 0, "skipped": 0}
    lock = asyncio.Lock()

    _approver_id = approver_id or uuid.uuid4()

    async def _send_one(app_id: uuid.UUID) -> None:
        async with semaphore:
            status = await send_notification(
                db=db,
                tenant_id=tenant_id,
                application_id=app_id,
                recipient_id=_approver_id,
                recipient_role="approver",
                event_type=NotificationEventType.REMINDER.value,
                application_title=application_title,
                applicant_name=applicant_name,
                total_amount=total_amount,
                store_name=store_name,
                brand_id=brand_id,
                comment=(
                    f"该申请已等待审批 {pending_hours} 小时，请及时处理。"
                    if pending_hours
                    else None
                ),
            )
            async with lock:
                if status == PushStatus.SENT.value:
                    results["sent"] += 1
                elif status == PushStatus.FAILED.value:
                    results["failed"] += 1
                else:
                    results["skipped"] += 1

    tasks = [asyncio.create_task(_send_one(app_id)) for app_id in application_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(
        "notification_batch_reminders_done",
        tenant_id=str(tenant_id),
        brand_id=str(brand_id),
        total=len(application_ids),
        **results,
    )
    return results
