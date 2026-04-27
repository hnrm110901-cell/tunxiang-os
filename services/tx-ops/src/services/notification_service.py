"""统一通知服务 — 多渠道消息发送（短信/微信/企业微信）

支持渠道:
  - sms: 阿里云短信服务
  - wechat: 微信公众号模板消息
  - wecom: 企业微信群机器人 Webhook
  - in_app: 应用内通知（写入 notifications 表）

所有发送均为异步，不阻塞主流程。发送记录持久化到 notifications 表。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── 短信模板 ───

SMS_TEMPLATES = {
    "reservation_confirmed": "SMS_RESERVATION_CONFIRM",
    "queue_called": "SMS_QUEUE_CALLED",
    "order_completed": "SMS_ORDER_COMPLETED",
    "arrival_confirmed": "SMS_ARRIVAL_CONFIRMED",
}

# ─── 微信模板 ───

WECHAT_TEMPLATES = {
    "reservation_confirmed": "WECHAT_TPL_RESERVATION",
    "queue_called": "WECHAT_TPL_QUEUE_CALLED",
    "order_completed": "WECHAT_TPL_ORDER_COMPLETED",
}


class NotificationService:
    """统一通知服务 — 多渠道消息发送

    使用方式:
        svc = NotificationService(db, tenant_id)
        await svc.send_sms("13800138000", "reservation_confirmed", {...})
        await svc.send_wechat("openid_xxx", "reservation_confirmed", {...})
        await svc.send_wecom(webhook_url, "折扣审批通知: ...")
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

        # 阿里云SMS配置
        self._sms_access_key = os.getenv("ALIYUN_SMS_ACCESS_KEY", "")
        self._sms_secret = os.getenv("ALIYUN_SMS_SECRET", "")
        self._sms_sign_name = os.getenv("ALIYUN_SMS_SIGN_NAME", "屯象OS")

        # 微信公众号配置
        self._wechat_app_id = os.getenv("WECHAT_APP_ID", "")
        self._wechat_app_secret = os.getenv("WECHAT_APP_SECRET", "")
        self._wechat_access_token: Optional[str] = None
        self._wechat_token_expires_at: float = 0.0

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  短信发送（阿里云SMS）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_sms(
        self,
        phone: str,
        template_id: str,
        params: dict[str, str],
        *,
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送短信（阿里云SMS API）

        Args:
            phone: 手机号
            template_id: 模板ID键名（如 reservation_confirmed）
            params: 模板参数
            store_id: 门店ID（用于记录）

        Returns:
            {notification_id, channel, status, phone}
        """
        aliyun_template = SMS_TEMPLATES.get(template_id, template_id)
        notification_id = f"SMS-{uuid.uuid4().hex[:10].upper()}"

        status = "sent"
        error_msg = None

        if self._sms_access_key and self._sms_secret:
            try:
                await self._call_aliyun_sms(phone, aliyun_template, params)
                logger.info(
                    "sms_sent",
                    notification_id=notification_id,
                    phone=self._mask_phone(phone),
                    template=aliyun_template,
                )
            except (ConnectionError, TimeoutError, ValueError) as exc:
                status = "failed"
                error_msg = str(exc)
                logger.error(
                    "sms_send_failed",
                    notification_id=notification_id,
                    phone=self._mask_phone(phone),
                    error=error_msg,
                )
        else:
            status = "mock"
            logger.info(
                "sms_sent_mock",
                notification_id=notification_id,
                phone=self._mask_phone(phone),
                template=aliyun_template,
                params=params,
            )

        # 持久化通知记录（手机号脱敏入库）
        await self._save_notification(
            notification_id=notification_id,
            channel="sms",
            recipient=self._mask_phone(phone),
            template_id=template_id,
            params=params,
            status=status,
            error_msg=error_msg,
            store_id=store_id,
        )

        return {
            "notification_id": notification_id,
            "channel": "sms",
            "status": status,
            "phone": self._mask_phone(phone),
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  微信模板消息
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_wechat(
        self,
        openid: str,
        template_id: str,
        data: dict[str, Any],
        *,
        url: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送微信公众号模板消息

        Args:
            openid: 用户openid
            template_id: 模板ID键名
            data: 模板数据 {key: {value, color}}
            url: 点击跳转链接
            store_id: 门店ID

        Returns:
            {notification_id, channel, status, openid}
        """
        wechat_template = WECHAT_TEMPLATES.get(template_id, template_id)
        notification_id = f"WX-{uuid.uuid4().hex[:10].upper()}"

        status = "sent"
        error_msg = None

        if self._wechat_app_id and self._wechat_app_secret:
            try:
                access_token = await self._get_wechat_access_token()
                await self._call_wechat_template_msg(access_token, openid, wechat_template, data, url)
                logger.info(
                    "wechat_msg_sent",
                    notification_id=notification_id,
                    openid=openid[:8] + "***",
                    template=wechat_template,
                )
            except (ConnectionError, TimeoutError, ValueError) as exc:
                status = "failed"
                error_msg = str(exc)
                logger.error(
                    "wechat_msg_failed",
                    notification_id=notification_id,
                    openid=openid[:8] + "***",
                    error=error_msg,
                )
        else:
            status = "mock"
            logger.info(
                "wechat_msg_mock",
                notification_id=notification_id,
                openid=openid[:8] + "***" if openid else "N/A",
                template=wechat_template,
                data=data,
            )

        await self._save_notification(
            notification_id=notification_id,
            channel="wechat",
            recipient=self._mask_openid(openid),
            template_id=template_id,
            params=data,
            status=status,
            error_msg=error_msg,
            store_id=store_id,
        )

        return {
            "notification_id": notification_id,
            "channel": "wechat",
            "status": status,
            "openid": openid[:8] + "***" if openid else "N/A",
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  企业微信群机器人
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_wecom(
        self,
        webhook_url: str,
        content: str,
        *,
        msg_type: str = "text",
        mentioned_list: Optional[list[str]] = None,
        store_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """发送企业微信群机器人消息

        用于内部告警通知（折扣审批、异常订单等）。

        Args:
            webhook_url: 企业微信群机器人 Webhook URL
            content: 消息内容
            msg_type: 消息类型 text/markdown
            mentioned_list: @人列表（userid 或 @all）
            store_id: 门店ID

        Returns:
            {notification_id, channel, status}
        """
        notification_id = f"WECOM-{uuid.uuid4().hex[:10].upper()}"

        status = "sent"
        error_msg = None

        if webhook_url and webhook_url.startswith("https://"):
            try:
                await self._call_wecom_webhook(webhook_url, content, msg_type, mentioned_list)
                logger.info(
                    "wecom_msg_sent",
                    notification_id=notification_id,
                    msg_type=msg_type,
                    content_length=len(content),
                )
            except (ConnectionError, TimeoutError, ValueError) as exc:
                status = "failed"
                error_msg = str(exc)
                logger.error(
                    "wecom_msg_failed",
                    notification_id=notification_id,
                    error=error_msg,
                )
        else:
            status = "mock"
            logger.info(
                "wecom_msg_mock",
                notification_id=notification_id,
                content=content[:200],
                msg_type=msg_type,
            )

        await self._save_notification(
            notification_id=notification_id,
            channel="wecom",
            recipient=webhook_url[:30] + "..." if webhook_url else "N/A",
            template_id=msg_type,
            params={"content": content[:500]},
            status=status,
            error_msg=error_msg,
            store_id=store_id,
        )

        return {
            "notification_id": notification_id,
            "channel": "wecom",
            "status": status,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  通知历史查询
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def list_notifications(
        self,
        *,
        channel: Optional[str] = None,
        store_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询通知发送历史

        Args:
            channel: 按渠道筛选 sms/wechat/wecom
            store_id: 按门店筛选
            page: 页码
            size: 每页条数

        Returns:
            {items: [...], total, page, size}
        """
        from sqlalchemy import text

        tenant_uuid = uuid.UUID(self.tenant_id)

        conditions = [text("tenant_id = :tid")]
        bind_params: dict[str, Any] = {"tid": str(tenant_uuid)}

        if channel:
            conditions.append(text("extra_data->>'channel' = :ch"))
            bind_params["ch"] = channel
        if store_id:
            conditions.append(text("store_id = :sid"))
            bind_params["sid"] = store_id

        where_clause = " AND ".join(str(c) for c in conditions)

        # Count
        count_sql = text(f"SELECT COUNT(*) FROM notifications WHERE {where_clause}")
        count_result = await self.db.execute(count_sql, bind_params)
        total = count_result.scalar() or 0

        # Query
        offset = (page - 1) * size
        query_sql = text(
            f"SELECT id, title, message, type, priority, store_id, "
            f"extra_data, source, created_at "
            f"FROM notifications WHERE {where_clause} "
            f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        )
        bind_params["lim"] = size
        bind_params["off"] = offset
        result = await self.db.execute(query_sql, bind_params)
        rows = result.fetchall()

        items = []
        for row in rows:
            items.append(
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "message": row[2],
                    "type": row[3],
                    "priority": row[4],
                    "store_id": str(row[5]) if row[5] else None,
                    "extra_data": row[6],
                    "source": row[7],
                    "created_at": row[8].isoformat() if row[8] else None,
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部方法 — 阿里云SMS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _call_aliyun_sms(self, phone: str, template_code: str, params: dict[str, str]) -> dict[str, Any]:
        """调用阿里云SMS API发送短信

        生产环境通过 alibabacloud-sdk 发送。当前实现为 HTTP API 直调。
        """
        import aiohttp

        # 阿里云 SMS API endpoint
        api_url = "https://dysmsapi.aliyuncs.com/"

        # 签名参数
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex[:16]

        query_params = {
            "AccessKeyId": self._sms_access_key,
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": phone,
            "RegionId": "cn-hangzhou",
            "SignName": self._sms_sign_name,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": nonce,
            "SignatureVersion": "1.0",
            "TemplateCode": template_code,
            "TemplateParam": json.dumps(params, ensure_ascii=False),
            "Timestamp": timestamp,
            "Version": "2017-05-25",
        }

        # 计算签名
        signature = self._calc_aliyun_signature(query_params)
        query_params["Signature"] = signature

        async with (
            aiohttp.ClientSession() as session,
            session.get(api_url, params=query_params, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            result = await resp.json()
            if result.get("Code") != "OK":
                raise ValueError(f"Aliyun SMS error: {result.get('Code')} - {result.get('Message')}")
            return result

    def _calc_aliyun_signature(self, params: dict[str, str]) -> str:
        """计算阿里云API签名（HMAC-SHA1）"""
        import base64
        from urllib.parse import quote

        sorted_params = sorted(params.items())
        canonicalized = "&".join(f"{quote(k, safe='')}" + "=" + f"{quote(v, safe='')}" for k, v in sorted_params)
        string_to_sign = f"GET&{quote('/', safe='')}&{quote(canonicalized, safe='')}"

        signing_key = (self._sms_secret + "&").encode("utf-8")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(signature).decode("utf-8")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部方法 — 微信公众号模板消息
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _get_wechat_access_token(self) -> str:
        """获取微信公众号 access_token（带缓存）"""
        now = time.time()
        if self._wechat_access_token and now < self._wechat_token_expires_at:
            return self._wechat_access_token

        import aiohttp

        url = (
            f"https://api.weixin.qq.com/cgi-bin/token"
            f"?grant_type=client_credential"
            f"&appid={self._wechat_app_id}"
            f"&secret={self._wechat_app_secret}"
        )

        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
        ):
            result = await resp.json()
            if "access_token" not in result:
                raise ValueError(f"WeChat token error: {result.get('errcode')} - {result.get('errmsg')}")
            self._wechat_access_token = result["access_token"]
            # 提前5分钟过期
            self._wechat_token_expires_at = now + result.get("expires_in", 7200) - 300
            return self._wechat_access_token

    async def _call_wechat_template_msg(
        self,
        access_token: str,
        openid: str,
        template_id: str,
        data: dict[str, Any],
        url: Optional[str] = None,
    ) -> dict[str, Any]:
        """调用微信模板消息API"""
        import aiohttp

        api_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"

        payload = {
            "touser": openid,
            "template_id": template_id,
            "data": data,
        }
        if url:
            payload["url"] = url

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                api_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            result = await resp.json()
            if result.get("errcode", 0) != 0:
                raise ValueError(f"WeChat template msg error: {result.get('errcode')} - {result.get('errmsg')}")
            return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部方法 — 企业微信群机器人
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _call_wecom_webhook(
        self,
        webhook_url: str,
        content: str,
        msg_type: str = "text",
        mentioned_list: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """调用企业微信群机器人 Webhook"""
        import aiohttp

        payload: dict[str, Any]
        if msg_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": content,
                },
            }
            if mentioned_list:
                payload["text"]["mentioned_list"] = mentioned_list

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            result = await resp.json()
            if result.get("errcode", 0) != 0:
                raise ValueError(f"WeCom webhook error: {result.get('errcode')} - {result.get('errmsg')}")
            return result

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部方法 — 持久化
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _save_notification(
        self,
        *,
        notification_id: str,
        channel: str,
        recipient: str,
        template_id: str,
        params: dict[str, Any],
        status: str,
        error_msg: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> None:
        """写入 notifications 表记录发送历史

        持久化失败仅记录日志，不阻塞主流程。
        """
        from sqlalchemy import text

        try:
            tenant_uuid = uuid.UUID(self.tenant_id)
            store_uuid = uuid.UUID(store_id) if store_id else None
            type_map = {"sent": "success", "mock": "info", "failed": "error"}

            await self.db.execute(
                text(
                    "INSERT INTO notifications "
                    "(id, tenant_id, title, message, type, priority, store_id, "
                    "extra_data, source, created_at, updated_at, is_deleted) "
                    "VALUES (:id, :tid, :title, :msg, :typ, 'normal', :sid, "
                    ":extra, :src, NOW(), NOW(), false)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tid": str(tenant_uuid),
                    "title": f"[{channel.upper()}] {template_id}",
                    "msg": f"To: {recipient} | Status: {status}" + (f" | Error: {error_msg}" if error_msg else ""),
                    "typ": type_map.get(status, "info"),
                    "sid": str(store_uuid) if store_uuid else None,
                    "extra": json.dumps(
                        {
                            "channel": channel,
                            "notification_id": notification_id,
                            "recipient": recipient,  # already masked by caller
                            "template_id": template_id,
                            "params": params,
                            "status": status,
                            "error": error_msg,
                        },
                        ensure_ascii=False,
                    ),
                    "src": f"notification_service/{channel}",
                },
            )
        except (OSError, ValueError, RuntimeError) as exc:
            logger.error(
                "notification_persist_failed",
                notification_id=notification_id,
                channel=channel,
                error=str(exc),
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  工具方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _mask_phone(phone: str) -> str:
        """手机号脱敏: 138****8000"""
        if len(phone) >= 7:
            return phone[:3] + "****" + phone[-4:]
        return "***"

    @staticmethod
    def _mask_openid(openid: str) -> str:
        """微信openid脱敏: oXyz1234****abcd"""
        if len(openid) >= 12:
            return openid[:8] + "****" + openid[-4:]
        return openid[:4] + "***" if len(openid) >= 4 else "***"
