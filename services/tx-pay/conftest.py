"""conftest.py — tx-pay 本地测试路径配置

容器路径：/app/services/tx_pay/src/   PYTHONPATH=/app
本地路径：services/tx-pay/src/         (目录名含 dash)

策略与 tx-trade/conftest.py 一致：
  1. ROOT 加入 path → shared.ontology 等
  2. SRC 加入 path  → from api.xxx / from models.xxx 等裸 import
  3. 建立 services.tx_pay / services.tx_pay.src 命名空间包，让
     `from services.tx_pay.src.main import app` 之类容器风格 import 也能在本地解析
"""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)        # services/tx-pay/
SRC_DIR = os.path.join(SVC_DIR, "src")     # services/tx-pay/src/

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


_ensure_ns("services.tx_pay", SVC_DIR)
_ensure_ns("services.tx_pay.src", SRC_DIR)

for _sub in ("api", "channels", "models", "orchestrator", "protocols", "routing"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_pay.src.{_sub}", _sub_path)
