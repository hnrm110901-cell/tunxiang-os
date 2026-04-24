"""Tier 1 契约测试 — 6 个 service main.py 的 auto_mount 块

Week 8 DEMO 启动前保障：OPEN PR 合入后 routes 自动挂载，无需手动改 main.py。
本测试保障：
  1. 每个 service main.py 都 import shared.service_utils.auto_mount_routes
  2. 每个期望 mount 的 module_name 都在对应 main.py 的 modules 列表里
  3. pkg 参数对齐 service 的 import 风格（相对 vs 绝对）
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# 期望的 service → routes 映射
EXPECTED_MOUNTS: dict[str, tuple[str, ...]] = {
    "tx-trade": (
        "canonical_delivery_routes",   # E1 #91
        "dish_publish_routes",          # E2 #92
        "xiaohongshu_routes",           # E3 #93
        "dispute_routes",               # E4 #94
    ),
    "tx-member": (
        "rfm_outreach_routes",          # D3a #82
        "campaign_roi_forecast_routes",  # D3b #83
    ),
    "tx-menu": (
        "dish_pricing_routes",          # D3c #84
    ),
    "tx-finance": (
        "cost_root_cause_routes",       # D4a #85
        "budget_forecast_routes",        # D4c #88
    ),
    "tx-org": (
        "salary_anomaly_routes",        # D4b #87
    ),
    "tx-brain": (
        "ab_experiment_routes",         # G #97
    ),
}


def _read_main(svc: str) -> str:
    path = ROOT / "services" / svc / "src" / "main.py"
    assert path.exists(), f"{path} 不存在"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# 1. 每个 service 都 import auto_mount_routes
# ─────────────────────────────────────────────────────────────


def test_all_services_import_auto_mount_routes():
    """6 个 service main.py 都 import shared.service_utils.auto_mount_routes"""
    missing = []
    for svc in EXPECTED_MOUNTS:
        source = _read_main(svc)
        if "auto_mount_routes" not in source:
            missing.append(svc)
        if "shared.service_utils" not in source:
            missing.append(svc)
    assert not missing, (
        f"下列 service 未接入 auto_mount_routes: {sorted(set(missing))}"
    )


def test_all_services_call_validate_result():
    """Review follow-up：6 service main.py 必须调 validate_result（失败不被忽视）"""
    missing = []
    for svc in EXPECTED_MOUNTS:
        source = _read_main(svc)
        if "validate_result" not in source:
            missing.append(svc)
    assert not missing, (
        f"下列 service 未调 validate_result（挂载失败将被静默吞掉）: "
        f"{sorted(set(missing))}"
    )


# ─────────────────────────────────────────────────────────────
# 2. 每个 service 的 modules 列表齐全
# ─────────────────────────────────────────────────────────────


class TestServiceMountConfigs:
    """每个 service 期望的 module_name 都必须出现在 main.py"""

    def _check_service(self, svc: str):
        source = _read_main(svc)
        expected = EXPECTED_MOUNTS[svc]
        for module_name in expected:
            # module_name 必须作为字符串字面量出现（tuple 元素）
            assert f'("{module_name}", "router")' in source, (
                f'{svc}/main.py 未 mount {module_name}；期望：'
                f'("{module_name}", "router")'
            )

    def test_tx_trade(self):
        self._check_service("tx-trade")

    def test_tx_member(self):
        self._check_service("tx-member")

    def test_tx_menu(self):
        self._check_service("tx-menu")

    def test_tx_finance(self):
        self._check_service("tx-finance")

    def test_tx_org(self):
        self._check_service("tx-org")

    def test_tx_brain(self):
        self._check_service("tx-brain")


# ─────────────────────────────────────────────────────────────
# 3. pkg 参数匹配 import 风格
# ─────────────────────────────────────────────────────────────


class TestPkgParamAlignsWithImportStyle:
    """tx-org 用绝对 import (pkg=None)；其他用相对 import (pkg=__package__)"""

    def test_tx_trade_uses_package_for_relative_imports(self):
        source = _read_main("tx-trade")
        # tx-trade 用 from .api.X 相对 import → pkg=__package__
        assert "pkg=__package__" in source, (
            "tx-trade main.py 应用 pkg=__package__（相对 import）"
        )

    def test_tx_member_uses_package(self):
        source = _read_main("tx-member")
        assert "pkg=__package__" in source

    def test_tx_menu_uses_package(self):
        source = _read_main("tx-menu")
        assert "pkg=__package__" in source

    def test_tx_finance_uses_package(self):
        source = _read_main("tx-finance")
        assert "pkg=__package__" in source

    def test_tx_org_uses_none_for_absolute_imports(self):
        """tx-org 用 from api.X 绝对 import → pkg=None"""
        source = _read_main("tx-org")
        assert "pkg=None" in source, (
            "tx-org main.py 应用 pkg=None（绝对 import 风格）"
        )

    def test_tx_brain_uses_package(self):
        source = _read_main("tx-brain")
        assert "pkg=__package__" in source


# ─────────────────────────────────────────────────────────────
# 4. api_dir 参数格式
# ─────────────────────────────────────────────────────────────


def test_all_services_use_api_subdir():
    """api_dir 必须指向 <main.py 目录>/api"""
    for svc in EXPECTED_MOUNTS:
        source = _read_main(svc)
        assert 'api_dir=_Path(__file__).parent / "api"' in source, (
            f"{svc}/main.py api_dir 参数不是 __file__.parent/api"
        )


# ─────────────────────────────────────────────────────────────
# 5. auto_mount 在 /health 端点之前
# ─────────────────────────────────────────────────────────────


def test_auto_mount_is_before_health():
    """auto_mount_routes 调用必须在 @app.get('/health') 之前

    如果 mount 在 health 之后，服务启动时 health 已经注册但 mount 未执行，
    路由不完整。
    """
    for svc in EXPECTED_MOUNTS:
        source = _read_main(svc)
        mount_idx = source.find("auto_mount_routes(")
        health_idx = source.find('@app.get("/health")')
        assert mount_idx > 0, f"{svc}: 未找到 auto_mount_routes 调用"
        assert health_idx > 0, f"{svc}: 未找到 /health 端点"
        assert mount_idx < health_idx, (
            f"{svc}: auto_mount_routes 应在 /health 之前（顺序错）"
        )


# ─────────────────────────────────────────────────────────────
# 6. shared/service_utils/ 模块存在
# ─────────────────────────────────────────────────────────────


class TestSharedServiceUtils:
    def test_init_exports_auto_mount_routes(self):
        path = ROOT / "shared" / "service_utils" / "__init__.py"
        assert path.exists()
        src = path.read_text(encoding="utf-8")
        assert "auto_mount_routes" in src
        assert "MountResult" in src

    def test_init_exports_validate_result(self):
        """Review follow-up：validate_result 也需在 __init__ 导出"""
        src = (
            ROOT / "shared" / "service_utils" / "__init__.py"
        ).read_text(encoding="utf-8")
        assert "validate_result" in src

    def test_auto_mount_py_exists(self):
        path = ROOT / "shared" / "service_utils" / "auto_mount.py"
        assert path.exists()

    def test_auto_mount_signature(self):
        """auto_mount_routes 签名：(app, *, pkg, api_dir, modules, strict=False)"""
        src = (
            ROOT / "shared" / "service_utils" / "auto_mount.py"
        ).read_text(encoding="utf-8")
        assert "def auto_mount_routes(" in src
        # 关键字参数必须存在
        for kw in ("pkg:", "api_dir:", "modules:", "strict:"):
            assert kw in src, f"auto_mount_routes 缺关键字 {kw}"

    def test_catches_base_exception(self):
        """Review follow-up：auto_mount.py 必须用 except BaseException 而非 Exception
        （否则 SystemExit/KeyboardInterrupt 不被捕获，会静默杀进程）
        """
        src = (
            ROOT / "shared" / "service_utils" / "auto_mount.py"
        ).read_text(encoding="utf-8")
        # 至少两处 except BaseException（import + include_router）
        count = src.count("except BaseException")
        assert count >= 2, (
            f"auto_mount.py 期望至少 2 处 except BaseException，实际 {count}。"
            f"若仅用 except Exception，SystemExit 等会穿透导致 service 静默崩溃。"
        )

    def test_has_router_type_check(self):
        """router 必须有 .routes 属性（防止 router=dict/str 等误用）"""
        src = (
            ROOT / "shared" / "service_utils" / "auto_mount.py"
        ).read_text(encoding="utf-8")
        assert 'hasattr(router, "routes")' in src or "hasattr(router, 'routes')" in src, (
            "auto_mount 未对 router 做类型检查"
        )

    def test_validate_result_exists(self):
        """validate_result 函数必须存在"""
        src = (
            ROOT / "shared" / "service_utils" / "auto_mount.py"
        ).read_text(encoding="utf-8")
        assert "def validate_result(" in src

    def test_validate_result_honors_env_strict(self):
        """validate_result 必须根据 AUTO_MOUNT_STRICT env 决定是否 sys.exit"""
        src = (
            ROOT / "shared" / "service_utils" / "auto_mount.py"
        ).read_text(encoding="utf-8")
        assert "AUTO_MOUNT_STRICT" in src
        assert "sys.exit" in src or "_sys.exit" in src


# ─────────────────────────────────────────────────────────────
# 7. 完整性对齐
# ─────────────────────────────────────────────────────────────


def test_expected_mounts_cover_all_open_prs():
    """EXPECTED_MOUNTS 必须覆盖全部 11 个 OPEN PR 的 routes"""
    total = sum(len(v) for v in EXPECTED_MOUNTS.values())
    assert total == 11, (
        f"EXPECTED_MOUNTS 应覆盖 11 个 OPEN PR routes，实际 {total}"
    )
