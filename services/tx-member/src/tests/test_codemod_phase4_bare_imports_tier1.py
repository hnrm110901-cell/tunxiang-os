"""Tier 1 — #298 codemod Phase 4 守门：tx-member test 文件零裸 import

#298 chain Phase 4 — 在 #335 (Phase 3, tx-trade) 之后的次大头跨服务清理：
tx_member test 文件 112 处裸 import / 31 文件 全清。

为什么是 Tier 1：
  与 #335 同因 — 裸 import + 全路径 import 共存 → SQLAlchemy metadata
  同表双注册（PR #287 extend_existing band-aid 兜底）。band-aid 必须等
  全部 codemod chain（含 production 端 short-path）落地后才能撤（决策 77）。
  本守门保证 tx_member test 端不再回退裸 import，是撤 band-aid 的前置条件之一。

策略：
  复用 scripts/codemod/test_import_style_rewrite.py 的 scan_repo 做
  source-level 静态扫描（决策 80：AST 守门优于 mock，反映源码真相）。
  任何 tx-member test 文件再写 `from services.X / api.X / models.X / ...`
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


def test_tx_member_zero_bare_imports() -> None:
    """tx-member test 全文件不得包含裸 import（#298 Phase 4 守门）。"""
    sites = scanner.scan_repo(_REPO_ROOT)
    bare_in_tx_member = [
        s
        for s in sites
        if s.style == "bare"
        and s.rel_path.startswith("services/tx-member/")
    ]
    if bare_in_tx_member:
        offenders = "\n".join(
            f"  {s.rel_path}:{s.line}  {s.namespace}/{s.module}  →  {s.proposed}"
            for s in bare_in_tx_member
        )
        pytest.fail(
            f"tx-member test 文件出现 {len(bare_in_tx_member)} 处裸 import（违反 #298 Phase 4）：\n"
            f"{offenders}\n\n"
            "修复：python3 scripts/codemod/test_import_style_rewrite.py --apply --service tx-member"
        )
