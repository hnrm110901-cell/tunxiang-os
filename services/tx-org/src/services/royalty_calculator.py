"""分润计算器

核心职责：
1. 阶梯分润计算（类似个税累进）
2. 月度账单批处理（查询、汇总、写入、逾期标记）
3. 加盟商看板数据汇总
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog

from ..models.franchise import (
    Franchisee,
    RoyaltyBill,
)

logger = structlog.get_logger(__name__)

# 欠款超过此天数标记为 overdue
OVERDUE_DAYS = 60


class FranchiseeDashboard:
    """加盟商经营看板"""

    def __init__(
        self,
        franchisee_id: UUID,
        current_month: str,
        current_month_revenue_fen: int,
        prev_month_revenue_fen: int,
        prev_year_month_revenue_fen: int,
        pending_due_fen: int,
        store_count: int,
        active_store_count: int,
        recent_audit_scores: List[float],
    ) -> None:
        self.franchisee_id = franchisee_id
        self.current_month = current_month
        self.current_month_revenue_fen = current_month_revenue_fen
        self.prev_month_revenue_fen = prev_month_revenue_fen
        self.prev_year_month_revenue_fen = prev_year_month_revenue_fen
        self.pending_due_fen = pending_due_fen
        self.store_count = store_count
        self.active_store_count = active_store_count
        self.recent_audit_scores = recent_audit_scores

    def mom_pct(self) -> Optional[float]:
        """月环比增长率（%）"""
        if self.prev_month_revenue_fen == 0:
            return None
        return round(
            (self.current_month_revenue_fen - self.prev_month_revenue_fen)
            / self.prev_month_revenue_fen
            * 100,
            2,
        )

    def yoy_pct(self) -> Optional[float]:
        """月同比增长率（%）"""
        if self.prev_year_month_revenue_fen == 0:
            return None
        return round(
            (self.current_month_revenue_fen - self.prev_year_month_revenue_fen)
            / self.prev_year_month_revenue_fen
            * 100,
            2,
        )

    def avg_audit_score(self) -> Optional[float]:
        if not self.recent_audit_scores:
            return None
        return round(sum(self.recent_audit_scores) / len(self.recent_audit_scores), 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "franchisee_id": str(self.franchisee_id),
            "current_month": self.current_month,
            "current_month_revenue_fen": self.current_month_revenue_fen,
            "prev_month_revenue_fen": self.prev_month_revenue_fen,
            "prev_year_month_revenue_fen": self.prev_year_month_revenue_fen,
            "mom_pct": self.mom_pct(),
            "yoy_pct": self.yoy_pct(),
            "pending_due_fen": self.pending_due_fen,
            "store_count": self.store_count,
            "active_store_count": self.active_store_count,
            "recent_audit_scores": self.recent_audit_scores,
            "avg_audit_score": self.avg_audit_score(),
        }


class RoyaltyCalculator:
    """分润计算器（无状态，所有方法均为纯函数或静态方法）"""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  核心计算：阶梯分润
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def calculate(monthly_revenue: float, franchisee: Franchisee) -> float:
        """计算月度分润金额。

        无阶梯：royalty = revenue × royalty_rate
        有阶梯：按区间分段累进（类似个税）

        阶梯示例（按 min_revenue 升序）：
          [{"min_revenue": 0,      "rate": 0.05},
           {"min_revenue": 100000, "rate": 0.04},
           {"min_revenue": 500000, "rate": 0.03}]

        营业额 200,000 时：
          - [0, 100000)     → 100,000 × 0.05 = 5,000
          - [100000, 200000)→ 100,000 × 0.04 = 4,000
          合计 = 9,000
        """
        if monthly_revenue <= 0:
            return 0.0

        tiers = franchisee.sorted_tiers()

        # 无阶梯配置：直接用基础费率
        if not tiers:
            return round(monthly_revenue * franchisee.royalty_rate, 2)

        # 确保第一个阶梯从 0 开始（若配置未覆盖0则用基础费率补齐）
        # 若首档 min_revenue > 0，则 [0, tiers[0].min_revenue) 使用基础费率
        royalty = 0.0
        prev_threshold = 0.0

        for i, tier in enumerate(tiers):
            if tier.min_revenue >= monthly_revenue:
                # 本档起点已超过营业额，本档之前的区间已全部处理完毕
                break

            # 若首档 min_revenue > 0，先用基础费率计算空缺区间
            if i == 0 and tier.min_revenue > 0:
                gap = min(tier.min_revenue, monthly_revenue)
                royalty += gap * franchisee.royalty_rate
                prev_threshold = tier.min_revenue
                if monthly_revenue <= tier.min_revenue:
                    break

            # 当前档区间：[tier.min_revenue, next_tier.min_revenue) 或 [tier.min_revenue, revenue)
            next_threshold = tiers[i + 1].min_revenue if i + 1 < len(tiers) else monthly_revenue
            segment_upper = min(next_threshold, monthly_revenue)
            segment = segment_upper - tier.min_revenue

            if segment > 0:
                royalty += segment * tier.rate

            prev_threshold = segment_upper

        # 若营业额超出最后一档，最后一档费率延续
        if prev_threshold < monthly_revenue and tiers:
            last_tier = tiers[-1]
            royalty += (monthly_revenue - prev_threshold) * last_tier.rate

        return round(royalty, 2)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  月度账单批处理
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def generate_monthly_bills(
        tenant_id: UUID,
        bill_month: str,
        db: Any,
    ) -> List[RoyaltyBill]:
        """月度账单批处理。

        步骤：
        1. 查询 tenant 下所有 active 加盟商
        2. 汇总各加盟商旗下门店的当月营业额
        3. 调用 calculate() 得出分润金额
        4. 写入 royalty_bills（已存在则跳过）
        5. 欠款超 60 天标记 overdue

        参数：
            tenant_id  — 集团 tenant_id
            bill_month — 账单月份，格式 "YYYY-MM"
            db         — 数据库连接

        返回已生成的账单列表。
        """
        log = logger.bind(tenant_id=str(tenant_id), bill_month=bill_month)
        log.info("franchise.generate_monthly_bills.start")

        year, month = int(bill_month[:4]), int(bill_month[5:7])
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])

        # Step 1: 查询所有 active 加盟商
        active_franchisees: List[Franchisee] = await RoyaltyCalculator._fetch_active_franchisees(
            tenant_id, db
        )

        bills: List[RoyaltyBill] = []
        today = date.today()

        for franchisee in active_franchisees:
            # Step 2: 汇总该加盟商门店当月营业额
            store_ids = await RoyaltyCalculator._fetch_franchisee_store_ids(
                franchisee.id, tenant_id, db
            )
            total_revenue_fen: int = await RoyaltyCalculator._sum_store_revenue_fen(
                store_ids, period_start, period_end, tenant_id, db
            )
            total_revenue = total_revenue_fen / 100.0

            # Step 3: 计算分润
            royalty_amount = RoyaltyCalculator.calculate(total_revenue, franchisee)
            royalty_amount_fen = int(round(royalty_amount * 100))
            management_fee_fen = franchisee.management_fee_fen  # type: ignore[attr-defined]
            total_due_fen = royalty_amount_fen + management_fee_fen

            # Step 4: 构建账单
            due_date = RoyaltyCalculator._calc_due_date(bill_month)

            # 检查是否已存在该加盟商本期账单，避免重复生成
            existing_id = await RoyaltyCalculator._find_existing_bill(
                tenant_id, franchisee.id, period_start, period_end, db
            )
            if existing_id:
                log.info(
                    "franchise.bill_already_exists",
                    franchisee_id=str(franchisee.id),
                    bill_id=str(existing_id),
                )
                continue

            bill = RoyaltyBill(
                tenant_id=tenant_id,
                franchisee_id=franchisee.id,
                bill_month=bill_month,
                total_revenue=total_revenue,
                royalty_amount=royalty_amount,
                due_date=due_date,
            )

            # Step 5: 逾期检查
            if due_date and (today - due_date).days > OVERDUE_DAYS:
                bill.mark_overdue()

            # 写入数据库
            if db is not None:
                await RoyaltyCalculator._insert_royalty_bill(
                    bill=bill,
                    period_start=period_start,
                    period_end=period_end,
                    revenue_fen=total_revenue_fen,
                    royalty_amount_fen=royalty_amount_fen,
                    management_fee_fen=management_fee_fen,
                    total_due_fen=total_due_fen,
                    db=db,
                )

            bills.append(bill)
            log.info(
                "franchise.bill_generated",
                franchisee_id=str(franchisee.id),
                total_revenue=total_revenue,
                royalty_amount=royalty_amount,
                status=bill.status,
            )

        log.info("franchise.generate_monthly_bills.done", count=len(bills))
        return bills

    @staticmethod
    async def mark_overdue_bills(tenant_id: UUID, cutoff: date, db: Any) -> int:
        """将到期日早于 cutoff 且未付款的账单标记为 overdue。

        返回已标记 overdue 的账单条数。
        """
        log = logger.bind(tenant_id=str(tenant_id), cutoff=str(cutoff))
        log.info("franchise.mark_overdue_bills.start")

        if db is None:
            log.warning("franchise.mark_overdue_bills.no_db")
            return 0

        result = await db.execute(
            """
            UPDATE royalty_bills
               SET status = 'overdue'
             WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
               AND tenant_id = :tenant_id
               AND status IN ('pending')
               AND due_date < :cutoff
            """,
            {"tenant_id": str(tenant_id), "cutoff": cutoff},
        )
        count: int = result.rowcount if hasattr(result, "rowcount") else 0
        log.info("franchise.mark_overdue_bills.done", marked=count)
        return count

    @staticmethod
    async def list_active_franchisees(tenant_id: UUID, db: Any) -> List[Franchisee]:
        """查询所有活跃加盟商（公开 API，供外部调用）。"""
        return await RoyaltyCalculator._fetch_active_franchisees(tenant_id, db)

    @staticmethod
    async def get_franchisee_dashboard(
        tenant_id: UUID,
        franchisee_id: UUID,
        db: Any,
    ) -> FranchiseeDashboard:
        """加盟商经营看板。

        包含：
        - 本月营收 / 环比 / 同比
        - 待缴费用（pending + overdue 账单合计）
        - 门店数量 / 活跃门店数
        - 近 3 次审计分数
        """
        today = date.today()
        current_month = today.strftime("%Y-%m")
        year, month = today.year, today.month

        # 当月区间
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])

        # 上月区间
        prev_month_end = period_start - timedelta(days=1)
        prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)

        # 去年同月区间
        prev_year_start = date(year - 1, month, 1)
        prev_year_end = date(
            year - 1, month, calendar.monthrange(year - 1, month)[1]
        )

        # 获取该加盟商旗下门店
        store_ids = await RoyaltyCalculator._fetch_franchisee_store_ids(
            franchisee_id, tenant_id, db
        )

        # 汇总营收（分）
        current_fen = await RoyaltyCalculator._sum_store_revenue_fen(
            store_ids, period_start, period_end, tenant_id, db
        )
        prev_month_fen = await RoyaltyCalculator._sum_store_revenue_fen(
            store_ids, prev_month_start, prev_month_end, tenant_id, db
        )
        prev_year_fen = await RoyaltyCalculator._sum_store_revenue_fen(
            store_ids, prev_year_start, prev_year_end, tenant_id, db
        )

        # 待缴费用（pending + overdue 账单 total_due_fen 合计）
        pending_due_fen = await RoyaltyCalculator._sum_pending_due_fen(
            franchisee_id, tenant_id, db
        )

        # 门店数量
        store_count = len(store_ids)
        active_store_count = await RoyaltyCalculator._count_active_stores(
            franchisee_id, tenant_id, db
        )

        # 近 3 次审计分数
        recent_scores = await RoyaltyCalculator._fetch_recent_audit_scores(
            franchisee_id, tenant_id, db, limit=3
        )

        return FranchiseeDashboard(
            franchisee_id=franchisee_id,
            current_month=current_month,
            current_month_revenue_fen=current_fen,
            prev_month_revenue_fen=prev_month_fen,
            prev_year_month_revenue_fen=prev_year_fen,
            pending_due_fen=pending_due_fen,
            store_count=store_count,
            active_store_count=active_store_count,
            recent_audit_scores=recent_scores,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助（DB 查询层）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def _fetch_active_franchisees(tenant_id: UUID, db: Any) -> List[Franchisee]:
        """从 DB 查询所有 active 加盟商。"""
        if db is None:
            return []
        rows = await db.fetch_all(
            """
            SELECT id, tenant_id, name AS franchisee_name,
                   contact_name, contact_phone,
                   contract_start, contract_end,
                   royalty_rate, royalty_tiers,
                   management_fee_fen, status, created_at
              FROM franchisees
             WHERE tenant_id = :tenant_id
               AND status = 'active'
             ORDER BY name
            """,
            {"tenant_id": str(tenant_id)},
        )
        result: List[Franchisee] = []
        for row in rows:
            f = Franchisee(
                id=row["id"],
                tenant_id=row["tenant_id"],
                franchisee_name=row["franchisee_name"],
                contact_name=row["contact_name"],
                contact_phone=row["contact_phone"],
                contract_start=row["contract_start"],
                contract_end=row["contract_end"],
                royalty_rate=float(row["royalty_rate"]),
                royalty_tiers=row["royalty_tiers"] or [],
                status=row["status"],
                created_at=row["created_at"],
            )
            # 将管理费存入对象供后续使用（扩展字段）
            object.__setattr__(f, "management_fee_fen", row["management_fee_fen"] or 0)
            result.append(f)
        return result

    @staticmethod
    async def _fetch_franchisee_store_ids(
        franchisee_id: UUID, tenant_id: UUID, db: Any
    ) -> List[UUID]:
        """查询加盟商旗下所有 active 门店 ID。"""
        if db is None:
            return []
        rows = await db.fetch_all(
            """
            SELECT store_id
              FROM franchisee_stores
             WHERE franchisee_id = :franchisee_id
               AND tenant_id = :tenant_id
               AND status = 'active'
            """,
            {"franchisee_id": str(franchisee_id), "tenant_id": str(tenant_id)},
        )
        return [UUID(str(row["store_id"])) for row in rows]

    @staticmethod
    async def _sum_store_revenue_fen(
        store_ids: List[UUID],
        period_start: date,
        period_end: date,
        tenant_id: UUID,
        db: Any,
    ) -> int:
        """汇总门店列表在指定区间内的营业额（分）。

        从 orders 表按实收金额（paid_amount_fen）汇总，
        仅统计状态为 completed 的订单。
        """
        if db is None or not store_ids:
            return 0
        store_id_strs = [str(sid) for sid in store_ids]
        row = await db.fetch_one(
            """
            SELECT COALESCE(SUM(paid_amount_fen), 0) AS total_fen
              FROM orders
             WHERE tenant_id = :tenant_id
               AND store_id = ANY(:store_ids)
               AND status = 'completed'
               AND created_at::date >= :period_start
               AND created_at::date <= :period_end
            """,
            {
                "tenant_id": str(tenant_id),
                "store_ids": store_id_strs,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        return int(row["total_fen"]) if row else 0

    @staticmethod
    async def _sum_pending_due_fen(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> int:
        """汇总加盟商未付账单 total_due_fen（pending + overdue）。"""
        if db is None:
            return 0
        row = await db.fetch_one(
            """
            SELECT COALESCE(SUM(total_due_fen), 0) AS total_fen
              FROM royalty_bills
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND status IN ('pending', 'overdue')
            """,
            {"tenant_id": str(tenant_id), "franchisee_id": str(franchisee_id)},
        )
        return int(row["total_fen"]) if row else 0

    @staticmethod
    async def _count_active_stores(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
    ) -> int:
        """统计加盟商旗下活跃门店数量。"""
        if db is None:
            return 0
        row = await db.fetch_one(
            """
            SELECT COUNT(*) AS cnt
              FROM franchisee_stores
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND status = 'active'
            """,
            {"tenant_id": str(tenant_id), "franchisee_id": str(franchisee_id)},
        )
        return int(row["cnt"]) if row else 0

    @staticmethod
    async def _fetch_recent_audit_scores(
        franchisee_id: UUID,
        tenant_id: UUID,
        db: Any,
        limit: int = 3,
    ) -> List[float]:
        """查询加盟商最近 N 次巡店审计分数。"""
        if db is None:
            return []
        rows = await db.fetch_all(
            """
            SELECT score
              FROM franchise_audits
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND score IS NOT NULL
             ORDER BY audit_date DESC, created_at DESC
             LIMIT :limit
            """,
            {
                "tenant_id": str(tenant_id),
                "franchisee_id": str(franchisee_id),
                "limit": limit,
            },
        )
        return [float(row["score"]) for row in rows]

    @staticmethod
    async def _find_existing_bill(
        tenant_id: UUID,
        franchisee_id: UUID,
        period_start: date,
        period_end: date,
        db: Any,
    ) -> Optional[UUID]:
        """查询是否已存在该加盟商本期账单（防重复生成）。"""
        if db is None:
            return None
        row = await db.fetch_one(
            """
            SELECT id
              FROM royalty_bills
             WHERE tenant_id = :tenant_id
               AND franchisee_id = :franchisee_id
               AND period_start = :period_start
               AND period_end = :period_end
             LIMIT 1
            """,
            {
                "tenant_id": str(tenant_id),
                "franchisee_id": str(franchisee_id),
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        return UUID(str(row["id"])) if row else None

    @staticmethod
    async def _insert_royalty_bill(
        bill: RoyaltyBill,
        period_start: date,
        period_end: date,
        revenue_fen: int,
        royalty_amount_fen: int,
        management_fee_fen: int,
        total_due_fen: int,
        db: Any,
    ) -> None:
        """将账单写入 royalty_bills 表。"""
        await db.execute(
            """
            INSERT INTO royalty_bills (
                id, tenant_id, franchisee_id,
                period_start, period_end,
                revenue_fen, royalty_rate, royalty_amount_fen,
                management_fee_fen, total_due_fen,
                status, due_date, created_at
            ) VALUES (
                :id, :tenant_id, :franchisee_id,
                :period_start, :period_end,
                :revenue_fen, :royalty_rate, :royalty_amount_fen,
                :management_fee_fen, :total_due_fen,
                :status, :due_date, NOW()
            )
            """,
            {
                "id": str(bill.id),
                "tenant_id": str(bill.tenant_id),
                "franchisee_id": str(bill.franchisee_id),
                "period_start": period_start,
                "period_end": period_end,
                "revenue_fen": revenue_fen,
                "royalty_rate": bill.royalty_amount / (bill.total_revenue or 1),
                "royalty_amount_fen": royalty_amount_fen,
                "management_fee_fen": management_fee_fen,
                "total_due_fen": total_due_fen,
                "status": bill.status,
                "due_date": bill.due_date,
            },
        )

    @staticmethod
    def _calc_due_date(bill_month: str) -> date:
        """计算账单到期日（次月 15 日）。"""
        year, month = int(bill_month[:4]), int(bill_month[5:7])
        if month == 12:
            return date(year + 1, 1, 15)
        return date(year, month + 1, 15)
