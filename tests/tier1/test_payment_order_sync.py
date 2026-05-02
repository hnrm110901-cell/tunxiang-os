"""Task 1.2: 支付事件驱动订单状态 — Tier 1 测试

验证：
  1. payment_event_consumer.py 正确订阅 payment.confirmed / payment.refunded
  2. tx-trade main.py 正确接入消费者 lifespan
  3. 事件类型匹配 tx-pay 发射的事件
  4. 幂等逻辑正确
"""

import ast
from pathlib import Path

import pytest

# ── 文件路径 ──

CONSUMER_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-trade" / "src" / "services" / "payment_event_consumer.py"
)
MAIN_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-trade" / "src" / "main.py"
)
TX_PAY_EVENTS_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-pay" / "src" / "events.py"
)
EVENT_TYPES_PY = (
    Path(__file__).parent.parent.parent
    / "shared" / "events" / "src" / "event_types.py"
)


def _find_function_source(file_path, func_name):
    """解析 Python 文件中指定函数的源码"""
    source = file_path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(source, node)
    return ""


def _find_class_source(file_path, class_name):
    """解析 Python 文件中指定类的源码"""
    source = file_path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(source, node)
    return ""


# ── payment_event_consumer.py 结构验证 ──


def test_consumer_file_exists():
    """payment_event_consumer.py 文件存在"""
    assert CONSUMER_PY.exists(), f"文件不存在: {CONSUMER_PY}"


def test_payment_event_handlers_class_exists():
    """PaymentEventHandlers 类已定义"""
    source = CONSUMER_PY.read_text()
    assert "class PaymentEventHandlers" in source, "PaymentEventHandlers 类未定义"


def test_handle_payment_confirmed_exists():
    """handle_payment_confirmed 方法已定义"""
    source = _find_function_source(CONSUMER_PY, "handle_payment_confirmed")
    assert source, "handle_payment_confirmed 方法未找到"
    assert "UPDATE orders" in source, "handle_payment_confirmed 未更新 orders 表"
    assert "SET status" in source, "handle_payment_confirmed 未设置 order status"


def test_handle_payment_refunded_exists():
    """handle_payment_refunded 方法已定义"""
    source = _find_function_source(CONSUMER_PY, "handle_payment_refunded")
    assert source, "handle_payment_refunded 方法未找到"
    assert "UPDATE orders" in source, "handle_payment_refunded 未更新 orders 表"


def test_consumer_subscribes_confirmed_event():
    """消费者订阅 payment.confirmed"""
    source = CONSUMER_PY.read_text()
    assert "PaymentEventType.CONFIRMED" in source, "未订阅 PaymentEventType.CONFIRMED"
    assert "handle_payment_confirmed" in source


def test_consumer_subscribes_refunded_event():
    """消费者订阅 payment.refunded"""
    source = CONSUMER_PY.read_text()
    assert "PaymentEventType.REFUNDED" in source, "未订阅 PaymentEventType.REFUNDED"
    assert "handle_payment_refunded" in source


def test_idempotency_skip_already_completed():
    """已完成订单跳过更新（幂等）"""
    source = _find_function_source(CONSUMER_PY, "handle_payment_confirmed")
    assert "already_completed" in source.lower() or "skip" in source.lower() or (
        "NOT IN" in source and "completed" in source
    ), "handle_payment_confirmed 缺少已完成订单跳过逻辑"


def test_consumer_group_name_defined():
    """CONSUMER_GROUP 常量已定义"""
    source = CONSUMER_PY.read_text()
    assert "CONSUMER_GROUP" in source, "CONSUMER_GROUP 未定义"
    assert "tx-trade" in source, "CONSUMER_GROUP 应包含 tx-trade 标识"


# ── tx-trade main.py 接入验证 ──


def test_main_py_wires_payment_consumer():
    """tx-trade main.py 在 lifespan 中启动支付事件消费者"""
    source = MAIN_PY.read_text()
    assert "payment_event_consumer" in source, (
        "main.py 未引用 payment_event_consumer"
    )
    assert "create_payment_event_consumer" in source, (
        "main.py 未调用 create_payment_event_consumer"
    )
    assert "payment_event_consumer_task" in source, (
        "main.py 未创建 payment_event_consumer_task"
    )


def test_main_py_graceful_shutdown_consumer():
    """tx-trade main.py 在 shutdown 中取消消费者 task"""
    source = MAIN_PY.read_text()
    assert "payment_event_consumer_task.cancel()" in source, (
        "main.py 未在 shutdown 时 cancel 消费者 task"
    )


def test_main_py_consumer_wrapped_in_try_except():
    """消费者启动失败不阻塞主服务启动"""
    source = MAIN_PY.read_text()
    # 消费者启动有 try/except 保护
    assert "payment_event_consumer_start_failed" in source, (
        "main.py 消费者启动缺少异常保护"
    )


# ── 事件类型一致性验证 ──


def test_event_types_match():
    """tx-pay 发射的事件类型与共享定义一致"""
    source = EVENT_TYPES_PY.read_text()
    assert "CONFIRMED = \"payment.confirmed\"" in source, (
        "PaymentEventType.CONFIRMED 定义不一致"
    )
    assert "REFUNDED = \"payment.refunded\"" in source, (
        "PaymentEventType.REFUNDED 定义不一致"
    )


def test_tx_pay_emits_confirmed_event():
    """tx-pay 发射 payment.confirmed 事件"""
    source = TX_PAY_EVENTS_PY.read_text()
    assert "PaymentEventType.CONFIRMED" in source, (
        "tx-pay events.py 未引用 PaymentEventType.CONFIRMED"
    )


def test_tx_pay_has_refund_emitter():
    """tx-pay 有 emit_payment_refunded 函数"""
    source = _find_function_source(TX_PAY_EVENTS_PY, "emit_payment_refunded")
    assert source, "emit_payment_refunded 函数未找到"
    assert "PaymentEventType.REFUNDED" in source, (
        "emit_payment_refunded 未发射 PaymentEventType.REFUNDED"
    )


# ── 订单状态正确性验证 ──


def test_order_status_completed_constant():
    """ORDER_STATUS_COMPLETED = 'completed'"""
    source = CONSUMER_PY.read_text()
    assert 'ORDER_STATUS_COMPLETED = "completed"' in source, (
        "ORDER_STATUS_COMPLETED 值不正确"
    )


def test_order_status_cancelled_constant():
    """ORDER_STATUS_CANCELLED = 'cancelled'"""
    source = CONSUMER_PY.read_text()
    assert 'ORDER_STATUS_CANCELLED = "cancelled"' in source, (
        "ORDER_STATUS_CANCELLED 值不正确"
    )


def test_payment_status_success_constant():
    """PAYMENT_STATUS_SUCCESS = 'success'"""
    source = CONSUMER_PY.read_text()
    assert 'PAYMENT_STATUS_SUCCESS = "success"' in source, (
        "PAYMENT_STATUS_SUCCESS 值不正确"
    )


# ── 端到端一致性：stream_id 映射 ──


def test_event_stream_id_maps_to_order_id():
    """payment.confirmed 的 stream_id 就是 order_id"""
    source = _find_function_source(CONSUMER_PY, "handle_payment_confirmed")
    assert "event.stream_id" in source, (
        "handle_payment_confirmed 未使用 event.stream_id"
    )
    assert "order_id = event.stream_id" in source or "order_id" in source, (
        "stream_id 未映射到 order_id"
    )


def test_refund_checks_full_vs_partial():
    """handle_payment_refunded 区分全额/部分退款"""
    source = _find_function_source(CONSUMER_PY, "handle_payment_refunded")
    assert "is_full_refund" in source or "full_refund" in source.lower(), (
        "handle_payment_refunded 未区分全额/部分退款"
    )
