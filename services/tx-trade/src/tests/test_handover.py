"""交班对账与稽核中心 — 全流程测试

覆盖场景：
1. 开始交班 → 快照班次数据
2. 录入现金清点（按面额）
3. 完成交班 → 计算差异（无差异）
4. 完成交班 → 差异超阈值自动标记
5. 班次对账 → 逐笔核对
6. 可疑交易标记 → 退款异常+折扣异常
7. 渠道核对 → 单渠道+全渠道报告
8. 现金长短款明细（长款/短款/平衡）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timezone

import pytest

# ─── 模拟数据库对象（脱离真实PG） ───


def _make_uuid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _make_uuid()
STORE_ID = _make_uuid()
CASHIER_ID = "C001"


class FakeRow:
    """模拟 SQLAlchemy ORM 行"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    """模拟 AsyncSession 用于纯逻辑测试"""

    def __init__(self):
        self.added = []
        self.deleted = []
        self.executed = []
        self.flushed = False
        self._execute_results = []
        self._execute_index = 0

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def execute(self, stmt, *args, **kwargs):
        if self._execute_index < len(self._execute_results):
            result = self._execute_results[self._execute_index]
            self._execute_index += 1
            return result
        return FakeResult()

    async def flush(self):
        self.flushed = True

    async def commit(self):
        pass

    def set_results(self, results: list):
        self._execute_results = results
        self._execute_index = 0


# ─── Test: ShiftHandoverService ───


class TestShiftHandoverService:
    """交班服务测试"""

    @pytest.mark.asyncio
    async def test_start_handover(self):
        """场景1: 开始交班 — 创建记录+快照"""
        db = FakeSession()
        # _snapshot_shift_data 查两次: orders, payments（无订单时不查退款）
        db.set_results(
            [
                FakeResult(rows=[]),  # orders query
            ]
        )

        from services.shift_handover_service import ShiftHandoverService

        svc = ShiftHandoverService(db, TENANT_ID)
        result = await svc.start_handover(CASHIER_ID, STORE_ID)

        assert result["cashier_id"] == CASHIER_ID
        assert result["store_id"] == STORE_ID
        assert result["status"] == "started"
        assert "handover_id" in result
        assert result["shift_snapshot"]["total_orders"] == 0
        assert len(db.added) == 1  # ShiftHandover record

    @pytest.mark.asyncio
    async def test_record_cash_count(self):
        """场景2: 录入现金清点 — 按面额计算"""
        db = FakeSession()

        handover_id = _make_uuid()
        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=5,
            revenue_fen=50000,
            cash_on_hand_fen=None,
            pending_issues={
                "status": "started",
                "shift_snapshot": {"cash_fen": 20000},
            },
            notes=None,
        )
        db.set_results(
            [
                FakeResult(scalar=fake_handover),  # _get_handover
            ]
        )

        from services.shift_handover_service import ShiftHandoverService

        svc = ShiftHandoverService(db, TENANT_ID)
        result = await svc.record_cash_count(
            handover_id,
            {"100": 2, "50": 1, "10": 3},  # 200 + 50 + 30 = 280元 = 28000分
        )

        assert result["cash_actual_fen"] == 28000
        assert result["status"] == "counting"
        assert "denomination_detail" in result
        assert result["denomination_detail"]["100"]["count"] == 2
        assert result["denomination_detail"]["100"]["subtotal_fen"] == 20000

    @pytest.mark.asyncio
    async def test_finalize_handover_no_variance(self):
        """场景3: 完成交班 — 无差异"""
        db = FakeSession()
        handover_id = _make_uuid()

        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=10,
            revenue_fen=80000,
            cash_on_hand_fen=20000,  # 实际清点 = 200元
            pending_issues={
                "status": "counting",
                "shift_snapshot": {"cash_fen": 20000},  # 系统应有 = 200元
                "cash_count": {"actual_fen": 20000},
                "finalized": False,
            },
            notes=None,
        )
        db.set_results([FakeResult(scalar=fake_handover)])

        from services.shift_handover_service import ShiftHandoverService

        svc = ShiftHandoverService(db, TENANT_ID)
        result = await svc.finalize_handover(handover_id)

        assert result["variance_fen"] == 0
        assert result["variance_alert"] is False
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_finalize_handover_variance_alert(self):
        """场景4: 完成交班 — 差异超阈值(100元)自动标记"""
        db = FakeSession()
        handover_id = _make_uuid()

        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=10,
            revenue_fen=80000,
            cash_on_hand_fen=5000,  # 实际50元
            pending_issues={
                "status": "counting",
                "shift_snapshot": {"cash_fen": 20000},  # 系统应有200元
                "cash_count": {"actual_fen": 5000},
                "finalized": False,
            },
            notes=None,
        )
        db.set_results([FakeResult(scalar=fake_handover)])

        from services.shift_handover_service import ShiftHandoverService

        svc = ShiftHandoverService(db, TENANT_ID)
        result = await svc.finalize_handover(handover_id)

        assert result["variance_fen"] == -15000  # 短款150元
        assert result["variance_alert"] is True
        assert result["status"] == "variance_alert"


class TestShiftReconciliation:
    """班次对账测试"""

    @pytest.mark.asyncio
    async def test_reconcile_shift_with_match(self):
        """场景5: 逐笔核对 — 有matched和unmatched"""
        db = FakeSession()
        handover_id = _make_uuid()
        order_id_1 = uuid.uuid4()
        order_id_2 = uuid.uuid4()

        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=2,
            revenue_fen=30000,
            cash_on_hand_fen=None,
            pending_issues={"status": "started", "shift_snapshot": {}},
            notes=None,
        )

        # 模拟支付记录：1笔有trade_no(matched), 1笔无trade_no(unmatched)
        fake_payment_matched = FakeRow(
            id=uuid.uuid4(),
            payment_no="PAY001",
            order_id=order_id_1,
            method="wechat",
            amount_fen=15000,
            trade_no="WX123456",
            paid_at=datetime.now(timezone.utc),
            status="paid",
        )
        fake_payment_unmatched = FakeRow(
            id=uuid.uuid4(),
            payment_no="PAY002",
            order_id=order_id_2,
            method="alipay",
            amount_fen=15000,
            trade_no=None,
            paid_at=datetime.now(timezone.utc),
            status="paid",
        )

        db.set_results(
            [
                FakeResult(scalar=fake_handover),  # _get_handover
                FakeResult(rows=[(order_id_1,), (order_id_2,)]),  # _get_shift_order_ids
                FakeResult(rows=[fake_payment_matched, fake_payment_unmatched]),  # payments
            ]
        )

        from services.shift_reconciliation import ShiftReconciliationService

        svc = ShiftReconciliationService(db, TENANT_ID)
        result = await svc.reconcile_shift(handover_id)

        assert result["matched_count"] == 1
        assert result["unmatched_count"] == 1
        assert len(result["unmatched_items"]) == 1
        assert result["unmatched_items"][0]["method"] == "alipay"

    @pytest.mark.asyncio
    async def test_flag_suspicious_transactions(self):
        """场景6: 可疑交易标记 — 退款异常+折扣异常"""
        db = FakeSession()
        handover_id = _make_uuid()
        order_id = uuid.uuid4()

        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=1,
            revenue_fen=10000,
            cash_on_hand_fen=None,
            pending_issues={"status": "started", "shift_snapshot": {}},
            notes=None,
        )

        # 退款：退了订单金额的80%（超过50%阈值）
        fake_refund = FakeRow(
            id=uuid.uuid4(),
            order_id=order_id,
            amount_fen=8000,
            reason="顾客投诉",
        )

        # 对应订单
        fake_order = FakeRow(
            id=order_id,
            order_no="TX20260327001",
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            status="completed",
            total_amount_fen=10000,
            discount_amount_fen=4000,  # 40%折扣 > 30%阈值
            final_amount_fen=10000,
            waiter_id=CASHIER_ID,
        )

        db.set_results(
            [
                FakeResult(scalar=fake_handover),  # _get_handover
                FakeResult(rows=[(order_id,)]),  # _get_shift_order_ids
                FakeResult(rows=[fake_refund]),  # refunds
                FakeResult(scalar=fake_order),  # order for refund check
                FakeResult(rows=[fake_order]),  # orders for discount check
                FakeResult(rows=[]),  # large cash payments
            ]
        )

        from services.shift_reconciliation import ShiftReconciliationService

        svc = ShiftReconciliationService(db, TENANT_ID)
        result = await svc.flag_suspicious_transactions(handover_id)

        assert result["suspicious_count"] >= 2
        types = [s["type"] for s in result["suspicious_items"]]
        assert "refund_anomaly" in types
        assert "discount_anomaly" in types


class TestChannelVerify:
    """渠道核对测试"""

    @pytest.mark.asyncio
    async def test_verify_wechat_channel(self):
        """场景7: 微信渠道核对"""
        db = FakeSession()
        order_id = uuid.uuid4()

        fake_payment = FakeRow(
            id=uuid.uuid4(),
            payment_no="PAY001",
            order_id=order_id,
            method="wechat",
            amount_fen=15000,
            trade_no="WX123456",
            paid_at=datetime.now(timezone.utc),
            status="paid",
        )

        db.set_results(
            [
                FakeResult(rows=[(order_id,)]),  # order_ids
                FakeResult(rows=[fake_payment]),  # wechat payments
            ]
        )

        from services.channel_verify import ChannelVerifyService

        svc = ChannelVerifyService(db, TENANT_ID)
        result = await svc.verify_wechat_payments(STORE_ID, "2026-03-27")

        assert result["channel"] == "wechat"
        assert result["system_total_fen"] == 15000
        assert result["pos_total_fen"] == 15000  # has trade_no → matched
        assert result["variance_fen"] == 0
        assert result["match_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_generate_channel_report(self):
        """场景8: 全渠道对账报告"""
        db = FakeSession()

        # 每个渠道查询需要2次execute: order_ids + payments
        # 5个渠道 = 10次
        for _ in range(5):
            db._execute_results.append(FakeResult(rows=[]))  # no orders
            db._execute_results.append(FakeResult(rows=[]))  # no payments

        from services.channel_verify import ChannelVerifyService

        svc = ChannelVerifyService(db, TENANT_ID)
        result = await svc.generate_channel_report(STORE_ID, "2026-03-27")

        assert "channels" in result
        assert len(result["channels"]) == 5
        assert "summary" in result
        assert result["summary"]["overall_match_rate"] == 1.0
        channel_names = [c["name"] for c in result["channels"]]
        assert "wechat" in channel_names
        assert "alipay" in channel_names
        assert "cash" in channel_names


class TestCashVarianceDetail:
    """现金长短款明细测试"""

    @pytest.mark.asyncio
    async def test_cash_surplus(self):
        """场景9: 现金长款"""
        db = FakeSession()
        handover_id = _make_uuid()

        fake_handover = FakeRow(
            id=uuid.UUID(handover_id),
            tenant_id=uuid.UUID(TENANT_ID),
            store_id=uuid.UUID(STORE_ID),
            from_employee_id=CASHIER_ID,
            to_employee_id="",
            orders_count=5,
            revenue_fen=50000,
            cash_on_hand_fen=25000,  # 实际250元
            pending_issues={
                "status": "completed",
                "shift_snapshot": {"cash_fen": 20000},  # 应有200元
                "cash_count": {
                    "denomination_detail": {"100": {"count": 2, "subtotal_fen": 20000}},
                    "counted_at": "2026-03-27T10:00:00+00:00",
                },
                "variance": {
                    "cash_expected_fen": 20000,
                    "cash_actual_fen": 25000,
                    "variance_fen": 5000,
                },
            },
            notes=None,
        )
        db.set_results([FakeResult(scalar=fake_handover)])

        from services.shift_reconciliation import ShiftReconciliationService

        svc = ShiftReconciliationService(db, TENANT_ID)
        result = await svc.get_cash_variance_detail(handover_id)

        assert result["variance_fen"] == 5000
        assert result["variance_type"] == "surplus"
        assert result["variance_alert"] is False  # 50元 < 100元阈值
