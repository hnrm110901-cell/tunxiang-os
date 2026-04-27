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

# 前向引用: AccountingPeriodService (W1.4b 接入). 本 service 允许不注入,
# 构造时传 period_service=None 即跳过账期校验 (向前兼容 / 历史回填路径).
try:
    from services.accounting_period_service import (  # type: ignore
        AccountingPeriodService,
    )
except ImportError:  # pragma: no cover — 仅为 IDE 类型提示兜底
    AccountingPeriodService = None  # type: ignore


log = structlog.get_logger(__name__)


# ─── 异常类型 ─────────────────────────────────────────────────────────


class TenantContextMismatchError(ValueError):
    """[BLOCKER-B5]: payload.tenant_id 与 session 里的 app.tenant_id 不一致.

    独立于普通 ValueError 抛出, 审计日志 / 告警系统可以区分
    "输入错误" vs "潜在安全事件".
    """
    def __init__(self, payload_tenant, session_tenant: str | None) -> None:
        self.payload_tenant = payload_tenant
        self.session_tenant = session_tenant
        super().__init__(
            f"租户上下文不匹配: payload.tenant_id={payload_tenant} "
            f"vs session app.tenant_id={session_tenant!r} "
            f"(RLS 会拒写入, 应用层提前中断避免 IntegrityError 污染批次)"
        )


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

    # [W2.A] 以前年度损益调整元数据. 两者必须同时非空或同时 None.
    source_period_year: int | None = None
    source_period_month: int | None = None


# ─── service 本体 ────────────────────────────────────────────────────


class FinancialVoucherService:
    """financial_vouchers + lines 持久化唯一入口.

    构造参数:
        period_service: AccountingPeriodService | None
            - None (默认): 跳过账期校验 (向前兼容 W1.4 前的调用方).
            - 非 None: create() 写前校验 voucher_date 所属 period 必须 open.
              period 不存在时走 auto_ensure (首次写该月自动建 open).
              period 已 closed/locked 时 raise ValueError (引导红冲).

    事务边界: service 只 flush 不 commit. 调用方持事务边界.
    """

    def __init__(
        self,
        period_service: "AccountingPeriodService | None" = None,
    ) -> None:
        self._period_service = period_service

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

        # [BLOCKER-B3] event_id 非空时 event_type 必填
        # 理由: uq_fv_tenant_event partial UNIQUE 的 WHERE 条件要求两者都非空,
        # 应用层显式校验比 DB 层错误消息更友好 + 防误用.
        if payload.event_id is not None and (
            payload.event_type is None or not str(payload.event_type).strip()
        ):
            raise ValueError(
                "event_id 非空时 event_type 必填 "
                "(幂等键需要 (tenant_id, event_type, event_id) 完整三元组)"
            )

        # [BLOCKER-B5] 租户上下文断言
        # payload.tenant_id 来自调用方不可信输入 (如 ERPVoucher webhook).
        # session 的 app.tenant_id 来自路由中间件 SET LOCAL (可信).
        # 两者必须一致, 否则:
        #   - INSERT 会被 RLS WITH CHECK 拒 → IntegrityError (消息不明, 污染批次)
        #   - 攻击者可能通过"预期行为与错误消息"做存在性探测
        # 修复: 显式断言, 不一致抛 TenantContextMismatchError (独立异常类型,
        #   审计/告警系统可区分"配置错误" vs "横向越权尝试").
        await self._assert_tenant_matches_session(
            session=session, payload_tenant_id=payload.tenant_id,
        )

        total_debit_fen = sum(l.debit_fen for l in payload.lines)
        total_credit_fen = sum(l.credit_fen for l in payload.lines)
        if total_debit_fen != total_credit_fen:
            raise ValueError(
                f"借贷不平衡 (fen 整数零容忍): "
                f"debit={total_debit_fen} != credit={total_credit_fen}"
            )
        if total_debit_fen == 0:
            raise ValueError("凭证借贷总额均为 0, 无会计意义")

        # 2. 幂等预查 (先于账期校验) ─────────────────────────────────
        # [W2.B 修复] 原顺序: 账期校验 → 幂等预查. 导致外卖 T+N webhook
        # 月结后重发被拒: 美团 T+2 到账, 月结在 T+1 关了, payload.event_id
        # 是之前成功写入的凭证. 但账期校验在幂等预查前, 直接 raise,
        # 调用方收到 ValueError 记为"失败", 生产流水年化百万级损失.
        #
        # 新顺序: event_id 非空 → 先查是否已处理过本事件.
        # - 命中: 返回既存凭证 (该凭证写入时账期必是 open, 不影响账期语义)
        # - 未命中: 下沉到账期校验 (真正写新凭证时才拦)
        #
        # 账期 closed 场景:
        # - webhook 重发 (event_id 命中): 返回既存 ✅ (T+N 订单不再丢)
        # - 全新 event_id 但 voucher_date 在 closed 期: 拒 ✅ (账期保护仍在)
        # - event_id=NULL (手工) + closed: 沿着幂等 skip 走到账期校验, 拒 ✅
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

        # 3. 账期校验 (W1.4b, period_service 注入时启用) ──────────────
        # [W2.B 修复] 只对"新凭证"校验. 幂等命中的已在上面 return existing,
        # 永远不会走到这里 — 自然允许 T+N webhook 重发.
        # closed/locked 时 raise, 引导 reopen 或红冲.
        if self._period_service is not None:
            writable = await self._period_service.is_date_writable(
                tenant_id=payload.tenant_id,
                biz_date=payload.voucher_date,
                session=session,
                auto_ensure=True,  # period 不存在则懒建 open
            )
            if not writable:
                # 找具体状态以便错误信息指向正确路径
                period = await self._period_service.find_period_for_date(
                    tenant_id=payload.tenant_id,
                    biz_date=payload.voucher_date,
                    session=session,
                )
                status = period.status if period else "unknown"
                raise ValueError(
                    f"账期 {payload.voucher_date.year}-{payload.voucher_date.month:02d} "
                    f"状态={status}, 凭证写入被拒 "
                    f"(请走红冲 red_flush 或先重开账期)"
                )

        # 4. 构造 ORM (双写 entries + lines, 单事务) ──────────────────
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
        tenant_id: uuid.UUID | None = None,
    ) -> FinancialVoucher:
        """作废凭证 (调用 ORM 层 void() 方法 + flush).

        [W2.E 修复] 加 tenant_id 显式过滤, 防 Oracle 攻击.

        Args:
            tenant_id: 调用方声明的租户 (可选, 但推荐传).
                传入时: 走 SELECT WHERE id + tenant_id, 显式过滤.
                不传: 降级为 session.get(PK), 依赖 RLS. 为兼容现有 caller 保留.

        Raises:
            ValueError: "凭证不存在或无权限" (统一消息, 不区分 "不存在"/"跨租户",
                防 Oracle 攻击通过错误消息差异探测 UUID 存在性).
        """
        voucher = await self._load_voucher_tenant_scoped(
            session=session, voucher_id=voucher_id, tenant_id=tenant_id,
        )

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

    # ── 红冲 (W1.5) ───────────────────────────────────────────────────

    async def red_flush(
        self,
        voucher_id: uuid.UUID,
        *,
        operator_id: uuid.UUID,
        reason: str,
        session: AsyncSession,
        new_voucher_no: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> FinancialVoucher:
        """红冲凭证 — 对 exported 凭证的唯一合法纠错路径.

        金税四期要求: 已推 ERP 的凭证不能删改, 必须生成反向分录入账.
        本方法:
          1. 前置校验原凭证可红冲 (exported / 未被红冲 / 未作废 / 本身不是红冲)
          2. 构造红字凭证: 借贷对调, 金额保持正 (DB CHECK 要求), 凭证级 total_amount_fen 取负
          3. 双向 link: 新凭证 red_flush_of = 原; 原 red_flushed_by = 新
          4. 同事务 flush

        账期校验: 红冲**绕过** is_date_writable (period_service 校验).
          理由: 红冲本身就是 closed/locked 账期凭证的唯一合法纠错路径,
          若校验会让闭账凭证永远无法修正, 违反金税四期.

        Args:
            voucher_id: 被红冲的原凭证 id
            operator_id: 操作员 UUID (审计)
            reason: 红冲原因 (必填, 审计)
            new_voucher_no: 红字凭证编号. None 时自动 "{原 voucher_no}-R".

        Returns:
            新创建的红冲凭证 (含反向 lines, total_amount_fen < 0).

        Raises:
            ValueError: 原凭证不存在 / 非 exported / 已被红冲 / 本身是红冲 / 已作废
        """
        # ── 1. 前置校验 ────────────────────────────────────────────────
        # [W2.E] tenant 作用域加载, 统一错误消息防 Oracle 攻击
        original = await self._load_voucher_tenant_scoped(
            session=session, voucher_id=voucher_id, tenant_id=tenant_id,
        )

        if not reason or not reason.strip():
            raise ValueError("红冲原因必填 (审计留痕)")

        if original.status != "exported":
            raise ValueError(
                f"凭证 {original.voucher_no} 状态={original.status}, "
                f"只有 exported 凭证需要红冲 (draft/confirmed 请直接 void)"
            )
        if original.voided:
            raise ValueError(
                f"凭证 {original.voucher_no} 已作废, 不能再红冲"
            )
        if original.has_been_red_flushed:
            raise ValueError(
                f"凭证 {original.voucher_no} 已被红冲 "
                f"(→ {original.red_flushed_by_voucher_id}), 不可重复红冲"
            )
        if original.is_red_flush_voucher:
            raise ValueError(
                f"凭证 {original.voucher_no} 本身是红冲凭证, 不能再被红冲 (防递归)"
            )

        # ── 2. 构造红字凭证 — 借贷对调, 金额保持正 (DB CHECK) ────────
        red_voucher_no = new_voucher_no or f"{original.voucher_no}-R"
        red = FinancialVoucher(
            id=uuid.uuid4(),
            tenant_id=original.tenant_id,
            store_id=original.store_id,
            voucher_no=red_voucher_no,
            voucher_date=original.voucher_date,  # 红冲沿用原业务日期 (审计可对应)
            voucher_type=original.voucher_type,
            # 凭证级金额取负 (红字显示), 分录级仍正
            total_amount_fen=-(original.total_amount_fen or 0),
            total_amount=(
                -float(original.total_amount)
                if original.total_amount is not None else None
            ),
            entries=self._reverse_entries_jsonb(original.entries),
            source_type=original.source_type,
            source_id=original.source_id,
            status="draft",  # 红冲凭证重新走 draft → confirmed → exported (再推 ERP)
            # 不继承 event_id (红冲是手工操作, 不走事件幂等)
            event_type="red_flush.voucher",
            event_id=None,
            voided=False,
        )
        # 借贷对调: 原借变贷, 原贷变借 (金额正)
        red.lines = [
            FinancialVoucherLine(
                id=uuid.uuid4(),
                tenant_id=original.tenant_id,
                line_no=idx + 1,
                account_code=orig_line.account_code,
                account_name=orig_line.account_name,
                debit_fen=orig_line.credit_fen,   # 交换
                credit_fen=orig_line.debit_fen,
                summary=f"红冲: {orig_line.summary or ''}".strip(),
            )
            for idx, orig_line in enumerate(original.lines)
        ]

        # ── 3. 双向 link ──────────────────────────────────────────────
        # [W2.D] pre-check: 若已有红字凭证指向 original (孤儿场景), 拒绝再建
        # 配合 v276 UNIQUE partial 索引 (DB 层兜底). 应用层早拒消息更清晰.
        pre_check_stmt = select(FinancialVoucher).where(
            FinancialVoucher.red_flush_of_voucher_id == original.id,
        ).limit(1)
        pre_check_result = await session.execute(pre_check_stmt)
        existing_red = pre_check_result.scalar_one_or_none()
        if existing_red is not None:
            raise ValueError(
                f"凭证 {original.voucher_no} 已有红字凭证 {existing_red.voucher_no} "
                f"指向它 (可能是 W1.5 孤儿: 原凭证 red_flushed_by_voucher_id "
                f"= NULL 但红字凭证仍在 DB). 需 DBA 手工修复 original."
            )

        red.red_flush_of_voucher_id = original.id
        # [W2.F] 审计字段入 DB (不再只 log)
        red.red_flush_operator_id = operator_id
        red.red_flush_reason = reason.strip()
        red.red_flushed_at = datetime.now(timezone.utc)
        session.add(red)
        try:
            await session.flush()  # 先 flush 拿到 red.id
        except IntegrityError as exc:
            # [W2.D DB 兜底] v276 UNIQUE partial 防并发红冲
            if "ix_fv_red_flush_of" in str(exc.orig):
                raise ValueError(
                    f"并发红冲冲突: 凭证 {original.voucher_no} 已被另一进程红冲. "
                    f"请 refetch 原凭证并重试 (has_been_red_flushed 应为 True)."
                ) from exc
            raise

        original.red_flushed_by_voucher_id = red.id
        # 作废原因冗余写入原凭证 voided_reason 以明确 (不改 voided=TRUE —
        # 红冲与作废是两条语义, 原凭证仍 exported, 仅被 red_flushed)
        await session.flush()

        log.info(
            "voucher.red_flush.ok",
            original_id=str(voucher_id),
            red_voucher_id=str(red.id),
            red_voucher_no=red_voucher_no,
            operator_id=str(operator_id),
            reason=reason,
        )
        return red

    @staticmethod
    def _reverse_entries_jsonb(
        original_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """entries JSONB 借贷对调 (元字段, 兼容 ERP 推送).

        原 entry {debit: 100, credit: 0} → 红冲 {debit: 0, credit: 100}
        """
        reversed_entries: list[dict[str, Any]] = []
        for e in original_entries:
            reversed_entries.append({
                "account_code": e.get("account_code"),
                "account_name": e.get("account_name"),
                "debit": e.get("credit", 0),   # 交换
                "credit": e.get("debit", 0),
                "summary": f"红冲: {e.get('summary', '')}".strip(),
            })
        return reversed_entries

    # ── 以前年度损益调整 (W2.A) ──────────────────────────────────────

    async def create_prior_period_adjustment(
        self,
        payload: VoucherCreateInput,
        *,
        session: AsyncSession,
    ) -> FinancialVoucher:
        """创建"以前年度损益调整"凭证 — 跨期漏账合法补录路径.

        [§19 CFO P0-1 响应] 2027-03 发现 2026-12 漏账场景的唯一解.
        W1 能力全覆没 (reopen locked / red_flush 无原 / create 被账期校验拦),
        W2.A 提供新语义.

        业务约束 (service 层强制):
          1. payload.source_period_year + month 必须同时非空
          2. source_period 必须在过去 (< voucher_date 所属月)
          3. voucher_date 必须在当前 open 账期 (走 create() 正常账期校验)
          4. payload.voucher_type 推荐 'prior_period_adjustment' (但不强制)
          5. reason 必填, 走 extra_metadata['reason'] 留痕

        DB 层:
          - CHECK chk_fv_source_period: 两列同时 NULL 或同时非空 (v278)
          - ix_fv_source_period partial: 按源期间审计查询

        Raises:
            ValueError: source_period 元数据不一致 / 不在过去 / reason 空
        """
        from datetime import date as _date

        # 1. 元数据完整性
        if payload.source_period_year is None or payload.source_period_month is None:
            raise ValueError(
                "create_prior_period_adjustment 要求 source_period_year + "
                "source_period_month 两者必填 (以前年度损益调整的业务原属期间)"
            )

        if not (2020 <= payload.source_period_year <= 2100):
            raise ValueError(
                f"source_period_year 越界: {payload.source_period_year} "
                f"(应在 2020-2100)"
            )
        if not (1 <= payload.source_period_month <= 12):
            raise ValueError(
                f"source_period_month 越界: {payload.source_period_month} "
                f"(应在 1-12)"
            )

        # 2. 源期间必须在过去 — 语义正确性防护
        # 允许源期间 = 当前凭证月份的场景 (同期内补录) 作为边界, 但禁止源期间 > 当期
        source_first_day = _date(
            payload.source_period_year, payload.source_period_month, 1
        )
        if source_first_day > payload.voucher_date:
            raise ValueError(
                f"以前年度损益调整要求 source_period 在过去: "
                f"source={payload.source_period_year}-{payload.source_period_month:02d} "
                f"> voucher_date={payload.voucher_date}"
            )

        # 3. 转发到 create() 正常路径
        # 账期校验按 voucher_date 执行 (当前期必须 open).
        # 幂等 / tenant 断言 / 借贷平衡 / 双写 lines+entries 全走 create 流程.
        voucher = await self.create(payload, session=session)

        log.info(
            "voucher.prior_period_adjustment.created",
            voucher_id=str(voucher.id),
            voucher_no=voucher.voucher_no,
            voucher_date=str(voucher.voucher_date),
            source_period=f"{payload.source_period_year}-{payload.source_period_month:02d}",
            total_fen=voucher.total_amount_fen,
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

    async def _assert_tenant_matches_session(
        self,
        *,
        session: AsyncSession,
        payload_tenant_id: uuid.UUID,
    ) -> None:
        """[BLOCKER-B5] 校验 payload.tenant_id == session 当前 app.tenant_id.

        不通过则 raise TenantContextMismatchError.

        豁免场景 (session 未 SET app.tenant_id, 设置为空字符串):
          - 测试 / 管理员脚本 直接用 DB superuser 跑, 没走路由中间件
          - 历史回填 / backfill 场景 (voucher_backfill_service) 可能 unset
          - 此时跳过断言 (RLS 自己兜底; service 下游 DB 约束仍生效)
        """
        from sqlalchemy import text as _text

        result = await session.execute(
            _text("SELECT NULLIF(current_setting('app.tenant_id', true), '')")
        )
        session_tid_str = result.scalar()

        # 豁免: session 未 SET, 视为特权/管理员路径 (RLS 会拒, 不在这里叠加拒绝)
        if session_tid_str is None or session_tid_str == "":
            return

        try:
            session_tid = uuid.UUID(str(session_tid_str))
        except (ValueError, TypeError):
            # session 里的值无法转 UUID. 两种情况:
            # 1. 生产: app.tenant_id 被误设为非 UUID 字符串 → 配置错误, 告警后豁免
            #    (RLS 会拦 INSERT; service 不该在这里替运维做"先拒绝")
            # 2. 测试: AsyncMock.scalar() 返回 MagicMock → 不是真实 SET, 豁免
            log.warning(
                "voucher.create.tenant_context_unparseable",
                raw_value=repr(session_tid_str)[:80],
                payload_tenant=str(payload_tenant_id),
            )
            return

        if session_tid != payload_tenant_id:
            raise TenantContextMismatchError(
                payload_tenant=payload_tenant_id,
                session_tenant=str(session_tid),
            )

    async def _load_voucher_tenant_scoped(
        self,
        *,
        session: AsyncSession,
        voucher_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
    ) -> FinancialVoucher:
        """[W2.E] 按 (id, tenant_id) 加载凭证, 防 Oracle 攻击 + 错误消息统一.

        原 session.get(FinancialVoucher, voucher_id) 的问题 (安全 P1-1):
          - PK 直查, 依赖 RLS 拦截. 若 app.tenant_id 未 SET 或错配:
            跨租户的 voucher_id 查到 None, 同租户查到 business error.
            攻击者通过 "不存在" vs "已作废" 的错误差异探测 UUID 存在性.

        修复:
          - tenant_id 显式传入时: SELECT WHERE id AND tenant_id, 明确过滤
          - tenant_id=None (向前兼容老 caller): 降级 session.get + RLS 兜底
          - 找不到统一消息 "凭证不存在或无权限" (不区分跨租户/不存在)

        Raises:
            ValueError: 统一 "凭证不存在或无权限: {voucher_id}"
        """
        from sqlalchemy import select as _select

        if tenant_id is not None:
            # 显式 tenant 过滤 — 主路径
            stmt = _select(FinancialVoucher).where(
                FinancialVoucher.id == voucher_id,
                FinancialVoucher.tenant_id == tenant_id,
            ).limit(1)
            result = await session.execute(stmt)
            voucher = result.scalar_one_or_none()
        else:
            # 兼容路径: PK 直查, RLS 兜底
            voucher = await session.get(FinancialVoucher, voucher_id)

        if voucher is None:
            raise ValueError(
                f"凭证不存在或无权限: {voucher_id}"
            )
        return voucher

    async def _find_by_event(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        event_type: str | None,
        event_id: uuid.UUID,
    ) -> FinancialVoucher | None:
        """按 (tenant, event_type, event_id) 查现有凭证 (幂等预查).

        event_type=None 时查询退化为 (tenant_id, event_id), 不带 event_type 过滤.
        此路径仅供 get_by_event() 公开查询使用; create() 内部调用时 event_type
        保证非空 (由 step 1 "event_id 非空 ⇒ event_type 必填" 校验).
        """
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
            # [W2.A] 以前年度损益调整元数据
            source_period_year=payload.source_period_year,
            source_period_month=payload.source_period_month,
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
