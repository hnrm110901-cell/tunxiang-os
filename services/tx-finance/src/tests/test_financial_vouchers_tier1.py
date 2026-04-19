"""Tier 1 测试: financial_vouchers Schema ↔ ORM 对齐 + 金额 fen 统一 (v264)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期链路

测试边界(CLAUDE.md §20 "基于真实餐厅场景"):
  - 门店日结 ¥3,456.78 凭证: fen 存储应为 345678
  - 销售凭证借贷平衡 (¥1,000 = ¥1,000)
  - 历史行 period_start 回填到 voucher_date
  - ORM nullable 与 v264 物理 schema 对齐(新列允许 NULL)
  - v264 迁移文件结构正确(revision=v264, down_revision=v263)

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_financial_vouchers_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# sys.path: 加入 services/tx-finance/src/ 以匹配同目录其他测试的 import 风格
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher  # type: ignore  # noqa: E402


# ─── 真实场景 #1: 门店日结销售凭证 ──────────────────────────────────


class TestDailySettlementVoucherScenario:
    """场景: S001 门店当日堂食营收 ¥3,456.78, 生成销售凭证."""

    def test_voucher_stores_amount_in_fen(self):
        """¥3,456.78 应以 345678 分存储于 total_amount_fen."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_S001_20260419_001",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount_fen=345678,  # ¥3,456.78 的 fen 值
            entries=[
                {"account_code": "1001", "account_name": "库存现金",
                 "debit": 3456.78, "credit": 0.00,
                 "summary": "2026-04-19堂食现金收入"},
                {"account_code": "6001", "account_name": "主营业务收入-餐饮",
                 "debit": 0.00, "credit": 3456.78,
                 "summary": "2026-04-19堂食营收"},
            ],
            status="draft",
        )
        assert v.total_amount_fen == 345678
        assert v.is_balanced() is True  # 借贷 3456.78 = 3456.78

    def test_legacy_total_amount_field_optional_after_v264(self):
        """v264 后 total_amount (NUMERIC 元) 可为 NULL, 只写 fen 也合法."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_S001_20260419_002",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount=None,          # DEPRECATED, 允许 NULL
            total_amount_fen=1000000,   # ¥10,000 的 fen
            entries=[],
            status="draft",
        )
        assert v.total_amount is None
        assert v.total_amount_fen == 1000000

    def test_to_dict_exposes_both_amount_fields(self):
        """to_dict() 必须同时暴露 total_amount (兼容) 和 total_amount_fen (SSOT)."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_S001_20260419_003",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount=None,
            total_amount_fen=500000,
            entries=[],
            status="draft",
            created_at=datetime.now(timezone.utc),
        )
        d = v.to_dict()
        assert "total_amount" in d
        assert "total_amount_fen" in d
        assert d["total_amount_fen"] == 500000
        assert d["total_amount"] is None


# ─── 真实场景 #2: 借贷不平衡的异常凭证 ──────────────────────────────


class TestUnbalancedVoucherScenario:
    """场景: 系统生成凭证时借方 100 元 但贷方 99 元, 不平衡校验必须拦住."""

    def test_unbalanced_voucher_detected(self):
        """借 100 元 / 贷 99 元: is_balanced() 必须返回 False."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_BAD_001",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount_fen=10000,
            entries=[
                {"account_code": "1001", "debit": 100.00, "credit": 0.00},
                {"account_code": "6001", "debit": 0.00, "credit": 99.00},
            ],
            status="draft",
        )
        assert v.is_balanced() is False

    def test_rejects_1_cent_discrepancy(self):
        """1 分钱错账必须被拦住 (会计零容忍, 证监会/四大审计不接受容忍度)."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_DISCREP_001",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount_fen=10001,
            entries=[
                {"account_code": "1001", "debit": 100.01, "credit": 0.00},
                {"account_code": "6001", "debit": 0.00, "credit": 100.00},
            ],
            status="draft",
        )
        # 1 分钱差异 = 1 fen 差异, 必须拦住
        assert v.is_balanced() is False

    def test_ieee_754_float_arithmetic_no_false_reject(self):
        """0.1 + 0.2 != 0.3 的 IEEE 754 坑不能导致误判 (fen 整数比较规避)."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_IEEE_001",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount_fen=30,
            entries=[
                {"account_code": "1001", "debit": 0.1, "credit": 0.0},
                {"account_code": "1002", "debit": 0.2, "credit": 0.0},
                {"account_code": "6001", "debit": 0.0, "credit": 0.3},
            ],
            status="draft",
        )
        # 浮点: 0.1 + 0.2 = 0.30000000000000004 ≠ 0.3
        # fen 整数: round(0.1*100) + round(0.2*100) = 30 = round(0.3*100)
        assert v.is_balanced() is True

    def test_exact_fen_equality_required(self):
        """借贷精确 fen 整数相等才视为平衡 (无任何容忍度)."""
        v_exact = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=uuid.uuid4(),
            voucher_no="V_EXACT_001",
            voucher_date=date(2026, 4, 19),
            voucher_type="sales",
            total_amount_fen=100000,
            entries=[
                {"account_code": "1001", "debit": 1000.00, "credit": 0.00},
                {"account_code": "6001", "debit": 0.00, "credit": 1000.00},
            ],
            status="draft",
        )
        assert v_exact.is_balanced() is True


# ─── 真实场景 #3: 历史行兼容 (v031 建表的旧数据) ─────────────────────


class TestHistoricalRowCompatibilityScenario:
    """场景: v031 时代写入的凭证, store_id / voucher_date 为 NULL, v264 迁移后仍可读."""

    def test_orm_allows_null_store_id_for_historical_rows(self):
        """v264 物理 schema 允许 store_id NULL, ORM 必须匹配."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=None,          # 历史行无 store_id
            voucher_no="V_LEGACY_001",
            voucher_date=None,      # 历史行无 voucher_date (迁移后会回填, 但 NULL 合法)
            voucher_type="settlement",
            total_amount=100.00,    # 老字段, 元
            total_amount_fen=None,  # 老行未回填 fen
            entries=[],
            status="draft",
        )
        assert v.store_id is None
        assert v.voucher_date is None

    def test_to_dict_handles_null_fields_gracefully(self):
        """历史行 to_dict() 不应崩溃, NULL 字段应序列化为 None."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            store_id=None,
            voucher_no="V_LEGACY_002",
            voucher_date=None,
            voucher_type="settlement",
            total_amount=None,
            total_amount_fen=None,
            entries=[],
            status="draft",
            created_at=datetime.now(timezone.utc),
        )
        d = v.to_dict()
        assert d["store_id"] is None
        assert d["voucher_date"] is None
        assert d["total_amount"] is None
        assert d["total_amount_fen"] is None


# ─── 迁移文件结构验证 (防漂移, CLAUDE.md §21) ─────────────────────────


class TestV264MigrationFileStructure:
    """v264_financial_vouchers_sync_orm.py 结构契约."""

    MIGRATION_PATH = (
        Path(__file__).resolve().parents[4]
        / "shared/db-migrations/versions/v264_financial_vouchers_sync_orm.py"
    )

    @pytest.fixture
    def migration_source(self) -> str:
        assert self.MIGRATION_PATH.exists(), f"迁移文件缺失: {self.MIGRATION_PATH}"
        return self.MIGRATION_PATH.read_text(encoding="utf-8")

    def test_revision_is_v264(self, migration_source):
        assert re.search(r'^revision\s*=\s*"v264"', migration_source, re.M)

    def test_down_revision_is_v263(self, migration_source):
        """必须 down_revision=v263 (不能踩 v265 FCT Agent 2.0 的坑)."""
        assert re.search(r'^down_revision\s*=\s*"v263"', migration_source, re.M)

    def test_adds_all_8_expected_columns(self, migration_source):
        """upgrade() 必须 ADD 8 个 ORM 期望列 (含 v031 悬空的 total_amount)."""
        for col in [
            "store_id", "voucher_date",
            "total_amount", "total_amount_fen",
            "source_type", "source_id", "exported_at", "updated_at",
        ]:
            assert f"ADD COLUMN IF NOT EXISTS {col}" in migration_source, \
                f"迁移缺列: {col}"

    def test_total_amount_fen_uses_bigint(self, migration_source):
        """金额字段必须 BIGINT (屯象 fen 约定, 不能用 NUMERIC)."""
        assert re.search(r"total_amount_fen\s+BIGINT", migration_source)

    def test_drops_not_null_on_legacy_period_columns(self, migration_source):
        """v264 必须松绑 period_start/period_end NOT NULL."""
        assert "ALTER COLUMN period_start DROP NOT NULL" in migration_source
        assert "ALTER COLUMN period_end   DROP NOT NULL" in migration_source

    def test_backfills_voucher_date_from_period_start(self, migration_source):
        """必须回填 voucher_date = period_start (语义等价, 幂等)."""
        assert "UPDATE financial_vouchers" in migration_source
        assert "SET voucher_date = period_start" in migration_source
        assert "WHERE voucher_date IS NULL" in migration_source  # 幂等

    def test_deprecated_columns_have_comments(self, migration_source):
        """被 deprecate 的列必须有 COMMENT, 告诉后来者原因."""
        for col in ["period_start", "period_end", "total_debit", "total_credit",
                    "total_amount"]:
            assert re.search(
                rf"COMMENT ON COLUMN financial_vouchers\.{col}",
                migration_source,
            ), f"列 {col} 缺 DEPRECATED COMMENT"

    def test_downgrade_is_not_empty(self, migration_source):
        """downgrade() 必须非空 (MIGRATION_RULES 铁律)."""
        # 跨空行抓 downgrade 全函数体
        m = re.search(r"def downgrade\(\).*?(?=\Z|^def )",
                      migration_source, re.S | re.M)
        assert m, "downgrade 函数不存在"
        body = m.group(0)
        assert "op.execute" in body, "downgrade 必须有实际 SQL, 不能只有 pass"
        assert "DROP COLUMN IF EXISTS" in body, "downgrade 必须 DROP 所有新列"
        assert "DROP INDEX CONCURRENTLY" in body, "downgrade 必须 CONCURRENTLY DROP 索引"

    def test_index_uses_concurrently(self, migration_source):
        """DBA 风险 #1 修复: CREATE INDEX 必须用 CONCURRENTLY, 不阻塞 DML."""
        assert "CREATE INDEX CONCURRENTLY" in migration_source, \
            "索引必须 CONCURRENTLY 创建, 否则阻塞千万级表的所有 INSERT/UPDATE"
        assert "autocommit_block()" in migration_source, \
            "CONCURRENTLY 必须脱离 alembic 主事务, 用 autocommit_block"

    def test_downgrade_has_null_period_guard(self, migration_source):
        """DBA 风险 #7 修复: downgrade 前置检查, 发现 NULL period_start 必须中止."""
        # 找 downgrade 函数体内是否有 guard
        m = re.search(
            r"def downgrade\(\).*?(?=\Z|def )",
            migration_source, re.S,
        )
        assert m
        body = m.group(0)
        assert "period_start IS NULL" in body, \
            "downgrade 必须先 SELECT COUNT period_start IS NULL"
        assert "RAISE EXCEPTION" in body, \
            "发现 NULL period_start 必须 RAISE EXCEPTION 中止"

    def test_migration_has_raise_notice_for_observability(self, migration_source):
        """DBA 风险 #5 修复: migration 必须有 RAISE NOTICE 进度标记."""
        notice_count = len(re.findall(r"RAISE NOTICE 'v264", migration_source))
        # upgrade 5 步 + downgrade 3 步 + 2 个 "complete" = 10 次
        assert notice_count >= 8, \
            f"RAISE NOTICE 不足 (找到 {notice_count} 次, 至少 8 次)"

    def test_runbook_removes_broken_pg_sleep_pattern(self, migration_source):
        """DBA 风险 #2 修复: 上一版 runbook 的 DO $$ + pg_sleep 是错的(单事务)."""
        # Runbook 应已标注"上一版错了"并给出外部 bash 脚本方案
        assert "scripts/backfill_voucher_date.sh" in migration_source, \
            "大表回填方案必须指向外部脚本"
        assert "SKIP LOCKED" in migration_source or "独立事务" in migration_source, \
            "外部脚本方案必须说明每批独立事务"

    def test_backfill_has_inline_threshold_guard(self, migration_source):
        """[BLOCKER-B4 独立验证响应]: UPDATE 全表前必须预检行数阈值.

        原风险 (DBA P0-1): 百万级 UPDATE 在 alembic 主事务内 → WAL 爆炸 + 主从 lag.
        修复: 迁移里预查 COUNT(*), 超阈值 RAISE EXCEPTION 强制走外部脚本.
        """
        # 预检查要求: 能找到 "RAISE EXCEPTION" + 阈值 (50000 或 BACKFILL_INLINE_THRESHOLD)
        assert "RAISE EXCEPTION" in migration_source, (
            "step 3 UPDATE 前必须 RAISE EXCEPTION guard"
        )
        # 阈值要有硬编码 or 变量声明
        assert re.search(
            r"(threshold.{0,30}50000|BACKFILL_INLINE_THRESHOLD|null_rows\s*>\s*threshold)",
            migration_source, re.I,
        ), "必须有阈值比较逻辑 (默认 5 万行)"
        # Exception 消息必须引导外部脚本
        assert re.search(
            r"backfill_voucher_date\.sh|external.*script|外部.*脚本",
            migration_source, re.I,
        ), "Exception 消息必须提示外部脚本路径"
