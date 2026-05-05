"""Tier 1 — 反退化：P2.2 清理过的 3 文件不得退回 f-string SQL

P2.2 清理范围：
  - shared/apikeys/src/key_service.py    (5 处 f-string → 静态 SQL)
  - shared/apikeys/src/webhook_service.py (9 处 f-string → 静态 SQL)
  - scripts/demo_seed.py                  (1 处加 # noqa: S608 + 注释)

本测试只守这 3 文件 + 整个 shared/apikeys/src/ 目录强基线。
全仓 f-string SQL 清理是更大的工程，不在本 PR 范围。

为什么不全仓 grep：
  - 全仓约 400 处 f-string SQL，多数为内部白名单变量插值，零真注入风险
  - 一刀切会阻断所有不相关 PR
  - 真正的全仓收紧应分阶段：S608 ruff 规则 → 团队达成共识 → 大批量 codemod

PJ.6 增强 (2026-05-04)：
  扩展扫描器同时识别 SQLAlchemy `text(f"...")` / `text(f'...')` 包装模式 —
  这是项目内更高频的注入面（全仓 ~298 处），表面上"安全"因为走了 text() 但 f-string
  字符串拼接照样有风险。本测试守门范围不变（保护文件 + apikeys 强基线），
  规则同时适用，确保未来任何在保护范围内新增 text(f"...") 立即 fail。
  全仓 text(f) 清理是历史债（约 200 文件、298 处），需独立大规模 codemod。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# P2.2 改动过、必须保持零 f-string SQL 的文件
_PROTECTED_FILES = (
    "shared/apikeys/src/key_service.py",
    "shared/apikeys/src/webhook_service.py",
)

_FSTRING_START = re.compile(r"""(?<![A-Za-z_])[fF]['"]""")
_SQL_KEYWORDS = ("SELECT", "INSERT INTO", "UPDATE ", "DELETE FROM", " JOIN ")
# PJ.6: SQLAlchemy text() 包装的 f-string 也算注入面 — 即便没有命中
# _SQL_KEYWORDS（如分页 LIMIT/动态 ORDER BY 等），text(f"...") 本身就足以判红。
_TEXT_FSTRING_PATTERN = re.compile(r"""text\(\s*[fF]['"]""")


def _scan_file(rel_path: str) -> list[tuple[int, str]]:
    """单文件扫 f-string SQL 行。

    命中条件（任一）：
      1. 行内有 f-string 起始 + 命中 SQL 关键字
      2. 行内有 text(f"..." 或 text(f'..." 模式（PJ.6 新增）
    """
    p = _REPO_ROOT / rel_path
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        # 规则 1：f-string + SQL keyword
        if _FSTRING_START.search(line) and any(kw in line for kw in _SQL_KEYWORDS):
            hits.append((i, line.strip()))
            continue
        # 规则 2：text(f"...") 包装（PJ.6 新增）
        if _TEXT_FSTRING_PATTERN.search(line):
            hits.append((i, line.strip()))
    return hits


@pytest.mark.parametrize("rel_path", _PROTECTED_FILES)
def test_p22_cleaned_files_stay_clean(rel_path: str) -> None:
    """P2.2 已清理的文件必须保持零 f-string SQL。"""
    hits = _scan_file(rel_path)
    if hits:
        msg = "\n  - ".join(f"{rel_path}:{ln} → {src[:140]}" for ln, src in hits)
        pytest.fail(
            f"{rel_path} 出现 {len(hits)} 处 f-string SQL（P2.2 已清理过该文件）：\n  - {msg}\n\n"
            "请用静态 SQL + bind params；表名硬编码即可，无需模块常量。"
        )


# ──────────────── PK.1：tx-trade Tier 1 财务红线 baseline 守门 ────────────────
#
# tx-trade 是 Tier 1 财务红线域。当前 src/api + src/services + src/routers
# 共 33 处 text(f) 拼接，PK.0 审计已分类：
#   - 0 处真注入（已在 PK.0 修完 3 处 RLS f-string）
#   - 33 处都是项目内白名单 conditions list / set_clauses 拼接
#
# baseline 锁定上限 33，**不允许新增**：
#   - 新 PR 引入 text(f) → fail，强迫 reviewer 改用 :param + bindparams
#   - 重构减少命中 → fail（baseline 锁定为精确数，迫使开发者下调 baseline）
# 已存在的 33 处不强制立即清理（噪音改动 ROI 低），但守门冻结后续退化。


def _count_text_fstring_in_dir(rel_dir: str) -> int:
    """统计目录内所有 .py 的 text(f"...") 命中数（生产代码，排除 tests/）。"""
    base = _REPO_ROOT / rel_dir
    if not base.is_dir():
        return 0
    count = 0
    for py in base.rglob("*.py"):
        rel = py.relative_to(_REPO_ROOT).as_posix()
        if "/tests/" in rel:
            continue
        try:
            body = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in body.splitlines():
            if _TEXT_FSTRING_PATTERN.search(line):
                count += 1
    return count


# tx-trade 域 baseline：PK.0 审计后基线。下调请同步本数。
_TX_TRADE_TEXT_FSTRING_BASELINE = 33


def test_tx_trade_text_fstring_baseline_exact() -> None:
    """tx-trade 域 text(f) 命中数必须等于 baseline（防退化 + 防漂移）。

    - 命中数 > baseline：新 PR 引入 text(f)，请改用 :param + bindparams
      参考 PK.0 set_config 模式（shared/ontology/src/database.py:25）
    - 命中数 < baseline：清理工作已发生，请下调 _TX_TRADE_TEXT_FSTRING_BASELINE
      锁定新基线（精确锁定迫使每次清理都被显式 review）

    背景：PK.0 已修 3 处真注入（_set_rls f-string）；剩余 33 处都是
    项目内 conditions list / set_clauses 拼接（白名单内字段名，零真注入风险）。
    """
    current = _count_text_fstring_in_dir("services/tx-trade/src")
    if current > _TX_TRADE_TEXT_FSTRING_BASELINE:
        pytest.fail(
            f"tx-trade/src text(f) 命中数 {current} > baseline {_TX_TRADE_TEXT_FSTRING_BASELINE}\n"
            "Tier 1 财务红线域引入新 text(f) f-string SQL — "
            "请改用 :param 占位 + bindparams（参考 PK.0 set_config 模式）。\n"
            "若确实必要（如新动态 WHERE 拼接 helper），更新 baseline 数并加注释说明。"
        )
    if current < _TX_TRADE_TEXT_FSTRING_BASELINE:
        pytest.fail(
            f"tx-trade/src text(f) 命中数 {current} < baseline {_TX_TRADE_TEXT_FSTRING_BASELINE}\n"
            "已有清理工作，请下调 _TX_TRADE_TEXT_FSTRING_BASELINE 锁定新基线。"
        )


def test_apikeys_dir_strong_baseline() -> None:
    """shared/apikeys/src/ 整目录强基线 — 任何新增 .py 都不能引入 f-string SQL。"""
    apikeys = _REPO_ROOT / "shared" / "apikeys" / "src"
    if not apikeys.is_dir():
        pytest.skip("shared/apikeys/src 不存在")

    hits: list[tuple[str, int, str]] = []
    for py in apikeys.rglob("*.py"):
        rel = py.relative_to(_REPO_ROOT).as_posix()
        for ln, src in _scan_file(rel):
            hits.append((rel, ln, src))

    if hits:
        msg = "\n  - ".join(f"{p}:{ln} → {src[:140]}" for p, ln, src in hits)
        pytest.fail(f"shared/apikeys/ 出现 {len(hits)} 处 f-string SQL：\n  - {msg}")


def test_demo_seed_keeps_noqa_marker() -> None:
    """scripts/demo_seed.py 中 DELETE FROM {t} 一行必须保留 # noqa: S608 标注
    （否则误删 noqa 后 ruff 会再红，无声 regression）。"""
    p = _REPO_ROOT / "scripts" / "demo_seed.py"
    if not p.is_file():
        pytest.skip("scripts/demo_seed.py 不存在")
    text = p.read_text(encoding="utf-8")
    assert "DELETE FROM {t}" in text, "demo_seed.py 已被改名/重构，请同步本测试"
    # 找到该行并确认 noqa 标注存在
    for line in text.splitlines():
        if "DELETE FROM {t}" in line:
            assert "noqa: S608" in line, (
                "scripts/demo_seed.py DELETE FROM {t} 行缺 # noqa: S608 标注 — ruff S608 会再红，请加回去。"
            )
            return
    pytest.fail("找不到 DELETE FROM {t} 行")
