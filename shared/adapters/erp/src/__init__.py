"""ERP 适配器包 — 金蝶 / 用友统一接口层

用法示例：
    from shared.adapters.erp.src import (
        ERPAdapter, ERPVoucher, ERPVoucherEntry,
        ERPAccount, ERPPushResult, ERPType, VoucherType,
        KingdeeAdapter, YonyouAdapter, get_erp_adapter,
    )

    adapter = get_erp_adapter(erp_type="kingdee")
    result = await adapter.push_voucher(voucher)
"""
from .base import (
    ERPAdapter,
    ERPAccount,
    ERPPushResult,
    ERPType,
    ERPVoucher,
    ERPVoucherEntry,
    PushStatus,
    VoucherType,
)
from .kingdee_adapter import KingdeeAdapter
from .yonyou_adapter import YonyouAdapter
from .factory import get_erp_adapter

__all__ = [
    # 基类 & 数据模型
    "ERPAdapter",
    "ERPAccount",
    "ERPPushResult",
    "ERPType",
    "ERPVoucher",
    "ERPVoucherEntry",
    "PushStatus",
    "VoucherType",
    # 具体实现
    "KingdeeAdapter",
    "YonyouAdapter",
    # 工厂
    "get_erp_adapter",
]
