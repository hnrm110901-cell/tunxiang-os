"""视频号小店电商回调路由 — VC-1.1

接收微信视频号小店的订单/商品回调。
Gateway 层负责：URL 验签 + 消息转发至 tx-trade webhook。

微信文档：https://developers.weixin.qq.com/doc/channels/API/
"""

import hashlib
import os
import time
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/channels-ec", tags=["channels-ec"])

# 视频号小店配置
CHANNELS_EC_APP_ID = os.environ.get("CHANNELS_EC_APP_ID", "")
CHANNELS_EC_TOKEN = os.environ.get("CHANNELS_EC_TOKEN", "")
CHANNELS_EC_ENCODING_AES_KEY = os.environ.get("CHANNELS_EC_ENCODING_AES_KEY", "")

# 转发目标（tx-trade webhook）
TRADE_WEBHOOK_BASE = os.environ.get("TRADE_WEBHOOK_BASE", "http://localhost:8001")

_TIMESTAMP_TOLERANCE = 300


class ChannelsECCallbackResp(BaseModel):
    """视频号小店回调响应"""

    msg: str = "ok"


def _verify_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """微信 SHA1 签名验证：SHA1(sorted(token, timestamp, nonce))

    与公众号/小程序/视频号小店共用同一签名算法。
    """
    if not CHANNELS_EC_TOKEN:
        logger.error("channels_ec_no_token_configured")
        return False

    try:
        ts = int(timestamp)
        if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
            logger.warning("channels_ec_timestamp_expired", diff=abs(int(time.time()) - ts))
            return False
    except (ValueError, TypeError):
        logger.warning("channels_ec_bad_timestamp", timestamp=timestamp)
        return False

    sign_list = sorted([CHANNELS_EC_TOKEN, timestamp, nonce])
    sign_str = "".join(sign_list)
    expected = hashlib.sha1(sign_str.encode("utf-8")).hexdigest()
    return expected == signature


@router.get("/callback", response_model=ChannelsECCallbackResp)
async def verify_callback_url(
    request: Request,
) -> ChannelsECCallbackResp:
    """微信首次配置回调 URL 时的验签请求（GET）。

    WeChat 会带着 echostr 参数 GET 请求此 URL，
    需要原样返回 echostr 以证明 URL 所有权。
    """
    signature = request.query_params.get("signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    echostr = request.query_params.get("echostr", "")

    if not signature or not timestamp or not nonce:
        raise HTTPException(status_code=400, detail="缺少验签参数")

    if not _verify_signature(signature, timestamp, nonce):
        logger.warning("channels_ec_url_verify_failed")
        raise HTTPException(status_code=403, detail="签名验证失败")

    if echostr:
        # 返回 echostr 作为响应体（微信协议要求）
        return ChannelsECCallbackResp(msg=echostr)

    return ChannelsECCallbackResp(msg="ok")


@router.post("/callback")
async def channels_ec_callback(request: Request) -> dict:
    """接收视频号小店事件推送（POST）。

    验证签名后将事件体转发到 tx-trade webhook 做订单持久化。
    支持的事件类型: order_create, order_pay, order_refund, 等。
    """
    signature = request.headers.get("X-Wechat-Signature", "")
    timestamp = request.headers.get("X-Wechat-Timestamp", "")
    nonce = request.headers.get("X-Wechat-Nonce", "")

    if not _verify_signature(signature, timestamp, nonce):
        logger.warning("channels_ec_callback_sign_invalid")
        raise HTTPException(status_code=403, detail="签名验证失败")

    raw_body = (await request.body()).decode("utf-8")
    try:
        body: dict[str, Any] = await request.json()
    except ValueError as exc:
        logger.error("channels_ec_bad_json", error=str(exc))
        raise HTTPException(status_code=400, detail="请求体 JSON 解析失败") from exc

    event_type = body.get("event", body.get("type", "unknown"))
    logger.info("channels_ec_event_received", event_type=event_type)

    # 转发到 tx-trade webhook
    target_url = f"{TRADE_WEBHOOK_BASE}/api/v1/webhook/channels-ec/callback"
    forward_headers = {
        "Content-Type": "application/json",
        "X-Wechat-Signature": signature,
        "X-Wechat-Timestamp": timestamp,
        "X-Wechat-Nonce": nonce,
        "X-Tenant-ID": request.headers.get("X-Tenant-ID", ""),
        "X-Store-ID": request.headers.get("X-Store-ID", ""),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                target_url,
                content=raw_body,
                headers=forward_headers,
            )
            resp.raise_for_status()
            result = resp.json()
    except httpx.TimeoutException:
        logger.error("channels_ec_forward_timeout", target=target_url)
        raise HTTPException(status_code=504, detail="转发到订单服务超时")
    except httpx.HTTPStatusError as exc:
        logger.error("channels_ec_forward_error", status=exc.response.status_code)
        raise HTTPException(status_code=502, detail="转发到订单服务失败")
    except httpx.ConnectError as exc:
        logger.error("channels_ec_forward_connect_error", error=str(exc))
        raise HTTPException(status_code=502, detail="无法连接到订单服务")

    return {"ok": True, "data": result}
