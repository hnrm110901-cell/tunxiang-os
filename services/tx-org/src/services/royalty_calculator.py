"""分润计算器

核心职责：
1. 阶梯分润计算（类似个税累进）
2. 月度账单批处理（查询、汇总、写入、逾期标记）
"""

from __future__ import annotations

import structlog
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from ..models.franchise import (
    Franchisee,
    FranchiseeStatus,
    FranchiseeStore,
    RoyaltyBill,
    RoyaltyBillStatus,
    RoyaltyTier,
)

logger = structlog.get_logger(__name__)

# 欠款超过此天数标记为 overdue
OVERDUE_DAYS = 60


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
        2. 汇总各加盟商旗下门店的当月营业额（当前为模拟数据）
        3. 调用 calculate() 得出分润金额
        4. 写入 royalty_bills
        5. 欠款超 60 天标记 overdue

        参数：
            tenant_id  — 集团 tenant_id
            bill_month — 账单月份，格式 "YYYY-MM"
            db         — 数据库会话（此版本为模拟实现）

        返回已生成的账单列表。
        """
        log = logger.bind(tenant_id=str(tenant_id), bill_month=bill_month)
        log.info("franchise.generate_monthly_bills.start")

        # Step 1: 查询所有 active 加盟商（模拟；实际需从 DB 查询）
        active_franchisees: List[Franchisee] = await RoyaltyCalculator._fetch_active_franchisees(
            tenant_id, db
        )

        bills: List[RoyaltyBill] = []
        today = date.today()

        for franchisee in active_franchisees:
            # Step 2: 汇总该加盟商门店当月营业额（模拟）
            store_ids = await RoyaltyCalculator._fetch_franchisee_store_ids(
                franchisee.id, tenant_id, db
            )
            total_revenue = await RoyaltyCalculator._sum_store_revenue(
                store_ids, bill_month, tenant_id, db
            )

            # Step 3: 计算分润
            royalty_amount = RoyaltyCalculator.calculate(total_revenue, franchisee)

            # Step 4: 构建账单
            due_date = RoyaltyCalculator._calc_due_date(bill_month)
            bill = RoyaltyBill(
                tenant_id=tenant_id,
                franchisee_id=franchisee.id,
                bill_month=bill_month,
                total_revenue=total_revenue,
                royalty_amount=royalty_amount,
                due_date=due_date,
            )

            # Step 5: 逾期检查（超 60 天未付款）
            if due_date and (today - due_date).days > OVERDUE_DAYS:
                bill.mark_overdue()

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
    async def mark_overdue_bills(tenant_id: UUID, db: Any) -> List[UUID]:
        """将超过 60 天未付款的 pending/confirmed 账单标记为 overdue。

        返回已标记 overdue 的账单 ID 列表。
        """
        cutoff = date.today() - timedelta(days=OVERDUE_DAYS)
        # 实际实现：从 DB 查询 due_date < cutoff AND status IN ('pending','confirmed')
        # 此版本为占位，返回空列表
        log = logger.bind(tenant_id=str(tenant_id), cutoff=str(cutoff))
        log.info("franchise.mark_overdue_bills.called")
        return []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  私有辅助（模拟 DB 查询，便于测试替换）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    async def _fetch_active_franchisees(tenant_id: UUID, db: Any) -> List[Franchisee]:
        """从 DB 查询 active 加盟商（模拟实现）。"""
        # TODO: 替换为真实 DB 查询
        # SELECT * FROM franchisees WHERE tenant_id = :tenant_id AND status = 'active'
        return []

    @staticmethod
    async def _fetch_franchisee_store_ids(
        franchisee_id: UUID, tenant_id: UUID, db: Any
    ) -> List[UUID]:
        """从 DB 查询加盟商关联的门店 ID 列表（模拟实现）。"""
        # TODO: 替换为真实 DB 查询
        # SELECT store_id FROM franchisee_stores
        # WHERE franchisee_id = :franchisee_id AND tenant_id = :tenant_id
        return []

    @staticmethod
    async def _sum_store_revenue(
        store_ids: List[UUID], bill_month: str, tenant_id: UUID, db: Any
    ) -> float:
        """汇总门店列表当月营业额（模拟实现）。"""
        # TODO: 替换为真实 DB 查询（跨域调用 tx-finance 或本地汇总表）
        # SELECT SUM(revenue) FROM store_monthly_revenue
        # WHERE store_id = ANY(:store_ids) AND month = :bill_month AND tenant_id = :tenant_id
        return 0.0

    @staticmethod
    def _calc_due_date(bill_month: str) -> date:
        """计算账单到期日（次月 15 日）。"""
        year, month = int(bill_month[:4]), int(bill_month[5:7])
        if month == 12:
            return date(year + 1, 1, 15)
        return date(year, month + 1, 15)
