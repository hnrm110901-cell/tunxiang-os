"""企业微信会话存档 API 封装

提供会话存档相关的企微 API 调用：
  1. 获取会话存档权限信息
  2. 获取用户同意情况
  3. 获取加密的会话原始数据
  4. 解密回调推送的加密消息

依赖 shared/integrations/wecom_sdk.py 的 access_token 管理。

环境变量：
  WECOM_CORP_ID            — 企业 ID
  WECOM_CORP_SECRET        — 会话存档 Secret（需在企微管理后台配置）
  WECOM_CHAT_ARCHIVE_KEY   — 会话存档 RSA 私钥（PKCS#1 PEM，用于解密回调）
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import httpx
import structlog

from shared.integrations.wecom_sdk import BASE_URL, WeComAPIError

logger = structlog.get_logger(__name__)

# ─── 环境变量 ───

_CORP_ID = os.environ.get("WECOM_CORP_ID", "")
_ARCHIVE_SECRET = os.environ.get("WECOM_CHAT_ARCHIVE_SECRET", "")
_ARCHIVE_KEY_PATH = os.environ.get("WECOM_CHAT_ARCHIVE_KEY_PATH", "")


def _is_configured() -> bool:
    return bool(_CORP_ID and _ARCHIVE_SECRET)


def _load_archive_private_key() -> bytes | None:
    """加载会话存档 RSA 私钥。"""
    if not _ARCHIVE_KEY_PATH:
        return None
    try:
        with open(_ARCHIVE_KEY_PATH, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("chat_archive_private_key_not_found", path=_ARCHIVE_KEY_PATH)
        return None


# ─── SDK ───


class WeComChatArchiveSDK:
    """企业微信会话存档 API 客户端。

    使用独立的 access_token（会话存档有单独的 Secret）。
    需要 企微管理后台 → 管理工具 → 会话存档 开通并配置。
    """

    _TOKEN_BUFFER_SEC = 300

    def __init__(
        self,
        corp_id: str = "",
        archive_secret: str = "",
    ) -> None:
        self.corp_id = corp_id or _CORP_ID
        self.archive_secret = archive_secret or _ARCHIVE_SECRET
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._mock_mode = not _is_configured()

        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

        if self._mock_mode:
            logger.warning("WeComChatArchiveSDK: 未配置环境变量，进入 Mock 模式。")

    # ─── Token ───

    async def _get_access_token(self) -> str:
        if self._mock_mode:
            return "MOCK_ACCESS_TOKEN"

        import time

        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        resp = await self._client.get(
            "/gettoken",
            params={"corpid": self.corp_id, "corpsecret": self.archive_secret},
        )
        data = resp.json()
        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise WeComAPIError(
                errcode=errcode,
                errmsg=data.get("errmsg", "unknown"),
                url="/gettoken",
            )

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        self._token_expires_at = now + expires_in - self._TOKEN_BUFFER_SEC
        return self._access_token

    # ─── 权限与配置 ───

    async def get_permission(self) -> dict[str, Any]:
        """获取会话存档权限信息。

        POST /cgi-bin/msgaudit/get_permission

        Returns:
            {errcode, errmsg, permission, ...}
            permission: 1=已开通, 0=未开通
        """
        if self._mock_mode:
            return {"errcode": 0, "errmsg": "ok", "permission": 1}

        token = await self._get_access_token()
        resp = await self._client.post(
            "/msgaudit/get_permission",
            params={"access_token": token},
        )
        data = resp.json()
        _check_response(data, "/msgaudit/get_permission")
        return data

    async def get_agree_info(self, userid: str) -> dict[str, Any]:
        """获取用户是否同意会话存档。

        POST /cgi-bin/msgaudit/get_agree_info

        Args:
            userid: 企业成员 userid

        Returns:
            {errcode, errmsg, agree_info: {status, ...}}
            status: 1=已同意, 2=未同意
        """
        if self._mock_mode:
            return {"errcode": 0, "errmsg": "ok", "agree_info": {"status": 1}}

        token = await self._get_access_token()
        resp = await self._client.post(
            "/msgaudit/get_agree_info",
            params={"access_token": token},
            json={"userid": userid},
        )
        data = resp.json()
        _check_response(data, "/msgaudit/get_agree_info")
        return data

    # ─── 获取加密会话数据 ───

    async def get_raw_data(self, seq: int, limit: int = 100) -> dict[str, Any]:
        """获取加密的会话存档数据。

        POST /cgi-bin/msgaudit/get_raw_data

        Args:
            seq: 起始 seq（从 0 开始，每次返回的最大 seq 用于下一次请求）
            limit: 每次拉取条数（最大 1000）

        Returns:
            {errcode, errmsg, raw_data_list: [{seq, msgid, publickey_ver, encrypt_random_key, encrypt_chat_msg}], ...}
        """
        if self._mock_mode:
            return {
                "errcode": 0,
                "errmsg": "ok",
                "raw_data_list": [
                    {
                        "seq": seq,
                        "msgid": f"MOCK_MSG_{seq}",
                        "publickey_ver": 1,
                        "encrypt_random_key": base64.b64encode(b"mock_random_key").decode(),
                        "encrypt_chat_msg": base64.b64encode(
                            json.dumps({"msgtype": "text", "content": "Mock消息"}).encode()
                        ).decode(),
                    }
                ],
            }

        token = await self._get_access_token()
        resp = await self._client.post(
            "/msgaudit/get_raw_data",
            params={"access_token": token},
            json={"seq": seq, "limit": limit},
        )
        data = resp.json()
        _check_response(data, "/msgaudit/get_raw_data")
        return data

    # ─── 获取群聊会话 ───

    async def get_groupchat(self, chatid: str) -> dict[str, Any]:
        """获取群聊会话信息。

        POST /cgi-bin/msgaudit/groupchat/get

        Args:
            chatid: 群聊 ID

        Returns:
            {errcode, errmsg, groupchat: {chatid, name, member_count, ...}}
        """
        if self._mock_mode:
            return {
                "errcode": 0,
                "errmsg": "ok",
                "groupchat": {
                    "chatid": chatid,
                    "name": "Mock群聊",
                    "member_count": 5,
                },
            }

        token = await self._get_access_token()
        resp = await self._client.post(
            "/msgaudit/groupchat/get",
            params={"access_token": token},
            json={"chatid": chatid},
        )
        data = resp.json()
        _check_response(data, "/msgaudit/groupchat/get")
        return data

    # ─── 关闭 ───

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "WeComChatArchiveSDK":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


# ─── 内部辅助 ───


def _check_response(data: dict[str, Any], url: str) -> None:
    errcode = data.get("errcode", 0)
    if errcode != 0:
        raise WeComAPIError(
            errcode=errcode,
            errmsg=data.get("errmsg", "unknown"),
            url=url,
        )


# ─── 全局单例 ───

_instance: WeComChatArchiveSDK | None = None


def get_chat_archive_sdk() -> WeComChatArchiveSDK:
    global _instance
    if _instance is None:
        _instance = WeComChatArchiveSDK()
    return _instance
