"""短信服务 -- 支持阿里云/腾讯云双通道

环境变量:
  SMS_PROVIDER          -- aliyun / tencent (默认 aliyun)
  SMS_ACCESS_KEY_ID     -- 密钥ID
  SMS_ACCESS_KEY_SECRET -- 密钥
  SMS_SIGN_NAME         -- 签名（如"屯象科技"）
  SMS_REGION            -- 区域（默认 cn-hangzhou）

当 SMS_ACCESS_KEY_ID 未配置时自动进入 Mock 模式，仅打印日志不发真实短信。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import structlog

logger = structlog.get_logger(__name__)

# ─── 短信模板映射 ───

ALIYUN_TEMPLATES = {
    "verification_code": "SMS_VERIFY_CODE",
    "order_notification": "SMS_ORDER_STATUS",
    "queue_notification": "SMS_QUEUE_CALLED",
    "marketing": "SMS_MARKETING",
}

TENCENT_TEMPLATES = {
    "verification_code": "1001",
    "order_notification": "1002",
    "queue_notification": "1003",
    "marketing": "1004",
}


class SMSService:
    """短信发送服务 -- 阿里云/腾讯云双通道，自动降级 Mock"""

    def __init__(self) -> None:
        self._provider = os.getenv("SMS_PROVIDER", "aliyun")
        self._access_key_id = os.getenv("SMS_ACCESS_KEY_ID", "")
        self._access_key_secret = os.getenv("SMS_ACCESS_KEY_SECRET", "")
        self._sign_name = os.getenv("SMS_SIGN_NAME", "屯象科技")
        self._region = os.getenv("SMS_REGION", "cn-hangzhou")
        self._is_mock = not (self._access_key_id and self._access_key_secret)

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  公开接口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def send_verification_code(self, phone: str, code: str) -> dict[str, Any]:
        """发送验证码短信

        Args:
            phone: 手机号
            code: 验证码

        Returns:
            {biz_id, status, phone, provider}
        """
        return await self._send(
            phone=phone,
            template_key="verification_code",
            params={"code": code},
        )

    async def send_order_notification(
        self,
        phone: str,
        order_no: str,
        store_name: str,
        status: str,
    ) -> dict[str, Any]:
        """发送订单状态通知

        Args:
            phone: 手机号
            order_no: 订单编号
            store_name: 门店名称
            status: 订单状态描述

        Returns:
            {biz_id, status, phone, provider}
        """
        return await self._send(
            phone=phone,
            template_key="order_notification",
            params={
                "order_no": order_no,
                "store_name": store_name,
                "status": status,
            },
        )

    async def send_queue_notification(
        self,
        phone: str,
        queue_no: str,
        store_name: str,
    ) -> dict[str, Any]:
        """发送叫号通知

        Args:
            phone: 手机号
            queue_no: 排队号
            store_name: 门店名称

        Returns:
            {biz_id, status, phone, provider}
        """
        return await self._send(
            phone=phone,
            template_key="queue_notification",
            params={"queue_no": queue_no, "store_name": store_name},
        )

    async def send_marketing(self, phone: str, content: str) -> dict[str, Any]:
        """发送营销短信（需用户授权）

        Args:
            phone: 手机号
            content: 营销内容

        Returns:
            {biz_id, status, phone, provider}
        """
        return await self._send(
            phone=phone,
            template_key="marketing",
            params={"content": content},
        )

    async def query_send_status(self, biz_id: str) -> dict[str, Any]:
        """查询发送状态

        Args:
            biz_id: 发送业务ID

        Returns:
            {biz_id, status, send_time}
        """
        if self._is_mock:
            logger.info("sms_query_status_mock", biz_id=biz_id)
            return {
                "biz_id": biz_id,
                "status": "delivered",
                "send_time": datetime.now(timezone.utc).isoformat(),
            }

        # 真实查询 -- 阿里云/腾讯云各自有查询接口
        if self._provider == "aliyun":
            return await self._query_aliyun_status(biz_id)
        return await self._query_tencent_status(biz_id)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部：统一发送入口
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _send(
        self,
        phone: str,
        template_key: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """统一发送入口 -- 根据 provider 分发"""
        biz_id = f"sms_{uuid.uuid4().hex[:12]}"
        masked_phone = self._mask_phone(phone)

        if self._is_mock:
            logger.info(
                "sms_send_mock",
                biz_id=biz_id,
                phone=masked_phone,
                provider=self._provider,
                template_key=template_key,
                params=params,
            )
            return {
                "biz_id": biz_id,
                "status": "mock",
                "phone": masked_phone,
                "provider": self._provider,
            }

        try:
            if self._provider == "tencent":
                await self._call_tencent_sms(phone, template_key, params)
            else:
                await self._call_aliyun_sms(phone, template_key, params)

            logger.info(
                "sms_sent",
                biz_id=biz_id,
                phone=masked_phone,
                provider=self._provider,
                template_key=template_key,
            )
            return {
                "biz_id": biz_id,
                "status": "sent",
                "phone": masked_phone,
                "provider": self._provider,
            }
        except (ConnectionError, TimeoutError, ValueError, OSError) as exc:
            logger.error(
                "sms_send_failed",
                biz_id=biz_id,
                phone=masked_phone,
                provider=self._provider,
                error=str(exc),
            )
            return {
                "biz_id": biz_id,
                "status": "failed",
                "phone": masked_phone,
                "provider": self._provider,
                "error": str(exc),
            }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部：阿里云 SMS API
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _call_aliyun_sms(
        self, phone: str, template_key: str, params: dict[str, str]
    ) -> dict[str, Any]:
        """调用阿里云 dysmsapi SendSms 接口"""
        import aiohttp

        template_code = ALIYUN_TEMPLATES.get(template_key, template_key)
        api_url = "https://dysmsapi.aliyuncs.com/"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex[:16]

        query_params = {
            "AccessKeyId": self._access_key_id,
            "Action": "SendSms",
            "Format": "JSON",
            "PhoneNumbers": phone,
            "RegionId": self._region,
            "SignName": self._sign_name,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": nonce,
            "SignatureVersion": "1.0",
            "TemplateCode": template_code,
            "TemplateParam": json.dumps(params, ensure_ascii=False),
            "Timestamp": timestamp,
            "Version": "2017-05-25",
        }

        signature = self._calc_aliyun_signature(query_params)
        query_params["Signature"] = signature

        async with aiohttp.ClientSession() as session, session.get(
            api_url, params=query_params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            result = await resp.json()
            if result.get("Code") != "OK":
                raise ValueError(
                    f"Aliyun SMS error: {result.get('Code')} - {result.get('Message')}"
                )
            return result

    def _calc_aliyun_signature(self, params: dict[str, str]) -> str:
        """计算阿里云 API 签名（HMAC-SHA1）"""
        sorted_params = sorted(params.items())
        canonicalized = "&".join(
            f"{quote(k, safe='')}" + "=" + f"{quote(str(v), safe='')}"
            for k, v in sorted_params
        )
        string_to_sign = f"GET&{quote('/', safe='')}&{quote(canonicalized, safe='')}"
        signing_key = (self._access_key_secret + "&").encode("utf-8")
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha1
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    async def _query_aliyun_status(self, biz_id: str) -> dict[str, Any]:
        """阿里云短信发送状态查询（占位）"""
        logger.info("aliyun_sms_query_status", biz_id=biz_id)
        return {"biz_id": biz_id, "status": "unknown", "send_time": None}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  内部：腾讯云 SMS API
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _call_tencent_sms(
        self, phone: str, template_key: str, params: dict[str, str]
    ) -> dict[str, Any]:
        """调用腾讯云 SMS SendSms 接口

        使用 TC3-HMAC-SHA256 签名。
        """
        import aiohttp

        template_id = TENCENT_TEMPLATES.get(template_key, template_key)
        sdk_app_id = os.getenv("TENCENT_SMS_SDK_APP_ID", "")
        api_url = "https://sms.tencentcloudapi.com"

        # 腾讯云需要 +86 前缀
        phone_with_prefix = phone if phone.startswith("+") else f"+86{phone}"

        payload = {
            "SmsSdkAppId": sdk_app_id,
            "SignName": self._sign_name,
            "TemplateId": template_id,
            "TemplateParamSet": list(params.values()),
            "PhoneNumberSet": [phone_with_prefix],
        }

        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        headers = self._build_tencent_headers(payload, timestamp)

        async with aiohttp.ClientSession() as session, session.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            result = await resp.json()
            response = result.get("Response", {})
            if response.get("Error"):
                raise ValueError(
                    f"Tencent SMS error: {response['Error'].get('Code')} - "
                    f"{response['Error'].get('Message')}"
                )
            return response

    def _build_tencent_headers(
        self, payload: dict[str, Any], timestamp: str
    ) -> dict[str, str]:
        """构建腾讯云 TC3-HMAC-SHA256 签名 headers"""
        service = "sms"
        host = "sms.tencentcloudapi.com"
        date = datetime.fromtimestamp(
            int(timestamp), tz=timezone.utc
        ).strftime("%Y-%m-%d")

        # Step 1: 拼接规范请求串
        payload_str = json.dumps(payload, separators=(",", ":"))
        hashed_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        canonical_request = (
            f"POST\n/\n\n"
            f"content-type:application/json\n"
            f"host:{host}\n\n"
            f"content-type;host\n"
            f"{hashed_payload}"
        )

        # Step 2: 拼接待签名字符串
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical = hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()
        string_to_sign = (
            f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{hashed_canonical}"
        )

        # Step 3: 计算签名
        def _hmac_sha256(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = _hmac_sha256(
            f"TC3{self._access_key_secret}".encode("utf-8"), date
        )
        secret_service = _hmac_sha256(secret_date, service)
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Step 4: 拼接 Authorization
        authorization = (
            f"TC3-HMAC-SHA256 Credential={self._access_key_id}/{credential_scope}, "
            f"SignedHeaders=content-type;host, Signature={signature}"
        )

        return {
            "Content-Type": "application/json",
            "Host": host,
            "X-TC-Action": "SendSms",
            "X-TC-Version": "2021-01-11",
            "X-TC-Timestamp": timestamp,
            "X-TC-Region": self._region,
            "Authorization": authorization,
        }

    async def _query_tencent_status(self, biz_id: str) -> dict[str, Any]:
        """腾讯云短信发送状态查询（占位）"""
        logger.info("tencent_sms_query_status", biz_id=biz_id)
        return {"biz_id": biz_id, "status": "unknown", "send_time": None}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  工具方法
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _mask_phone(phone: str) -> str:
        """手机号脱敏: 138****8000"""
        if len(phone) >= 7:
            return phone[:3] + "****" + phone[-4:]
        return "***"
