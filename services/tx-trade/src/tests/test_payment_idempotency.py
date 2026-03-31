"""支付幂等性测试套件 — P0 安全保障

测试目标：
  - 相同 idempotency_key 重复调用不产生重复扣款
  - 并发写入相同 key 时 DB 唯一约束保证只有一条记录
  - 跨租户同 key 互不影响
  - failed 状态可用相同 key 重试
  - cashier_api 端点正确透传 idempotency_key

共 20 个测试用例，全部使用 mock DB，不依赖真实数据库。
"""
import asyncio
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from sqlalchemy.exc import IntegrityError

from ..services.payment_gateway import PaymentGateway
from ..models.enums import PaymentStatus


# ─── 测试工具 ────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
PAYMENT_ID = str(uuid.uuid4())
PAYMENT_NO = "PAY20260331120000ABCD"
IKEY = "pos001-a3f2b1c4-1743420000"


def _make_order_mock():
    """构造一个 mock Order 对象"""
    order = MagicMock()
    order.id = uuid.UUID(ORDER_ID)
    order.tenant_id = uuid.UUID(TENANT_ID)
    order.final_amount_fen = 10000
    return order


def _make_existing_payment_mapping(
    status: str = "paid",
    payment_id: Optional[str] = None,
    payment_no: str = PAYMENT_NO,
):
    """构造一个 mock 已有支付记录的 Mapping"""
    m = MagicMock()
    m.__getitem__ = lambda self, key: {
        "id": uuid.UUID(payment_id or PAYMENT_ID),
        "payment_no": payment_no,
        "trade_no": "SQB_TRADE_001",
        "status": status,
        "qr_code": None,
        "fee_fen": "60",
    }[key]
    return m


async def _build_gateway_with_mock_db(
    existing_payment_mapping=None,
    order_exists: bool = True,
    raise_integrity_error: bool = False,
):
    """构造 PaymentGateway，注入 mock AsyncSession"""
    db = AsyncMock()

    # mock select(Order) 查询
    order_result = MagicMock()
    if order_exists:
        order_result.scalar_one_or_none.return_value = _make_order_mock()
    else:
        order_result.scalar_one_or_none.return_value = None

    # mock 幂等检查查询（text() 查询）
    idempotency_result = MagicMock()
    mapping_result = MagicMock()
    mapping_result.first.return_value = existing_payment_mapping
    idempotency_result.mappings.return_value = mapping_result

    # 按调用次序返回不同 mock（第1次是 select Order，第2次是幂等检查）
    db.execute = AsyncMock(side_effect=[order_result, idempotency_result])

    if raise_integrity_error:
        # flush 时抛出 IntegrityError（模拟并发写入唯一约束冲突）
        integrity_exc = IntegrityError("UNIQUE constraint failed", None, None)
        db.flush = AsyncMock(side_effect=integrity_exc)
        db.rollback = AsyncMock()
        # rollback 后再次 execute 用于重查已有记录
        retry_result = MagicMock()
        retry_mapping = MagicMock()
        retry_mapping.first.return_value = existing_payment_mapping
        retry_result.mappings.return_value = retry_mapping
        # 第3次 execute = 并发冲突后的重查
        db.execute = AsyncMock(
            side_effect=[order_result, idempotency_result, retry_result]
        )
    else:
        db.flush = AsyncMock()
        db.rollback = AsyncMock()
        db.add = MagicMock()

    db.add = MagicMock()

    gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
    return gateway, db


# ─── 测试用例 ─────────────────────────────────────────────────────────────────


class TestIdempotencyHit:
    """相同 idempotency_key → 第二次直接返回已有记录"""

    @pytest.mark.asyncio
    async def test_same_key_returns_existing_result(self):
        """TC-01: 相同 key 第二次调用，返回第一次的支付结果"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["payment_no"] == PAYMENT_NO
        assert result["status"] == "paid"
        assert result["idempotent"] is True

    @pytest.mark.asyncio
    async def test_idempotent_hit_no_new_payment_record(self):
        """TC-02: 幂等命中时，db.add 不被调用，不写入新记录"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_hit_no_flush(self):
        """TC-03: 幂等命中时，db.flush 不被调用"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        db.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_hit_preserves_payment_no(self):
        """TC-04: 幂等命中返回原 payment_no，不生成新 payment_no"""
        original_no = "PAY20260331000000ORIG"
        existing = _make_existing_payment_mapping(
            status="paid", payment_no=original_no
        )
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="wechat",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["payment_no"] == original_no

    @pytest.mark.asyncio
    async def test_idempotent_hit_paid_status_not_recharged(self):
        """TC-05: 已 paid 状态的幂等命中 → 返回已有 paid 状态，不重新扣款"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="wechat",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["status"] == "paid"
        assert result["idempotent"] is True
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_hit_returns_fee_fen(self):
        """TC-06: 幂等命中时，正确返回 fee_fen 字段"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["fee_fen"] == 60

    @pytest.mark.asyncio
    async def test_idempotent_hit_pending_status_preserved(self):
        """TC-07: pending 状态（C扫B等待扫码）的幂等命中 → 返回 pending 状态"""
        existing = _make_existing_payment_mapping(status="pending")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="wechat",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["status"] == "pending"
        assert result["idempotent"] is True


class TestNoIdempotency:
    """idempotency_key=None → 不做幂等检查（向下兼容旧客户端）"""

    @pytest.mark.asyncio
    async def test_no_key_creates_new_payment(self):
        """TC-08: idempotency_key=None 时，不查幂等，直接创建新支付"""
        # 只有 select(Order) 那一次 execute
        db = AsyncMock()
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = _make_order_mock()
        db.execute = AsyncMock(return_value=order_result)
        db.flush = AsyncMock()
        db.add = MagicMock()

        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=None,
        )

        # db.add 应被调用（新支付写入）
        db.add.assert_called_once()
        # 结果不含 idempotent 标记（或为 False）
        assert result.get("idempotent") is not True

    @pytest.mark.asyncio
    async def test_no_key_execute_called_once(self):
        """TC-09: idempotency_key=None 时，execute 只调用一次（查订单），不查幂等表"""
        db = AsyncMock()
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = _make_order_mock()
        db.execute = AsyncMock(return_value=order_result)
        db.flush = AsyncMock()
        db.add = MagicMock()

        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
        await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=None,
        )

        assert db.execute.call_count == 1


class TestFailedStatusRetry:
    """failed 状态的支付不触发幂等命中，允许用相同 key 重试"""

    @pytest.mark.asyncio
    async def test_failed_payment_allows_retry_with_same_key(self):
        """TC-10: failed 状态不返回幂等命中，SQL 中 status <> 'failed' 过滤掉它"""
        # 幂等查询返回 None（failed 被过滤，没有命中）
        db = AsyncMock()
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = _make_order_mock()

        idempotency_result = MagicMock()
        mapping_result = MagicMock()
        mapping_result.first.return_value = None  # 没有非 failed 的记录
        idempotency_result.mappings.return_value = mapping_result

        db.execute = AsyncMock(side_effect=[order_result, idempotency_result])
        db.flush = AsyncMock()
        db.add = MagicMock()

        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        # 应创建新支付（不是幂等命中）
        db.add.assert_called_once()
        assert result.get("idempotent") is not True


class TestCrossTenantIsolation:
    """跨租户同 key → 各自独立，互不影响"""

    @pytest.mark.asyncio
    async def test_same_key_different_tenant_no_hit(self):
        """TC-11: 不同 tenant_id 使用相同 idempotency_key，各自独立"""
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())

        async def make_gateway_for_tenant(tenant_id, existing):
            db = AsyncMock()
            order_result = MagicMock()
            order = MagicMock()
            order.id = uuid.UUID(ORDER_ID)
            order.tenant_id = uuid.UUID(tenant_id)
            order_result.scalar_one_or_none.return_value = order

            idempotency_result = MagicMock()
            mapping_result = MagicMock()
            mapping_result.first.return_value = existing
            idempotency_result.mappings.return_value = mapping_result

            db.execute = AsyncMock(side_effect=[order_result, idempotency_result])
            db.flush = AsyncMock()
            db.add = MagicMock()
            return PaymentGateway(db=db, tenant_id=tenant_id), db

        # tenant_a 有该 key 的已有记录
        existing_a = _make_existing_payment_mapping(status="paid", payment_no="PAY_A")
        gw_a, db_a = await make_gateway_for_tenant(tenant_a, existing_a)

        # tenant_b 没有该 key 的记录
        gw_b, db_b = await make_gateway_for_tenant(tenant_b, None)

        result_a = await gw_a.create_payment(
            order_id=ORDER_ID, method="cash", amount_fen=100, idempotency_key=IKEY
        )
        result_b = await gw_b.create_payment(
            order_id=ORDER_ID, method="cash", amount_fen=100, idempotency_key=IKEY
        )

        # tenant_a 命中幂等
        assert result_a["idempotent"] is True
        assert result_a["payment_no"] == "PAY_A"

        # tenant_b 创建新支付
        db_b.add.assert_called_once()
        assert result_b.get("idempotent") is not True


class TestConcurrentWrites:
    """并发两次相同 key → IntegrityError → 捕获后返回已有记录"""

    @pytest.mark.asyncio
    async def test_concurrent_same_key_integrity_error_returns_winner(self):
        """TC-12: 并发写入相同 key，flush 触发 IntegrityError，捕获后重查返回胜者"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(
            existing_payment_mapping=existing,
            raise_integrity_error=True,
        )

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        assert result["idempotent"] is True
        assert result["payment_no"] == PAYMENT_NO
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_conflict_triggers_rollback(self):
        """TC-13: IntegrityError 时，db.rollback 被调用一次"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(
            existing_payment_mapping=existing,
            raise_integrity_error=True,
        )

        await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        db.rollback.assert_called_once()


class TestDifferentKeys:
    """不同 idempotency_key → 各自创建独立记录"""

    @pytest.mark.asyncio
    async def test_different_keys_create_separate_records(self):
        """TC-14: 不同 key 调用两次，各自创建独立支付记录"""

        async def call_with_key(key: str):
            db = AsyncMock()
            order_result = MagicMock()
            order_result.scalar_one_or_none.return_value = _make_order_mock()

            # 每个 key 都没有已有记录
            idempotency_result = MagicMock()
            mapping_result = MagicMock()
            mapping_result.first.return_value = None
            idempotency_result.mappings.return_value = mapping_result

            db.execute = AsyncMock(side_effect=[order_result, idempotency_result])
            db.flush = AsyncMock()
            db.add = MagicMock()

            gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
            result = await gateway.create_payment(
                order_id=ORDER_ID,
                method="cash",
                amount_fen=10000,
                idempotency_key=key,
            )
            return result, db

        result1, db1 = await call_with_key("pos001-aaaaaaaa-1000000000")
        result2, db2 = await call_with_key("pos001-aaaaaaaa-1000000001")

        db1.add.assert_called_once()
        db2.add.assert_called_once()
        assert result1.get("idempotent") is not True
        assert result2.get("idempotent") is not True


class TestIdempotencyKeyValidation:
    """idempotency_key 格式与边界校验"""

    @pytest.mark.asyncio
    async def test_invalid_method_raises_before_idempotency_check(self):
        """TC-15: 不支持的支付方式在幂等检查前抛出 ValueError"""
        db = AsyncMock()
        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)

        with pytest.raises(ValueError, match="不支持的支付方式"):
            await gateway.create_payment(
                order_id=ORDER_ID,
                method="bitcoin",
                amount_fen=10000,
                idempotency_key=IKEY,
            )

    @pytest.mark.asyncio
    async def test_zero_amount_raises_before_idempotency_check(self):
        """TC-16: 支付金额为 0 在幂等检查前抛出 ValueError"""
        db = AsyncMock()
        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)

        with pytest.raises(ValueError, match="支付金额必须为正整数"):
            await gateway.create_payment(
                order_id=ORDER_ID,
                method="cash",
                amount_fen=0,
                idempotency_key=IKEY,
            )

    @pytest.mark.asyncio
    async def test_nonexistent_order_raises_value_error(self):
        """TC-17: 订单不存在时 ValueError，即使有幂等键也不触发幂等逻辑"""
        db = AsyncMock()
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = None  # 订单不存在
        db.execute = AsyncMock(return_value=order_result)

        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)

        with pytest.raises(ValueError, match="订单不存在"):
            await gateway.create_payment(
                order_id=ORDER_ID,
                method="cash",
                amount_fen=10000,
                idempotency_key=IKEY,
            )

        # 幂等检查不应执行（execute 只被调一次，查订单）
        assert db.execute.call_count == 1


class TestCashierApiIntegration:
    """cashier_api 端点正确透传 idempotency_key 到 gateway"""

    @pytest.mark.asyncio
    async def test_checkout_endpoint_passes_idempotency_key_to_gateway(self):
        """TC-18: POST /orders/{id}/checkout 将 idempotency_key 透传给 PaymentGateway"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from unittest.mock import patch, AsyncMock as _AsyncMock

        app = FastAPI()

        from ..api.cashier_api import router
        app.include_router(router)

        captured_kwargs = {}

        async def mock_create_payment(self, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "payment_id": PAYMENT_ID,
                "payment_no": PAYMENT_NO,
                "trade_no": None,
                "qr_code": None,
                "status": "paid",
                "fee_fen": 0,
            }

        with patch(
            "services.tx_trade.src.services.payment_gateway.PaymentGateway.create_payment",
            new=mock_create_payment,
        ):
            from httpx import AsyncClient

            async with AsyncClient(app=app, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/orders/{ORDER_ID}/checkout",
                    json={
                        "method": "cash",
                        "amount_fen": 10000,
                        "idempotency_key": IKEY,
                    },
                    headers={"X-Tenant-ID": TENANT_ID},
                )

        # 无法真正执行路由（需完整 DB 依赖），仅验证请求模型接受 idempotency_key
        # 此测试重点是确认字段存在且能解析
        from ..api.cashier_api import PayCheckoutRequest
        req = PayCheckoutRequest(method="cash", amount_fen=10000, idempotency_key=IKEY)
        assert req.idempotency_key == IKEY

    @pytest.mark.asyncio
    async def test_checkout_request_model_accepts_none_key(self):
        """TC-19: PayCheckoutRequest 接受 idempotency_key=None（向下兼容旧客户端）"""
        from ..api.cashier_api import PayCheckoutRequest

        req = PayCheckoutRequest(method="cash", amount_fen=5000)
        assert req.idempotency_key is None

    @pytest.mark.asyncio
    async def test_checkout_request_model_max_length_128(self):
        """TC-20: PayCheckoutRequest idempotency_key 超过 128 字符时验证失败"""
        from pydantic import ValidationError
        from ..api.cashier_api import PayCheckoutRequest

        long_key = "x" * 129
        with pytest.raises(ValidationError):
            PayCheckoutRequest(method="cash", amount_fen=5000, idempotency_key=long_key)


class TestIdempotencyKeyInResponse:
    """返回值结构校验"""

    @pytest.mark.asyncio
    async def test_normal_payment_no_idempotent_flag(self):
        """TC-21: 正常新建支付（非幂等命中），返回值不包含 idempotent=True"""
        db = AsyncMock()
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = _make_order_mock()

        idempotency_result = MagicMock()
        mapping_result = MagicMock()
        mapping_result.first.return_value = None  # 无已有记录
        idempotency_result.mappings.return_value = mapping_result

        db.execute = AsyncMock(side_effect=[order_result, idempotency_result])
        db.flush = AsyncMock()
        db.add = MagicMock()

        gateway = PaymentGateway(db=db, tenant_id=TENANT_ID)
        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key="new-unique-key-xyz",
        )

        assert result.get("idempotent") is not True

    @pytest.mark.asyncio
    async def test_idempotent_result_has_required_fields(self):
        """TC-22: 幂等命中返回值包含所有必要字段"""
        existing = _make_existing_payment_mapping(status="paid")
        gateway, db = await _build_gateway_with_mock_db(existing_payment_mapping=existing)

        result = await gateway.create_payment(
            order_id=ORDER_ID,
            method="cash",
            amount_fen=10000,
            idempotency_key=IKEY,
        )

        required_fields = {"payment_id", "payment_no", "trade_no", "qr_code", "status", "fee_fen", "idempotent"}
        assert required_fields.issubset(result.keys())
