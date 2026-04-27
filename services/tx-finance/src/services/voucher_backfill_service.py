"""历史凭证 entries JSONB → lines 子表回填服务 (W1.6)

Tier 级别: 🔴 Tier 1 (资金安全 / 金税四期链路)

背景:
  W1.1 (v266) 建立 financial_voucher_lines 子表作为分录 SSOT.
  W1.3 (service) 让新写入路径双写 entries + lines.
  但历史凭证 (v266 之前) 只有 entries JSONB, lines 表空. 导致:
    - is_balanced_from_lines() 对历史凭证返 True (0 == 0, 误判)
    - 科目总账查询 (ix_fvl_tenant_account) 漏掉历史数据
    - W2 计划 drop entries 时, 历史数据无处可去

  W1.6 一次性回填: 扫全表 financial_vouchers, 解析 entries JSONB,
  生成对应 lines 子表行. 幂等 (重跑不重复) + 批量 (不锁全表) + 多格式兼容.

entries JSONB 格式兼容:
  格式 A (W1.0 voucher_service.py 风格):
    {"direction": "debit|credit", "account_code", "amount_fen", "amount_yuan", "summary"}
  格式 B (W1.3 FinancialVoucherService 风格):
    {"account_code", "account_name", "debit": 100.00, "credit": 0, "summary"}
  格式 C (W1.5 红冲 _reverse_entries_jsonb 风格): 同 B
  解析器统一输出 (debit_fen, credit_fen) 二元组.

并发安全:
  - FOR UPDATE SKIP LOCKED: 多 worker 并行 backfill 不争锁
  - 每批独立事务 (避免 WAL 膨胀 + 主从延迟)
  - 幂等 pre-check: 已有 lines 的 voucher 跳过

失败容忍:
  - 单张凭证解析失败 → 记入 errors list 跳过, 不阻塞 batch
  - 借贷不平衡 → 默认跳过 + 告警 (可选 strict 模式 raise)
  - 零金额 entries → 跳过 (DB CHECK 拒)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.voucher import FinancialVoucher, FinancialVoucherLine  # type: ignore

log = structlog.get_logger(__name__)


@dataclass
class BackfillError:
    voucher_id: str
    voucher_no: str
    error: str


@dataclass
class BackfillReport:
    total_scanned: int = 0       # 本批扫了多少张凭证
    backfilled: int = 0           # 成功生成 lines 的凭证数
    skipped_existing: int = 0     # 已有 lines 跳过的
    skipped_empty: int = 0        # entries 为空或无有效分录的
    skipped_unbalanced: int = 0   # 借贷不平衡跳过的
    errors: list[BackfillError] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        return (
            f"scanned={self.total_scanned} "
            f"backfilled={self.backfilled} "
            f"skipped_existing={self.skipped_existing} "
            f"skipped_empty={self.skipped_empty} "
            f"skipped_unbalanced={self.skipped_unbalanced} "
            f"errors={len(self.errors)} "
            f"dry_run={self.dry_run}"
        )


class VoucherBackfillService:
    """历史 entries → lines 批量回填."""

    async def backfill_batch(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID | None = None,
        batch_size: int = 500,
        dry_run: bool = False,
        strict: bool = False,
    ) -> BackfillReport:
        """扫一批 (未回填的) 凭证, 生成 lines.

        Args:
            tenant_id: 限定租户 (None=全租户, 运维脚本用).
            batch_size: 单批凭证数. 默认 500, 大表可降到 100.
            dry_run: True 时只解析不 INSERT (预检用).
            strict: True 时单张凭证解析失败/借贷不平衡直接 raise.
                False (默认) 跳过 + 记 errors.

        Returns:
            BackfillReport 统计.
        """
        report = BackfillReport(dry_run=dry_run)

        # ── 扫一批未回填的凭证 (幂等 pre-check) ────────────────────
        # 关键: WHERE NOT EXISTS (lines) 防重复回填.
        # FOR UPDATE SKIP LOCKED: 并行 worker 不争锁.
        where_tenant = "AND fv.tenant_id = :tid" if tenant_id else ""
        query_sql = text(f"""
            SELECT fv.id, fv.tenant_id, fv.voucher_no, fv.entries
              FROM financial_vouchers fv
             WHERE jsonb_array_length(fv.entries) > 0
               AND NOT EXISTS (
                   SELECT 1 FROM financial_voucher_lines fvl
                    WHERE fvl.voucher_id = fv.id
               )
               {where_tenant}
             ORDER BY fv.created_at ASC
             LIMIT :n
             FOR UPDATE OF fv SKIP LOCKED
        """)
        params: dict[str, Any] = {"n": batch_size}
        if tenant_id is not None:
            params["tid"] = tenant_id

        result = await session.execute(query_sql, params)
        rows = result.mappings().all()
        report.total_scanned = len(rows)

        # ── 逐张解析 + 生成 lines ────────────────────────────────
        for row in rows:
            try:
                await self._backfill_one(
                    voucher_id=row["id"],
                    tenant_id=row["tenant_id"],
                    voucher_no=row["voucher_no"],
                    entries=row["entries"],
                    session=session,
                    report=report,
                    dry_run=dry_run,
                    strict=strict,
                )
            except Exception as exc:
                if strict:
                    raise
                report.errors.append(BackfillError(
                    voucher_id=str(row["id"]),
                    voucher_no=row["voucher_no"],
                    error=f"{type(exc).__name__}: {exc}",
                ))
                log.warning(
                    "voucher.backfill.row_error",
                    voucher_id=str(row["id"]),
                    voucher_no=row["voucher_no"],
                    error=str(exc),
                )

        if not dry_run:
            await session.flush()

        log.info("voucher.backfill.batch_done", **report.__dict__)
        return report

    async def _backfill_one(
        self,
        *,
        voucher_id: uuid.UUID,
        tenant_id: uuid.UUID,
        voucher_no: str,
        entries: list[dict[str, Any]],
        session: AsyncSession,
        report: BackfillReport,
        dry_run: bool,
        strict: bool,
    ) -> None:
        """单张凭证 entries → lines."""
        # 1. 解析 entries → (debit_fen, credit_fen) 二元组
        parsed = self._parse_entries_to_fen_pairs(entries, voucher_no)

        # 过滤零金额 (DB CHECK 会拒, 直接跳过)
        valid_parsed = [p for p in parsed if p["debit_fen"] > 0 or p["credit_fen"] > 0]
        if not valid_parsed:
            report.skipped_empty += 1
            return

        # 2. 借贷平衡校验 (凭证级)
        total_debit = sum(p["debit_fen"] for p in valid_parsed)
        total_credit = sum(p["credit_fen"] for p in valid_parsed)
        if total_debit != total_credit:
            msg = (
                f"借贷不平衡: debit_fen={total_debit} "
                f"!= credit_fen={total_credit}"
            )
            if strict:
                raise ValueError(msg)
            report.skipped_unbalanced += 1
            report.errors.append(BackfillError(
                voucher_id=str(voucher_id),
                voucher_no=voucher_no,
                error=msg,
            ))
            return

        # 3. 生成 lines (dry_run 时不 add)
        if not dry_run:
            for idx, p in enumerate(valid_parsed):
                line = FinancialVoucherLine(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    voucher_id=voucher_id,
                    line_no=idx + 1,
                    account_code=p["account_code"],
                    account_name=p["account_name"],
                    debit_fen=p["debit_fen"],
                    credit_fen=p["credit_fen"],
                    summary=p.get("summary") or None,
                )
                session.add(line)

        report.backfilled += 1

    # ── entries 解析 (多格式兼容) ─────────────────────────────────

    def _parse_entries_to_fen_pairs(
        self,
        entries: list[dict[str, Any]],
        voucher_no: str,
    ) -> list[dict[str, Any]]:
        """多格式 entries → [{account_code, account_name, debit_fen, credit_fen, summary}].

        兼容格式:
          A. {direction: 'debit'|'credit', amount_fen, account_code, ...}
             — W1.0 voucher_service.py 风格. amount_fen 是负时 (折扣) 视情况处理.
          B. {account_code, debit: float, credit: float, ...}
             — W1.3+ FinancialVoucherService 风格. 元单位.
          C. 混合: 不规范字段由 get() 兜底取 0.
        """
        parsed: list[dict[str, Any]] = []
        for e in entries:
            account_code = str(e.get("account_code") or "").strip()
            account_name = str(e.get("account_name") or "").strip()
            if not account_code:
                # 科目代码缺失 — 跳过该行
                continue

            # 格式 A: direction + amount_fen
            direction = e.get("direction")
            if direction in ("debit", "credit"):
                amount_fen_raw = e.get("amount_fen")
                if amount_fen_raw is None:
                    # amount_fen 缺, 回退 amount_yuan * 100
                    amount_yuan = e.get("amount_yuan")
                    if amount_yuan is None:
                        continue
                    amount_fen = round(float(amount_yuan) * 100)
                else:
                    amount_fen = int(amount_fen_raw)

                # 负金额 (W1.0 discount entries 里有): 对调方向
                # e.g. 折扣 credit=-1000 (减少收入) → debit=+1000
                if amount_fen < 0:
                    amount_fen = -amount_fen
                    direction = "credit" if direction == "debit" else "debit"

                if direction == "debit":
                    parsed.append({
                        "account_code": account_code,
                        "account_name": account_name or account_code,
                        "debit_fen": amount_fen,
                        "credit_fen": 0,
                        "summary": e.get("summary"),
                    })
                else:
                    parsed.append({
                        "account_code": account_code,
                        "account_name": account_name or account_code,
                        "debit_fen": 0,
                        "credit_fen": amount_fen,
                        "summary": e.get("summary"),
                    })
                continue

            # 格式 B: debit / credit 元字段
            debit = e.get("debit", 0)
            credit = e.get("credit", 0)
            try:
                debit_fen = round(float(debit) * 100) if debit else 0
                credit_fen = round(float(credit) * 100) if credit else 0
            except (TypeError, ValueError):
                continue  # 无法解析金额 — 跳过该行

            # 非法行: 都为 0 或都非零 (不满足 DB CHECK 互斥)
            if debit_fen == 0 and credit_fen == 0:
                continue
            if debit_fen > 0 and credit_fen > 0:
                # 格式 B 理论上不该出现, 但保守跳过
                continue
            # 负数 entries B 格式: 理论上不该出现 (W1.3 service 不产出)
            if debit_fen < 0 or credit_fen < 0:
                continue

            parsed.append({
                "account_code": account_code,
                "account_name": account_name or account_code,
                "debit_fen": debit_fen,
                "credit_fen": credit_fen,
                "summary": e.get("summary"),
            })

        return parsed
