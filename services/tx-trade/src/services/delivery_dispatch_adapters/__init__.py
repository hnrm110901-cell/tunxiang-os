"""配送商适配器 — 达达 / 顺丰同城 / 自有骑手

统一接口：dispatch / cancel / query_location / notify_pickup_ready

工厂方法 `get_adapter(provider, store_config)` 按 provider 字符串返回对应实例。

接入路线（务实）：
- 当前所有 adapter 返回 mock 结果，但接口契约完整（DispatchResult / RiderLocation）
- 接入真实 API 时，仅替换 dispatch / query_location 内部 HTTP 调用即可
"""

from .base import (
    BaseDeliveryDispatchAdapter,
    DispatchOrderInput,
    DispatchResult,
    ProviderConfigSnapshot,
    RiderLocation,
)
from .dada_adapter import DadaAdapter
from .own_rider_adapter import OwnRiderAdapter
from .sf_express_adapter import SfExpressAdapter

PROVIDER_ADAPTER_MAP: dict[str, type[BaseDeliveryDispatchAdapter]] = {
    "dada": DadaAdapter,
    "shunfeng": SfExpressAdapter,
    "self_rider": OwnRiderAdapter,
}


def get_adapter(
    provider: str,
    store_config: ProviderConfigSnapshot,
) -> BaseDeliveryDispatchAdapter:
    """按 provider 字符串返回对应 adapter 实例。

    Raises:
        ValueError: 未知 provider
    """
    cls = PROVIDER_ADAPTER_MAP.get(provider)
    if cls is None:
        raise ValueError(f"unknown delivery provider: {provider!r}, valid: {list(PROVIDER_ADAPTER_MAP)}")
    return cls(store_config)


__all__ = [
    "BaseDeliveryDispatchAdapter",
    "DadaAdapter",
    "DispatchOrderInput",
    "DispatchResult",
    "OwnRiderAdapter",
    "PROVIDER_ADAPTER_MAP",
    "ProviderConfigSnapshot",
    "RiderLocation",
    "SfExpressAdapter",
    "get_adapter",
]
