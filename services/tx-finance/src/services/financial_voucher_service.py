"""财务凭证持久化服务 (W1.3) — financial_vouchers + lines 子表写入唯一入口

Tier 级别: 🔴 Tier 1 (资金安全 / 金税四期)

背景:
  Wave 1 前置 PR 建立了 schema 骨架:
    W1.0 (v264): financial_vouchers schema ↔ ORM 对齐, 金额统一到 fen
    W1.1 (v266): financial_voucher_lines 子表 (分录 SSOT)
    W1.2 (v268): event_type/event_id 幂等 + voided 作废状态机

  但 FinancialVoucher ORM 至今无代码写入 (孤岛). 现有两个"service":
    - voucher_service.py:     纯函数式 dict 生成, 不碰 DB
    - voucher_generator.py:   生成 ERPVoucher pydantic, 推 ERP, 不写 financial_vouchers

  W1.3 补上这个缺口: 作为 financial_vouchers + lines 的**唯一写入入口**,
  提供幂等保证 + 双写 + 状态机.

核心能力:
  1. **幂等写入** — 同 (tenant_id, event_type, event_id) 只生成 1 张凭证.
     并发场景靠 PG partial UNIQUE (uq_fv_tenant_event) 兜底 + refetch.
  2. **双写** — 同事务写 entries JSONB (向后兼容) + lines 子表 (SSOT).
     W1.6 历史回填后, W2 考虑逐步 drop entries.
  3. **借贷平衡前置校验** — 应用层先验, DB 层 CHECK 再兜 (lines 互斥非负).
  4. **作废状态机** — FinancialVoucher.void() 方法转发, 审计留痕 (w/ when/why).

调用者契约:
  - 事务边界由**调用方**持有. service 内部只 flush, 不 commit.
    理由: 日结 Celery 任务可能一次写多张凭证 + settlement 状态, 需要原子性.
  - 传入 AsyncSession 必须已 SET app.tenant_id (RLS 前置).
    service 不重复 SET, 避免污染跨 service 事务.
  - 非幂等调用 (event_id=None) 由 voucher_no UNIQUE 兜底, 但不保证安全,
    调用方应显式传 event_id.

金额单位:
  全程 fen (BIGINT). entries JSONB 双写时仍用元 (兼容 ERP 推送契约).
  元字段 total_amount 由 SSOT total_amount_fen 派生, W2 PR 考虑 DB GENERATED.

Referenced ADRs:
  - CLAUDE.md §17 Tier 1: 测试先于实现 / DEMO 环境验收
  - CLAUDE.md §20: 测试基于真实餐厅场景
  - W1.2 docstring: voided/event_id 设计原因
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.voucher import FinancialVoucher, FinancialVoucherLine  # type: ignore

log = structlog.get_logger(__name__)


# ─── 输入/输出数据契约 ────────────────────────────────────────────────


@dataclass
class VoucherLineInput:
    """分录输入. 借贷互斥非负 — 与 v266 DB CHECK 对应."""
    account_code: str
    account_name: str
    debit_fen: int = 0
    credit_fen: int = 0
    summary: str = ""

    def __post_init__(self) -> None:
        if self.debit_fen < 0 or self.credit_fen < 0:
            raise ValueError(
                f"分录 {self.account_code} 借贷必须非负 "
                f"(debit={self.debit_fen}, credit={self.credit_fen})"
            )
        both_zero = self.debit_fen == 0 and self.credit_fen == 0
        both_nonzero = self.debit_fen > 0 and self.credit_fen > 0
        if both_zero or both_nonzero:
            raise ValueError(
                f"分录 {self.account_code} 借贷互斥 "
                f"(debit={self.debit_fen}, credit={self.credit_fen})"
            )


@dataclass
class VoucherCreateInput:
    """凭证创建输入 — 封装 ORM 需要的所有字段.

    event_type / event_id:
      同 (tenant_id, event_type, event_id) 只生成一张凭证 (partial UNIQUE).
      event_id=None 跳过幂等, 靠 voucher_no UNIQUE 兜底 (不推荐).
    """
    tenant_id: uuid.UUID
    voucher_no: str  # 应用层按规则生成 V{store_short}{YYYYMMDD}{SEQ}
    voucher_date: date
    voucher_type: str  # sales / cost / payment / receipt
    lines: list[VoucherLineInput]

    store_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None

    event_type: str | None = None
    event_id: uuid.UUID | None = None

    status: str = "draft"  # draft / confirmed / exported
    extra_metadata: dict[str, Any] = field(default_factory=dict)


# ─── service 本体 ────────────────────────────────────────────────────


class FinancialVoucherService:
    """financial_vouchers + lines 持久化唯一入口.

    无状态 — 所有 session / tenant_id 通过方法参数传入. 方便测试 / DI.
    """

    # ── 创建 ──────────────────────────────────────────────────────────

    async def create(
        self,
        payload: VoucherCreateInput,
        *,
        session: AsyncSession,
    ) -> FinancialVoucher:
        """创建凭证 (双写 entries JSONB + lines 子表, 幂等).

        幂等语义:
          - payload.event_id=None: 不走幂等, 每次调用都 INSERT.
            voucher_no UNIQUE 仍兜底 (但业务编号冲突语义不清晰).
          - payload.event_id 非空:
            1. 先 SELECT 看是否已有 (同 tenant + event_type + event_id).
              若有, 直接返回 (真正的幂等语义).
            2. 若无, INSERT. 并发场景下可能两个 worker 都走到 (2),
              由 partial UNIQUE (uq_fv_tenant_event) 兜底, 后者 IntegrityError
              → refetch 返回前者的结果.

        借贷平衡:
          - 应用层先验: lines 借方总 fen == 贷方总 fen (零容忍)
          - DB 层 CHECK 不管凭证级平衡, 只管行级借贷互斥
          - total_amount_fen = sum(debit_fen) (借方总)

        Returns:
            已 flush 但未 commit 的 FinancialVoucher.
            caller 持有事务边界, 决定 commit 时机.

        Raises:
            ValueError: 借贷不平衡 / lines 为空 / 输入字段非法
            IntegrityError: 非幂等场景的 UNIQUE 冲突 (voucher_no)
        """
        # 1. 前置校验 ────────────────────────────────────────────────
        if not payload.lines:
            raise ValueError("凭证必须含至少一条分录")

        total_debit_fen = sum(l.debit_fen for l in payload.lines)
        total_credit_fen = sum(l.credit_fen for l in payload.lines)
        if total_debit_fen != total_credit_fen:
            raise ValueError(
                f"借贷不平衡 (fen 整数零容忍): "
                f"debit={total_debit_fen} != credit={total_credit_fen}"
            )
        if total_debit_fen == 0:
            raise ValueError("凭证借贷总额均为 0, 无会计意义")

        # 2. 幂等预查 ─────────────────────────────────────────────────
        if payload.event_id is not None:
            existing = await self._find_by_event(
                session=session,
                tenant_id=payload.tenant_id,
                event_type=payload.event_type,
                event_id=payload.event_id,
            )
            if existing is not None:
                log.info(
                    "voucher.create.idempotent_hit",
                    voucher_id=str(existing.id),
                    event_type=payload.event_type,
                    event_id=str(payload.event_id),
                )
                return existing

        # 3. 构造 ORM (双写 entries + lines, 单事务) ──────────────────
        voucher = self._build_orm_voucher(payload, total_debit_fen)
        session.add(voucher)

        try:
            await session.flush()
        except IntegrityError as exc:
            # 并发场景: 两 worker 同 event_id, 一个先 flush 成功, 后者撞
            # partial UNIQUE (uq_fv_tenant_event). 回滚 + refetch.
            if payload.event_id is not None and "uq_fv_tenant_event" in str(exc.orig):
                log.info(
                    "voucher.create.race_refetch",
                    event_type=payload.event_type,
                    event_id=str(payload.event_id),
                )
                await session.rollback()
                winner = await self._find_by_event(
                    session=session,
                    tenant_id=payload.tenant_id,
                    event_type=payload.event_type,
                    event_id=payload.event_id,
                )
                if winner is None:
                    # 理论不可能 — 如果 UNIQUE 冲突了, 那行必然存在
                    raise RuntimeError(
                        f"幂等冲突但 refetch 未找到 event_id={payload.event_id}"
                    ) from exc
                return winner
            raise  # 其他 UNIQUE 冲突 (voucher_no 等) 直接上抛

        log.info(
            "voucher.create.ok",
            voucher_id=str(voucher.id),
            voucher_no=voucher.voucher_no,
            total_fen=total_debit_fen,
            line_count=len(payload.lines),
            idempotent=payload.event_id is not None,
        )
        return voucher

    # ── 作废 ──────────────────────────────────────────────────────────

    async def void(
        self,
        voucher_id: uuid.UUID,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
        voided_at: datetime | None = None,
    ) -> FinancialVoucher:
        """作废凭证 (调用 ORM 层 void() 方法 + flush).

        Raises:
            ValueError: 凭证不存在 / 已作废 / status=exported (需红冲)
        """
        voucher = await session.get(FinancialVoucher, voucher_id)
        if voucher is None:
            raise ValueError(f"凭证不存在: {voucher_id}")

        # ORM 层方法已内置所有守护 (is_voidable 检查)
        voucher.void(
            operator_id=operator_id,
            reason=reason,
            voided_at=voided_at or datetime.now(timezone.utc),
        )
        await session.flush()

        log.info(
            "voucher.void.ok",
            voucher_id=str(voucher_id),
            operator_id=str(operator_id),
            reason=reason,
        )
        return voucher

    # ── 查询 ──────────────────────────────────────────────────────────

    async def get_by_event(
        self,
        tenant_id: uuid.UUID,
        event_type: str | None,
        event_id: uuid.UUID,
        *,
        session: AsyncSession,
    ) -> FinancialVoucher | None:
        """按幂等键查凭证. 用于调用方预先检查是否已处理过事件."""
        return await self._find_by_event(
            session=session,
            tenant_id=tenant_id,
            event_type=event_type,
            event_id=event_id,
        )

    # ── 私有辅助 ──────────────────────────────────────────────────────

    async def _find_by_event(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        event_type: str | None,
        event_id: uuid.UUID,
    ) -> FinancialVoucher | None:
        """按 (tenant, event_type, event_id) 查现有凭证 (幂等预查)."""
        stmt = select(FinancialVoucher).where(
            FinancialVoucher.tenant_id == tenant_id,
            FinancialVoucher.event_id == event_id,
        )
        if event_type is not None:
            stmt = stmt.where(FinancialVoucher.event_type == event_type)
        stmt = stmt.limit(1)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    def _build_orm_voucher(
        self,
        payload: VoucherCreateInput,
        total_fen: int,
    ) -> FinancialVoucher:
        """构造 FinancialVoucher + lines (内存中, 未 flush).

        双写设计: 同时写 lines 子表 (SSOT) 和 entries JSONB (向后兼容).
        W2 考虑 entries 改为 GENERATED 或逐步 drop.
        """
        voucher = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=payload.tenant_id,
            store_id=payload.store_id,
            voucher_no=payload.voucher_no,
            voucher_date=payload.voucher_date,
            voucher_type=payload.voucher_type,
            total_amount_fen=total_fen,
            total_amount=total_fen / 100,  # 元, 过渡期保留
            entries=self._lines_to_entries_jsonb(payload.lines),
            source_type=payload.source_type,
            source_id=payload.source_id,
            status=payload.status,
            event_type=payload.event_type,
            event_id=payload.event_id,
            voided=False,
        )
        # 先设父, 再构造 lines (lines.voucher_id 由 relationship 自动填)
        voucher.lines = [
            FinancialVoucherLine(
                id=uuid.uuid4(),
                tenant_id=payload.tenant_id,  # 冗余: 与 voucher.tenant_id 同步
                line_no=idx + 1,
                account_code=l.account_code,
                account_name=l.account_name,
                debit_fen=l.debit_fen,
                credit_fen=l.credit_fen,
                summary=l.summary or None,
            )
            for idx, l in enumerate(payload.lines)
        ]
        return voucher

    @staticmethod
    def _lines_to_entries_jsonb(
        lines: list[VoucherLineInput],
    ) -> list[dict[str, Any]]:
        """将 lines 转换为 entries JSONB 兼容格式 (元为单位).

        历史 entries 格式 (ERP 推送契约, 见 FinancialVoucher docstring):
            [{
                "account_code": "6001",
                "account_name": "主营业务收入",
                "debit": 0.00,       # 元
                "credit": 1000.00,   # 元
                "summary": "..."
            }]

        W1.3 双写期保持兼容, 让报表层无需改动.
        """
        return [
            {
                "account_code": l.account_code,
                "account_name": l.account_name,
                "debit": l.debit_fen / 100,
                "credit": l.credit_fen / 100,
                "summary": l.summary,
            }
            for l in lines
        ]
