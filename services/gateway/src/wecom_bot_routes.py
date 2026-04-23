"""
企微机器人对话入口

POST /api/v1/wecom/bot/callback — 企微机器人消息回调
  接收店长在企微发的消息 → 路由到 NLQ 引擎处理 → 返回自然语言回答

技术要点：
  1. 企微机器人 webhook 接收消息
  2. 调用 tx-analytics NLQ /ask 端点
  3. 将 NLQ 结果格式化为企微消息返回
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/wecom/bot", tags=["wecom-bot"])

# ─── 配置 ────────────────────────────────────────────────────────────

_BOT_CALLBACK_TOKEN: str = os.getenv("WECOM_BOT_CALLBACK_TOKEN", "")
_BOT_ENCODING_AES_KEY: str = os.getenv("WECOM_BOT_ENCODING_AES_KEY", "")
_NLQ_SERVICE_URL: str = os.getenv("TX_ANALYTICS_URL", "http://tx-analytics:8009")
_BOT_WEBHOOK_URL: str = os.getenv("WECOM_BOT_WEBHOOK_URL", "")


# ─── 签名验证 ────────────────────────────────────────────────────────


def _verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """验证企微回调签名：sha1(排序拼接 token + timestamp + nonce)"""
    parts = sorted([token, timestamp, nonce])
    raw = "".join(parts).encode("utf-8")
    expected = hashlib.sha1(raw).hexdigest()
    return expected == signature


# ─── NLQ 调用 ────────────────────────────────────────────────────────


async def _call_nlq(
    question: str,
    tenant_id: str,
    user_id: str = "",
) -> dict[str, Any]:
    """调用 tx-analytics NLQ /ask 端点获取回答"""
    url = f"{_NLQ_SERVICE_URL}/api/v1/nlq/ask"
    payload = {
        "question": question,
        "session_id": f"wecom_{user_id}" if user_id else "wecom_anonymous",
    }
    headers = {
        "X-Tenant-ID": tenant_id,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("nlq_call_success", question=question[:50], status=resp.status_code)
            return data
    except httpx.TimeoutException:
        logger.warning("nlq_call_timeout", question=question[:50])
        return {"ok": False, "error": "NLQ 服务响应超时，请稍后重试"}
    except httpx.HTTPStatusError as exc:
        logger.warning("nlq_call_http_error", status=exc.response.status_code, question=question[:50])
        return {"ok": False, "error": f"NLQ 服务返回错误: {exc.response.status_code}"}
    except httpx.ConnectError:
        logger.warning("nlq_call_connect_error", question=question[:50])
        return {"ok": False, "error": "无法连接 NLQ 服务"}


def _format_nlq_response(nlq_result: dict[str, Any]) -> str:
    """将 NLQ 返回结果格式化为企微消息文本"""
    if not nlq_result.get("ok"):
        return nlq_result.get("error", "抱歉，暂时无法处理您的问题，请稍后重试。")

    data = nlq_result.get("data", {})
    answer = data.get("answer", "")
    if not answer:
        answer = data.get("narrative", data.get("text", "暂无回答"))

    # 追加建议操作（如有）
    actions = data.get("actions", [])
    if actions:
        answer += "\n\n💡 建议操作："
        for act in actions[:3]:
            label = act.get("label", act.get("action", ""))
            if label:
                answer += f"\n• {label}"

    # 追加图表提示（如有）
    chart_type = data.get("chart_type", "")
    if chart_type:
        answer += f"\n\n📊 可在驾驶舱查看{chart_type}图表"

    return answer


async def _send_wecom_reply(webhook_url: str, content: str) -> None:
    """通过企微 webhook 发送回复消息"""
    if not webhook_url:
        logger.warning("wecom_bot_webhook_not_configured")
        return

    payload = {
        "msgtype": "text",
        "text": {"content": content},
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("wecom_bot_reply_sent", status=resp.status_code)
    except httpx.HTTPError as exc:
        logger.warning("wecom_bot_reply_failed", error=str(exc))


# ─── XML 解析 ────────────────────────────────────────────────────────


def _parse_xml_message(raw_xml: str) -> dict[str, str]:
    """解析企微回调 XML 消息"""
    try:
        root = ET.fromstring(raw_xml)  # noqa: S314 — trusted WeWork webhook XML
    except ET.ParseError as exc:
        logger.error("wecom_bot_xml_parse_error", error=str(exc))
        return {}

    result: dict[str, str] = {}
    for child in root:
        result[child.tag] = (child.text or "").strip()
    return result


# ─── 请求模型（JSON 模式） ────────────────────────────────────────────


class BotMessageRequest(BaseModel):
    """企微机器人消息（JSON 格式回调）"""

    msg_type: str = Field(default="text", alias="MsgType", description="消息类型")
    content: str = Field(default="", alias="Content", description="消息内容")
    from_user: str = Field(default="", alias="FromUserName", description="发送者企微ID")
    create_time: int = Field(default=0, alias="CreateTime", description="消息创建时间戳")


# ─── 路由 ─────────────────────────────────────────────────────────────


@router.get("/callback")
async def bot_callback_verify(
    msg_signature: str = Query("", description="企微签名"),
    timestamp: str = Query("", description="时间戳"),
    nonce: str = Query("", description="随机数"),
    echostr: str = Query("", description="验证字符串"),
) -> Response:
    """企微服务器验证（GET 请求）"""
    if _BOT_CALLBACK_TOKEN and msg_signature:
        if not _verify_signature(_BOT_CALLBACK_TOKEN, timestamp, nonce, msg_signature):
            raise HTTPException(status_code=403, detail="签名验证失败")
    return Response(content=echostr, media_type="text/plain")


@router.post("/callback")
async def bot_callback_message(
    request: Request,
    msg_signature: str = Query("", description="企微签名"),
    timestamp: str = Query("", description="时间戳"),
    nonce: str = Query("", description="随机数"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> dict:
    """
    企微机器人消息回调

    接收店长在企微发的消息，路由到 NLQ 引擎处理，返回自然语言回答。
    支持 XML 和 JSON 两种回调格式。
    """
    # 签名验证
    if _BOT_CALLBACK_TOKEN and msg_signature:
        if not _verify_signature(_BOT_CALLBACK_TOKEN, timestamp, nonce, msg_signature):
            raise HTTPException(status_code=403, detail="签名验证失败")

    # 解析消息（支持 XML 和 JSON）
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")

    if "xml" in content_type or body_str.strip().startswith("<"):
        msg = _parse_xml_message(body_str)
        msg_type = msg.get("MsgType", "text")
        content = msg.get("Content", "")
        from_user = msg.get("FromUserName", "")
    else:
        try:
            import json

            msg = json.loads(body_str)
            msg_type = msg.get("MsgType", msg.get("msg_type", "text"))
            content = msg.get("Content", msg.get("content", ""))
            from_user = msg.get("FromUserName", msg.get("from_user", ""))
        except (json.JSONDecodeError, ValueError):
            logger.warning("wecom_bot_invalid_body", body=body_str[:200])
            return {"ok": False, "error": "无法解析消息体"}

    logger.info(
        "wecom_bot_message_received",
        msg_type=msg_type,
        from_user=from_user,
        content_preview=content[:50] if content else "",
    )

    # 只处理文本消息
    if msg_type != "text" or not content.strip():
        return {
            "ok": True,
            "data": {"reply": "目前仅支持文本消息，请输入您的经营问题。"},
        }

    # 调用 NLQ 引擎
    nlq_result = await _call_nlq(content.strip(), x_tenant_id, from_user)

    # 格式化回复
    reply_text = _format_nlq_response(nlq_result)

    # 异步发送企微回复（不阻塞响应）
    import asyncio

    if _BOT_WEBHOOK_URL:
        asyncio.create_task(_send_wecom_reply(_BOT_WEBHOOK_URL, reply_text))

    return {
        "ok": True,
        "data": {
            "from_user": from_user,
            "question": content.strip(),
            "reply": reply_text,
            "nlq_ok": nlq_result.get("ok", False),
        },
    }
