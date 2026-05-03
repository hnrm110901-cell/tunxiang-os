"""shared.region.src — 屯象OS 区域化与跨境报表基础设施

Phase 3 Sprint 3.6 产物。提供多市场区域配置、跨国收入汇总、
多币种转换、跨时区运营时间查询等能力。

模块：
  region_config       — 中央区域配置（MarketRegion / RegionConfig / 4国配置）
  cross_border_report — 跨境报表服务（收入汇总 / 市场对比 / 运营时间）
"""

from .cross_border_report import CrossBorderReportService, convert_currency
from .region_config import (
    REGION_CONFIGS,
    MarketRegion,
    RegionConfig,
    get_config,
    get_config_by_code,
    get_supported_markets,
    is_market_supported,
)

__all__ = [
    # 区域枚举
    "MarketRegion",
    # 配置数据类
    "RegionConfig",
    # 配置数据字典
    "REGION_CONFIGS",
    # 配置查询接口
    "get_config",
    "get_config_by_code",
    "get_supported_markets",
    "is_market_supported",
    # 跨境报表服务
    "CrossBorderReportService",
    "convert_currency",
]
