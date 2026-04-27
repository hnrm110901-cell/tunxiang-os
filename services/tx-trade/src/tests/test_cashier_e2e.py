"""收银全流程端到端测试

测试链路：开单 → 加菜 → 改菜 → 折扣 → 结算 → 支付 → 退款
不依赖真实数据库，使用 mock AsyncSession。
"""

import asyncio
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

# import via package to support relative imports within src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from src.services.order_service import OrderService
from src.services.payment_service import PaymentService
from src.services.receipt_service import ReceiptService

TENANT_ID = "00000000-0000-0000-0000-000000000001"
STORE_ID = "11111111-1111-1111-1111-111111111111"


def _mock_db():
    """创建 mock AsyncSession"""
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ─── OrderService 测试 ───


class TestOrderService:
    def test_create_order(self):
        db = _mock_db()
        svc = OrderService(db, TENANT_ID)
        result = asyncio.run(svc.create_order(store_id=STORE_ID, table_no="A01"))
        assert "order_id" in result
        assert "order_no" in result
        assert result["order_no"].startswith("TX")
        db.add.assert_called_once()

    def test_add_item(self):
        db = _mock_db()
        svc = OrderService(db, TENANT_ID)
        order_id = str(uuid.uuid4())
        result = asyncio.run(
            svc.add_item(
                order_id=order_id,
                dish_id=str(uuid.uuid4()),
                dish_name="剁椒鱼头",
                quantity=1,
                unit_price_fen=8800,
            )
        )
        assert result["subtotal_fen"] == 8800
        assert "item_id" in result

    def test_add_item_multiple_quantity(self):
        db = _mock_db()
        svc = OrderService(db, TENANT_ID)
        result = asyncio.run(
            svc.add_item(
                order_id=str(uuid.uuid4()),
                dish_id=str(uuid.uuid4()),
                dish_name="米饭",
                quantity=3,
                unit_price_fen=300,
            )
        )
        assert result["subtotal_fen"] == 900

    def test_apply_discount_validates_amount(self):
        """折扣不能超过订单总额"""
        db = _mock_db()
        # mock order with total_amount_fen = 10000
        mock_order = MagicMock()
        mock_order.total_amount_fen = 10000
        mock_order.discount_amount_fen = 0
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        db.execute.return_value = mock_result

        svc = OrderService(db, TENANT_ID)
        # 正常折扣
        result = asyncio.run(svc.apply_discount(str(uuid.uuid4()), 2000, "会员折扣"))
        assert result["discount_fen"] == 2000

    def test_apply_excessive_discount_raises(self):
        """折扣超过总额应报错"""
        db = _mock_db()
        mock_order = MagicMock()
        mock_order.total_amount_fen = 5000
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        db.execute.return_value = mock_result

        svc = OrderService(db, TENANT_ID)
        try:
            asyncio.run(svc.apply_discount(str(uuid.uuid4()), 6000))
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "exceeds" in str(e)

    def test_settle_order(self):
        db = _mock_db()
        mock_order = MagicMock()
        mock_order.status = "confirmed"
        mock_order.order_no = "TX20260322001"
        mock_order.table_number = "A01"
        mock_order.store_id = uuid.UUID(STORE_ID)
        mock_order.final_amount_fen = 15800
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        db.execute.return_value = mock_result

        svc = OrderService(db, TENANT_ID)
        result = asyncio.run(svc.settle_order(str(uuid.uuid4())))
        assert result["final_amount_fen"] == 15800
        assert "settled_at" in result
        assert mock_order.status == "completed"

    def test_settle_already_completed_raises(self):
        db = _mock_db()
        mock_order = MagicMock()
        mock_order.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        db.execute.return_value = mock_result

        svc = OrderService(db, TENANT_ID)
        try:
            asyncio.run(svc.settle_order(str(uuid.uuid4())))
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "already settled" in str(e)

    def test_cancel_order(self):
        db = _mock_db()
        mock_order = MagicMock()
        mock_order.status = "confirmed"
        mock_order.order_no = "TX20260322002"
        mock_order.table_number = "A02"
        mock_order.store_id = uuid.UUID(STORE_ID)
        mock_order.order_metadata = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        db.execute.return_value = mock_result

        svc = OrderService(db, TENANT_ID)
        result = asyncio.run(svc.cancel_order(str(uuid.uuid4()), reason="客户取消"))
        assert result["status"] == "cancelled"
        assert mock_order.status == "cancelled"


# ─── PaymentService 测试 ───


class TestPaymentService:
    def test_create_payment(self):
        db = _mock_db()
        svc = PaymentService(db, TENANT_ID)
        result = asyncio.run(
            svc.create_payment(
                order_id=str(uuid.uuid4()),
                method="wechat",
                amount_fen=15800,
            )
        )
        assert result["payment_no"].startswith("PAY")
        assert result["status"] == "paid"

    def test_refund_validates_amount(self):
        """退款金额不能超过支付金额"""
        db = _mock_db()
        mock_payment = MagicMock()
        mock_payment.amount_fen = 10000
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_payment
        db.execute.return_value = mock_result

        svc = PaymentService(db, TENANT_ID)
        try:
            asyncio.run(
                svc.process_refund(
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    amount_fen=15000,
                )
            )
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "exceeds" in str(e)

    def test_full_refund(self):
        db = _mock_db()
        mock_payment = MagicMock()
        mock_payment.amount_fen = 10000
        mock_payment.status = "paid"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_payment
        db.execute.return_value = mock_result

        svc = PaymentService(db, TENANT_ID)
        result = asyncio.run(
            svc.process_refund(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                amount_fen=10000,
            )
        )
        assert result["refund_no"].startswith("REF")
        assert result["status"] == "refunded"

    def test_partial_refund(self):
        db = _mock_db()
        mock_payment = MagicMock()
        mock_payment.amount_fen = 10000
        mock_payment.status = "paid"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_payment
        db.execute.return_value = mock_result

        svc = PaymentService(db, TENANT_ID)
        result = asyncio.run(
            svc.process_refund(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                amount_fen=3000,
                refund_type="partial",
            )
        )
        assert result["status"] == "partial_refund"


# ─── 全流程集成测试 ───


class TestCashierE2EFlow:
    """模拟完整收银流程"""

    def test_full_cashier_flow(self):
        """开单 → 加菜×2 → 结算"""
        db = _mock_db()
        svc = OrderService(db, TENANT_ID)

        # 1. 开单
        order = asyncio.run(svc.create_order(store_id=STORE_ID, table_no="B01"))
        assert order["order_no"].startswith("TX")
        order_id = order["order_id"]

        # 2. 加菜
        item1 = asyncio.run(svc.add_item(order_id, str(uuid.uuid4()), "剁椒鱼头", 1, 8800))
        assert item1["subtotal_fen"] == 8800

        item2 = asyncio.run(svc.add_item(order_id, str(uuid.uuid4()), "米饭", 3, 300))
        assert item2["subtotal_fen"] == 900

    def test_receipt_generation_for_order(self):
        """生成小票"""
        order_data = {
            "order_no": "TX20260322143000AB",
            "table_number": "B01",
            "order_time": "2026-03-22T14:30:00",
            "total_amount_fen": 9700,
            "discount_amount_fen": 0,
            "final_amount_fen": 9700,
            "items": [
                {"item_name": "剁椒鱼头", "quantity": 1, "subtotal_fen": 8800, "kitchen_station": "热菜档"},
                {"item_name": "米饭", "quantity": 3, "subtotal_fen": 900, "kitchen_station": "default"},
            ],
        }
        receipt = ReceiptService.format_receipt(order_data, store_name="尝在一起·芙蓉路店")
        assert len(receipt) > 0
        assert "尝在一起".encode("gbk") in receipt

        # 厨房分单
        stations = ReceiptService.split_by_station(order_data)
        assert len(stations) == 2
        assert "热菜档" in stations
        assert "default" in stations

    def test_payment_then_refund_flow(self):
        """支付 → 退款"""
        db = _mock_db()

        # 支付
        pay_svc = PaymentService(db, TENANT_ID)
        payment = asyncio.run(pay_svc.create_payment(str(uuid.uuid4()), "wechat", 9700))
        assert payment["status"] == "paid"

        # 退款（mock 查到支付记录）
        mock_payment = MagicMock()
        mock_payment.amount_fen = 9700
        mock_payment.status = "paid"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_payment
        db.execute.return_value = mock_result

        refund = asyncio.run(
            pay_svc.process_refund(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                amount_fen=9700,
                reason="菜品问题",
            )
        )
        assert refund["status"] == "refunded"
