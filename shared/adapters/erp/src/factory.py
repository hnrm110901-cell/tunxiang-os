"""ERP 适配器工厂 — 按 erp_type 字符串实例化对应适配器

用法：
    adapter = get_erp_adapter("kingdee")
    adapter = get_erp_adapter("yonyou")
"""
from __future__ import annotations

from .base import ERPAdapter, ERPType
from .kingdee_adapter import KingdeeAdapter
from .yonyou_adapter import YonyouAdapter


def get_erp_adapter(erp_type: str) -> ERPAdapter:
    """工厂函数：按 ERP 类型返回对应适配器实例

    Args:
        erp_type: ERP 系统类型字符串，支持 "kingdee" / "yonyou"

    Returns:
        对应适配器实例（懒初始化，首次调用时从环境变量读取配置）

    Raises:
        ValueError: 不支持的 ERP 类型
        KeyError: 缺少必要的环境变量（由适配器构造函数抛出）
    """
    normalized = erp_type.strip().lower()
    if normalized == ERPType.KINGDEE.value:
        return KingdeeAdapter()
    if normalized == ERPType.YONYOU.value:
        return YonyouAdapter()
    raise ValueError(
        f"不支持的 ERP 类型: {erp_type!r}。"
        f"支持的类型: {[e.value for e in ERPType]}"
    )
