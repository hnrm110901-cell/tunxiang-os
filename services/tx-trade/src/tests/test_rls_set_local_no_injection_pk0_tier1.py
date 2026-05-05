"""Tier 1 — PK.0 P0 SECURITY：禁止 SET LOCAL app.tenant_id f-string 拼接

发现路径（PK.0 修复）：
  - services/tx-trade/src/api/printer_config_routes.py:35
  - services/tx-trade/src/api/crew_stats_routes.py:46
  - services/tx-trade/src/api/print_manager_routes.py:42

风险：
  原代码 `text(f"SET LOCAL app.tenant_id = '{tenant_id}'")` 直接把
  X-Tenant-ID header（**用户可控**）拼进 SQL utility statement。攻击者可构造：
    X-Tenant-ID: tenant-a'; SET app.tenant_id = 'tenant-b'; --
  逃逸 RLS 多租户隔离 → 跨租户数据访问。CLAUDE.md §6/§13 RLS 多租户隔离是 Tier 1 零容忍路径。

修复：
  统一改用 `text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid}`
  与 shared/ontology/src/database.py:25 已有 helper 一致。set_config(..., true) 是
  PG 标准程序化设置 GUC 接口，完全参数化，无字符串拼接。

守门：
  本测试 source-level grep 全 services/ 范围，禁止任何文件用 f-string 拼接
  SET LOCAL app.tenant_id = '...' 模式。豁免：
    - shared/db-migrations/versions/*.py（_SYSTEM_TENANT 是 module 常量，无外部输入）
    - 注释/docstring 字面字符串（非真执行代码）

后续：tx-growth/src/api/growth_hub_routes.py 大量使用
  `text("SET LOCAL app.tenant_id = :tid"), {"tid": ...}` 模式 — PG SET 命令实际不支持
  bind parameters，需独立 PR (PK.0.1) 评估实际运行时行为并迁移到 set_config。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# 禁止模式：text(f"SET LOCAL app.tenant_id = '...{var}...'")
# 关键特征：text(f开头 + SET LOCAL app.tenant_id + 单引号包裹的 f-string 内容
_FSTRING_SET_LOCAL = re.compile(
    r"""text\(\s*[fF]['"][^'"]*SET\s+LOCAL\s+app\.tenant_id\s*=""",
    flags=re.IGNORECASE,
)

# 也禁止裸 f-string 拼接（不通过 text() 包装 — op.execute 等场景）
_RAW_FSTRING_SET_LOCAL = re.compile(
    r"""[fF]['"][^'"]*SET\s+LOCAL\s+app\.tenant_id\s*=\s*['"]\s*\{""",
    flags=re.IGNORECASE,
)

_SCAN_DIRS = ("services", "edge")

# 豁免：
#   - migration 内 _SYSTEM_TENANT 是 module 常量（无外部输入）
#   - 守门测试本文件 docstring 含字面 bad-pattern 字符串描述场景
_ALLOWLIST = {
    "shared/db-migrations/versions/v232_event_agent_bindings.py",
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
            # 跳过注释和 docstring 单行
            if stripped.startswith("#"):
                continue
            if _FSTRING_SET_LOCAL.search(line) or _RAW_FSTRING_SET_LOCAL.search(line):
                hits.append((rel, i, stripped))
    return hits


@pytest.mark.parametrize("rel_dir", _SCAN_DIRS)
def test_no_fstring_set_local_tenant_id(rel_dir: str) -> None:
    """services/ 与 edge/ 全域禁止 f-string 拼接 SET LOCAL app.tenant_id。"""
    hits = _scan_dir(rel_dir)
    if hits:
        msg = "\n  - ".join(f"{p}:{ln} → {src[:140]}" for p, ln, src in hits)
        pytest.fail(
            f"在 {rel_dir}/ 发现 {len(hits)} 处 RLS tenant_id f-string 拼接（P0 SECURITY）：\n"
            f"  - {msg}\n\n"
            "X-Tenant-ID 来自用户 header，f-string 拼接 → SQL 注入逃逸 RLS。\n"
            '请改用：text("SELECT set_config(\'app.tenant_id\', :tid, true)"), {"tid": tid}\n'
            "参考 shared/ontology/src/database.py:25 标准 helper。"
        )


# ──────────────── 修复后期望模式守门 ────────────────


@pytest.mark.parametrize(
    "rel_path",
    [
        "services/tx-trade/src/api/printer_config_routes.py",
        "services/tx-trade/src/api/crew_stats_routes.py",
        "services/tx-trade/src/api/print_manager_routes.py",
    ],
)
def test_fixed_files_use_set_config(rel_path: str) -> None:
    """PK.0 修复的 3 文件必须用 set_config(..., true) 参数化模式。"""
    p = _REPO_ROOT / rel_path
    assert p.is_file(), f"{rel_path} 不存在"
    text_body = p.read_text(encoding="utf-8")
    assert "set_config('app.tenant_id', :tid, true)" in text_body, (
        f"{rel_path} 未用 set_config 参数化模式 — PK.0 修复回退？"
    )
    # 双保险：确认无 f-string SET LOCAL 残留
    for i, line in enumerate(text_body.splitlines(), 1):
        if _FSTRING_SET_LOCAL.search(line) or _RAW_FSTRING_SET_LOCAL.search(line):
            pytest.fail(f"{rel_path}:{i} 仍有 f-string SET LOCAL：{line.strip()}")


def test_canonical_helper_unchanged() -> None:
    """shared/ontology/src/database.py 标准 helper 必须保留 set_config 参数化模式。"""
    p = _REPO_ROOT / "shared/ontology/src/database.py"
    text_body = p.read_text(encoding="utf-8")
    assert "set_config('app.tenant_id', :tid, true)" in text_body, (
        "shared/ontology/src/database.py 已不再用 set_config 参数化 — 严重退化"
    )
