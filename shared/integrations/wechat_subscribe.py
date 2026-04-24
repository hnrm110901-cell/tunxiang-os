"""微信小程序订阅消息服务

环境变量:
  WECHAT_APPID       -- 小程序 AppID
  WECHAT_APP_SECRET  -- 小程序 AppSecret

当 WECHAT_APPID 未配置时自动进入 Mock 模式，仅打印日志不发真实消息。

订阅消息模板需在微信后台申请，模板ID通过环境变量或数据库配置注入。
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# ─── 订阅消息模板ID映射（需在微信后台申请后填入环境变量或数据库配置） ───

DEFAULT_TEMPLATE_IDS = {
    "order_status": os.getenv("WX_TPL_ORDER_STATUS", ""),
    "queue_called": os.getenv("WX_TPL_QUEUE_CALLED", ""),
    "promotion": os.getenv("WX_TPL_PROMOTION", ""),
    "booking_reminder": os.getenv("WX_TPL_BOOKING_REMINDER", ""),
}


class WechatSubscribeService:
    """微信小程序订阅消息服务 -- 支持 Mock 降级"""

    def __init__(self) -> None:
        self._appid = os.getenv("WECHAT_APPID", "")
        self._app_secret = os.getenv("WECHAT_APP_SECRET", "")
        self._is_mock = not (self._appid and self._app_secret)

        # access_token 缓存
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  公开接口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_order_status(
        self,
        openid: str,
        order_no: str,
        status: str,
        time_str: str,
    ) -> dict[str, Any]:
        """订单状态变更通知

        Args:
            openid: 用户 openid
            order_no: 订单编号
            status: 订单状态（如"已完成"、"配送中"）
            time_str: 状态变更时间

        Returns:
            {msg_id, status, openid, template_key}
        """
        data = {
            "character_string1": {"value": order_no},
            "phrase2": {"value": status},
            "time3": {"value": time_str},
        }
        return await self._send_subscribe_msg(
            openid=openid,
            template_key="order_status",
            data=data,
        )

    async def send_queue_called(
        self,
        openid: str,
        queue_no: str,
        store_name: str,
    ) -> dict[str, Any]:
        """叫号通知

        Args:
            openid: 用户 openid
            queue_no: 排队号
            store_name: 门店名称

        Returns:
            {msg_id, status, openid, template_key}
        """
        data = {
            "character_string1": {"value": queue_no},
            "thing2": {"value": store_name},
            "time3": {"value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        }
        return await self._send_subscribe_msg(
            openid=openid,
            template_key="queue_called",
            data=data,
        )

    async def send_promotion(
        self,
        openid: str,
        title: str,
        desc: str,
        time_str: str,
    ) -> dict[str, Any]:
        """活动通知

        Args:
            openid: 用户 openid
            title: 活动标题
            desc: 活动描述
            time_str: 活动时间

        Returns:
            {msg_id, status, openid, template_key}
        """
        data = {
            "thing1": {"value": title[:20]},  # 微信限制20字
            "thing2": {"value": desc[:20]},
            "time3": {"value": time_str},
        }
        return await self._send_subscribe_msg(
            openid=openid,
            template_key="promotion",
            data=data,
        )

    async def send_booking_reminder(
        self,
        openid: str,
        date: str,
        time_str: str,
        store_name: str,
    ) -> dict[str, Any]:
        """预约提醒

        Args:
            openid: 用户 openid
            date: 预约日期
            time_str: 预约时间
            store_name: 门店名称

        Returns:
            {msg_id, status, openid, template_key}
        """
        data = {
            "date1": {"value": date},
            "time2": {"value": time_str},
            "thing3": {"value": store_name},
        }
        return await self._send_subscribe_msg(
            openid=openid,
            template_key="booking_reminder",
            data=data,
        )

    async def get_access_token(self) -> str:
        """获取 access_token（缓存 2 小时，提前 5 分钟刷新）

        Returns:
            access_token 字符串

        Raises:
            ValueError: Mock 模式或获取失败
        """
        if self._is_mock:
            raise ValueError("WechatSubscribeService is in mock mode, no access_token available")

        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        import aiohttp

        url = (
            f"https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={self._appid}"
            f"&secret={self._app_secret}"
        )

        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            result = await resp.json()
            if "access_token" not in result:
                raise ValueError(f"WeChat token error: {result.get('errcode')} - {result.get('errmsg')}")
            self._access_token = result["access_token"]
            # 提前 5 分钟过期
            self._token_expires_at = now + result.get("expires_in", 7200) - 300
            return self._access_token

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部：统一发送
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _send_subscribe_msg(
        self,
        openid: str,
        template_key: str,
        data: dict[str, Any],
        page: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送订阅消息（统一入口）"""
        msg_id = f"wxsub_{uuid.uuid4().hex[:12]}"
        masked_openid = self._mask_openid(openid)

        if self._is_mock:
            logger.info(
                "wechat_subscribe_mock",
                msg_id=msg_id,
                openid=masked_openid,
                template_key=template_key,
                data=data,
            )
            return {
                "msg_id": msg_id,
                "status": "mock",
                "openid": masked_openid,
                "template_key": template_key,
            }

        template_id = DEFAULT_TEMPLATE_IDS.get(template_key, "")
        if not template_id:
            logger.warning(
                "wechat_subscribe_no_template",
                template_key=template_key,
                msg_id=msg_id,
            )
            return {
                "msg_id": msg_id,
                "status": "skipped",
                "openid": masked_openid,
                "template_key": template_key,
                "error": f"Template ID not configured for '{template_key}'",
            }

        try:
            access_token = await self.get_access_token()
            result = await self._call_subscribe_api(access_token, openid, template_id, data, page)
            logger.info(
                "wechat_subscribe_sent",
                msg_id=msg_id,
                openid=masked_openid,
                template_key=template_key,
            )
            return {
                "msg_id": msg_id,
                "status": "sent",
                "openid": masked_openid,
                "template_key": template_key,
                "wx_msgid": result.get("msgid"),
            }
        except (ConnectionError, TimeoutError, ValueError, OSError) as exc:
            logger.error(
                "wechat_subscribe_failed",
                msg_id=msg_id,
                openid=masked_openid,
                template_key=template_key,
                error=str(exc),
            )
            return {
                "msg_id": msg_id,
                "status": "failed",
                "openid": masked_openid,
                "template_key": template_key,
                "error": str(exc),
            }

    async def _call_subscribe_api(
        self,
        access_token: str,
        openid: str,
        template_id: str,
        data: dict[str, Any],
        page: Optional[str] = None,
    ) -> dict[str, Any]:
        """调用微信小程序订阅消息发送接口

        文档: https://developers.weixin.qq.com/miniprogram/dev/OpenApiDoc/mp-message/subscribe-message/sendMessage.html
        """
        import aiohttp

        api_url = f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}"

        payload: dict[str, Any] = {
            "touser": openid,
            "template_id": template_id,
            "data": data,
        }
        if page:
            payload["page"] = page

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                api_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            result = await resp.json()
            errcode = result.get("errcode", 0)
            if errcode != 0:
                raise ValueError(f"WeChat subscribe msg error: {errcode} - {result.get('errmsg')}")
            return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  工具方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _mask_openid(openid: str) -> str:
        """openid 脱敏: oXyz1234****abcd"""
        if len(openid) >= 12:
            return openid[:8] + "****" + openid[-4:]
        return openid[:4] + "***" if len(openid) >= 4 else "***"
