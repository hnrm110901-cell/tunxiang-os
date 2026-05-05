"""auto_mount AUTO_MOUNT_STRICT env 门禁测试 (P0-3)

确认：
  · env AUTO_MOUNT_STRICT=1 → 任一 mount 失败 raise RouteMountError 阻断启动
  · env 未设置 → 仅 WARNING，不抛
  · 严格模式下收集 **全部** 失败模块（不在第一个 fail 时立即 raise）
  · error log 列出全部失败模块名
  · 显式 strict=False 可绕过 env（开发本地调试）
  · 不打破 except Exception 禁令（具体异常类型）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.service_utils.auto_mount import (  # noqa: E402
    STRICT_ENV_VAR,
    RouteMountError,
    auto_mount_routes,
)


@pytest.fixture(autouse=True)
def _clear_api_from_sys_modules():
    """清 sys.modules 里的 api.* 条目，避免跨 tmp_path 污染"""
    to_drop = [k for k in sys.modules if k == "api" or k.startswith("api.")]
    for k in to_drop:
        del sys.modules[k]
    yield
    to_drop = [k for k in sys.modules if k == "api" or k.startswith("api.")]
    for k in to_drop:
        del sys.modules[k]


def _make_api_dir(tmp_path: Path) -> Path:
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "__init__.py").write_text("")
    return api_dir


def _make_ok_route(api_dir: Path, name: str) -> None:
    (api_dir / f"{name}.py").write_text(
        "class _R:\n"
        "    def __init__(self): self.routes = []\n"
        "router = _R()\n"
    )


def _make_broken_route(api_dir: Path, name: str, error: str = "RuntimeError") -> None:
    (api_dir / f"{name}.py").write_text(f"raise {error}('intentional broken')\n")


# ─────────────────────────────────────────────────────────────
# env-driven 严格模式
# ─────────────────────────────────────────────────────────────


class TestEnvStrictMode:
    def test_env_strict_1_raises_on_failure(self, tmp_path, monkeypatch):
        """AUTO_MOUNT_STRICT=1 + import 失败 → RouteMountError"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        with pytest.raises(RouteMountError) as exc_info:
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("broken_routes", "router")],
            )
        assert exc_info.value.failures[0][0] == "broken_routes"
        assert "RuntimeError" in exc_info.value.failures[0][1]

    def test_env_strict_0_does_not_raise(self, tmp_path, monkeypatch):
        """AUTO_MOUNT_STRICT=0（或未设置）→ 仅 WARNING"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "0")

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("broken_routes", "router")],
        )
        # 不抛 → 返回结果
        assert len(result.failed) == 1
        assert result.mounted == []

    def test_env_unset_does_not_raise(self, tmp_path, monkeypatch):
        """env 未设置 → 默认宽松模式（向后兼容）"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delenv(STRICT_ENV_VAR, raising=False)

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("broken_routes", "router")],
        )
        assert len(result.failed) == 1

    @pytest.mark.parametrize("env_value", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_env_strict_accepted_values(self, tmp_path, monkeypatch, env_value):
        """1 / true / yes / on（大小写无关）都启用严格模式"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, env_value)

        app = MagicMock()
        with pytest.raises(RouteMountError):
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("broken_routes", "router")],
            )

    @pytest.mark.parametrize("env_value", ["", "0", "false", "no", "off", "random"])
    def test_env_strict_rejected_values(self, tmp_path, monkeypatch, env_value):
        """空 / false / no / off / 任意字符串 → 不启用"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, env_value)

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("broken_routes", "router")],
        )
        assert len(result.failed) == 1  # 不抛


# ─────────────────────────────────────────────────────────────
# 显式 strict 参数 vs env 优先级
# ─────────────────────────────────────────────────────────────


class TestExplicitStrictOverridesEnv:
    def test_explicit_strict_false_overrides_env_1(self, tmp_path, monkeypatch):
        """显式 strict=False 时即使 env=1 也不抛（开发调试场景）"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("broken_routes", "router")],
            strict=False,
        )
        assert len(result.failed) == 1  # 显式 False 胜出

    def test_explicit_strict_true_overrides_env_unset(
        self, tmp_path, monkeypatch,
    ):
        """显式 strict=True 时即使 env 没设也抛"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken_routes")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delenv(STRICT_ENV_VAR, raising=False)

        app = MagicMock()
        with pytest.raises(RouteMountError):
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("broken_routes", "router")],
                strict=True,
            )


# ─────────────────────────────────────────────────────────────
# 全部失败聚合 + log error
# ─────────────────────────────────────────────────────────────


class TestStrictAggregatesAllFailures:
    def test_collects_all_failures_before_raising(self, tmp_path, monkeypatch):
        """3 个失败模块 → RouteMountError.failures 含全部 3 个"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "fail_a", error="RuntimeError")
        _make_broken_route(api_dir, "fail_b", error="ValueError")
        _make_broken_route(api_dir, "fail_c", error="TypeError")
        _make_ok_route(api_dir, "ok_route")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        with pytest.raises(RouteMountError) as exc_info:
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[
                    ("fail_a", "router"),
                    ("ok_route", "router"),
                    ("fail_b", "router"),
                    ("fail_c", "router"),
                ],
            )
        failed_modules = [m for m, _ in exc_info.value.failures]
        assert sorted(failed_modules) == ["fail_a", "fail_b", "fail_c"]
        # ok_route 仍然 mount 成功（虽然最后被 raise 中断）
        app.include_router.assert_called_once()

    def test_error_log_lists_all_failed_modules(
        self, tmp_path, monkeypatch, caplog,
    ):
        """严格模式下 error log 必须列出每个失败模块"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "fail_alpha")
        _make_broken_route(api_dir, "fail_beta")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        caplog.set_level(logging.ERROR)
        app = MagicMock()
        with pytest.raises(RouteMountError):
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[
                    ("fail_alpha", "router"),
                    ("fail_beta", "router"),
                ],
            )
        # error log 必须包含两个失败模块名
        assert "fail_alpha" in caplog.text
        assert "fail_beta" in caplog.text
        assert "STRICT mode" in caplog.text
        assert "BLOCKED" in caplog.text

    def test_strict_no_failures_no_raise(self, tmp_path, monkeypatch):
        """严格模式 + 全部 mount 成功 → 不抛"""
        api_dir = _make_api_dir(tmp_path)
        _make_ok_route(api_dir, "ok_a")
        _make_ok_route(api_dir, "ok_b")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("ok_a", "router"), ("ok_b", "router")],
        )
        assert len(result.mounted) == 2
        assert app.include_router.call_count == 2


# ─────────────────────────────────────────────────────────────
# 多种失败模式都被严格模式拦截
# ─────────────────────────────────────────────────────────────


class TestStrictCoversAllFailureKinds:
    def test_strict_catches_missing_router_attr(self, tmp_path, monkeypatch):
        """strict 也覆盖 'router 属性缺失' → RouteMountError"""
        api_dir = _make_api_dir(tmp_path)
        (api_dir / "no_attr.py").write_text("# no router\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        with pytest.raises(RouteMountError) as exc_info:
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("no_attr", "router")],
            )
        assert "no 'router' attribute" in exc_info.value.failures[0][1]

    def test_strict_catches_wrong_router_type(self, tmp_path, monkeypatch):
        """strict 覆盖 'router 类型错误'（非 APIRouter）"""
        api_dir = _make_api_dir(tmp_path)
        (api_dir / "bad_type.py").write_text("router = 'not a router'\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        with pytest.raises(RouteMountError) as exc_info:
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("bad_type", "router")],
            )
        assert "not a router" in exc_info.value.failures[0][1]

    def test_strict_skipped_files_not_failures(self, tmp_path, monkeypatch):
        """文件不存在 = skipped，不算 failure，严格模式不抛"""
        api_dir = _make_api_dir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(STRICT_ENV_VAR, "1")

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("not_present", "router")],
        )
        # skipped 不阻塞启动，符合 "PR 未合并" 场景
        assert result.skipped == ["not_present"]
        assert result.failed == []


# ─────────────────────────────────────────────────────────────
# 自定义 env 名（运维灵活性）
# ─────────────────────────────────────────────────────────────


class TestCustomEnvVar:
    def test_custom_env_var(self, tmp_path, monkeypatch):
        """支持自定义 env 名（默认 AUTO_MOUNT_STRICT）"""
        api_dir = _make_api_dir(tmp_path)
        _make_broken_route(api_dir, "broken")
        monkeypatch.syspath_prepend(str(tmp_path))
        # 默认 env 不开
        monkeypatch.delenv(STRICT_ENV_VAR, raising=False)
        # 自定义 env 开
        monkeypatch.setenv("MY_PROD_GATE", "1")

        app = MagicMock()
        with pytest.raises(RouteMountError):
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("broken", "router")],
                strict_env_var="MY_PROD_GATE",
            )
