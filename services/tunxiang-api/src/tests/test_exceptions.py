"""屯象OS 异常层级体系测试

覆盖：
- 每个异常类可正确实例化并包含 context
- to_dict() 方法序列化
- TenantIsolationError 构造时自动 logger.critical
- isinstance 继承关系
"""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# 辅助：一次性导入全部异常类
# ---------------------------------------------------------------------------

@pytest.fixture()
def all_exception_classes():
    from shared.core.exceptions import (
        AgentConstraintViolation,
        AgentDecisionError,
        AgentError,
        AoqiweiAPIError,
        BusinessRuleError,
        CacheConnectionError,
        DataValidationError,
        ExternalAPIError,
        FeishuWebhookError,
        FoodSafetyError,
        InfrastructureError,
        MarginViolationError,
        MeituanAPIError,
        ModelRouterError,
        PinzhiAPIError,
        POSAdapterError,
        ReconciliationMismatchError,
        ServiceTimeoutError,
        SMSServiceError,
        TenantIsolationError,
        TunxiangBaseError,
        VectorDBError,
        WeComWebhookError,
    )
    return {
        "TunxiangBaseError": TunxiangBaseError,
        "ExternalAPIError": ExternalAPIError,
        "POSAdapterError": POSAdapterError,
        "PinzhiAPIError": PinzhiAPIError,
        "AoqiweiAPIError": AoqiweiAPIError,
        "MeituanAPIError": MeituanAPIError,
        "WeComWebhookError": WeComWebhookError,
        "FeishuWebhookError": FeishuWebhookError,
        "SMSServiceError": SMSServiceError,
        "DataValidationError": DataValidationError,
        "ReconciliationMismatchError": ReconciliationMismatchError,
        "TenantIsolationError": TenantIsolationError,
        "BusinessRuleError": BusinessRuleError,
        "MarginViolationError": MarginViolationError,
        "FoodSafetyError": FoodSafetyError,
        "ServiceTimeoutError": ServiceTimeoutError,
        "InfrastructureError": InfrastructureError,
        "CacheConnectionError": CacheConnectionError,
        "VectorDBError": VectorDBError,
        "ModelRouterError": ModelRouterError,
        "AgentError": AgentError,
        "AgentDecisionError": AgentDecisionError,
        "AgentConstraintViolation": AgentConstraintViolation,
    }


# ---------------------------------------------------------------------------
# 基本实例化与 context
# ---------------------------------------------------------------------------

class TestTunxiangBaseError:
    def test_instantiate_with_message(self):
        from shared.core.exceptions import TunxiangBaseError
        err = TunxiangBaseError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.message == "something went wrong"

    def test_default_context_is_empty_dict(self):
        from shared.core.exceptions import TunxiangBaseError
        err = TunxiangBaseError("oops")
        assert err.context == {}

    def test_custom_context(self):
        from shared.core.exceptions import TunxiangBaseError
        ctx = {"store_id": "S001", "amount": 12345}
        err = TunxiangBaseError("oops", context=ctx)
        assert err.context["store_id"] == "S001"
        assert err.context["amount"] == 12345

    def test_has_timestamp(self):
        from shared.core.exceptions import TunxiangBaseError
        err = TunxiangBaseError("oops")
        assert err.timestamp is not None
        assert isinstance(err.timestamp, str)

    def test_is_exception_subclass(self):
        from shared.core.exceptions import TunxiangBaseError
        assert issubclass(TunxiangBaseError, Exception)


# ---------------------------------------------------------------------------
# to_dict() 序列化
# ---------------------------------------------------------------------------

class TestToDict:
    def test_to_dict_keys(self):
        from shared.core.exceptions import TunxiangBaseError
        err = TunxiangBaseError("fail", context={"key": "val"})
        d = err.to_dict()
        assert set(d.keys()) == {"error_type", "message", "context", "timestamp"}

    def test_to_dict_error_type(self):
        from shared.core.exceptions import PinzhiAPIError
        err = PinzhiAPIError("timeout", context={"url": "/api/orders"})
        d = err.to_dict()
        assert d["error_type"] == "PinzhiAPIError"
        assert d["message"] == "timeout"
        assert d["context"]["url"] == "/api/orders"

    def test_to_dict_on_leaf_class(self):
        from shared.core.exceptions import AgentConstraintViolation
        err = AgentConstraintViolation("budget exceeded", context={"budget": 5000})
        d = err.to_dict()
        assert d["error_type"] == "AgentConstraintViolation"
        assert d["context"]["budget"] == 5000


# ---------------------------------------------------------------------------
# TenantIsolationError 自动 logger.critical
# ---------------------------------------------------------------------------

class TestTenantIsolationError:
    def test_logs_critical_on_init(self):
        with patch("shared.core.exceptions.logger") as mock_logger:
            from shared.core.exceptions import TenantIsolationError
            TenantIsolationError(
                "跨租户访问",
                context={"source_tenant": "T001", "target_tenant": "T002"},
            )
            mock_logger.critical.assert_called_once()
            call_args = mock_logger.critical.call_args
            assert call_args[0][0] == "tenant_isolation_violation"
            assert call_args[1]["error_message"] == "跨租户访问"

    def test_is_tunxiang_base_error(self):
        with patch("shared.core.exceptions.logger"):
            from shared.core.exceptions import TenantIsolationError, TunxiangBaseError
            err = TenantIsolationError("breach")
            assert isinstance(err, TunxiangBaseError)

    def test_to_dict_works(self):
        with patch("shared.core.exceptions.logger"):
            from shared.core.exceptions import TenantIsolationError
            err = TenantIsolationError("breach", context={"detail": "x"})
            d = err.to_dict()
            assert d["error_type"] == "TenantIsolationError"


# ---------------------------------------------------------------------------
# 继承关系 (isinstance)
# ---------------------------------------------------------------------------

class TestInheritanceHierarchy:
    """验证完整的继承树"""

    def test_external_api_errors(self):
        from shared.core.exceptions import (
            AoqiweiAPIError,
            ExternalAPIError,
            FeishuWebhookError,
            MeituanAPIError,
            PinzhiAPIError,
            POSAdapterError,
            SMSServiceError,
            TunxiangBaseError,
            WeComWebhookError,
        )
        # POSAdapterError 子类
        for cls in [PinzhiAPIError, AoqiweiAPIError, MeituanAPIError]:
            err = cls("test")
            assert isinstance(err, POSAdapterError)
            assert isinstance(err, ExternalAPIError)
            assert isinstance(err, TunxiangBaseError)
            assert isinstance(err, Exception)

        # ExternalAPIError 直接子类
        for cls in [WeComWebhookError, FeishuWebhookError, SMSServiceError]:
            err = cls("test")
            assert isinstance(err, ExternalAPIError)
            assert isinstance(err, TunxiangBaseError)
            assert not isinstance(err, POSAdapterError)

    def test_data_validation_errors(self):
        from shared.core.exceptions import (
            DataValidationError,
            ReconciliationMismatchError,
            TunxiangBaseError,
        )
        err = ReconciliationMismatchError("mismatch")
        assert isinstance(err, DataValidationError)
        assert isinstance(err, TunxiangBaseError)

    def test_business_rule_errors(self):
        from shared.core.exceptions import (
            BusinessRuleError,
            FoodSafetyError,
            MarginViolationError,
            ServiceTimeoutError,
            TunxiangBaseError,
        )
        for cls in [MarginViolationError, FoodSafetyError, ServiceTimeoutError]:
            err = cls("test")
            assert isinstance(err, BusinessRuleError)
            assert isinstance(err, TunxiangBaseError)

    def test_infrastructure_errors(self):
        from shared.core.exceptions import (
            CacheConnectionError,
            InfrastructureError,
            ModelRouterError,
            TunxiangBaseError,
            VectorDBError,
        )
        for cls in [CacheConnectionError, VectorDBError, ModelRouterError]:
            err = cls("test")
            assert isinstance(err, InfrastructureError)
            assert isinstance(err, TunxiangBaseError)

    def test_agent_errors(self):
        from shared.core.exceptions import (
            AgentConstraintViolation,
            AgentDecisionError,
            AgentError,
            TunxiangBaseError,
        )
        for cls in [AgentDecisionError, AgentConstraintViolation]:
            err = cls("test")
            assert isinstance(err, AgentError)
            assert isinstance(err, TunxiangBaseError)

    def test_tenant_isolation_is_direct_child(self):
        with patch("shared.core.exceptions.logger"):
            from shared.core.exceptions import TenantIsolationError, TunxiangBaseError
            err = TenantIsolationError("breach")
            assert isinstance(err, TunxiangBaseError)
            from shared.core.exceptions import (
                AgentError,
                BusinessRuleError,
                ExternalAPIError,
                InfrastructureError,
            )
            assert not isinstance(err, ExternalAPIError)
            assert not isinstance(err, BusinessRuleError)
            assert not isinstance(err, InfrastructureError)
            assert not isinstance(err, AgentError)


# ---------------------------------------------------------------------------
# 全部异常可实例化
# ---------------------------------------------------------------------------

class TestAllExceptionsInstantiable:
    def test_all_classes_instantiate_with_context(self, all_exception_classes):
        ctx = {"test_key": "test_value"}
        for name, cls in all_exception_classes.items():
            if name == "TenantIsolationError":
                with patch("shared.core.exceptions.logger"):
                    err = cls("test msg", context=ctx)
            else:
                err = cls("test msg", context=ctx)
            assert err.message == "test msg", f"{name} message mismatch"
            assert err.context["test_key"] == "test_value", f"{name} context mismatch"
            assert hasattr(err, "timestamp"), f"{name} missing timestamp"
