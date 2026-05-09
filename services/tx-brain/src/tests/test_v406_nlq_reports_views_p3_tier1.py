"""Tier 1 — v406 NLQ reports schema 收尾视图静态校验

S4-02 PR2.A.3 — 收尾 mv_* 8 表暴露层（v404 #325 / v405 #326 续 4 个）。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. revision = "v406_nlq_reports_views_p3"，down_revision = "v405_nlq_reports_views_p2"
  2. 4 个视图必须 WITH (security_invoker = on)
  3. 敏感字段不暴露：
     - top_operators（discount_health 操作员 PII）
     - expiry_alerts / overdue_certificates（safety_compliance JSONB 含批次/证件 PII）
     - off_hours_anomalies（energy_efficiency JSONB 含设备 ID 异常明细）
  4. GRANT SELECT 各视图给 tx_nlq_readonly
  5. 不引入新 role / schema（沿用 v404）
  6. downgrade 反向 REVOKE + DROP VIEW（保留 role/schema）

延续 v404/v405 测试模式 — sql_only fixture 提取 op.execute 块避免 docstring 误报。
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
    / "v406_nlq_reports_views_p3.py"
)

_VIEW_NAMES = [
    "discount_health",
    "inventory_bom",
    "safety_compliance",
    "energy_efficiency",
]


@pytest.fixture(scope="module")
def migration_src() -> str:
    assert _MIGRATION_PATH.is_file(), f"v406 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_only(migration_src: str) -> str:
    """提取所有 op.execute(...) 块内的 SQL，剔除 docstring/注释。"""
    import re

    blocks = re.findall(r"op\.execute\([^)]*\)", migration_src, re.DOTALL)
    return "\n".join(blocks)


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_id(migration_src: str) -> None:
    assert 'revision: str = "v406_nlq_reports_views_p3"' in migration_src


def test_down_revision_chains_to_v405(migration_src: str) -> None:
    """v405 是 PR2.A.2 的 head（5/9 #326 merged 后）。"""
    assert (
        'down_revision: Union[str, None] = "v405_nlq_reports_views_p2"'
        in migration_src
    )


# ──────────────── 2. 视图 + security_invoker ────────────────


@pytest.mark.parametrize("view_name", _VIEW_NAMES)
def test_view_uses_security_invoker(
    migration_src: str, view_name: str
) -> None:
    """每个视图必须 CREATE 且 WITH (security_invoker = on)。"""
    assert f"CREATE VIEW {{_SCHEMA}}.{view_name}" in migration_src
    # 4 个视图 → security_invoker=on 至少出现 4 次
    assert migration_src.count("WITH (security_invoker = on)") >= 4


@pytest.mark.parametrize("view_name", _VIEW_NAMES)
def test_view_drops_before_create_idempotent(
    migration_src: str, view_name: str
) -> None:
    """视图前置 DROP VIEW IF EXISTS 保证幂等。"""
    assert f"DROP VIEW IF EXISTS {{_SCHEMA}}.{view_name}" in migration_src


# ──────────────── 3. 敏感字段不暴露 ────────────────


@pytest.mark.parametrize(
    "sensitive_col",
    [
        "top_operators",          # discount_health 操作员 PII
        "expiry_alerts",          # safety_compliance JSONB 批次明细
        "overdue_certificates",   # safety_compliance JSONB 证件明细
        "off_hours_anomalies",    # energy_efficiency JSONB 异常/设备 ID
        "last_event_id",          # 实现细节
        "updated_at",             # 实现细节
    ],
)
def test_sensitive_columns_not_exposed(
    sql_only: str, sensitive_col: str
) -> None:
    """敏感字段不在 SELECT 子句内（仅扫 op.execute 块，剔 SQL `--` 注释）。"""
    import re

    real_refs = []
    for line in sql_only.split("\n"):
        if "--" in line:
            line = line[: line.index("--")]
        if re.search(rf"\b{re.escape(sensitive_col)}\s*[,\n\r]?$", line):
            real_refs.append(line)
    assert not real_refs, (
        f"视图不应暴露敏感列 {sensitive_col}；命中：{real_refs}"
    )


# ──────────────── 4. GRANT 守约束 ────────────────


@pytest.mark.parametrize("view_name", _VIEW_NAMES)
def test_grants_select_on_each_view(
    migration_src: str, view_name: str
) -> None:
    """role 必须对每个视图有 SELECT 权限。"""
    assert (
        f"GRANT SELECT ON {{_SCHEMA}}.{view_name} TO {{_ROLE}}" in migration_src
    )


# ──────────────── 5. 不重复创建 v404 已有的 role / schema ────────────────


def test_does_not_recreate_role(sql_only: str) -> None:
    """role 由 v404 建，本迁移不应再 CREATE ROLE。"""
    assert "CREATE ROLE" not in sql_only


def test_does_not_recreate_schema(sql_only: str) -> None:
    """schema 由 v404 建，本迁移不应再 CREATE SCHEMA。"""
    assert "CREATE SCHEMA" not in sql_only


# ──────────────── 6. downgrade 反向 ────────────────


@pytest.mark.parametrize("view_name", _VIEW_NAMES)
def test_downgrade_revokes_and_drops_each_view(
    migration_src: str, view_name: str
) -> None:
    """downgrade 先撤 GRANT，再 DROP 视图。"""
    assert (
        f"REVOKE ALL ON {{_SCHEMA}}.{view_name} FROM {{_ROLE}}" in migration_src
    )
    assert f"DROP VIEW IF EXISTS {{_SCHEMA}}.{view_name}" in migration_src


def test_downgrade_does_not_drop_role_or_schema(sql_only: str) -> None:
    """ROLE/SCHEMA 由 v404 owner，本迁移 downgrade 不应触碰。"""
    assert "DROP ROLE" not in sql_only
    assert "DROP SCHEMA" not in sql_only
