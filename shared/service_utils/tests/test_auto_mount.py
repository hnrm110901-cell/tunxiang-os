"""auto_mount 单元测试"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.service_utils.auto_mount import (  # noqa: E402
    MountResult,
    auto_mount_routes,
    mount_report,
    validate_result,
)

# ─────────────────────────────────────────────────────────────
# MountResult 数据契约
# ─────────────────────────────────────────────────────────────


class TestMountResult:
    def test_empty_result_ok(self):
        r = MountResult()
        assert r.ok is True
        assert r.total == 0

    def test_failed_not_ok(self):
        r = MountResult(failed=[("foo", "ImportError")])
        assert r.ok is False

    def test_total_counts_all(self):
        r = MountResult(
            mounted=["a", "b"],
            skipped=["c"],
            failed=[("d", "x")],
        )
        assert r.total == 4

    def test_to_dict_contract(self):
        r = MountResult(
            mounted=["a"], skipped=["b"], failed=[("c", "reason")],
        )
        d = r.to_dict()
        assert d["mounted"] == ["a"]
        assert d["skipped"] == ["b"]
        assert d["failed"] == [{"module": "c", "reason": "reason"}]
        assert d["total"] == 3
        assert d["ok"] is False


# ─────────────────────────────────────────────────────────────
# auto_mount_routes 行为
# ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_api_from_sys_modules():
    """每个测试前清 sys.modules 里的 `api.*` 条目，避免跨 tmp_path 污染"""
    to_drop = [k for k in sys.modules if k == "api" or k.startswith("api.")]
    for k in to_drop:
        del sys.modules[k]
    yield
    to_drop = [k for k in sys.modules if k == "api" or k.startswith("api.")]
    for k in to_drop:
        del sys.modules[k]


class TestAutoMount:
    def test_skips_when_file_not_present(self, tmp_path):
        """模块文件不存在 → 归入 skipped，不尝试 import"""
        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg=None,
            api_dir=tmp_path,
            modules=[("nonexistent_module", "router")],
        )
        assert result.skipped == ["nonexistent_module"]
        assert result.mounted == []
        assert result.failed == []
        app.include_router.assert_not_called()

    def test_mounts_existing_module(self, tmp_path, monkeypatch):
        """文件存在 + 可 import + 有 router → mounted"""
        # 创建一个真模块
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (tmp_path / "__init__.py").write_text("")
        (api_dir / "__init__.py").write_text("")
        (api_dir / "my_test_routes.py").write_text(
            "class _FakeRouter:\n"
            "    def __init__(self): self.routes = []\n"
            "router = _FakeRouter()\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg=None,
            api_dir=api_dir,
            modules=[("my_test_routes", "router")],
        )
        assert result.mounted == ["my_test_routes"]
        assert result.skipped == []
        assert result.failed == []
        app.include_router.assert_called_once()

    def test_failed_when_import_errors(self, tmp_path, monkeypatch):
        """文件存在但 import 失败 → failed + WARNING + 不抛"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "broken_routes.py").write_text("raise RuntimeError('bad')\n")
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg=None,
            api_dir=api_dir,
            modules=[("broken_routes", "router")],
        )
        assert result.mounted == []
        assert result.skipped == []
        assert len(result.failed) == 1
        assert "broken_routes" in result.failed[0][0]
        assert "RuntimeError" in result.failed[0][1]

    def test_strict_raises_on_failure(self, tmp_path, monkeypatch):
        """strict=True 时 import 失败抛异常"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "boom_routes.py").write_text("1/0\n")
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        with pytest.raises(ZeroDivisionError):
            auto_mount_routes(
                app,
                pkg=None,
                api_dir=api_dir,
                modules=[("boom_routes", "router")],
                strict=True,
            )

    def test_failed_when_module_missing_router_attr(
        self, tmp_path, monkeypatch,
    ):
        """模块 import 成功但没 router 属性"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "no_router.py").write_text("# no router defined\n")
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg=None,
            api_dir=api_dir,
            modules=[("no_router", "router")],
        )
        assert result.mounted == []
        assert len(result.failed) == 1
        assert "no 'router' attribute" in result.failed[0][1]

    def test_multiple_modules_mixed_outcomes(self, tmp_path, monkeypatch):
        """混合场景：mounted + skipped + failed 同时出现"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")

        # 1. ok_routes
        (api_dir / "ok_routes.py").write_text(
            "class _R:\n"
            "    def __init__(self): self.routes = []\n"
            "router = _R()\n"
        )
        # 2. broken_routes（存在但 import 失败）
        (api_dir / "broken_routes.py").write_text(
            "raise ImportError('nope')\n"
        )
        # 3. missing_routes 不创建 → skipped

        monkeypatch.syspath_prepend(str(tmp_path))
        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg=None,
            api_dir=api_dir,
            modules=[
                ("ok_routes", "router"),
                ("broken_routes", "router"),
                ("missing_routes", "router"),
            ],
        )
        assert result.mounted == ["ok_routes"]
        assert result.skipped == ["missing_routes"]
        assert len(result.failed) == 1
        assert result.failed[0][0] == "broken_routes"
        app.include_router.assert_called_once()

    def test_pkg_path_used_when_provided(self, tmp_path, monkeypatch):
        """pkg 参数构造 {pkg}.api.{module_name} import 路径"""
        api_dir = tmp_path / "mysvc" / "api"
        api_dir.mkdir(parents=True)
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "mysvc" / "__init__.py").write_text("")
        (api_dir / "__init__.py").write_text("")
        (api_dir / "cool_routes.py").write_text(
            "class _R:\n    def __init__(self): self.routes = []\nrouter = _R()\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app,
            pkg="mysvc",
            api_dir=api_dir,
            modules=[("cool_routes", "router")],
        )
        assert result.mounted == ["cool_routes"]


# ─────────────────────────────────────────────────────────────
# mount_report
# ─────────────────────────────────────────────────────────────


class TestMountReport:
    def test_empty_report(self):
        report = mount_report(MountResult())
        assert "0 mounted" in report
        assert "0 skipped" in report
        assert "0 failed" in report

    def test_all_categories(self):
        result = MountResult(
            mounted=["a", "b"],
            skipped=["c"],
            failed=[("d", "oops")],
        )
        report = mount_report(result)
        assert "2 mounted" in report
        assert "1 skipped" in report
        assert "1 failed" in report
        assert "✅ a" in report
        assert "✅ b" in report
        assert "⏭️  c" in report
        assert "❌ d" in report
        assert "oops" in report


# ─────────────────────────────────────────────────────────────
# Review follow-up：BaseException 捕获 + 类型校验 + validate_result
# ─────────────────────────────────────────────────────────────


class TestBaseExceptionCapture:
    """关键：`except Exception` 无法捕获 SystemExit/KeyboardInterrupt。
    未修复前 malicious/buggy route 含 `sys.exit(1)` 顶层调用会静默杀进程。
    """

    def test_system_exit_at_import_caught(self, tmp_path, monkeypatch):
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "sysexit_routes.py").write_text(
            "import sys\nsys.exit(42)  # malicious/buggy\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        # 期望：不抛异常而是归入 failed
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("sysexit_routes", "router")],
        )
        assert result.mounted == []
        assert len(result.failed) == 1
        assert "SystemExit" in result.failed[0][1]

    def test_keyboard_interrupt_at_import_caught(self, tmp_path, monkeypatch):
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "kbint_routes.py").write_text(
            "raise KeyboardInterrupt()\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("kbint_routes", "router")],
        )
        assert result.mounted == []
        assert len(result.failed) == 1
        assert "KeyboardInterrupt" in result.failed[0][1]

    def test_strict_still_raises_system_exit(self, tmp_path, monkeypatch):
        """strict=True 时 SystemExit 应该重新抛出"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "exit_routes.py").write_text(
            "import sys\nsys.exit(1)\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        with pytest.raises(SystemExit):
            auto_mount_routes(
                app, pkg=None, api_dir=api_dir,
                modules=[("exit_routes", "router")],
                strict=True,
            )


class TestRouterTypeCheck:
    """router 属性必须是 FastAPI APIRouter（duck-typed 含 routes）"""

    def test_router_is_none_rejected(self, tmp_path, monkeypatch):
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        # 注：getattr 默认 None 时在旧逻辑是 "no 'router' attribute"
        # 这里让 getattr 返回 None：显式写 router = None
        (api_dir / "none_router.py").write_text("router = None\n")
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("none_router", "router")],
        )
        assert len(result.failed) == 1
        # router=None 走 "no attribute" 分支（getattr 默认返 None）
        assert "no 'router' attribute" in result.failed[0][1]

    def test_router_is_dict_rejected(self, tmp_path, monkeypatch):
        """router 是 dict 而非 APIRouter → 类型校验 fail"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "dict_router.py").write_text(
            "router = {'routes': 'fake'}  # looks like router but isn't\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("dict_router", "router")],
        )
        # dict 含 'routes' key 所以 hasattr(dict, 'routes') False
        # 但 hasattr 对 dict 的 'routes' 检查的是属性，不是键
        assert len(result.failed) == 1
        assert "not a router" in result.failed[0][1]

    def test_router_is_string_rejected(self, tmp_path, monkeypatch):
        """router 是 str → 类型校验 fail"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "str_router.py").write_text("router = 'fake'\n")
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("str_router", "router")],
        )
        assert len(result.failed) == 1
        assert "not a router" in result.failed[0][1]

    def test_router_with_routes_attr_accepted(self, tmp_path, monkeypatch):
        """duck-typed: 只要有 .routes 属性就通过类型检查"""
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        (api_dir / "__init__.py").write_text("")
        (api_dir / "duck_router.py").write_text(
            "class _R:\n"
            "    def __init__(self): self.routes = []\n"
            "router = _R()\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        app = MagicMock()
        result = auto_mount_routes(
            app, pkg=None, api_dir=api_dir,
            modules=[("duck_router", "router")],
        )
        assert result.mounted == ["duck_router"]


class TestValidateResult:
    """validate_result: 失败时 stderr + WARNING，env strict 时 sys.exit"""

    def test_all_green_no_exit(self, capsys, caplog):
        import logging
        caplog.set_level(logging.INFO)
        result = MountResult(mounted=["a"], skipped=[], failed=[])
        validate_result(result)  # 不应 sys.exit
        captured = capsys.readouterr()
        # INFO summary line logged, no stderr warning
        assert "summary" in caplog.text
        assert captured.err == ""  # 全绿不写 stderr

    def test_failed_writes_to_stderr(self, capsys, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        result = MountResult(
            mounted=["ok_route"],
            failed=[("bad_route", "ImportError: nope")],
        )
        validate_result(result)  # 默认不 exit
        captured = capsys.readouterr()
        assert "bad_route" in captured.err
        assert "WARNING" in captured.err
        assert "ImportError" in captured.err

    def test_env_strict_causes_exit(self, monkeypatch):
        result = MountResult(failed=[("bad", "oops")])
        monkeypatch.setenv("AUTO_MOUNT_STRICT", "1")
        with pytest.raises(SystemExit) as exc_info:
            validate_result(result)
        assert exc_info.value.code == 1

    def test_env_strict_case_insensitive(self, monkeypatch):
        result = MountResult(failed=[("bad", "oops")])
        for val in ("true", "yes", "on", "TRUE"):
            monkeypatch.setenv("AUTO_MOUNT_STRICT", val)
            with pytest.raises(SystemExit):
                validate_result(result)

    def test_env_strict_skipped_when_no_failures(self, monkeypatch):
        """env 开但没有失败 → 不 exit"""
        result = MountResult(mounted=["a"])
        monkeypatch.setenv("AUTO_MOUNT_STRICT", "1")
        validate_result(result)  # 不抛

    def test_env_strict_off_by_default(self, monkeypatch):
        """env 未设置 → 有失败也不 exit（仅 WARNING）"""
        monkeypatch.delenv("AUTO_MOUNT_STRICT", raising=False)
        result = MountResult(failed=[("bad", "oops")])
        validate_result(result)  # 不抛

    def test_custom_env_name(self, monkeypatch):
        """支持自定义 env 变量名"""
        result = MountResult(failed=[("bad", "oops")])
        monkeypatch.setenv("MY_STRICT", "1")
        with pytest.raises(SystemExit):
            validate_result(result, env_strict="MY_STRICT")
