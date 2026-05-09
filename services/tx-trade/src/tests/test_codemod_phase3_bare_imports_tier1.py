"""Tier 1 — #298 codemod Phase 3 守门：tx-trade test 文件零裸 import

#298 chain 上半场（#318/#320/#322）改写 tx_trade top-20 文件。Phase 3 收尾：
扫尾余下的 tx_trade test 文件，强制裸 import 计数归 0。

为什么是 Tier 1：
  裸 import + 全路径 import 共存 → SQLAlchemy metadata 同表双注册（PR #287
  extend_existing band-aid 兜底）。band-aid 必须等 codemod 全覆盖（包括
  production 端 short-path import 也清掉）才能撤（决策 77）；本守门保证
  test 端 tx-trade 不再回退裸 import，是撤 band-aid 的前置条件之一。

策略：
  复用 scripts/codemod/test_import_style_rewrite.py 的 scan_repo + filter_sites
  做 source-level 静态扫描（决策 80：AST 守门优于 mock，反映源码真相）。
  任何 tx-trade test 文件再写 `from services.X / api.X / models.X / ...`
  形式裸 import 即时 fail，附带文件:行号:模块定位。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCANNER_DIR = _REPO_ROOT / "scripts" / "codemod"
sys.path.insert(0, str(_SCANNER_DIR))

import test_import_style_rewrite as scanner  # noqa: E402  pyright: ignore[reportMissingImports]


def test_tx_trade_zero_bare_imports() -> None:
    """tx-trade test 全文件不得包含裸 import（#298 Phase 3 守门）。"""
    sites = scanner.scan_repo(_REPO_ROOT)
    bare_in_tx_trade = [
        s
        for s in sites
        if s.style == "bare"
        and s.rel_path.startswith("services/tx-trade/")
    ]
    if bare_in_tx_trade:
        offenders = "\n".join(
            f"  {s.rel_path}:{s.line}  {s.namespace}/{s.module}  →  {s.proposed}"
            for s in bare_in_tx_trade
        )
        pytest.fail(
            f"tx-trade test 文件出现 {len(bare_in_tx_trade)} 处裸 import（违反 #298 Phase 3）：\n"
            f"{offenders}\n\n"
            "修复：python3 scripts/codemod/test_import_style_rewrite.py --apply --service tx-trade"
        )
