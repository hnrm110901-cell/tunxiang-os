"""Tier 1 测试: accounting_periods 账期表 + 状态机 + service (v270 + W1.4)

Tier 级别:
  🔴 Tier 1 — 资金安全 / 金税四期审计红线

测试边界 (CLAUDE.md §20 "基于真实餐厅场景"):
  场景 1. 月结: 店长在 2026-05-03 关 2026-04 账期 (审计留痕)
  场景 2. 重开: 发现 4 月数据错漏, CFO 批准重开补录 (closed → open)
  场景 3. 年结锁定: 2026 年 12 个月全 closed 后, 财务总监 lock_year (不可重开)
  场景 4. locked 后尝试 reopen → 拒绝
  场景 5. 并发 ensure_period: 两 worker 同时建同月 → UNIQUE + refetch
  场景 6. find_period_for_date: 2026-04-15 落在 2026-04 period
  场景 7. is_date_writable: auto_ensure 行为 + 默认兜底
  迁移结构 8. v270 文件有 7 CHECK / 3 indexes / RLS / UNIQUE

注: DB CHECK / RLS 用结构化断言 (解析迁移文件) + DEV Postgres 端到端脚本.

运行:
  cd /Users/lichun/Documents/GitHub/zhilian-os/services/tx-finance
  pytest src/tests/test_accounting_periods_tier1.py -v
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.accounting_period import (  # type: ignore  # noqa: E402
    STATUS_CLOSED,
    STATUS_LOCKED,
    STATUS_OPEN,
    AccountingPeriod,
    month_range,
)
from services.accounting_period_service import (  # type: ignore  # noqa: E402
    AccountingPeriodService,
)


# ─── 工具 ────────────────────────────────────────────────────────────


def _period(
    year: int = 2026, month: int = 4,
    status: str = STATUS_OPEN,
    tenant_id: uuid.UUID | None = None,
) -> AccountingPeriod:
    start, end = month_range(year, month)
    return AccountingPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        period_year=year,
        period_month=month,
        period_start=start,
        period_end=end,
        status=status,
    )


# ─── month_range 工具函数 ───────────────────────────────────────────


class TestMonthRange:
    """月份首末日计算 — 闰年 / 12 月跨年等边界."""

    def test_normal_month(self):
        assert month_range(2026, 4) == (date(2026, 4, 1), date(2026, 4, 30))

    def test_31_day_month(self):
        assert month_range(2026, 1) == (date(2026, 1, 1), date(2026, 1, 31))

    def test_february_leap_year(self):
        assert month_range(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))

    def test_february_non_leap(self):
        assert month_range(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))

    def test_december_no_year_overflow(self):
        """12 月末必须是 12-31, 不能溢到下一年."""
        assert month_range(2026, 12) == (date(2026, 12, 1), date(2026, 12, 31))

    def test_invalid_month_rejected(self):
        with pytest.raises(ValueError, match="月份非法"):
            month_range(2026, 13)
        with pytest.raises(ValueError, match="月份非法"):
            month_range(2026, 0)


# ─── AccountingPeriod ORM 状态机 ───────────────────────────────────


class TestPeriodStateMachine:
    """open → closed → (open | locked) 状态转换铁律."""

    def test_new_period_is_open(self):
        p = _period()
        assert p.is_open is True
        assert p.is_writable is True

    def test_close_sets_audit_fields(self):
        p = _period()
        operator = uuid.uuid4()
        t_before = datetime.now(timezone.utc)
        p.close(operator_id=operator, reason="2026-04 月结")
        t_after = datetime.now(timezone.utc)

        assert p.status == STATUS_CLOSED
        assert p.is_closed is True
        assert p.is_writable is False
        assert p.closed_by == operator
        assert p.closed_reason == "2026-04 月结"
        assert t_before <= p.closed_at <= t_after

    def test_close_rejects_already_closed(self):
        p = _period(status=STATUS_CLOSED)
        with pytest.raises(ValueError, match="状态 closed 不支持月结"):
            p.close(operator_id=uuid.uuid4(), reason="重复")

    def test_close_rejects_locked(self):
        p = _period(status=STATUS_LOCKED)
        with pytest.raises(ValueError, match="状态 locked 不支持月结"):
            p.close(operator_id=uuid.uuid4(), reason="试")

    def test_close_rejects_empty_reason(self):
        p = _period()
        with pytest.raises(ValueError, match="月结原因必填"):
            p.close(operator_id=uuid.uuid4(), reason="")
        with pytest.raises(ValueError, match="月结原因必填"):
            p.close(operator_id=uuid.uuid4(), reason="   ")

    def test_reopen_clears_is_writable_back_to_true(self):
        p = _period()
        p.close(operator_id=uuid.uuid4(), reason="关账")
        p.reopen(operator_id=uuid.uuid4(), reason="CFO 批复补录")
        assert p.status == STATUS_OPEN
        assert p.is_writable is True
        assert p.reopened_by is not None
        assert p.reopened_reason == "CFO 批复补录"

    def test_reopen_keeps_closed_audit_trail(self):
        """重开不清空 closed_at/by/reason — 审计留痕铁律."""
        p = _period()
        op1 = uuid.uuid4()
        p.close(operator_id=op1, reason="关账")
        prev_closed_at = p.closed_at
        p.reopen(operator_id=uuid.uuid4(), reason="补录")
        assert p.closed_at == prev_closed_at  # 不清
        assert p.closed_by == op1  # 不清

    def test_reopen_rejects_open(self):
        p = _period()  # 已 open
        with pytest.raises(ValueError, match="状态 open 不支持重开"):
            p.reopen(operator_id=uuid.uuid4(), reason="试")

    def test_reopen_rejects_locked(self):
        p = _period(status=STATUS_LOCKED)
        with pytest.raises(ValueError, match="已年结锁定.*不可重开"):
            p.reopen(operator_id=uuid.uuid4(), reason="试")

    def test_lock_rejects_open(self):
        """lock 必须从 closed 出发, 不能直接 open → locked."""
        p = _period()
        with pytest.raises(ValueError, match="需先月结 closed"):
            p.lock(operator_id=uuid.uuid4(), reason="年结")

    def test_lock_from_closed(self):
        p = _period()
        p.close(operator_id=uuid.uuid4(), reason="关账")
        p.lock(operator_id=uuid.uuid4(), reason="2026 年度结账")
        assert p.status == STATUS_LOCKED
        assert p.is_locked is True
        assert p.is_writable is False
        assert p.locked_reason == "2026 年度结账"


# ─── contains_date ─────────────────────────────────────────────────


class TestContainsDate:
    def test_date_inside_range(self):
        p = _period(year=2026, month=4)
        assert p.contains_date(date(2026, 4, 15)) is True

    def test_boundary_start(self):
        p = _period(year=2026, month=4)
        assert p.contains_date(date(2026, 4, 1)) is True

    def test_boundary_end(self):
        p = _period(year=2026, month=4)
        assert p.contains_date(date(2026, 4, 30)) is True

    def test_date_outside(self):
        p = _period(year=2026, month=4)
        assert p.contains_date(date(2026, 5, 1)) is False
        assert p.contains_date(date(2026, 3, 31)) is False


# ─── Service: ensure_period ────────────────────────────────────────


class _FakeSavepoint:
    """[W2.C] 模拟 session.begin_nested() 返回的 async context manager.

    真 SQLAlchemy 的 begin_nested() 返回 SAVEPOINT transaction.
    异常时自动 ROLLBACK TO SAVEPOINT, 异常继续向外传播.
    """
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # 不抑制异常 (返 False), 让 IntegrityError 穿透到 service 的 try/except
        return False


class TestEnsurePeriod:
    @pytest.mark.asyncio
    async def test_ensure_creates_when_missing(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        # _find_period miss
        mock_miss = MagicMock()
        mock_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_miss)
        session.flush = AsyncMock()
        # [W2.C] begin_nested 返回 fake savepoint
        session.begin_nested = MagicMock(return_value=_FakeSavepoint())

        p = await svc.ensure_period(
            tenant_id=uuid.uuid4(), year=2026, month=4, session=session,
        )
        assert p.status == STATUS_OPEN
        assert p.period_start == date(2026, 4, 1)
        assert p.period_end == date(2026, 4, 30)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        # [W2.C] 必走 SAVEPOINT
        session.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_returns_existing(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        existing = _period(year=2026, month=4, status=STATUS_CLOSED)
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=existing)
        session.execute = AsyncMock(return_value=mock_hit)

        p = await svc.ensure_period(
            tenant_id=existing.tenant_id, year=2026, month=4, session=session,
        )
        assert p is existing
        session.add.assert_not_called()  # 不重复 INSERT
        # [W2.C] 已存在 → 不进 SAVEPOINT
        session.begin_nested.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_race_does_not_rollback_outer_transaction(self):
        """[W2.C 业务价值测试] 并发 race 不破坏调用方前置写入.

        模拟: create_voucher 流程内调用 ensure_period, 若 ensure_period 触发 race:
        - W2.C 前: session.rollback() 清空 caller 的凭证/分录写入 (丢数据)
        - W2.C 后: SAVEPOINT 回滚只影响 period INSERT, caller 前置写入保留
        """
        from sqlalchemy.exc import IntegrityError

        svc = AccountingPeriodService()
        winner = _period(year=2026, month=4)

        session = AsyncMock()
        miss = MagicMock()
        miss.scalar_one_or_none = MagicMock(return_value=None)
        hit = MagicMock()
        hit.scalar_one_or_none = MagicMock(return_value=winner)
        session.execute = AsyncMock(side_effect=[miss, hit])

        session.flush = AsyncMock(side_effect=IntegrityError(
            "INSERT ...", {},
            Exception('duplicate key value violates unique constraint "uq_ap_tenant_year_month"'),
        ))
        session.begin_nested = MagicMock(return_value=_FakeSavepoint())
        session.rollback = AsyncMock()
        # 模拟外层事务内已有前置写入 (e.g. create_voucher 已 add 凭证)
        session.add = MagicMock()

        await svc.ensure_period(
            tenant_id=winner.tenant_id, year=2026, month=4, session=session,
        )

        # 业务价值: session.rollback 从不调 (外层事务完整保留)
        assert session.rollback.await_count == 0
        # 流程走: begin_nested → add (尝试) → flush (IntegrityError) → SAVEPOINT 自动撤销
        session.begin_nested.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_refetches_on_concurrent_race(self):
        """[W2.C 关键修复] race 分支只回滚 SAVEPOINT, 不调 session.rollback().

        原问题: rollback() 会清空外层事务的所有前置写入 (CFO P0-2 年化百万丢单).
        修复: begin_nested() 创建 SAVEPOINT, flush 失败自动 ROLLBACK TO SAVEPOINT,
        外层事务完整保留.
        """
        from sqlalchemy.exc import IntegrityError

        svc = AccountingPeriodService()
        session = AsyncMock()

        winner = _period(year=2026, month=4)

        # 预查 miss → begin_nested → add → flush IntegrityError → refetch hit
        miss = MagicMock()
        miss.scalar_one_or_none = MagicMock(return_value=None)
        hit = MagicMock()
        hit.scalar_one_or_none = MagicMock(return_value=winner)
        session.execute = AsyncMock(side_effect=[miss, hit])

        fake_orig = Exception(
            'duplicate key value violates unique constraint "uq_ap_tenant_year_month"'
        )
        session.flush = AsyncMock(
            side_effect=IntegrityError("INSERT ...", {}, fake_orig)
        )
        # [W2.C] SAVEPOINT 正常退出 (异常穿透), session.rollback 不应被调
        session.begin_nested = MagicMock(return_value=_FakeSavepoint())
        session.rollback = AsyncMock()

        p = await svc.ensure_period(
            tenant_id=winner.tenant_id, year=2026, month=4, session=session,
        )
        assert p is winner
        # [W2.C 核心断言] 不调 session.rollback() — 外层事务保持完整
        session.rollback.assert_not_called()
        # SAVEPOINT 被创建
        session.begin_nested.assert_called_once()


# ─── Service: close / reopen / lock ────────────────────────────────


class TestCloseReopenLockViaService:
    @pytest.mark.asyncio
    async def test_close_transitions_state(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        p = _period()
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=p)
        session.execute = AsyncMock(return_value=mock_hit)
        session.flush = AsyncMock()

        await svc.close_period(
            tenant_id=p.tenant_id, year=2026, month=4,
            operator_id=uuid.uuid4(), reason="2026-04 月结",
            session=session,
        )
        assert p.status == STATUS_CLOSED
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_period_not_found_raises(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        mock_miss = MagicMock()
        mock_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_miss)

        with pytest.raises(ValueError, match="账期 2026-04 不存在"):
            await svc.close_period(
                tenant_id=uuid.uuid4(), year=2026, month=4,
                operator_id=uuid.uuid4(), reason="关账",
                session=session,
            )

    @pytest.mark.asyncio
    async def test_lock_year_requires_all_12_closed(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        # 11 月份, 缺 12 月
        periods = [_period(year=2026, month=m, status=STATUS_CLOSED) for m in range(1, 12)]
        mock_list = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=periods)
        mock_list.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_list)

        with pytest.raises(ValueError, match="只找到 11 个 period"):
            await svc.lock_year(
                tenant_id=uuid.uuid4(), year=2026,
                operator_id=uuid.uuid4(), reason="2026 年度结账",
                session=session,
            )

    @pytest.mark.asyncio
    async def test_lock_year_rejects_non_closed_periods(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        # 全 12 个, 但 3 月仍 open
        periods = [_period(year=2026, month=m, status=STATUS_CLOSED) for m in range(1, 13)]
        periods[2].status = STATUS_OPEN  # 3 月还开着

        mock_list = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=periods)
        mock_list.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_list)

        with pytest.raises(ValueError, match="非 closed.*2026-03"):
            await svc.lock_year(
                tenant_id=uuid.uuid4(), year=2026,
                operator_id=uuid.uuid4(), reason="年结",
                session=session,
            )

    @pytest.mark.asyncio
    async def test_lock_year_success(self):
        svc = AccountingPeriodService()
        session = AsyncMock()
        session.flush = AsyncMock()

        periods = [_period(year=2026, month=m, status=STATUS_CLOSED) for m in range(1, 13)]
        mock_list = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=periods)
        mock_list.scalars = MagicMock(return_value=mock_scalars)
        session.execute = AsyncMock(return_value=mock_list)

        result = await svc.lock_year(
            tenant_id=uuid.uuid4(), year=2026,
            operator_id=uuid.uuid4(), reason="2026 年度结账",
            session=session,
        )
        assert all(p.status == STATUS_LOCKED for p in result)


# ─── Service: find_period_for_date / is_date_writable ──────────────


class TestPeriodLookup:
    @pytest.mark.asyncio
    async def test_find_period_for_date_hit(self):
        svc = AccountingPeriodService()
        session = AsyncMock()

        p = _period(year=2026, month=4)
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=p)
        session.execute = AsyncMock(return_value=mock_hit)

        result = await svc.find_period_for_date(
            tenant_id=p.tenant_id, biz_date=date(2026, 4, 15),
            session=session,
        )
        assert result is p

    @pytest.mark.asyncio
    async def test_find_period_miss(self):
        svc = AccountingPeriodService()
        session = AsyncMock()
        mock_miss = MagicMock()
        mock_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_miss)

        result = await svc.find_period_for_date(
            tenant_id=uuid.uuid4(), biz_date=date(2026, 4, 15),
            session=session,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_is_date_writable_when_period_open(self):
        svc = AccountingPeriodService()
        session = AsyncMock()
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=_period())
        session.execute = AsyncMock(return_value=mock_hit)

        result = await svc.is_date_writable(
            tenant_id=uuid.uuid4(), biz_date=date(2026, 4, 15),
            session=session,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_is_date_writable_when_period_closed(self):
        svc = AccountingPeriodService()
        session = AsyncMock()
        mock_hit = MagicMock()
        mock_hit.scalar_one_or_none = MagicMock(return_value=_period(status=STATUS_CLOSED))
        session.execute = AsyncMock(return_value=mock_hit)

        result = await svc.is_date_writable(
            tenant_id=uuid.uuid4(), biz_date=date(2026, 4, 15),
            session=session,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_date_writable_default_true_when_period_absent(self):
        """period 不存在 + auto_ensure=False: 视作可写 (向前兼容 W1.4 未接入前)."""
        svc = AccountingPeriodService()
        session = AsyncMock()
        mock_miss = MagicMock()
        mock_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_miss)

        result = await svc.is_date_writable(
            tenant_id=uuid.uuid4(), biz_date=date(2026, 4, 15),
            session=session,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_is_date_writable_auto_ensure_creates_period(self):
        """auto_ensure=True + period 不存在: 创建 open period 并返回 True."""
        svc = AccountingPeriodService()
        session = AsyncMock()
        # find_period_for_date miss, 然后 ensure_period 内 _find_period miss
        mock_miss = MagicMock()
        mock_miss.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=mock_miss)
        session.flush = AsyncMock()
        # [W2.C] ensure_period 走 SAVEPOINT
        session.begin_nested = MagicMock(return_value=_FakeSavepoint())

        result = await svc.is_date_writable(
            tenant_id=uuid.uuid4(), biz_date=date(2026, 4, 15),
            session=session, auto_ensure=True,
        )
        assert result is True
        session.add.assert_called_once()


# ─── 迁移文件结构验证 ───────────────────────────────────────────────


class TestV270MigrationFileStructure:
    migration_src: str = ""

    @pytest.fixture(autouse=True)
    def _load_migration(self):
        path = (
            Path(__file__).resolve().parents[4]
            / "shared" / "db-migrations" / "versions"
            / "v270_accounting_periods.py"
        )
        assert path.exists(), f"v270 迁移文件不存在: {path}"
        self.migration_src = path.read_text(encoding="utf-8")

    def test_revision_id_is_v270(self):
        assert re.search(r'^revision\s*=\s*"v270"', self.migration_src, re.M)

    def test_down_revision_chains_from_v268(self):
        assert re.search(r'^down_revision\s*=\s*"v268"', self.migration_src, re.M)

    def test_seven_check_constraints(self):
        """7 CHECK: status / month / year / date_range / closed_audit / locked_audit / ... """
        required_checks = [
            "chk_ap_status_valid",
            "chk_ap_month_range",
            "chk_ap_year_range",
            "chk_ap_date_range",
            "chk_ap_closed_audit",
            "chk_ap_locked_audit",
        ]
        for c in required_checks:
            assert c in self.migration_src, f"v270 缺少 CHECK {c}"

    def test_closed_audit_enforces_at_and_by(self):
        """status='closed' → closed_at + closed_by 必填."""
        assert re.search(
            r"status\s*!=\s*'closed'\s*OR\s*\(\s*closed_at\s+IS\s+NOT\s+NULL\s+AND\s+closed_by\s+IS\s+NOT\s+NULL\s*\)",
            self.migration_src, re.I,
        )

    def test_locked_audit_enforces_at_and_by(self):
        assert re.search(
            r"status\s*!=\s*'locked'\s*OR\s*\(\s*locked_at\s+IS\s+NOT\s+NULL\s+AND\s+locked_by\s+IS\s+NOT\s+NULL\s*\)",
            self.migration_src, re.I,
        )

    def test_unique_tenant_year_month(self):
        assert "uq_ap_tenant_year_month" in self.migration_src
        uq_block = re.search(
            r"UniqueConstraint\(\s*(.*?)\s*name=.uq_ap_tenant_year_month.",
            self.migration_src, re.S,
        )
        assert uq_block is not None
        cols = uq_block.group(1)
        assert '"tenant_id"' in cols
        assert '"period_year"' in cols
        assert '"period_month"' in cols

    def test_partial_index_on_open_status(self):
        """ix_ap_tenant_open 必须是 partial index WHERE status='open'."""
        assert "ix_ap_tenant_open" in self.migration_src
        assert re.search(
            r'ix_ap_tenant_open.*?postgresql_where.*?status\s*=\s*.open.',
            self.migration_src, re.S,
        ), "ix_ap_tenant_open 必须是 partial index WHERE status='open'"

    def test_date_range_index(self):
        assert "ix_ap_tenant_date_range" in self.migration_src
        assert re.search(
            r'ix_ap_tenant_date_range.*?\[\s*"tenant_id"\s*,\s*"period_start"\s*,\s*"period_end"\s*\]',
            self.migration_src, re.S,
        )

    def test_rls_enabled_with_app_tenant_id(self):
        assert re.search(
            r"ALTER TABLE\s+accounting_periods\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY",
            self.migration_src, re.I,
        )
        assert "CREATE POLICY accounting_periods_tenant" in self.migration_src
        assert "current_setting('app.tenant_id', true)" in self.migration_src

    def test_rls_policy_has_with_check(self):
        """[BLOCKER-B2]: 策略必须同时有 USING 和 WITH CHECK (防御性显式)."""
        assert re.search(
            r"CREATE POLICY.*accounting_periods_tenant.*"
            r"USING\s*\(.*app\.tenant_id.*\).*"
            r"WITH\s+CHECK\s*\(.*app\.tenant_id.*\)",
            self.migration_src, re.S | re.I,
        ), "POLICY 必须同时声明 USING 和 WITH CHECK"

    def test_tenant_id_not_nullable(self):
        tenant_col = re.search(
            r'Column\(\s*"tenant_id"\s*,\s*UUID\(as_uuid=True\)\s*,\s*(.+?)\)',
            self.migration_src, re.S,
        )
        assert tenant_col is not None
        assert "nullable=False" in tenant_col.group(1)

    def test_upgrade_raise_notice_markers(self):
        notices = re.findall(r"RAISE NOTICE\s+'v270\s+step\s+\d+/\d+", self.migration_src)
        assert len(notices) >= 3

    def test_downgrade_not_empty(self):
        m = re.search(r"def downgrade\(\) -> None:(.*?)(?=\Z|^def )",
                      self.migration_src, re.S | re.M)
        assert m is not None
        body = m.group(1)
        assert "drop_table" in body.lower()

    def test_downgrade_warns_about_audit_data_loss(self):
        assert re.search(
            r"(审计|数据.{0,5}丢|不可降级|24h)",
            self.migration_src,
        )
