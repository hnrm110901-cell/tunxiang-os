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
本 conftest 在 pytest 启动期：
  1. 把所有 `services/<svc>/src/services/` 追加到顶级 services namespace
     的 __path__（issue #220 root cause #4）
  2. 把 `shared` 与 `shared.adapters` 注册成 namespace package（避免 pytest
     importlib 模式下偶发缓存为非包，导致 `from shared.security.X` /
     `from shared.adapters.xiaohongshu.X` 触发 'is not a package' 错误）

这是 CI infra 修复（不改业务代码）。
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


def _patch_shared_namespace() -> None:
    """注册 shared 与 shared.adapters 为 namespace package。

    pytest --import-mode=importlib 在 collection 阶段偶发将 `shared` 缓存为
    非 package（无 __path__），导致 `from shared.security.src.X import Y` 在
    业务代码 import 链触发时报 "shared is not a package"。

    修补：启动期主动注册 shared / shared.adapters 为 namespace package，
    指向真实磁盘路径。已有 __init__.py 时不覆盖（保持原 ModuleSpec）。
    """
    shared_dir = os.path.join(_REPO_ROOT, "shared")
    if not os.path.isdir(shared_dir):
        return

    pkg = sys.modules.get("shared")
    if pkg is None or not hasattr(pkg, "__path__"):
        new_pkg = types.ModuleType("shared")
        new_pkg.__path__ = [shared_dir]
        new_pkg.__package__ = "shared"
        sys.modules["shared"] = new_pkg

    adapters_dir = os.path.join(shared_dir, "adapters")
    if os.path.isdir(adapters_dir):
        ad = sys.modules.get("shared.adapters")
        if ad is None or not hasattr(ad, "__path__"):
            ad_mod = types.ModuleType("shared.adapters")
            ad_mod.__path__ = [adapters_dir]
            ad_mod.__package__ = "shared.adapters"
            sys.modules["shared.adapters"] = ad_mod


_patch_shared_namespace()
