"""企微 JS-SDK 签名接口

GET /api/v1/wecom/jssdk-config?url={当前页面URL}

为企微侧边栏 H5 应用提供 wx.config + wx.agentConfig 所需的签名数据。

签名算法（标准 jsapi_ticket 算法）：
  str = "jsapi_ticket={ticket}&noncestr={nonce}&timestamp={ts}&url={url}"
  signature = sha1(str)
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Query

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/wecom", tags=["wecom-jssdk"])

# ─── 企微配置（环境变量） ────────────────────────────────────────────
_CORP_ID: str    = os.getenv("WECOM_CORP_ID", "")
_AGENT_ID: str   = os.getenv("WECOM_AGENT_ID", "")
_SECRET: str     = os.getenv("WECOM_SECRET", "")

# ─── jsapi_ticket 内存缓存（有效期 7200 秒，提前 300 秒刷新） ────────
_ticket_cache: dict[str, object] = {
    "ticket": None,
    "agent_ticket": None,
    "expires_at": 0.0,
}

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


async def _get_access_token() -> str:
    """获取企微 access_token（复用 external_sdk 逻辑，此处独立实现避免循环依赖）"""
    url = (
        f"{WECOM_API_BASE}/gettoken"
        f"?grant_type=client_credential"
        f"&corpid={_CORP_ID}"
        f"&corpsecret={_SECRET}"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("jssdk_get_token_http_error", status=exc.response.status_code)
            raise HTTPException(status_code=502, detail="企微 access_token 获取失败") from exc
        except httpx.ConnectError as exc:
            logger.error("jssdk_get_token_connect_error", error=str(exc))
            raise HTTPException(status_code=502, detail="企微 API 连接失败") from exc
        except httpx.TimeoutException as exc:
            logger.error("jssdk_get_token_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="企微 API 超时") from exc

    data = resp.json()
    if data.get("errcode", 0) != 0:
        logger.error("jssdk_get_token_api_error", errcode=data.get("errcode"), errmsg=data.get("errmsg"))
        raise HTTPException(status_code=502, detail=f"企微 API 错误: {data.get('errmsg')}")

    return str(data["access_token"])


async def _get_jsapi_ticket(token: str) -> str:
    """获取公众号 jsapi_ticket（用于 wx.config）"""
    url = f"{WECOM_API_BASE}/get_jsapi_ticket?access_token={token}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("jssdk_get_ticket_http_error", status=exc.response.status_code)
            raise HTTPException(status_code=502, detail="jsapi_ticket 获取失败") from exc
        except httpx.ConnectError as exc:
            logger.error("jssdk_get_ticket_connect_error", error=str(exc))
            raise HTTPException(status_code=502, detail="企微 API 连接失败") from exc
        except httpx.TimeoutException as exc:
            logger.error("jssdk_get_ticket_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="企微 API 超时") from exc

    data = resp.json()
    if data.get("errcode", 0) != 0:
        logger.error("jssdk_get_ticket_api_error", errcode=data.get("errcode"), errmsg=data.get("errmsg"))
        raise HTTPException(status_code=502, detail=f"jsapi_ticket 错误: {data.get('errmsg')}")

    return str(data["ticket"])


async def _get_agent_ticket(token: str) -> str:
    """获取应用 ticket（用于 wx.agentConfig）"""
    url = f"{WECOM_API_BASE}/ticket/get?access_token={token}&type=agent_config"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("jssdk_get_agent_ticket_http_error", status=exc.response.status_code)
            raise HTTPException(status_code=502, detail="agent_ticket 获取失败") from exc
        except httpx.ConnectError as exc:
            logger.error("jssdk_get_agent_ticket_connect_error", error=str(exc))
            raise HTTPException(status_code=502, detail="企微 API 连接失败") from exc
        except httpx.TimeoutException as exc:
            logger.error("jssdk_get_agent_ticket_timeout", error=str(exc))
            raise HTTPException(status_code=504, detail="企微 API 超时") from exc

    data = resp.json()
    if data.get("errcode", 0) != 0:
        logger.error("jssdk_get_agent_ticket_api_error", errcode=data.get("errcode"), errmsg=data.get("errmsg"))
        raise HTTPException(status_code=502, detail=f"agent_ticket 错误: {data.get('errmsg')}")

    return str(data["ticket"])


async def _get_tickets() -> tuple[str, str]:
    """获取 jsapi_ticket + agent_ticket，带内存缓存（7200s，提前 300s 刷新）"""
    now = time.time()
    if (
        _ticket_cache["ticket"]
        and _ticket_cache["agent_ticket"]
        and now < float(_ticket_cache["expires_at"]) - 300
    ):
        return str(_ticket_cache["ticket"]), str(_ticket_cache["agent_ticket"])

    token = await _get_access_token()
    jsapi_ticket = await _get_jsapi_ticket(token)
    agent_ticket = await _get_agent_ticket(token)

    _ticket_cache["ticket"] = jsapi_ticket
    _ticket_cache["agent_ticket"] = agent_ticket
    _ticket_cache["expires_at"] = now + 7200

    logger.info("jssdk_tickets_refreshed")
    return jsapi_ticket, agent_ticket


def _sign(ticket: str, nonce: str, timestamp: int, url: str) -> str:
    """
    标准 jsapi_ticket 签名算法：
      sha1("jsapi_ticket=...&noncestr=...&timestamp=...&url=...")
    参数按字典序拼接（j < n < t < u）。
    """
    raw = (
        f"jsapi_ticket={ticket}"
        f"&noncestr={nonce}"
        f"&timestamp={timestamp}"
        f"&url={url}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@router.get("/jssdk-config")
async def get_jssdk_config(
    url: str = Query(..., description="当前 H5 页面完整 URL（不含 # 部分）"),
) -> dict:
    """返回企微 JS-SDK 鉴权所需的签名配置

    前端调用顺序：
      1. wx.config(appId, timestamp, nonceStr, signature)          # 使用本接口 signature
      2. wx.agentConfig(corpid, agentid, ..., agentSignature)      # 使用本接口 agentSignature
      3. wx.invoke('getCurExternalContact', ...)                    # 获取当前客户 ID
    """
    if not all([_CORP_ID, _AGENT_ID, _SECRET]):
        logger.error("jssdk_config_missing_env_vars")
        raise HTTPException(
            status_code=503,
            detail="企微 JS-SDK 配置未完整（WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_SECRET）",
        )

    jsapi_ticket, agent_ticket = await _get_tickets()

    # 每次请求生成新的 nonce + timestamp（安全要求）
    nonce = secrets.token_hex(8)          # 16 字符随机串
    timestamp = int(time.time())

    signature = _sign(jsapi_ticket, nonce, timestamp, url)
    agent_signature = _sign(agent_ticket, nonce, timestamp, url)

    logger.info("jssdk_config_generated", corp_id=_CORP_ID, url=url[:80])

    return {
        "ok": True,
        "data": {
            "appId":          _CORP_ID,
            "timestamp":      timestamp,
            "nonceStr":       nonce,
            "signature":      signature,
            "agentSignature": agent_signature,
            "agentId":        _AGENT_ID,
        },
    }
