"""Tier 1 — 反退化：禁止 f-string 拼 SQL 重新潜入生产路径

P2.2 第二轮清理把 shared/apikeys/* 和 scripts/demo_seed.py 中所有
f-string 拼 SQL 全部改为静态字符串 + bind params。本测试守门防止退化。

为什么：
  - bandit/ruff S608 误报频繁，但偶有真实漏洞混入
  - 静态字符串 + :bind_param 是安全契约的最低标准
  - 即便 S608 是误报，f-string SQL 也增加未来真注入的可能（开发者不查
    上下文就以为安全）

策略：
  - 用 ruff S608 扫描全仓 → 命中数必须保持 0
  - 同步附 demo_seed.py / shared/apikeys/ 的 # noqa: S608 白名单审计
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_no_sql_injection_warnings_in_production_paths() -> None:
    """ruff S608 扫描 services/ shared/ edge/ scripts/ 必须零命中。

    若新增警告：
      - 真漏洞 → 改为静态 SQL + bind params
      - 误报（白名单常量）→ 加 # noqa: S608 + 注释为什么安全
    """
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "S608",
            "services/",
            "shared/",
            "edge/",
            "scripts/",
            "--output-format",
            "concise",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(
            f"S608 SQL injection warnings detected:\n{result.stdout}\n"
            "如确认安全（白名单常量/硬编码列表），加 # noqa: S608 + 解释注释；"
            "否则改为静态 SQL + bind params。"
        )


def test_apikeys_files_have_zero_fstring_sql() -> None:
    """shared/apikeys/ 下任何 .py 都不得出现 f"...SELECT..." 等 SQL f-string。"""
    apikeys = _REPO_ROOT / "shared" / "apikeys" / "src"
    if not apikeys.is_dir():
        pytest.skip("shared/apikeys/src 不存在")

    sql_keywords = ("SELECT", "INSERT", "UPDATE", "DELETE", "JOIN")
    hits: list[tuple[str, int, str]] = []

    for py in apikeys.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if not (stripped.startswith('f"') or stripped.startswith("f'")):
                continue
            if any(kw in line for kw in sql_keywords):
                hits.append((py.relative_to(_REPO_ROOT).as_posix(), i, line.strip()))

    if hits:
        msg = "\n".join(f"  {p}:{ln} → {src[:120]}" for p, ln, src in hits)
        pytest.fail(f"shared/apikeys/ 出现 {len(hits)} 处 f-string SQL：\n{msg}")
