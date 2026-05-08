"""Tier1 — v403 dashboard_pinned 表 + RLS 静态校验

S4-04 PR2.A — 把 PR1 in-memory _PINNED_STORE 迁移到 PG。

校验点（CLAUDE.md §17 Tier1 路径必须 TDD）：
  1. revision = "v403_dashboard_pinned"，down_revision = "v402"
  2. CREATE TABLE 含 §6 标准列（tenant_id / created_at / updated_at / is_deleted）
     + 业务列（pin_id PK / pinner_user_id / pinned_at / surface_snapshot 等）
  3. 索引 (tenant_id, pinned_at DESC) WHERE is_deleted=FALSE
  4. RLS ENABLE + FORCE
  5. SELECT 策略 USING-only（SELECT 无写入侧）
  6. INSERT/UPDATE/DELETE 三条策略 USING + WITH CHECK（v395 PR #139 §19 修法）
  7. WITH CHECK 表达式与 USING 等价（NULLIF/current_setting 模式相同）
  8. downgrade DROP TABLE（PG CASCADE 级联清理 policies + index）

参考 services/tx-trade/src/tests/test_v395_delivery_dispatches_rls_tier1.py 模式 —
不需要真连 DB，纯静态扫描迁移源代码。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/ → src/ → tx-analytics/ → services/ → repo_root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = (
    _REPO_ROOT
    / "shared"
    / "db-migrations"
    / "versions"
    / "v403_dashboard_pinned.py"
)

_WRITE_ACTIONS = ("insert", "update", "delete")


@pytest.fixture(scope="module")
def migration_src() -> str:
    """读取 v403 迁移源代码。"""
    assert _MIGRATION_PATH.is_file(), f"v403 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_id(migration_src: str) -> None:
    assert 'revision: str = "v403_dashboard_pinned"' in migration_src


def test_down_revision_chains_to_v402(migration_src: str) -> None:
    """v402 是 5/8 时 main HEAD 上的最新 alembic revision。"""
    assert 'down_revision: Union[str, None] = "v402"' in migration_src


# ──────────────── 2. CREATE TABLE 含 §6 标准列 + 业务列 ────────────────


@pytest.mark.parametrize(
    "column",
    [
        "pin_id",
        "tenant_id",
        "pinner_user_id",
        "pinned_at",
        "surface_snapshot",
        "source_query_id",
        "source_natural_query",
        "created_at",
        "updated_at",
        "is_deleted",
    ],
)
def test_create_table_has_required_columns(
    migration_src: str, column: str
) -> None:
    """§6 标准列 + 业务列必须全部出现在 CREATE TABLE。"""
    assert column in migration_src, f"v403 CREATE TABLE 缺列 {column}"


def test_pin_id_is_uuid_pk_with_default(migration_src: str) -> None:
    assert "pin_id" in migration_src
    assert "UUID PRIMARY KEY DEFAULT gen_random_uuid" in migration_src


def test_tenant_id_not_null(migration_src: str) -> None:
    """tenant_id NOT NULL 是 §6 + RLS 双重要求。"""
    assert "tenant_id               UUID NOT NULL" in migration_src


def test_surface_snapshot_is_jsonb(migration_src: str) -> None:
    """A2UI declaration 必须 JSONB（支持 GIN 索引 + 路径查询）。"""
    assert "surface_snapshot        JSONB NOT NULL" in migration_src


# ──────────────── 3. 索引 ────────────────


def test_partial_index_on_tenant_pinned_at_desc(migration_src: str) -> None:
    """(tenant_id, pinned_at DESC) WHERE is_deleted=FALSE — list 路径高频。"""
    # f-string 模板形式（运行时拼成 ix_dashboard_pinned_tenant_pinned_at）
    assert "ix_{_TABLE}_tenant_pinned_at" in migration_src
    assert "(tenant_id, pinned_at DESC)" in migration_src
    assert "WHERE is_deleted = FALSE" in migration_src


# ──────────────── 4. RLS ENABLE + FORCE ────────────────


def test_rls_enabled(migration_src: str) -> None:
    assert "ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY" in migration_src


def test_rls_forced(migration_src: str) -> None:
    """FORCE 防 superuser 绕过；§13 禁止跳过 RLS。"""
    assert "ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY" in migration_src


# ──────────────── 5. SELECT 策略 USING-only ────────────────


def test_select_policy_is_using_only(migration_src: str) -> None:
    """SELECT 策略不带 WITH CHECK（SELECT 无写入侧）。

    f-string 多行拼接，分片段断言（参考 v395 测试模式）。
    """
    # 片段 1：策略名 + 表
    assert "CREATE POLICY rls_{_TABLE}_select ON {_TABLE} " in migration_src
    # 片段 2：SELECT 关键字
    assert "AS PERMISSIVE FOR SELECT TO PUBLIC " in migration_src
    # 片段 3：USING 表达式（结尾 `;` 而非空格 → 表明无后续 WITH CHECK）
    assert 'f"USING (tenant_id = {_RLS_EXPR});"' in migration_src


# ──────────────── 6. INSERT/UPDATE/DELETE 策略 USING + WITH CHECK ────────────────


def test_write_actions_loop_iterates_insert_update_delete(
    migration_src: str,
) -> None:
    """v395 PR #139 §19 修法：必须循环 INSERT / UPDATE / DELETE 三个写入 action
    建带 WITH CHECK 的策略。检查 _WRITE_ACTIONS 元组定义。"""
    assert '_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")' in migration_src
    assert "for action in _WRITE_ACTIONS:" in migration_src


def test_write_action_policy_template_has_using_and_with_check(
    migration_src: str,
) -> None:
    """循环内的 CREATE POLICY 模板同时含 USING + WITH CHECK 子句 —
    f-string 多行拼接，分片段断言。"""
    # 片段 1：循环里 policy 名以 _with_check 结尾
    assert (
        'policy = f"rls_{_TABLE}_{action.lower()}_with_check"' in migration_src
    )
    # 片段 2：CREATE POLICY 头
    assert 'f"CREATE POLICY {policy} ON {_TABLE} "' in migration_src
    # 片段 3：动作占位符
    assert 'f"AS PERMISSIVE FOR {action} TO PUBLIC "' in migration_src
    # 片段 4：USING 子句（注意结尾空格 → 后接 WITH CHECK，不是 `;`）
    assert 'f"USING (tenant_id = {_RLS_EXPR}) "' in migration_src
    # 片段 5：WITH CHECK 子句（结尾 `;` → 是策略最后一段）
    assert 'f"WITH CHECK (tenant_id = {_RLS_EXPR});"' in migration_src


def test_rls_expr_uses_nullif_pattern(migration_src: str) -> None:
    """_RLS_EXPR 必须用 NULLIF + current_setting('app.tenant_id', true) 模式 —
    与 v391/v395/全 26 表 RLS 一致；裸 current_setting 在 NULL 时会抛错。"""
    assert (
        '_RLS_EXPR = "NULLIF(current_setting(\'app.tenant_id\', true), \'\')::UUID"'
        in migration_src
    )


# ──────────────── 7. downgrade ────────────────


def test_downgrade_drops_table(migration_src: str) -> None:
    """downgrade DROP TABLE — PG CASCADE 自动级联清理 policies + indexes。"""
    assert "DROP TABLE IF EXISTS {_TABLE};" in migration_src
