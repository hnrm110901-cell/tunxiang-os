"""马来西亚业务智能仪表盘服务 — Phase 3 Sprint 3.3

生成马来西亚专属的经营分析报告，整合 SST、e-Invoice、节假日效应、
菜系表现、政府补贴利用率和多币种财务汇总。

所有金额单位：分（fen），与系统 Amount Convention 一致。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tx_agent.src.config.malaysia_holidays import (
    get_high_impact_periods,
    get_holidays_by_year,
)
from services.tx_agent.src.config.malaysia_cuisine_profiles import (
    CUISINE_PROFILES,
    get_cuisine_by_state,
    get_cuisine_profile,
)

logger = structlog.get_logger(__name__)

# 默认货币转换（用于多币种报告）
CNY_TO_MYR = 0.65  # 1 CNY ≈ 0.65 MYR（参考汇率，实际使用实时汇率）
MYR_TO_CNY = 1.5385  # 1 MYR ≈ 1.5385 CNY


class MYDashboardService:
    """马来西亚业务智能仪表盘服务

    基于现有 SST/e-Invoice/Subsidy 服务的数据持久层，直接查询数据库表
    生成聚合报告和趋势分析。

    用法：
        svc = MYDashboardService()
        sst_summary = await svc.get_sst_summary(tenant_id, "2026-01-01", "2026-03-31", db)
    """

    async def get_sst_summary(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """SST 汇总报告

        按 SST 分类（6%/8%/0%）统计期间内销售额、SST 税额，
        并计算每月应付给 Royal Malaysian Customs 的 SST 金额。

        Args:
            tenant_id: 商户 UUID.
            period_start: 统计起始日（YYYY-MM-DD）.
            period_end: 统计结束日（YYYY-MM-DD）.
            db: 数据库会话.

        Returns:
            {
                period: { from, to },
                by_category: {
                    standard_6: { total_sales_fen, sst_fen, transaction_count },
                    specific_8: { total_sales_fen, sst_fen, transaction_count },
                    exempt:     { total_sales_fen, sst_fen, transaction_count },
                },
                total_sst_payable_fen: int,       # 应付 Customs 总额
                monthly_breakdown: [
                    { month, standard_sst_fen, specific_sst_fen, total_sst_fen }
                ],
                total_transactions: int,
            }
        """
        log = logger.bind(tenant_id=tenant_id, period_start=period_start, period_end=period_end)
        log.info("my_dashboard.sst_summary")

        # 按 SST 分类统计销售额和税额
        by_category: dict[str, dict[str, int | float]] = {
            "standard_6": {"total_sales_fen": 0, "sst_fen": 0, "transaction_count": 0},
            "specific_8": {"total_sales_fen": 0, "sst_fen": 0, "transaction_count": 0},
            "exempt": {"total_sales_fen": 0, "sst_fen": 0, "transaction_count": 0},
        }

        # 月度 SST 明细
        monthly_map: dict[str, dict[str, int]] = {}

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        sst_category,
                        SUM(amount_fen) AS total_amount_fen,
                        COUNT(*) AS transaction_count,
                        TO_CHAR(transaction_date, 'YYYY-MM') AS month
                    FROM order_items oi
                    JOIN orders o ON oi.order_id = o.id
                    WHERE o.tenant_id = :tid
                      AND o.order_date >= :pstart
                      AND o.order_date <= :pend
                      AND o.status IN ('completed', 'settled')
                      AND o.is_deleted = FALSE
                    GROUP BY sst_category, TO_CHAR(transaction_date, 'YYYY-MM')
                    ORDER BY month, sst_category
                """),
                {
                    "tid": tenant_id,
                    "pstart": period_start,
                    "pend": period_end,
                },
            )
            mappings = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("sst_summary_query_failed", error=str(exc))
            mappings = []

        total_sst_payable_fen = 0
        total_transactions = 0

        for row in mappings:
            cat = row.get("sst_category", "standard")
            amount_fen = int(row.get("total_amount_fen", 0) or 0)
            count = int(row.get("transaction_count", 0) or 0)
            month = row.get("month", "")

            # 计算 SST
            if cat == "standard":
                sst = int(amount_fen * 0.06 / 1.06)
                cat_key = "standard_6"
            elif cat == "specific":
                sst = int(amount_fen * 0.08 / 1.08)
                cat_key = "specific_8"
            else:
                sst = 0
                cat_key = "exempt"

            by_category[cat_key]["total_sales_fen"] += amount_fen
            by_category[cat_key]["sst_fen"] += sst
            by_category[cat_key]["transaction_count"] += count
            total_sst_payable_fen += sst
            total_transactions += count

            if month:
                if month not in monthly_map:
                    monthly_map[month] = {"standard_sst_fen": 0, "specific_sst_fen": 0, "total_sst_fen": 0}
                if cat == "standard":
                    monthly_map[month]["standard_sst_fen"] += sst
                elif cat == "specific":
                    monthly_map[month]["specific_sst_fen"] += sst
                monthly_map[month]["total_sst_fen"] += sst

        monthly_breakdown = [
            {
                "month": m,
                "standard_sst_fen": v["standard_sst_fen"],
                "specific_sst_fen": v["specific_sst_fen"],
                "total_sst_fen": v["total_sst_fen"],
                "total_sst_rm": round(v["total_sst_fen"] / 100, 2),
            }
            for m, v in sorted(monthly_map.items())
        ]

        result = {
            "period": {"from": period_start, "to": period_end},
            "by_category": {
                k: {
                    "total_sales_fen": int(v["total_sales_fen"]),
                    "total_sales_rm": round(v["total_sales_fen"] / 100, 2),
                    "sst_fen": int(v["sst_fen"]),
                    "sst_rm": round(v["sst_fen"] / 100, 2),
                    "transaction_count": v["transaction_count"],
                }
                for k, v in by_category.items()
            },
            "total_sst_payable_fen": total_sst_payable_fen,
            "total_sst_payable_rm": round(total_sst_payable_fen / 100, 2),
            "monthly_breakdown": monthly_breakdown,
            "total_transactions": total_transactions,
        }

        log.info(
            "my_dashboard.sst_summary_complete",
            total_sst_fen=total_sst_payable_fen,
            transactions=total_transactions,
        )
        return result

    async def get_einvoice_stats(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """e-Invoice 统计报告

        统计 LHDN MyInvois 提交量、接受/拒绝率、按月的提交趋势。

        Args:
            tenant_id: 商户 UUID.
            period_start: 统计起始日（YYYY-MM-DD）.
            period_end: 统计结束日（YYYY-MM-DD）.
            db: 数据库会话.

        Returns:
            {
                period: { from, to },
                total_submitted: int,
                total_accepted: int,
                total_rejected: int,
                acceptance_rate: float,
                monthly_volume: [{ month, submitted, accepted, rejected }],
                by_platform: { myinvois: { submitted, accepted, rejected } },
            }
        """
        log = logger.bind(tenant_id=tenant_id, period_start=period_start, period_end=period_end)
        log.info("my_dashboard.einvoice_stats")

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        status,
                        platform,
                        COUNT(*) AS cnt,
                        TO_CHAR(submitted_at, 'YYYY-MM') AS month
                    FROM e_invoice_documents
                    WHERE tenant_id = :tid
                      AND submitted_at >= :pstart::timestamp
                      AND submitted_at <= :pend::timestamp + INTERVAL '1 day'
                      AND is_deleted = FALSE
                    GROUP BY status, platform, TO_CHAR(submitted_at, 'YYYY-MM')
                    ORDER BY month, platform, status
                """),
                {
                    "tid": tenant_id,
                    "pstart": period_start,
                    "pend": period_end,
                },
            )
            mappings = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("einvoice_stats_query_failed", error=str(exc))
            mappings = []

        total_submitted = 0
        total_accepted = 0
        total_rejected = 0
        monthly_map: dict[str, dict[str, int]] = {}
        platform_map: dict[str, dict[str, int]] = {}

        for row in mappings:
            status = row.get("status", "unknown")
            platform = row.get("platform", "myinvois")
            count = int(row.get("cnt", 0) or 0)
            month = row.get("month", "")

            total_submitted += count
            if status in ("accepted", "valid"):
                total_accepted += count
            elif status in ("rejected", "invalid"):
                total_rejected += count

            if month:
                if month not in monthly_map:
                    monthly_map[month] = {"submitted": 0, "accepted": 0, "rejected": 0}
                monthly_map[month]["submitted"] += count
                if status in ("accepted", "valid"):
                    monthly_map[month]["accepted"] += count
                elif status in ("rejected", "invalid"):
                    monthly_map[month]["rejected"] += count

            pl = platform or "myinvois"
            if pl not in platform_map:
                platform_map[pl] = {"submitted": 0, "accepted": 0, "rejected": 0}
            platform_map[pl]["submitted"] += count
            if status in ("accepted", "valid"):
                platform_map[pl]["accepted"] += count
            elif status in ("rejected", "invalid"):
                platform_map[pl]["rejected"] += count

        acceptance_rate = round(total_accepted / max(total_submitted, 1) * 100, 2)

        monthly_volume = [
            {
                "month": m,
                "submitted": v["submitted"],
                "accepted": v["accepted"],
                "rejected": v["rejected"],
            }
            for m, v in sorted(monthly_map.items())
        ]

        result = {
            "period": {"from": period_start, "to": period_end},
            "total_submitted": total_submitted,
            "total_accepted": total_accepted,
            "total_rejected": total_rejected,
            "acceptance_rate": acceptance_rate,
            "monthly_volume": monthly_volume,
            "by_platform": {
                pl: {
                    "submitted": v["submitted"],
                    "accepted": v["accepted"],
                    "rejected": v["rejected"],
                    "acceptance_rate": round(v["accepted"] / max(v["submitted"], 1) * 100, 2),
                }
                for pl, v in platform_map.items()
            },
        }

        log.info(
            "my_dashboard.einvoice_stats_complete",
            submitted=total_submitted,
            accepted=total_accepted,
            rejected=total_rejected,
        )
        return result

    async def get_holiday_sales_impact(
        self,
        tenant_id: str,
        year: int,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """节假日销售额影响分析

        分析每个马来西亚公共假期前后、期间的销售变化，各菜系表现，
        以及与上年的同比对比。

        Args:
            tenant_id: 商户 UUID.
            year: 目标年份.
            db: 数据库会话.

        Returns:
            [
                {
                    holiday_name, date, impact,
                    sales_before_fen, sales_during_fen, sales_after_fen,
                    dine_in_boost_actual, takeaway_boost_actual,
                    best_performing_cuisine,
                    yoy_change_pct (if prior year data available),
                }
            ]
        """
        log = logger.bind(tenant_id=tenant_id, year=year)
        log.info("my_dashboard.holiday_impact")

        holidays = get_holidays_by_year(year)
        if not holidays:
            log.warning("my_dashboard.no_holiday_data", year=year)
            return []

        # 获取所有商店的州信息（用于菜系匹配）
        try:
            store_rows = await db.execute(
                text("""
                    SELECT id, region, store_metadata
                    FROM stores
                    WHERE tenant_id = :tid AND is_deleted = FALSE
                """),
                {"tid": tenant_id},
            )
            stores = store_rows.mappings().fetchall()
        except Exception as exc:
            log.warning("store_fetch_failed", error=str(exc))
            stores = []

        # 获取每个商店的市/州信息
        store_cuisine_map: dict[str, list[str]] = {}
        for store in stores:
            sid = str(store.get("id", ""))
            state = store.get("region") or ""
            store_cuisine_map[sid] = get_cuisine_by_state(state) if state else ["malay", "chinese", "indian"]

        results: list[dict[str, Any]] = []

        for holiday in holidays:
            holiday_date = holiday["date"]
            duration = holiday.get("duration_days", 1)
            prep_days = holiday.get("prep_lead_days", 0)
            holiday_name = holiday["name"]

            # 定义分析窗口：前 prep_days + 节假日期间 + 后 3 天
            h_dt = datetime.strptime(holiday_date, "%Y-%m-%d").date()
            before_start = (h_dt - timedelta(days=prep_days + 3)).isoformat()
            before_end = (h_dt - timedelta(days=1)).isoformat()
            during_start = holiday_date
            during_end = (h_dt + timedelta(days=duration - 1)).isoformat()
            after_start = (h_dt + timedelta(days=duration)).isoformat()
            after_end = (h_dt + timedelta(days=duration + 2)).isoformat()

            # 查询节前销售额
            sales_before = await self._query_sales(tenant_id, before_start, before_end, db)
            sales_during = await self._query_sales(tenant_id, during_start, during_end, db)
            sales_after = await self._query_sales(tenant_id, after_start, after_end, db)

            # 计算实际增长
            avg_daily_before = sales_before["total_fen"] / max(sales_before["day_count"], 1)
            avg_daily_during = sales_during["total_fen"] / max(sales_during["day_count"], 1)
            dine_in_actual = round((avg_daily_during - avg_daily_before) / max(avg_daily_before, 1), 4) if avg_daily_before > 0 else 0.0

            # 最佳菜系（基于配置数据和分类销量）
            category_boost = holiday.get("category_boost", {})
            best_cuisine = max(category_boost, key=category_boost.get) if category_boost else None

            # 同比数据（上年同期）
            yoy_change = await self._calc_yoy_change(tenant_id, holiday_date, duration, prep_days, db)

            expected_boost = holiday.get("dine_in_boost", 0.0)

            results.append({
                "holiday_name": holiday_name,
                "date": holiday_date,
                "duration_days": duration,
                "impact": holiday.get("impact", "low"),
                "cuisine_trend": holiday.get("cuisine_trend", ""),
                "sales_before_fen": sales_before["total_fen"],
                "sales_during_fen": sales_during["total_fen"],
                "sales_after_fen": sales_after["total_fen"],
                "avg_daily_before_fen": int(round(avg_daily_before)),
                "avg_daily_during_fen": int(round(avg_daily_during)),
                "dine_in_boost_expected": expected_boost,
                "dine_in_boost_actual": dine_in_actual,
                "best_performing_cuisine": best_cuisine,
                "expected_category_boost": category_boost,
                "yoy_change_pct": yoy_change,
            })

        # 按日期排序
        results.sort(key=lambda x: x["date"])

        log.info(
            "my_dashboard.holiday_impact_complete",
            holiday_count=len(results),
        )
        return results

    async def get_cuisine_performance(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """菜系经营表现分析

        按菜系类型（Malay/Chinese/Indian/Fusion/Borneo）拆分销售数据，
        包括平均订单价、高峰时段、渠道分布。

        Args:
            tenant_id: 商户 UUID.
            period_start: 统计起始日（YYYY-MM-DD）.
            period_end: 统计结束日（YYYY-MM-DD）.
            db: 数据库会话.

        Returns:
            {
                period: { from, to },
                cuisines: {
                    malay: {
                        total_sales_fen, avg_order_value_fen, transaction_count,
                        peak_hours, dine_in_ratio, takeaway_ratio, delivery_ratio,
                        top_dishes: [{ name, sales_fen, count }]
                    },
                    ...
                },
                total_sales_fen, top_cuisine, worst_cuisine,
            }
        """
        log = logger.bind(tenant_id=tenant_id, period_start=period_start, period_end=period_end)
        log.info("my_dashboard.cuisine_performance")

        # 初始化菜系数据，使用 CUISINE_PROFILES 中的定义
        cuisines: dict[str, dict[str, Any]] = {}
        for cuisine_key, profile in CUISINE_PROFILES.items():
            cuisines[cuisine_key] = {
                "cuisine_name": cuisine_key,
                "description": profile.get("description", ""),
                "avg_spend_per_pax_fen": profile.get("avg_spend_per_pax_fen", 2000),
                "peak_hours": profile.get("peak_hours", [12, 13, 19, 20]),
                "total_sales_fen": 0,
                "avg_order_value_fen": 0,
                "transaction_count": 0,
                "dine_in_count": 0,
                "takeaway_count": 0,
                "delivery_count": 0,
                "top_dishes": [],
            }

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        d.cuisine_category AS cuisine,
                        COUNT(*) AS order_count,
                        SUM(o.final_amount_fen) AS total_sales_fen,
                        AVG(o.final_amount_fen) AS avg_order_fen,
                        SUM(CASE WHEN o.order_type = 'dine_in' THEN 1 ELSE 0 END) AS dine_in_cnt,
                        SUM(CASE WHEN o.order_type = 'takeaway' THEN 1 ELSE 0 END) AS takeaway_cnt,
                        SUM(CASE WHEN o.order_type = 'delivery' THEN 1 ELSE 0 END) AS delivery_cnt
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.id
                    JOIN dishes d ON d.id = oi.dish_id
                    WHERE o.tenant_id = :tid
                      AND o.order_date >= :pstart
                      AND o.order_date <= :pend
                      AND o.status IN ('completed', 'settled')
                      AND o.is_deleted = FALSE
                      AND d.cuisine_category IS NOT NULL
                    GROUP BY d.cuisine_category
                    ORDER BY total_sales_fen DESC
                """),
                {
                    "tid": tenant_id,
                    "pstart": period_start,
                    "pend": period_end,
                },
            )
            db_rows = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("cuisine_performance_query_failed", error=str(exc))
            db_rows = []

        total_sales_fen = 0
        best_sales = 0
        worst_sales = float("inf")
        top_cuisine = None
        worst_cuisine = None

        for row in db_rows:
            cuisine_key = (row.get("cuisine") or "").lower().replace(" ", "_")
            if cuisine_key not in cuisines:
                cuisine_key = "fusion"

            c = cuisines[cuisine_key]
            c["total_sales_fen"] = int(row.get("total_sales_fen", 0) or 0)
            c["avg_order_value_fen"] = int(round(row.get("avg_order_fen", 0) or 0))
            c["transaction_count"] = int(row.get("order_count", 0) or 0)
            c["dine_in_count"] = int(row.get("dine_in_cnt", 0) or 0)
            c["takeaway_count"] = int(row.get("takeaway_cnt", 0) or 0)
            c["delivery_count"] = int(row.get("delivery_cnt", 0) or 0)
            tc = c["transaction_count"]
            c["dine_in_ratio"] = round(c["dine_in_count"] / max(tc, 1), 4)
            c["takeaway_ratio"] = round(c["takeaway_count"] / max(tc, 1), 4)
            c["delivery_ratio"] = round(c["delivery_count"] / max(tc, 1), 4)
            c["total_sales_rm"] = round(c["total_sales_fen"] / 100, 2)
            c["avg_order_rm"] = round(c["avg_order_value_fen"] / 100, 2)

            total_sales_fen += c["total_sales_fen"]
            if c["total_sales_fen"] > best_sales:
                best_sales = c["total_sales_fen"]
                top_cuisine = cuisine_key
            if 0 < c["total_sales_fen"] < worst_sales:
                worst_sales = c["total_sales_fen"]
                worst_cuisine = cuisine_key

        # 获取每个菜系的畅销菜品 Top 5
        for cuisine_key in cuisines:
            try:
                dish_rows = await db.execute(
                    text("""
                        SELECT
                            d.name AS dish_name,
                            SUM(oi.amount_fen) AS sales_fen,
                            COUNT(*) AS order_count
                        FROM order_items oi
                        JOIN orders o ON oi.order_id = o.id
                        JOIN dishes d ON d.id = oi.dish_id
                        WHERE o.tenant_id = :tid
                          AND o.order_date >= :pstart
                          AND o.order_date <= :pend
                          AND o.status IN ('completed', 'settled')
                          AND o.is_deleted = FALSE
                          AND d.cuisine_category = :cuisine
                        GROUP BY d.name
                        ORDER BY sales_fen DESC
                        LIMIT 5
                    """),
                    {
                        "tid": tenant_id,
                        "pstart": period_start,
                        "pend": period_end,
                        "cuisine": cuisine_key,
                    },
                )
                top_dishes = [
                    {
                        "name": r["dish_name"],
                        "sales_fen": int(r["sales_fen"]),
                        "sales_rm": round(r["sales_fen"] / 100, 2),
                        "order_count": int(r["order_count"]),
                    }
                    for r in dish_rows.mappings().fetchall()
                ]
                cuisines[cuisine_key]["top_dishes"] = top_dishes
            except Exception as exc:
                log.warning("top_dishes_query_failed", cuisine=cuisine_key, error=str(exc))
                cuisines[cuisine_key]["top_dishes"] = []

        result = {
            "period": {"from": period_start, "to": period_end},
            "cuisines": cuisines,
            "total_sales_fen": total_sales_fen,
            "total_sales_rm": round(total_sales_fen / 100, 2),
            "top_cuisine": top_cuisine,
            "worst_cuisine": worst_cuisine,
            "cuisine_count": len([k for k, v in cuisines.items() if v["total_sales_fen"] > 0]),
        }

        log.info(
            "my_dashboard.cuisine_performance_complete",
            total_sales_fen=total_sales_fen,
            top_cuisine=top_cuisine,
        )
        return result

    async def get_subsidy_utilization(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """政府补贴利用率报告

        统计商户的补贴方案申请情况、已节省金额、活跃补贴状态等。

        Args:
            tenant_id: 商户 UUID.
            db: 数据库会话.

        Returns:
            {
                has_active_subsidy: bool,
                active_subsidies: [{ program, rate, monthly_fee_fen,
                                    subsidy_amount_fen, applied_at, expires_at }],
                total_saved_fen: int,
                total_billed_fen: int,
                total_payable_fen: int,
                monthly_savings: [{ month, subsidy_fen, billed_fen }],
                program_summary: [{ program, count, total_saved_fen }],
            }
        """
        log = logger.bind(tenant_id=tenant_id)
        log.info("my_dashboard.subsidy_utilization")

        try:
            # 活跃补贴
            active_rows = await db.execute(
                text("""
                    SELECT id, program, subsidy_rate, monthly_fee_fen,
                           subsidy_amount_fen, applied_at, expires_at, status
                    FROM tenant_subsidies
                    WHERE tenant_id = :tid
                      AND status = 'active'
                      AND expires_at >= NOW()
                    ORDER BY applied_at DESC
                """),
                {"tid": tenant_id},
            )
            active_subsidies = [
                {
                    "subsidy_id": str(r.id),
                    "program": r.program,
                    "subsidy_rate": float(r.subsidy_rate),
                    "monthly_fee_fen": r.monthly_fee_fen,
                    "monthly_fee_rm": round(r.monthly_fee_fen / 100, 2),
                    "subsidy_amount_fen": r.subsidy_amount_fen,
                    "subsidy_amount_rm": round(r.subsidy_amount_fen / 100, 2),
                    "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                    "status": r.status,
                }
                for r in active_rows.fetchall()
            ]

            # 累计节省 / 账单
            bill_stats = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(subsidy_fen), 0) AS total_saved_fen,
                        COALESCE(SUM(base_fee_fen), 0) AS total_billed_fen,
                        COALESCE(SUM(payable_fen), 0) AS total_payable_fen
                    FROM subsidy_bills
                    WHERE tenant_id = :tid
                """),
                {"tid": tenant_id},
            )
            bill_row = bill_stats.fetchone()
            total_saved_fen = int(bill_row.total_saved_fen) if bill_row else 0
            total_billed_fen = int(bill_row.total_billed_fen) if bill_row else 0
            total_payable_fen = int(bill_row.total_payable_fen) if bill_row else 0

            # 月度节省趋势
            monthly_rows = await db.execute(
                text("""
                    SELECT
                        TO_CHAR(period_start, 'YYYY-MM') AS month,
                        SUM(subsidy_fen) AS subsidy_fen,
                        SUM(base_fee_fen) AS billed_fen
                    FROM subsidy_bills
                    WHERE tenant_id = :tid
                    GROUP BY TO_CHAR(period_start, 'YYYY-MM')
                    ORDER BY month DESC
                    LIMIT 12
                """),
                {"tid": tenant_id},
            )
            monthly_savings = [
                {
                    "month": r.month,
                    "subsidy_fen": int(r.subsidy_fen),
                    "subsidy_rm": round(r.subsidy_fen / 100, 2),
                    "billed_fen": int(r.billed_fen),
                    "billed_rm": round(r.billed_fen / 100, 2),
                }
                for r in monthly_rows.fetchall()
            ]

            # 按项目汇总
            program_rows = await db.execute(
                text("""
                    SELECT
                        program,
                        COUNT(*) AS cnt,
                        COALESCE(SUM(subsidy_amount_fen), 0) AS total_saved_fen
                    FROM tenant_subsidies
                    WHERE tenant_id = :tid
                    GROUP BY program
                    ORDER BY total_saved_fen DESC
                """),
                {"tid": tenant_id},
            )
            program_summary = [
                {
                    "program": r.program,
                    "count": int(r.cnt),
                    "total_saved_fen": int(r.total_saved_fen),
                    "total_saved_rm": round(r.total_saved_fen / 100, 2),
                }
                for r in program_rows.fetchall()
            ]

        except Exception as exc:
            log.warning("subsidy_utilization_query_failed", error=str(exc))
            active_subsidies = []
            total_saved_fen = 0
            total_billed_fen = 0
            total_payable_fen = 0
            monthly_savings = []
            program_summary = []

        result = {
            "has_active_subsidy": len(active_subsidies) > 0,
            "active_subsidies": active_subsidies,
            "total_saved_fen": total_saved_fen,
            "total_saved_rm": round(total_saved_fen / 100, 2),
            "total_billed_fen": total_billed_fen,
            "total_billed_rm": round(total_billed_fen / 100, 2),
            "total_payable_fen": total_payable_fen,
            "total_payable_rm": round(total_payable_fen / 100, 2),
            "monthly_savings": monthly_savings,
            "program_summary": program_summary,
        }

        log.info(
            "my_dashboard.subsidy_utilization_complete",
            has_active=len(active_subsidies) > 0,
            total_saved_fen=total_saved_fen,
        )
        return result

    async def get_multi_currency_report(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """多币种财务汇总报告

        适用于在中国和马来西亚同时运营的品牌，汇总 CNY 和 MYR 的收入报表。

        Args:
            tenant_id: 商户 UUID.
            db: 数据库会话.

        Returns:
            {
                currencies: {
                    CNY: { total_revenue_fen, transaction_count, stores },
                    MYR: { total_revenue_fen, transaction_count, stores },
                },
                consolidated: {
                    total_cny_fen, total_myr_fen,
                    total_cny_rm, total_myr_rm,
                    grand_total_myr_fen, grand_total_myr_rm,
                },
                store_breakdown: [{ store_id, store_name, currency, revenue_fen, ... }],
                exchange_rate: { cny_to_myr, myr_to_cny, note },
            }
        """
        log = logger.bind(tenant_id=tenant_id)
        log.info("my_dashboard.multi_currency")

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        s.id AS store_id,
                        s.name AS store_name,
                        s.country_code,
                        s.currency,
                        COUNT(o.id) AS transaction_count,
                        COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
                    FROM stores s
                    LEFT JOIN orders o ON o.store_id = s.id
                        AND o.tenant_id = s.tenant_id
                        AND o.status IN ('completed', 'settled')
                        AND o.is_deleted = FALSE
                    WHERE s.tenant_id = :tid
                      AND s.is_deleted = FALSE
                    GROUP BY s.id, s.name, s.country_code, s.currency
                    ORDER BY revenue_fen DESC
                """),
                {"tid": tenant_id},
            )
            store_data = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("multi_currency_query_failed", error=str(exc))
            store_data = []

        cny_total_fen = 0
        myr_total_fen = 0
        cny_stores: list[dict[str, Any]] = []
        myr_stores: list[dict[str, Any]] = []

        for row in store_data:
            currency = (row.get("currency") or "CNY").upper()
            revenue_fen = int(row.get("revenue_fen", 0) or 0)
            store_entry = {
                "store_id": str(row.get("store_id", "")),
                "store_name": row.get("store_name", ""),
                "country_code": row.get("country_code", ""),
                "currency": currency,
                "revenue_fen": revenue_fen,
                "revenue_rm": round(revenue_fen / 100, 2),
                "transaction_count": int(row.get("transaction_count", 0) or 0),
            }

            if currency == "MYR":
                myr_total_fen += revenue_fen
                myr_stores.append(store_entry)
            else:
                cny_total_fen += revenue_fen
                cny_stores.append(store_entry)

        # 汇总
        grand_total_myr_fen = myr_total_fen + int(cny_total_fen * CNY_TO_MYR)

        result = {
            "currencies": {
                "CNY": {
                    "total_revenue_fen": cny_total_fen,
                    "total_revenue_rm": round(cny_total_fen / 100, 2),
                    "transaction_count": sum(s["transaction_count"] for s in cny_stores),
                    "stores": len(cny_stores),
                },
                "MYR": {
                    "total_revenue_fen": myr_total_fen,
                    "total_revenue_rm": round(myr_total_fen / 100, 2),
                    "transaction_count": sum(s["transaction_count"] for s in myr_stores),
                    "stores": len(myr_stores),
                },
            },
            "consolidated": {
                "total_cny_fen": cny_total_fen,
                "total_cny_rm": round(cny_total_fen / 100, 2),
                "total_myr_fen": myr_total_fen,
                "total_myr_rm": round(myr_total_fen / 100, 2),
                "grand_total_myr_fen": grand_total_myr_fen,
                "grand_total_myr_rm": round(grand_total_myr_fen / 100, 2),
                "note": "CNY 金额按参考汇率 1 CNY = 0.65 MYR 转换为 MYR",
            },
            "store_breakdown": cny_stores + myr_stores,
            "exchange_rate": {
                "cny_to_myr": CNY_TO_MYR,
                "myr_to_cny": MYR_TO_CNY,
                "note": "参考汇率，实际对账使用银行/支付渠道实时汇率",
                "updated": datetime.now(timezone.utc).isoformat(),
            },
        }

        log.info(
            "my_dashboard.multi_currency_complete",
            cny_fen=cny_total_fen,
            myr_fen=myr_total_fen,
        )
        return result

    # ─── Internal Helpers ──────────────────────────────────────────

    @staticmethod
    async def _query_sales(
        tenant_id: str,
        date_from: str,
        date_to: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """查询指定日期范围内的销售汇总"""
        try:
            row = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(final_amount_fen), 0) AS total_fen,
                        COUNT(*) AS order_count,
                        COUNT(DISTINCT order_date) AS day_count
                    FROM orders
                    WHERE tenant_id = :tid
                      AND order_date >= :dfrom
                      AND order_date <= :dto
                      AND status IN ('completed', 'settled')
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "dfrom": date_from, "dto": date_to},
            )
            r = row.fetchone()
            return {
                "total_fen": int(r.total_fen) if r else 0,
                "order_count": int(r.order_count) if r else 0,
                "day_count": max(int(r.day_count) if r else 0, 1),
            }
        except Exception as exc:
            logger.warning("sales_query_failed", date_from=date_from, date_to=date_to, error=str(exc))
            return {"total_fen": 0, "order_count": 0, "day_count": 1}

    @staticmethod
    async def _calc_yoy_change(
        tenant_id: str,
        holiday_date: str,
        duration: int,
        prep_days: int,
        db: AsyncSession,
    ) -> float | None:
        """计算节假日的同比变化（上年同期）"""
        try:
            h_dt = datetime.strptime(holiday_date, "%Y-%m-%d").date()
            prev_year_start = h_dt.replace(year=h_dt.year - 1).isoformat()
            prev_year_end = (h_dt.replace(year=h_dt.year - 1) + timedelta(days=duration - 1)).isoformat()

            prev_row = await db.execute(
                text("""
                    SELECT COALESCE(AVG(final_amount_fen), 0) AS avg_revenue
                    FROM orders
                    WHERE tenant_id = :tid
                      AND order_date >= :dfrom
                      AND order_date <= :dto
                      AND status IN ('completed', 'settled')
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "dfrom": prev_year_start, "dto": prev_year_end},
            )
            prev_avg = int(prev_row.fetchone().avg_revenue) if prev_row else 0

            curr_row = await db.execute(
                text("""
                    SELECT COALESCE(AVG(final_amount_fen), 0) AS avg_revenue
                    FROM orders
                    WHERE tenant_id = :tid
                      AND order_date >= :dfrom
                      AND order_date <= :dto
                      AND status IN ('completed', 'settled')
                      AND is_deleted = FALSE
                """),
                {"tid": tenant_id, "dfrom": holiday_date, "dto": (h_dt + timedelta(days=duration - 1)).isoformat()},
            )
            curr_avg = int(curr_row.fetchone().avg_revenue) if curr_row else 0

            if prev_avg > 0:
                return round((curr_avg - prev_avg) / prev_avg * 100, 2)
            return None
        except Exception as exc:
            logger.warning("yoy_calc_failed", holiday=holiday_date, error=str(exc))
            return None
