"""
事件 Webhook 接收路由
其他微服务通过 POST /internal/events 推送事件到 tx-expense。

此端点仅供内部服务调用，不对外暴露（由 gateway 控制访问）。

安全机制：
  - 可选 HMAC-SHA256 验签（Header: X-Event-Signature）
  - 密钥从环境变量 INTERNAL_EVENT_SECRET 读取
  - 未配置密钥时跳过验签（开发/测试环境）

签名算法：
  HMAC-SHA256(message="{event_id}{event_type}{tenant_id}", key=INTERNAL_EVENT_SECRET)
  Header 值格式：sha256=<hex_digest>
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field

from shared.ontology.src.database import TenantSession

log = structlog.get_logger(__name__)

router = APIRouter()

_INTERNAL_EVENT_SECRET: Optional[str] = os.getenv("INTERNAL_EVENT_SECRET")


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class IncomingEvent(BaseModel):
    """内部事件推送请求体。"""

    event_id: str = Field(..., description="唯一事件ID（用于幂等去重）")
    event_type: str = Field(..., description="事件类型，如 ops.daily_close.completed")
    tenant_id: str = Field(..., description="租户UUID")
    payload: dict[str, Any] = Field(default_factory=dict, description="事件业务数据")
    occurred_at: str = Field(..., description="事件发生时间（ISO8601）")


class EventAcceptedResponse(BaseModel):
    status: str = "accepted"
    event_id: str


# ---------------------------------------------------------------------------
# 验签辅助
# ---------------------------------------------------------------------------


def _verify_signature(
    event_id: str,
    event_type: str,
    tenant_id: str,
    signature: Optional[str],
) -> None:
    """校验 HMAC-SHA256 签名。

    未配置 INTERNAL_EVENT_SECRET 时直接跳过（开发环境）。
    配置了密钥但签名不匹配时抛出 403。
    """
    if not _INTERNAL_EVENT_SECRET:
        return  # 未配置密钥，跳过验签

    if not signature:
        raise HTTPException(
            status_code=403,
            detail="缺少 X-Event-Signature Header",
        )

    message = f"{event_id}{event_type}{tenant_id}".encode()
    expected_digest = hmac.new(
        _INTERNAL_EVENT_SECRET.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()
    expected = f"sha256={expected_digest}"

    # 使用 compare_digest 防止时序攻击
    if not hmac.compare_digest(expected, signature):
        log.warning(
            "event_webhook_invalid_signature",
            event_id=event_id,
            event_type=event_type,
            tenant_id=tenant_id,
        )
        raise HTTPException(
            status_code=403,
            detail="X-Event-Signature 验签失败",
        )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post(
    "/internal/events",
    status_code=202,
    response_model=EventAcceptedResponse,
    summary="接收内部事件推送",
    description=(
        "其他微服务通过此端点向 tx-expense 推送业务事件。"
        "接收后立即返回 202，实际处理在后台异步执行。"
        "不对外暴露，由 API Gateway 控制内部访问。"
    ),
)
async def receive_event(
    event: IncomingEvent,
    background_tasks: BackgroundTasks,
    x_event_signature: Optional[str] = Header(
        None,
        alias="X-Event-Signature",
        description="HMAC-SHA256 签名（格式：sha256=<hex>），未配置密钥时可省略",
    ),
) -> EventAcceptedResponse:
    """接收内部事件，立即返回 202，后台异步处理。

    处理流程：
      1. 验签（可选，取决于 INTERNAL_EVENT_SECRET 是否配置）
      2. 幂等检查（在后台任务内部执行，避免阻塞响应）
      3. 后台执行事件路由与业务处理
    """
    # 1. 验签
    _verify_signature(
        event.event_id,
        event.event_type,
        event.tenant_id,
        x_event_signature,
    )

    log.info(
        "event_webhook_received",
        event_id=event.event_id,
        event_type=event.event_type,
        tenant_id=event.tenant_id,
        occurred_at=event.occurred_at,
    )

    # 2. 注册后台任务（立即返回 202，不等待处理完成）
    background_tasks.add_task(
        _dispatch_event,
        event_type=event.event_type,
        event_id=event.event_id,
        tenant_id=event.tenant_id,
        payload=event.payload,
    )

    # 3. 立即返回
    return EventAcceptedResponse(event_id=event.event_id)


# ---------------------------------------------------------------------------
# 后台分发（隔离 import，避免循环依赖）
# ---------------------------------------------------------------------------


async def _dispatch_event(
    event_type: str,
    event_id: str,
    tenant_id: str,
    payload: dict[str, Any],
) -> None:
    """后台任务：将事件分发到 event_consumer_service.process_event。

    使用 TenantSession 作为 db_factory，确保 RLS 租户隔离。
    异常在 process_event 内部已 catch，此处不再重复捕获。
    """
    from src.services.event_consumer_service import process_event

    await process_event(
        db_factory=TenantSession,
        event_type=event_type,
        event_id=event_id,
        tenant_id=tenant_id,
        payload=payload,
    )
