"""v265 迁移结构测试 (T5.1.4).

测试范围 (不连真实数据库):
- 迁移模块 import 无错
- revision / down_revision 正确
- upgrade / downgrade 函数存在且可调用
- upgrade 使用了 CREATE TABLE 且包含两张目标表
- downgrade 使用了 DROP TABLE 且反序删除

不测 SQL 语义正确性 — 留给集成测试 T5.1.9 对接 testcontainers-postgres.
"""
from __future__ import annotations

import importlib.util
import os


def _load_v265():
    """动态导入 v265 模块."""
    versions_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "versions")
    )
    fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
    spec = importlib.util.spec_from_file_location("_migration_v265", fpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV265RevisionChain:
    def test_revision_is_v265(self) -> None:
        m = _load_v265()
        assert m.revision == "v265"

    def test_down_revision_is_v263(self) -> None:
        """v265 down_revision 指向 v263 (避开 v261/v262 重复问题)."""
        m = _load_v265()
        assert m.down_revision == "v263"

    def test_no_branch_labels(self) -> None:
        m = _load_v265()
        assert m.branch_labels is None
        assert m.depends_on is None


class TestV265Structure:
    def test_has_upgrade_function(self) -> None:
        m = _load_v265()
        assert callable(m.upgrade)

    def test_has_downgrade_function(self) -> None:
        m = _load_v265()
        assert callable(m.downgrade)

    def test_upgrade_docstring_mentions_both_tables(self) -> None:
        """文档字符串应说明两张新表."""
        m = _load_v265()
        doc = m.__doc__ or ""
        assert "event_outbox_cursor" in doc
        assert "processed_events" in doc


class TestV265Idempotency:
    """验证 upgrade 使用了 inspector 防重建 (IF NOT EXISTS 模式)."""

    def test_upgrade_source_uses_inspector(self) -> None:
        versions_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "versions")
        )
        fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        assert "inspector.get_table_names()" in source, (
            "upgrade() 应使用 inspector 防重建 (与其他迁移一致)"
        )
        assert 'if "event_outbox_cursor" not in existing' in source
        assert 'if "processed_events" not in existing' in source


class TestV265RlsPolicy:
    """processed_events 必须启用 RLS; event_outbox_cursor 是基础设施表可不启用."""

    def test_processed_events_has_rls_policy(self) -> None:
        versions_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "versions")
        )
        fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        assert "ALTER TABLE processed_events ENABLE ROW LEVEL SECURITY" in source
        assert "CREATE POLICY processed_events_tenant ON processed_events" in source
        assert 'app.tenant_id' in source

    def test_event_outbox_cursor_no_rls_by_design(self) -> None:
        """event_outbox_cursor 是 Relay 基础设施表, 故意不启用 RLS."""
        versions_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "versions")
        )
        fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        # 应有注释/说明, 不能只是遗漏
        assert (
            "基础设施" in source or "infrastructure" in source.lower()
        ), "event_outbox_cursor 无 RLS 需在注释中说明"


class TestV265Downgrade:
    """downgrade 必须反序清理, 且非空 (符合 MIGRATION_RULES.md)."""

    def test_downgrade_drops_both_tables(self) -> None:
        versions_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "versions")
        )
        fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        assert "DROP TABLE IF EXISTS processed_events" in source
        assert "DROP TABLE IF EXISTS event_outbox_cursor" in source

    def test_downgrade_drops_policy_before_table(self) -> None:
        """反序: 先 DROP POLICY, 再 DROP TABLE."""
        versions_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "versions")
        )
        fpath = os.path.join(versions_dir, "v265_ontology_outbox_cursor.py")
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        policy_idx = source.find("DROP POLICY IF EXISTS processed_events_tenant")
        table_idx = source.find("DROP TABLE IF EXISTS processed_events")
        assert policy_idx < table_idx, "应先 DROP POLICY 再 DROP TABLE"
