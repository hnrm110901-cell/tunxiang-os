"""conftest.py — tx-supply 本地测试路径配置

容器路径：/app/services/tx_supply/src/  PYTHONPATH=/app
本地路径：services/tx-supply/src/       (目录名含 dash)

策略（参照 services/tx-trade/conftest.py）：
  1. ROOT 加入 path → shared.ontology 等跨服务包
  2. SRC 加入 path  → 支持裸 import
  3. 注册 services.tx_supply / .src / 子包 → 支持
     `from services.tx_supply.src.xxx import ...` 全路径写法（容器和本地一致）
"""

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)            # services/tx-supply/
SRC_DIR = os.path.join(SVC_DIR, "src")          # services/tx-supply/src/

# 1. ROOT + SRC 入 path
for p in [ROOT, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


# 2. 注册命名空间包（不动顶级 services，避免冲突）
def _ensure_ns(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]  # type: ignore[assignment]
        mod.__package__ = name
        sys.modules[name] = mod
    elif not hasattr(sys.modules[name], "__path__"):
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_ns("services.tx_supply", SVC_DIR)
_ensure_ns("services.tx_supply.src", SRC_DIR)

for _sub in ("api", "models", "services", "repositories", "tests", "routers"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_supply.src.{_sub}", _sub_path)
