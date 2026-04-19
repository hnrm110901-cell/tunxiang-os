"""会计账期服务 (W1.4) — accounting_periods 的唯一操作入口

Tier 级别: 🔴 Tier 1 (资金安全 / 金税四期审计红线)

职责:
  1. 懒初始化 account period (首次写凭证时按需创建)
  2. 状态机转换: close / reopen / lock
  3. 按 voucher_date 查所属 period (W1.4b voucher 写路径用)
  4. 查 "某租户有哪些 period 仍 open"

与 W1.4b 的接口约定 (W1.4b 独立 PR 接入):
  voucher_service.create 写凭证前:
    period = await accounting_period_service.find_period_for_date(...)
    if period is None:
        period = await accounting_period_service.ensure_period(...)
    if not period.is_writable:
        raise ValueError("账期已关, 请走红冲")

事务边界:
  与 FinancialVoucherService 一致: service 只 flush 不 commit. 调用方持边界.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.accounting_period import (  # type: ignore
    STATUS_CLOSED,
    STATUS_LOCKED,
    STATUS_OPEN,
    AccountingPeriod,
    month_range,
)

log = structlog.get_logger(__name__)


class AccountingPeriodService:
    """accounting_periods 唯一操作入口.

    无状态 — 所有 session / tenant_id 通过方法参数传入.
    """

    # ── 懒初始化 ──────────────────────────────────────────────────────

    async def ensure_period(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        *,
        session: AsyncSession,
    ) -> AccountingPeriod:
        """确保 (tenant, year, month) 的 period 存在, 不存在则按 open 创建.

        [W2.C 修复] 并发 race 用 SAVEPOINT 隔离, 不污染外层事务.

        原问题 (CFO P0-2): race 分支走 session.rollback() 会把**调用方**的
        所有前置写入全部回滚. 典型场景:
          1. FinancialVoucherService.create() 调用链:
             幂等预查 → ensure_period(auto_ensure) → [race 发生 → rollback]
                                                   ↓
             整个 create() 事务被清空, 调用方拿到"静默失败"
          2. 早高峰 200 店同日首单并发写 → 5% 遇到 race → 5 分钟几十单丢失

        SAVEPOINT 修复:
          - session.begin_nested() 创建 SAVEPOINT
          - 只有 INSERT 的 flush 阶段回滚到 SAVEPOINT, 前置写入保留
          - 外层事务状态完整, caller 可继续操作

        并发安全: UNIQUE (tenant_id, year, month) + SAVEPOINT 回滚 + refetch.
        """
        existing = await self._find_period(
            session=session,
            tenant_id=tenant_id,
            year=year,
            month=month,
        )
        if existing is not None:
            return existing

        start, end = month_range(year, month)
        period = AccountingPeriod(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            period_year=year,
            period_month=month,
            period_start=start,
            period_end=end,
            status=STATUS_OPEN,
        )

        # [W2.C] SAVEPOINT 隔离 INSERT 失败 — 不影响外层事务
        # begin_nested() 创建 SAVEPOINT, __aexit__ 时:
        # - 正常退出: RELEASE SAVEPOINT (INSERT 保留)
        # - 异常退出: ROLLBACK TO SAVEPOINT (仅撤 INSERT, 外层事务保留)
        try:
            async with session.begin_nested():
                session.add(period)
                await session.flush()
        except IntegrityError as exc:
            if "uq_ap_tenant_year_month" in str(exc.orig):
                # 并发: 另一 worker 先 INSERT 成功. SAVEPOINT 已自动回滚 INSERT,
                # refetch 拿到 winner. **外层事务保持完整.**
                log.info(
                    "accounting_period.ensure.race_refetch",
                    tenant_id=str(tenant_id),
                    period=f"{year}-{month:02d}",
                )
                winner = await self._find_period(
                    session=session,
                    tenant_id=tenant_id,
                    year=year,
                    month=month,
                )
                if winner is None:
                    raise RuntimeError(
                        f"ensure_period race refetch miss: {year}-{month:02d}"
                    ) from exc
                return winner
            raise

        log.info(
            "accounting_period.ensure.created",
            tenant_id=str(tenant_id),
            period=f"{year}-{month:02d}",
        )
        return period

    # ── 状态机操作 ────────────────────────────────────────────────────

    async def close_period(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
        closed_at: datetime | None = None,
    ) -> AccountingPeriod:
        """月结: open → closed. Period 不存在则报错."""
        period = await self._require_period(
            session=session, tenant_id=tenant_id, year=year, month=month,
        )
        period.close(operator_id=operator_id, reason=reason, closed_at=closed_at)
        await session.flush()
        log.info(
            "accounting_period.close.ok",
            tenant_id=str(tenant_id),
            period=f"{year}-{month:02d}",
            operator_id=str(operator_id),
        )
        return period

    async def reopen_period(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
        reopened_at: datetime | None = None,
    ) -> AccountingPeriod:
        """重开: closed → open. locked 拒."""
        period = await self._require_period(
            session=session, tenant_id=tenant_id, year=year, month=month,
        )
        period.reopen(
            operator_id=operator_id, reason=reason, reopened_at=reopened_at,
        )
        await session.flush()
        log.info(
            "accounting_period.reopen.ok",
            tenant_id=str(tenant_id),
            period=f"{year}-{month:02d}",
            operator_id=str(operator_id),
        )
        return period

    async def lock_period(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
        locked_at: datetime | None = None,
    ) -> AccountingPeriod:
        """年结锁定: closed → locked. 必须先月结."""
        period = await self._require_period(
            session=session, tenant_id=tenant_id, year=year, month=month,
        )
        period.lock(operator_id=operator_id, reason=reason, locked_at=locked_at)
        await session.flush()
        log.info(
            "accounting_period.lock.ok",
            tenant_id=str(tenant_id),
            period=f"{year}-{month:02d}",
            operator_id=str(operator_id),
        )
        return period

    async def lock_year(
        self,
        tenant_id: uuid.UUID,
        year: int,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
    ) -> list[AccountingPeriod]:
        """年结锁定全年 12 个 period (原子操作).

        前置: 12 张 period 全部必须是 closed 状态.
        """
        periods = await self._find_year_periods(
            session=session, tenant_id=tenant_id, year=year,
        )
        if len(periods) != 12:
            raise ValueError(
                f"{year} 年度只找到 {len(periods)} 个 period, 需要先全部月结才能年结"
            )
        not_closed = [p for p in periods if p.status != STATUS_CLOSED]
        if not_closed:
            raise ValueError(
                f"{year} 年以下 period 非 closed: "
                f"{[f'{p.period_year}-{p.period_month:02d}({p.status})' for p in not_closed]}"
            )
        for p in periods:
            p.lock(operator_id=operator_id, reason=reason)
        await session.flush()
        log.info(
            "accounting_period.lock_year.ok",
            tenant_id=str(tenant_id),
            year=year,
            operator_id=str(operator_id),
        )
        return periods

    # ── 查询 ──────────────────────────────────────────────────────────

    async def find_period_for_date(
        self,
        tenant_id: uuid.UUID,
        biz_date: date,
        *,
        session: AsyncSession,
    ) -> AccountingPeriod | None:
        """按日期查所属 period. 不存在返回 None (caller 决定是否 ensure)."""
        stmt = (
            select(AccountingPeriod)
            .where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.period_start <= biz_date,
                AccountingPeriod.period_end >= biz_date,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_period(
        self,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
        *,
        session: AsyncSession,
    ) -> AccountingPeriod | None:
        """按 (year, month) 查 period. 不存在返回 None."""
        return await self._find_period(
            session=session, tenant_id=tenant_id, year=year, month=month,
        )

    async def list_open_periods(
        self,
        tenant_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> list[AccountingPeriod]:
        """列出该租户所有 open 状态的 period (用 partial index ix_ap_tenant_open)."""
        stmt = (
            select(AccountingPeriod)
            .where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.status == STATUS_OPEN,
            )
            .order_by(
                AccountingPeriod.period_year.asc(),
                AccountingPeriod.period_month.asc(),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def is_date_writable(
        self,
        tenant_id: uuid.UUID,
        biz_date: date,
        *,
        session: AsyncSession,
        auto_ensure: bool = False,
    ) -> bool:
        """判定某日期是否可写凭证.

        约定:
          - period 不存在: 若 auto_ensure=True 则创建 (open, 可写), 否则视作可写 (向前兼容 W1.4 未全量接入前)
          - period 存在且 open: 可写
          - period 存在且 closed/locked: 不可写
        """
        period = await self.find_period_for_date(
            tenant_id=tenant_id, biz_date=biz_date, session=session,
        )
        if period is None:
            if auto_ensure:
                period = await self.ensure_period(
                    tenant_id=tenant_id,
                    year=biz_date.year,
                    month=biz_date.month,
                    session=session,
                )
                return period.is_writable
            # 未接入 W1.4b 的路径: period 不存在视作可写
            return True
        return period.is_writable

    # ── 私有 ──────────────────────────────────────────────────────────

    async def _find_period(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
    ) -> AccountingPeriod | None:
        stmt = (
            select(AccountingPeriod)
            .where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.period_year == year,
                AccountingPeriod.period_month == month,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_year_periods(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
    ) -> list[AccountingPeriod]:
        stmt = (
            select(AccountingPeriod)
            .where(
                AccountingPeriod.tenant_id == tenant_id,
                AccountingPeriod.period_year == year,
            )
            .order_by(AccountingPeriod.period_month.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _require_period(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        year: int,
        month: int,
    ) -> AccountingPeriod:
        period = await self._find_period(
            session=session, tenant_id=tenant_id, year=year, month=month,
        )
        if period is None:
            raise ValueError(
                f"账期 {year}-{month:02d} 不存在 (需先 ensure_period)"
            )
        return period
