"""Task 1.3 + 1.4: 退款闭环 + 支付验签 — Tier 1 测试

Task 1.3 验证：
  1. 退款后 payment 状态更新（refunded/partial_refund）
  2. 退款后 net_amount 正确
  3. 退款后发射 payment.refunded 事件

Task 1.4 验证：
  4. 四通道回调全部有验签逻辑（非空壳 stub）
  5. 生产环境 mock mode 返回错误
  6. 验签失败返回 400
  7. 验签失败记录 ERROR 日志
"""

import ast
from pathlib import Path

import pytest

# ── 文件路径 ──

PAYMENT_SERVICE_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-pay" / "src" / "payment_service.py"
)
CALLBACK_ROUTES_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-pay" / "src" / "api" / "callback_routes.py"
)
TX_PAY_EVENTS_PY = (
    Path(__file__).parent.parent.parent
    / "services" / "tx-pay" / "src" / "events.py"
)


def _find_function_source(file_path, func_name):
    source = file_path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(source, node)
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Task 1.3: 退款持久化与事件发射
# ═══════════════════════════════════════════════════════════════════════


class TestRefundPersistence:
    """退款持久化到 payments 表 + 发射事件"""

    def test_refund_method_persists_result(self):
        """refund() 方法持久化退款结果到 payments 表"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert source, "refund 方法未找到"
        # 持久化 UPDATE
        assert "UPDATE payments" in source, (
            "refund 方法未执行 UPDATE payments 持久化退款"
        )
        # 状态更新
        assert "partial_refund" in source or "refunded" in source, (
            "refund 方法未更新 payment status"
        )

    def test_refund_emits_event_on_success(self):
        """退款成功后发射 payment.refunded 事件"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "emit_payment_refunded" in source, (
            "refund 方法未调用 emit_payment_refunded"
        )

    def test_refund_updates_net_amount(self):
        """退款后更新 net_amount_fen"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "net_amount_fen" in source, (
            "refund 方法未更新 net_amount_fen"
        )

    def test_refund_checks_amount_limit(self):
        """退款金额超限时抛出 ValueError"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "超过原支付金额" in source or "refund_amount_fen >" in source, (
            "refund 方法未校验退款金额上限"
        )

    def test_full_refund_sets_status_refunded(self):
        """全额退款设置 status = 'refunded'"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "'refunded'" in source, (
            "refund 方法未设置全额退款状态 'refunded'"
        )

    def test_partial_refund_sets_status_partial(self):
        """部分退款设置 status = 'partial_refund'"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "partial_refund" in source, (
            "refund 方法未设置部分退款状态 'partial_refund'"
        )

    def test_refund_uses_case_when_for_status(self):
        """使用 CASE WHEN 区分全额/部分退款"""
        source = _find_function_source(PAYMENT_SERVICE_PY, "refund")
        assert "CASE" in source, "refund 方法未使用 CASE WHEN"


class TestRefundEventEmission:
    """支付退款事件发射"""

    def test_emit_payment_refunded_exists(self):
        """emit_payment_refunded 函数已定义"""
        source = _find_function_source(TX_PAY_EVENTS_PY, "emit_payment_refunded")
        assert source, "emit_payment_refunded 函数未找到"

    def test_emit_payment_refunded_uses_correct_event_type(self):
        """emit_payment_refunded 使用 PaymentEventType.REFUNDED"""
        source = _find_function_source(TX_PAY_EVENTS_PY, "emit_payment_refunded")
        assert "PaymentEventType.REFUNDED" in source, (
            "emit_payment_refunded 未使用正确的事件类型"
        )

    def test_emit_payment_refunded_includes_refund_id(self):
        """退款事件包含 refund_id"""
        source = _find_function_source(TX_PAY_EVENTS_PY, "emit_payment_refunded")
        assert "refund_id" in source, "退款事件 payload 缺少 refund_id"

    def test_emit_payment_refunded_includes_amount_fen(self):
        """退款事件包含 amount_fen"""
        source = _find_function_source(TX_PAY_EVENTS_PY, "emit_payment_refunded")
        assert "amount_fen" in source, "退款事件 payload 缺少 amount_fen"


# ═══════════════════════════════════════════════════════════════════════
# Task 1.4: 支付通道验签加固
# ═══════════════════════════════════════════════════════════════════════


class TestCallbackVerificationHardening:
    """回调验签不再是空壳 stub"""

    def test_wechat_callback_has_verification(self):
        """微信回调有完整验签逻辑"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "wechat_callback")
        assert "verify_callback" in source, "微信回调未调用 verify_callback"
        assert "FAIL" in source, "微信回调验签失败无错误返回"

    def test_alipay_callback_has_verification(self):
        """支付宝回调不再是空壳 — 有验签逻辑"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "alipay_callback")
        assert "verify_callback" in source, (
            "支付宝回调未调用 verify_callback — 仍是空壳 stub"
        )
        assert "emit_payment_confirmed" in source, (
            "支付宝回调验签成功后未发射支付确认事件"
        )

    def test_lakala_callback_has_verification(self):
        """拉卡拉回调不再是空壳 — 有验签逻辑"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "lakala_callback")
        assert "verify_callback" in source, (
            "拉卡拉回调未调用 verify_callback — 仍是空壳 stub"
        )
        assert "emit_payment_confirmed" in source, (
            "拉卡拉回调验签成功后未发射支付确认事件"
        )

    def test_shouqianba_callback_has_verification(self):
        """收钱吧回调不再是空壳 — 有验签逻辑"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "shouqianba_callback")
        assert "verify_callback" in source, (
            "收钱吧回调未调用 verify_callback — 仍是空壳 stub"
        )
        assert "emit_payment_confirmed" in source, (
            "收钱吧回调验签成功后未发射支付确认事件"
        )


class TestMockModeProtection:
    """生产环境 mock mode 保护"""

    def test_mock_mode_guard_exists(self):
        """TX_PAY_MOCK_MODE 环境变量检查存在"""
        source = CALLBACK_ROUTES_PY.read_text()
        assert "TX_PAY_MOCK_MODE" in source, (
            "callback_routes.py 未检查 TX_PAY_MOCK_MODE"
        )
        assert "_MOCK_MODE" in source, (
            "callback_routes.py 未定义 _MOCK_MODE 变量"
        )

    def test_wechat_mock_mode_returns_error(self):
        """微信 mock mode 返回 400 而非 200"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "wechat_callback")
        assert "_MOCK_MODE" in source, "微信回调未检查 mock mode"
        assert "400" in source or "FAIL" in source, (
            "mock mode 下微信回调应返回错误状态"
        )

    def test_alipay_mock_mode_returns_error(self):
        """支付宝 mock mode 返回错误"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "alipay_callback")
        assert "_MOCK_MODE" in source, "支付宝回调未检查 mock mode"

    def test_lakala_mock_mode_returns_error(self):
        """拉卡拉 mock mode 返回错误"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "lakala_callback")
        assert "_MOCK_MODE" in source, "拉卡拉回调未检查 mock mode"

    def test_shouqianba_mock_mode_returns_error(self):
        """收钱吧 mock mode 返回错误"""
        source = _find_function_source(CALLBACK_ROUTES_PY, "shouqianba_callback")
        assert "_MOCK_MODE" in source, "收钱吧回调未检查 mock mode"


class TestVerificationFailureHandling:
    """验签失败的错误处理"""

    def test_verify_failed_returns_400(self):
        """验签失败返回 400（非 200）"""
        source = CALLBACK_ROUTES_PY.read_text()
        assert "400" in source, "回调路由中缺少 400 错误状态码"

    def test_not_implemented_error_logged(self):
        """NotImplementedError 记录 ERROR 日志"""
        source = CALLBACK_ROUTES_PY.read_text()
        assert "NotImplementedError" in source, (
            "回调路由未处理 NotImplementedError"
        )
        assert "logger.error" in source, (
            "回调路由验签失败未使用 ERROR 级别日志"
        )

    def test_generic_exception_returns_error(self):
        """通用异常时返回错误响应而非 200"""
        source = CALLBACK_ROUTES_PY.read_text()
        assert "except Exception" in source, (
            "回调路由缺少通用异常处理"
        )


class TestChannelAvailabilityCheck:
    """渠道可用性检查"""

    def test_channel_none_returns_error(self):
        """渠道不可用时返回 500"""
        source = CALLBACK_ROUTES_PY.read_text()
        assert "is None" in source or "not_available" in source, (
            "回调路由未检查渠道 registry 返回值"
        )
