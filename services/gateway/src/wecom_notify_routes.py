"""企微群管理与通知推送路由

POST /api/v1/wecom/groups              创建群组
GET  /api/v1/wecom/groups              群组列表
POST /api/v1/wecom/groups/{id}/send-message  发送消息到群
POST /api/v1/wecom/notify              发送通知（支持文本/卡片/图文/markdown）
GET  /api/v1/wecom/status              企微连接状态

实现要点：
- 从环境变量读取企微 CorpID/AgentID/Secret（不硬编码）
- 调用企微开放API（httpx 异步）
- 无企微配置时返回 {ok: true, data: {skipped: true, reason: "企微未配置"}}，不抛异常
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Literal, Optional

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .external_sdk import WecomAPIError, WecomConfig, WecomSDK
from .response import ok

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/wecom", tags=["wecom-notify"])


# ── 企微配置检查 ───────────────────────────────────────────────────


def _wecom_configured() -> bool:
    """检查企微必要环境变量是否已配置"""
    return bool(
        os.getenv("WECOM_CORP_ID")
        and os.getenv("WECOM_AGENT_ID")
        and os.getenv("WECOM_SECRET")
    )


def _get_sdk() -> WecomSDK:
    """获取企微 SDK 实例（使用环境变量配置）"""
    return WecomSDK(
        config=WecomConfig(
            corp_id=os.getenv("WECOM_CORP_ID", ""),
            agent_id=os.getenv("WECOM_AGENT_ID", ""),
            secret=os.getenv("WECOM_SECRET", ""),
        )
    )


# ── Request schemas ──────────────────────────────────────────────


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="群名称")
    owner_userid: str = Field(..., description="群主企微 userid")
    member_userids: list[str] = Field(..., min_length=2, description="成员 userid 列表（至少2人）")
    chatid: Optional[str] = Field(None, description="自定义群 ID（可选）")


class SendGroupMessageRequest(BaseModel):
    msgtype: Literal["text", "textcard", "news", "markdown"] = Field(
        default="text", description="消息类型"
    )
    content: dict[str, Any] = Field(
        ...,
        description=(
            "消息内容体，按 msgtype 对应：\n"
            '  text:     {"content": "文本内容"}\n'
            '  textcard: {"title": "...", "description": "...", "url": "...", "btntxt": "详情"}\n'
            '  news:     {"articles": [{"title": "...", "description": "...", "url": "...", "picurl": "..."}]}\n'
            '  markdown: {"content": "**Markdown 内容**"}'
        ),
    )


class NotifyRequest(BaseModel):
    touser: str = Field(..., description="接收人企微 userid，多人用 | 分隔，全员用 @all")
    msgtype: Literal["text", "textcard", "news", "markdown"] = Field(
        default="text", description="消息类型"
    )
    content: dict[str, Any] = Field(..., description="消息内容体（同 SendGroupMessageRequest.content）")


# ── 工具函数 ──────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误") from exc


# ── 1. 创建群组 ───────────────────────────────────────────────────


@router.post("/groups")
async def create_wecom_group(
    req: CreateGroupRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """调用企微 API 创建群组。

    无企微配置时返回 skipped 响应，不抛异常。

    Returns:
        {ok, data: {chatid, name, member_count}}
        或 {ok, data: {skipped: true, reason: "企微未配置"}}
    """
    _parse_tenant(x_tenant_id)

    if not _wecom_configured():
        logger.info("wecom_create_group_skipped_no_config", group_name=req.name)
        return ok({"skipped": True, "reason": "企微未配置"})

    sdk = _get_sdk()
    log = logger.bind(group_name=req.name, tenant_id=x_tenant_id)

    try:
        result = await sdk.create_group_chat(
            name=req.name,
            owner_userid=req.owner_userid,
            member_userids=req.member_userids,
            chatid=req.chatid,
        )
    except WecomAPIError as exc:
        log.error("wecom_create_group_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
        raise HTTPException(
            status_code=400,
            detail=f"企微 API 错误 {exc.errcode}: {exc.errmsg}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        log.error("wecom_create_group_http_error", status=exc.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"企微接口 HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        log.error("wecom_create_group_request_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"企微接口请求失败: {exc}") from exc

    chatid: str = result.get("chatid", "")
    log.info("wecom_create_group_ok", chatid=chatid)

    return ok({
        "chatid": chatid,
        "name": req.name,
        "member_count": len(req.member_userids),
    })


# ── 2. 群组列表 ──────────────────────────────────────────────────


@router.get("/groups")
async def list_wecom_groups(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """列出当前租户的企微群组配置。

    实际群列表来自 wecom_group_configs 表（由 wecom_group_routes 管理）。
    若企微未配置，返回 skipped 响应。

    Returns:
        {ok, data: {items: [...], total}}
        或 {ok, data: {skipped: true, reason: "企微未配置"}}
    """
    tenant_id = _parse_tenant(x_tenant_id)

    if not _wecom_configured():
        logger.info("wecom_list_groups_skipped_no_config", tenant_id=str(tenant_id))
        return ok({"skipped": True, "reason": "企微未配置", "items": [], "total": 0})

    # 从数据库读取群配置（通过内部服务调用避免重复 DB 依赖）
    try:
        from sqlalchemy import select

        from .database import get_async_session  # type: ignore[import]
        from .models.wecom_group import WecomGroupConfig  # type: ignore[import]

        async for db in get_async_session():
            stmt = (
                select(WecomGroupConfig)
                .where(WecomGroupConfig.tenant_id == tenant_id)
                .order_by(WecomGroupConfig.created_at.desc())
                .limit(100)
            )
            result = await db.execute(stmt)
            configs = result.scalars().all()

            items = [
                {
                    "config_id": str(c.id),
                    "group_name": c.group_name,
                    "group_chat_id": c.group_chat_id,
                    "status": c.status,
                    "max_members": c.max_members,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in configs
            ]
            return ok({"items": items, "total": len(items)})

    except ImportError:
        logger.warning("wecom_list_groups_db_not_configured", tenant_id=str(tenant_id))
        return ok({"items": [], "total": 0, "note": "数据库未配置"})


# ── 3. 发送消息到群 ──────────────────────────────────────────────


@router.post("/groups/{chatid}/send-message")
async def send_group_message(
    chatid: str,
    req: SendGroupMessageRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """向指定企微群发送消息。

    无企微配置时返回 skipped 响应，不抛异常。

    Args:
        chatid: 企微群 ID（来自建群结果）

    Returns:
        {ok, data: {chatid, msgtype, status: "sent"}}
        或 {ok, data: {skipped: true, reason: "企微未配置"}}
    """
    _parse_tenant(x_tenant_id)

    if not _wecom_configured():
        logger.info(
            "wecom_send_group_message_skipped_no_config",
            chatid=chatid,
            msgtype=req.msgtype,
        )
        return ok({"skipped": True, "reason": "企微未配置"})

    sdk = _get_sdk()
    log = logger.bind(chatid=chatid, msgtype=req.msgtype, tenant_id=x_tenant_id)

    try:
        await sdk.send_group_chat_message(
            chatid=chatid,
            msgtype=req.msgtype,
            content_dict=req.content,
        )
    except WecomAPIError as exc:
        log.error("wecom_send_group_message_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
        raise HTTPException(
            status_code=400,
            detail=f"企微 API 错误 {exc.errcode}: {exc.errmsg}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        log.error("wecom_send_group_message_http_error", status=exc.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"企微接口 HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        log.error("wecom_send_group_message_request_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"企微接口请求失败: {exc}") from exc

    log.info("wecom_send_group_message_ok")
    return ok({"chatid": chatid, "msgtype": req.msgtype, "status": "sent"})


# ── 4. 发送通知 ──────────────────────────────────────────────────


@router.post("/notify")
async def send_wecom_notify(
    req: NotifyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """向企微用户发送通知消息（支持文本/卡片/图文/markdown）。

    无企微配置时返回 skipped 响应，不抛异常。

    Returns:
        {ok, data: {touser, msgtype, status: "sent"}}
        或 {ok, data: {skipped: true, reason: "企微未配置"}}
    """
    _parse_tenant(x_tenant_id)

    if not _wecom_configured():
        logger.info(
            "wecom_notify_skipped_no_config",
            touser=req.touser,
            msgtype=req.msgtype,
        )
        return ok({"skipped": True, "reason": "企微未配置"})

    sdk = _get_sdk()
    log = logger.bind(touser=req.touser, msgtype=req.msgtype, tenant_id=x_tenant_id)

    try:
        if req.msgtype == "text":
            content_text = req.content.get("content", "")
            await sdk.send_text(user_id=req.touser, content=content_text)

        elif req.msgtype == "textcard":
            await sdk.send_text_card(
                user_id=req.touser,
                title=req.content.get("title", ""),
                description=req.content.get("description", ""),
                url=req.content.get("url", ""),
                btntxt=req.content.get("btntxt", "详情"),
            )

        elif req.msgtype == "news":
            articles = req.content.get("articles", [])
            await sdk.send_news(user_id=req.touser, articles=articles)

        elif req.msgtype == "markdown":
            content_md = req.content.get("content", "")
            await sdk.send_markdown(user_id=req.touser, content=content_md)

        else:
            raise HTTPException(status_code=400, detail=f"不支持的消息类型: {req.msgtype}")

    except WecomAPIError as exc:
        log.error("wecom_notify_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
        raise HTTPException(
            status_code=400,
            detail=f"企微 API 错误 {exc.errcode}: {exc.errmsg}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        log.error("wecom_notify_http_error", status=exc.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"企微接口 HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        log.error("wecom_notify_request_error", error=str(exc))
        raise HTTPException(status_code=503, detail=f"企微接口请求失败: {exc}") from exc

    log.info("wecom_notify_sent_ok")
    return ok({"touser": req.touser, "msgtype": req.msgtype, "status": "sent"})


# ── 5. 企微连接状态 ──────────────────────────────────────────────


@router.get("/status")
async def get_wecom_status(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """检查企微连接状态（验证 access_token 是否可正常获取）。

    无企微配置时返回 {configured: false}，不抛异常。

    Returns:
        {ok, data: {configured: bool, corp_id: str, agent_id: str, token_ok: bool}}
    """
    _parse_tenant(x_tenant_id)

    corp_id = os.getenv("WECOM_CORP_ID", "")
    agent_id = os.getenv("WECOM_AGENT_ID", "")

    if not _wecom_configured():
        logger.info("wecom_status_not_configured", tenant_id=x_tenant_id)
        return ok({
            "configured": False,
            "corp_id": corp_id or None,
            "agent_id": agent_id or None,
            "token_ok": False,
            "reason": "企微未配置（WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET 缺失）",
        })

    sdk = _get_sdk()
    token_ok = False
    error_detail: Optional[str] = None

    try:
        await sdk.get_access_token()
        token_ok = True
    except WecomAPIError as exc:
        error_detail = f"WecomAPIError {exc.errcode}: {exc.errmsg}"
        logger.warning("wecom_status_token_api_error", errcode=exc.errcode, errmsg=exc.errmsg)
    except httpx.RequestError as exc:
        error_detail = str(exc)
        logger.warning("wecom_status_token_request_error", error=str(exc))
    except httpx.HTTPStatusError as exc:
        error_detail = f"http_{exc.response.status_code}"
        logger.warning("wecom_status_token_http_error", status=exc.response.status_code)

    return ok({
        "configured": True,
        "corp_id": corp_id,
        "agent_id": agent_id,
        "token_ok": token_ok,
        "error": error_detail,
    })
