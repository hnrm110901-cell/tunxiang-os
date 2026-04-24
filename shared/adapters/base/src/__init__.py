"""API适配器基础模块"""

try:
    from .adapter import APIError, BaseAdapter
    from .event_bus import AdapterEventMixin, SyncTrack, emit_adapter_event
    from .mapper import DataMapper
    from .registry import (
        ADAPTER_CATEGORIES,
        DELIVERY_REGISTRY,
        FINANCE_REGISTRY,
        MEMBER_REGISTRY,
        POS_REGISTRY,
        RESERVATION_REGISTRY,
        SUPPLY_CHAIN_REGISTRY,
        AdapterNotImplementedError,
        get_adapter,
        get_transformer,
        list_all_categories,
        list_category_types,
        list_implemented_pos_types,
        list_registered_pos_types,
    )

    __all__ = [
        "BaseAdapter",
        "APIError",
        "AdapterEventMixin",
        "SyncTrack",
        "emit_adapter_event",
        "DataMapper",
        "POS_REGISTRY",
        "RESERVATION_REGISTRY",
        "DELIVERY_REGISTRY",
        "SUPPLY_CHAIN_REGISTRY",
        "MEMBER_REGISTRY",
        "FINANCE_REGISTRY",
        "ADAPTER_CATEGORIES",
        "AdapterNotImplementedError",
        "get_transformer",
        "get_adapter",
        "list_registered_pos_types",
        "list_implemented_pos_types",
        "list_all_categories",
        "list_category_types",
    ]
except ImportError:
    # 依赖未安装时（如仅运行类型测试），允许降级加载
    __all__ = []
