"""Tier 1 测试: financial_voucher_lines 会计分录子表 (v266)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期链路

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. 销售凭证 2 分录 (借: 应收账款 / 贷: 主营业务收入) — fen 存储 + 借贷平衡
  场景 2. 借贷互斥 (同行借贷都非零 → DB CHECK 拒)
  场景 3. 借贷都为零 → DB CHECK 拒 (零分录没有会计意义)
  场景 4. 负数分录 → DB CHECK 拒
  场景 5. 凭证内 line_no 唯一 (避免分录乱序/重复)
  场景 6. 级联删除 (voucher 删则 lines 自动清)
  场景 7. 跨租户 JOIN 攻击 (RLS policy 拒绝用户 X 读 Y 的 lines)
  迁移结构 8. v266 文件有 CHECK 约束 / RLS / 3 索引 / revision 链

注: DB CHECK / RLS / FK CASCADE 用结构化断言 (解析迁移文件源码),
    而不是起真实 PG. 理由与 v264 test 保持一致:
    - tx-finance 现有测试基础设施不含 Docker PG fixture
    - 结构化断言 + DEV Postgres 手动 SQL 验证 (在 progress.md 留痕) 是等效覆盖

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_financial_voucher_lines_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher, FinancialVoucherLine  # type: ignore  # noqa: E402


# ─── 真实场景 #1: 销售凭证 2 分录 (借: 应收 / 贷: 主营业务收入) ──────────


class TestSalesVoucherLinesScenario:
    """场景: 徐记海鲜堂食 ¥1,000 生成销售凭证, 2 条分录 + 借贷平衡."""

    def _build_voucher_with_lines(self) -> FinancialVoucher:
        tenant_id = uuid.uuid4()
        store_id = uuid.uuid4()
        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            voucher_no="V_XJ_20260419_001",
            voucher_type="sales",
            total_amount_fen=100000,  # ¥1,000
            entries=[],  # W1.3 前 entries 双写; 本测试只验 lines 路径
        )
        voucher.lines = [
            FinancialVoucherLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                voucher_id=voucher.id,
                line_no=1,
                account_code="1122",
                account_name="应收账款",
                debit_fen=100000,
                credit_fen=0,
                summary="2026-04-19 堂食应收",
            ),
            FinancialVoucherLine(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                voucher_id=voucher.id,
                line_no=2,
                account_code="6001",
                account_name="主营业务收入-餐饮",
                debit_fen=0,
                credit_fen=100000,
                summary="2026-04-19 堂食收入",
            ),
        ]
        return voucher

    def test_lines_store_amount_in_fen(self):
        """¥1,000 应以 100000 分存储, 不做元/分转换."""
        voucher = self._build_voucher_with_lines()
        assert voucher.lines[0].debit_fen == 100000
        assert voucher.lines[0].credit_fen == 0
        assert voucher.lines[1].debit_fen == 0
        assert voucher.lines[1].credit_fen == 100000

    def test_voucher_is_balanced_from_lines(self):
        """借贷平衡: 借方总 == 贷方总 (fen 整数, 零容忍)."""
        voucher = self._build_voucher_with_lines()
        assert voucher.total_debit_fen_from_lines() == 100000
        assert voucher.total_credit_fen_from_lines() == 100000
        assert voucher.is_balanced_from_lines() is True

    def test_3_way_split_still_balances(self):
        """三分录场景: 借 100 + 借 50 = 贷 150 (支付凭证典型分录)."""
        tenant_id = uuid.uuid4()
        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            voucher_no="V_TEST_3WAY",
            voucher_type="payment",
            total_amount_fen=15000,
            entries=[],
        )
        voucher.lines = [
            FinancialVoucherLine(tenant_id=tenant_id, voucher_id=voucher.id,
                                 line_no=1, account_code="5401", account_name="主营成本",
                                 debit_fen=10000, credit_fen=0),
            FinancialVoucherLine(tenant_id=tenant_id, voucher_id=voucher.id,
                                 line_no=2, account_code="5602", account_name="管理费用",
                                 debit_fen=5000, credit_fen=0),
            FinancialVoucherLine(tenant_id=tenant_id, voucher_id=voucher.id,
                                 line_no=3, account_code="1002", account_name="银行存款",
                                 debit_fen=0, credit_fen=15000),
        ]
        assert voucher.is_balanced_from_lines() is True

    def test_unbalanced_lines_detected(self):
        """借 100 贷 99 → 不平衡, fen 整数精确比较, 零容忍."""
        tenant_id = uuid.uuid4()
        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            voucher_no="V_TEST_UNBAL",
            voucher_type="sales",
            total_amount_fen=10000,
            entries=[],
        )
        voucher.lines = [
            FinancialVoucherLine(tenant_id=tenant_id, voucher_id=voucher.id,
                                 line_no=1, account_code="1122", account_name="应收账款",
                                 debit_fen=10000, credit_fen=0),
            FinancialVoucherLine(tenant_id=tenant_id, voucher_id=voucher.id,
                                 line_no=2, account_code="6001", account_name="主营业务收入",
                                 debit_fen=0, credit_fen=9900),  # 少 1 分!
        ]
        assert voucher.is_balanced_from_lines() is False


# ─── 真实场景 #2-5: DB CHECK / UNIQUE / FK CASCADE 结构验证 ───────────


class TestVoucherLinesConstraints:
    """分录约束: 从迁移文件源码验证 DB 层 CHECK / UNIQUE / FK."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v266_financial_voucher_lines.py"
        )
        assert path.exists(), f"v266 迁移文件不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_check_debit_credit_exclusive_exists(self):
        """DB CHECK 强制借贷互斥 (同行借贷都非零 → DB 拒)."""
        assert "chk_fvl_debit_credit_exclusive" in self.migration_src
        # 表达式必须同时包含两个互斥分支
        assert re.search(
            r"debit_fen\s*=\s*0\s*AND\s*credit_fen\s*>\s*0",
            self.migration_src,
        ), "互斥 CHECK 缺少 '借=0 AND 贷>0' 分支"
        assert re.search(
            r"debit_fen\s*>\s*0\s*AND\s*credit_fen\s*=\s*0",
            self.migration_src,
        ), "互斥 CHECK 缺少 '借>0 AND 贷=0' 分支"

    def test_check_non_negative_exists(self):
        """DB CHECK 强制非负 (防御性冗余, 互斥约束已蕴含但显式)."""
        assert "chk_fvl_non_negative" in self.migration_src
        assert re.search(
            r"debit_fen\s*>=\s*0\s*AND\s*credit_fen\s*>=\s*0",
            self.migration_src,
        )

    def test_check_rejects_both_zero_via_exclusive(self):
        """借贷都为 0 被互斥约束拒 (两个分支都要求某侧 > 0)."""
        # 从 CHECK 表达式反推: 两分支都含 "> 0"; 若 debit=credit=0 两个分支都假
        exclusive_clauses = re.findall(
            r"\(debit_fen\s*[=><]+\s*0\s*AND\s*credit_fen\s*[=><]+\s*0\)",
            self.migration_src,
        )
        assert len(exclusive_clauses) >= 2, (
            "互斥 CHECK 需要至少两个分支 '借=0 AND 贷>0' 和 '借>0 AND 贷=0', "
            "两个分支都含 '> 0' 才能拒 0/0"
        )
        for clause in exclusive_clauses[:2]:
            assert ">" in clause, f"分支 {clause} 缺少 > 0 条件, 不能拒 0/0"

    def test_unique_voucher_line_no(self):
        """UNIQUE (voucher_id, line_no) — 凭证内行号不可重复."""
        assert "uq_fvl_voucher_line_no" in self.migration_src
        # UniqueConstraint 调用里要同时见到两个列
        uq_block = re.search(
            r"UniqueConstraint\(\s*(.*?)\s*name=.uq_fvl_voucher_line_no.",
            self.migration_src, re.S,
        )
        assert uq_block is not None, "UniqueConstraint(voucher_id, line_no) 缺失"
        cols = uq_block.group(1)
        assert '"voucher_id"' in cols and '"line_no"' in cols

    def test_fk_voucher_id_cascade(self):
        """FK voucher_id ON DELETE CASCADE — voucher 删则 lines 自动清."""
        assert re.search(
            r'ForeignKeyConstraint\(\s*\[.voucher_id.\]\s*,\s*'
            r'\[.financial_vouchers\.id.\]\s*,\s*'
            r'ondelete\s*=\s*.CASCADE.',
            self.migration_src,
        ), "FK voucher_id ON DELETE CASCADE 缺失"


# ─── 真实场景 #6: RLS 跨租户隔离 ─────────────────────────────────────


class TestVoucherLinesRLS:
    """RLS 合资公司场景: 品牌 A 的财务不能读品牌 B 的凭证分录."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v266_financial_voucher_lines.py"
        )
        self.migration_src = path.read_text(encoding="utf-8")

    def test_rls_enabled_on_voucher_lines(self):
        """ALTER TABLE financial_voucher_lines ENABLE ROW LEVEL SECURITY."""
        assert re.search(
            r"ALTER TABLE\s+financial_voucher_lines\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
            self.migration_src,
            re.I,
        )

    def test_rls_policy_uses_app_tenant_id(self):
        """RLS 策略必须走 NULLIF(current_setting('app.tenant_id', true), '')::uuid."""
        assert "CREATE POLICY financial_voucher_lines_tenant" in self.migration_src
        assert "current_setting('app.tenant_id', true)" in self.migration_src
        assert "NULLIF(" in self.migration_src

    def test_tenant_id_is_not_nullable(self):
        """tenant_id 必须 NOT NULL — 防 RLS 绕过 (NULL = NULL 永假但 IS NULL 为真)."""
        # 找 tenant_id 列定义
        tenant_col = re.search(
            r'Column\(\s*"tenant_id"\s*,\s*UUID\(as_uuid=True\)\s*,\s*(.+?)\)',
            self.migration_src, re.S,
        )
        assert tenant_col is not None, "tenant_id 列定义未找到"
        col_def = tenant_col.group(1)
        assert "nullable=False" in col_def, (
            "tenant_id 必须 nullable=False, "
            "否则 NULL 行可被恶意租户通过 unset app.tenant_id 读到"
        )


# ─── 迁移结构: revision 链 + 3 索引 ──────────────────────────────────


class TestV266MigrationFileStructure:
    """v266 迁移文件的骨架健康检查."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v266_financial_voucher_lines.py"
        )
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_id_is_v266(self):
        assert re.search(r'^revision\s*=\s*"v266"', self.migration_src, re.M)

    def test_down_revision_chains_from_v264(self):
        """v266 从 v264 (我的 wave1 前置) 延续, 跳过 v265 (并行 event_outbox).

        链式分叉由另一 P0 PR (fix/alembic-chain-dedup) 治理,
        本 PR 只保证单链连续.
        """
        assert re.search(r'^down_revision\s*=\s*"v264"', self.migration_src, re.M)

    def test_three_indexes_created(self):
        """3 索引: (voucher_id), (tenant_id, account_code), (tenant_id, created_at)."""
        assert "ix_fvl_voucher_id" in self.migration_src
        assert "ix_fvl_tenant_account" in self.migration_src
        assert "ix_fvl_tenant_created" in self.migration_src
        # 业务要求: 科目总账索引必须是 (tenant_id, account_code) 复合
        assert re.search(
            r'ix_fvl_tenant_account.*?\[\s*"tenant_id"\s*,\s*"account_code"\s*\]',
            self.migration_src, re.S,
        ), "ix_fvl_tenant_account 必须是 (tenant_id, account_code) 复合索引"

    def test_upgrade_has_raise_notice_markers(self):
        """RAISE NOTICE 可观测性: 生产 psql 能看到分步进度."""
        notices = re.findall(r"RAISE NOTICE\s+'v266\s+step\s+\d+/\d+", self.migration_src)
        assert len(notices) >= 3, f"v266 upgrade 至少 3 个进度标记, 实际 {len(notices)}"

    def test_downgrade_is_not_empty(self):
        """downgrade 必须实际 DROP TABLE, 不能是 pass."""
        m = re.search(r"def downgrade\(\) -> None:(.*?)(?=\Z|^def )",
                      self.migration_src, re.S | re.M)
        assert m is not None
        body = m.group(1)
        assert "drop_table" in body.lower() or "DROP TABLE" in body

    def test_downgrade_warns_about_w16_backfill_loss(self):
        """downgrade 必须在 docstring / 注释里告警 W1.6 回填后不可降级."""
        # 搜索 downgrade 函数前后的注释 + docstring
        assert re.search(
            r"(W1\.6|历史回填|数据.{0,5}丢|24h|紧急回滚)",
            self.migration_src,
        ), "v266 downgrade 风险必须在文件里文档化 (提到 W1.6 / 历史回填 / 24h 边界)"

    def test_create_index_not_concurrently_for_new_empty_table(self):
        """新空表索引不应用 CONCURRENTLY (无意义 + 禁用事务的成本).

        原则: CONCURRENTLY 是给"已有 TB 级数据、不能停写"的老表用的.
        v266 新建空表, op.create_index 同步立即完成, 更简单安全.
        """
        # 只检函数体 (upgrade + downgrade), 不检 docstring 里解释为什么不用 CONCURRENTLY.
        func_bodies = re.findall(
            r"^def (?:upgrade|downgrade)\(\) -> None:(.*?)(?=\Z|^def )",
            self.migration_src, re.S | re.M,
        )
        assert len(func_bodies) == 2, "upgrade + downgrade 函数应都存在"
        combined = "\n".join(func_bodies)
        assert not re.search(
            r"CREATE\s+INDEX\s+CONCURRENTLY", combined, re.I
        ), "v266 是新空表, DDL 不应含 CREATE INDEX CONCURRENTLY"
        assert "autocommit_block" not in combined, (
            "v266 新空表不需要 autocommit_block() — 这是给老表 CONCURRENTLY 用的"
        )
