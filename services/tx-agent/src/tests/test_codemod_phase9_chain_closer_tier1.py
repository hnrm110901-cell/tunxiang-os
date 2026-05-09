"""Tier 1 — #298 codemod Phase 9 chain closer：余 7 服务 test 文件零裸 import

#298 chain Phase 9 — 续 #335 / #338 / #341 / #344 / #348 / #349 之后，
**chain 收官 PR**：余 7 服务一波清（gateway / tx-agent / tx-analytics /
tx-brain / tx-intel / tx-menu / tx-ops）共 ~159 处裸 import / 65 文件 全清。

为什么是 Tier 1：
  与前 6 PR 同因 — 裸 import + 全路径 import 共存 → SQLAlchemy metadata
  同表双注册（PR #287 extend_existing band-aid 兜底）。本 PR 完成后
  chain 100%（test 端），是撤 band-aid 的关键前置（决策 77，仍需 production
  端 short-path 跟进）。

策略：
  复用 scripts/codemod/test_import_style_rewrite.py 的 scan_repo 做
  source-level 静态扫描（决策 80：AST 守门优于 mock，反映源码真相）。
  本 fixture 一次性守住 7 服务（统一防回退），任何回退即时 fail，
  附带服务:文件:行号:模块定位。

为什么单 fixture 而不是 7 个：
  - chain 收官需统一断言"余 7 服务全清"
  - 单 fixture 失败信息更聚合，便于回退批量识别
  - 仍 service-scoped（只看 7 服务路径），不影响其他 fixture 独立性
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCANNER_DIR = _REPO_ROOT / "scripts" / "codemod"
sys.path.insert(0, str(_SCANNER_DIR))

import test_import_style_rewrite as scanner  # noqa: E402  pyright: ignore[reportMissingImports]

# 余 7 服务（含 tx-civic — 实测 0 处但纳入守门防回退）
PHASE9_SERVICES = (
    "services/gateway/",
    "services/tx-agent/",
    "services/tx-analytics/",
    "services/tx-brain/",
    "services/tx-civic/",
    "services/tx-intel/",
    "services/tx-menu/",
    "services/tx-ops/",
)


def test_phase9_services_zero_bare_imports() -> None:
    """Phase 9 余 7 服务 test 全文件不得包含裸 import（#298 chain 收官守门）。"""
    sites = scanner.scan_repo(_REPO_ROOT)
    bare = [
        s
        for s in sites
        if s.style == "bare"
        and any(s.rel_path.startswith(p) for p in PHASE9_SERVICES)
    ]
    if bare:
        offenders = "\n".join(
            f"  {s.rel_path}:{s.line}  {s.namespace}/{s.module}  →  {s.proposed}"
            for s in bare
        )
        pytest.fail(
            f"#298 chain Phase 9 余 7 服务出现 {len(bare)} 处裸 import：\n"
            f"{offenders}\n\n"
            "修复（按服务）：python3 scripts/codemod/test_import_style_rewrite.py --apply --service <svc>"
        )
