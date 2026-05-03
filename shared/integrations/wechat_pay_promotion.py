"""微信支付 V3 营销类 API

封装摇一摇优惠（Shake Coupon）、商家名片（Merchant Card）、
投放计划（Promotion Plan）等营销类接口。

使用与 wechat_pay.py 相同的鉴权方式（RSA-SHA256 签名、APIv3 密钥）。

环境变量:
  WECHAT_PAY_MCH_ID           — 商户号
  WECHAT_PAY_API_KEY_V3       — APIv3密钥
  WECHAT_PAY_CERT_PATH        — 商户私钥证书路径（apiclient_key.pem）
  WECHAT_PAY_APPID            — 小程序AppID
  WECHAT_PAY_MCH_CERT_SERIAL  — 商户 API 证书序列号
  WECHAT_PAY_SERIAL_NO        — 同上（兼容）

当环境变量未配置时，非生产环境返回 Mock 成功响应，便于开发调试。
生产环境（ENVIRONMENT/ENV 为 production 或 prod）若未配置密钥，默认拒绝启动，
除非显式设置 TX_WECHAT_PAY_ALLOW_MOCK=1。
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ─── 环境变量 ───

_MCH_ID = os.environ.get("WECHAT_PAY_MCH_ID", "")
_API_KEY_V3 = os.environ.get("WECHAT_PAY_API_KEY_V3", "")
_CERT_PATH = os.environ.get("WECHAT_PAY_CERT_PATH", "")
_APPID = os.environ.get("WECHAT_PAY_APPID", "")
_BASE_URL = "https://api.mch.weixin.qq.com"


def _is_configured() -> bool:
    """检查环境变量是否已配置"""
    return bool(_MCH_ID and _API_KEY_V3 and _CERT_PATH and _APPID)


def _is_production_env() -> bool:
    env = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "").strip().lower()
    return env in ("production", "prod")


def _mock_explicitly_allowed() -> bool:
    """生产环境是否允许 Mock（仅应急演练；须显式开启）。"""
    return os.environ.get("TX_WECHAT_PAY_ALLOW_MOCK", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _load_private_key() -> Any:
    """加载商户 RSA 私钥（PEM 格式）"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    with open(_CERT_PATH, "rb") as f:
        return load_pem_private_key(f.read(), password=None)


class WechatPayPromotionService:
    """微信支付 V3 营销类服务

    提供摇一摇优惠、商家名片、投放计划等营销 API 调用。

    - 未配置环境变量时：非生产为 Mock；生产默认拒绝实例化
    - 所有金额单位：分（int）
    - 签名算法：RSA-SHA256（V3 规范）
    """

    def __init__(self) -> None:
        self._mock_mode = not _is_configured()
        self._private_key: Any = None
        self._merchant_serial_no: str | None = None
        if self._mock_mode:
            if _is_production_env() and not _mock_explicitly_allowed():
                raise RuntimeError(
                    "生产环境禁止微信支付营销 Mock：请配置 WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / "
                    "WECHAT_PAY_CERT_PATH / WECHAT_PAY_APPID"
                )
            logger.warning(
                "WechatPayPromotionService: 环境变量未配置，进入 Mock 模式。"
            )
        else:
            self._private_key = _load_private_key()

    # ─── 签名与请求 ───

    def _load_merchant_serial_no(self) -> str:
        """商户 API 证书序列号（请求微信 V3 接口 Authorization 必填）。"""
        if self._merchant_serial_no is not None:
            return self._merchant_serial_no
        serial = (os.environ.get("WECHAT_PAY_MCH_CERT_SERIAL") or os.environ.get("WECHAT_PAY_SERIAL_NO") or "").strip()
        if serial:
            self._merchant_serial_no = serial
            return serial
        x509_path = (
            os.environ.get("WECHAT_PAY_MCH_X509_PATH") or os.environ.get("WECHAT_PAY_CERT_X509_PATH") or ""
        ).strip()
        if x509_path and os.path.isfile(x509_path):
            from cryptography import x509

            with open(x509_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            self._merchant_serial_no = format(cert.serial_number, "X")
            return self._merchant_serial_no
        raise ValueError(
            "微信支付营销 API 需商户证书序列号：设置 WECHAT_PAY_MCH_CERT_SERIAL"
            "（或 WECHAT_PAY_SERIAL_NO），或配置 WECHAT_PAY_MCH_X509_PATH"
        )

    def _sign_v3(self, method: str, url: str, timestamp: str, nonce: str, body: str) -> str:
        """生成微信支付 V3 请求签名。

        签名格式：HTTP方法\\n URL路径\\n 时间戳\\n 随机串\\n 请求体\\n
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        sign_message = f"{method}\n{url}\n{timestamp}\n{nonce}\n{body}\n"
        signature = self._private_key.sign(
            sign_message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    async def _request(self, method: str, url_path: str, body: dict | None = None) -> dict:
        """发送微信支付 V3 HTTP 请求（带签名）。"""
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        body_str = json.dumps(body) if body else ""

        signature = self._sign_v3(method, url_path, timestamp, nonce, body_str)
        mch_serial = self._load_merchant_serial_no()
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{_MCH_ID}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{mch_serial}",'
            f'signature="{signature}"'
        )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.request(
                    method,
                    f"{_BASE_URL}{url_path}",
                    headers={
                        "Authorization": auth_header,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    content=body_str if body_str else None,
                )
                if resp.status_code >= 400:
                    logger.error(
                        "微信支付营销 API 错误: status=%s body=%s",
                        resp.status_code,
                        resp.text,
                    )
                    raise ValueError(f"微信支付营销 API 返回 {resp.status_code}: {resp.text}")
                return resp.json()
        except ImportError:
            logger.warning("httpx 未安装，降级为 Mock 响应")
            return {"mock": True, "message": "httpx 不可用"}

    # ─── 摇一摇优惠 ───

    async def create_shake_coupon_activity(
        self,
        activity_name: str,
        begin_time: str,
        end_time: str,
        award_amount_fen: int,
        total_count: int,
        **kwargs: Any,
    ) -> dict:
        """创建摇一摇优惠活动。

        Args:
            activity_name: 活动名称
            begin_time: 活动开始时间（ISO 8601）
            end_time: 活动结束时间（ISO 8601）
            award_amount_fen: 优惠金额（分）
            total_count: 优惠总份数

        Returns:
            dict: { activity_id, activity_name, status, create_time }
        """
        if self._mock_mode:
            return self._mock_shake_coupon_response(activity_name)

        body = {
            "appid": _APPID,
            "mchid": _MCH_ID,
            "activity_name": activity_name,
            "begin_time": begin_time,
            "end_time": end_time,
            "award_amount": {"total": award_amount_fen, "currency": "CNY"},
            "total_count": total_count,
        }
        body.update(kwargs)
        return await self._request("POST", "/v3/marketing/shake", body)

    # ─── 商家名片 ───

    async def create_merchant_card(
        self,
        card_name: str,
        card_type: str,
        **kwargs: Any,
    ) -> dict:
        """配置商家名片。

        Args:
            card_name: 名片名称
            card_type: 名片类型（如 "coupon"、"membership"）

        Returns:
            dict: { card_id, card_name, status, create_time }
        """
        if self._mock_mode:
            return self._mock_merchant_card_response(card_name)

        body = {
            "appid": _APPID,
            "mchid": _MCH_ID,
            "card_name": card_name,
            "card_type": card_type,
        }
        body.update(kwargs)
        return await self._request("POST", "/v3/marketing/merchant-card", body)

    # ─── 投放计划 ───

    async def create_promotion_plan(
        self,
        plan_name: str,
        plan_type: str,
        begin_time: str,
        end_time: str,
        **kwargs: Any,
    ) -> dict:
        """创建投放计划。

        Args:
            plan_name: 投放计划名称
            plan_type: 投放计划类型
            begin_time: 开始时间（ISO 8601）
            end_time: 结束时间（ISO 8601）

        Returns:
            dict: { plan_id, plan_name, status, create_time }
        """
        if self._mock_mode:
            return self._mock_promotion_plan_response(plan_name)

        body = {
            "appid": _APPID,
            "mchid": _MCH_ID,
            "plan_name": plan_name,
            "plan_type": plan_type,
            "begin_time": begin_time,
            "end_time": end_time,
        }
        body.update(kwargs)
        return await self._request("POST", "/v3/marketing/promotion-plan", body)

    # ─── 旁路触发摇优惠（支付回调使用） ───

    async def trigger_shake_coupon(self, openid: str, store_id: str, amount_fen: int) -> dict:
        """旁路触发摇一摇优惠。

        在支付回调中异步调用，不阻塞主流程。
        根据支付金额和门店配置决定是否触发摇优惠。

        Args:
            openid: 用户 OpenID
            store_id: 门店 ID
            amount_fen: 支付金额（分）

        Returns:
            dict: { triggered, openid, amount_fen, ... }
        """
        if self._mock_mode:
            return {
                "triggered": True,
                "openid": openid,
                "store_id": store_id,
                "amount_fen": amount_fen,
                "mock": True,
            }

        body = {
            "appid": _APPID,
            "mchid": _MCH_ID,
            "openid": openid,
            "store_id": store_id,
            "amount": {"total": amount_fen, "currency": "CNY"},
        }
        return await self._request("POST", "/v3/marketing/shake/trigger", body)

    # ─── Mock 响应 ───

    def _mock_shake_coupon_response(self, activity_name: str) -> dict:
        """Mock 摇一摇优惠活动响应"""
        return {
            "activity_id": f"MOCK_SHAKE_{uuid.uuid4().hex[:16]}",
            "activity_name": activity_name,
            "status": "CREATED",
            "create_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }

    def _mock_merchant_card_response(self, card_name: str) -> dict:
        """Mock 商家名片响应"""
        return {
            "card_id": f"MOCK_CARD_{uuid.uuid4().hex[:16]}",
            "card_name": card_name,
            "status": "CREATED",
            "create_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }

    def _mock_promotion_plan_response(self, plan_name: str) -> dict:
        """Mock 投放计划响应"""
        return {
            "plan_id": f"MOCK_PLAN_{uuid.uuid4().hex[:16]}",
            "plan_name": plan_name,
            "status": "CREATED",
            "create_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }


# ─── 全局单例 ───

_instance: WechatPayPromotionService | None = None


def get_wechat_pay_promotion_service() -> WechatPayPromotionService:
    """获取 WechatPayPromotionService 全局单例"""
    global _instance
    if _instance is None:
        _instance = WechatPayPromotionService()
    return _instance
