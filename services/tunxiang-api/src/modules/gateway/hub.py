"""Hub管理API — re-export from gateway

直接引用 gateway 的 hub_api 模块。
"""

import os
import sys

_gateway_src = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "gateway", "src")
if os.path.isdir(_gateway_src) and _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)

try:
    from hub_api import router as hub_router  # noqa: F401
except ImportError:
    hub_router = None
