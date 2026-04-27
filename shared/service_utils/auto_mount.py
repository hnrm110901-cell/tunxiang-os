"""自动挂载路由模块（容错版）

背景：
  多个 OPEN PR（D3a / D3b / D3c / D4a / D4b / D4c / E1 / E2 / E3 / E4 / G）
  各自引入了新的 `api/*_routes.py` 模块。合入顺序不确定，且合入后需要有人
  手动改各 service 的 `main.py` 去 `include_router`。

本模块提供 `auto_mount_routes`：
  · 接受一个 FastAPI `app` + 一份 `(module_name, router_attr)` 清单
  · 如果模块文件存在 → import + include_router + 记录成功
  · 如果文件不存在 → 跳过（DEBUG 日志）
  · 如果文件存在但 import 失败 → WARNING 日志 + 不阻塞 service 启动
    （生产环境不允许静默失败：加载失败时可选择 `strict=True` 抛异常）

使用约定：
  每个 service 在 main.py 末尾（include_router 块后 + @app.get("/health") 前）
  插入一小段：

      from shared.service_utils import auto_mount_routes
      auto_mount_routes(
          app,
          pkg=__package__,            # 或 "src" 若绝对 import 风格
          api_dir=Path(__file__).parent / "api",
          modules=[
              ("canonical_delivery_routes", "router"),
              ("dish_publish_routes", "router"),
              ...
          ],
      )

服务 main.py 不需要知道哪些 module 一定存在；本函数只 mount "现在存在" 的。

测试：shared/service_utils/tests/test_auto_mount.py
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class MountResult:
    """auto_mount_routes 返回的报告"""

    mounted: list[str] = field(default_factory=list)   # 成功挂载
    skipped: list[str] = field(default_factory=list)   # 模块文件不存在
    failed: list[tuple[str, str]] = field(default_factory=list)  # (module, reason)

    @property
    def total(self) -> int:
        return len(self.mounted) + len(self.skipped) + len(self.failed)

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "mounted": list(self.mounted),
            "skipped": list(self.skipped),
            "failed": [{"module": m, "reason": r} for m, r in self.failed],
            "total": self.total,
            "ok": self.ok,
        }


def auto_mount_routes(
    app: Any,
    *,
    pkg: Optional[str],
    api_dir: Path,
    modules: Iterable[tuple[str, str]],
    strict: bool = False,
) -> MountResult:
    """为 FastAPI `app` 自动挂载存在的路由模块

    Args:
      app: FastAPI 实例（需 `include_router(router)` 方法）
      pkg: Python 包路径（如 `"services.tx_trade.src"` 或调用方的 `__package__`）
           若为 None 则用绝对 import（`api.X` 而非 `.api.X`）
      api_dir: API 模块所在目录（检查文件存在用）
      modules: [(module_name, router_attr_name), ...]
           module_name 不含 `.api.` 前缀，如 `"canonical_delivery_routes"`
           router_attr 通常为 `"router"`
      strict: 若 True，任何 import 失败抛异常；默认 False（静默 + WARNING）

    Returns:
      MountResult（挂载报告）
    """
    result = MountResult()
    for module_name, attr_name in modules:
        py_file = api_dir / f"{module_name}.py"
        if not py_file.exists():
            logger.debug("[auto-mount] %s.py not present, skipped", module_name)
            result.skipped.append(module_name)
            continue

        # 构造完整 import 路径
        if pkg:
            full_path = f"{pkg}.api.{module_name}"
        else:
            full_path = f"api.{module_name}"

        try:
            module = importlib.import_module(full_path)
        except BaseException as exc:  # noqa: BLE001 - 含 SystemExit/KeyboardInterrupt 等
            # 关键：`except Exception` 无法捕获 SystemExit/KeyboardInterrupt/GeneratorExit
            # 这些 BaseException 子类在模块顶层抛出会静默杀掉 service 启动
            # 我们必须拦下来并转为 failed + WARNING（strict 时再 raise）
            msg = f"import failed: {type(exc).__name__}: {exc}"
            logger.warning(
                "[auto-mount] %s exists but %s",
                module_name, msg,
            )
            result.failed.append((module_name, msg))
            if strict:
                raise
            continue

        router = getattr(module, attr_name, None)
        if router is None:
            msg = f"no '{attr_name}' attribute"
            logger.warning("[auto-mount] %s has %s", module_name, msg)
            result.failed.append((module_name, msg))
            if strict:
                raise AttributeError(
                    f"{module_name} module has no '{attr_name}'"
                )
            continue

        # 类型检查：必须是 FastAPI APIRouter（或 duck-typed 含 routes 属性）
        # 防止 `router = None` / `router = {}` / `router = SomeOtherObject()` 等
        # 误用导致 include_router 抛深层异常
        if not hasattr(router, "routes"):
            msg = (
                f"'{attr_name}' is not a router (type={type(router).__name__}, "
                f"missing 'routes' attribute)"
            )
            logger.warning("[auto-mount] %s %s", module_name, msg)
            result.failed.append((module_name, msg))
            if strict:
                raise TypeError(msg)
            continue

        try:
            app.include_router(router)
        except BaseException as exc:  # noqa: BLE001 - 含 SystemExit 等
            msg = f"include_router failed: {type(exc).__name__}: {exc}"
            logger.warning("[auto-mount] %s %s", module_name, msg)
            result.failed.append((module_name, msg))
            if strict:
                raise
            continue

        logger.info("[auto-mount] mounted %s", module_name)
        result.mounted.append(module_name)

    return result


def mount_report(result: MountResult) -> str:
    """构造人类可读的 mount 报告（service 启动时可打印）"""
    lines = [
        f"Auto-mount: {len(result.mounted)} mounted / "
        f"{len(result.skipped)} skipped (pending PR) / "
        f"{len(result.failed)} failed",
    ]
    for m in result.mounted:
        lines.append(f"  ✅ {m}")
    for m in result.skipped:
        lines.append(f"  ⏭️  {m} (module file not present)")
    for m, r in result.failed:
        lines.append(f"  ❌ {m}: {r}")
    return "\n".join(lines)


def validate_result(
    result: MountResult,
    *,
    env_strict: str = "AUTO_MOUNT_STRICT",
    logger_override: Optional[logging.Logger] = None,
) -> None:
    """在 service 启动时校验 mount result，必要时打印到 stderr + 按 env 强制 exit。

    调用方式（典型 service main.py）：
        _result = auto_mount_routes(...)
        validate_result(_result)       # WARNING only (default)
        # or set env AUTO_MOUNT_STRICT=1 to sys.exit(1) on any failure

    行为：
      · result.failed 非空 → 总是打印完整报告到 stderr + WARNING log
      · env AUTO_MOUNT_STRICT=1（或 true/yes）→ 有 failed 时 sys.exit(1)
      · result 全绿 → INFO log 一行摘要

    设计：默认不 sys.exit（服务仍可启动），但失败 **无法忽视**。
    生产部署建议 env AUTO_MOUNT_STRICT=1（缺路由即启动失败）。
    """
    import os as _os
    import sys as _sys

    log = logger_override or logger
    summary = (
        f"auto-mount summary: mounted={len(result.mounted)} "
        f"skipped={len(result.skipped)} failed={len(result.failed)}"
    )

    if not result.failed:
        log.info("[auto-mount] %s", summary)
        return

    # 有失败时：always 打印到 stderr（不依赖日志级别），便于 k8s / docker logs 可见
    report = mount_report(result)
    log.warning("[auto-mount] %s\n%s", summary, report)
    print(
        f"\n[auto-mount] WARNING: {len(result.failed)} route(s) failed to mount\n"
        f"{report}\n",
        file=_sys.stderr,
    )

    # env 强制 exit
    strict_env = _os.environ.get(env_strict, "").strip().lower()
    if strict_env in ("1", "true", "yes", "on"):
        log.error("[auto-mount] %s=%s → exit(1) on mount failures", env_strict, strict_env)
        _sys.exit(1)
