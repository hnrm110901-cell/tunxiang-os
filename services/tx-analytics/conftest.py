"""conftest.py — tx-analytics 本地测试路径配置

容器路径：/app/services/tx_analytics/src/  PYTHONPATH=/app
本地路径：services/tx-analytics/src/       (目录名含 dash)

策略与 tx-trade/tx-org conftest.py 一致：
  1. ROOT 加入 path → shared.ontology 等
  2. SRC 加入 path  → from services.xxx / from api.xxx 等裸 import
  3. 创建 services.tx_analytics.src 命名空间包 → 支持完整容器包路径 import
     (production code services/tx-analytics/src/reports/__init__.py 已用 FQN
     `from services.tx_analytics.src.reports import ...`，本地 pytest 也需注册)
"""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)  # services/tx-analytics/
SRC_DIR = os.path.join(SVC_DIR, "src")  # services/tx-analytics/src/

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
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_ns("services.tx_analytics", SVC_DIR)
_ensure_ns("services.tx_analytics.src", SRC_DIR)

for _sub in ("api", "models", "services", "repositories", "tests", "routers", "workers", "reports"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_analytics.src.{_sub}", _sub_path)
