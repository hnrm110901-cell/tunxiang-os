"""tx-pay 健康检查冒烟测试 [Tier1]

P0-1 端口统一（8016）后的最小可用性验证：
  - /health 端点返回 200 + ok=True + service=tx-pay
  - 防止后续重构再次出现端口/路由/依赖回归

测试不依赖外部服务（DB/Redis/支付渠道），仅校验 ASGI 应用可装配且 health 路由可达。
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 关闭 lifespan 中真实渠道初始化的副作用（callback_routes 走 mock 验签）
    os.environ.setdefault("TX_PAY_MOCK_MODE", "true")
    os.environ.setdefault("PAY_NOTIFY_BASE_URL", "http://localhost:8016")

    from services.tx_pay.src.main import app

    # 不进入 lifespan（不需要全局 ChannelRegistry/RoutingEngine 即可校验 health）
    return TestClient(app, raise_server_exceptions=True)


def test_health_endpoint_returns_200(client: TestClient) -> None:
    """tx-pay /health 必须返回 200 + 标准响应包络。"""
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["service"] == "tx-pay"
    assert "version" in body["data"]
