"""shared.adapters.config — 多系统凭证配置 Pydantic 模型"""
from .multi_system_config import (
    AoqiweiCrmConfig,
    AoqiweiSupplyConfig,
    PinzhiConfig,
    TenantSystemsConfig,
    YidingConfig,
)

__all__ = [
    "PinzhiConfig",
    "AoqiweiCrmConfig",
    "AoqiweiSupplyConfig",
    "YidingConfig",
    "TenantSystemsConfig",
]
