"""商户经营目标配置 — 从 shared/merchant_targets 导入

保持此文件作为服务级入口点，实际数据源在 shared/merchant_targets。
"""

# 重新导出共享配置（实际数据源在 shared/merchant_targets）
from shared.merchant_targets import (  # noqa: F401 — re-export
    DEFAULT_TARGETS,
    KPI_LABELS,
    LOWER_IS_BETTER,
    SUPPORTED_MERCHANTS,
)
