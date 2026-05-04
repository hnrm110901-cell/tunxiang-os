"""test_payment_routes.py — 支付核心 API 路由测试

覆盖端点：
  POST /api/v1/pay/create          — 发起支付
  POST /api/v1/pay/query           — 查询支付状态
  POST /api/v1/pay/refund          — 退款
  POST /api/v1/pay/close           — 关闭未支付交易
  POST /api/v1/pay/split           — 多方式拆单支付
  GET  /api/v1/pay/daily-summary   — 当日支付汇总

测试策略：
  所有路由通过 from ..deps import get_payment_service 惰性获取服务实例。
  通过 patch("src.deps.get_payment_service", mock_get_payment_service)
  注入 mock service（mock_get_payment_service 为 async 函数）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from src.channels.base import PayMethod, PayStatus, PaymentResult, RefundResult
from src.orchestrator.split_pay import SplitPayResult
from src.tests.conftest import TENANT_HEADERS

# ─── 辅助 ────────────────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


# ─── 创建支付 ─────────────────────────────────────────────────────────────────


class TestCreatePayment:
    """POST /api/v1/pay/create"""

    CREATE_URL = "/api/v1/pay/create"

    @pytest.mark.asyncio
    async def test_create_payment_wechat(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """微信支付创建成功 → ok=True, payment_id 非空"""
        mock_payment_service.create_payment.return_value = PaymentResult(
            payment_id="pay_wx_001", status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT, amount_fen=8800, trade_no="txn_wx_001",
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-001",
                    "amount_fen": 8800,
                    "method": "wechat",
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["payment_id"] == "pay_wx_001"
        assert data["data"]["amount_fen"] == 8800
        assert data["data"]["method"] == "wechat"

    @pytest.mark.asyncio
    async def test_create_payment_cash(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """现金支付创建成功 → method=cash, status=success"""
        mock_payment_service.create_payment.return_value = PaymentResult(
            payment_id="pay_cash_001", status=PayStatus.SUCCESS,
            method=PayMethod.CASH, amount_fen=5000,
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-002",
                    "amount_fen": 5000,
                    "method": "cash",
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["method"] == "cash"

    @pytest.mark.asyncio
    async def test_create_payment_missing_amount(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """缺少 amount_fen → HTTP 422"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={"store_id": "store-001", "order_id": "order-003", "method": "wechat"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_payment_zero_amount(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """amount_fen=0（gt=0 校验）→ HTTP 422"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-004",
                    "amount_fen": 0,
                    "method": "wechat",
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_payment_missing_tenant(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """缺少 X-Tenant-ID header → HTTP 422（FastAPI Header 校验）"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-005",
                    "amount_fen": 1000,
                    "method": "wechat",
                },
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_payment_unknown_method(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """不支持的支付方式 → HTTP 422（Pydantic 枚举校验）"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CREATE_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-006",
                    "amount_fen": 1000,
                    "method": "bitcoin",
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422


# ─── 查询支付 ─────────────────────────────────────────────────────────────────


class TestQueryPayment:
    """POST /api/v1/pay/query"""

    QUERY_URL = "/api/v1/pay/query"

    @pytest.mark.asyncio
    async def test_query_payment_found(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """查询已存在的支付 → ok=True, status=success"""
        mock_payment_service.query_payment.return_value = PaymentResult(
            payment_id="pay_wx_001", status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT, amount_fen=8800, trade_no="txn_wx_001",
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.QUERY_URL,
                json={"payment_id": "pay_wx_001"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["payment_id"] == "pay_wx_001"
        assert data["data"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_query_payment_not_found(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """不存在的 payment_id → 返回 PENDING 状态"""
        mock_payment_service.query_payment.return_value = PaymentResult(
            payment_id="nonexistent", status=PayStatus.PENDING,
            method=PayMethod.WECHAT, amount_fen=0,
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.QUERY_URL,
                json={"payment_id": "nonexistent"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_query_payment_with_trade_no(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """携带 trade_no 查询 → 调用 query_payment 时传递 trade_no"""
        mock_payment_service.query_payment.return_value = PaymentResult(
            payment_id="pay_wx_001", status=PayStatus.SUCCESS,
            method=PayMethod.WECHAT, amount_fen=8800, trade_no="txn_external_001",
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.QUERY_URL,
                json={"payment_id": "pay_wx_001", "trade_no": "txn_external_001"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["trade_no"] == "txn_external_001"


# ─── 退款 ─────────────────────────────────────────────────────────────────────


class TestRefund:
    """POST /api/v1/pay/refund"""

    REFUND_URL = "/api/v1/pay/refund"

    @pytest.mark.asyncio
    async def test_refund_full(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """全额退款 → refund_id 非空, status=success"""
        mock_payment_service.refund.return_value = RefundResult(
            refund_id="REF_mock_001", payment_id="pay_wx_001",
            status="success", amount_fen=8800,
            refund_trade_no="REF_txn_001",
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.REFUND_URL,
                json={"payment_id": "pay_wx_001", "refund_amount_fen": 8800, "reason": "全额退款"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["refund_id"] == "REF_mock_001"
        assert data["data"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_refund_partial(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """部分退款 → amount_fen=500"""
        mock_payment_service.refund.return_value = RefundResult(
            refund_id="REF_partial_001", payment_id="pay_wx_001",
            status="success", amount_fen=500,
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.REFUND_URL,
                json={"payment_id": "pay_wx_001", "refund_amount_fen": 500, "reason": "部分退款"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["amount_fen"] == 500

    @pytest.mark.asyncio
    async def test_refund_zero_amount(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """退款金额为 0 → HTTP 422（gt=0 校验）"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.REFUND_URL,
                json={"payment_id": "pay_wx_001", "refund_amount_fen": 0},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422


# ─── 关闭支付 ─────────────────────────────────────────────────────────────────


class TestClosePayment:
    """POST /api/v1/pay/close"""

    CLOSE_URL = "/api/v1/pay/close"

    @pytest.mark.asyncio
    async def test_close_payment(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """关闭未支付交易 → closed=True"""
        mock_payment_service.close_payment.return_value = True
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.CLOSE_URL,
                json={"payment_id": "pay_wx_001"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["closed"] is True


# ─── 拆单支付 ─────────────────────────────────────────────────────────────────


class TestSplitPayment:
    """POST /api/v1/pay/split"""

    SPLIT_URL = "/api/v1/pay/split"

    @pytest.mark.asyncio
    async def test_split_payment(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """拆单支付成功 → success=True, total_fen=8000"""
        mock_payment_service.split_payment.return_value = SplitPayResult(
            success=True, total_fen=8000, entries=[],
        )
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.SPLIT_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-split-001",
                    "entries": [
                        {"method": "member_balance", "amount_fen": 5000},
                        {"method": "wechat", "amount_fen": 3000},
                    ],
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["success"] is True
        assert data["data"]["total_fen"] == 8000

    @pytest.mark.asyncio
    async def test_split_payment_empty_entries(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """空拆单项 → HTTP 422（min_length=1 校验）"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.SPLIT_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-split-002",
                    "entries": [],
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_split_payment_zero_entry(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """拆单项金额为 0 → HTTP 422（gt=0 校验）"""
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.post(
                self.SPLIT_URL,
                json={
                    "store_id": "store-001",
                    "order_id": "order-split-003",
                    "entries": [{"method": "wechat", "amount_fen": 0}],
                },
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 422


# ─── 日汇总 ───────────────────────────────────────────────────────────────────


class TestDailySummary:
    """GET /api/v1/pay/daily-summary"""

    SUMMARY_URL = "/api/v1/pay/daily-summary"

    @pytest.mark.asyncio
    async def test_daily_summary(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """当日汇总 → 按支付方式分组，含 grand_total_fen"""
        today = date.today().isoformat()
        mock_payment_service.daily_summary.return_value = {
            "date": today,
            "store_id": "store-001",
            "methods": {
                "wechat": {"count": 10, "total_fen": 50000, "fee_fen": 300},
                "cash": {"count": 5, "total_fen": 20000, "fee_fen": 0},
            },
            "grand_total_fen": 70000,
        }
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.get(
                self.SUMMARY_URL,
                params={"store_id": "store-001"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["grand_total_fen"] == 70000
        assert "wechat" in data["data"]["methods"]
        assert "cash" in data["data"]["methods"]

    @pytest.mark.asyncio
    async def test_daily_summary_empty(
        self, client: AsyncClient, mock_payment_service, mock_get_payment_service,
    ):
        """当日无记录 → grand_total_fen=0, methods 为空"""
        today = date.today().isoformat()
        mock_payment_service.daily_summary.return_value = {
            "date": today,
            "store_id": "store-999",
            "methods": {},
            "grand_total_fen": 0,
        }
        with patch("src.deps.get_payment_service", mock_get_payment_service):
            resp = await client.get(
                self.SUMMARY_URL,
                params={"store_id": "store-999"},
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["grand_total_fen"] == 0
        assert data["data"]["methods"] == {}
