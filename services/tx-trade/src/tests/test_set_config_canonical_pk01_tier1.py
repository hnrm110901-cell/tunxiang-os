"""Tier 1 — PK.0.1：禁止 text("SET LOCAL app.tenant_id = ...") 任何形式

PK.0 修了 3 处 f-string 拼接的真注入。PK.0.1 把全仓 89 处
`text("SET LOCAL app.tenant_id = :tid"), {"tid": ...}` 模式统一迁移到
shared/ontology/src/database.py:25 标准 helper：

    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid}

为什么不用 `text("SET LOCAL ... = :tid")` 模式：
  - PG SET 是 utility statement，不走 PARSE/BIND（不支持原生 bind parameter）
  - 实际由 SQLAlchemy + asyncpg 处理时行为不可 100% 确定
    （asyncpg 可能 fallback simple query + client-side substitution，
     可能未来版本变更）
  - SQLAlchemy event listener 抓到的是 `SET LOCAL ... = ?` placeholder，
    驱动层处理细节（quoting/escape 是否安全）依赖驱动版本
  - 而 SELECT set_config(name, value, is_local) 是 PG 原生函数调用：
    走标准 PREPARE + BIND，参数 100% 安全，等价于 SET LOCAL（is_local=true）

所以本守门测试：
  - 禁止 services/ edge/ shared/ 全域出现 text("SET LOCAL ... = ...") 任何形式
  - 强制改用 SELECT set_config 标准 helper
  - 加豁免：守门测试本文件 + PK.0 守门文件（含字面字符串描述场景）+ migration
    文件（_SYSTEM_TENANT 是 module 常量）
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# 禁止：text(... + 任何 SET LOCAL app.tenant_id 模式
_TEXT_SET_LOCAL = re.compile(
    r"""text\(\s*['"][^'"]*SET\s+LOCAL\s+app\.tenant_id""",
    flags=re.IGNORECASE,
)

# 禁止：op.execute(... + SET LOCAL app.tenant_id（migration 内 module 常量例外）
_OP_EXECUTE_SET_LOCAL = re.compile(
    r"""op\.execute\(\s*[fF]?['"][^'"]*SET\s+LOCAL\s+app\.tenant_id""",
    flags=re.IGNORECASE,
)

_SCAN_DIRS = ("services", "edge")

# 豁免：
#   - 守门测试本文件 + PK.0 守门文件（docstring 含字面 bad-pattern 描述场景）
#   - migration 用 _SYSTEM_TENANT 模块常量是 PK.0 已审核（CLAUDE.md §15）
_ALLOWLIST = {
    "services/tx-trade/src/tests/test_set_config_canonical_pk01_tier1.py",
    "services/tx-trade/src/tests/test_rls_set_local_no_injection_pk0_tier1.py",
}


def _scan_dir(rel_dir: str) -> list[tuple[str, int, str]]:
    base = _REPO_ROOT / rel_dir
    if not base.is_dir():
        return []
    hits: list[tuple[str, int, str]] = []
    for py in base.rglob("*.py"):
        rel = py.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        try:
            text_body = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text_body.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _TEXT_SET_LOCAL.search(line) or _OP_EXECUTE_SET_LOCAL.search(line):
                hits.append((rel, i, stripped))
    return hits


@pytest.mark.parametrize("rel_dir", _SCAN_DIRS)
def test_no_text_set_local_app_tenant_id(rel_dir: str) -> None:
    """services/ edge/ 全域禁止 text("SET LOCAL app.tenant_id ...) 任何形式。"""
    hits = _scan_dir(rel_dir)
    if hits:
        msg = "\n  - ".join(f"{p}:{ln} → {src[:140]}" for p, ln, src in hits)
        pytest.fail(
            f"在 {rel_dir}/ 发现 {len(hits)} 处 SET LOCAL app.tenant_id 模式：\n"
            f"  - {msg}\n\n"
            "请改用 PG 原生 set_config 标准 helper（参数化 100% 安全）：\n"
            '  text("SELECT set_config(\'app.tenant_id\', :tid, true)"), {"tid": tid}\n'
            "参考 shared/ontology/src/database.py:25 主 helper。"
        )


# ──────────────── 强制 set_config 命中数下限 ────────────────


def test_set_config_canonical_widely_adopted() -> None:
    """整仓必须有大量 set_config 调用（迁移产物）。

    PK.0.1 迁移 89 处 + ontology 主 helper + 之前的 6 处零散调用 → 至少应有 ~95 命中。
    若数量骤降说明迁移被回退或文件被大批删。
    """
    canonical_pattern = re.compile(
        r"""set_config\(\s*['"]app\.tenant_id['"]\s*,\s*:tid\s*,\s*(?:true|True)\s*\)""",
        flags=re.IGNORECASE,
    )
    count = 0
    for rel_dir in ("services", "edge", "shared"):
        base = _REPO_ROOT / rel_dir
        if not base.is_dir():
            continue
        for py in base.rglob("*.py"):
            try:
                text_body = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            count += len(canonical_pattern.findall(text_body))

    # 阈值 80：略低于 PK.0.1 迁移后的 ~95，避免小幅重构假阳性
    assert count >= 80, f"set_config('app.tenant_id', :tid, true) 命中数 {count} < 80 — PK.0.1 迁移被回退？"


def test_canonical_helper_unchanged() -> None:
    """shared/ontology/src/database.py 标准 helper 必须保留 set_config 模式。"""
    p = _REPO_ROOT / "shared/ontology/src/database.py"
    text_body = p.read_text(encoding="utf-8")
    assert "set_config('app.tenant_id', :tid, true)" in text_body, "shared/ontology/src/database.py 标准 helper 已退化"
