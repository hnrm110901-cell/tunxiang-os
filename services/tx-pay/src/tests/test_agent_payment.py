"""test_agent_payment.py — Agent 支付 API 路由测试

覆盖端点：
  POST /api/v1/pay/agent/prepare     — Agent 准备支付（不扣款）
  POST /api/v1/pay/agent/confirm     — 人类确认后执行支付
  POST /api/v1/pay/agent/reject      — 人类拒绝 Agent 发起的支付
  GET  /api/v1/pay/agent/pending     — 列出待确认的 Agent 支付

测试策略：
  - 通过 agent_routes.set_protocol() 注入真实的 AgentPaymentProtocol 实例
  - payment_service mock 由上层 fixture 提供
  - HTTP 层验证请求/响应格式

注意：
  - agent_routes 中的 prepare/confirm/reject 不做 try/except，
    ValueError 会传播为 FastAPI 500 错误（当前设计）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api import agent_routes
from src.channels.base import PayMethod, PayStatus, PaymentResult
from src.protocols.agent_payment import AgentPaymentProtocol
from src.tests.conftest import TENANT_HEADERS


@pytest.fixture(autouse=True)
def setup_protocol(mock_payment_service: AsyncMock):
    """每个测试前注入 AgentPaymentProtocol 实例"""
    protocol = AgentPaymentProtocol(payment_service=mock_payment_service)
    agent_routes.set_protocol(protocol)
    yield
    # 清理，避免跨测试污染
    agent_routes._protocol = None


class TestAgentPrepare:
    """POST /api/v1/pay/agent/prepare"""

    PREPARE_URL = "/api/v1/pay/agent/prepare"

    @pytest.mark.asyncio
    async def test_agent_prepare_success(self, agent_client: AsyncClient):
        """Agent 准备支付 → prepared_id 非空, status=prepared"""
        resp = await agent_client.post(
            self.PREPARE_URL,
            json={
                "order_id": "order-agent-001",
                "amount_fen": 5000,
                "method": "wechat",
                "reason": "顾客余额不足，建议更换支付方式",
                "confidence": 0.85,
                "store_id": "store-001",
                "metadata": {"agent_id": "discount_guardian"},
            },
            headers=TENANT_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["prepared_id"].startswith("AGENT_")
        assert data["data"]["status"] == "prepared"
        assert data["data"]["amount_fen"] == 5000
        assert data["data"]["method"] == "wechat"

    @pytest.mark.asyncio
    async def test_agent_prepare_over_limit(self, agent_client: AsyncClient):
        """超过 Agent 单笔限额（100000 分=1000 元）→ ValueError（路由未捕获，httpx 传播）"""
        with pytest.raises(ValueError, match="Agent 单笔限额"):
            await agent_client.post(
                self.PREPARE_URL,
                json={
                    "order_id": "order-agent-over",
                    "amount_fen": 200_000,  # 2000 元，超限
                    "method": "wechat",
                    "confidence": 0.9,
                },
                headers=TENANT_HEADERS,
            )

    @pytest.mark.asyncio
    async def test_agent_prepare_zero_amount(self, agent_client: AsyncClient):
        """amount_fen=0 → HTTP 422"""
        resp = await agent_client.post(
            self.PREPARE_URL,
            json={
                "order_id": "order-agent-zero",
                "amount_fen": 0,
                "method": "wechat",
            },
            headers=TENANT_HEADERS,
        )

        assert resp.status_code == 422


class TestAgentConfirm:
    """POST /api/v1/pay/agent/confirm"""

    CONFIRM_URL = "/api/v1/pay/agent/confirm"

    @pytest.mark.asyncio
    async def test_agent_confirm_success(
        self, agent_client: AsyncClient, mock_payment_service: AsyncMock,
    ):
        """人类确认 → 调用 create_payment → status=completed"""
        # 先 prepare
        mock_payment_service.create_payment.return_value = PaymentResult(
            payment_id="pay_agent_001", status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT, amount_fen=5000, trade_no="txn_agent_001",
        )

        prepare_resp = await agent_client.post(
            "/api/v1/pay/agent/prepare",
            json={
                "order_id": "order-agent-confirm",
                "amount_fen": 5000,
                "method": "wechat",
                "reason": "test confirm",
                "confidence": 0.8,
                "store_id": "store-001",
                "metadata": {"agent_id": "test_agent"},
            },
            headers=TENANT_HEADERS,
        )

        prepared_id = prepare_resp.json()["data"]["prepared_id"]

        # confirm
        confirm_resp = await agent_client.post(
            self.CONFIRM_URL,
            json={
                "prepared_id": prepared_id,
                "operator_id": "op-001",
                "auth_type": "biometric",
                "auth_token": "bio_token_001",
            },
            headers=TENANT_HEADERS,
        )

        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data["ok"] is True
        mock_payment_service.create_payment.assert_awaited()

    @pytest.mark.asyncio
    async def test_agent_confirm_not_found(self, agent_client: AsyncClient):
        """确认不存在的 prepared_id → ValueError（路由未捕获，httpx 传播）"""
        with pytest.raises(ValueError, match="未找到准备中的支付"):
            await agent_client.post(
                self.CONFIRM_URL,
                json={
                    "prepared_id": "AGENT_NONEXISTENT",
                    "operator_id": "op-001",
                    "auth_type": "biometric",
                },
                headers=TENANT_HEADERS,
            )

    @pytest.mark.asyncio
    async def test_agent_confirm_already_rejected(self, agent_client: AsyncClient):
        """确认已拒绝的支付 → ValueError（路由未捕获，httpx 传播）"""
        # prepare
        prepare_resp = await agent_client.post(
            "/api/v1/pay/agent/prepare",
            json={
                "order_id": "order-agent-rejected",
                "amount_fen": 3000,
                "method": "cash",
                "reason": "test double confirm",
                "confidence": 0.7,
                "store_id": "store-001",
                "metadata": {"agent_id": "test_agent"},
            },
            headers=TENANT_HEADERS,
        )
        prepared_id = prepare_resp.json()["data"]["prepared_id"]

        # reject
        await agent_client.post(
            "/api/v1/pay/agent/reject",
            json={"prepared_id": prepared_id, "reason": "顾客选择其他方式"},
            headers=TENANT_HEADERS,
        )

        # confirm after reject → should fail
        with pytest.raises(ValueError, match="支付状态不正确"):
            await agent_client.post(
                self.CONFIRM_URL,
                json={
                    "prepared_id": prepared_id,
                    "operator_id": "op-001",
                    "auth_type": "biometric",
                },
                headers=TENANT_HEADERS,
            )


class TestAgentReject:
    """POST /api/v1/pay/agent/reject"""

    REJECT_URL = "/api/v1/pay/agent/reject"

    @pytest.mark.asyncio
    async def test_agent_reject(self, agent_client: AsyncClient):
        """拒绝 Agent 支付 → ok=True, message=已拒绝"""
        prepare_resp = await agent_client.post(
            "/api/v1/pay/agent/prepare",
            json={
                "order_id": "order-agent-reject-test",
                "amount_fen": 2000,
                "method": "wechat",
                "reason": "test reject",
                "confidence": 0.6,
                "store_id": "store-001",
                "metadata": {"agent_id": "test_agent"},
            },
            headers=TENANT_HEADERS,
        )
        prepared_id = prepare_resp.json()["data"]["prepared_id"]

        resp = await agent_client.post(
            self.REJECT_URL,
            json={"prepared_id": prepared_id, "reason": "顾客选择现金支付"},
            headers=TENANT_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["message"] == "已拒绝"

    @pytest.mark.asyncio
    async def test_agent_reject_not_found(self, agent_client: AsyncClient):
        """拒绝不存在的 prepared_id → ValueError（路由未捕获，httpx 传播）"""
        with pytest.raises(ValueError, match="未找到准备中的支付"):
            await agent_client.post(
                self.REJECT_URL,
                json={"prepared_id": "AGENT_NO_EXIST", "reason": "测试"},
                headers=TENANT_HEADERS,
            )


class TestAgentPending:
    """GET /api/v1/pay/agent/pending"""

    PENDING_URL = "/api/v1/pay/agent/pending"

    @pytest.mark.asyncio
    async def test_agent_pending_list(self, agent_client: AsyncClient):
        """列出待确认的 Agent 支付 → 返回 pending 列表"""
        for i in range(2):
            await agent_client.post(
                "/api/v1/pay/agent/prepare",
                json={
                    "order_id": f"order-pending-{i}",
                    "amount_fen": 3000,
                    "method": "wechat",
                    "reason": f"test pending {i}",
                    "confidence": 0.7,
                    "store_id": "store-001",
                    "metadata": {"agent_id": "test_agent"},
                },
                headers=TENANT_HEADERS,
            )

        resp = await agent_client.get(
            self.PENDING_URL,
            params={},
            headers=TENANT_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]) >= 2

    @pytest.mark.asyncio
    async def test_agent_pending_filter_by_agent(self, agent_client: AsyncClient):
        """按 agent_id 过滤 → 只返回该 Agent 的待确认支付"""
        await agent_client.post(
            "/api/v1/pay/agent/prepare",
            json={
                "order_id": "order-filter-1",
                "amount_fen": 1000,
                "method": "cash",
                "reason": "filter test",
                "confidence": 0.5,
                "store_id": "store-001",
                "metadata": {"agent_id": "filter_agent"},
            },
            headers=TENANT_HEADERS,
        )

        resp = await agent_client.get(
            self.PENDING_URL,
            params={"agent_id": "filter_agent"},
            headers=TENANT_HEADERS,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["data"]) >= 1
        for item in data["data"]:
            assert item["agent_id"] == "filter_agent"
