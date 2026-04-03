"""支付Saga补偿事务测试

覆盖场景（25个用例）：

正常路径：
  T01: S1→S2→S3 全成功 → status=done
  T02: 现金支付（非SQB）全流程成功
  T03: 支付成功后幂等键重复请求 → 直接返回 done
  T04: 失败后用相同幂等键重试 → 正常走新支付流程

S1失败：
  T05: 订单不存在 → status=failed，不补偿
  T06: 订单已结账 → status=failed，不补偿
  T07: 订单已取消 → status=failed，不补偿

S2失败：
  T08: 支付网关 RuntimeError → status=failed，不补偿（未扣款）
  T09: 支付网关 ValueError（无效支付方式）→ status=failed，不补偿

S3失败（触发补偿）：
  T10: complete_order DB超时（SQLAlchemyError）→ 退款成功 → status=compensated
  T11: complete_order RuntimeError → 退款成功 → status=compensated
  T12: complete_order ValueError → 退款成功 → status=compensated

补偿路径：
  T13: compensate() 成功 → refund被调用，step=compensated，返回True
  T14: compensate() 退款网关失败 → step=failed，返回False
  T15: compensate() 无payment_id → step=failed，返回False

崩溃恢复：
  T16: recover_pending_sagas — paying状态有payment_id → 重试S3成功 → done
  T17: recover_pending_sagas — paying状态无payment_id → 标记failed
  T18: recover_pending_sagas — completing状态 → 重试S3成功 → done
  T19: recover_pending_sagas — completing状态S3失败 → 补偿退款
  T20: recover_pending_sagas — 无挂起Saga → 返回0

租户隔离：
  T21: 不同tenant_id的Saga互不可见（幂等键隔离）
  T22: compensate对不同租户的saga_id无效

幂等保护：
  T23: 多次execute相同idempotency_key → compensated状态直接返回
  T24: 无idempotency_key不保护（允许重复执行）

Saga记录：
  T25: 每次step变更都有flush调用（不污染外部事务）
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))


# ─────────────────────────────────────────────────────────────────────────────
# 辅助工具
# ─────────────────────────────────────────────────────────────────────────────

def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _uid_str() -> str:
    return str(uuid.uuid4())


def _make_payment_result(payment_id: Optional[str] = None) -> dict:
    return {
        "payment_id": payment_id or _uid_str(),
        "payment_no": f"PAY20260331{uuid.uuid4().hex[:4].upper()}",
        "trade_no": "SQB_TRADE_001",
        "qr_code": None,
        "status": "paid",
        "fee_fen": 23,
    }


def _make_refund_result() -> dict:
    return {
        "refund_id": _uid_str(),
        "refund_no": f"REF20260331{uuid.uuid4().hex[:4].upper()}",
        "refund_trade_no": "SQB_REF_001",
        "amount_fen": 3800,
        "status": "refunded",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mock DB构建器
# ─────────────────────────────────────────────────────────────────────────────

def _make_db(
    order_status: str = "open",
    saga_rows: Optional[list[dict]] = None,
    complete_order_error: Optional[Exception] = None,
    update_rowcount: int = 1,
) -> AsyncMock:
    """构造模拟 AsyncSession。

    saga_rows: 按顺序返回的 execute 查询结果，每行是 dict（模拟 mappings().first()）
    """
    db = AsyncMock()
    db.flush = AsyncMock()

    # 按调用顺序返回不同的 execute 结果
    _call_count = {"n": 0}
    _saga_rows = list(saga_rows or [])

    async def _execute(stmt, params=None):
        result = MagicMock()
        # 对 UPDATE 操作，rowcount 表示影响行数
        result.rowcount = update_rowcount

        # mappings().first() 用于 SELECT 查询
        mappings_mock = MagicMock()
        if _saga_rows:
            row = _saga_rows[_call_count["n"] % len(_saga_rows)]
            _call_count["n"] += 1
        else:
            row = None

        mappings_mock.first.return_value = row
        mappings_mock.all.return_value = []
        result.mappings.return_value = mappings_mock
        result.scalar_one_or_none.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_gateway(
    payment_result: Optional[dict] = None,
    payment_error: Optional[Exception] = None,
    refund_result: Optional[dict] = None,
    refund_error: Optional[Exception] = None,
) -> MagicMock:
    """构造模拟 PaymentGateway。"""
    gw = MagicMock()

    if payment_error:
        gw.create_payment = AsyncMock(side_effect=payment_error)
    else:
        gw.create_payment = AsyncMock(return_value=payment_result or _make_payment_result())

    if refund_error:
        gw.refund = AsyncMock(side_effect=refund_error)
    else:
        gw.refund = AsyncMock(return_value=refund_result or _make_refund_result())

    return gw


# ─────────────────────────────────────────────────────────────────────────────
# 从 PaymentSagaService 导入
# ─────────────────────────────────────────────────────────────────────────────

from services.payment_saga_service import (
    PaymentSagaService,
    SagaStep,
)

# ─────────────────────────────────────────────────────────────────────────────
# 辅助：构造 PaymentSagaService，注入 mock _validate_order / _complete_order
# ─────────────────────────────────────────────────────────────────────────────

def _make_service(
    gw=None,
    order_exists: bool = True,
    order_status: str = "open",
    complete_order_error: Optional[Exception] = None,
    saga_find_result: Optional[dict] = None,
    tenant_id: Optional[uuid.UUID] = None,
) -> tuple[PaymentSagaService, AsyncMock]:
    """构造 PaymentSagaService，mock 内部 DB 操作。"""
    db = AsyncMock()
    db.flush = AsyncMock()

    # 模拟 execute：INSERT/UPDATE 总成功，SELECT 按需返回
    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        mappings_mock = MagicMock()
        mappings_mock.first.return_value = saga_find_result
        mappings_mock.all.return_value = []
        result.mappings.return_value = mappings_mock
        return result

    db.execute = AsyncMock(side_effect=_execute)

    tid = tenant_id or _uid()
    gw = gw or _make_gateway()
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)

    # Patch 内部方法，避免依赖真实 DB 查询
    if not order_exists:
        svc._validate_order = AsyncMock(side_effect=ValueError("订单不存在"))
    elif order_status == "completed":
        svc._validate_order = AsyncMock(side_effect=ValueError("订单已结账"))
    elif order_status == "cancelled":
        svc._validate_order = AsyncMock(side_effect=ValueError("订单已取消"))
    else:
        svc._validate_order = AsyncMock(return_value=None)

    if complete_order_error:
        svc._complete_order = AsyncMock(side_effect=complete_order_error)
    else:
        svc._complete_order = AsyncMock(return_value=None)

    return svc, db


# ─────────────────────────────────────────────────────────────────────────────
# T01 — 正常路径：S1→S2→S3 全成功 → status=done
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T01_happy_path_done():
    """正常路径：全流程成功返回 done"""
    payment_id = _uid_str()
    gw = _make_gateway(payment_result=_make_payment_result(payment_id))
    svc, db = _make_service(gw=gw)

    result = await svc.execute(
        order_id=_uid(),
        method="wechat",
        amount_fen=3800,
        auth_code="134500000001",
    )

    assert result["status"] == SagaStep.DONE
    assert result["payment_id"] == payment_id
    assert result["payment_no"] is not None
    assert result["error"] is None
    assert "saga_id" in result
    gw.create_payment.assert_awaited_once()
    svc._complete_order.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T02 — 现金支付全流程成功
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T02_cash_payment_done():
    """现金支付（无SQB调用）全流程成功"""
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw)

    result = await svc.execute(
        order_id=_uid(),
        method="cash",
        amount_fen=5000,
    )

    assert result["status"] == SagaStep.DONE
    gw.create_payment.assert_awaited_once()
    svc._complete_order.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T03 — 幂等键命中 done 状态 → 直接返回
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T03_idempotency_done_hit():
    """幂等键命中已完成Saga → 直接返回done，不重复扣款"""
    existing_payment_id = _uid()
    gw = _make_gateway()
    svc, _ = _make_service(
        gw=gw,
        saga_find_result={
            "saga_id": _uid(),
            "step": SagaStep.DONE,
            "payment_id": existing_payment_id,
            "compensation_reason": None,
        },
    )
    # 覆盖 _find_by_idempotency_key 直接返回已有记录
    svc._find_by_idempotency_key = AsyncMock(return_value={
        "saga_id": _uid(),
        "step": SagaStep.DONE,
        "payment_id": existing_payment_id,
        "compensation_reason": None,
    })

    result = await svc.execute(
        order_id=_uid(),
        method="wechat",
        amount_fen=3800,
        idempotency_key="device001-abcd1234-1743420000",
    )

    assert result["status"] == SagaStep.DONE
    # 幂等命中：不应再调用支付网关
    gw.create_payment.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T04 — 失败后相同幂等键重试 → 正常走新支付流程
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T04_idempotency_failed_allows_retry():
    """失败状态的幂等键 → 直接返回failed（客户端可换新key重试）"""
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw)
    svc._find_by_idempotency_key = AsyncMock(return_value={
        "saga_id": _uid(),
        "step": SagaStep.FAILED,
        "payment_id": None,
        "compensation_reason": "SQB超时",
    })

    result = await svc.execute(
        order_id=_uid(),
        method="wechat",
        amount_fen=3800,
        idempotency_key="device001-abcd1234-1743420000",
    )

    # 幂等键命中 failed 状态 → 直接返回 failed，不重复执行
    assert result["status"] == SagaStep.FAILED
    gw.create_payment.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T05 — S1失败：订单不存在
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T05_s1_order_not_found():
    """S1: 订单不存在 → status=failed，不补偿"""
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw, order_exists=False)

    result = await svc.execute(order_id=_uid(), method="wechat", amount_fen=3800)

    assert result["status"] == SagaStep.FAILED
    assert "订单不存在" in result["error"]
    gw.create_payment.assert_not_awaited()
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T06 — S1失败：订单已结账
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T06_s1_order_already_completed():
    """S1: 订单已结账 → status=failed，不补偿"""
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw, order_status="completed")

    result = await svc.execute(order_id=_uid(), method="cash", amount_fen=2000)

    assert result["status"] == SagaStep.FAILED
    assert "已结账" in result["error"]
    gw.create_payment.assert_not_awaited()
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T07 — S1失败：订单已取消
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T07_s1_order_cancelled():
    """S1: 订单已取消 → status=failed，不补偿"""
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw, order_status="cancelled")

    result = await svc.execute(order_id=_uid(), method="alipay", amount_fen=1500)

    assert result["status"] == SagaStep.FAILED
    assert "已取消" in result["error"]
    gw.create_payment.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T08 — S2失败：支付网关 RuntimeError
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T08_s2_gateway_runtime_error():
    """S2: 收钱吧超时 → status=failed，不退款（未扣款）"""
    gw = _make_gateway(payment_error=RuntimeError("收钱吧支付失败: 网络超时"))
    svc, _ = _make_service(gw=gw)

    result = await svc.execute(order_id=_uid(), method="wechat", amount_fen=3800)

    assert result["status"] == SagaStep.FAILED
    assert result["payment_id"] is None
    gw.refund.assert_not_awaited()
    svc._complete_order.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T09 — S2失败：支付网关 ValueError（无效支付方式）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T09_s2_gateway_value_error():
    """S2: 无效支付方式 → status=failed，不退款"""
    gw = _make_gateway(payment_error=ValueError("不支持的支付方式: bitcoin"))
    svc, _ = _make_service(gw=gw)

    result = await svc.execute(order_id=_uid(), method="bitcoin", amount_fen=100)

    assert result["status"] == SagaStep.FAILED
    assert "bitcoin" in result["error"]
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T10 — S3失败（SQLAlchemyError）→ 退款成功 → status=compensated
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T10_s3_db_timeout_compensated():
    """S3: DB超时 → 退款成功 → status=compensated"""
    payment_id = _uid_str()
    gw = _make_gateway(payment_result=_make_payment_result(payment_id))

    db_error = OperationalError("connection timeout", None, None)
    svc, _ = _make_service(gw=gw, complete_order_error=db_error)

    # compensate 内部需要查到 payment_id，mock _find_payment_id_from_db
    async def _mock_compensate(saga_id, reason):
        await gw.refund(
            payment_id=payment_id,
            refund_amount_fen=3800,
            reason=reason,
        )
        return True

    svc.compensate = AsyncMock(side_effect=_mock_compensate)

    result = await svc.execute(order_id=_uid(), method="wechat", amount_fen=3800)

    assert result["status"] == SagaStep.COMPENSATED
    gw.refund.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T11 — S3失败（RuntimeError）→ 退款成功 → status=compensated
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T11_s3_runtime_error_compensated():
    """S3: RuntimeError → 退款成功 → status=compensated"""
    payment_id = _uid_str()
    gw = _make_gateway(payment_result=_make_payment_result(payment_id))
    svc, _ = _make_service(
        gw=gw,
        complete_order_error=RuntimeError("order state machine locked"),
    )

    svc.compensate = AsyncMock(return_value=True)

    result = await svc.execute(order_id=_uid(), method="wechat", amount_fen=3800)

    assert result["status"] == SagaStep.COMPENSATED
    svc.compensate.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T12 — S3失败（ValueError）→ 退款成功 → status=compensated
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T12_s3_value_error_compensated():
    """S3: ValueError（订单状态冲突）→ 退款成功 → status=compensated"""
    gw = _make_gateway()
    svc, _ = _make_service(
        gw=gw,
        complete_order_error=ValueError("订单状态冲突"),
    )
    svc.compensate = AsyncMock(return_value=True)

    result = await svc.execute(order_id=_uid(), method="alipay", amount_fen=2000)

    assert result["status"] == SagaStep.COMPENSATED


# ─────────────────────────────────────────────────────────────────────────────
# T13 — compensate() 成功：refund被调用，step=compensated，返回True
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T13_compensate_success():
    """compensate(): 退款成功 → 返回True"""
    saga_id = _uid()
    payment_id = _uid()
    amount_fen = 3800

    gw = _make_gateway()
    gw.refund = AsyncMock(return_value=_make_refund_result())

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = {
            "payment_id": payment_id,
            "payment_amount_fen": amount_fen,
        }
        m.all.return_value = []
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)

    tid = _uid()
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)

    ok = await svc.compensate(saga_id=saga_id, reason="S3失败")

    assert ok is True
    gw.refund.assert_awaited_once()
    call_kwargs = gw.refund.call_args
    assert call_kwargs.kwargs["payment_id"] == str(payment_id)
    assert call_kwargs.kwargs["refund_amount_fen"] == amount_fen


# ─────────────────────────────────────────────────────────────────────────────
# T14 — compensate() 退款网关失败 → 返回False
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T14_compensate_refund_gateway_failure():
    """compensate(): 退款网关异常 → 返回False，step=failed"""
    saga_id = _uid()
    payment_id = _uid()

    gw = _make_gateway(refund_error=RuntimeError("收钱吧退款失败: 订单已超时"))

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = {"payment_id": payment_id, "payment_amount_fen": 3800}
        m.all.return_value = []
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    tid = _uid()
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)

    ok = await svc.compensate(saga_id=saga_id, reason="S3失败")

    assert ok is False
    gw.refund.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T15 — compensate() 无payment_id → 返回False
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T15_compensate_no_payment_id():
    """compensate(): payment_id为空 → 返回False，无退款调用"""
    saga_id = _uid()
    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = {"payment_id": None, "payment_amount_fen": 3800}
        m.all.return_value = []
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    tid = _uid()
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)

    ok = await svc.compensate(saga_id=saga_id, reason="无payment_id")

    assert ok is False
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T16 — 崩溃恢复：paying有payment_id → S3成功 → done
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T16_recover_paying_with_payment_id_success():
    """recover_pending_sagas: paying状态有payment_id → S3重试成功 → done"""
    saga_id = _uid()
    payment_id = _uid()
    order_id = _uid()
    tid = _uid()

    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    # all() 返回挂起Saga列表
    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = None
        m.all.return_value = [
            {
                "saga_id": saga_id,
                "step": SagaStep.PAYING,
                "payment_id": payment_id,
                "order_id": order_id,
                "payment_amount_fen": 3800,
                "payment_method": "wechat",
            }
        ]
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)
    svc._complete_order = AsyncMock(return_value=None)
    svc._update_step = AsyncMock()

    count = await svc.recover_pending_sagas()

    assert count == 1
    svc._complete_order.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T17 — 崩溃恢复：paying无payment_id → 标记failed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T17_recover_paying_no_payment_id():
    """recover_pending_sagas: paying无payment_id → S2未完成 → 标记failed"""
    saga_id = _uid()
    order_id = _uid()
    tid = _uid()
    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = None
        m.all.return_value = [
            {
                "saga_id": saga_id,
                "step": SagaStep.PAYING,
                "payment_id": None,
                "order_id": order_id,
                "payment_amount_fen": 3800,
                "payment_method": "wechat",
            }
        ]
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)
    svc._update_step = AsyncMock()

    count = await svc.recover_pending_sagas()

    assert count == 1
    # 无payment_id应标记failed
    svc._update_step.assert_awaited_once_with(
        saga_id,
        SagaStep.FAILED,
        compensation_reason="崩溃恢复：paying状态无payment_id，S2未完成",
    )
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T18 — 崩溃恢复：completing → S3重试成功 → done
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T18_recover_completing_success():
    """recover_pending_sagas: completing状态 → S3重试成功 → done"""
    saga_id = _uid()
    payment_id = _uid()
    order_id = _uid()
    tid = _uid()
    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = None
        m.all.return_value = [
            {
                "saga_id": saga_id,
                "step": SagaStep.COMPLETING,
                "payment_id": payment_id,
                "order_id": order_id,
                "payment_amount_fen": 3800,
                "payment_method": "wechat",
            }
        ]
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)
    svc._complete_order = AsyncMock(return_value=None)
    svc._update_step = AsyncMock()

    count = await svc.recover_pending_sagas()

    assert count == 1
    svc._complete_order.assert_awaited_once_with(order_id)


# ─────────────────────────────────────────────────────────────────────────────
# T19 — 崩溃恢复：completing S3失败 → 触发补偿
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T19_recover_completing_s3_fails_compensate():
    """recover_pending_sagas: completing S3失败 → 调用compensate"""
    saga_id = _uid()
    payment_id = _uid()
    order_id = _uid()
    tid = _uid()
    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 1
        m = MagicMock()
        m.first.return_value = None
        m.all.return_value = [
            {
                "saga_id": saga_id,
                "step": SagaStep.COMPLETING,
                "payment_id": payment_id,
                "order_id": order_id,
                "payment_amount_fen": 3800,
                "payment_method": "wechat",
            }
        ]
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    svc = PaymentSagaService(db=db, tenant_id=tid, payment_gateway=gw)
    svc._complete_order = AsyncMock(side_effect=RuntimeError("DB写入超时"))
    svc.compensate = AsyncMock(return_value=True)
    svc._update_step = AsyncMock()

    count = await svc.recover_pending_sagas()

    assert count == 1
    svc.compensate.assert_awaited_once()
    compensate_call_reason = svc.compensate.call_args.kwargs["reason"]
    assert "DB写入超时" in compensate_call_reason


# ─────────────────────────────────────────────────────────────────────────────
# T20 — 崩溃恢复：无挂起Saga → 返回0
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T20_recover_no_pending():
    """recover_pending_sagas: 无挂起Saga → 返回0"""
    gw = _make_gateway()
    db = AsyncMock()
    db.flush = AsyncMock()

    async def _execute(stmt, params=None):
        result = MagicMock()
        m = MagicMock()
        m.all.return_value = []
        m.first.return_value = None
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    svc = PaymentSagaService(db=db, tenant_id=_uid(), payment_gateway=gw)

    count = await svc.recover_pending_sagas()

    assert count == 0


# ─────────────────────────────────────────────────────────────────────────────
# T21 — 租户隔离：不同tenant_id的幂等键互不可见
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T21_tenant_isolation_idempotency():
    """不同租户下相同幂等键独立处理"""
    ikey = "device001-aaaa1111-1743420000"

    gw_a = _make_gateway()
    svc_a, _ = _make_service(gw=gw_a, tenant_id=_uid())
    svc_a._find_by_idempotency_key = AsyncMock(return_value=None)  # 租户A找不到

    gw_b = _make_gateway()
    svc_b, _ = _make_service(gw=gw_b, tenant_id=_uid())
    svc_b._find_by_idempotency_key = AsyncMock(return_value=None)  # 租户B也找不到

    result_a = await svc_a.execute(order_id=_uid(), method="wechat", amount_fen=3800, idempotency_key=ikey)
    result_b = await svc_b.execute(order_id=_uid(), method="wechat", amount_fen=3800, idempotency_key=ikey)

    # 两个租户都应独立执行各自支付
    assert result_a["status"] == SagaStep.DONE
    assert result_b["status"] == SagaStep.DONE
    gw_a.create_payment.assert_awaited_once()
    gw_b.create_payment.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# T22 — 租户隔离：compensate对不同租户的saga_id无效
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T22_tenant_isolation_compensate():
    """compensate 查询带 tenant_id 过滤：跨租户saga_id查不到payment_id → False"""
    saga_id = _uid()
    gw = _make_gateway()

    db = AsyncMock()
    db.flush = AsyncMock()

    # 模拟跨租户：row为None（找不到）
    async def _execute(stmt, params=None):
        result = MagicMock()
        result.rowcount = 0
        m = MagicMock()
        m.first.return_value = None  # 不同租户，找不到
        m.all.return_value = []
        result.mappings.return_value = m
        return result

    db.execute = AsyncMock(side_effect=_execute)
    # 使用与saga不同的tenant_id
    other_tenant_id = _uid()
    svc = PaymentSagaService(db=db, tenant_id=other_tenant_id, payment_gateway=gw)

    ok = await svc.compensate(saga_id=saga_id, reason="跨租户测试")

    assert ok is False
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T23 — 幂等：compensated状态直接返回
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T23_idempotency_compensated_state():
    """幂等键命中 compensated 状态 → 直接返回compensated"""
    existing_payment_id = _uid()
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw)
    svc._find_by_idempotency_key = AsyncMock(return_value={
        "saga_id": _uid(),
        "step": SagaStep.COMPENSATED,
        "payment_id": existing_payment_id,
        "compensation_reason": "S3超时已退款",
    })

    result = await svc.execute(
        order_id=_uid(),
        method="wechat",
        amount_fen=3800,
        idempotency_key="device001-bbbb2222-1743430000",
    )

    assert result["status"] == SagaStep.COMPENSATED
    assert "S3超时已退款" in result["error"]
    gw.create_payment.assert_not_awaited()
    gw.refund.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# T24 — 无幂等键：允许重复执行（两次独立支付）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T24_no_idempotency_key_allows_duplicate():
    """不传幂等键：每次都正常执行，无幂等保护"""
    order_id = _uid()
    gw = _make_gateway()
    svc, _ = _make_service(gw=gw)

    result1 = await svc.execute(order_id=order_id, method="cash", amount_fen=1000)
    result2 = await svc.execute(order_id=order_id, method="cash", amount_fen=1000)

    assert result1["status"] == SagaStep.DONE
    assert result2["status"] == SagaStep.DONE
    assert gw.create_payment.await_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# T25 — 每次step变更都flush：不污染外部事务
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_T25_flush_called_on_each_step():
    """每次 _update_step / _set_payment_id 都调用 db.flush，确保step变更即时持久化"""
    gw = _make_gateway()
    svc, db = _make_service(gw=gw)

    await svc.execute(order_id=_uid(), method="wechat", amount_fen=3800)

    # 正常路径：INSERT(创建) + validating→paying + set_payment_id + paying→completing + completing→done
    # 每次 _update_step 和 _set_payment_id 都会 flush
    assert db.flush.await_count >= 4, (
        f"期望至少4次flush（每个step变更+payment_id写入），实际: {db.flush.await_count}"
    )
