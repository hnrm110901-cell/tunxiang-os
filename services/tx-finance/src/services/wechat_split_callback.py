"""WeChat 分账回调适配器 — 微信 V3 API 异步通知 → 内部 ChannelNotifyRequest

微信支付 V3 分账回调格式（简化）：
  {
    "id": "EV-2018022511223320873",
    "create_time": "2015-05-20T13:29:35+08:00",
    "resource_type": "encrypt-resource",
    "event_type": "PROFITSHARING.FINISHED",
    "summary": "分账完成",
    "resource": {
      "original_type": "profitsharing",
      "algorithm": "AEAD_AES_256_GCM",
      "ciphertext": "...",
      "associated_data": "profitsharing",
      "nonce": "..."
    }
  }

解密后 resource（分账结果）：
  {
    "transaction_id": "4200000000000000001",
    "out_order_no": "P20210401000001",
    "receivers": [
      {"type": "MERCHANT_ID", "account": "1900000001", "amount": 100, "result": "SUCCESS"},
      {"type": "MERCHANT_ID", "account": "1900000002", "amount": 200, "result": "FAIL"}
    ],
    "state": "FINISHED",
    "success_time": "2021-04-01T10:30:00+08:00"
  }

本模块负责：
  1. 验证微信平台证书签名（API V3 回调验签）
  2. 解密 resource.ciphertext（AEAD_AES_256_GCM）
  3. 转换为内部 ChannelNotifyRequest 格式
  4. 调用 SplitEngine.apply_channel_notification 更新流水状态
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .split_engine import SplitEngine

logger = structlog.get_logger(__name__)

# 微信支付 V3 API 回调内容类型
_WECHAT_CALLBACK_CONTENT_TYPE = "application/json"

# 签名有效时间窗口（秒）— 防重放攻击
_SIGNATURE_MAX_AGE_SEC = 300


def _verify_wechat_signature(
    body: bytes,
    wechatpay_signature: str,
    wechatpay_timestamp: str,
    wechatpay_nonce: str,
    wechatpay_serial: str,
) -> bool:
    """验证微信支付 V3 回调签名。

    微信签名算法（V3）：
      sign_str = timestamp + "\n" + nonce + "\n" + body + "\n"
      signature = base64(SHA256-RSA2048(sign_str))  # 平台证书私钥签名

    Args:
        body: 原始 HTTP 请求体（字节）
        wechatpay_signature: Wechatpay-Signature header（Base64 编码的 RSA-SHA256 签名）
        wechatpay_timestamp: Wechatpay-Timestamp header（Unix 秒级时间戳）
        wechatpay_nonce: Wechatpay-Nonce header（随机字符串）
        wechatpay_serial: Wechatpay-Serial header（平台证书序列号）

    Returns:
        True 如果签名有效，否则 False
    """
    # 防重放：时间戳不能超过 5 分钟
    try:
        ts = int(wechatpay_timestamp)
    except (ValueError, TypeError):
        logger.warning("wechat_split_callback.invalid_timestamp", timestamp=wechatpay_timestamp)
        return False
    if abs(time.time() - ts) > _SIGNATURE_MAX_AGE_SEC:
        logger.warning(
            "wechat_split_callback.timestamp_expired",
            timestamp=ts,
            now=int(time.time()),
            diff=abs(time.time() - ts),
        )
        return False

    # TODO: 使用微信平台公钥验证 RSA-SHA256 签名
    # 平台证书通过 GET /v3/certificates 定期下载并缓存
    # 公钥存储在 TX_WECHAT_PLATFORM_CERT_{serial} 环境变量或 Redis 中
    sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body.decode('utf-8')}\n"

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        # 从环境变量或 Redis 中加载平台证书公钥
        cert_pem = os.getenv(f"TX_WECHAT_PLATFORM_CERT_{wechatpay_serial}", "")
        cert_env_key = os.getenv("TX_WECHAT_PLATFORM_CERT_KEY", "")
        if cert_env_key:
            cert_pem = os.getenv(cert_env_key, "")

        if not cert_pem:
            # 非开发环境禁止 dev HMAC 降级，防止生产后门
            env_name = os.getenv("TX_ENV", "").strip().lower()
            is_dev = env_name in ("dev", "development", "local")
            secret = os.getenv("TX_WECHAT_CALLBACK_DEV_SECRET", "").strip()
            if secret:
                if not is_dev:
                    logger.error(
                        "wechat_split_callback.dev_hmac_in_non_dev",
                        serial=wechatpay_serial,
                        env=env_name,
                    )
                    return False
                expected = hmac.new(
                    secret.encode("utf-8"), body, hashlib.sha256
                ).hexdigest()
                return hmac.compare_digest(wechatpay_signature, expected)
            logger.error("wechat_split_callback.no_platform_cert", serial=wechatpay_serial)
            return False

        public_key = serialization.load_pem_public_key(cert_pem.encode("utf-8"))
        signature_bytes = base64.b64decode(wechatpay_signature)
        public_key.verify(
            signature_bytes,
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        logger.exception("wechat_split_callback.signature_verification_failed")
        return False


def _decrypt_wechat_resource(ciphertext: str, associated_data: str, nonce: str) -> Optional[dict]:
    """解密微信支付回调 resource.ciphertext。

    解密算法：AEAD_AES_256_GCM

    Args:
        ciphertext: Base64 编码的密文
        associated_data: 附加数据（字符串，如 "profitsharing"）
        nonce: Base64 编码的 nonce

    Returns:
        解密后的 JSON 字典，解密失败返回 None
    """
    api_v3_key = os.getenv("TX_WECHAT_API_V3_KEY", "").strip()
    if not api_v3_key:
        logger.error("wechat_split_callback.missing_api_v3_key")
        return None

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(api_v3_key.encode("utf-8"))
        decrypted = aesgcm.decrypt(
            base64.b64decode(nonce),
            base64.b64decode(ciphertext),
            associated_data.encode("utf-8"),
        )
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        logger.exception("wechat_split_callback.decrypt_failed")
        return None


def _map_wechat_to_internal(
    resource: dict, state: str, wechat_event_id: str
) -> List[Dict[str, Any]]:
    """将微信分账结果映射为内部 ChannelNotifyItem 列表。

    Args:
        resource: 解密后的 resource 对象
        state: 分账状态（FINISHED / FAILED / PROCESSING）
        wechat_event_id: 微信回调事件 ID

    Returns:
        [{"record_id": "wx_...", "outcome": "settled"|"failed", "order_no": "...", "receiver_account": "..."}]
    """
    items: List[Dict[str, Any]] = []

    # 微信分账单号（用于通过 orders.out_order_no 定位内部 order_id，然后找到 profit_split_records）
    out_order_no = resource.get("out_order_no", "")
    # 微信支付子商户号（用于 tenant_id 映射）
    sub_mchid = resource.get("sub_mchid", "") or resource.get("mchid", "")
    # 微信交易单号（回查用）
    transaction_id = resource.get("transaction_id", "")

    for receiver in resource.get("receivers", []):
        receiver_account = receiver.get("account", "")
        result = receiver.get("result", "SUCCESS")

        outcome = "settled" if result == "SUCCESS" else "failed"

        # record_id 为非 UUID 格式（wx_ 前缀），实际定位通过 order_no + receiver_account
        items.append({
            "record_id": f"wx_{out_order_no}_{receiver_account}",
            "outcome": outcome,
            "order_no": out_order_no,           # 用于 split_engine._settle_by_lookup
            "receiver_account": receiver_account,  # 用于 split_engine._settle_by_lookup
            "wechat_event_id": wechat_event_id,
            "wechat_state": state,
            "sub_mchid": sub_mchid,             # 用于 tenant_id 解析
            "receiver_type": receiver.get("type", "MERCHANT_ID"),
            "amount_fen": receiver.get("amount", 0),
            "transaction_id": transaction_id,
        })

    return items


def _resolve_tenant_id_from_wechat(sub_mchid: str, order_no: str) -> Optional[str]:
    """从微信子商户号或分账单号解析 tenant_id。

    优先级：
      1. 环境变量 TX_WECHAT_MCH_TENANT_MAP JSON：{"mchid": "tenant_uuid", ...}
      2. 数据库查询：SELECT tenant_id FROM orders WHERE out_order_no = :order_no
      3. 默认 tenant_id 环境变量 TX_WECHAT_DEFAULT_TENANT_ID

    Returns:
        tenant_id 字符串，解析失败返回 None
    """
    import json as _json

    # 方式 1: 环境变量映射
    mch_map_raw = os.getenv("TX_WECHAT_MCH_TENANT_MAP", "").strip()
    if mch_map_raw and sub_mchid:
        try:
            mch_map = _json.loads(mch_map_raw)
            tenant = mch_map.get(sub_mchid)
            if tenant:
                return str(tenant)
        except (_json.JSONDecodeError, TypeError):
            logger.warning("wechat_split_callback.invalid_mch_map")

    # 方式 2: 数据库查询（在生产环境中，通过 order_no 反查 tenant_id）
    # TODO: 实现异步 DB 查询 `SELECT tenant_id FROM orders WHERE out_order_no = :order_no`
    # 当前仅支持方式 1 和 3

    # 方式 3: 默认租户（单租户部署场景）
    default = os.getenv("TX_WECHAT_DEFAULT_TENANT_ID", "").strip()
    if default:
        return default

    logger.error(
        "wechat_split_callback.cannot_resolve_tenant",
        sub_mchid=sub_mchid,
        order_no=order_no,
    )
    return None


class WechatSplitCallbackHandler:
    """微信支付分账回调处理器。

    使用方式：
        handler = WechatSplitCallbackHandler(db_session, tenant_id)
        result = await handler.process_callback(
            body_bytes=request_body,
            headers={
                "Wechatpay-Signature": "...",
                "Wechatpay-Timestamp": "...",
                "Wechatpay-Nonce": "...",
                "Wechatpay-Serial": "...",
            },
        )
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.engine = SplitEngine(db, tenant_id)

    async def process_callback(
        self, body_bytes: bytes, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """处理微信分账回调通知。

        流程:
          1. 验证回调签名
          2. 解析回调 body
          3. 解密 resource.ciphertext
          4. 转换为内部格式
          5. 更新 profit_split_records 状态

        Returns:
            处理结果摘要
        """
        # Step 1: 验签
        signature = headers.get("wechatpay-signature", "")
        timestamp = headers.get("wechatpay-timestamp", "")
        nonce = headers.get("wechatpay-nonce", "")
        serial = headers.get("wechatpay-serial", "")

        if not all([signature, timestamp, nonce, serial]):
            logger.error(
                "wechat_split_callback.missing_headers",
                tenant_id=self.tenant_id,
            )
            return {"ok": False, "error": {"code": "MISSING_WECHAT_HEADERS"}}

        if not _verify_wechat_signature(body_bytes, signature, timestamp, nonce, serial):
            logger.error(
                "wechat_split_callback.invalid_signature",
                tenant_id=self.tenant_id,
                serial=serial,
            )
            return {"ok": False, "error": {"code": "SIGNATURE_VERIFICATION_FAILED"}}

        # Step 2: 解析回调 body
        try:
            notification = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return {"ok": False, "error": {"code": "INVALID_JSON", "detail": str(e)}}

        event_type = notification.get("event_type", "")
        wechat_event_id = notification.get("id", "")
        resource_data = notification.get("resource", {})

        if event_type != "PROFITSHARING.FINISHED":
            logger.info(
                "wechat_split_callback.unknown_event_type",
                event_type=event_type,
                tenant_id=self.tenant_id,
            )
            return {"ok": True, "data": {"ignored": True, "event_type": event_type}}

        # Step 3: 解密 resource
        resource = _decrypt_wechat_resource(
            ciphertext=resource_data.get("ciphertext", ""),
            associated_data=resource_data.get("associated_data", ""),
            nonce=resource_data.get("nonce", ""),
        )

        if resource is None:
            return {"ok": False, "error": {"code": "DECRYPT_FAILED"}}

        # Step 4: 映射
        state = resource.get("state", "UNKNOWN")
        items = _map_wechat_to_internal(resource, state, wechat_event_id)

        if not items:
            return {"ok": True, "data": {"ignored": True, "reason": "no_receivers"}}

        # Step 5: 更新流水
        logger.info(
            "wechat_split_callback.processing",
            tenant_id=self.tenant_id,
            items_count=len(items),
            event_id=wechat_event_id,
            state=state,
        )

        result = await self.engine.apply_channel_notification(items)
        await self.db.commit()

        return {
            "ok": True,
            "data": {
                "wechat_event_id": wechat_event_id,
                "state": state,
                **result,
            },
        }
