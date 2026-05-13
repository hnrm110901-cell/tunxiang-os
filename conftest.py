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

跨服务 collision enforcement（Issue #501 Phase 2）
================================================
Phase 1 advisory warning 仍保留。Phase 2 加 MetaPathFinder enforcer 注册到
`sys.meta_path[0]`：当 `from services.X import ...` 且 X ∈
COLLISION_BASENAMES（12 个跨服务同名模块）→ raise ImportError，要求用 FQN
`from services.<svc>.src.services.X import ...`。

例外文件 _NOQA_ALLOWED_FILES（test_approval_engine.py / test_auto_procurement.py）
保留 bare-NS 形式（pre-existing noqa 标记，PR #494/#497 留下）。
"""

import importlib.abc
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


# Phase 2 enforcement set — 12 cross-service collision basenames (no __init__.py).
# Hardcoded per Issue #501 Phase 2 (A1 decision): explicit list beats dynamic
# computation; surgical change; 12 groups churn slowly. If new collision groups
# are introduced, update this set manually + add Tier 2 test coverage.
# Source: `ls services/*/src/services/*.py | basename | sort | uniq -c | $1>1` on
# main `6ab4cbd1` (2026-05-13).
COLLISION_BASENAMES: frozenset[str] = frozenset({
    "approval_engine",
    "approval_service",
    "budget_forecast_service",
    "budget_service",
    "cost_root_cause_service",
    "coupon_service",
    "dish_margin",
    "gdpr_service",
    "invoice_service",       # Tier 1 (tx-trade + tx-finance) — currently 0 bare-NS hits in repo
    "notification_service",
    "repository",            # Heaviest: 4 services
    "report_engine",
})

# Phase 2 allowlist — pre-existing noqa-marked bare-NS imports to preserve.
# These files intentionally use bare-NS form per PR #494 (tx-supply auto_procurement
# dual-load reverse) and PR #497 (tx-org approval_engine collision root cause).
# Phase 3 (file rename) will eliminate the root cause and these can be removed.
_NOQA_ALLOWED_FILES: frozenset[str] = frozenset({
    "test_approval_engine.py",  # tx-org #497 留 noqa
    "test_auto_procurement.py",  # tx-supply #494 留 noqa (dual-load, 对称保留)
})


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


class _CollisionEnforcer(importlib.abc.MetaPathFinder):
    """Block bare-NS imports of collision-prone modules (Issue #501 Phase 2).

    `from services.X import ...` where X ∈ COLLISION_BASENAMES resolves to
    alphabetically-first service via the merged namespace `__path__` order —
    silent wrong-service risk (PR #497 reviewer confirmed tx-org's
    `test_approval_engine.py` was loading tx-ops's `approval_engine.py` for
    months, despite the test's intent of testing tx-org's).

    Phase 1 (#509) emitted advisory warning at startup. Phase 2 raises
    `ImportError` at import time unless the caller frame's file is in
    `_NOQA_ALLOWED_FILES` (preserves intentional bare-NS in pre-existing
    noqa-marked files).

    FQN form `from services.<svc>.src.services.X import ...` (5+ segments)
    bypasses this enforcer — `find_spec` only intercepts exactly 2-segment
    `services.X`.
    """

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        # Only intercept exactly `services.X` (2-segment bare-NS form)
        if len(parts) != 2 or parts[0] != "services":
            return None
        if parts[1] not in COLLISION_BASENAMES:
            return None
        # Allowlist: walk caller frames; if any frame's file basename is in
        # _NOQA_ALLOWED_FILES, bypass. This handles direct module-body imports
        # (the typical noqa case) as well as indirect re-imports via the same
        # allowed file.
        frame = sys._getframe(1)
        while frame is not None:
            caller_file = os.path.basename(frame.f_code.co_filename)
            if caller_file in _NOQA_ALLOWED_FILES:
                return None
            frame = frame.f_back
        raise ImportError(
            f"bare-NS `import {fullname}` blocked: '{parts[1]}' is in "
            f"{len(COLLISION_BASENAMES)}-name collision set "
            f"(silent wrong-service risk per Issue #501). Use FQN: "
            f"`from services.<svc>.src.services.{parts[1]} import ...`."
        )


_ENFORCER_INSTALLED = False


def _install_collision_enforcer() -> None:
    """Register _CollisionEnforcer at sys.meta_path[0] (highest priority).

    Idempotent — safe to call multiple times (pytest-xdist workers, conftest
    re-imports). Installs at front to intercept before any path-based finder.
    """
    global _ENFORCER_INSTALLED
    if _ENFORCER_INSTALLED:
        return
    _ENFORCER_INSTALLED = True
    if not any(isinstance(f, _CollisionEnforcer) for f in sys.meta_path):
        sys.meta_path.insert(0, _CollisionEnforcer())


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
_install_collision_enforcer()
