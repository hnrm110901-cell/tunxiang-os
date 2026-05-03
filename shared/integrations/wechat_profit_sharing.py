"""微信支付 V3 分账 API 对接（Task P0-05 / 3.1）

基于现有 WechatPayService 签名体系，增加分账 API：
  - 添加/删除分账接收方
  - 创建分账订单
  - 查询分账结果
  - 分账回调验签

环境变量（复用微信支付 V3 配置）：
  WECHAT_PAY_MCH_ID / WECHAT_PAY_API_KEY_V3 / WECHAT_PAY_CERT_PATH
  WECHAT_PAY_APPID / WECHAT_PAY_MCH_CERT_SERIAL

生产环境禁止 Mock（与 wechat_pay.py 一致），设置 TX_WECHAT_PAY_ALLOW_MOCK=1 强制允许。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .wechat_pay import (
    WechatPayService,
    _is_production_env,
    _mock_explicitly_allowed,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.mch.weixin.qq.com"

# 分账接收方类型
RECEIVER_TYPE_MERCHANT = "MERCHANT_ID"
RECEIVER_TYPE_PERSONAL = "PERSONAL_OPENID"

# 分账关系类型
RELATION_TYPE = {
    "supplier": "SUPPLIER",
    "distributor": "DISTRIBUTOR",
    "service_provider": "SERVICE_PROVIDER",
    "platform": "PLATFORM",
    "others": "OTHERS",
}


@dataclass
class ProfitSharingReceiver:
    """分账接收方"""
    type: str  # MERCHANT_ID / PERSONAL_OPENID
    account: str  # 商户号 / openid
    name: str = ""  # 接收方名称（个人必填）
    relation_type: str = "OTHERS"  # 与分账方的关系类型
    custom_relation: str = ""  # 自定义关系说明


@dataclass
class ProfitSharingOrder:
    """分账订单"""
    out_order_no: str  # 商户分账单号（幂等键）
    transaction_id: str  # 微信支付订单号
    receivers: List[Dict[str, Any]] = field(default_factory=list)
    unfreeze_unsplit: bool = True  # 是否解冻剩余资金


@dataclass
class ProfitSharingResult:
    """分账结果"""
    out_order_no: str
    transaction_id: str
    order_id: str = ""  # 微信分账单号
    state: str = "PROCESSING"  # PROCESSING / FINISHED
    receivers: List[Dict[str, Any]] = field(default_factory=list)


class WechatProfitSharingService:
    """微信支付分账 API 客户端

    复用 WechatPayService 的签名/Auth/加密能力。
    """

    def __init__(self, wechat_service: Optional[WechatPayService] = None):
        self._svc = wechat_service or WechatPayService()
        self._mock = not (self._svc._is_configured() if hasattr(self._svc, '_is_configured') else True)

        if _is_production_env() and self._mock and not _mock_explicitly_allowed():
            raise RuntimeError(
                "生产环境禁止 Mock 微信分账：请配置 WECHAT_PAY_* 环境变量"
                " 或设置 TX_WECHAT_PAY_ALLOW_MOCK=1（仅应急）"
            )

        self._http = None
        logger.info(
            "wechat_profit_sharing_init",
            mock=self._mock,
            production=_is_production_env(),
        )

    # ── 添加分账接收方 ─────────────────────────────────────────────

    async def add_receiver(self, receiver: ProfitSharingReceiver) -> dict:
        """POST /v3/profitsharing/receivers/add"""
        body = {
            "appid": os.environ.get("WECHAT_PAY_APPID", ""),
            "type": receiver.type,
            "account": receiver.account,
            "name": receiver.name,
            "relation_type": receiver.relation_type,
        }
        if receiver.custom_relation:
            body["custom_relation"] = receiver.custom_relation

        if self._mock:
            return {
                "ok": True,
                "type": receiver.type,
                "account": receiver.account,
                "mock": True,
            }

        return await self._request("POST", "/v3/profitsharing/receivers/add", body)

    async def delete_receiver(self, receiver_type: str, account: str) -> dict:
        """POST /v3/profitsharing/receivers/delete"""
        body = {
            "appid": os.environ.get("WECHAT_PAY_APPID", ""),
            "type": receiver_type,
            "account": account,
        }

        if self._mock:
            return {"ok": True, "type": receiver_type, "account": account, "mock": True}

        return await self._request("POST", "/v3/profitsharing/receivers/delete", body)

    # ── 创建分账订单 ───────────────────────────────────────────────

    async def create_order(self, order: ProfitSharingOrder) -> dict:
        """POST /v3/profitsharing/orders

        幂等键: out_order_no
        """
        body = {
            "appid": os.environ.get("WECHAT_PAY_APPID", ""),
            "transaction_id": order.transaction_id,
            "out_order_no": order.out_order_no,
            "receivers": [
                {
                    "type": r["type"],
                    "account": r["account"],
                    "amount": r["amount"],  # 分
                    "description": r.get("description", "分账"),
                }
                for r in order.receivers
            ],
            "unfreeze_unsplit": order.unfreeze_unsplit,
        }

        if self._mock:
            return {
                "ok": True,
                "out_order_no": order.out_order_no,
                "transaction_id": order.transaction_id,
                "order_id": f"wx_ps_{uuid.uuid4().hex[:16]}",
                "state": "FINISHED",
                "mock": True,
            }

        return await self._request("POST", "/v3/profitsharing/orders", body)

    # ── 查询分账结果 ───────────────────────────────────────────────

    async def query_order(self, out_order_no: str, transaction_id: str) -> dict:
        """GET /v3/profitsharing/orders/{out_order_no}?transaction_id={transaction_id}"""
        if self._mock:
            return {
                "out_order_no": out_order_no,
                "transaction_id": transaction_id,
                "state": "FINISHED",
                "receivers": [],
                "mock": True,
            }

        return await self._request(
            "GET",
            f"/v3/profitsharing/orders/{out_order_no}",
            params={"transaction_id": transaction_id},
        )

    async def query_detail(self, out_order_no: str, transaction_id: str) -> dict:
        """GET /v3/profitsharing/orders/{out_order_no}/detail?transaction_id=..."""
        if self._mock:
            return {
                "out_order_no": out_order_no,
                "transaction_id": transaction_id,
                "receivers": [],
                "mock": True,
            }

        return await self._request(
            "GET",
            f"/v3/profitsharing/orders/{out_order_no}/detail",
            params={"transaction_id": transaction_id},
        )

    # ── 分账回调验签 ───────────────────────────────────────────────

    async def verify_notification(self, headers: dict, body: bytes) -> dict:
        """验证微信分账回调通知（复用 WechatPayService.verify_callback）。

        微信分账回调使用相同的 V3 签名格式（WECHATPAY2-SHA256-RSA2048 + 平台证书）。
        """
        try:
            payload = await self._svc.verify_callback(headers, body)
            logger.info(
                "profitsharing_callback_verified",
                out_order_no=payload.get("out_order_no", ""),
            )
            return payload.raw if hasattr(payload, 'raw') else payload
        except Exception as exc:
            logger.error(
                "profitsharing_callback_verify_failed",
                error=str(exc),
                exc_info=True,
            )
            raise

    # ── 内部 ────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """通过 WechatPayService 签名体系发送请求"""
        import httpx

        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30))

        url = f"{_BASE_URL}{path}"
        body_bytes = json.dumps(data).encode() if data else b""

        # 复用 wechat_pay 的签名生成
        auth_header = self._svc._build_authorization(
            method, path, body_bytes
        ) if hasattr(self._svc, '_build_authorization') else ""

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "TunxiangOS/4.0",
        }

        resp = await self._http.request(
            method=method,
            url=url,
            headers=headers,
            content=body_bytes,
            params=params,
        )

        if resp.status_code >= 400:
            logger.error(
                "profitsharing_api_error",
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise RuntimeError(
                f"微信分账 API 错误 {resp.status_code}: {resp.text[:300]}"
            )

        return resp.json()


# ── API 适配器：桥接 SplitEngine → 微信分账 ─────────────────────────


class SplitChannelAdapter:
    """分账通道适配器 — 连接 tx-finance SplitEngine 和微信/支付宝分账 API。

    职责：
      1. 接收 SplitEngine 生成的 profit_split_records
      2. 转换为微信/支付宝分账 receiver 格式
      3. 调用通道 API 创建分账订单
      4. 处理回调结果，更新 profit_split_records 状态
      5. 失败重试 + 差错标记
    """

    def __init__(self, wechat_ps: Optional[WechatProfitSharingService] = None):
        self._wechat = wechat_ps
        self._init_failed = wechat_ps is None

    async def ensure_initialized(self):
        """延迟初始化（避免 import 时触发环境变量检查）"""
        if self._wechat is None:
            try:
                self._wechat = WechatProfitSharingService()
                self._init_failed = False
            except RuntimeError as exc:
                logger.warning("split_channel_adapter_init_failed", error=str(exc))
                self._init_failed = True

    async def submit_split_to_channel(
        self,
        channel: str,  # "wechat" | "alipay"
        transaction_id: str,  # 微信/支付宝支付订单号
        out_order_no: str,
        receivers: List[Dict[str, Any]],  # [{type, account, amount, description}]
    ) -> dict:
        """向支付通道提交分账订单"""
        await self.ensure_initialized()

        if self._init_failed:
            return {
                "ok": False,
                "error": "CHANNEL_NOT_AVAILABLE",
                "message": "分账通道未初始化，请检查 WECHAT_PAY_* 环境变量",
            }

        if channel == "wechat" and self._wechat is not None:
            order = ProfitSharingOrder(
                out_order_no=out_order_no,
                transaction_id=transaction_id,
                receivers=receivers,
            )
            return await self._wechat.create_order(order)

        return {
            "ok": False,
            "error": "UNSUPPORTED_CHANNEL",
            "message": f"不支持的分账通道: {channel}",
        }

    async def query_split_result(
        self,
        channel: str,
        out_order_no: str,
        transaction_id: str,
    ) -> dict:
        """查询分账结果"""
        await self.ensure_initialized()

        if self._init_failed or self._wechat is None:
            return {"ok": False, "error": "CHANNEL_NOT_AVAILABLE"}

        if channel == "wechat":
            return await self._wechat.query_order(out_order_no, transaction_id)

        return {"ok": False, "error": "UNSUPPORTED_CHANNEL"}
