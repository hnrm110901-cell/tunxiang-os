"""Unit tests for scripts/codemod/test_import_style_rewrite.py [#318 follow-up]

#318 Phase 1 scanner 漏抓 `import xxx` 形式（只抓 `from xxx import yyy`）。
本套件锁定两种形式都被识别 + 都能正确改写。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 显式注入 scripts/codemod/ 到 sys.path 以 import 同级 module
SCANNER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCANNER_DIR))

import test_import_style_rewrite as scanner  # noqa: E402  pyright: ignore[reportMissingImports]


# ─── 1. classify_module（共享逻辑）── 不变契约 ─────────────────────


class TestClassifyModule:
    def test_bare_services_namespace(self) -> None:
        style, ns = scanner.classify_module("services.cashier_engine")
        assert style == "bare"
        assert ns == "services"

    def test_bare_api_namespace(self) -> None:
        style, ns = scanner.classify_module("api.cashier_routes")
        assert style == "bare"
        assert ns == "api"

    def test_full_path(self) -> None:
        style, _ = scanner.classify_module(
            "services.tx_trade.src.services.cashier_engine"
        )
        assert style == "full-path"

    def test_other_third_party(self) -> None:
        style, _ = scanner.classify_module("pytest")
        assert style == "other"

    def test_empty(self) -> None:
        style, _ = scanner.classify_module("")
        assert style == "other"


# ─── 2. scan_file 必须同时抓 `from X import Y` 和 `import X`（#318 follow-up） ──


@pytest.fixture
def fixture_test_file(tmp_path: Path) -> Path:
    """构造 services/tx-foo/src/tests/test_X.py 形态的临时测试文件，
    含两种 import 形式（裸 + 全路径）的全 4 种组合。"""
    test_dir = tmp_path / "services" / "tx-foo" / "src" / "tests"
    test_dir.mkdir(parents=True)
    fp = test_dir / "test_imports_dual_form.py"
    fp.write_text(
        '''"""Fixture：4 种 import 形式覆盖"""

# 1. from-import 裸（应抓）
from services.cashier_engine import OrderEngine
from api.cashier_routes import router

# 2. from-import 全路径（应抓 + 标记 full-path）
from services.tx_foo.src.services.cashier_engine import OrderEngine as _OE

# 3. import 裸（#318 follow-up — scanner 漏抓的）
import api.cashier_routes as _cashier_mod
import services.payment_service

# 4. import 全路径（应抓 + 标记 full-path）
import services.tx_foo.src.api.cashier_routes as _full_mod

# 5. 第三方 / 标准库 / 相对（不动）
import os
import pytest
from datetime import datetime
from . import sibling
''',
        encoding="utf-8",
    )
    return fp


class TestScanFileBothImportForms:
    def test_scans_both_from_and_import_forms(
        self, tmp_path: Path, fixture_test_file: Path
    ) -> None:
        sites = scanner.scan_file(fixture_test_file, tmp_path, "tx_foo")
        # 应抓：3 from-import + 3 import = 6 站点
        # （from 2 裸 + 1 全 + import 2 裸 + 1 全）
        # 不抓：os/pytest/datetime/sibling
        assert len(sites) == 6, f"应有 6 站点，实际 {len(sites)}: {sites}"

    def test_import_form_detected_as_bare(
        self, tmp_path: Path, fixture_test_file: Path
    ) -> None:
        sites = scanner.scan_file(fixture_test_file, tmp_path, "tx_foo")
        bare_modules = sorted(s.module for s in sites if s.style == "bare")
        # `import api.cashier_routes` + `import services.payment_service` +
        # `from services.cashier_engine` + `from api.cashier_routes`
        assert "api.cashier_routes" in bare_modules
        assert "services.payment_service" in bare_modules

    def test_import_form_proposed_rewrite_correct(
        self, tmp_path: Path, fixture_test_file: Path
    ) -> None:
        sites = scanner.scan_file(fixture_test_file, tmp_path, "tx_foo")
        bare = {s.module: s.proposed for s in sites if s.style == "bare"}
        assert (
            bare["api.cashier_routes"]
            == "services.tx_foo.src.api.cashier_routes"
        )
        assert (
            bare["services.payment_service"]
            == "services.tx_foo.src.services.payment_service"
        )

    def test_full_path_import_form_marked_full(
        self, tmp_path: Path, fixture_test_file: Path
    ) -> None:
        sites = scanner.scan_file(fixture_test_file, tmp_path, "tx_foo")
        full = [s for s in sites if s.style == "full-path"]
        # 1 from-import 全 + 1 import 全 = 2
        assert len(full) == 2


# ─── 3. apply_rewrites_to_file 必须改两种形式 ──────────────────────


class TestApplyRewritesBothForms:
    def test_rewrites_both_forms_in_file(
        self, tmp_path: Path, fixture_test_file: Path
    ) -> None:
        sites = scanner.scan_file(fixture_test_file, tmp_path, "tx_foo")
        bare_sites = [s for s in sites if s.style == "bare"]
        n = scanner.apply_rewrites_to_file(fixture_test_file, bare_sites)
        # 4 处裸 import 全部应改写
        assert n == 4

        new_content = fixture_test_file.read_text(encoding="utf-8")
        # from 形式
        assert (
            "from services.tx_foo.src.services.cashier_engine import OrderEngine"
            in new_content
        )
        assert (
            "from services.tx_foo.src.api.cashier_routes import router"
            in new_content
        )
        # import 形式（关键 — #318 follow-up 修补点）
        assert (
            "import services.tx_foo.src.api.cashier_routes as _cashier_mod"
            in new_content
        )
        assert "import services.tx_foo.src.services.payment_service" in new_content
        # 第三方 / 全路径未受影响
        assert "import os" in new_content
        assert "from datetime import datetime" in new_content
        assert "from . import sibling" in new_content
