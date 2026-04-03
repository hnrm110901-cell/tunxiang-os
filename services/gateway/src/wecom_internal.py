"""企业微信内部消息发送端点（仅供内网微服务调用）

POST /internal/wecom/send

接收来自 tx-growth 等内部服务的发送请求，调用 WecomSDK 完成实际推送。
此路由不经过外部鉴权，仅限 Docker 内网访问（不对外暴露）。

消息类型：
    text       — 纯文本消息
    text_card  — 文本卡片（带按钮和跳转链接）
    news       — 图文消息
"""
from __future__ import annotations

from typing import Literal, Optional

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .external_sdk import WecomSDK

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal/wecom", tags=["wecom-internal"])


# ---------------------------------------------------------------------------
# 请求 / 响应 Schema
# ---------------------------------------------------------------------------


class WecomSendRequest(BaseModel):
    user_id: str = Field(..., description="企微 external_userid 或员工 userid")
    message_type: Literal["text", "text_card", "news"] = Field(
        "text", description="消息类型"
    )
    # text
    content: Optional[str] = Field(None, description="文本消息内容（message_type=text 时使用）")
    # text_card
    title: Optional[str] = Field(None, description="卡片标题")
    description: Optional[str] = Field(None, description="卡片描述")
    url: Optional[str] = Field(None, description="卡片跳转链接")
    btntxt: Optional[str] = Field("查看详情", description="卡片按钮文字")
    # news
    articles: Optional[list[dict]] = Field(None, description="图文消息列表")


class WecomSendResponse(BaseModel):
    ok: bool
    message_type: str
    user_id: str
    wecom_response: dict


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


@router.post("/send", response_model=WecomSendResponse)
async def internal_wecom_send(
    body: WecomSendRequest,
    request: Request,
) -> WecomSendResponse:
    """内部发送企微消息

    由 tx-growth journey_executor 通过 ChannelEngine 调用，不对外暴露。

    - text       → WecomSDK.send_text
    - text_card  → WecomSDK.send_text_card（需要 title / description / url）
    - news       → WecomSDK.send_news（需要 articles 列表）
    """
    tenant_id: str = request.headers.get("X-Tenant-ID", "")
    log = logger.bind(
        user_id=body.user_id,
        message_type=body.message_type,
        tenant_id=tenant_id,
    )

    sdk = WecomSDK()

    try:
        if body.message_type == "text":
            text_content = body.content or f"{body.title or ''}\n{body.description or ''}"
            if not text_content.strip():
                raise HTTPException(
                    status_code=422,
                    detail="text 消息缺少 content 或 title/description",
                )
            wecom_resp = await sdk.send_text(
                user_id=body.user_id,
                content=text_content,
            )

        elif body.message_type == "text_card":
            if not body.title:
                raise HTTPException(status_code=422, detail="text_card 消息缺少 title")
            if not body.url:
                # 无 url 时降级为 text 消息
                log.info("wecom_internal_text_card_downgrade_no_url")
                text_content = f"{body.title}\n{body.description or ''}"
                wecom_resp = await sdk.send_text(
                    user_id=body.user_id,
                    content=text_content,
                )
            else:
                wecom_resp = await sdk.send_text_card(
                    user_id=body.user_id,
                    title=body.title,
                    description=body.description or "",
                    url=body.url,
                    btntxt=body.btntxt or "查看详情",
                )

        elif body.message_type == "news":
            if not body.articles:
                raise HTTPException(status_code=422, detail="news 消息缺少 articles")
            wecom_resp = await sdk.send_news(
                user_id=body.user_id,
                articles=body.articles,
            )

        else:
            raise HTTPException(
                status_code=422,
                detail=f"不支持的消息类型: {body.message_type}",
            )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — SDK 底层异常统一转 502
        log.error(
            "wecom_internal_send_sdk_error",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"企微发送失败: {exc}") from exc

    log.info("wecom_internal_send_success")
    return WecomSendResponse(
        ok=True,
        message_type=body.message_type,
        user_id=body.user_id,
        wecom_response=wecom_resp,
    )
