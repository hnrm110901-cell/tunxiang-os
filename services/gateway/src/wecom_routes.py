"""企业微信回调处理路由

POST /api/v1/wecom/callback — 接收企微消息推送（XML）
GET  /api/v1/wecom/callback — 企微服务器验证（echostr）

支持的客户联系事件：
  customer_add    — 导购加客户好友
  customer_del    — 客户删除好友
  transfer_fail   — 好友转移失败（仅日志）
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/wecom", tags=["wecom-callback"])

_CALLBACK_TOKEN: str = os.getenv("WECOM_CALLBACK_TOKEN", "")

# tx-member 服务内部地址
_MEMBER_SERVICE_URL: str = os.getenv("TX_MEMBER_URL", "http://tx-member:8004")


def _verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """验证企微签名：sha1(排序拼接 token + timestamp + nonce)"""
    parts = sorted([token, timestamp, nonce])
    raw = "".join(parts).encode("utf-8")
    expected = hashlib.sha1(raw).hexdigest()
    return expected == signature


def _parse_xml_event(raw_xml: str) -> dict:
    """解析企微回调 XML，返回 key/value 字典（仅提取文本节点）"""
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        logger.error("wecom_callback_xml_parse_error", error=str(exc))
        return {}

    result: dict[str, str] = {}
    for child in root:
        result[child.tag] = (child.text or "").strip()
    return result


# ─────────────────────────────────────────────────────────────────
# 事件处理器（后台任务，不阻塞回调响应）
# ─────────────────────────────────────────────────────────────────

async def _handle_customer_add(event: dict) -> None:
    """处理 customer_add 事件：导购加客户好友

    幂等性：以 wecom_external_userid 为唯一键，PATCH 接口使用 upsert 语义。
    """
    external_userid: str = event.get("ExternalUserID", "")
    follow_user: str = event.get("UserID", "")
    state: str = event.get("State", "")  # 扫码来源，通常为 store_id

    if not external_userid:
        logger.warning("wecom_customer_add_missing_external_userid", event=event)
        return

    log = logger.bind(
        event_type="customer_add",
        external_userid=external_userid,
        follow_user=follow_user,
        state=state,
    )
    log.info("wecom_customer_add_processing")

    # 1. 获取客户详情（企微客户联系 API）
    from .wecom_contact import wecom_contact_sdk

    try:
        contact_data = await wecom_contact_sdk.get_external_contact(external_userid)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
        log.error("wecom_customer_add_get_contact_failed", error=str(exc))
        return

    ext_contact: dict = contact_data.get("external_contact", {})
    name: str = ext_contact.get("name", "")
    unionid: str = ext_contact.get("unionid", "")
    mobile: str = ext_contact.get("mobile", "")

    follow_at: str = datetime.now(timezone.utc).isoformat()

    # 2. 通知 tx-member 执行绑定（查找 + 更新或创建临时档案）
    wecom_payload = {
        "wecom_external_userid": external_userid,
        "wecom_follow_user": follow_user,
        "wecom_follow_at": follow_at,
        "wecom_remark": "",
        "mobile": mobile,
        "unionid": unionid,
        "name": name,
        "state": state,
    }

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.post(
                f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/wecom/bind_by_external_id",
                json=wecom_payload,
            )
            resp.raise_for_status()
            result = resp.json()
            log.info(
                "wecom_customer_add_bound",
                customer_id=result.get("data", {}).get("customer_id"),
                created=result.get("data", {}).get("created", False),
            )
        except httpx.HTTPStatusError as exc:
            log.error("wecom_customer_add_member_http_error", status=exc.response.status_code)
        except httpx.ConnectError as exc:
            log.error("wecom_customer_add_member_connect_error", error=str(exc))
        except httpx.TimeoutException as exc:
            log.error("wecom_customer_add_member_timeout", error=str(exc))


async def _handle_customer_del(event: dict) -> None:
    """处理 customer_del 事件：客户删除好友

    幂等性：如果已清空则 PATCH 无副作用。
    """
    external_userid: str = event.get("ExternalUserID", "")
    follow_user: str = event.get("UserID", "")

    if not external_userid:
        logger.warning("wecom_customer_del_missing_external_userid", event=event)
        return

    log = logger.bind(
        event_type="customer_del",
        external_userid=external_userid,
        follow_user=follow_user,
    )
    log.info("wecom_customer_del_processing")

    # 通知 tx-member 清空企微字段并打"已删除好友"标签
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.post(
                f"{_MEMBER_SERVICE_URL}/api/v1/member/customers/wecom/unbind_by_external_id",
                json={"wecom_external_userid": external_userid, "follow_user": follow_user},
            )
            resp.raise_for_status()
            log.info("wecom_customer_del_unbound")
        except httpx.HTTPStatusError as exc:
            log.error("wecom_customer_del_member_http_error", status=exc.response.status_code)
        except httpx.ConnectError as exc:
            log.error("wecom_customer_del_member_connect_error", error=str(exc))
        except httpx.TimeoutException as exc:
            log.error("wecom_customer_del_member_timeout", error=str(exc))


async def _handle_transfer_fail(event: dict) -> None:
    """处理 transfer_fail 事件：好友转移失败（仅记录日志）"""
    logger.warning(
        "wecom_transfer_fail",
        event_type="transfer_fail",
        failed_external_userid=event.get("ExternalUserID", ""),
        failed_user_id=event.get("UserID", ""),
        raw_event=event,
    )


# ─────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────

@router.get("/callback")
async def wecom_callback_verify(
    msg_signature: Optional[str] = Query(None),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> Response:
    """企微服务器验证接口（GET）"""
    signature = msg_signature or ""
    if not _verify_signature(_CALLBACK_TOKEN, timestamp, nonce, signature):
        logger.warning(
            "wecom_callback_verify_failed",
            timestamp=timestamp,
            nonce=nonce,
        )
        raise HTTPException(status_code=403, detail="signature mismatch")

    logger.info("wecom_callback_verified", timestamp=timestamp)
    return Response(content=echostr, media_type="text/plain")


@router.post("/callback")
async def wecom_callback_receive(
    request: Request,
    msg_signature: Optional[str] = Query(None),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> Response:
    """接收企微消息推送（POST XML）

    签名验证通过后立即返回 "success"（<500ms），
    耗时的业务处理通过 asyncio.create_task 异步执行。
    """
    signature = msg_signature or ""
    if not _verify_signature(_CALLBACK_TOKEN, timestamp, nonce, signature):
        logger.warning(
            "wecom_callback_post_verify_failed",
            timestamp=timestamp,
            nonce=nonce,
        )
        raise HTTPException(status_code=403, detail="signature mismatch")

    try:
        body = await request.body()
        raw_xml = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.error("wecom_callback_decode_error", error=str(exc))
        raise HTTPException(status_code=400, detail="invalid encoding") from exc

    event = _parse_xml_event(raw_xml)
    event_type: str = event.get("Event", "")
    msg_type: str = event.get("MsgType", "")

    logger.info(
        "wecom_callback_received",
        timestamp=timestamp,
        nonce=nonce,
        msg_type=msg_type,
        event_type=event_type,
        body_length=len(raw_xml),
    )

    # 路由到对应事件处理器（后台任务，不阻塞响应）
    if event_type == "change_external_contact":
        change_type: str = event.get("ChangeType", "")
        if change_type == "add_external_contact":
            asyncio.create_task(_handle_customer_add(event))
        elif change_type == "del_external_contact":
            asyncio.create_task(_handle_customer_del(event))
        else:
            logger.info("wecom_callback_unhandled_change_type", change_type=change_type)
    elif event_type == "transfer_fail":
        asyncio.create_task(_handle_transfer_fail(event))
    else:
        logger.info("wecom_callback_unhandled_event", event_type=event_type, msg_type=msg_type)

    return Response(content="success", media_type="text/plain")
