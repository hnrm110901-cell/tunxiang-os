"""菜单配置 — re-export from gateway

直接引用 gateway 的 menu_config 模块。
"""

import os
import sys

_gateway_src = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "gateway", "src")
if os.path.isdir(_gateway_src) and _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)

try:
    from menu_config import MenuConfig, generate_menu_for_tenant  # noqa: F401
except ImportError:
    generate_menu_for_tenant = None
    MenuConfig = None
