"""Tier 1 — v405 NLQ reports schema 续补视图静态校验

S4-02 PR2.A.2 — store_pnl + channel_margin 视图（v404 #325 续补）。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. revision = "v405_nlq_reports_views_p2"，down_revision = "v404_nlq_readonly_views_role"
  2. 视图 reports.store_pnl / reports.channel_margin：
       - 必须 WITH (security_invoker = on)
       - 不暴露 last_event_id / updated_at（实现细节字段）
  3. GRANT SELECT 各视图给 tx_nlq_readonly
  4. 不引入新 role / schema（沿用 v404 的）
  5. downgrade 反向 REVOKE + DROP VIEW（保留 role/schema）

延续 v404 测试模式 — sql_only fixture 提取 op.execute 块避免 docstring 误报。
真 PG 行为留 PR2.D（仓库级 docker-compose-pg fixture 落地后）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/ → src/ → tx-brain/ → services/ → repo_root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = (
    _REPO_ROOT
    / "shared"
    / "db-migrations"
    / "versions"
    / "v405_nlq_reports_views_p2.py"
)


@pytest.fixture(scope="module")
def migration_src() -> str:
    assert _MIGRATION_PATH.is_file(), f"v405 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_only(migration_src: str) -> str:
    """提取所有 op.execute(...) 块内的 SQL，剔除 docstring/注释。"""
    import re

    blocks = re.findall(r"op\.execute\([^)]*\)", migration_src, re.DOTALL)
    return "\n".join(blocks)


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_id(migration_src: str) -> None:
    assert 'revision: str = "v405_nlq_reports_views_p2"' in migration_src


def test_down_revision_chains_to_v404(migration_src: str) -> None:
    """v404 是 PR2.A 的 head（5/9 #325 merged 后）。"""
    assert (
        'down_revision: Union[str, None] = "v404_nlq_readonly_views_role"'
        in migration_src
    )


# ──────────────── 2. 视图 + security_invoker ────────────────


@pytest.mark.parametrize("view_name", ["store_pnl", "channel_margin"])
def test_view_uses_security_invoker(
    migration_src: str, view_name: str
) -> None:
    """每个视图必须 WITH (security_invoker = on)。"""
    assert f"CREATE VIEW {{_SCHEMA}}.{view_name}" in migration_src
    # 静态扫描：security_invoker=on 至少出现 N 次（每个视图独立声明）
    assert migration_src.count("WITH (security_invoker = on)") >= 2


@pytest.mark.parametrize(
    "implementation_col",
    ["last_event_id", "updated_at"],
)
def test_implementation_columns_not_exposed(
    sql_only: str, implementation_col: str
) -> None:
    """实现细节字段不应在 SELECT 子句内（仅扫 op.execute 块）。

    SQL `--` 注释行内的列名不算暴露；用行内注释剥离逻辑。
    """
    import re

    real_refs = []
    for line in sql_only.split("\n"):
        # 跳过 SQL 注释
        if "--" in line:
            line = line[: line.index("--")]
        if re.search(rf"\b{re.escape(implementation_col)}\s*[,\n\r]?$", line):
            real_refs.append(line)
    assert not real_refs, (
        f"视图不应暴露实现细节列 {implementation_col}；命中：{real_refs}"
    )


def test_view_drops_before_create_idempotent(migration_src: str) -> None:
    """视图前置 DROP VIEW IF EXISTS 保证幂等（迁移可重跑）。"""
    assert "DROP VIEW IF EXISTS {_SCHEMA}.store_pnl" in migration_src
    assert "DROP VIEW IF EXISTS {_SCHEMA}.channel_margin" in migration_src


# ──────────────── 3. GRANT 守约束 ────────────────


@pytest.mark.parametrize("view_name", ["store_pnl", "channel_margin"])
def test_grants_select_on_each_view(
    migration_src: str, view_name: str
) -> None:
    """role 必须对每个视图有 SELECT 权限。"""
    assert (
        f"GRANT SELECT ON {{_SCHEMA}}.{view_name} TO {{_ROLE}}" in migration_src
    )


# ──────────────── 4. 不重复创建 v404 已有的 role / schema ────────────────


def test_does_not_recreate_role(sql_only: str) -> None:
    """role 由 v404 建，本迁移不应再 CREATE ROLE。"""
    assert "CREATE ROLE" not in sql_only, (
        "v405 不应重复 CREATE ROLE — v404 已建 tx_nlq_readonly"
    )


def test_does_not_recreate_schema(sql_only: str) -> None:
    """schema 由 v404 建，本迁移不应再 CREATE SCHEMA。"""
    assert "CREATE SCHEMA" not in sql_only, (
        "v405 不应重复 CREATE SCHEMA — v404 已建 reports"
    )


# ──────────────── 5. downgrade 反向 ────────────────


@pytest.mark.parametrize("view_name", ["store_pnl", "channel_margin"])
def test_downgrade_revokes_and_drops_each_view(
    migration_src: str, view_name: str
) -> None:
    """downgrade 先撤 GRANT，再 DROP 视图（幂等）。"""
    assert f"REVOKE ALL ON {{_SCHEMA}}.{view_name} FROM {{_ROLE}}" in migration_src
    assert f"DROP VIEW IF EXISTS {{_SCHEMA}}.{view_name}" in migration_src


def test_downgrade_does_not_drop_role_or_schema(sql_only: str) -> None:
    """ROLE/SCHEMA 由 v404 owner，本迁移 downgrade 不应触碰。"""
    assert "DROP ROLE" not in sql_only
    assert "DROP SCHEMA" not in sql_only
