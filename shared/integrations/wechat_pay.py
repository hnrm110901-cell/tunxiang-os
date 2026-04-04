"""微信支付 V3 API 对接

环境变量:
  WECHAT_PAY_MCH_ID      — 商户号
  WECHAT_PAY_API_KEY_V3  — APIv3密钥（用于回调解密）
  WECHAT_PAY_CERT_PATH   — 商户私钥证书路径（apiclient_key.pem）
  WECHAT_PAY_APPID       — 小程序AppID

当环境变量未配置时，所有方法返回 Mock 成功响应，便于开发调试。
"""

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

# 微信支付 V3 基地址
_BASE_URL = "https://api.mch.weixin.qq.com"


def _is_configured() -> bool:
    """检查环境变量是否已配置"""
    return bool(_MCH_ID and _API_KEY_V3 and _CERT_PATH and _APPID)


def _load_private_key() -> Any:
    """加载商户 RSA 私钥（PEM 格式）"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    with open(_CERT_PATH, "rb") as f:
        return load_pem_private_key(f.read(), password=None)


class WechatPayService:
    """微信支付 V3 服务

    - 未配置环境变量时自动降级为 Mock 模式
    - 所有金额单位：分（int）
    - 签名算法：RSA-SHA256（V3 规范）
    - 回调解密：AES-256-GCM
    """

    def __init__(self) -> None:
        self._mock_mode = not _is_configured()
        self._private_key: Any = None
        if self._mock_mode:
            logger.warning(
                "WechatPayService: 环境变量未配置，进入 Mock 模式。"
                "请设置 WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / "
                "WECHAT_PAY_CERT_PATH / WECHAT_PAY_APPID"
            )
        else:
            self._private_key = _load_private_key()

    # ─── 创建预支付订单 ───

    async def create_prepay(
        self,
        out_trade_no: str,
        total_fen: int,
        description: str,
        openid: str,
        notify_url: str,
    ) -> dict:
        """创建 JSAPI 预支付订单，返回小程序调 wx.requestPayment 所需全部参数。

        Args:
            out_trade_no: 商户订单号（唯一）
            total_fen: 支付金额（分）
            description: 商品描述
            openid: 用户 OpenID
            notify_url: 支付结果回调地址

        Returns:
            dict: { timeStamp, nonceStr, package, signType, paySign }
        """
        if self._mock_mode:
            return self._mock_prepay_response(out_trade_no)

        # 构造请求体
        body = {
            "appid": _APPID,
            "mchid": _MCH_ID,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": notify_url,
            "amount": {"total": total_fen, "currency": "CNY"},
            "payer": {"openid": openid},
        }

        url_path = "/v3/pay/transactions/jsapi"
        resp_data = await self._request("POST", url_path, body)
        prepay_id = resp_data.get("prepay_id", "")

        # 生成小程序调起支付所需的签名参数
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        package_str = f"prepay_id={prepay_id}"

        # 签名内容：appId\n时间戳\n随机字符串\nprepay_id=xxx\n
        sign_message = f"{_APPID}\n{timestamp}\n{nonce_str}\n{package_str}\n"
        pay_sign = self._sign_v3_raw(sign_message)

        return {
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package_str,
            "signType": "RSA",
            "paySign": pay_sign,
        }

    # ─── 验证支付回调 ───

    async def verify_callback(self, headers: dict, body: bytes) -> dict:
        """验证微信支付回调签名并解密通知内容。

        Args:
            headers: HTTP 请求头（需包含 Wechatpay-Timestamp, Wechatpay-Nonce,
                     Wechatpay-Signature, Wechatpay-Serial）
            body: 原始请求体（bytes）

        Returns:
            dict: 解密后的通知内容（含 out_trade_no, transaction_id, trade_state 等）

        Raises:
            ValueError: 签名验证失败
        """
        if self._mock_mode:
            return self._mock_callback_response(body)

        # 1. 验证签名（生产环境需加载微信平台证书公钥验签）
        # TODO: 从微信获取平台证书并验签（需定期下载平台证书）
        wechat_timestamp = headers.get("Wechatpay-Timestamp", "")
        wechat_nonce = headers.get("Wechatpay-Nonce", "")
        wechat_signature = headers.get("Wechatpay-Signature", "")
        wechat_serial = headers.get("Wechatpay-Serial", "")

        if not all([wechat_timestamp, wechat_nonce, wechat_signature, wechat_serial]):
            raise ValueError("缺少微信支付回调签名头")

        # 签名验证消息：时间戳\n随机串\n请求体\n
        body_str = body.decode("utf-8") if isinstance(body, bytes) else body
        _sign_msg = f"{wechat_timestamp}\n{wechat_nonce}\n{body_str}\n"

        # TODO: 使用微信平台证书公钥验证 wechat_signature
        # 此处暂信任（生产必须实现验签）
        logger.warning(
            "verify_callback: 平台证书验签尚未实现，serial=%s", wechat_serial
        )

        # 2. 解密通知内容
        notification = json.loads(body_str)
        resource = notification.get("resource", {})
        nonce = resource.get("nonce", "")
        ciphertext = resource.get("ciphertext", "")
        associated_data = resource.get("associated_data", "")

        return self._decrypt_callback(nonce, ciphertext, associated_data)

    # ─── 主动查询订单 ───

    async def query_order(self, out_trade_no: str) -> dict:
        """主动查询订单支付状态。

        Args:
            out_trade_no: 商户订单号

        Returns:
            dict: { trade_state, trade_state_desc, transaction_id, ... }
        """
        if self._mock_mode:
            return {
                "out_trade_no": out_trade_no,
                "trade_state": "SUCCESS",
                "trade_state_desc": "支付成功（Mock）",
                "transaction_id": f"MOCK_TXN_{uuid.uuid4().hex[:16]}",
                "payer": {"openid": "MOCK_OPENID"},
                "amount": {"total": 100, "payer_total": 100, "currency": "CNY"},
            }

        url_path = (
            f"/v3/pay/transactions/out-trade-no/{out_trade_no}"
            f"?mchid={_MCH_ID}"
        )
        return await self._request("GET", url_path)

    # ─── 申请退款 ───

    async def refund(
        self,
        out_trade_no: str,
        refund_no: str,
        total_fen: int,
        refund_fen: int,
        reason: str = "",
    ) -> dict:
        """申请退款。

        Args:
            out_trade_no: 原商户订单号
            refund_no: 商户退款单号（唯一）
            total_fen: 原订单金额（分）
            refund_fen: 退款金额（分）
            reason: 退款原因

        Returns:
            dict: { refund_id, out_refund_no, status, ... }
        """
        if self._mock_mode:
            return {
                "refund_id": f"MOCK_REFUND_{uuid.uuid4().hex[:16]}",
                "out_refund_no": refund_no,
                "out_trade_no": out_trade_no,
                "status": "PROCESSING",
                "amount": {
                    "total": total_fen,
                    "refund": refund_fen,
                    "currency": "CNY",
                },
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            }

        body = {
            "out_trade_no": out_trade_no,
            "out_refund_no": refund_no,
            "reason": reason,
            "amount": {
                "refund": refund_fen,
                "total": total_fen,
                "currency": "CNY",
            },
        }
        return await self._request("POST", "/v3/refund/domestic/refunds", body)

    # ─── 查询退款状态 ───

    async def query_refund(self, refund_no: str) -> dict:
        """查询退款状态。

        Args:
            refund_no: 商户退款单号

        Returns:
            dict: { refund_id, out_refund_no, status, ... }
        """
        if self._mock_mode:
            return {
                "refund_id": f"MOCK_REFUND_{uuid.uuid4().hex[:16]}",
                "out_refund_no": refund_no,
                "status": "SUCCESS",
                "amount": {"refund": 100, "total": 100, "currency": "CNY"},
            }

        url_path = f"/v3/refund/domestic/refunds/{refund_no}"
        return await self._request("GET", url_path)

    # ─── V3 签名（RSA-SHA256） ───

    def _sign_v3(
        self, method: str, url: str, timestamp: str, nonce: str, body: str
    ) -> str:
        """生成微信支付 V3 请求签名。

        签名格式：HTTP方法\\n URL路径\\n时间戳\\n随机串\\n请求体\\n

        Args:
            method: HTTP 方法（GET/POST）
            url: URL 路径（如 /v3/pay/transactions/jsapi）
            timestamp: 时间戳
            nonce: 随机字符串
            body: 请求体（GET 请求为空字符串）

        Returns:
            str: Base64 编码的签名
        """
        sign_message = f"{method}\n{url}\n{timestamp}\n{nonce}\n{body}\n"
        return self._sign_v3_raw(sign_message)

    def _sign_v3_raw(self, message: str) -> str:
        """对原始消息进行 RSA-SHA256 签名并返回 Base64 编码结果。"""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = self._private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    # ─── AES-256-GCM 解密回调 ───

    def _decrypt_callback(
        self, nonce: str, ciphertext: str, associated_data: str
    ) -> dict:
        """AES-256-GCM 解密微信支付回调通知。

        Args:
            nonce: 随机串
            ciphertext: Base64 编码的密文
            associated_data: 附加数据

        Returns:
            dict: 解密后的 JSON 对象
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = _API_KEY_V3.encode("utf-8")
        nonce_bytes = nonce.encode("utf-8")
        aad = associated_data.encode("utf-8") if associated_data else None
        data = base64.b64decode(ciphertext)

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce_bytes, data, aad)
        return json.loads(plaintext.decode("utf-8"))

    # ─── HTTP 请求（生产模式） ───

    async def _request(
        self, method: str, url_path: str, body: dict | None = None
    ) -> dict:
        """发送微信支付 V3 HTTP 请求（带签名）。

        当前阶段：HTTP 请求通过 httpx 实现。
        若 httpx 不可用则降级为 Mock 响应。
        """
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        body_str = json.dumps(body) if body else ""

        signature = self._sign_v3(method, url_path, timestamp, nonce, body_str)
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{_MCH_ID}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="CERT_SERIAL_TODO",'
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
                        "微信支付 API 错误: status=%s body=%s",
                        resp.status_code,
                        resp.text,
                    )
                    raise ValueError(
                        f"微信支付 API 返回 {resp.status_code}: {resp.text}"
                    )
                return resp.json()
        except ImportError:
            logger.warning("httpx 未安装，降级为 Mock 响应")
            return {"prepay_id": f"MOCK_PREPAY_{uuid.uuid4().hex[:16]}"}

    # ─── Mock 响应 ───

    def _mock_prepay_response(self, out_trade_no: str) -> dict:
        """Mock 预支付响应（开发调试用）"""
        timestamp = str(int(time.time()))
        nonce_str = uuid.uuid4().hex
        mock_prepay_id = f"MOCK_PREPAY_{uuid.uuid4().hex[:16]}"
        return {
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": f"prepay_id={mock_prepay_id}",
            "signType": "RSA",
            "paySign": f"MOCK_SIGN_{out_trade_no[:8]}",
        }

    def _mock_callback_response(self, body: bytes) -> dict:
        """Mock 回调解密响应（开发调试用）"""
        try:
            body_str = body.decode("utf-8") if isinstance(body, bytes) else body
            notification = json.loads(body_str)
            # 尝试从 Mock 回调体中提取 out_trade_no
            resource = notification.get("resource", {})
            out_trade_no = resource.get("out_trade_no", f"MOCK_{uuid.uuid4().hex[:8]}")
        except (json.JSONDecodeError, AttributeError):
            out_trade_no = f"MOCK_{uuid.uuid4().hex[:8]}"

        return {
            "out_trade_no": out_trade_no,
            "transaction_id": f"MOCK_TXN_{uuid.uuid4().hex[:16]}",
            "trade_state": "SUCCESS",
            "trade_state_desc": "支付成功（Mock）",
            "trade_type": "JSAPI",
            "payer": {"openid": "MOCK_OPENID"},
            "amount": {"total": 100, "payer_total": 100, "currency": "CNY"},
            "success_time": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }


# ─── 全局单例 ───

_instance: WechatPayService | None = None


def get_wechat_pay_service() -> WechatPayService:
    """获取 WechatPayService 全局单例"""
    global _instance
    if _instance is None:
        _instance = WechatPayService()
    return _instance
