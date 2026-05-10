"""ORM ↔ Migration drift 检测 Tier 1（rescue plan future work）

ORM model 声明 `__tablename__ = "X"` 但 migrations 没有任何 `CREATE TABLE X`
= drift（runtime 必坏：service 启动后 ORM query 撞 relation does not exist）。

反方向（migration 创建表但无 ORM model）= orphan，本测试不强制检测（可能是
lookup table / 历史保留 / 其他 service 用 raw SQL）。

为什么 Tier 1：drift 是 service runtime startup 失败的最常见原因之一。
B'-1 至 B'-6 recon 暴露的 22 bug 中至少 8 个属于这一类（class A 同名表撞
schema 也是 ORM/migration 不对齐的子集）。

策略：
  - 扫 services/*/src/models/**.py 找 `__tablename__ = "..."`
  - 扫 ALL migration dirs 找 `CREATE TABLE [IF NOT EXISTS] <name>`：
      shared/db-migrations/versions/                    (legacy mono-repo)
      shared/db-migrations-core/versions/               (路线 a 跨服务核心)
      services/*/db-migrations/versions/                (路线 a per-service)
  - diff: ORM 表 not in CREATE TABLE 全集 = drift
  - ratchet baseline 模式（同 schema_lint_tier1）

执行（CI）：在 migration-ci.yml schema lint step 一并跑（不阻塞 phase 4a-4
但暴露既有 drift）。
"""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent

# ── 扫 ORM `__tablename__` ──────────────────────────────────────────────────

_TABLENAME_RE = re.compile(
    r"""__tablename__\s*=\s*["']([a-z_][a-z0-9_]*)["']""",
)


def _scan_orm_tablenames() -> dict[str, list[str]]:
    """Return {table_name: [file_paths]}.

    Scan services/*/src/models/**/*.py + shared/ontology/src/**/*.py。
    """
    tables: dict[str, list[str]] = collections.defaultdict(list)
    candidates: list[Path] = []

    services_dir = REPO_ROOT / "services"
    if services_dir.is_dir():
        for svc_models in services_dir.glob("*/src/models"):
            candidates.extend(svc_models.rglob("*.py"))

    ontology_dir = REPO_ROOT / "shared/ontology/src"
    if ontology_dir.is_dir():
        candidates.extend(ontology_dir.rglob("*.py"))

    for path in candidates:
        try:
            src = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for m in _TABLENAME_RE.finditer(src):
            table = m.group(1)
            tables[table].append(str(path.relative_to(REPO_ROOT)))
    return dict(tables)


# ── 扫所有 migration CREATE TABLE ──────────────────────────────────────────

_CREATE_TABLE_RE = re.compile(
    r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[a-z_][a-z0-9_]*\.)?([a-z_][a-z0-9_]*)\s*\(""",
    re.IGNORECASE,
)
_OP_CREATE_TABLE_RE = re.compile(
    r"""op\.create_table\s*\(\s*["']([a-z_][a-z0-9_]*)["']""",
)


def _scan_migration_tablenames() -> set[str]:
    """Return all table names appearing in `CREATE TABLE` or `op.create_table` across:
    - shared/db-migrations/versions/
    - shared/db-migrations-core/versions/
    - services/*/db-migrations/versions/
    """
    tables: set[str] = set()
    migration_dirs = [
        REPO_ROOT / "shared/db-migrations/versions",
        REPO_ROOT / "shared/db-migrations-core/versions",
    ]
    services_dir = REPO_ROOT / "services"
    if services_dir.is_dir():
        for svc_versions in services_dir.glob("*/db-migrations/versions"):
            migration_dirs.append(svc_versions)

    for d in migration_dirs:
        if not d.is_dir():
            continue
        for path in d.glob("*.py"):
            if path.name.startswith("__") or path.name.endswith(".disabled"):
                continue
            try:
                src = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for m in _CREATE_TABLE_RE.finditer(src):
                tables.add(m.group(1))
            for m in _OP_CREATE_TABLE_RE.finditer(src):
                tables.add(m.group(1))
    return tables


# ── drift 计算 ──────────────────────────────────────────────────────────────

def _compute_orm_drift() -> dict[str, list[str]]:
    """Return {table_name: [orm_files]} for ORM tables NOT found in any migration."""
    orm = _scan_orm_tablenames()
    migration_tables = _scan_migration_tablenames()
    return {t: files for t, files in orm.items() if t not in migration_tables}


# ── baseline ratchet ───────────────────────────────────────────────────────

# Phase 4a-3 baseline — 起点 18 处 drift（PR #357 锁定）。
# Ratchet: 18 (起点) → 15 (PR #360 Class B 命名漂移) → 12 (PR #361 retail_mall revive +
# Class F SECURITY 修) → 10 (PR #362 distribution_trips/items revive) →
# 7 (PR #363 fund_settlement 三表 revive) → 4 (本 PR Class C dead ORM 清理 —
# audit 见 docs/orm-drift-class-c-audit.md，删 banquet_menu_templates_v2 /
# daily_plans / stored_value_account_transactions 三个 ORM-only 0 引用 dead 类)。
#
# 剩余 4 张全部 Class C LIVE（待 v410 revive PR 收尾归零）：
#   brand_groups (tx-member, group_member_service heavy raw SQL) /
#   cook_time_baselines (tx-trade, cook_time_stats raw SQL) /
#   delivery_auto_accept_rules (tx-trade, ORM CRUD via Repository) /
#   kds_tasks (tx-trade, 9+ raw SQL CRUD 跨 5 文件) — 需 v410 单 migration 全部 revive
# 修一个 drift → ratchet 下调本数值。终态 0：所有 ORM model 都有对应 migration 创建路径。
_ORM_DRIFT_BASELINE = 4


def test_orm_migration_drift_no_new_violations():
    """ORM `__tablename__` 全部应在 migrations 中有对应 CREATE TABLE。

    drift 检测：ORM 声明了表但 migration 完全没创建 → service runtime 撞 'relation
    does not exist'。

    当前 baseline ({_ORM_DRIFT_BASELINE}) 是 placeholder — 路线 a Phase 4a-4 baseline
    入栈后，所有真实表会被 production schema squash 写入 baseline.sql，drift 数
    应大幅下降至接近 0。
    """
    drift = _compute_orm_drift()
    assert len(drift) <= _ORM_DRIFT_BASELINE, (
        f"ORM drift 数 {len(drift)} 超 baseline {_ORM_DRIFT_BASELINE}\n"
        + "前 30 处 drift（ORM 表名 → ORM 文件）:\n"
        + "\n".join(
            f"  {t}: {files[0] if files else '?'}"
            + (f" (+{len(files)-1} more)" if len(files) > 1 else "")
            for t, files in sorted(drift.items())[:30]
        )
        + (f"\n  ... +{len(drift) - 30} more" if len(drift) > 30 else "")
    )


def test_drift_baseline_ratchet_hint():
    """信息性测试：实际 drift < baseline 时提示 ratchet 下调。"""
    drift = _compute_orm_drift()
    actual = len(drift)
    if actual < _ORM_DRIFT_BASELINE:
        print(
            f"\n[ratchet hint] ORM drift baseline = {_ORM_DRIFT_BASELINE}, "
            f"实际 = {actual}; 下个 PR 中下调 baseline 到 {actual}（终态 0）。"
        )
