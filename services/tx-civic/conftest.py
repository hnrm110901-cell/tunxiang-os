"""conftest.py — 本地测试路径配置

容器路径：/app/services/tx_civic/src/  PYTHONPATH=/app
本地路径：services/tx-civic/src/       (目录名含 dash)

策略：
  1. ROOT 加入 path → shared.ontology 等
  2. SVC_DIR 加入 path → from src.api.xxx / from src.services.xxx 裸 import
  3. 创建 services.tx_civic.src 命名空间包
"""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)       # services/tx-civic/
SRC_DIR = os.path.join(SVC_DIR, "src")   # services/tx-civic/src/

# 1. ROOT 先入 path（shared.ontology 等跨服务包）
# 2. SVC_DIR 入 path → src 包可被 `from src.api.xxx` 找到
for p in [ROOT, SVC_DIR, SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 3. 建立 services.tx_civic / services.tx_civic.src 命名空间包
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

_ensure_ns("services.tx_civic",       SVC_DIR)
_ensure_ns("services.tx_civic.src",   SRC_DIR)

for _sub in ("api", "services", "models", "tests"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_civic.src.{_sub}", _sub_path)
