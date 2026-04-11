"""城市适配器层 — 对接各地监管平台的统一抽象"""

from .base_city_adapter import (
    BaseCityAdapter,
    CivicPlatformAuthError,
    CivicPlatformError,
    CivicPlatformTimeoutError,
    SubmissionResult,
)
from .base_domain_adapter import BaseDomainAdapter
from .registry import CityAdapterRegistry

__all__ = [
    "BaseCityAdapter",
    "BaseDomainAdapter",
    "CityAdapterRegistry",
    "CivicPlatformAuthError",
    "CivicPlatformError",
    "CivicPlatformTimeoutError",
    "SubmissionResult",
]
