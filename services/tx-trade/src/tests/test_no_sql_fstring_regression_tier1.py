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
# PJ.6 + PK.2-fix: SQLAlchemy text() 包装的 f-string 也算注入面，且必须跨行扫描。
# 模式 `\s*` 已经匹配 `\n`，所以同一 regex 同时覆盖：
#   text(f"...")            （单行）
#   text(\n    f"""...""")  （多行 — tx-finance/tx-supply 主流写法）
# 关键：scanner 必须 read 整个 body 用 finditer/findall，**不能** splitlines 后逐行。
# 此前因逐行扫漏 60%+ 真实命中（tx-trade: 33→139, tx-finance: 21→59, tx-supply: 23→78）。
_TEXT_FSTRING_PATTERN = re.compile(r"""text\(\s*[fF]['"]""")


def _scan_file(rel_path: str) -> list[tuple[int, str]]:
    """单文件扫 f-string SQL 行/块。

    命中条件（任一）：
      1. 行内有 f-string 起始 + 命中 SQL 关键字
      2. text(f"..." 包装（含跨行：text( 后换行接 f-string 字面量）
    """
    p = _REPO_ROOT / rel_path
    if not p.is_file():
        return []
    try:
        body = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    seen_lines: set[int] = set()
    lines = body.splitlines()
    # 规则 1：f-string + SQL keyword（按行）
    for i, line in enumerate(lines, 1):
        if _FSTRING_START.search(line) and any(kw in line for kw in _SQL_KEYWORDS):
            hits.append((i, line.strip()))
            seen_lines.add(i)
    # 规则 2：text(f"..." 包装（含跨行）— finditer 整 body + 反算行号
    for m in _TEXT_FSTRING_PATTERN.finditer(body):
        line_no = body[: m.start()].count("\n") + 1
        if line_no in seen_lines:
            continue
        hits.append((line_no, lines[line_no - 1].strip()))
        seen_lines.add(line_no)
    hits.sort(key=lambda h: h[0])
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


# ──────────────── PK.1+2+3 (PK.2-fix 整改后)：Tier 1 财务红线域 baseline 守门 ────────────────
#
# 三大 Tier 1 域统一精确 baseline 双向锁定：
#   - 命中数 > baseline：新 PR 引入 text(f) → fail，强迫改用 :param + bindparams
#   - 命中数 < baseline：清理已发生 → fail（迫使下调 baseline 显式 review 清理范围）
#
# baseline 数=本 PR 整改后的实测命中数（含多行 text(\n  f"""...""")）。
# 当前命中均为项目内白名单 conditions list / set_clauses 拼接，零真注入面。
# 不强制立即清理（噪音改动 ROI 低），但冻结后续退化。
#
# PK.2-fix 历史教训：原 scanner 单行扫漏 60%+ 真实命中（老 33/21/23 是单行子集），
# 真实总数应为 139/59/78。任何新 baseline 调整必须 re-run `findall` 整 body。


def _count_text_fstring_in_dir(rel_dir: str) -> int:
    """统计目录内所有 .py 的 text(f"...") 命中数（生产代码，排除 tests/）。

    PK.2-fix：必须 findall 整 body — 单行 splitlines 会漏多行
    text(...换行...f-string)（tx-finance/tx-supply 主流写法，曾漏 60%+ 真实命中）。
    """
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
        count += len(_TEXT_FSTRING_PATTERN.findall(body))
    return count


# 三大 Tier 1 域 baseline。下调请把对应数字改小，同 PR review。
# 上调（=新增 text(f) 拼接）请改走 :param + bindparams 模式（参考 PK.0
# shared/ontology/src/database.py:25 set_config helper）。
_TIER1_TEXT_FSTRING_BASELINES: dict[str, int] = {
    "services/tx-trade/src": 139,  # PK.1 / PK.2-fix 校准
    "services/tx-finance/src": 59,  # PK.2 / PK.2-fix 校准
    # PR #625 (PR-01C round-2 P1-3) 加 1 — cert_service.count_certificates
    # 同 _TIER1_TEXT_SQLVAR_BASELINES 注释（同一处 text(f"...") 触发两条 baseline），
    # where_sql 由硬编码字面量 + 参数占位组成，无用户输入注入面。
    "services/tx-supply/src": 79,  # PK.3 / PK.2-fix 校准 + PR-01C count_certificates
}


@pytest.mark.parametrize(
    "rel_dir,baseline",
    sorted(_TIER1_TEXT_FSTRING_BASELINES.items()),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_tier1_text_fstring_baseline_exact(rel_dir: str, baseline: int) -> None:
    """Tier 1 域 text(f) 命中数必须精确等于 baseline（防退化 + 防漂移）。

    新增 text(f) → fail；清理 → 同步下调 _TIER1_TEXT_FSTRING_BASELINES[rel_dir]。
    """
    current = _count_text_fstring_in_dir(rel_dir)
    if current > baseline:
        pytest.fail(
            f"{rel_dir} text(f) 命中数 {current} > baseline {baseline}\n"
            "Tier 1 域引入新 text(f) f-string SQL — "
            "请改用 :param 占位 + bindparams（参考 PK.0 set_config 模式，"
            "shared/ontology/src/database.py:25）。\n"
            "若确实必要（如新动态 WHERE 拼接 helper），更新 _TIER1_TEXT_FSTRING_BASELINES "
            f"中 {rel_dir!r} 的值并加注释说明。"
        )
    if current < baseline:
        pytest.fail(
            f"{rel_dir} text(f) 命中数 {current} < baseline {baseline}\n"
            f"已有清理工作，请下调 _TIER1_TEXT_FSTRING_BASELINES[{rel_dir!r}] 锁定新基线。"
        )


# ──────────────── PK.2-fix +：text(<sql_var>) 变量间接注入面守门 ────────────────
#
# strict-code-reviewer Suggestion #6：除 text(f"..." )，还有 text(sql) /
# text(stmt) / text(*_sql) 模式 — SQL 先拼到变量再 execute。如果变量是字符串
# 拼接构造的（sql = "SELECT ... " + clause），同样可注入。
#
# 不直接 ban — 这是项目内合法 helper 模式（动态拼复杂 WHERE/ORDER BY 的常用写法）。
# 套同 baseline 双向锁定模式，冻结现状，迫使新增 reviewer 走 :param + bindparams。
#
# 范围限制：仅 sql / stmt / query / *_sql / *_stmt / *_query 这些 SQL 习惯命名，
# 排除 text(self) / text(request) / text(message) 等显然非 SQL 的伪命中。
_TEXT_SQLVAR_PATTERN = re.compile(r"""text\(\s*((?:sql|stmt|query)|[a-z_]+_(?:sql|stmt|query))\s*[,)]""")


def _count_text_sqlvar_in_dir(rel_dir: str) -> int:
    """统计目录内所有 .py 的 text(<sql_var>) 命中数（含 text(sql) / text(*_sql)）。"""
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
        count += len(_TEXT_SQLVAR_PATTERN.findall(body))
    return count


_TIER1_TEXT_SQLVAR_BASELINES: dict[str, int] = {
    "services/tx-trade/src": 15,  # PK.2-fix 立项时实测
    "services/tx-finance/src": 4,
    # PR #625 (PR-01C round-2 P1-3) 加 1 — cert_service.count_certificates
    # 用 text(f"... WHERE {where_sql}") 拼分页 COUNT(*)，where_sql 由
    # 硬编码字面量 + 参数占位 :tenant_id/:supplier_id/:today 组成，无用户
    # 输入注入面（status 枚举由 FastAPI Query pattern= 校验过滤），
    # 与同文件 list_certificates 同模式。
    "services/tx-supply/src": 8,
}


@pytest.mark.parametrize(
    "rel_dir,baseline",
    sorted(_TIER1_TEXT_SQLVAR_BASELINES.items()),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_tier1_text_sqlvar_baseline_exact(rel_dir: str, baseline: int) -> None:
    """Tier 1 域 text(<sql_var>) 命中数必须精确等于 baseline（防退化 + 防漂移）。

    新增 text(sql) / text(stmt) / text(*_sql) → fail；清理 → 同步下调
    _TIER1_TEXT_SQLVAR_BASELINES[rel_dir]。
    """
    current = _count_text_sqlvar_in_dir(rel_dir)
    if current > baseline:
        pytest.fail(
            f"{rel_dir} text(<sql_var>) 命中数 {current} > baseline {baseline}\n"
            "Tier 1 域引入新 text(sql) / text(stmt) 变量间接调用 — "
            "如变量来自字符串拼接则可注入，请改用 :param 占位 + bindparams。\n"
            f"若确实必要，更新 _TIER1_TEXT_SQLVAR_BASELINES[{rel_dir!r}] 的值并加注释说明。"
        )
    if current < baseline:
        pytest.fail(
            f"{rel_dir} text(<sql_var>) 命中数 {current} < baseline {baseline}\n"
            f"已有清理工作，请下调 _TIER1_TEXT_SQLVAR_BASELINES[{rel_dir!r}] 锁定新基线。"
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
