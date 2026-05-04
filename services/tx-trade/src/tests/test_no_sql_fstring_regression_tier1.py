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


def _scan_file(rel_path: str) -> list[tuple[int, str]]:
    """单文件扫 f-string SQL 行。"""
    p = _REPO_ROOT / rel_path
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if not _FSTRING_START.search(line):
            continue
        if any(kw in line for kw in _SQL_KEYWORDS):
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
