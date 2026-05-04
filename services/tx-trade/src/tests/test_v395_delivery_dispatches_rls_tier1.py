"""Tier1 — v395 配送调度 RLS WITH CHECK 修补静态校验

§19 PR #139 独立验证发现 v391_delivery_dispatches RLS 策略漏洞：
INSERT/UPDATE/DELETE 三条策略只用 USING、未声明 WITH CHECK，
导致拿到 db session 的代码可向其他租户写入伪造调度记录
（伪骑手位置、伪送达时间戳、污染配送商回调 payload）。

v395 修补必须满足：
  1. revision = "v395"，down_revision = "v391_delivery_dispatches"
  2. 对 delivery_dispatches + delivery_provider_configs 两张表
     的 INSERT / UPDATE / DELETE 三条策略都 DROP 旧策略 + CREATE 新策略
     同时含 USING + WITH CHECK
  3. SELECT 策略可以保留 USING-only（SELECT 无写入侧）
  4. WITH CHECK 表达式与 USING 等价（相同 NULLIF/current_setting 模式）
  5. downgrade 反向还原 v391 仅 USING 形态
  6. 启用 + FORCE RLS 防御幂等

本测试参考 services/tx-trade/src/tests/test_rbac_tier1.py:526-573
（v274 trade_audit_logs 修补的等价静态扫描模式），不需要真连 DB。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/ → src/ → tx-trade/ → services/ → repo_root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "shared" / "db-migrations" / "versions" / "v395_delivery_dispatches_rls_with_check.py"

_AFFECTED_TABLES = ("delivery_dispatches", "delivery_provider_configs")
_WRITE_ACTIONS = ("insert", "update", "delete")


@pytest.fixture(scope="module")
def migration_src() -> str:
    """读取 v395 迁移源代码。"""
    assert _MIGRATION_PATH.is_file(), f"v395 迁移文件不存在：{_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


# ──────────────── 1. revision/down_revision 衔接 ────────────────


def test_revision_id_is_v395(migration_src: str) -> None:
    """revision 字段必须为 'v395'（参考 v274b 模式）。"""
    assert 'revision: str = "v395"' in migration_src, "v395 迁移 revision 字段必须为 'v395'"


def test_down_revision_chains_to_v391(migration_src: str) -> None:
    """down_revision 必须挂在 v391_delivery_dispatches 之后。"""
    assert 'down_revision: Union[str, None] = "v391_delivery_dispatches"' in migration_src


# ──────────────── 2. 受影响表覆盖 ────────────────


def test_both_tables_covered(migration_src: str) -> None:
    """两张表都必须被列入 _TABLES 元组。"""
    for table in _AFFECTED_TABLES:
        assert f'"{table}"' in migration_src, f"v395 应修补 {table}（v391 创建的两张表之一）"


# ──────────────── 3. 每张表的 INSERT/UPDATE/DELETE 写入侧策略 ────────────────


@pytest.mark.parametrize("table", _AFFECTED_TABLES)
def test_drop_old_using_only_policies_per_table(migration_src: str, table: str) -> None:
    """对每张表 — 必须 DROP v391 仅 USING 的旧策略 rls_<table>_<action>。"""
    for action in _WRITE_ACTIONS:
        old_policy = f"rls_{table}_{action}"
        # DROP 语句通过 f-string 拼接，源码中不会有完整字面量；改为查模板
        # 而模板里的完整 DROP 字面量是 op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")
        # 所以静态扫描应找到 'DROP POLICY IF EXISTS {old_policy} ON {table};' 模板
        pass

    # 模板写法：使用 f-string + {old_policy}/{table} 占位符 — 验证模板存在
    assert "DROP POLICY IF EXISTS {old_policy} ON {table}" in migration_src, (
        "v395 必须包含 DROP IF EXISTS 旧 USING-only 策略的模板"
    )


def test_create_new_policy_with_using_and_with_check(migration_src: str) -> None:
    """新策略必须 *同时* 声明 USING + WITH CHECK，且条件相同。"""
    # 模板字面量
    assert "CREATE POLICY {new_policy} ON {table}" in migration_src
    assert "AS PERMISSIVE FOR {action} TO PUBLIC" in migration_src
    assert "USING (tenant_id = {_RLS_EXPR})" in migration_src or (migration_src.count("tenant_id = {_RLS_EXPR}") >= 2)
    # WITH CHECK 必须存在
    assert "WITH CHECK (tenant_id = {_RLS_EXPR})" in migration_src, "v395 必须为新策略声明 WITH CHECK 子句"


def test_using_and_with_check_use_same_rls_expression(migration_src: str) -> None:
    """USING + WITH CHECK 必须使用相同的 RLS 表达式（NULLIF + current_setting）。"""
    # _RLS_EXPR 的字面定义
    assert "_RLS_EXPR = \"NULLIF(current_setting('app.tenant_id', true), '')::UUID\"" in migration_src, (
        "v395 必须复用 v391 同款 RLS 表达式（NULLIF 防 UNSET）"
    )

    # USING + WITH CHECK 在新策略 CREATE 模板内各出现一次（共 2 次）
    create_block_signature = "USING (tenant_id = {_RLS_EXPR}) "
    with_check_signature = "WITH CHECK (tenant_id = {_RLS_EXPR})"
    assert create_block_signature in migration_src, f"找不到 USING 模板：{create_block_signature!r}"
    assert with_check_signature in migration_src, f"找不到 WITH CHECK 模板：{with_check_signature!r}"


def test_write_actions_tuple_contains_insert_update_delete(migration_src: str) -> None:
    """_WRITE_ACTIONS 必须覆盖所有写入侧 action。"""
    # 写入侧 = INSERT + UPDATE + DELETE；SELECT 不需要 WITH CHECK
    assert '_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")' in migration_src, (
        "v395 必须为 INSERT/UPDATE/DELETE 三个写入侧 action 都补 WITH CHECK"
    )


# ──────────────── 4. RLS 启用 + FORCE 幂等 ────────────────


@pytest.mark.parametrize("table", _AFFECTED_TABLES)
def test_rls_enabled_and_forced_per_table(migration_src: str, table: str) -> None:
    """upgrade 必须显式重申 ENABLE + FORCE ROW LEVEL SECURITY（防御幂等）。"""
    # 使用 f-string 模板形式
    assert "ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in migration_src
    assert "ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in migration_src


# ──────────────── 5. downgrade 反向操作完整 ────────────────


def test_downgrade_drops_new_policy(migration_src: str) -> None:
    """downgrade 必须 DROP 新带 WITH CHECK 的策略。"""
    assert "def downgrade()" in migration_src
    # downgrade 部分必须含 DROP {new_policy}
    downgrade_section = migration_src.split("def downgrade()", 1)[1]
    assert "DROP POLICY IF EXISTS {new_policy} ON {table}" in downgrade_section, (
        "downgrade 必须 DROP 新带 WITH CHECK 的策略"
    )


def test_downgrade_recreates_v391_using_only_policy(migration_src: str) -> None:
    """downgrade 必须重建 v391 仅 USING 的旧策略形态（等价回滚）。"""
    downgrade_section = migration_src.split("def downgrade()", 1)[1]
    assert "CREATE POLICY {old_policy} ON {table}" in downgrade_section
    assert "USING (tenant_id = {_RLS_EXPR})" in downgrade_section
    # downgrade 里 *不* 应该有 WITH CHECK（确保是回退到 v391 形态）
    # 切片 downgrade 内的 CREATE POLICY 块，验证不含 WITH CHECK
    create_idx = downgrade_section.find("CREATE POLICY {old_policy}")
    assert create_idx != -1
    create_block = downgrade_section[create_idx : create_idx + 300]
    assert "WITH CHECK" not in create_block, (
        "downgrade 重建的 v391 仅 USING 策略不应含 WITH CHECK（保证 down 等价回滚）"
    )


# ──────────────── 6. SECURITY 注释存在（审计可读性） ────────────────


def test_docstring_documents_security_severity(migration_src: str) -> None:
    """docstring 必须明确说明 SECURITY/Tier1 + 漏洞影响（取证 + 跨租户污染）。"""
    assert "[SECURITY][Tier1]" in migration_src
    assert "WITH CHECK" in migration_src
    assert "跨租户" in migration_src or "cross-tenant" in migration_src.lower()
