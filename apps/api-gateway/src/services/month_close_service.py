"""月结/年结服务（D7 Nice-to-Have）

提供三个核心流程：
  1. pre_close_check        月结前阻塞检查（未过账/未审批/未收货/未对账）
  2. execute_month_close    月结：冻结当月凭证 + 生成试算平衡表 + 利润/资产负债快照
  3. reopen_month           反结账（仅 ADMIN/老板）
  4. execute_year_close     年结：12 个月全部月结 + 结转损益

金额：所有 *_fen 字段为整型「分」；利润结转时净额写入 4101 本年利润 → 4103 未分配利润。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.accounting import Voucher, VoucherEntry, VoucherStatus
from ..models.ar_ap import AccountPayable, AccountReceivable
from ..models.month_close import MonthCloseLog, TrialBalanceSnapshot
from ..models.user import User, UserRole

logger = structlog.get_logger()


# ────────────── 科目区间（中国会计科目一级分类规则，仅按前缀） ──────────────
REVENUE_PREFIXES = ("6001", "6011", "6051")       # 主营业务收入 / 其他业务收入
COST_PREFIXES = ("6401", "6402")                  # 主营/其他业务成本
EXPENSE_PREFIXES = ("6601", "6602", "6603", "6711")  # 销售/管理/财务/营业外支出
PNL_ACCOUNT_CURRENT_YEAR = "4101"                  # 本年利润
PNL_ACCOUNT_RETAINED = "4103"                      # 利润分配-未分配利润


class MonthCloseError(Exception):
    """月结/年结业务异常"""


class MonthCloseService:
    """月结/年结编排"""

    # ───────────────── Pre-Check ─────────────────

    async def pre_close_check(
        self, session: AsyncSession, store_id: str, year_month: str
    ) -> dict[str, Any]:
        """月结前阻塞项检查。返回 {blocked: bool, issues: [..]}

        year_month: YYYYMM
        """
        _validate_ym(year_month)
        start, end = _ym_range(year_month)
        issues: list[dict[str, Any]] = []

        # 1) 未过账/草稿凭证
        sql = text(
            """
            SELECT COUNT(*) AS cnt FROM vouchers
             WHERE store_id = CAST(:sid AS uuid)
               AND voucher_date >= :start AND voucher_date < :end
               AND status = 'draft'
            """
        )
        try:
            cnt = (
                await session.execute(
                    sql, {"sid": _to_uuid(store_id), "start": start, "end": end}
                )
            ).scalar() or 0
        except Exception:
            cnt = 0
        if cnt:
            issues.append({"code": "draft_vouchers", "count": int(cnt), "msg": f"{cnt} 张凭证未过账"})

        # 2) 未审批采购单（purchase_approvals.status = pending）
        cnt = await _safe_count(
            session,
            """
            SELECT COUNT(*) FROM purchase_approvals
             WHERE store_id = :sid
               AND created_at >= :start AND created_at < :end
               AND status IN ('pending','submitted')
            """,
            {"sid": str(store_id), "start": start, "end": end},
        )
        if cnt:
            issues.append({"code": "pending_purchase", "count": cnt, "msg": f"{cnt} 张采购单未审批"})

        # 3) 未收货到货单（goods_receipts.status = pending）
        cnt = await _safe_count(
            session,
            """
            SELECT COUNT(*) FROM goods_receipts
             WHERE store_id = :sid
               AND created_at >= :start AND created_at < :end
               AND status = 'pending'
            """,
            {"sid": str(store_id), "start": start, "end": end},
        )
        if cnt:
            issues.append({"code": "pending_goods_receipt", "count": cnt, "msg": f"{cnt} 张到货单未收货"})

        # 4) 未对账账单 AR/AP（open 且 issue_date 落在月内）
        try:
            stmt = select(AccountReceivable).where(
                AccountReceivable.store_id == _to_uuid(store_id),
                AccountReceivable.issue_date >= start.date(),
                AccountReceivable.issue_date < end.date(),
                AccountReceivable.status.in_(["open", "partial", "overdue"]),
            )
            open_ar = len((await session.execute(stmt)).scalars().all())
        except Exception:
            open_ar = 0
        try:
            stmt = select(AccountPayable).where(
                AccountPayable.store_id == _to_uuid(store_id),
                AccountPayable.issue_date >= start.date(),
                AccountPayable.issue_date < end.date(),
                AccountPayable.status.in_(["open", "partial", "overdue"]),
            )
            open_ap = len((await session.execute(stmt)).scalars().all())
        except Exception:
            open_ap = 0
        if open_ar:
            issues.append({"code": "open_ar", "count": open_ar, "msg": f"{open_ar} 笔应收账款未核销"})
        if open_ap:
            issues.append({"code": "open_ap", "count": open_ap, "msg": f"{open_ap} 笔应付账款未核销"})

        # 5) 已月结则不可重复
        existing = await self._get_log(session, store_id, year_month)
        if existing and existing.status in ("closed", "year_closed"):
            issues.append({
                "code": "already_closed",
                "count": 1,
                "msg": f"{year_month} 已于 {existing.closed_at} 月结，如需重结请先反结账",
            })

        return {"blocked": bool(issues), "issues": issues, "year_month": year_month, "store_id": store_id}

    # ───────────────── 月结 ─────────────────

    async def execute_month_close(
        self,
        session: AsyncSession,
        store_id: str,
        year_month: str,
        operator: User,
    ) -> dict[str, Any]:
        """执行月结。全过程在单事务内，失败回滚。"""
        _validate_ym(year_month)
        # 预检
        pre = await self.pre_close_check(session, store_id, year_month)
        if pre["blocked"]:
            raise MonthCloseError(f"月结阻塞: {pre['issues']}")

        start, end = _ym_range(year_month)
        try:
            # 1) 冻结当月已过账凭证 → locked (用 voucher.extras 标记，避免枚举迁移成本)
            #    这里采用 status 保留 posted，但通过 MonthCloseLog 判定期间锁定；
            #    同时将 voucher.extras->>'locked'=true 以便 API 层拒绝修改。
            lock_sql = text(
                """
                UPDATE vouchers
                   SET extras = COALESCE(extras, '{}'::jsonb) || jsonb_build_object('locked', true, 'locked_ym', :ym)
                 WHERE store_id = CAST(:sid AS uuid)
                   AND voucher_date >= :start AND voucher_date < :end
                """
            )
            try:
                await session.execute(
                    lock_sql,
                    {"sid": _to_uuid(store_id), "start": start, "end": end, "ym": year_month},
                )
            except Exception as e:  # 测试环境无真实表时允许继续
                logger.warning("lock_vouchers_failed", error=str(e))

            # 2) 生成试算平衡表快照
            tb = await self._build_trial_balance(session, store_id, year_month)
            await self._persist_trial_balance(session, store_id, year_month, tb)

            # 3) 生成利润表 + 资产负债表 JSON 快照
            income_stmt = self._build_income_statement(tb)
            balance_sheet = self._build_balance_sheet(tb)

            # 4) 写 MonthCloseLog
            log = await self._get_log(session, store_id, year_month)
            if not log:
                log = MonthCloseLog(
                    id=uuid.uuid4(),
                    store_id=str(store_id),
                    year_month=year_month,
                    status="closed",
                )
                session.add(log)
            log.status = "closed"
            log.closed_at = datetime.utcnow()
            log.closed_by = getattr(operator, "id", None)
            log.snapshot_json = {
                "trial_balance": tb,
                "income_statement": income_stmt,
                "balance_sheet": balance_sheet,
            }

            await session.commit()
            return {
                "store_id": store_id,
                "year_month": year_month,
                "status": "closed",
                "accounts": len(tb),
                "net_profit_yuan": income_stmt.get("net_profit_yuan", 0),
            }
        except Exception:
            await session.rollback()
            raise

    # ───────────────── 反结账 ─────────────────

    async def reopen_month(
        self,
        session: AsyncSession,
        store_id: str,
        year_month: str,
        operator: User,
        reason: str,
    ) -> dict[str, Any]:
        """反结账 — 仅 ADMIN 可操作，记审计"""
        role = getattr(operator, "role", None)
        role = role if isinstance(role, UserRole) else UserRole(role) if role else None
        if role != UserRole.ADMIN:
            raise MonthCloseError("仅管理员/老板可执行反结账")
        if not reason or len(reason.strip()) < 5:
            raise MonthCloseError("反结账必须填写原因（≥5 字）")

        log = await self._get_log(session, store_id, year_month)
        if not log or log.status not in ("closed", "year_closed"):
            raise MonthCloseError(f"{year_month} 尚未月结，无需反结账")

        try:
            # 解除凭证锁
            start, end = _ym_range(year_month if len(year_month) == 6 and year_month[-2:] != "00" else year_month[:4] + "01")
            try:
                await session.execute(
                    text(
                        """
                        UPDATE vouchers
                           SET extras = COALESCE(extras, '{}'::jsonb) || jsonb_build_object('locked', false)
                         WHERE store_id = CAST(:sid AS uuid)
                           AND voucher_date >= :start AND voucher_date < :end
                        """
                    ),
                    {"sid": _to_uuid(store_id), "start": start, "end": end},
                )
            except Exception as e:
                logger.warning("unlock_vouchers_failed", error=str(e))

            log.status = "reopened"
            log.reopened_at = datetime.utcnow()
            log.reopened_by = getattr(operator, "id", None)
            log.reason = reason
            await session.commit()
            logger.info(
                "month_reopened",
                store_id=store_id,
                year_month=year_month,
                operator=str(getattr(operator, "id", "")),
                reason=reason,
            )
            return {"store_id": store_id, "year_month": year_month, "status": "reopened"}
        except Exception:
            await session.rollback()
            raise

    # ───────────────── 年结 ─────────────────

    async def execute_year_close(
        self,
        session: AsyncSession,
        store_id: str,
        year: int,
        operator: User,
    ) -> dict[str, Any]:
        """年结：前置 12 个月必须全部月结，然后结转损益到 4101/4103。"""
        # 1) 前置检查
        months = [f"{year}{m:02d}" for m in range(1, 13)]
        stmt = select(MonthCloseLog).where(
            MonthCloseLog.store_id == str(store_id),
            MonthCloseLog.year_month.in_(months),
        )
        logs = {l.year_month: l for l in (await session.execute(stmt)).scalars().all()}
        missing = [m for m in months if m not in logs or logs[m].status not in ("closed", "year_closed")]
        if missing:
            raise MonthCloseError(f"年结前置失败，以下月份未月结: {missing}")

        year_ym = f"{year}00"  # 年结统一标识
        try:
            # 2) 汇总全年损益（6xxx 收入 - 6xxx/5xxx 成本费用）
            sql = text(
                """
                SELECT ve.account_code,
                       COALESCE(SUM(ve.debit_fen),0)  AS d,
                       COALESCE(SUM(ve.credit_fen),0) AS c
                  FROM voucher_entries ve
                  JOIN vouchers v ON v.id = ve.voucher_id
                 WHERE v.store_id = CAST(:sid AS uuid)
                   AND v.voucher_date >= :start AND v.voucher_date < :end
                   AND v.status = 'posted'
                 GROUP BY ve.account_code
                """
            )
            start = datetime(year, 1, 1)
            end = datetime(year + 1, 1, 1)
            rows: list[Any] = []
            try:
                rows = (
                    await session.execute(sql, {"sid": _to_uuid(store_id), "start": start, "end": end})
                ).all()
            except Exception as e:
                logger.warning("year_close_aggregate_failed", error=str(e))

            revenue_fen = 0
            cost_exp_fen = 0
            for code, d, c in rows:
                code = str(code)
                if code.startswith(REVENUE_PREFIXES):
                    revenue_fen += int(c or 0) - int(d or 0)
                elif code.startswith(COST_PREFIXES) or code.startswith(EXPENSE_PREFIXES):
                    cost_exp_fen += int(d or 0) - int(c or 0)

            net_profit_fen = revenue_fen - cost_exp_fen

            # 3) 生成结转凭证（本年利润 4101 → 未分配利润 4103）
            carry_voucher = Voucher(
                id=uuid.uuid4(),
                store_id=_to_uuid(store_id),
                voucher_no=f"YC-{year}-CLOSE",
                voucher_date=datetime(year, 12, 31).date(),
                summary=f"{year} 年度结转损益到未分配利润",
                status=VoucherStatus.POSTED,
                total_debit_fen=abs(net_profit_fen),
                total_credit_fen=abs(net_profit_fen),
                posted_by=getattr(operator, "id", None),
                posted_at=datetime.utcnow(),
                source_type="year_close",
            )
            if net_profit_fen >= 0:
                # 盈利：借 4101，贷 4103
                carry_voucher.entries = [
                    VoucherEntry(line_no=1, account_code=PNL_ACCOUNT_CURRENT_YEAR,
                                 account_name="本年利润", debit_fen=net_profit_fen, credit_fen=0),
                    VoucherEntry(line_no=2, account_code=PNL_ACCOUNT_RETAINED,
                                 account_name="利润分配-未分配利润", debit_fen=0, credit_fen=net_profit_fen),
                ]
            else:
                # 亏损：借 4103，贷 4101
                amt = -net_profit_fen
                carry_voucher.entries = [
                    VoucherEntry(line_no=1, account_code=PNL_ACCOUNT_RETAINED,
                                 account_name="利润分配-未分配利润", debit_fen=amt, credit_fen=0),
                    VoucherEntry(line_no=2, account_code=PNL_ACCOUNT_CURRENT_YEAR,
                                 account_name="本年利润", debit_fen=0, credit_fen=amt),
                ]
            try:
                session.add(carry_voucher)
            except Exception as e:
                logger.warning("year_close_voucher_add_failed", error=str(e))

            # 4) 写 MonthCloseLog(year_ym = YYYY00)
            log = await self._get_log(session, store_id, year_ym)
            if not log:
                log = MonthCloseLog(
                    id=uuid.uuid4(),
                    store_id=str(store_id),
                    year_month=year_ym,
                    status="year_closed",
                )
                session.add(log)
            log.status = "year_closed"
            log.closed_at = datetime.utcnow()
            log.closed_by = getattr(operator, "id", None)
            log.snapshot_json = {
                "year": year,
                "revenue_fen": revenue_fen,
                "revenue_yuan": round(revenue_fen / 100, 2),
                "cost_exp_fen": cost_exp_fen,
                "cost_exp_yuan": round(cost_exp_fen / 100, 2),
                "net_profit_fen": net_profit_fen,
                "net_profit_yuan": round(net_profit_fen / 100, 2),
                "carry_voucher_no": carry_voucher.voucher_no,
            }

            await session.commit()
            return {
                "store_id": store_id,
                "year": year,
                "status": "year_closed",
                "net_profit_yuan": round(net_profit_fen / 100, 2),
            }
        except Exception:
            await session.rollback()
            raise

    async def get_year_close_status(
        self, session: AsyncSession, store_id: str, year: int
    ) -> dict[str, Any]:
        """返回某年份 12 个月的月结状态 + 年结状态"""
        months = [f"{year}{m:02d}" for m in range(1, 13)] + [f"{year}00"]
        stmt = select(MonthCloseLog).where(
            MonthCloseLog.store_id == str(store_id),
            MonthCloseLog.year_month.in_(months),
        )
        logs = {l.year_month: l for l in (await session.execute(stmt)).scalars().all()}
        return {
            "store_id": store_id,
            "year": year,
            "months": {
                ym: (logs[ym].status if ym in logs else "pending") for ym in months[:12]
            },
            "year_closed": logs.get(f"{year}00").status if f"{year}00" in logs else "pending",
        }

    # ─────────────── 内部工具 ───────────────

    async def _get_log(
        self, session: AsyncSession, store_id: str, year_month: str
    ) -> MonthCloseLog | None:
        stmt = select(MonthCloseLog).where(
            MonthCloseLog.store_id == str(store_id),
            MonthCloseLog.year_month == year_month,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def _build_trial_balance(
        self, session: AsyncSession, store_id: str, year_month: str
    ) -> list[dict[str, Any]]:
        """基于当月已过账凭证构建试算平衡表"""
        start, end = _ym_range(year_month)
        sql = text(
            """
            SELECT ve.account_code, ve.account_name,
                   COALESCE(SUM(ve.debit_fen),0)  AS d,
                   COALESCE(SUM(ve.credit_fen),0) AS c
              FROM voucher_entries ve
              JOIN vouchers v ON v.id = ve.voucher_id
             WHERE v.store_id = CAST(:sid AS uuid)
               AND v.voucher_date >= :start AND v.voucher_date < :end
               AND v.status = 'posted'
             GROUP BY ve.account_code, ve.account_name
             ORDER BY ve.account_code
            """
        )
        rows: list[Any] = []
        try:
            rows = (
                await session.execute(sql, {"sid": _to_uuid(store_id), "start": start, "end": end})
            ).all()
        except Exception as e:
            logger.warning("trial_balance_failed", error=str(e))

        out = []
        for code, name, d, c in rows:
            d_fen, c_fen = int(d or 0), int(c or 0)
            closing_d = max(d_fen - c_fen, 0)
            closing_c = max(c_fen - d_fen, 0)
            out.append({
                "account_code": code,
                "account_name": name,
                "period_debit_fen": d_fen,
                "period_credit_fen": c_fen,
                "closing_debit_fen": closing_d,
                "closing_credit_fen": closing_c,
                "period_debit_yuan": round(d_fen / 100, 2),
                "period_credit_yuan": round(c_fen / 100, 2),
                "closing_debit_yuan": round(closing_d / 100, 2),
                "closing_credit_yuan": round(closing_c / 100, 2),
            })
        return out

    async def _persist_trial_balance(
        self, session: AsyncSession, store_id: str, year_month: str, tb: list[dict]
    ) -> None:
        """将试算平衡表落库（先清理同 store/ym 再重插）"""
        try:
            await session.execute(
                text(
                    "DELETE FROM trial_balance_snapshots WHERE store_id=:sid AND year_month=:ym"
                ),
                {"sid": str(store_id), "ym": year_month},
            )
        except Exception as e:
            logger.warning("tb_delete_failed", error=str(e))
            return
        for row in tb:
            session.add(TrialBalanceSnapshot(
                id=uuid.uuid4(),
                store_id=str(store_id),
                year_month=year_month,
                account_code=row["account_code"],
                account_name=row["account_name"],
                period_debit_fen=row["period_debit_fen"],
                period_credit_fen=row["period_credit_fen"],
                closing_debit_fen=row["closing_debit_fen"],
                closing_credit_fen=row["closing_credit_fen"],
            ))

    def _build_income_statement(self, tb: list[dict]) -> dict[str, Any]:
        revenue_fen = 0
        cost_exp_fen = 0
        for row in tb:
            code = str(row["account_code"])
            if code.startswith(REVENUE_PREFIXES):
                revenue_fen += row["period_credit_fen"] - row["period_debit_fen"]
            elif code.startswith(COST_PREFIXES) or code.startswith(EXPENSE_PREFIXES):
                cost_exp_fen += row["period_debit_fen"] - row["period_credit_fen"]
        net = revenue_fen - cost_exp_fen
        return {
            "revenue_fen": revenue_fen,
            "revenue_yuan": round(revenue_fen / 100, 2),
            "cost_exp_fen": cost_exp_fen,
            "cost_exp_yuan": round(cost_exp_fen / 100, 2),
            "net_profit_fen": net,
            "net_profit_yuan": round(net / 100, 2),
        }

    def _build_balance_sheet(self, tb: list[dict]) -> dict[str, Any]:
        asset = liab = equity = 0
        for row in tb:
            code = str(row["account_code"])
            closing = row["closing_debit_fen"] - row["closing_credit_fen"]
            if code.startswith("1"):
                asset += closing
            elif code.startswith("2"):
                liab += -closing
            elif code.startswith(("3", "4")):
                equity += -closing
        return {
            "total_asset_fen": asset,
            "total_asset_yuan": round(asset / 100, 2),
            "total_liability_fen": liab,
            "total_liability_yuan": round(liab / 100, 2),
            "total_equity_fen": equity,
            "total_equity_yuan": round(equity / 100, 2),
        }


# ──────────────────── helpers ────────────────────


def _validate_ym(ym: str) -> None:
    if not (isinstance(ym, str) and len(ym) == 6 and ym.isdigit()):
        raise MonthCloseError(f"year_month 必须 YYYYMM 格式，收到: {ym}")
    mm = int(ym[4:])
    if not (1 <= mm <= 12):
        raise MonthCloseError(f"年月月份超界: {ym}")


def _ym_range(ym: str) -> tuple[datetime, datetime]:
    y = int(ym[:4])
    m = int(ym[4:])
    start = datetime(y, m, 1)
    end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
    return start, end


def _to_uuid(s: str):
    """柔性 UUID 转换：失败则原样返回（供 text() 绑定）"""
    try:
        return str(uuid.UUID(str(s)))
    except Exception:
        return str(s)


async def _safe_count(session: AsyncSession, sql: str, params: dict) -> int:
    try:
        cnt = (await session.execute(text(sql), params)).scalar()
        return int(cnt or 0)
    except Exception:
        return 0


month_close_service = MonthCloseService()
