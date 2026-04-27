"""tx-pay 客户端 — tx-trade 通过此客户端调用支付中枢

渐进迁移策略（Strangler Fig）：
  Phase 1（当前）：tx-trade 保留原有 PaymentGateway，同时提供 TxPayClient
                   新代码使用 TxPayClient，旧代码继续走 PaymentGateway
  Phase 2：逐步将 PaymentGateway 的调用方切换到 TxPayClient
  Phase 3：移除 PaymentGateway、ShouqianbaClient、LakalaClient

环境变量：
  TX_PAY_URL — tx-pay 服务地址（默认 http://localhost:8013）
  TX_PAY_ENABLED — 是否启用 tx-pay 桥接（默认 false，渐进开启）
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

_TX_PAY_URL = os.getenv("TX_PAY_URL", "http://localhost:8013")
_TX_PAY_ENABLED = os.getenv("TX_PAY_ENABLED", "false").lower() in ("true", "1", "yes")

# 连接池（模块级单例）
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=_TX_PAY_URL,
            timeout=httpx.Timeout(connect=3, read=15, write=5, pool=3),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _client


def is_enabled() -> bool:
    """检查 tx-pay 桥接是否启用"""
    return _TX_PAY_ENABLED


class TxPayClient:
    """tx-pay 支付中枢客户端

    使用方式：
        client = TxPayClient(tenant_id="...")
        result = await client.create_payment(
            store_id="...", order_id="...", amount_fen=8800, method="wechat",
        )
    """

    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id
        self._headers = {"X-Tenant-ID": tenant_id}

    async def create_payment(
        self,
        store_id: str,
        order_id: str,
        amount_fen: int,
        method: str,
        trade_type: str = "b2c",
        auth_code: Optional[str] = None,
        openid: Optional[str] = None,
        description: str = "",
        idempotency_key: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """发起支付（委托 tx-pay）"""
        resp = await _get_client().post(
            "/api/v1/pay/create",
            json={
                "store_id": store_id,
                "order_id": order_id,
                "amount_fen": amount_fen,
                "method": method,
                "trade_type": trade_type,
                "auth_code": auth_code,
                "openid": openid,
                "description": description,
                "idempotency_key": idempotency_key,
                "metadata": metadata or {},
            },
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def query_payment(self, payment_id: str) -> dict:
        """查询支付状态"""
        resp = await _get_client().post(
            "/api/v1/pay/query",
            json={"payment_id": payment_id},
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def refund(
        self,
        payment_id: str,
        refund_amount_fen: int,
        reason: str = "",
    ) -> dict:
        """退款"""
        resp = await _get_client().post(
            "/api/v1/pay/refund",
            json={
                "payment_id": payment_id,
                "refund_amount_fen": refund_amount_fen,
                "reason": reason,
            },
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def split_payment(
        self,
        store_id: str,
        order_id: str,
        entries: list[dict],
    ) -> dict:
        """多方式拆单支付"""
        resp = await _get_client().post(
            "/api/v1/pay/split",
            json={
                "store_id": store_id,
                "order_id": order_id,
                "entries": entries,
            },
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def daily_summary(
        self,
        store_id: str,
        summary_date: Optional[str] = None,
    ) -> dict:
        """当日支付汇总"""
        params = {"store_id": store_id}
        if summary_date:
            params["summary_date"] = summary_date
        resp = await _get_client().get(
            "/api/v1/pay/daily-summary",
            params=params,
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    async def close(self, payment_id: str) -> bool:
        """关闭未支付交易"""
        resp = await _get_client().post(
            "/api/v1/pay/close",
            json={"payment_id": payment_id},
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("closed", False)
