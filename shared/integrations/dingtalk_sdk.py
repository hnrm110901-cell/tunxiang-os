"""钉钉 Server API 封装

通过 httpx.AsyncClient 调用钉钉开放 API，提供：
 - access_token 自动获取与缓存（7200s 有效期）
 - 部门列表 / 部门成员列表
 - 工作通知发送

环境变量（也可通过构造参数注入）：
  DINGTALK_APP_KEY
  DINGTALK_APP_SECRET
  DINGTALK_AGENT_ID
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

OLD_BASE_URL = "https://oapi.dingtalk.com"
API_BASE_URL = "https://api.dingtalk.com"

# ─── 自定义异常 ──────────────────────────────────────────────────────────────────


class DingTalkAPIError(Exception):
    """钉钉 API 调用失败时抛出。"""

    def __init__(self, errcode: int, errmsg: str, url: str = ""):
        self.errcode = errcode
        self.errmsg = errmsg
        self.url = url
        super().__init__(f"DingTalkAPIError({errcode}): {errmsg} [{url}]")


# ─── SDK 主类 ─────────────────────────────────────────────────────────────────


class DingTalkSDK:
    """钉钉 Server API 客户端。

    Args:
        app_key: 应用 AppKey
        app_secret: 应用 AppSecret
        agent_id: 应用 AgentId（发送工作通知时需要）
    """

    _TOKEN_BUFFER_SEC = 300

    def __init__(self, app_key: str, app_secret: str, agent_id: str = "") -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.agent_id = agent_id

        self._access_token: str = ""
        self._token_expires_at: float = 0.0

        self._old_client = httpx.AsyncClient(
            base_url=OLD_BASE_URL,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        self._api_client = httpx.AsyncClient(
            base_url=API_BASE_URL,
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

        resp = await self._old_client.get(
            "/gettoken",
            params={"appkey": self.app_key, "appsecret": self.app_secret},
        )
        data = resp.json()
        errcode = data.get("errcode", -1)
        if errcode != 0:
            raise DingTalkAPIError(
                errcode=errcode,
                errmsg=data.get("errmsg", "unknown"),
                url="/gettoken",
            )

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        self._token_expires_at = now + expires_in - self._TOKEN_BUFFER_SEC

        logger.info(
            "dingtalk_token_refreshed",
            app_key=self.app_key[:8] + "***",
            expires_in=expires_in,
        )
        return self._access_token

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  通讯录 — 部门
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_department_list(self) -> list[dict[str, Any]]:
        """获取部门列表。

        Returns:
            [{dept_id, name, parentid, ...}, ...]
        """
        token = await self.get_access_token()
        resp = await self._old_client.get(
            "/department/list",
            params={"access_token": token},
        )
        data = resp.json()
        self._check_old_response(data, "/department/list")
        departments: list[dict[str, Any]] = data.get("department", [])
        logger.debug("dingtalk_department_list", count=len(departments))
        return departments

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  通讯录 — 成员
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def get_user_list(self, department_id: int) -> list[dict[str, Any]]:
        """获取部门用户详情列表。

        钉钉新版 API 使用 POST + body。自动分页拉取全部用户。

        Args:
            department_id: 部门 ID

        Returns:
            [{userid, name, mobile, dept_id_list, position, active, ...}, ...]
        """
        token = await self.get_access_token()
        all_users: list[dict[str, Any]] = []
        cursor = 0
        page_size = 100

        while True:
            resp = await self._api_client.post(
                "/v1.0/contact/users",
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "dept_id": department_id,
                    "cursor": cursor,
                    "size": page_size,
                },
            )
            data = resp.json()
            # 新版 API 错误格式不同
            if resp.status_code != 200:
                raise DingTalkAPIError(
                    errcode=data.get("code", resp.status_code),
                    errmsg=data.get("message", "unknown"),
                    url="/v1.0/contact/users",
                )

            result = data.get("result", {})
            user_list: list[dict[str, Any]] = result.get("list", [])
            all_users.extend(user_list)

            has_more = result.get("has_more", False)
            if not has_more or not user_list:
                break
            cursor = result.get("next_cursor", 0)

        logger.debug(
            "dingtalk_user_list",
            department_id=department_id,
            count=len(all_users),
        )
        return all_users

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  工作通知
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_work_notification(self, userid_list: str, msg: dict[str, Any]) -> dict[str, Any]:
        """发送工作通知。

        Args:
            userid_list: 接收者 userid，多人用逗号分隔
            msg: 消息体，需符合钉钉工作通知消息格式

        Returns:
            API 响应 dict（含 request_id / task_id 等）
        """
        token = await self.get_access_token()
        payload = {
            "agent_id": self.agent_id,
            "userid_list": userid_list,
            "msg": msg,
        }
        resp = await self._old_client.post(
            "/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": token},
            json=payload,
        )
        data = resp.json()
        self._check_old_response(data, "/topapi/message/corpconversation/asyncsend_v2")
        logger.info(
            "dingtalk_work_notification_sent",
            userid_list=userid_list[:50],
            msg_type=msg.get("msgtype", "unknown"),
        )
        return data

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部辅助
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _check_old_response(data: dict[str, Any], url: str) -> None:
        """检查旧版 oapi 接口响应，errcode != 0 则抛出 DingTalkAPIError。"""
        errcode = data.get("errcode", -1)
        if errcode != 0:
            raise DingTalkAPIError(
                errcode=errcode,
                errmsg=data.get("errmsg", "unknown"),
                url=url,
            )

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        await self._old_client.aclose()
        await self._api_client.aclose()

    async def __aenter__(self) -> "DingTalkSDK":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
