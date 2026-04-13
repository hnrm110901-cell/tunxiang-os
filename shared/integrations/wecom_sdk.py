"""企业微信 Server API 封装

通过 httpx.AsyncClient 调用企微开放 API，提供：
 - access_token 自动获取与缓存（7200s 有效期）
 - 部门列表 / 部门成员详情
 - 文本消息 / 模板卡片消息发送

环境变量（也可通过构造参数注入）：
  WECOM_CORP_ID
  WECOM_CORP_SECRET
  WECOM_AGENT_ID
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin"

# ─── 自定义异常 ──────────────────────────────────────────────────────────────────


class WeComAPIError(Exception):
    """企业微信 API 调用失败时抛出。"""

    def __init__(self, errcode: int, errmsg: str, url: str = ""):
        self.errcode = errcode
        self.errmsg = errmsg
        self.url = url
        super().__init__(f"WeComAPIError({errcode}): {errmsg} [{url}]")


# ─── SDK 主类 ─────────────────────────────────────────────────────────────────


class WeComSDK:
    """企业微信 Server API 客户端。

    Args:
        corp_id: 企业 ID
        corp_secret: 应用 Secret
        agent_id: 应用 AgentId（发送消息时需要）
    """

    # token 缓存提前 5 分钟刷新，避免临界失效
    _TOKEN_BUFFER_SEC = 300

    def __init__(self, corp_id: str, corp_secret: str, agent_id: str = "") -> None:
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id

        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Token 管理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_access_token(self) -> str:
        """获取 access_token，带本地缓存（7200s 有效期，提前 300s 刷新）。"""
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        resp = await self._client.get(
            "/gettoken",
            params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
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

        logger.info(
            "wecom_token_refreshed",
            corp_id=self.corp_id,
            expires_in=expires_in,
        )
        return self._access_token

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  通讯录 — 部门
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_department_list(self) -> list[dict[str, Any]]:
        """获取部门列表。

        Returns:
            [{id, name, parentid, order}, ...]
        """
        token = await self.get_access_token()
        resp = await self._client.get(
            "/department/list",
            params={"access_token": token},
        )
        data = resp.json()
        self._check_response(data, "/department/list")
        departments: list[dict[str, Any]] = data.get("department", [])
        logger.debug("wecom_department_list", count=len(departments))
        return departments

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  通讯录 — 成员
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_user_list(self, department_id: int) -> list[dict[str, Any]]:
        """获取部门成员详情列表。

        Args:
            department_id: 部门 ID

        Returns:
            [{userid, name, mobile, department, position, status, ...}, ...]
        """
        token = await self.get_access_token()
        resp = await self._client.get(
            "/user/list",
            params={
                "access_token": token,
                "department_id": department_id,
                "fetch_child": 1,
            },
        )
        data = resp.json()
        self._check_response(data, "/user/list")
        users: list[dict[str, Any]] = data.get("userlist", [])
        logger.debug(
            "wecom_user_list",
            department_id=department_id,
            count=len(users),
        )
        return users

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  消息发送
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_text_message(self, touser: str, content: str) -> dict[str, Any]:
        """发送文本消息。

        Args:
            touser: 接收者 userid（多人用 ``|`` 分隔）
            content: 消息文本

        Returns:
            API 响应 dict（含 errcode/errmsg/invaliduser 等）
        """
        token = await self.get_access_token()
        payload = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(self.agent_id) if self.agent_id else 0,
            "text": {"content": content},
        }
        resp = await self._client.post(
            "/message/send",
            params={"access_token": token},
            json=payload,
        )
        data = resp.json()
        self._check_response(data, "/message/send")
        logger.info(
            "wecom_text_message_sent",
            touser=touser,
            content_len=len(content),
        )
        return data

    async def send_template_card(
        self, touser: str, card: dict[str, Any]
    ) -> dict[str, Any]:
        """发送模板卡片消息（审批/预警通知）。

        Args:
            touser: 接收者 userid（多人用 ``|`` 分隔）
            card: 模板卡片内容，需符合企微 template_card 格式

        Returns:
            API 响应 dict
        """
        token = await self.get_access_token()
        payload = {
            "touser": touser,
            "msgtype": "template_card",
            "agentid": int(self.agent_id) if self.agent_id else 0,
            "template_card": card,
        }
        resp = await self._client.post(
            "/message/send",
            params={"access_token": token},
            json=payload,
        )
        data = resp.json()
        self._check_response(data, "/message/send(template_card)")
        logger.info(
            "wecom_template_card_sent",
            touser=touser,
            card_type=card.get("card_type", "unknown"),
        )
        return data

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部辅助
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _check_response(data: dict[str, Any], url: str) -> None:
        """检查企微 API 响应，errcode != 0 则抛出 WeComAPIError。"""
        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise WeComAPIError(
                errcode=errcode,
                errmsg=data.get("errmsg", "unknown"),
                url=url,
            )

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        await self._client.aclose()

    async def __aenter__(self) -> "WeComSDK":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
