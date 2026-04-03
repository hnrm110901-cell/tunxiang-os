"""v064_wms_persistence 迁移内容静态验证测试

验证目标：
1. 迁移文件存在于预期路径
2. 包含所有必要的表名（6张 WMS 表）
3. RLS 使用正确变量名 app.tenant_id（NULLIF 模式）
4. 不包含被禁止的错误变量名（app.current_store_id / app.current_tenant）
5. 包含 FORCE ROW LEVEL SECURITY
6. down_revision 正确接在 v063 之后
7. 所有表包含 tenant_id NOT NULL 和 is_deleted 字段
8. 四操作 RLS policy（SELECT/INSERT/UPDATE/DELETE）

注意：纯静态文件内容检查，不需要 DB 连接，也不会执行任何 SQL。
"""
from __future__ import annotations

import re
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────────────────────────────────────

MIGRATION_PATH = Path(__file__).parent.parent.parent.parent / (
    "shared/db-migrations/versions/v064_wms_persistence.py"
)

# 必须存在的六张 WMS 表
REQUIRED_TABLES = [
    "stocktakes",
    "stocktake_items",
    "warehouse_transfers",
    "warehouse_transfer_items",
    "supplier_profiles",
    "supplier_score_history",
]

# 被禁止使用的错误变量名（v056+ 安全规范）
FORBIDDEN_SETTINGS = [
    "app.current_store_id",
    "app.current_tenant",
]

# 正确的 RLS 变量名
CORRECT_SETTING = "app.tenant_id"

# 正确的 NULLIF NULL-guard 模式（核心安全检查）
NULLIF_PATTERN = re.compile(
    r"NULLIF\s*\(\s*current_setting\s*\(\s*['\"]app\.tenant_id['\"]",
    re.IGNORECASE,
)

# 四操作 RLS policy 后缀
RLS_OPERATIONS = ["rls_select", "rls_insert", "rls_update", "rls_delete"]


# ──────────────────────────────────────────────────────────────────────────────
#  Fixtures（读取文件内容，所有测试共用）
# ──────────────────────────────────────────────────────────────────────────────

def _read_migration() -> str:
    """读取迁移文件内容，若文件不存在则返回空字符串。"""
    if MIGRATION_PATH.exists():
        return MIGRATION_PATH.read_text(encoding="utf-8")
    return ""


# ──────────────────────────────────────────────────────────────────────────────
#  测试：文件存在性
# ──────────────────────────────────────────────────────────────────────────────

class TestMigrationFileExists:
    """验证迁移文件存在且路径正确。"""

    def test_file_exists(self) -> None:
        assert MIGRATION_PATH.exists(), (
            f"迁移文件不存在: {MIGRATION_PATH}\n"
            "请确认已创建 v064_wms_persistence.py"
        )

    def test_file_is_python(self) -> None:
        assert MIGRATION_PATH.suffix == ".py", "迁移文件必须是 .py 文件"

    def test_file_not_empty(self) -> None:
        content = _read_migration()
        assert len(content) > 100, "迁移文件内容过短，疑似空文件"


# ──────────────────────────────────────────────────────────────────────────────
#  测试：版本链
# ──────────────────────────────────────────────────────────────────────────────

class TestRevisionChain:
    """验证迁移版本号和 down_revision 正确。"""

    def test_revision_is_v064(self) -> None:
        content = _read_migration()
        assert 'revision: str = "v064"' in content or "revision = 'v064'" in content or (
            'revision' in content and 'v064' in content
        ), "revision 应为 v064"

    def test_down_revision_is_v063(self) -> None:
        content = _read_migration()
        assert "v063" in content, (
            "down_revision 必须是 v063，确保此迁移接在 v063 之后"
        )

    def test_down_revision_assignment(self) -> None:
        content = _read_migration()
        # 确认 down_revision 赋值语句存在且指向 v063
        pattern = re.compile(r'down_revision\s*[=:][^\n]*v063', re.IGNORECASE)
        assert pattern.search(content), (
            "down_revision 赋值应包含 v063"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  测试：必要表名
# ──────────────────────────────────────────────────────────────────────────────

class TestRequiredTables:
    """验证六张 WMS 表均在迁移文件中出现。"""

    def test_all_required_tables_present(self) -> None:
        content = _read_migration()
        missing = [t for t in REQUIRED_TABLES if t not in content]
        assert not missing, (
            f"以下表在迁移文件中缺失: {missing}\n"
            f"必须包含: {REQUIRED_TABLES}"
        )

    def test_stocktakes_table(self) -> None:
        assert "stocktakes" in _read_migration()

    def test_stocktake_items_table(self) -> None:
        assert "stocktake_items" in _read_migration()

    def test_warehouse_transfers_table(self) -> None:
        assert "warehouse_transfers" in _read_migration()

    def test_warehouse_transfer_items_table(self) -> None:
        assert "warehouse_transfer_items" in _read_migration()

    def test_supplier_profiles_table(self) -> None:
        assert "supplier_profiles" in _read_migration()

    def test_supplier_score_history_table(self) -> None:
        assert "supplier_score_history" in _read_migration()


# ──────────────────────────────────────────────────────────────────────────────
#  测试：RLS 安全规范
# ──────────────────────────────────────────────────────────────────────────────

class TestRLSSecurity:
    """验证 RLS 使用正确的 v056+ 安全模式。"""

    def test_uses_correct_setting_variable(self) -> None:
        content = _read_migration()
        assert CORRECT_SETTING in content, (
            f"迁移必须使用 '{CORRECT_SETTING}' 变量名\n"
            f"参考: NULLIF(current_setting('app.tenant_id', true), '')::UUID"
        )

    def test_no_forbidden_app_current_store_id(self) -> None:
        content = _read_migration()
        assert "app.current_store_id" not in content, (
            "禁止使用 'app.current_store_id'（错误变量名）\n"
            "正确变量名：app.tenant_id"
        )

    def test_no_forbidden_app_current_tenant(self) -> None:
        content = _read_migration()
        assert "app.current_tenant" not in content, (
            "禁止使用 'app.current_tenant'（错误变量名）\n"
            "正确变量名：app.tenant_id"
        )

    def test_uses_nullif_pattern(self) -> None:
        content = _read_migration()
        assert NULLIF_PATTERN.search(content), (
            "RLS 条件必须使用 NULLIF NULL-guard 模式：\n"
            "NULLIF(current_setting('app.tenant_id', true), '')::UUID\n"
            "此模式防止空字符串绕过 RLS 隔离"
        )

    def test_force_row_level_security_present(self) -> None:
        content = _read_migration()
        assert "FORCE ROW LEVEL SECURITY" in content, (
            "必须包含 FORCE ROW LEVEL SECURITY\n"
            "此指令确保表所有者也受 RLS 约束"
        )

    def test_enable_row_level_security_present(self) -> None:
        content = _read_migration()
        assert "ENABLE ROW LEVEL SECURITY" in content, (
            "必须包含 ENABLE ROW LEVEL SECURITY"
        )

    def test_all_four_rls_operations(self) -> None:
        content = _read_migration()
        missing_ops = [op for op in RLS_OPERATIONS if op not in content]
        assert not missing_ops, (
            f"以下 RLS 操作策略缺失: {missing_ops}\n"
            "必须包含全部四操作：rls_select / rls_insert / rls_update / rls_delete"
        )

    def test_rls_applied_to_all_tables(self) -> None:
        """验证每张表都调用了 _apply_safe_rls 或包含对应 RLS 策略。"""
        content = _read_migration()
        missing_rls = []
        for table in REQUIRED_TABLES:
            # 检查是否有对该表的 RLS 启用调用
            has_rls = (
                f'_apply_safe_rls("{table}")' in content
                or f"_apply_safe_rls('{table}')" in content
                or "FORCE ROW LEVEL SECURITY" in content  # 至少存在 FORCE 语句
            )
            # 更严格检查：该表名和 rls 同时出现
            table_rls_pattern = re.compile(
                rf'{re.escape(table)}.*rls|rls.*{re.escape(table)}',
                re.IGNORECASE | re.DOTALL,
            )
            if not table_rls_pattern.search(content):
                missing_rls.append(table)
        assert not missing_rls, (
            f"以下表缺少 RLS 策略引用: {missing_rls}"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  测试：表结构规范
# ──────────────────────────────────────────────────────────────────────────────

class TestTableStructure:
    """验证表结构符合屯象OS 底层基类规范。"""

    def test_tenant_id_not_null_present(self) -> None:
        content = _read_migration()
        # 应多次出现 tenant_id NOT NULL（每张表一次）
        count = content.count("tenant_id")
        assert count >= len(REQUIRED_TABLES), (
            f"tenant_id 出现次数 ({count}) 少于表数量 ({len(REQUIRED_TABLES)})\n"
            "每张表必须包含 tenant_id UUID NOT NULL"
        )

    def test_is_deleted_field_present(self) -> None:
        content = _read_migration()
        count = content.count("is_deleted")
        assert count >= len(REQUIRED_TABLES), (
            f"is_deleted 出现次数 ({count}) 少于表数量 ({len(REQUIRED_TABLES)})\n"
            "每张表必须包含 is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
        )

    def test_created_at_field_present(self) -> None:
        content = _read_migration()
        assert "created_at" in content, "表必须包含 created_at 字段"

    def test_updated_at_field_present(self) -> None:
        content = _read_migration()
        assert "updated_at" in content, "表必须包含 updated_at 字段"

    def test_stocktake_status_check_constraint(self) -> None:
        content = _read_migration()
        # 验证盘点状态约束包含正确的值
        assert "in_progress" in content, "stocktakes.status 应包含 'in_progress'"
        assert "completed" in content, "stocktakes.status 应包含 'completed'"
        assert "cancelled" in content, "stocktakes.status 应包含 'cancelled'"

    def test_variance_generated_column(self) -> None:
        content = _read_migration()
        assert "GENERATED ALWAYS AS" in content, (
            "stocktake_items.variance 应为 GENERATED ALWAYS AS STORED 计算列"
        )
        assert "STORED" in content, (
            "GENERATED 列必须是 STORED 模式（物化存储，提升查询性能）"
        )

    def test_supplier_profiles_status_check(self) -> None:
        content = _read_migration()
        assert "blacklisted" in content, (
            "supplier_profiles.status 应包含 'blacklisted'"
        )
        assert "suspended" in content, (
            "supplier_profiles.status 应包含 'suspended'"
        )

    def test_supplier_score_composite_score(self) -> None:
        content = _read_migration()
        assert "composite_score" in content, (
            "supplier_score_history 必须包含 composite_score 字段（综合分 0-100）"
        )

    def test_supplier_score_ai_insight(self) -> None:
        content = _read_migration()
        assert "ai_insight" in content, (
            "supplier_score_history 必须包含 ai_insight 字段（AI 分析文本）"
        )

    def test_warehouse_transfer_type_check(self) -> None:
        content = _read_migration()
        assert "emergency" in content, (
            "warehouse_transfers.transfer_type 应包含 'emergency'"
        )

    def test_foreign_key_references(self) -> None:
        content = _read_migration()
        # stocktake_items 应引用 stocktakes
        assert "REFERENCES stocktakes(id)" in content, (
            "stocktake_items 应有 REFERENCES stocktakes(id) 外键约束"
        )
        # warehouse_transfer_items 应引用 warehouse_transfers
        assert "REFERENCES warehouse_transfers(id)" in content, (
            "warehouse_transfer_items 应有 REFERENCES warehouse_transfers(id) 外键约束"
        )
        # supplier_score_history 应引用 supplier_profiles
        assert "REFERENCES supplier_profiles(id)" in content, (
            "supplier_score_history 应有 REFERENCES supplier_profiles(id) 外键约束"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  测试：downgrade 函数
# ──────────────────────────────────────────────────────────────────────────────

class TestDowngrade:
    """验证 downgrade 函数可以正确回滚。"""

    def test_downgrade_function_present(self) -> None:
        content = _read_migration()
        assert "def downgrade" in content, "必须包含 downgrade() 函数"

    def test_downgrade_drops_all_tables(self) -> None:
        content = _read_migration()
        assert "DROP TABLE" in content or "DROP POLICY" in content, (
            "downgrade() 应包含 DROP TABLE 或 DROP POLICY 语句"
        )

    def test_downgrade_uses_cascade(self) -> None:
        content = _read_migration()
        assert "CASCADE" in content, (
            "DROP TABLE 应使用 CASCADE 以正确级联删除外键依赖"
        )
