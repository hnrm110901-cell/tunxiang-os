"""统一通知调度器 -- 根据渠道分发到对应服务

支持渠道:
  - sms: 短信（阿里云/腾讯云）
  - wechat_subscribe: 微信小程序订阅消息
  - in_app: 应用内通知（写入 DB）
  - email: 邮件（占位，未实现）

用法:
    dispatcher = NotificationDispatcher()
    result = await dispatcher.send("sms", "+8613800138000", "verification_code", {"code": "1234"})
    results = await dispatcher.send_multi_channel(
        ["sms", "wechat_subscribe"],
        {"phone": "13800138000", "openid": "oXyz1234abcd"},
        "order_notification",
        {"order_no": "ORD001", "store_name": "长沙万达店", "status": "已完成"},
    )
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from .sms_service import SMSService
from .wechat_subscribe import WechatSubscribeService

logger = structlog.get_logger(__name__)

# ─── 支持的渠道 ───

VALID_CHANNELS = ("sms", "wechat_subscribe", "in_app", "email")


class NotificationDispatcher:
    """统一通知调度器 -- 根据渠道分发到对应底层服务"""

    def __init__(self) -> None:
        self._sms_service = SMSService()
        self._wechat_service = WechatSubscribeService()

    @property
    def sms_service(self) -> SMSService:
        return self._sms_service

    @property
    def wechat_service(self) -> WechatSubscribeService:
        return self._wechat_service

    async def send(
        self,
        channel: str,
        target: str | dict[str, str],
        template_code: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """统一发送入口 -- 根据 channel 分发到对应服务

        Args:
            channel: 渠道名 (sms / wechat_subscribe / in_app / email)
            target: 目标地址。
                    sms: 手机号字符串
                    wechat_subscribe: openid 字符串
                    in_app: user_id 字符串
                    email: 邮箱字符串
                    或者传 dict 包含多个字段
            template_code: 模板代码（如 verification_code, order_notification）
            variables: 模板变量

        Returns:
            {channel, status, detail, dispatched_at}

        Raises:
            ValueError: 不支持的渠道
        """
        if channel not in VALID_CHANNELS:
            raise ValueError(
                f"Unsupported channel '{channel}'. Valid: {', '.join(VALID_CHANNELS)}"
            )

        dispatch_id = f"dispatch_{uuid.uuid4().hex[:10]}"
        dispatched_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "notification_dispatch",
            dispatch_id=dispatch_id,
            channel=channel,
            template_code=template_code,
        )

        detail: dict[str, Any]

        if channel == "sms":
            phone = target if isinstance(target, str) else target.get("phone", "")
            detail = await self._dispatch_sms(phone, template_code, variables)
        elif channel == "wechat_subscribe":
            openid = target if isinstance(target, str) else target.get("openid", "")
            detail = await self._dispatch_wechat(openid, template_code, variables)
        elif channel == "in_app":
            user_id = target if isinstance(target, str) else target.get("user_id", "")
            detail = await self._dispatch_in_app(user_id, template_code, variables)
        elif channel == "email":
            email_addr = target if isinstance(target, str) else target.get("email", "")
            detail = await self._dispatch_email(email_addr, template_code, variables)
        else:
            detail = {"status": "unsupported"}

        return {
            "dispatch_id": dispatch_id,
            "channel": channel,
            "status": detail.get("status", "unknown"),
            "detail": detail,
            "dispatched_at": dispatched_at,
        }

    async def send_multi_channel(
        self,
        channels: list[str],
        target: str | dict[str, str],
        template_code: str,
        variables: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """多渠道同时发送（并发执行）

        Args:
            channels: 渠道列表
            target: 目标地址（dict 时可包含 phone/openid/user_id/email）
            template_code: 模板代码
            variables: 模板变量

        Returns:
            每个渠道的发送结果列表
        """
        tasks = [
            self.send(ch, target, template_code, variables)
            for ch in channels
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "notification_multi_channel_error",
                    channel=channels[i],
                    error=str(result),
                )
                final.append({
                    "channel": channels[i],
                    "status": "error",
                    "detail": {"error": str(result)},
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                final.append(result)

        return final

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部分发方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _dispatch_sms(
        self, phone: str, template_code: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """分发到 SMSService"""
        if not phone:
            return {"status": "skipped", "error": "No phone number provided"}

        # 根据 template_code 映射到具体的 SMS 方法
        if template_code == "verification_code":
            return await self._sms_service.send_verification_code(
                phone, variables.get("code", "")
            )
        elif template_code == "order_notification":
            return await self._sms_service.send_order_notification(
                phone=phone,
                order_no=variables.get("order_no", ""),
                store_name=variables.get("store_name", ""),
                status=variables.get("status", ""),
            )
        elif template_code == "queue_notification":
            return await self._sms_service.send_queue_notification(
                phone=phone,
                queue_no=variables.get("queue_no", ""),
                store_name=variables.get("store_name", ""),
            )
        elif template_code == "marketing":
            return await self._sms_service.send_marketing(
                phone=phone,
                content=variables.get("content", ""),
            )
        else:
            # 通用模板：使用 verification_code 通道兜底
            logger.warning(
                "sms_unknown_template_fallback",
                template_code=template_code,
            )
            return await self._sms_service.send_verification_code(
                phone, variables.get("code", variables.get("content", ""))
            )

    async def _dispatch_wechat(
        self, openid: str, template_code: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """分发到 WechatSubscribeService"""
        if not openid:
            return {"status": "skipped", "error": "No openid provided"}

        if template_code == "order_notification" or template_code == "order_status":
            return await self._wechat_service.send_order_status(
                openid=openid,
                order_no=variables.get("order_no", ""),
                status=variables.get("status", ""),
                time_str=variables.get("time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
            )
        elif template_code == "queue_notification" or template_code == "queue_called":
            return await self._wechat_service.send_queue_called(
                openid=openid,
                queue_no=variables.get("queue_no", ""),
                store_name=variables.get("store_name", ""),
            )
        elif template_code == "promotion":
            return await self._wechat_service.send_promotion(
                openid=openid,
                title=variables.get("title", ""),
                desc=variables.get("desc", ""),
                time_str=variables.get("time", ""),
            )
        elif template_code == "booking_reminder":
            return await self._wechat_service.send_booking_reminder(
                openid=openid,
                date=variables.get("date", ""),
                time_str=variables.get("time", ""),
                store_name=variables.get("store_name", ""),
            )
        else:
            logger.warning(
                "wechat_unknown_template",
                template_code=template_code,
            )
            return {
                "status": "skipped",
                "error": f"Unknown template_code '{template_code}' for wechat_subscribe",
            }

    async def _dispatch_in_app(
        self, user_id: str, template_code: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """分发到应用内通知（写入 DB 或内存）

        当前为 Mock 实现，生产环境需接入 notification_engine 或直接写 notifications 表。
        """
        if not user_id:
            return {"status": "skipped", "error": "No user_id provided"}

        msg_id = f"inapp_{uuid.uuid4().hex[:10]}"
        logger.info(
            "in_app_notification_mock",
            msg_id=msg_id,
            user_id=user_id,
            template_code=template_code,
            variables=variables,
        )
        return {
            "msg_id": msg_id,
            "status": "mock",
            "user_id": user_id,
            "template_code": template_code,
        }

    async def _dispatch_email(
        self, email: str, template_code: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """分发到邮件服务（占位，未实现）"""
        if not email:
            return {"status": "skipped", "error": "No email provided"}

        msg_id = f"email_{uuid.uuid4().hex[:10]}"
        logger.info(
            "email_notification_placeholder",
            msg_id=msg_id,
            email=email[:3] + "***" if len(email) > 3 else "***",
            template_code=template_code,
        )
        return {
            "msg_id": msg_id,
            "status": "not_implemented",
            "email": email[:3] + "***" if len(email) > 3 else "***",
            "template_code": template_code,
        }
