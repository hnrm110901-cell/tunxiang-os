"""conftest.py — tx-finance 本地测试路径配置

容器路径：/app/services/tx_finance/src/  PYTHONPATH=/app
本地路径:services/tx-finance/src/       (目录名含 dash)

策略（参照 services/tx-supply/conftest.py + tx-org workers 子包扩展）：
  1. ROOT 加入 path → shared.ontology 等跨服务包
  2. SRC 加入 path  → 支持裸 import
  3. 注册 services.tx_finance / .src / 子包 → 支持
     `from services.tx_finance.src.xxx import ...` 全路径写法（容器和本地一致）
"""

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SVC_DIR = os.path.dirname(__file__)  # services/tx-finance/
SRC_DIR = os.path.join(SVC_DIR, "src")  # services/tx-finance/src/

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


_ensure_ns("services.tx_finance", SVC_DIR)
_ensure_ns("services.tx_finance.src", SRC_DIR)

for _sub in ("api", "models", "services", "repositories", "tests", "routers", "workers"):
    _sub_path = os.path.join(SRC_DIR, _sub)
    if os.path.isdir(_sub_path):
        _ensure_ns(f"services.tx_finance.src.{_sub}", _sub_path)


# 3. models/ 模块身份别名 — 防 isinstance 假阴性
# 决策 77 production codemod 把 financial_voucher_service.py 等改为
# `from services.tx_finance.src.models.X import ...`，但 Tier 1 测试仍用
# `from models.X import ...`（test-side codemod 还在 #349 review 中）。
# 同一文件被加载为两个 sys.modules 条目 → isinstance 失败。
# 解决：对 models/ 子目录每个 .py，预加载裸路径并把全路径 sys.modules 别名指过去。
# 范围只限 models/（SQLAlchemy declarative，导入纯注册元数据，无业务副作用）。
import importlib

_MODELS_DIR = os.path.join(SRC_DIR, "models")
if os.path.isdir(_MODELS_DIR):
    for _f in os.listdir(_MODELS_DIR):
        if not _f.endswith(".py") or _f.startswith("_"):
            continue
        _mod_name = _f[:-3]
        _bare = f"models.{_mod_name}"
        _full = f"services.tx_finance.src.models.{_mod_name}"
        try:
            _bare_mod = importlib.import_module(_bare)
            sys.modules[_full] = _bare_mod
        except ImportError:
            pass
