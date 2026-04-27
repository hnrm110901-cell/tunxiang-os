"""Tier 1 测试: v274 erp_push_log + RLS (W2.G)

Tier 级别:
  🔴 Tier 1 — 数据合规 / 租户隔离 (§19 安全 P1-2 响应)

背景: erp_push_log 表之前无 RLS POLICY, 任何租户可查全表.
修复: 补幂等 CREATE TABLE IF NOT EXISTS + RLS USING + WITH CHECK.

测试边界: 迁移文件结构断言 (USING + WITH CHECK 双声明, IF EXISTS 幂等, 3 索引).
DB 层行为由 DEV Postgres 端到端脚本覆盖.

运行:
  pytest src/tests/test_erp_push_log_rls_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestV274ErpPushLogRLSMigration:
    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v274_erp_push_log_rls.py"
        )
        assert path.exists(), f"v274 迁移不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_id_is_v274(self):
        assert re.search(r'^revision\s*=\s*"v274"', self.migration_src, re.M)

    def test_down_revision_chains_from_v272(self):
        """Wave 2 从 v272 (W1.5 red_flush) 开始."""
        assert re.search(r'^down_revision\s*=\s*"v272"', self.migration_src, re.M)

    def test_create_table_is_idempotent(self):
        """CREATE TABLE IF NOT EXISTS — 幂等, 生产表已存在不破坏."""
        assert re.search(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+erp_push_log",
            self.migration_src, re.I,
        )

    def test_tenant_id_not_null(self):
        """tenant_id UUID NOT NULL (RLS 必需)."""
        assert re.search(
            r"tenant_id\s+UUID\s+NOT\s+NULL",
            self.migration_src, re.I,
        )

    def test_enable_rls(self):
        """ALTER TABLE ENABLE ROW LEVEL SECURITY (幂等)."""
        assert re.search(
            r"ALTER\s+TABLE\s+erp_push_log\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
            self.migration_src, re.I,
        )

    def test_policy_has_using_and_with_check(self):
        """[§19 Blockers B2 一致] POLICY 必须 USING + WITH CHECK 双声明."""
        assert "CREATE POLICY erp_push_log_tenant" in self.migration_src
        assert re.search(
            r"CREATE POLICY.*erp_push_log_tenant.*"
            r"USING\s*\(.*app\.tenant_id.*\).*"
            r"WITH\s+CHECK\s*\(.*app\.tenant_id.*\)",
            self.migration_src, re.S | re.I,
        ), "POLICY 必须显式 USING 和 WITH CHECK 双声明"

    def test_drop_policy_if_exists_before_create(self):
        """DROP POLICY IF EXISTS 在 CREATE 前 (幂等重跑)."""
        assert re.search(
            r"DROP\s+POLICY\s+IF\s+EXISTS\s+erp_push_log_tenant",
            self.migration_src, re.I,
        )

    def test_three_indexes(self):
        """3 索引: tenant_pushed / voucher_id / status_failed partial."""
        assert "ix_erp_push_log_tenant_pushed" in self.migration_src
        assert "ix_erp_push_log_voucher_id" in self.migration_src
        assert "ix_erp_push_log_status_failed" in self.migration_src

    def test_status_failed_partial_index(self):
        """失败重试队列快查: partial index WHERE status='failed'."""
        assert re.search(
            r"CREATE\s+INDEX.*ix_erp_push_log_status_failed.*WHERE\s+status\s*=\s*'failed'",
            self.migration_src, re.S | re.I,
        )

    def test_downgrade_keeps_table(self):
        """downgrade 只关 RLS + 删 POLICY, 不删表 (保历史数据)."""
        m = re.search(r"def downgrade\(\) -> None:(.*?)(?=\Z|^def )",
                      self.migration_src, re.S | re.M)
        assert m is not None
        body = m.group(1)
        # 只 DROP POLICY + DISABLE RLS, 不 DROP TABLE
        assert "DROP POLICY" in body.upper()
        assert "DISABLE ROW LEVEL SECURITY" in body.upper()
        assert not re.search(r"DROP\s+TABLE\s+erp_push_log", body, re.I), (
            "downgrade 不应 DROP TABLE (保历史审计数据)"
        )

    def test_raise_notice_markers(self):
        """3 步 RAISE NOTICE 观测性."""
        notices = re.findall(r"RAISE NOTICE\s+'v274\s+step\s+\d+/\d+", self.migration_src)
        assert len(notices) >= 3

    def test_migration_mentions_oracle_attack(self):
        """迁移 docstring 必须关联到 §19 安全 P1-2 审查发现."""
        assert re.search(
            r"P1-2|跨租户|竞品情报|source_id|Oracle|\u00a719|§19",
            self.migration_src,
        ), "迁移需在 docstring 说明修复的安全风险 (审计可追溯)"
