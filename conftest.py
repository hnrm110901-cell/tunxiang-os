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

跨服务 collision warning（Issue #501 Phase 1）
============================================
多个服务有同名 `.py` 文件时（如 invoice_service.py 同时存在于 tx-trade 和 tx-finance），
bare-NS `from services.X import ...` 按 __path__ 顺序解析到 alphabetically-first
service — 可能与开发者意图不符。本 conftest 启动时 emit advisory warning，
推荐 FQN 形式 `from services.<svc>.src.services.X import ...`。
"""

import os
import sys
import types
import warnings

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERVICES_DIR = os.path.join(_REPO_ROOT, "services")


class ServicesNamespaceCollision(UserWarning):
    """Bare-NS `services.X` import 可能解析到 alphabetically-first 服务（Issue #501）。

    专用 category 让未来 `filterwarnings = ["error", "ignore::conftest.ServicesNamespaceCollision"]`
    选择性放行（避免与其他 UserWarning 误伤）。
    """


_COLLISION_WARNED = False


def _collect_src_services_dirs() -> list[str]:
    paths = []
    if os.path.isdir(_SERVICES_DIR):
        for entry in sorted(os.listdir(_SERVICES_DIR)):
            candidate = os.path.join(_SERVICES_DIR, entry, "src", "services")
            if os.path.isdir(candidate):
                paths.append(candidate)
    return paths


def _warn_on_collisions(services_dirs: list[str]) -> None:
    """检测跨服务同名 service file — bare-NS imports silent 错调风险（Issue #501）。

    Root conftest 把所有 `services/<svc>/src/services/` 合并入顶级 `services`
    namespace `__path__`。当多个服务有同名 `.py` 文件时，bare-NS 形式
    `from services.X import ...` 会按 `__path__` 顺序解析到 alphabetically-first
    服务 — 与开发者意图可能不符（PR #497 reviewer 揭示 tx-org test_approval_engine.py
    一直 silently import tx-ops 的 approval_engine.py 真实例）。

    本函数 emit collision warning 让开发者意识到风险，并推荐 FQN 形式
    `from services.<svc>.src.services.X import ...` 避免歧义。

    Advisory only — 不阻塞 import，仅 warn。
    """
    global _COLLISION_WARNED
    if _COLLISION_WARNED:
        # 防 pytest-xdist worker / 多次 import 重复 emit
        return
    _COLLISION_WARNED = True

    seen: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for svc_services_dir in services_dirs:
        for f in os.listdir(svc_services_dir):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            if f in seen:
                collisions.setdefault(f, [seen[f]]).append(svc_services_dir)
            else:
                seen[f] = svc_services_dir
    for f, dirs in collisions.items():
        rel_dirs = [os.path.relpath(d, _REPO_ROOT) for d in dirs]
        warnings.warn(
            f"namespace collision: '{f}' exists in {len(dirs)} services "
            f"({', '.join(rel_dirs)}) — bare-NS import "
            f"'from services.{f[:-3]} import ...' may silently resolve to wrong "
            f"service. Use FQN: 'from services.<svc>.src.services.{f[:-3]} "
            f"import ...'. See issue #501.",
            ServicesNamespaceCollision,
            stacklevel=2,
        )


def _patch_services_namespace() -> None:
    extra = _collect_src_services_dirs()
    if not extra:
        return

    _warn_on_collisions(extra)

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
