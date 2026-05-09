"""Tier 1 — v404 NLQ readonly role + reports 视图静态校验

S4-02 PR2.A — 建 NLQ 沙箱第二层 DB 防御（schema + role + 视图 + GRANT）。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. revision = "v404_nlq_readonly_views_role"，down_revision = "v403_dashboard_pinned"
  2. CREATE SCHEMA reports（IF NOT EXISTS 幂等）
  3. CREATE ROLE tx_nlq_readonly NOLOGIN（DO $$ EXCEPTION duplicate_object 块兜底幂等）
  4. 视图 reports.daily_revenue / reports.member_clv：
       - 必须 WITH (security_invoker = on)（PG 15+，让 RLS 跟调用者 app.tenant_id）
       - daily_revenue 必须过滤 status='closed'（仅暴露已结算）
       - daily_revenue 不得暴露 cash_discrepancy_fen / pending_items（敏感）
       - member_clv 不得暴露 churn_probability / next_visit_days（预测字段）
  5. GRANT 守约束：
       - GRANT USAGE ON SCHEMA reports TO tx_nlq_readonly
       - GRANT SELECT ON 各视图 TO tx_nlq_readonly
       - REVOKE ALL ON SCHEMA public FROM tx_nlq_readonly（防 LLM 直查原表）
  6. downgrade 反向 REVOKE + DROP 视图（保留 role/schema 防误删依赖）

参考 v403 / v395 静态扫描模式 — 不需要真连 DB，纯字符串扫迁移源代码。
真 PG 行为（视图 RLS 实际生效 / GRANT 后 LLM SQL 越权拒）留 PR2.D
（仓库级 docker-compose-pg fixture 落地后）。
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
    / "v404_nlq_readonly_views_role.py"
)


@pytest.fixture(scope="module")
def migration_src() -> str:
    assert _MIGRATION_PATH.is_file(), f"v404 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_only(migration_src: str) -> str:
    """提取所有 op.execute(...) 块内的 SQL 字符串，剔除 Python docstring/comments。

    用于敏感字段 / 关键字检测，避免误报（docstring 里提及 'DROP ROLE' 不算真创建）。
    """
    import re

    # 匹配 op.execute( 后到匹配的右括号 ) 之间的内容（含三引号字符串）
    blocks = re.findall(r"op\.execute\([^)]*\)", migration_src, re.DOTALL)
    return "\n".join(blocks)


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_id(migration_src: str) -> None:
    assert 'revision: str = "v404_nlq_readonly_views_role"' in migration_src


def test_down_revision_chains_to_v403(migration_src: str) -> None:
    """v403_dashboard_pinned 是当前 alembic head（5/9 凌晨 #316 merged 后）。"""
    assert 'down_revision: Union[str, None] = "v403_dashboard_pinned"' in migration_src


# ──────────────── 2. CREATE SCHEMA reports ────────────────


def test_creates_reports_schema_idempotent(migration_src: str) -> None:
    """schema 必须 IF NOT EXISTS（幂等，env 重跑迁移不报错）。"""
    assert "CREATE SCHEMA IF NOT EXISTS {_SCHEMA}" in migration_src


# ──────────────── 3. CREATE ROLE tx_nlq_readonly ────────────────


def test_creates_role_with_nologin(migration_src: str) -> None:
    """role 必须 NOLOGIN — 通过 SET ROLE 进入，不持密码。"""
    assert "CREATE ROLE {_ROLE} NOLOGIN" in migration_src


def test_role_creation_is_idempotent(migration_src: str) -> None:
    """PG 无 CREATE ROLE IF NOT EXISTS，必须用 DO $$ EXCEPTION duplicate_object 兜底。"""
    assert "DO $$" in migration_src
    assert "WHEN duplicate_object THEN" in migration_src


def test_role_constant_is_tx_nlq_readonly(migration_src: str) -> None:
    """role 名锁定 tx_nlq_readonly（PR2.B sql_generator SET ROLE 调用契约）。"""
    assert '_ROLE = "tx_nlq_readonly"' in migration_src


# ──────────────── 4. 视图 + security_invoker ────────────────


@pytest.mark.parametrize(
    "view_name", ["daily_revenue", "member_clv"]
)
def test_view_uses_security_invoker(migration_src: str, view_name: str) -> None:
    """每个视图必须 WITH (security_invoker = on) — PG 15+ 让 RLS 跟调用者上下文，
    避免 view owner 持 BYPASSRLS 时跨租户绕过。"""
    assert f"CREATE VIEW {{_SCHEMA}}.{view_name}" in migration_src
    # security_invoker=on 是关键安全配置，每个视图必须独立声明
    # 静态扫描：CREATE VIEW + WITH (security_invoker 同时出现在源中
    assert "WITH (security_invoker = on)" in migration_src


def test_daily_revenue_filters_closed_status(migration_src: str) -> None:
    """daily_revenue 必须过滤 status='closed' — 未结算的日数据不应暴露给 LLM。"""
    assert "WHERE status = 'closed'" in migration_src


@pytest.mark.parametrize(
    "sensitive_col",
    [
        "cash_discrepancy_fen",  # daily_revenue 不得暴露差异
        "pending_items",          # 待审核项含 PII
        "churn_probability",      # member_clv 预测字段，LLM 误用风险
        "next_visit_days",        # 同上
    ],
)
def test_sensitive_columns_not_exposed(
    sql_only: str, sensitive_col: str
) -> None:
    """敏感字段不在 SELECT 子句内（仅扫 op.execute 块，docstring 提及不算）。

    SQL 列名出现的位置只能是 SELECT/INSERT 子句 — 在 op.execute 块外提及（如
    docstring 列举"为何不暴露"）不算真泄露。
    """
    # 检查只扫 op.execute 块；列名出现 = SQL 内引用 = 真暴露
    # 注释行 `-- 不暴露 cash_discrepancy_fen` 在 op.execute 块内 SQL 字符串内，
    # 但是以 `-- ` 开头的 SQL 注释，不会被 PG 解析为列引用
    # 用更精确的"列名 + 逗号或换行"模式排除注释
    import re

    # 匹配列名后跟 , 或 \n 或 \r（真引用）；SQL 注释 `-- col_name 是为什么不暴露` 不会命中
    pattern = rf"\b{re.escape(sensitive_col)}\s*[,\n\r]"
    matches = re.findall(pattern, sql_only)
    # 但 SQL 注释行 `-- 不暴露 cash_discrepancy_fen / pending_items` 也会命中
    # 所以再检查命中行是否是 SQL 注释（行首是 -- 或 行内 -- 之后）
    real_refs = []
    for line in sql_only.split("\n"):
        stripped = line.strip()
        # 跳过 SQL 注释（-- 之后）
        if "--" in line:
            line = line[: line.index("--")]
        if re.search(rf"\b{re.escape(sensitive_col)}\s*[,\n\r]?$", line):
            real_refs.append(line)
    assert not real_refs, (
        f"视图 SELECT 子句不应暴露敏感列 {sensitive_col}；命中：{real_refs}"
    )


# ──────────────── 5. GRANT 守约束 ────────────────


def test_grants_usage_on_reports_schema(migration_src: str) -> None:
    """role 必须能 USAGE 进入 reports schema 才能查视图。"""
    assert "GRANT USAGE ON SCHEMA {_SCHEMA} TO {_ROLE}" in migration_src


@pytest.mark.parametrize(
    "view_name", ["daily_revenue", "member_clv"]
)
def test_grants_select_on_each_view(
    migration_src: str, view_name: str
) -> None:
    """role 必须对每个视图有 SELECT 权限。"""
    assert f"GRANT SELECT ON {{_SCHEMA}}.{view_name} TO {{_ROLE}}" in migration_src


def test_revokes_public_schema_usage(migration_src: str) -> None:
    """关键防御：显式 REVOKE public schema USAGE — 否则 LLM SQL 直查 mv_*/orders/customers
    等敏感原表（PG 默认所有 role 隐式 USAGE ON public）。"""
    assert "REVOKE ALL ON SCHEMA public FROM {_ROLE}" in migration_src


# ──────────────── 6. downgrade 反向 ────────────────


def test_downgrade_revokes_grants(migration_src: str) -> None:
    """downgrade 先撤 GRANT 防 dangling 权限。"""
    assert "REVOKE ALL ON SCHEMA {_SCHEMA} FROM {_ROLE}" in migration_src
    assert "REVOKE ALL ON {_SCHEMA}.daily_revenue FROM {_ROLE}" in migration_src
    assert "REVOKE ALL ON {_SCHEMA}.member_clv FROM {_ROLE}" in migration_src


def test_downgrade_drops_views(migration_src: str) -> None:
    """downgrade DROP VIEW IF EXISTS（幂等）— 视图被删后 GRANT 自动失效。"""
    assert "DROP VIEW IF EXISTS {_SCHEMA}.daily_revenue" in migration_src
    assert "DROP VIEW IF EXISTS {_SCHEMA}.member_clv" in migration_src


def test_downgrade_does_not_drop_role_or_schema(sql_only: str) -> None:
    """ROLE/SCHEMA 是 cluster-level，可能被其他迁移依赖 — 不主动 DROP，运维手动清理。

    扫 op.execute 块内 SQL，docstring 提及 'DROP ROLE' 不算（注释/解释用途）。
    """
    assert "DROP ROLE" not in sql_only, "downgrade 不应执行 DROP ROLE（cluster-level）"
    assert "DROP SCHEMA" not in sql_only, "downgrade 不应执行 DROP SCHEMA（可能被依赖）"
