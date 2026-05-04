"""shared/service_utils — 跨 service 共用工具

现在只暴露 auto_mount；未来可加更多 service bootstrap 工具。
"""

from .auto_mount import (
    STRICT_ENV_VAR,
    MountResult,
    RouteMountError,
    auto_mount_routes,
    mount_report,
    validate_result,
)

__all__ = [
    "STRICT_ENV_VAR",
    "MountResult",
    "RouteMountError",
    "auto_mount_routes",
    "mount_report",
    "validate_result",
]
