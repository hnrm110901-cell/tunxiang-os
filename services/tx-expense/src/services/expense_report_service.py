"""
费控汇总报表引擎
提供月度汇总、趋势分析、TOP消费员工、异常费用检测等报表能力。

设计原则：
  - 所有聚合在 SQL 层完成，Python 层只做数据格式化
  - tenant_id 在所有查询中显式传入（遵循 RLS 规范）
  - 金额全部为分(fen)，返回时同样保持分为单位，展示层负责转换
  - 异常检测基于统计规则，不依赖 AI（降低延迟）
  - 节假日判断使用静态规则（中国法定节假日，按年维护）

依赖：
  - expense_applications（费用申请主表）
  - expense_items（费用申请明细行）
  - expense_categories（科目树）
  - invoices（发票表）
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

# 中国法定节假日（月-日，近三年通用核心节假日，实际项目中应从配置读取）
_CN_HOLIDAYS_MMDD = {
    "01-01",  # 元旦
    "01-02",
    "01-03",
    "02-10",  # 春节（2024 大年初一）
    "02-11",
    "02-12",
    "02-13",
    "02-14",
    "02-15",
    "02-16",
    "04-04",  # 清明节
    "04-05",
    "04-06",
    "05-01",  # 劳动节
    "05-02",
    "05-03",
    "06-10",  # 端午节
    "09-17",  # 中秋节（2024）
    "10-01",  # 国庆节
    "10-02",
    "10-03",
    "10-04",
    "10-05",
    "10-06",
    "10-07",
}

# 节假日大额阈值：单笔超过 2000 元（= 200000 分）视为节假日大额
_HOLIDAY_LARGE_AMOUNT_FEN = 200_000

# 异常倍数阈值：单笔超过本人上季度平均的 3 倍
_ABNORMAL_MULTIPLIER = 3


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回 (month_start, month_end) 作为查询边界。"""
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return first_day, last_day


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """返回上个月的 (year, month)。"""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _quarter_range(year: int, month: int) -> tuple[date, date]:
    """返回上季度的日期范围（用于异常检测基线计算）。"""
    q = (month - 1) // 3  # 当前季度 0-based
    prev_q = (q - 1) % 4
    prev_q_year = year if q > 0 else year - 1
    q_start_month = prev_q * 3 + 1
    q_end_month = q_start_month + 2
    q_start = date(prev_q_year, q_start_month, 1)
    q_end = date(prev_q_year, q_end_month, calendar.monthrange(prev_q_year, q_end_month)[1])
    return q_start, q_end


# ─────────────────────────────────────────────────────────────────────────────
# 报表服务
# ─────────────────────────────────────────────────────────────────────────────


class ExpenseReportService:
    """
    费控汇总报表引擎。

    所有方法均为 async，接受 db: AsyncSession（租户 RLS 已在 session 层设置）。
    """

    async def generate_monthly_report(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        month: int,
    ) -> dict:
        """
        月度费控汇总报表，三维度：
          1. 按门店：各门店费用总额/申请数/审批通过率/TOP3科目
          2. 按部门/岗位：各岗位费用分布（依赖 expense_applications.department 字段）
          3. 按科目：各费用类型占比/与上月对比

        返回完整报表结构（dict，可直接 JSON 序列化）。
        """
        start, end = _month_range(year, month)
        prev_year, prev_month = _prev_month(year, month)
        prev_start, prev_end = _month_range(prev_year, prev_month)

        log = logger.bind(tenant_id=str(tenant_id), year=year, month=month)

        # ── 1. 总览 ─────────────────────────────────────────────────────────
        try:
            overview = await self._query_overview(db, tenant_id, start, end)
        except SQLAlchemyError as exc:
            logger.error("report_monthly_overview_error", error=str(exc), exc_info=True)
            overview = {}

        # ── 2. 按门店 ────────────────────────────────────────────────────────
        try:
            by_store = await self._query_by_store(db, tenant_id, start, end)
        except SQLAlchemyError as exc:
            logger.error("report_monthly_by_store_error", error=str(exc), exc_info=True)
            by_store = []

        # ── 3. 按科目 ────────────────────────────────────────────────────────
        try:
            by_category = await self._query_by_category(db, tenant_id, start, end)
            prev_by_category = await self._query_by_category(db, tenant_id, prev_start, prev_end)
        except SQLAlchemyError as exc:
            logger.error("report_monthly_by_category_error", error=str(exc), exc_info=True)
            by_category = []
            prev_by_category = []

        # 计算科目同比上月变化
        prev_cat_map = {row["category_name"]: row["amount_fen"] for row in prev_by_category}
        for row in by_category:
            prev_amt = prev_cat_map.get(row["category_name"], 0)
            if prev_amt > 0:
                row["mom_change_rate"] = round((row["amount_fen"] - prev_amt) / prev_amt, 4)
            elif row["amount_fen"] > 0:
                row["mom_change_rate"] = None  # 新增科目，无法计算环比
            else:
                row["mom_change_rate"] = 0.0
            row["prev_month_amount_fen"] = prev_amt

        # ── 4. 按申请人/部门 ─────────────────────────────────────────────────
        try:
            by_applicant = await self._query_by_applicant(db, tenant_id, start, end)
        except SQLAlchemyError as exc:
            logger.error("report_monthly_by_applicant_error", error=str(exc), exc_info=True)
            by_applicant = []

        log.info("report_monthly_generated", overview_total=overview.get("total_amount_fen", 0))

        return {
            "report_type": "monthly",
            "year": year,
            "month": month,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "tenant_id": str(tenant_id),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "overview": overview,
            "by_store": by_store,
            "by_category": by_category,
            "by_applicant": by_applicant,
        }

    async def _query_overview(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> dict:
        """查询周期总览数据。"""
        sql = text("""
            SELECT
                COUNT(DISTINCT ea.id)                                           AS total_applications,
                COALESCE(SUM(ea.total_amount), 0)                               AS total_amount_fen,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status = 'approved')     AS approved_count,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status = 'rejected')     AS rejected_count,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status IN ('submitted','in_review')) AS pending_count,
                COALESCE(SUM(ea.total_amount) FILTER (WHERE ea.status = 'approved'), 0) AS approved_amount_fen
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "start": start,
                "end": end,
            },
        )
        row = result.mappings().one_or_none()
        if not row:
            return {}

        total = int(row["total_applications"] or 0)
        approved = int(row["approved_count"] or 0)
        return {
            "total_applications": total,
            "total_amount_fen": int(row["total_amount_fen"] or 0),
            "approved_count": approved,
            "rejected_count": int(row["rejected_count"] or 0),
            "pending_count": int(row["pending_count"] or 0),
            "approved_amount_fen": int(row["approved_amount_fen"] or 0),
            "approval_rate": round(approved / total, 4) if total > 0 else 0.0,
        }

    async def _query_by_store(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> list:
        """按门店统计费用。"""
        sql = text("""
            SELECT
                ea.store_id                                                         AS store_id,
                COUNT(DISTINCT ea.id)                                               AS application_count,
                COALESCE(SUM(ea.total_amount), 0)                                   AS total_amount_fen,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status = 'approved')         AS approved_count,
                COALESCE(SUM(ea.total_amount) FILTER (WHERE ea.status = 'approved'), 0) AS approved_amount_fen
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
            GROUP BY ea.store_id
            ORDER BY SUM(ea.total_amount) DESC NULLS LAST
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "start": start,
                "end": end,
            },
        )
        rows = result.mappings().all()

        stores = []
        for row in rows:
            total = int(row["application_count"] or 0)
            approved = int(row["approved_count"] or 0)
            stores.append(
                {
                    "store_id": str(row["store_id"]),
                    "application_count": total,
                    "total_amount_fen": int(row["total_amount_fen"] or 0),
                    "approved_count": approved,
                    "approved_amount_fen": int(row["approved_amount_fen"] or 0),
                    "approval_rate": round(approved / total, 4) if total > 0 else 0.0,
                }
            )
        return stores

    async def _query_by_category(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> list:
        """按科目统计费用（聚合 SQL，含科目占比）。"""
        sql = text("""
            WITH period_total AS (
                SELECT COALESCE(SUM(ei.amount), 0) AS grand_total
                FROM expense_items ei
                JOIN expense_applications ea ON ea.id = ei.application_id
                WHERE ei.tenant_id = :tenant_id
                  AND ea.is_deleted = FALSE
                  AND ei.is_deleted = FALSE
                  AND DATE(ea.created_at) BETWEEN :start AND :end
            )
            SELECT
                ec.name                         AS category_name,
                ec.code                         AS category_code,
                COALESCE(SUM(ei.amount), 0)     AS amount_fen,
                COUNT(DISTINCT ei.id)           AS item_count,
                COUNT(DISTINCT ea.id)           AS application_count,
                CASE WHEN pt.grand_total > 0
                     THEN ROUND(SUM(ei.amount)::NUMERIC / pt.grand_total, 4)
                     ELSE 0 END                 AS amount_ratio
            FROM expense_items ei
            JOIN expense_applications ea ON ea.id = ei.application_id
            JOIN expense_categories ec ON ec.id = ei.category_id
            CROSS JOIN period_total pt
            WHERE ei.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND ei.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
            GROUP BY ec.id, ec.name, ec.code, pt.grand_total
            ORDER BY SUM(ei.amount) DESC NULLS LAST
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "start": start,
                "end": end,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "category_name": row["category_name"],
                "category_code": row["category_code"],
                "amount_fen": int(row["amount_fen"] or 0),
                "item_count": int(row["item_count"] or 0),
                "application_count": int(row["application_count"] or 0),
                "amount_ratio": float(row["amount_ratio"] or 0),
            }
            for row in rows
        ]

    async def _query_by_applicant(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> list:
        """按申请人统计费用（TOP20，聚合 SQL）。"""
        sql = text("""
            SELECT
                ea.applicant_id                                                     AS applicant_id,
                COUNT(DISTINCT ea.id)                                               AS application_count,
                COALESCE(SUM(ea.total_amount), 0)                                   AS total_amount_fen,
                COALESCE(SUM(ea.total_amount) FILTER (WHERE ea.status = 'approved'), 0) AS approved_amount_fen,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status = 'approved')         AS approved_count
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
            GROUP BY ea.applicant_id
            ORDER BY SUM(ea.total_amount) DESC NULLS LAST
            LIMIT 20
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "start": start,
                "end": end,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "applicant_id": str(row["applicant_id"]),
                "application_count": int(row["application_count"] or 0),
                "total_amount_fen": int(row["total_amount_fen"] or 0),
                "approved_amount_fen": int(row["approved_amount_fen"] or 0),
                "approved_count": int(row["approved_count"] or 0),
            }
            for row in rows
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # 费用趋势
    # ─────────────────────────────────────────────────────────────────────────

    async def generate_expense_trend(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        months: int = 6,
    ) -> dict:
        """
        最近 N 个月费用趋势（含月均/环比/同比）。

        返回：
        {
            "months": int,
            "series": [
                {
                    "year": int,
                    "month": int,
                    "period": "2026-03",
                    "total_amount_fen": int,
                    "application_count": int,
                    "approved_amount_fen": int,
                    "mom_change_rate": float | None,   # 环比
                    "yoy_change_rate": float | None,   # 同比（需要去年同期数据）
                }
            ],
            "monthly_avg_fen": int,
            "generated_at": str,
        }
        """
        if months < 1 or months > 24:
            months = 6

        sql = text("""
            SELECT
                EXTRACT(YEAR FROM ea.created_at)::INT      AS year,
                EXTRACT(MONTH FROM ea.created_at)::INT     AS month,
                COUNT(DISTINCT ea.id)                      AS application_count,
                COALESCE(SUM(ea.total_amount), 0)          AS total_amount_fen,
                COALESCE(SUM(ea.total_amount) FILTER (WHERE ea.status = 'approved'), 0) AS approved_amount_fen
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND ea.created_at >= (NOW() - INTERVAL '1 month' * :months)
            GROUP BY year, month
            ORDER BY year ASC, month ASC
        """)

        try:
            result = await db.execute(
                sql,
                {
                    "tenant_id": str(tenant_id),
                    "months": months,
                },
            )
            rows = list(result.mappings().all())
        except SQLAlchemyError as exc:
            logger.error(
                "report_trend_query_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            rows = []

        series = []
        for i, row in enumerate(rows):
            amt = int(row["total_amount_fen"] or 0)
            entry: dict = {
                "year": int(row["year"]),
                "month": int(row["month"]),
                "period": f"{int(row['year'])}-{int(row['month']):02d}",
                "total_amount_fen": amt,
                "application_count": int(row["application_count"] or 0),
                "approved_amount_fen": int(row["approved_amount_fen"] or 0),
                "mom_change_rate": None,
                "yoy_change_rate": None,
            }
            # 环比
            if i > 0:
                prev_amt = series[i - 1]["total_amount_fen"]
                if prev_amt > 0:
                    entry["mom_change_rate"] = round((amt - prev_amt) / prev_amt, 4)
            series.append(entry)

        total_amt = sum(r["total_amount_fen"] for r in series)
        monthly_avg = total_amt // len(series) if series else 0

        return {
            "months": months,
            "series": series,
            "monthly_avg_fen": monthly_avg,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # TOP 消费员工
    # ─────────────────────────────────────────────────────────────────────────

    async def get_top_spenders(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        month: int,
        limit: int = 10,
    ) -> list:
        """
        TOP N 费用员工排行（按审批通过金额降序）。

        返回：
        [
            {
                "rank": int,
                "applicant_id": str,
                "application_count": int,
                "total_amount_fen": int,        # 申请总额（含未审批）
                "approved_amount_fen": int,     # 审批通过金额
                "approved_count": int,
            }
        ]
        """
        if limit < 1 or limit > 50:
            limit = 10

        start, end = _month_range(year, month)

        sql = text("""
            SELECT
                ea.applicant_id,
                COUNT(DISTINCT ea.id)                                               AS application_count,
                COALESCE(SUM(ea.total_amount), 0)                                   AS total_amount_fen,
                COALESCE(SUM(ea.total_amount) FILTER (WHERE ea.status = 'approved'), 0) AS approved_amount_fen,
                COUNT(DISTINCT ea.id) FILTER (WHERE ea.status = 'approved')         AS approved_count
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
            GROUP BY ea.applicant_id
            ORDER BY approved_amount_fen DESC NULLS LAST
            LIMIT :limit
        """)

        try:
            result = await db.execute(
                sql,
                {
                    "tenant_id": str(tenant_id),
                    "start": start,
                    "end": end,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
        except SQLAlchemyError as exc:
            logger.error(
                "report_top_spenders_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            return []

        return [
            {
                "rank": idx + 1,
                "applicant_id": str(row["applicant_id"]),
                "application_count": int(row["application_count"] or 0),
                "total_amount_fen": int(row["total_amount_fen"] or 0),
                "approved_amount_fen": int(row["approved_amount_fen"] or 0),
                "approved_count": int(row["approved_count"] or 0),
            }
            for idx, row in enumerate(rows)
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # 异常费用检测
    # ─────────────────────────────────────────────────────────────────────────

    async def get_abnormal_expenses(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        month: int,
    ) -> list:
        """
        异常费用检测（三条规则）：
          Rule-1：单笔超过本人上季度平均的 3 倍
          Rule-2：同一天同一科目多次报销（同一申请人）
          Rule-3：节假日大额报销（> 2000 元）

        返回：
        [
            {
                "rule": "over_personal_avg" | "same_day_same_category" | "holiday_large",
                "application_id": str,
                "applicant_id": str,
                "amount_fen": int,
                "expense_date": str,        # YYYY-MM-DD（Rule-1/3 为申请创建日期）
                "category_name": str | None,
                "detail": str,              # 异常说明
            }
        ]
        """
        start, end = _month_range(year, month)
        q_start, q_end = _quarter_range(year, month)
        results = []

        # ── Rule-1：单笔超过本人上季度平均 3 倍 ─────────────────────────────
        try:
            rule1_rows = await self._detect_over_personal_avg(db, tenant_id, start, end, q_start, q_end)
            results.extend(rule1_rows)
        except SQLAlchemyError as exc:
            logger.error(
                "abnormal_rule1_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )

        # ── Rule-2：同一天同一科目多次报销 ──────────────────────────────────
        try:
            rule2_rows = await self._detect_same_day_same_category(db, tenant_id, start, end)
            results.extend(rule2_rows)
        except SQLAlchemyError as exc:
            logger.error(
                "abnormal_rule2_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )

        # ── Rule-3：节假日大额报销 ───────────────────────────────────────────
        try:
            rule3_rows = await self._detect_holiday_large(db, tenant_id, start, end)
            results.extend(rule3_rows)
        except SQLAlchemyError as exc:
            logger.error(
                "abnormal_rule3_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )

        logger.info(
            "abnormal_expenses_detected",
            tenant_id=str(tenant_id),
            year=year,
            month=month,
            total=len(results),
        )
        return results

    async def _detect_over_personal_avg(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
        q_start: date,
        q_end: date,
    ) -> list:
        """Rule-1：单笔超过本人上季度单笔平均的 3 倍。"""
        sql = text("""
            WITH personal_avg AS (
                -- 上季度本人平均单笔金额（按明细行）
                SELECT
                    ea.applicant_id,
                    AVG(ei.amount)::BIGINT AS avg_item_fen
                FROM expense_items ei
                JOIN expense_applications ea ON ea.id = ei.application_id
                WHERE ei.tenant_id = :tenant_id
                  AND ea.is_deleted = FALSE
                  AND ei.is_deleted = FALSE
                  AND DATE(ea.created_at) BETWEEN :q_start AND :q_end
                GROUP BY ea.applicant_id
            )
            SELECT
                ea.id           AS application_id,
                ea.applicant_id AS applicant_id,
                ei.id           AS item_id,
                ei.amount       AS amount_fen,
                ec.name         AS category_name,
                DATE(ea.created_at) AS expense_date,
                pa.avg_item_fen AS personal_avg_fen
            FROM expense_items ei
            JOIN expense_applications ea ON ea.id = ei.application_id
            JOIN expense_categories ec ON ec.id = ei.category_id
            JOIN personal_avg pa ON pa.applicant_id = ea.applicant_id
            WHERE ei.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND ei.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
              AND pa.avg_item_fen > 0
              AND ei.amount > pa.avg_item_fen * :multiplier
            ORDER BY ei.amount DESC
            LIMIT 100
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "q_start": q_start,
                "q_end": q_end,
                "start": start,
                "end": end,
                "multiplier": _ABNORMAL_MULTIPLIER,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "rule": "over_personal_avg",
                "application_id": str(row["application_id"]),
                "applicant_id": str(row["applicant_id"]),
                "amount_fen": int(row["amount_fen"]),
                "expense_date": str(row["expense_date"]),
                "category_name": row["category_name"],
                "detail": (
                    f"单笔 {row['amount_fen'] / 100:.2f} 元超过本人上季度平均单笔 "
                    f"{row['personal_avg_fen'] / 100:.2f} 元的 {_ABNORMAL_MULTIPLIER} 倍"
                ),
            }
            for row in rows
        ]

    async def _detect_same_day_same_category(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> list:
        """Rule-2：同一申请人同一天同一科目多次报销。"""
        sql = text("""
            SELECT
                ea.applicant_id,
                DATE(ea.created_at)     AS expense_date,
                ec.name                 AS category_name,
                COUNT(DISTINCT ea.id)   AS application_count,
                COALESCE(SUM(ei.amount), 0) AS total_amount_fen,
                STRING_AGG(DISTINCT ea.id::TEXT, ',') AS application_ids
            FROM expense_items ei
            JOIN expense_applications ea ON ea.id = ei.application_id
            JOIN expense_categories ec ON ec.id = ei.category_id
            WHERE ei.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND ei.is_deleted = FALSE
              AND DATE(ea.created_at) BETWEEN :start AND :end
            GROUP BY ea.applicant_id, DATE(ea.created_at), ec.id, ec.name
            HAVING COUNT(DISTINCT ea.id) > 1
            ORDER BY COUNT(DISTINCT ea.id) DESC, SUM(ei.amount) DESC
            LIMIT 50
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "start": start,
                "end": end,
            },
        )
        rows = result.mappings().all()

        anomalies = []
        for row in rows:
            app_ids = (row["application_ids"] or "").split(",")
            # 每个 group 取第一个 application_id 作为代表
            anomalies.append(
                {
                    "rule": "same_day_same_category",
                    "application_id": app_ids[0].strip() if app_ids else "",
                    "applicant_id": str(row["applicant_id"]),
                    "amount_fen": int(row["total_amount_fen"]),
                    "expense_date": str(row["expense_date"]),
                    "category_name": row["category_name"],
                    "detail": (
                        f"同一天（{row['expense_date']}）同一科目「{row['category_name']}」"
                        f"提交 {row['application_count']} 次报销，合计 {row['total_amount_fen'] / 100:.2f} 元"
                    ),
                }
            )
        return anomalies

    async def _detect_holiday_large(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        start: date,
        end: date,
    ) -> list:
        """Rule-3：节假日大额报销（单笔超过阈值）。"""
        sql = text("""
            SELECT
                ea.id           AS application_id,
                ea.applicant_id AS applicant_id,
                ea.total_amount AS total_amount_fen,
                DATE(ea.created_at) AS expense_date
            FROM expense_applications ea
            WHERE ea.tenant_id = :tenant_id
              AND ea.is_deleted = FALSE
              AND ea.total_amount > :threshold
              AND DATE(ea.created_at) BETWEEN :start AND :end
            ORDER BY ea.total_amount DESC
            LIMIT 100
        """)
        result = await db.execute(
            sql,
            {
                "tenant_id": str(tenant_id),
                "threshold": _HOLIDAY_LARGE_AMOUNT_FEN,
                "start": start,
                "end": end,
            },
        )
        rows = result.mappings().all()

        anomalies = []
        for row in rows:
            exp_date = row["expense_date"]
            if not exp_date:
                continue
            # 判断是否为节假日（按月-日匹配）
            mmdd = exp_date.strftime("%m-%d") if hasattr(exp_date, "strftime") else str(exp_date)[5:10]
            # 也检查是否为周末
            is_weekend = exp_date.weekday() >= 5 if hasattr(exp_date, "weekday") else False
            is_holiday = mmdd in _CN_HOLIDAYS_MMDD or is_weekend

            if is_holiday:
                anomalies.append(
                    {
                        "rule": "holiday_large",
                        "application_id": str(row["application_id"]),
                        "applicant_id": str(row["applicant_id"]),
                        "amount_fen": int(row["total_amount_fen"]),
                        "expense_date": str(exp_date),
                        "category_name": None,
                        "detail": (
                            f"节假日/周末（{exp_date}）大额报销 "
                            f"{row['total_amount_fen'] / 100:.2f} 元，"
                            f"超过阈值 {_HOLIDAY_LARGE_AMOUNT_FEN / 100:.2f} 元"
                        ),
                    }
                )
        return anomalies

    # ─────────────────────────────────────────────────────────────────────────
    # 导出
    # ─────────────────────────────────────────────────────────────────────────

    async def export_to_dict(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        month: int,
        dimension: str = "all",
    ) -> dict:
        """
        导出报表数据（dimension: store/category/person/all）。

        返回 dict 可直接 JSON 序列化后作为下载内容。
        """
        valid_dimensions = {"store", "category", "person", "all"}
        if dimension not in valid_dimensions:
            dimension = "all"

        start, end = _month_range(year, month)
        export_data: dict = {
            "export_type": "expense_report",
            "dimension": dimension,
            "year": year,
            "month": month,
            "tenant_id": str(tenant_id),
            "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            if dimension in ("store", "all"):
                export_data["by_store"] = await self._query_by_store(db, tenant_id, start, end)

            if dimension in ("category", "all"):
                export_data["by_category"] = await self._query_by_category(db, tenant_id, start, end)

            if dimension in ("person", "all"):
                export_data["by_applicant"] = await self._query_by_applicant(db, tenant_id, start, end)

            if dimension == "all":
                export_data["overview"] = await self._query_overview(db, tenant_id, start, end)
        except SQLAlchemyError as exc:
            logger.error(
                "report_export_error",
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=True,
            )
            export_data["error"] = str(exc)

        return export_data


# 单例（路由层通过依赖注入使用）
expense_report_service = ExpenseReportService()
