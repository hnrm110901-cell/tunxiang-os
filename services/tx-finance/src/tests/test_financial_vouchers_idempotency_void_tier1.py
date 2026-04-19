"""Tier 1 测试: financial_vouchers 幂等字段 + 作废状态机 (v268)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期审计留痕

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. order.paid 事件重试: 同 event_id 只生成 1 张凭证 (partial UNIQUE)
  场景 2. 历史凭证 event_id=NULL 不参与去重 (partial 允许多个 NULL)
  场景 3. 手工录入凭证 (event_type=NULL) 不受幂等约束
  场景 4. 误生成凭证 void: 审计留痕 (who/when/why)
  场景 5. void guard: exported 凭证不可 void, 必须红冲
  场景 6. void guard: 已 voided 不可重复 voided
  场景 7. void guard: reason 必填
  场景 8. is_active: voided=TRUE 凭证不参与账簿汇总
  迁移结构 9. v268 文件有 partial UNIQUE / CHECK / 辅助索引 / revision 链

注: 数据库层 CHECK / partial UNIQUE 用结构化断言 (解析迁移文件)
    + DEV Postgres 手动 SQL 验证 (progress.md 留痕). 理由见 v266 测试.

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_financial_vouchers_idempotency_void_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.voucher import FinancialVoucher  # type: ignore  # noqa: E402


# ─── 真实场景 #1-3: 幂等行为 (ORM + 迁移文件双视角) ──────────────────────


class TestIdempotencyFields:
    """场景: order.paid 事件被 Celery 重试 / 操作员重复点击 — 只生成 1 张凭证."""

    def test_voucher_accepts_event_fields(self):
        """凭证可挂 event_type + event_id (幂等 3 元组的 2/3)."""
        tenant_id = uuid.uuid4()
        event_id = uuid.uuid4()
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            voucher_no="V_TEST_EVT_001",
            voucher_type="sales",
            entries=[],
            event_type="order.paid",
            event_id=event_id,
        )
        assert v.event_type == "order.paid"
        assert v.event_id == event_id

    def test_event_fields_optional(self):
        """手工录入凭证可留空 event_type / event_id (不走幂等)."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_MANUAL_001",
            voucher_type="payment",
            entries=[],
        )
        assert v.event_type is None
        assert v.event_id is None

    def test_to_dict_exposes_event_fields(self):
        """to_dict 输出必须含 event_type / event_id (ERP 推送 + 审计消费)."""
        v = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no="V_TEST_001",
            voucher_type="sales",
            entries=[],
            event_type="order.paid",
            event_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        )
        d = v.to_dict()
        assert d["event_type"] == "order.paid"
        assert d["event_id"] == "00000000-0000-0000-0000-000000000001"


# ─── 真实场景 #4-8: 作废状态机 ─────────────────────────────────────────


class TestVoidStateMachine:
    """场景: 收银员误点"确认"生成凭证, 店长核对后要求作废. 审计留痕."""

    def _draft_voucher(self) -> FinancialVoucher:
        return FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            voucher_no=f"V_VOID_TEST_{uuid.uuid4().hex[:6]}",
            voucher_type="sales",
            status="draft",
            voided=False,
            entries=[],
        )

    def test_draft_voucher_is_voidable(self):
        v = self._draft_voucher()
        assert v.is_voidable is True
        assert v.is_active is True

    def test_confirmed_voucher_is_voidable(self):
        v = self._draft_voucher()
        v.status = "confirmed"
        assert v.is_voidable is True

    def test_exported_voucher_is_NOT_voidable(self):
        """exported 凭证不可 void, 必须走红冲 (金税四期规则)."""
        v = self._draft_voucher()
        v.status = "exported"
        assert v.is_voidable is False

    def test_voided_voucher_is_not_active(self):
        v = self._draft_voucher()
        v.voided = True
        v.voided_at = datetime.now(timezone.utc)
        v.voided_by = uuid.uuid4()
        v.voided_reason = "误生成"
        assert v.is_active is False

    def test_void_sets_audit_fields(self):
        """void() 同时设 voided/voided_at/voided_by/voided_reason — 审计留痕铁律."""
        v = self._draft_voucher()
        operator = uuid.uuid4()
        before = datetime.now(timezone.utc)
        v.void(operator_id=operator, reason="重复扫码误提交")
        after = datetime.now(timezone.utc)

        assert v.voided is True
        assert v.voided_at is not None
        assert before <= v.voided_at <= after
        assert v.voided_by == operator
        assert v.voided_reason == "重复扫码误提交"
        assert v.is_active is False

    def test_void_trims_reason(self):
        """作废原因首尾空白被清理 (存储规范)."""
        v = self._draft_voucher()
        v.void(operator_id=uuid.uuid4(), reason="  误录  ")
        assert v.voided_reason == "误录"

    def test_void_rejects_empty_reason(self):
        """reason 空字符串 / 纯空格 → ValueError (审计必需)."""
        v = self._draft_voucher()
        with pytest.raises(ValueError, match="作废原因必填"):
            v.void(operator_id=uuid.uuid4(), reason="")
        with pytest.raises(ValueError, match="作废原因必填"):
            v.void(operator_id=uuid.uuid4(), reason="   ")

    def test_void_rejects_exported_voucher(self):
        """exported → 禁止 void, 错误信息明确指向 red_flush."""
        v = self._draft_voucher()
        v.status = "exported"
        with pytest.raises(ValueError, match=r"红冲|red_flush"):
            v.void(operator_id=uuid.uuid4(), reason="纠错")

    def test_void_rejects_already_voided(self):
        """重复作废 → ValueError (防止 voided_by/at 被后者覆盖)."""
        v = self._draft_voucher()
        v.void(operator_id=uuid.uuid4(), reason="第一次")
        with pytest.raises(ValueError, match="已作废"):
            v.void(operator_id=uuid.uuid4(), reason="第二次")

    def test_void_accepts_custom_timestamp(self):
        """支持传入历史时间戳 (用于回溯补录作废记录)."""
        v = self._draft_voucher()
        t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        v.void(operator_id=uuid.uuid4(), reason="历史补录", voided_at=t)
        assert v.voided_at == t


# ─── 迁移文件结构验证 ───────────────────────────────────────────────


class TestV268MigrationFileStructure:
    """v268 迁移文件骨架 + CHECK / partial UNIQUE / CONCURRENTLY 等关键点."""

    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v268_financial_vouchers_idempotency_void.py"
        )
        assert path.exists(), f"v268 迁移文件不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_id_is_v268(self):
        assert re.search(r'^revision\s*=\s*"v268"', self.migration_src, re.M)

    def test_down_revision_chains_from_v266(self):
        """v268 从 v266 (W1.1 lines 子表) 延续."""
        assert re.search(r'^down_revision\s*=\s*"v266"', self.migration_src, re.M)

    def test_adds_six_columns(self):
        """ADD 6 列: event_type / event_id / voided / voided_at / voided_by / voided_reason."""
        required = [
            "event_type",
            "event_id",
            "voided",
            "voided_at",
            "voided_by",
            "voided_reason",
        ]
        for col in required:
            assert re.search(
                rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{col}\b",
                self.migration_src, re.I,
            ), f"v268 缺少 ADD COLUMN {col}"

    def test_check_void_consistency_exists(self):
        """CHECK: voided=TRUE → voided_at + voided_by 必填."""
        assert "chk_voucher_void_consistency" in self.migration_src
        # 表达式必须同时含 voided=TRUE 分支的三重条件
        assert re.search(
            r"voided\s*=\s*TRUE\s+AND\s+voided_at\s+IS\s+NOT\s+NULL\s+AND\s+voided_by\s+IS\s+NOT\s+NULL",
            self.migration_src, re.I,
        ), "CHECK 表达式必须强制 voided=TRUE 时 voided_at + voided_by 非空"

    def test_partial_unique_idempotency_index(self):
        """UNIQUE (tenant_id, event_type, event_id) WHERE 双非空.

        [BLOCKER-B3 修复]: WHERE 必须同时要求 event_id IS NOT NULL
        AND event_type IS NOT NULL. 否则 PG 对多 NULL 按 "都不相等" 处理,
        两条 event_id=同 UUID + event_type=None 都会落盘, 幂等失效.
        """
        assert "uq_fv_tenant_event" in self.migration_src
        # 必须是 partial 索引 + 双非空条件
        assert re.search(
            r"CREATE\s+UNIQUE\s+INDEX\s+CONCURRENTLY.*?uq_fv_tenant_event"
            r".*?WHERE\s+event_id\s+IS\s+NOT\s+NULL\s+AND\s+event_type\s+IS\s+NOT\s+NULL",
            self.migration_src, re.S | re.I,
        ), (
            "uq_fv_tenant_event 必须是 partial WHERE "
            "event_id IS NOT NULL AND event_type IS NOT NULL (防 NULL 幂等失效)"
        )

    def test_concurrently_used_for_all_indexes(self):
        """老表索引必须 CONCURRENTLY (不阻塞日结 DML)."""
        # 与 v266 (新空表) 对称: v268 改老表, CONCURRENTLY 是刚需
        create_index_stmts = re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            self.migration_src, re.I,
        )
        assert len(create_index_stmts) >= 3, (
            f"期望 3+ CREATE INDEX 语句 (uq_fv_tenant_event + ix_fv_event + ix_fv_voided_at), "
            f"实际 {create_index_stmts}"
        )
        # 所有 CREATE INDEX 都必须带 CONCURRENTLY (老表刚需)
        concurrent_count = len(re.findall(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY",
            self.migration_src, re.I,
        ))
        assert concurrent_count == len(create_index_stmts), (
            f"v268 所有 {len(create_index_stmts)} 个 CREATE INDEX 都必须 CONCURRENTLY, "
            f"实际 CONCURRENTLY {concurrent_count} 个 — 老表加索引锁表风险"
        )

    def test_autocommit_block_wraps_concurrently(self):
        """CREATE INDEX CONCURRENTLY 必须包在 autocommit_block() 里 (脱离 alembic 主事务)."""
        assert "autocommit_block" in self.migration_src
        # autocommit_block 应出现在 upgrade() 里
        upgrade_body = re.search(
            r"def upgrade\(\) -> None:(.*?)(?=\Z|^def downgrade)",
            self.migration_src, re.S | re.M,
        )
        assert upgrade_body is not None
        assert "autocommit_block" in upgrade_body.group(1), (
            "autocommit_block() 必须在 upgrade() 里, 否则 CONCURRENTLY 会跑失败"
        )

    def test_downgrade_drops_indexes_concurrently(self):
        """downgrade 也应 CONCURRENTLY DROP (避免锁表)."""
        downgrade_body = re.search(
            r"def downgrade\(\) -> None:(.*)", self.migration_src, re.S,
        )
        assert downgrade_body is not None
        body = downgrade_body.group(1)
        assert re.search(r"DROP\s+INDEX\s+CONCURRENTLY", body, re.I), (
            "downgrade DROP INDEX 也应 CONCURRENTLY"
        )

    def test_upgrade_has_raise_notice_markers(self):
        """RAISE NOTICE 分步可观测性 (>= 4 步)."""
        notices = re.findall(r"RAISE NOTICE\s+'v268\s+step\s+\d+/\d+", self.migration_src)
        assert len(notices) >= 4, f"v268 upgrade 至少 4 个 step 标记, 实际 {len(notices)}"

    def test_downgrade_warns_about_audit_data_loss(self):
        """downgrade 必须文档化 voided 审计数据会永久丢失."""
        assert re.search(
            r"(审计数据|voided.*丢|audit data loss|不可降级|24h)",
            self.migration_src,
        ), "v268 downgrade 必须告警 voided 审计字段会永久丢失"

    def test_orm_table_args_has_check_constraint(self):
        """ORM 的 __table_args__ 必须镜像 DB 层 CHECK (提供应用层早期校验)."""
        orm_path = (
            Path(__file__).resolve().parents[1]
            / "models" / "voucher.py"
        )
        orm_src = orm_path.read_text(encoding="utf-8")
        assert "chk_voucher_void_consistency" in orm_src, (
            "ORM __table_args__ 必须含 CheckConstraint 以供 SQLAlchemy 在 flush 前校验"
        )
