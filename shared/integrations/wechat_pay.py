"""微信支付 V3 API 对接

环境变量:
  WECHAT_PAY_MCH_ID      — 商户号
  WECHAT_PAY_API_KEY_V3  — APIv3密钥（用于回调解密、下载平台证书）
  WECHAT_PAY_CERT_PATH   — 商户私钥证书路径（apiclient_key.pem）
  WECHAT_PAY_APPID       — 小程序AppID
  WECHAT_PAY_MCH_CERT_SERIAL — 商户 API 证书序列号（调用 /v3/* 与拉取平台证书必填）
  WECHAT_PAY_SERIAL_NO   — 同上（与 gateway 命名兼容）
  WECHAT_PAY_MCH_X509_PATH — 可选：商户 apiclient_cert.pem，用于自动解析序列号

当环境变量未配置时，非生产环境返回 Mock 成功响应，便于开发调试。

生产环境（ENVIRONMENT/ENV 为 production 或 prod）若未配置四项密钥，默认 **拒绝启动**
`WechatPayService`（抛 RuntimeError），除非显式设置 `TX_WECHAT_PAY_ALLOW_MOCK=1`（仅限灰度/演练）。
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

# 微信支付 V3 基地址
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


def _normalize_wechat_serial(serial: str) -> str:
    return serial.strip().upper()


def _callback_timestamp_skew_seconds() -> int:
    raw = os.environ.get("WECHAT_PAY_CALLBACK_TIMESTAMP_SKEW_SECONDS", "300")
    try:
        return max(1, int(raw))
    except ValueError:
        return 300


def _get_wechatpay_header(headers: dict[str, str], suffix: str) -> str:
    """读取 Wechatpay-* 头。

    FastAPI/Starlette 的 ``dict(request.headers)`` 会将键规范为小写，故此处按不区分大小写匹配。
    """
    target = f"wechatpay-{suffix}".lower()
    for k, v in headers.items():
        if k.lower() == target:
            return str(v)
    return ""


def _verify_rsa_sha256_pkcs1v15(public_key: Any, message: bytes, signature_b64: str) -> None:
    """使用微信平台证书公钥验证回调签名（SHA256 + PKCS1v15）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        sig = base64.b64decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise ValueError("Wechatpay-Signature 非合法 Base64") from exc
    try:
        public_key.verify(sig, message, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise ValueError("微信支付回调签名验证失败") from exc


class WechatPayService:
    """微信支付 V3 服务

    - 未配置环境变量时：非生产为 Mock；生产默认拒绝实例化（见 __init__）
    - 所有金额单位：分（int）
    - 签名算法：RSA-SHA256（V3 规范）
    - 回调解密：AES-256-GCM
    """

    def __init__(self) -> None:
        self._mock_mode = not _is_configured()
        self._private_key: Any = None
        self._merchant_serial_no: str | None = None
        self._platform_public_keys: dict[str, Any] = {}
        self._platform_keys_lock = asyncio.Lock()
        if self._mock_mode:
            if _is_production_env() and not _mock_explicitly_allowed():
                raise RuntimeError(
                    "生产环境禁止微信支付 Mock：请配置 WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / "
                    "WECHAT_PAY_CERT_PATH / WECHAT_PAY_APPID；"
                    "若仅为灰度演练需 Mock，请显式设置 TX_WECHAT_PAY_ALLOW_MOCK=1"
                )
            logger.warning(
                "WechatPayService: 环境变量未配置，进入 Mock 模式。"
                "请设置 WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / "
                "WECHAT_PAY_CERT_PATH / WECHAT_PAY_APPID"
            )
        else:
            self._private_key = _load_private_key()

    def _load_merchant_serial_no(self) -> str:
        """商户 API 证书序列号（请求微信 V3 接口 Authorization 必填）。"""
        if self._merchant_serial_no is not None:
            return self._merchant_serial_no
        serial = (
            os.environ.get("WECHAT_PAY_MCH_CERT_SERIAL") or os.environ.get("WECHAT_PAY_SERIAL_NO") or ""
        ).strip()
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
            "微信支付 API 需商户证书序列号：设置 WECHAT_PAY_MCH_CERT_SERIAL（或 WECHAT_PAY_SERIAL_NO），"
            "或配置 WECHAT_PAY_MCH_X509_PATH 指向 apiclient_cert.pem"
        )

    def _decrypt_aes_gcm_api_v3(
        self, nonce: str, ciphertext: str, associated_data: str
    ) -> bytes:
        """APIv3 密钥 AES-256-GCM 解密（回调 resource / 平台证书 encrypt_certificate）。"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = _API_KEY_V3.encode("utf-8")
        nonce_bytes = nonce.encode("utf-8")
        aad = associated_data.encode("utf-8") if associated_data else None
        data = base64.b64decode(ciphertext)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce_bytes, data, aad)

    async def _ensure_platform_public_key(self, serial: str) -> Any:
        """按序列号解析微信平台证书公钥（带缓存与自动下载）。"""
        serial_n = _normalize_wechat_serial(serial)
        if not serial_n:
            raise ValueError("Wechatpay-Serial 为空")
        async with self._platform_keys_lock:
            if serial_n in self._platform_public_keys:
                return self._platform_public_keys[serial_n]
            await self._fetch_platform_certificates()
            if serial_n in self._platform_public_keys:
                return self._platform_public_keys[serial_n]
            # 证书轮换：清空后再拉一次
            self._platform_public_keys.clear()
            await self._fetch_platform_certificates()
            if serial_n in self._platform_public_keys:
                return self._platform_public_keys[serial_n]
        raise ValueError(f"无法获取微信平台证书公钥，serial={serial_n}")

    async def _fetch_platform_certificates(self) -> None:
        """GET /v3/certificates，解密并缓存平台证书公钥。"""
        from cryptography import x509

        resp = await self._request("GET", "/v3/certificates", None)
        for item in resp.get("data") or []:
            sn = item.get("serial_no") or ""
            ec = item.get("encrypt_certificate") or {}
            if not sn or not ec:
                continue
            sn_n = _normalize_wechat_serial(sn)
            try:
                pem_bytes = self._decrypt_aes_gcm_api_v3(
                    ec.get("nonce", ""),
                    ec.get("ciphertext", ""),
                    ec.get("associated_data", ""),
                )
            except (ValueError, KeyError) as exc:
                logger.warning("跳过无法解密的平台证书项: serial=%s err=%s", sn_n, exc)
                continue
            try:
                cert = x509.load_pem_x509_certificate(pem_bytes)
            except ValueError as exc:
                logger.warning("平台证书 PEM 解析失败: serial=%s err=%s", sn_n, exc)
                continue
            self._platform_public_keys[sn_n] = cert.public_key()

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
        wechat_timestamp = _get_wechatpay_header(headers, "timestamp")
        wechat_nonce = _get_wechatpay_header(headers, "nonce")
        wechat_signature = _get_wechatpay_header(headers, "signature")
        wechat_serial = _get_wechatpay_header(headers, "serial")

        if not all([wechat_timestamp, wechat_nonce, wechat_signature, wechat_serial]):
            raise ValueError("缺少微信支付回调签名头")

        body_str = body.decode("utf-8") if isinstance(body, bytes) else body
        try:
            ts_int = int(str(wechat_timestamp).strip())
        except ValueError as exc:
            raise ValueError("Wechatpay-Timestamp 非法") from exc
        skew = _callback_timestamp_skew_seconds()
        if abs(int(time.time()) - ts_int) > skew:
            raise ValueError("微信支付回调时间戳超出允许窗口（防重放）")

        sign_msg = f"{wechat_timestamp}\n{wechat_nonce}\n{body_str}\n".encode("utf-8")
        pub = await self._ensure_platform_public_key(wechat_serial)
        _verify_rsa_sha256_pkcs1v15(pub, sign_msg, wechat_signature)

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
        plaintext = self._decrypt_aes_gcm_api_v3(nonce, ciphertext, associated_data)
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
