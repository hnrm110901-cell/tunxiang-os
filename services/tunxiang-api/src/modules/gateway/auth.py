"""认证服务 — re-export from gateway

直接引用 gateway 的 auth 模块，不复制代码。
"""
import sys
import os

# Ensure gateway src is importable
_gateway_src = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "gateway", "src"
)
if os.path.isdir(_gateway_src) and _gateway_src not in sys.path:
    sys.path.insert(0, _gateway_src)

try:
    from auth import router as auth_router, DEMO_USERS, LoginBody  # noqa: F401
except ImportError:
    # Fallback: gateway not available in this environment
    auth_router = None
    DEMO_USERS = {}
    LoginBody = None
