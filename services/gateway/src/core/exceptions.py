"""屯象OS 自定义异常层级体系

使用场景：
  - 替换各服务中的 except Exception（逐步收窄）
  - 在 FastAPI 异常处理器中统一捕获并转换为 HTTP 响应
  - Agent 决策日志中记录 constraints_check 违规类型

引入方式：
  from services.gateway.src.core.exceptions import POSAdapterError, MarginViolationError
  # 或在各服务中直接 from gateway.src.core.exceptions import ...
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# 根异常
# ─────────────────────────────────────────────────────────────────────────────

class TunxiangBaseError(Exception):
    """屯象OS 根异常。所有自定义异常均继承自此类。"""

    def __init__(self, message: str, context: dict | None = None) -> None:
        self.context: dict = context or {}
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.args[0]!r}, context={self.context!r})"


# ─────────────────────────────────────────────────────────────────────────────
# 外部 API / 适配器异常
# ─────────────────────────────────────────────────────────────────────────────

class ExternalAPIError(TunxiangBaseError):
    """调用外部 API 失败（超时、认证、格式错误等）。"""


class POSAdapterError(ExternalAPIError):
    """POS 适配器异常（品智 / 奥琦玮 / 天财商龙 / 美团 SaaS 等）。"""


class WeComWebhookError(ExternalAPIError):
    """企业微信 Webhook / 消息推送异常。"""


class DeliveryPlatformError(ExternalAPIError):
    """外卖平台接口异常（美团外卖 / 饿了么 / 抖音外卖）。"""


class PaymentGatewayError(ExternalAPIError):
    """支付通道异常（微信支付 / 支付宝 / 银联）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 数据异常
# ─────────────────────────────────────────────────────────────────────────────

class DataValidationError(TunxiangBaseError):
    """数据校验失败（字段缺失、格式非法、业务规则不满足等）。"""


class ReconciliationMismatchError(DataValidationError):
    """对账不一致（预期金额与实际金额不符）。"""


class ImportParseError(DataValidationError):
    """数据导入文件解析失败（Excel / CSV 格式错误）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 安全 / 权限异常
# ─────────────────────────────────────────────────────────────────────────────

class TenantIsolationError(TunxiangBaseError):
    """租户隔离违规——安全事件，必须记录到 audit_logs。"""


class PermissionDeniedError(TunxiangBaseError):
    """权限不足（操作需要特定角色或显式授权）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 业务规则异常（对应三条硬约束）
# ─────────────────────────────────────────────────────────────────────────────

class BusinessRuleError(TunxiangBaseError):
    """业务规则违规基类。Agent 决策必须通过三条硬约束校验。"""


class MarginViolationError(BusinessRuleError):
    """毛利底线违规——折扣/赠送导致单笔毛利低于阈值（硬约束①）。"""


class FoodSafetyError(BusinessRuleError):
    """食安合规违规——临期/过期食材用于出品（硬约束②）。"""


class ServiceTimeoutError(BusinessRuleError):
    """出餐时限违规——出餐时间超过门店设定上限（硬约束③）。"""


# ─────────────────────────────────────────────────────────────────────────────
# 基础设施异常
# ─────────────────────────────────────────────────────────────────────────────

class CacheConnectionError(TunxiangBaseError):
    """Redis / 缓存连接失败（可降级处理）。"""


class DatabaseError(TunxiangBaseError):
    """数据库操作失败（连接中断、事务回滚等）。"""


class EdgeSyncError(TunxiangBaseError):
    """Mac mini 本地 PG ↔ 云端 PG 同步失败。"""


# ─────────────────────────────────────────────────────────────────────────────
# 公开导出
# ─────────────────────────────────────────────────────────────────────────────

__all__ = [
    "TunxiangBaseError",
    # 外部 API
    "ExternalAPIError",
    "POSAdapterError",
    "WeComWebhookError",
    "DeliveryPlatformError",
    "PaymentGatewayError",
    # 数据
    "DataValidationError",
    "ReconciliationMismatchError",
    "ImportParseError",
    # 安全
    "TenantIsolationError",
    "PermissionDeniedError",
    # 业务规则（三条硬约束）
    "BusinessRuleError",
    "MarginViolationError",
    "FoodSafetyError",
    "ServiceTimeoutError",
    # 基础设施
    "CacheConnectionError",
    "DatabaseError",
    "EdgeSyncError",
]
