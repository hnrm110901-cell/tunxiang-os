"""微信营销适配器 — 公众号模板消息 + 企业微信客户群发

覆盖两大微信营销渠道：
  1. WeChatOAService   — 微信公众号（服务号）模板消息
  2. WeComService      — 企业微信外部联系人消息（客户群发/一对一话术）

环境变量：
  WX_OA_APPID          — 公众号 AppID
  WX_OA_APP_SECRET     — 公众号 AppSecret
  WECOM_CORP_ID        — 企业微信 CorpID
  WECOM_CORP_SECRET    — 企业微信 CorpSecret（应用密钥）
  WECOM_AGENT_ID       — 企业微信 AgentID
  WECOM_EXTERNAL_SECRET — 企微外部联系人 API 密钥

当环境变量未配置时，自动进入 Mock 模式。
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 公众号（OA）模板消息服务
# ─────────────────────────────────────────────────────────────────────────────

class WeChatOAService:
    """微信公众号（服务号）模板消息服务

    支持向已关注公众号的用户发送模板消息。
    合规要求：用户需主动关注公众号，消息需与服务相关。
    """

    _OA_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
    _OA_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/template/send"

    def __init__(self) -> None:
        self._appid = os.getenv("WX_OA_APPID", "")
        self._app_secret = os.getenv("WX_OA_APP_SECRET", "")
        self._is_mock = not (self._appid and self._app_secret)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if self._is_mock:
            logger.info("wechat_oa_mock_mode", reason="WX_OA_APPID or WX_OA_APP_SECRET not set")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ─── 公开接口 ────────────────────────────────────────────────────────────

    async def send_template_msg(
        self,
        openid: str,
        template_id: str,
        data: dict[str, dict[str, str]],
        url: Optional[str] = None,
        miniprogram: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """发送公众号模板消息

        Args:
            openid: 用户 openid（需已关注公众号）
            template_id: 模板 ID（在微信后台申请）
            data: 模板数据，格式：{"keyword1": {"value": "xxx", "color": "#173177"}}
            url: 消息跳转链接（可选）
            miniprogram: 跳转小程序配置 {"appid": "...", "pagepath": "..."}（可选）

        Returns:
            {msg_id, status, openid_masked, template_id}
        """
        msg_id = f"oa_{uuid.uuid4().hex[:12]}"
        masked = _mask_openid(openid)

        if self._is_mock:
            logger.info(
                "wechat_oa_template_mock",
                msg_id=msg_id,
                openid=masked,
                template_id=template_id,
                data_keys=list(data.keys()),
            )
            return {"msg_id": msg_id, "status": "mock", "openid": masked, "template_id": template_id}

        try:
            token = await self._get_access_token()
            payload: dict[str, Any] = {"touser": openid, "template_id": template_id, "data": data}
            if url:
                payload["url"] = url
            if miniprogram:
                payload["miniprogram"] = miniprogram

            import aiohttp
            async with aiohttp.ClientSession() as session, session.post(
                f"{self._OA_SEND_URL}?access_token={token}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    raise ValueError(f"OA template error {errcode}: {result.get('errmsg')}")

            logger.info("wechat_oa_template_sent", msg_id=msg_id, openid=masked, template_id=template_id)
            return {
                "msg_id": msg_id,
                "status": "sent",
                "openid": masked,
                "template_id": template_id,
                "wx_msgid": result.get("msgid"),
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("wechat_oa_template_failed", msg_id=msg_id, openid=masked, error=str(exc))
            return {"msg_id": msg_id, "status": "failed", "openid": masked, "error": str(exc)}

    async def send_marketing_notification(
        self,
        openid: str,
        title: str,
        content: str,
        remark: str = "",
        url: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送通用营销通知（使用 thing+time+remark 三段式模板）

        适用场景：活动通知、优惠提醒、新品上市等。
        """
        template_id = os.getenv("WX_OA_TPL_MARKETING", "")
        if not template_id and not self._is_mock:
            logger.warning("wechat_oa_no_marketing_template")
            return {"msg_id": f"oa_{uuid.uuid4().hex[:8]}", "status": "skipped", "error": "WX_OA_TPL_MARKETING not configured"}

        data = {
            "thing1": {"value": title[:20]},
            "thing2": {"value": content[:20]},
            "time3": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        }
        if remark:
            data["remark"] = {"value": remark[:20]}
        return await self.send_template_msg(openid, template_id or "mock_tpl", data, url=url)

    async def send_order_notification(
        self,
        openid: str,
        order_no: str,
        store_name: str,
        status: str,
        amount_yuan: str,
    ) -> dict[str, Any]:
        """发送订单状态通知（公众号模板消息）"""
        template_id = os.getenv("WX_OA_TPL_ORDER", "")
        data = {
            "character_string1": {"value": order_no},
            "thing2": {"value": store_name[:20]},
            "phrase3": {"value": status},
            "amount4": {"value": f"¥{amount_yuan}"},
            "time5": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        }
        return await self.send_template_msg(openid, template_id or "mock_order_tpl", data)

    # ─── 内部：Token 管理 ────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """获取公众号 access_token（缓存2小时，提前5分钟刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import aiohttp
        async with aiohttp.ClientSession() as session, session.get(
            self._OA_TOKEN_URL,
            params={"grant_type": "client_credential", "appid": self._appid, "secret": self._app_secret},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            result = await resp.json()
            if "access_token" not in result:
                raise ValueError(f"OA token error: {result.get('errcode')} - {result.get('errmsg')}")
            self._access_token = result["access_token"]
            self._token_expires_at = now + result.get("expires_in", 7200) - 300
            return self._access_token


# ─────────────────────────────────────────────────────────────────────────────
# 企业微信（WeCom）外部联系人消息服务
# ─────────────────────────────────────────────────────────────────────────────

class WeComService:
    """企业微信外部联系人消息服务

    支持：
    - 给已添加企微的客户发送文本/图片/小程序卡片
    - 创建客户群发任务（staff_send，需员工确认后发送）
    - 企微 agentId 应用内消息（内部员工通知）
    """

    _WECOM_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    _WECOM_EXTERNAL_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/add_msg_template"
    _WECOM_AGENT_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

    def __init__(self) -> None:
        self._corp_id = os.getenv("WECOM_CORP_ID", "")
        self._corp_secret = os.getenv("WECOM_CORP_SECRET", "")
        self._agent_id = os.getenv("WECOM_AGENT_ID", "")
        self._external_secret = os.getenv("WECOM_EXTERNAL_SECRET", "")
        self._is_mock = not (self._corp_id and self._corp_secret)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if self._is_mock:
            logger.info("wecom_mock_mode", reason="WECOM_CORP_ID or WECOM_CORP_SECRET not set")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ─── 外部联系人消息 ──────────────────────────────────────────────────────

    async def send_text_to_customer(
        self,
        chat_type: str,
        chat_id_list: list[str],
        text_content: str,
        sender_list: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """向企微外部联系人发送文本消息（需员工确认后群发）

        Args:
            chat_type: "single" | "group"（单聊/群聊）
            chat_id_list: external_userid 列表（单聊）或 chat_id 列表（群聊）
            text_content: 文本内容（<= 4000 字）
            sender_list: 指定发送员工 user_id 列表（可选，为空时随机分配）

        Returns:
            {task_id, status, fail_list}
        """
        task_id = f"wecom_{uuid.uuid4().hex[:12]}"

        if self._is_mock:
            logger.info(
                "wecom_external_text_mock",
                task_id=task_id,
                chat_type=chat_type,
                recipient_count=len(chat_id_list),
                text_preview=text_content[:30],
            )
            return {"task_id": task_id, "status": "mock", "fail_list": []}

        try:
            token = await self._get_access_token()
            payload: dict[str, Any] = {
                "chat_type": chat_type,
                "text": {"content": text_content},
            }
            if chat_type == "single":
                payload["external_userid"] = chat_id_list
            else:
                payload["chat_id_list"] = chat_id_list
            if sender_list:
                payload["sender"] = sender_list

            import aiohttp
            async with aiohttp.ClientSession() as session, session.post(
                f"{self._WECOM_EXTERNAL_SEND_URL}?access_token={token}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    raise ValueError(f"WeCom external send error {errcode}: {result.get('errmsg')}")

            logger.info("wecom_external_text_sent", task_id=task_id, recipient_count=len(chat_id_list))
            return {
                "task_id": task_id,
                "status": "submitted",
                "msgid": result.get("msgid"),
                "fail_list": result.get("fail_list", []),
            }
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("wecom_external_text_failed", task_id=task_id, error=str(exc))
            return {"task_id": task_id, "status": "failed", "error": str(exc), "fail_list": chat_id_list}

    async def send_miniprogram_to_customer(
        self,
        external_userid_list: list[str],
        miniprogram_appid: str,
        page: str,
        title: str,
        pic_media_id: str = "",
    ) -> dict[str, Any]:
        """向外部联系人发送小程序卡片消息"""
        task_id = f"wecom_mp_{uuid.uuid4().hex[:10]}"

        if self._is_mock:
            logger.info(
                "wecom_miniprogram_mock",
                task_id=task_id,
                appid=miniprogram_appid,
                page=page,
                title=title,
                recipient_count=len(external_userid_list),
            )
            return {"task_id": task_id, "status": "mock", "fail_list": []}

        try:
            token = await self._get_access_token()
            payload = {
                "chat_type": "single",
                "external_userid": external_userid_list,
                "miniprogram": {
                    "appid": miniprogram_appid,
                    "page": page,
                    "title": title,
                },
            }
            if pic_media_id:
                payload["miniprogram"]["pic_media_id"] = pic_media_id  # type: ignore[index]

            import aiohttp
            async with aiohttp.ClientSession() as session, session.post(
                f"{self._WECOM_EXTERNAL_SEND_URL}?access_token={token}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    raise ValueError(f"WeCom miniprogram send error {errcode}: {result.get('errmsg')}")

            logger.info("wecom_miniprogram_sent", task_id=task_id, recipient_count=len(external_userid_list))
            return {"task_id": task_id, "status": "submitted", "fail_list": result.get("fail_list", [])}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("wecom_miniprogram_failed", task_id=task_id, error=str(exc))
            return {"task_id": task_id, "status": "failed", "error": str(exc)}

    async def send_agent_message(
        self,
        user_ids: list[str],
        content: str,
        msg_type: str = "text",
    ) -> dict[str, Any]:
        """向企业内部员工发送应用消息（用于经营告警、营销报告推送等）"""
        msg_id = f"wecom_agent_{uuid.uuid4().hex[:10]}"

        if self._is_mock:
            logger.info("wecom_agent_msg_mock", msg_id=msg_id, user_count=len(user_ids), content_preview=content[:30])
            return {"msg_id": msg_id, "status": "mock"}

        try:
            token = await self._get_access_token()
            payload = {
                "touser": "|".join(user_ids),
                "msgtype": msg_type,
                "agentid": int(self._agent_id),
                msg_type: {"content": content},
            }

            import aiohttp
            async with aiohttp.ClientSession() as session, session.post(
                f"{self._WECOM_AGENT_SEND_URL}?access_token={token}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    raise ValueError(f"WeCom agent msg error {errcode}: {result.get('errmsg')}")

            logger.info("wecom_agent_msg_sent", msg_id=msg_id, user_count=len(user_ids))
            return {"msg_id": msg_id, "status": "sent", "invaliduser": result.get("invaliduser", "")}
        except (ValueError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("wecom_agent_msg_failed", msg_id=msg_id, error=str(exc))
            return {"msg_id": msg_id, "status": "failed", "error": str(exc)}

    # ─── 内部：Token 管理 ────────────────────────────────────────────────────

    async def _get_access_token(self) -> str:
        """获取企业微信 access_token（缓存2小时，提前5分钟刷新）"""
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import aiohttp
        async with aiohttp.ClientSession() as session, session.get(
            self._WECOM_TOKEN_URL,
            params={"corpid": self._corp_id, "corpsecret": self._corp_secret},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            result = await resp.json()
            if "access_token" not in result:
                raise ValueError(f"WeCom token error: {result.get('errcode')} - {result.get('errmsg')}")
            self._access_token = result["access_token"]
            self._token_expires_at = now + result.get("expires_in", 7200) - 300
            return self._access_token


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _mask_openid(openid: str) -> str:
    """openid 脱敏: oXyz1234****abcd"""
    if len(openid) >= 12:
        return openid[:8] + "****" + openid[-4:]
    return openid[:4] + "***" if len(openid) >= 4 else "***"
