"""pytest path + env setup for meituan-saas tests.

历史：aab1a5b9 修复 import collection 失败 — 把 `meituan-saas/`（src 的父目录）
放 sys.path，让 src 作为 package 加载；test 用 `from src.adapter import ...`。

CH-02.7a a3 起 saas/src/client.py 已删，adapter.py 直接 import 顶层
`shared.adapters.meituan_delivery_adapter`；本 conftest 仍负责 src 作为 package
加载，但相对 `.client` 不再存在。整个 meituan-saas/ 子目录在 a4 移除。
"""

from __future__ import annotations

import os
import sys

_here = os.path.dirname(__file__)
_meituan_saas_root = os.path.abspath(os.path.join(_here, ".."))   # shared/adapters/meituan-saas/
_repo_root = os.path.abspath(os.path.join(_here, "../../../.."))  # repo root
_gateway_src = os.path.join(_repo_root, "apps", "api-gateway", "src")

for path in (_meituan_saas_root, _gateway_src):
    if path not in sys.path:
        sys.path.insert(0, path)

# import src 前设置 env 防 pydantic-settings 校验失败（沿用原 test 模式）
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
