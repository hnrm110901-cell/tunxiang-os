"""pytest path + env setup for meituan-saas tests.

修自 aab1a5b9 起的 import collection 失败：
  原 test 用 `sys.path.insert(meituan-saas/src) + from adapter import ...`，
  但 adapter.py 内部用 `from .client import ...` 相对 import — 一致性矛盾。

修法：把 `meituan-saas/`（src 的父目录）放 sys.path，让 src 作为 package 加载。
test 改用 `from src.adapter import ...`，adapter.py 的 `.client` 相对 import 自然生效。

CH-02.7a 真正 SoT 迁移到 top-level 后本 conftest 与整个 meituan-saas/ 子目录一并删除。
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
