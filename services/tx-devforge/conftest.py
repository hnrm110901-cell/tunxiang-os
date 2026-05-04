"""conftest.py — 本地测试路径配置

容器路径：/app/services/tx_devforge/src/  PYTHONPATH=/app
本地路径：services/tx-devforge/src/       (目录名含 dash)

策略：
  1. ROOT 加入 path -> shared.ontology 等
  2. SRC 加入 path  -> from api.xxx / from models.xxx / from src.xxx 等 import
  3. 创建 services.tx_devforge.src 命名空间包 -> 支持 from services.tx_devforge.src.xxx import
     (保持和容器一致的全路径 import，相对 import from ..models.xxx 也能正确解析)
"""

from __future__ import annotations

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)  # services/tx-devforge/
SRC_DIR = os.path.join(SVC_DIR, "src")  # services/tx-devforge/src/

# 1. ROOT 先入 path（shared.ontology 等跨服务包）
for p in [ROOT, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_ns(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]  # type: ignore[assignment]
        mod.__package__ = name
        sys.modules[name] = mod
    elif not hasattr(sys.modules[name], "__path__"):
        # 已存在但不是包，替换为命名空间包
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


# 2. tx_devforge 包（注意：不动顶级 services，避免冲突）
_ensure_ns("services.tx_devforge", SVC_DIR)
_ensure_ns("services.tx_devforge.src", SRC_DIR)

for _sub in ("api", "models", "repositories", "schemas", "middlewares", "utils"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_devforge.src.{_sub}", _sub_path)
