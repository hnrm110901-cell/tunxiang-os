"""Repo-root conftest — pytest collection 兼容层

问题背景
========
仓库根 services/ 目录含 dash 子目录（services/tx-trade, services/tx-pay 等），
都不是合法 Python identifier。pytest 在 --import-mode=importlib 下从 rootdir
向下走目录时会预注册 sys.modules["services"] 为 namespace package，
__path__ = [REPO_ROOT/services]。

但每个微服务的 `src/services/` 又是一个**正规** Python 包，里面是裸模块
（如 banquet_payment_service.py、payroll_engine_v3.py、kds_actions.py 等）。
测试代码常用 `from services.banquet_payment_service import ...` 这种容器风格
裸 import — 在容器（PYTHONPATH=/app, 路径 /app/services/banquet_payment_service.py）下
能解析，但 pytest 预注册的 services namespace 只指向仓库根而不指向各服务 src/services/，
裸 import 全部 ModuleNotFoundError。

修复
====
本 conftest 在 pytest 启动期把所有 `services/<svc>/src/services/` 追加到
顶级 services namespace 的 __path__，让裸 import 能解析回正确文件。

这是 CI infra 修复（不改业务代码）— Issue #220 root cause #4。
"""

import os
import sys
import types

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERVICES_DIR = os.path.join(_REPO_ROOT, "services")


def _collect_src_services_dirs() -> list[str]:
    paths = []
    if os.path.isdir(_SERVICES_DIR):
        for entry in sorted(os.listdir(_SERVICES_DIR)):
            candidate = os.path.join(_SERVICES_DIR, entry, "src", "services")
            if os.path.isdir(candidate):
                paths.append(candidate)
    return paths


def _patch_services_namespace() -> None:
    extra = _collect_src_services_dirs()
    if not extra:
        return

    pkg = sys.modules.get("services")
    if pkg is None:
        # pytest hasn't pre-registered yet — create namespace pkg ourselves
        pkg = types.ModuleType("services")
        pkg.__path__ = [_SERVICES_DIR, *extra]
        pkg.__package__ = "services"
        sys.modules["services"] = pkg
        return

    if not hasattr(pkg, "__path__"):
        # pkg cached as regular module (test stub) — replace with namespace pkg
        pkg = types.ModuleType("services")
        pkg.__path__ = [_SERVICES_DIR, *extra]
        pkg.__package__ = "services"
        sys.modules["services"] = pkg
        return

    existing = list(pkg.__path__)
    for p in extra:
        if p not in existing:
            pkg.__path__.append(p)


_patch_services_namespace()
