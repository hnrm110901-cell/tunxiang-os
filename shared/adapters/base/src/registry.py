"""
POS 适配器注册表

提供工厂函数 get_transformer()，按 pos_type 返回对应适配器实例。
新增 POS 系统只需：
  1. 实现 to_order() 和 to_staff_action()
  2. 在 POS_REGISTRY 中注册

不需要修改任何业务逻辑代码。
"""

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

# POS 系统注册表（pos_type → 适配器类路径）
# None 表示尚未实现，调用时会返回 NotImplementedError（有明确错误提示）
#
# 路径切换（#434 第 3 项）：原 `packages.api-adapters.*` 全 repo 不存在
# （packages/ 下仅 tx-tokens/ + tx-touch/），切到真实路径 `shared.adapters.*`。
POS_REGISTRY: Dict[str, Optional[str]] = {
    "aoqiwei": "shared.adapters.aoqiwei.src.adapter.AoqiweiAdapter",
    "pinzhi": "shared.adapters.pinzhi_pos.src.adapter.PinzhiAdapter",
    "meituan": "shared.adapters.meituan_saas_adapter.MeituanSaasAdapter",
    # TODO: tiancai-shanglong/ 目录名含 `-`，importlib 调用 `replace("-","_")` 后
    # 找不到目录（fs 为 tiancai-shanglong/，import 名为 tiancai_shanglong）。
    # 需独立目录重命名 PR（`git mv tiancai-shanglong tiancai_shanglong` +
    # 同步改 services/gateway 下两处 importlib.import_module 引用）后启用。
    "tiancai": "shared.adapters.tiancai-shanglong.src.adapter.TiancaiShanglongAdapter",
    "keruyun": "shared.adapters.keruyun.src.adapter.KeruyunAdapter",
}


class AdapterNotImplementedError(NotImplementedError):
    """适配器未实现错误"""

    def __init__(self, pos_type: str):
        super().__init__(
            f"POS 适配器 '{pos_type}' 尚未实现。请实现 to_order() 和 to_staff_action() 后在 POS_REGISTRY 中注册。"
        )
        self.pos_type = pos_type


def get_transformer(pos_type: str, store_id: str, brand_id: str, config: Optional[Dict[str, Any]] = None):
    """
    POS 适配器工厂函数

    Args:
        pos_type: POS 系统类型（如 "aoqiwei", "pinzhi"）
        store_id: 门店ID
        brand_id: 品牌ID
        config: 适配器配置字典（base_url、api_key 等）

    Returns:
        BaseAdapter 子类实例

    Raises:
        ValueError: pos_type 不在注册表中
        AdapterNotImplementedError: 适配器尚未实现（在注册表中但值为 None）
    """
    if pos_type not in POS_REGISTRY:
        registered = list(POS_REGISTRY.keys())
        raise ValueError(f"未知的 POS 系统类型: '{pos_type}'。已注册类型: {registered}")

    adapter_path = POS_REGISTRY[pos_type]
    if adapter_path is None:
        raise AdapterNotImplementedError(pos_type)

    # 动态导入适配器类
    module_path, class_name = adapter_path.rsplit(".", 1)
    # 将包路径中的 - 替换为 _ 以兼容 Python 模块命名
    module_path = module_path.replace("-", "_")

    import importlib

    try:
        module = importlib.import_module(module_path)
        adapter_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        logger.error("适配器加载失败", pos_type=pos_type, module_path=module_path, error=str(e))
        raise ImportError(f"无法加载 POS 适配器 '{pos_type}': {e}") from e

    cfg = config or {}
    cfg.setdefault("store_id", store_id)
    cfg.setdefault("brand_id", brand_id)

    logger.info("POS 适配器实例化", pos_type=pos_type, store_id=store_id, brand_id=brand_id)
    return adapter_class(cfg)


def list_registered_pos_types() -> list:
    """返回所有已注册的 POS 系统类型（包括未实现的）"""
    return list(POS_REGISTRY.keys())


def list_implemented_pos_types() -> list:
    """返回已实现的 POS 系统类型"""
    return [k for k, v in POS_REGISTRY.items() if v is not None]


# ============================================
# 预订系统注册表
# ============================================

RESERVATION_REGISTRY: Dict[str, Optional[str]] = {
    "yiding": "shared.adapters.yiding.src.adapter.YiDingAdapter",
    "kebide": None,
    "yanmishu": None,
}

# ============================================
# 外卖平台注册表
# ============================================

DELIVERY_REGISTRY: Dict[str, Optional[str]] = {
    "meituan_delivery": None,
    "eleme": "shared.adapters.eleme_open_platform.src.adapter.ElemeAdapter",
    "douyin": "shared.adapters.douyin_open_platform.src.adapter.DouyinAdapter",
}

# ============================================
# 供应链注册表
# ============================================

SUPPLY_CHAIN_REGISTRY: Dict[str, Optional[str]] = {}

# ============================================
# 会员系统注册表
# ============================================

MEMBER_REGISTRY: Dict[str, Optional[str]] = {
    "weishenghuo": "shared.adapters.weishenghuo.src.adapter.WeishenghuoAdapter",
}

# ============================================
# 财务系统注册表
# ============================================

FINANCE_REGISTRY: Dict[str, Optional[str]] = {
    "nuonuo": "shared.adapters.nuonuo.src.adapter.NuonuoAdapter",
}


# ============================================
# 统一分类注册表
# ============================================

ADAPTER_CATEGORIES = {
    "pos": POS_REGISTRY,
    "reservation": RESERVATION_REGISTRY,
    "delivery": DELIVERY_REGISTRY,
    "supply_chain": SUPPLY_CHAIN_REGISTRY,
    "member": MEMBER_REGISTRY,
    "finance": FINANCE_REGISTRY,
}


def get_adapter(category: str, system_type: str, config: Optional[Dict[str, Any]] = None):
    """
    统一适配器工厂函数

    Args:
        category: 系统类别 (pos/reservation/delivery/supply_chain/member/finance)
        system_type: 具体系统 (yiding/kebide/pinzhi/meituan/...)
        config: 适配器配置

    Returns:
        适配器实例

    Raises:
        ValueError: 类别或系统类型不在注册表中
        AdapterNotImplementedError: 适配器尚未实现
    """
    if category not in ADAPTER_CATEGORIES:
        raise ValueError(f"未知系统类别: '{category}'。可用: {list(ADAPTER_CATEGORIES.keys())}")

    registry = ADAPTER_CATEGORIES[category]

    if system_type not in registry:
        registered = list(registry.keys())
        raise ValueError(f"类别'{category}'中未注册: '{system_type}'。已注册: {registered}")

    adapter_path = registry[system_type]
    if adapter_path is None:
        raise AdapterNotImplementedError(system_type)

    module_path, class_name = adapter_path.rsplit(".", 1)
    module_path = module_path.replace("-", "_")

    import importlib

    try:
        module = importlib.import_module(module_path)
        adapter_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        logger.error("适配器加载失败", category=category, system_type=system_type, error=str(e))
        raise ImportError(f"无法加载适配器 '{category}/{system_type}': {e}") from e

    return adapter_class(config or {})


def list_all_categories() -> list:
    """返回所有系统类别"""
    return list(ADAPTER_CATEGORIES.keys())


def list_category_types(category: str) -> dict:
    """返回指定类别的所有系统类型及实现状态"""
    if category not in ADAPTER_CATEGORIES:
        raise ValueError(f"未知系统类别: '{category}'")
    registry = ADAPTER_CATEGORIES[category]
    return {k: (v is not None) for k, v in registry.items()}
