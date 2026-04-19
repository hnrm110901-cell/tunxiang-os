"""HQ跨品牌分析Service — 总部多品牌对比与门店绩效矩阵

适用场景：屯象OS首批客户三品牌总部视角
  - 尝在一起、最黔线、尚宫厨

数据源：
  - ontology_snapshots 表（entity_type='order'|'store'，含 brand_id）
  - mv_store_pnl 物化视图（门店实时P&L）

金额单位：分(fen)，所有金额字段为整数。
所有查询带 tenant_id（RLS 保障）。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ─── 内部常量 ────────────────────────────────────────────────────────────────

_HEALTH_REVENUE_WEIGHT = 0.40
_HEALTH_MARGIN_WEIGHT = 0.40
_HEALTH_ACTIVE_STORE_WEIGHT = 0.20

# 健康分满分基准：营收达成率≥120%→40分，毛利率≥65%→40分，活跃门店100%→20分
_REVENUE_ACH_FULL_THRESHOLD = 1.20  # 达成率 >= 此值得满分
_MARGIN_FULL_THRESHOLD = 0.65  # 毛利率 >= 此值得满分

# 趋势判断阈值（环比当周 vs 上周）
_TREND_UP_THRESHOLD = 0.03  # +3% 以上为 up
_TREND_DOWN_THRESHOLD = -0.03  # -3% 以下为 down


# ─── 日期范围解析 ──────────────────────────────────────────────────────────


def _resolve_date_range(date_range: str) -> tuple[date, date]:
    """将 today/week/month 转为 (start_date, end_date)（含两端）。"""
    today = date.today()
    if date_range == "week":
        start = today - timedelta(days=6)
        return start, today
    if date_range == "month":
        start = today - timedelta(days=29)
        return start, today
    # 默认 today
    return today, today


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HQBrandAnalyticsService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class HQBrandAnalyticsService:
    """总部跨品牌分析服务。"""

    # ──────────────────────────────────────────────────────────────────────────
    # 1. 品牌总览
    # ──────────────────────────────────────────────────────────────────────────

    async def get_brands_overview(
        self,
        db: AsyncSession,
        tenant_ids: list[UUID],
        date_range: str = "today",
        brand_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """跨品牌总览：每个品牌一条汇总记录。

        数据来源：ontology_snapshots（entity_type='order' + entity_type='store'）
        健康分：营收达成率40% + 毛利率40% + 活跃门店比例20%

        Args:
            db:         AsyncSession（调用方已设置 app.tenant_id）
            tenant_ids: 允许查询的租户ID列表（超管可传多个）
            date_range: today / week / month
            brand_ids:  可选过滤，None 时返回所有品牌

        Returns:
            list of brand summary dicts，空数据时返回 []
        """
        start_date, end_date = _resolve_date_range(date_range)

        brand_filter_sql = ""
        params: dict[str, Any] = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "tenant_ids": [str(t) for t in tenant_ids],
        }
        if brand_ids:
            params["brand_ids"] = [str(b) for b in brand_ids]
            brand_filter_sql = "AND brand_id = ANY(:brand_ids::uuid[])"

        # ── 从 ontology_snapshots 聚合 order 快照（按品牌）──────────────────
        order_sql = text(f"""
            SELECT
                brand_id,
                SUM((metrics->>'total_revenue_fen')::BIGINT)        AS revenue_fen,
                SUM((metrics->>'total_count')::BIGINT)              AS order_count,
                AVG((metrics->>'avg_order_value_fen')::NUMERIC)     AS avg_order_fen,
                AVG((metrics->>'avg_gross_margin')::NUMERIC)        AS avg_gross_margin,
                COUNT(DISTINCT snapshot_date)                       AS days_count
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'order'
              AND snapshot_type = 'daily'
              AND brand_id IS NOT NULL
              AND store_id IS NULL
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              {brand_filter_sql}
            GROUP BY brand_id
        """)

        # ── 从 ontology_snapshots 聚合 store 快照（门店数）───────────────────
        store_sql = text(f"""
            SELECT
                brand_id,
                AVG((metrics->>'total_store_count')::NUMERIC)   AS store_count,
                AVG((metrics->>'active_count')::NUMERIC)        AS active_stores
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'store'
              AND snapshot_type = 'daily'
              AND brand_id IS NOT NULL
              AND store_id IS NULL
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              {brand_filter_sql}
            GROUP BY brand_id
        """)

        # ── 上一周期营收（环比基准）──────────────────────────────────────────
        period_days = (end_date - start_date).days + 1
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)
        prev_params: dict[str, Any] = {
            "start_date": prev_start.isoformat(),
            "end_date": prev_end.isoformat(),
            "tenant_ids": [str(t) for t in tenant_ids],
        }
        if brand_ids:
            prev_params["brand_ids"] = [str(b) for b in brand_ids]

        prev_sql = text(f"""
            SELECT
                brand_id,
                SUM((metrics->>'total_revenue_fen')::BIGINT) AS prev_revenue_fen
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'order'
              AND snapshot_type = 'daily'
              AND brand_id IS NOT NULL
              AND store_id IS NULL
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
              {brand_filter_sql}
            GROUP BY brand_id
        """)

        try:
            order_result = await db.execute(order_sql, params)
            store_result = await db.execute(store_sql, params)
            prev_result = await db.execute(prev_sql, prev_params)
        except SQLAlchemyError as exc:
            logger.error(
                "hq_brand_analytics.get_brands_overview.db_error",
                error=str(exc),
                date_range=date_range,
            )
            raise

        order_rows = {str(r["brand_id"]): r for r in order_result.mappings().all()}
        store_rows = {str(r["brand_id"]): r for r in store_result.mappings().all()}
        prev_rows = {str(r["brand_id"]): r for r in prev_result.mappings().all()}

        if not order_rows:
            return []

        results: list[dict[str, Any]] = []
        for brand_id_str, orow in order_rows.items():
            srow = store_rows.get(brand_id_str, {})
            prow = prev_rows.get(brand_id_str, {})

            revenue_fen = int(orow["revenue_fen"] or 0)
            prev_rev = int(prow.get("prev_revenue_fen") or 0)
            revenue_wow_pct = round((revenue_fen - prev_rev) / prev_rev, 4) if prev_rev > 0 else 0.0

            order_count = int(orow["order_count"] or 0)
            avg_order_fen = int(float(orow["avg_order_fen"] or 0))
            avg_gross_margin = float(orow["avg_gross_margin"] or 0.0)

            store_count = int(float(srow.get("store_count") or 0))
            active_stores = int(float(srow.get("active_stores") or 0))
            active_ratio = active_stores / store_count if store_count > 0 else 0.0

            # 健康分计算（0-100，各分项 0-1 再乘权重×100）
            revenue_ach_rate = min(revenue_wow_pct + 1.0, _REVENUE_ACH_FULL_THRESHOLD) / _REVENUE_ACH_FULL_THRESHOLD
            margin_score = min(avg_gross_margin, _MARGIN_FULL_THRESHOLD) / _MARGIN_FULL_THRESHOLD
            health_score = round(
                (
                    revenue_ach_rate * _HEALTH_REVENUE_WEIGHT
                    + margin_score * _HEALTH_MARGIN_WEIGHT
                    + active_ratio * _HEALTH_ACTIVE_STORE_WEIGHT
                )
                * 100
            )
            health_score = max(0, min(100, health_score))

            results.append(
                {
                    "brand_id": brand_id_str,
                    "revenue_fen": revenue_fen,
                    "revenue_wow_pct": revenue_wow_pct,
                    "order_count": order_count,
                    "avg_order_fen": avg_order_fen,
                    "store_count": store_count,
                    "active_stores": active_stores,
                    "health_score": health_score,
                }
            )

        logger.info(
            "hq_brand_analytics.get_brands_overview.ok",
            brand_count=len(results),
            date_range=date_range,
        )
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 2. 品牌下门店绩效
    # ──────────────────────────────────────────────────────────────────────────

    async def get_brand_store_performance(
        self,
        db: AsyncSession,
        tenant_ids: list[UUID],
        brand_id: UUID,
        snapshot_date: date,
        sort_by: str = "revenue_fen",
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """品牌下所有门店的绩效列表（分页）。

        数据来源：ontology_snapshots WHERE entity_type='store' AND store_id IS NOT NULL

        Returns:
            {"items": [...], "total": int, "page": int, "size": int}
        """
        _VALID_SORT = frozenset(["revenue_fen", "revenue_achievement_pct", "gross_margin_pct", "rank"])
        if sort_by not in _VALID_SORT:
            sort_by = "revenue_fen"

        offset = (page - 1) * size

        # 当日门店快照
        params: dict[str, Any] = {
            "tenant_ids": [str(t) for t in tenant_ids],
            "brand_id": str(brand_id),
            "snapshot_date": snapshot_date.isoformat(),
            "limit": size,
            "offset": offset,
        }

        # 前一天快照用于趋势判断
        prev_date = snapshot_date - timedelta(days=1)
        params_prev: dict[str, Any] = {
            "tenant_ids": [str(t) for t in tenant_ids],
            "brand_id": str(brand_id),
            "snapshot_date": prev_date.isoformat(),
        }

        today_sql = text("""
            SELECT
                store_id,
                metrics
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'store'
              AND snapshot_type = 'daily'
              AND brand_id = :brand_id::uuid
              AND store_id IS NOT NULL
              AND snapshot_date = :snapshot_date
              AND is_deleted = FALSE
        """)

        prev_sql = text("""
            SELECT
                store_id,
                (metrics->>'avg_daily_revenue_fen')::BIGINT AS prev_revenue_fen
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'store'
              AND snapshot_type = 'daily'
              AND brand_id = :brand_id::uuid
              AND store_id IS NOT NULL
              AND snapshot_date = :snapshot_date
              AND is_deleted = FALSE
        """)

        # 该品牌门店目标营收（从 stores 表，缺失时为 0）
        target_sql = text("""
            SELECT id AS store_id, daily_revenue_target_fen
            FROM stores
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND brand_id = :brand_id
              AND is_deleted = FALSE
        """)

        try:
            today_result = await db.execute(today_sql, params)
            prev_result = await db.execute(prev_sql, params_prev)
            target_result = await db.execute(
                target_sql,
                {"tenant_ids": [str(t) for t in tenant_ids], "brand_id": str(brand_id)},
            )
        except SQLAlchemyError as exc:
            logger.error(
                "hq_brand_analytics.get_brand_store_performance.db_error",
                error=str(exc),
                brand_id=str(brand_id),
            )
            raise

        today_rows = today_result.mappings().all()
        prev_map = {str(r["store_id"]): int(r["prev_revenue_fen"] or 0) for r in prev_result.mappings().all()}

        # targets map：store_id → daily_revenue_target_fen（可能不存在该字段）
        target_map: dict[str, int] = {}
        for trow in target_result.mappings().all():
            val = trow.get("daily_revenue_target_fen")
            if val is not None:
                target_map[str(trow["store_id"])] = int(val)

        if not today_rows:
            return {"items": [], "total": 0, "page": page, "size": size}

        items: list[dict[str, Any]] = []
        for row in today_rows:
            store_id_str = str(row["store_id"])
            m = row["metrics"] if isinstance(row["metrics"], dict) else json.loads(row["metrics"] or "{}")

            revenue_fen = int(m.get("avg_daily_revenue_fen") or 0)
            target_fen = target_map.get(store_id_str, 0)
            revenue_achievement_pct = round(revenue_fen / target_fen, 4) if target_fen > 0 else 0.0

            # 毛利率：order 快照中的 avg_gross_margin（store 快照可能不含，降级为 0）
            gross_margin_pct = round(float(m.get("avg_gross_margin") or 0.0), 4)

            # 人工成本比（如有）
            labor_cost_ratio = round(float(m.get("labor_cost_ratio") or 0.0), 4)

            # 告警数（order 快照的 abnormal_count + margin_alert_count，store 快照无则 0）
            alert_count = int(m.get("abnormal_count") or 0) + int(m.get("margin_alert_count") or 0)

            # 趋势
            prev_rev = prev_map.get(store_id_str, 0)
            if revenue_fen > 0 and prev_rev > 0:
                change = (revenue_fen - prev_rev) / prev_rev
                if change >= _TREND_UP_THRESHOLD:
                    trend = "up"
                elif change <= _TREND_DOWN_THRESHOLD:
                    trend = "down"
                else:
                    trend = "flat"
            else:
                trend = "flat"

            items.append(
                {
                    "store_id": store_id_str,
                    "revenue_fen": revenue_fen,
                    "revenue_target_fen": target_fen,
                    "revenue_achievement_pct": revenue_achievement_pct,
                    "gross_margin_pct": gross_margin_pct,
                    "labor_cost_ratio": labor_cost_ratio,
                    "alert_count": alert_count,
                    "trend": trend,
                }
            )

        # 排序
        sort_key = (
            sort_by if sort_by in ("revenue_fen", "revenue_achievement_pct", "gross_margin_pct") else "revenue_fen"
        )
        items.sort(key=lambda x: x[sort_key], reverse=True)

        # 注入排名
        for idx, item in enumerate(items):
            item["rank"] = idx + 1

        total = len(items)
        paged_items = items[offset : offset + size]

        logger.info(
            "hq_brand_analytics.get_brand_store_performance.ok",
            brand_id=str(brand_id),
            snapshot_date=snapshot_date.isoformat(),
            total=total,
        )
        return {"items": paged_items, "total": total, "page": page, "size": size}

    # ──────────────────────────────────────────────────────────────────────────
    # 3. 多品牌对标
    # ──────────────────────────────────────────────────────────────────────────

    async def compare_brands(
        self,
        db: AsyncSession,
        tenant_ids: list[UUID],
        brand_ids: list[UUID],
        period: str = "week",
    ) -> dict[str, Any]:
        """多品牌四维度对标 + 7天日营收趋势折线图数据。

        四维度：revenue / gross_margin / avg_order / per_store_revenue
        趋势：最近7天每品牌每日营收

        Returns:
            {
              "dimensions": [
                {"dimension": "revenue", "rankings": [{"brand_id":..., "value":..., "rank":1},...]}
                ...
              ],
              "trend": {
                "dates": ["2026-04-06", ...],
                "brands": {"<brand_id>": [<rev_fen>, ...], ...}
              }
            }
        """
        start_date, end_date = _resolve_date_range(period)
        period_days = (end_date - start_date).days + 1

        params: dict[str, Any] = {
            "tenant_ids": [str(t) for t in tenant_ids],
            "brand_ids": [str(b) for b in brand_ids],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # 聚合：各品牌 order 快照（期间汇总）
        agg_sql = text("""
            SELECT
                brand_id,
                SUM((metrics->>'total_revenue_fen')::BIGINT)     AS revenue_fen,
                AVG((metrics->>'avg_gross_margin')::NUMERIC)      AS avg_gross_margin,
                AVG((metrics->>'avg_order_value_fen')::NUMERIC)   AS avg_order_fen
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'order'
              AND snapshot_type = 'daily'
              AND brand_id = ANY(:brand_ids::uuid[])
              AND store_id IS NULL
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            GROUP BY brand_id
        """)

        # 期间内各品牌门店数（取最新一天的快照）
        store_count_sql = text("""
            SELECT DISTINCT ON (brand_id)
                brand_id,
                (metrics->>'total_store_count')::NUMERIC AS store_count
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'store'
              AND snapshot_type = 'daily'
              AND brand_id = ANY(:brand_ids::uuid[])
              AND store_id IS NULL
              AND snapshot_date BETWEEN :start_date AND :end_date
              AND is_deleted = FALSE
            ORDER BY brand_id, snapshot_date DESC
        """)

        # 趋势：最近7天每天每品牌营收
        trend_start = end_date - timedelta(days=6)
        trend_sql = text("""
            SELECT
                brand_id,
                snapshot_date,
                SUM((metrics->>'total_revenue_fen')::BIGINT) AS revenue_fen
            FROM ontology_snapshots
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND entity_type = 'order'
              AND snapshot_type = 'daily'
              AND brand_id = ANY(:brand_ids::uuid[])
              AND store_id IS NULL
              AND snapshot_date BETWEEN :trend_start AND :trend_end
              AND is_deleted = FALSE
            GROUP BY brand_id, snapshot_date
            ORDER BY snapshot_date ASC
        """)
        trend_params = {**params, "trend_start": trend_start.isoformat(), "trend_end": end_date.isoformat()}

        try:
            agg_result = await db.execute(agg_sql, params)
            store_count_result = await db.execute(store_count_sql, params)
            trend_result = await db.execute(trend_sql, trend_params)
        except SQLAlchemyError as exc:
            logger.error(
                "hq_brand_analytics.compare_brands.db_error",
                error=str(exc),
                period=period,
            )
            raise

        agg_rows = {str(r["brand_id"]): r for r in agg_result.mappings().all()}
        store_count_map = {
            str(r["brand_id"]): int(float(r["store_count"] or 1)) for r in store_count_result.mappings().all()
        }

        if not agg_rows:
            return {"dimensions": [], "trend": {"dates": [], "brands": {}}}

        # ── 维度数据 ──────────────────────────────────────────────────────────
        brand_data: list[dict[str, Any]] = []
        for brand_id_str, row in agg_rows.items():
            sc = store_count_map.get(brand_id_str, 1)
            rev = int(row["revenue_fen"] or 0)
            per_store = rev // sc if sc > 0 else 0
            brand_data.append(
                {
                    "brand_id": brand_id_str,
                    "revenue": rev,
                    "gross_margin": round(float(row["avg_gross_margin"] or 0.0), 4),
                    "avg_order": int(float(row["avg_order_fen"] or 0)),
                    "per_store_revenue": per_store,
                }
            )

        def _rank_dimension(key: str) -> list[dict[str, Any]]:
            sorted_items = sorted(brand_data, key=lambda x: x[key], reverse=True)
            return [
                {"brand_id": item["brand_id"], "value": item[key], "rank": idx + 1}
                for idx, item in enumerate(sorted_items)
            ]

        dimensions = [
            {"dimension": "revenue", "rankings": _rank_dimension("revenue")},
            {"dimension": "gross_margin", "rankings": _rank_dimension("gross_margin")},
            {"dimension": "avg_order", "rankings": _rank_dimension("avg_order")},
            {"dimension": "per_store_revenue", "rankings": _rank_dimension("per_store_revenue")},
        ]

        # ── 趋势数据 ──────────────────────────────────────────────────────────
        dates: list[str] = [(trend_start + timedelta(days=i)).isoformat() for i in range(7)]
        brands_trend: dict[str, list[int]] = {str(b): [0] * 7 for b in brand_ids}
        date_index = {d: idx for idx, d in enumerate(dates)}

        for trow in trend_result.mappings().all():
            bid = str(trow["brand_id"])
            dstr = str(trow["snapshot_date"])
            idx = date_index.get(dstr)
            if idx is not None and bid in brands_trend:
                brands_trend[bid][idx] = int(trow["revenue_fen"] or 0)

        logger.info(
            "hq_brand_analytics.compare_brands.ok",
            brand_count=len(brand_data),
            period=period,
        )
        return {
            "dimensions": dimensions,
            "trend": {"dates": dates, "brands": brands_trend},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 4. 品牌P&L
    # ──────────────────────────────────────────────────────────────────────────

    async def get_brand_pnl(
        self,
        db: AsyncSession,
        tenant_ids: list[UUID],
        brand_id: UUID,
        year_month: str,
    ) -> dict[str, Any]:
        """品牌月度P&L：品牌汇总 + 各门店明细。

        数据来源：mv_store_pnl（stat_date 在 year_month 范围内）

        Args:
            year_month: "YYYY-MM" 格式

        Returns:
            {
              "summary": {revenue_fen, cost_fen, gross_profit_fen, gross_margin_pct,
                          net_profit_fen, net_margin_pct},
              "stores": [{store_id, ...同字段...}]
            }
        """
        try:
            year, month = int(year_month[:4]), int(year_month[5:7])
        except (ValueError, IndexError) as exc:
            raise ValueError(f"year_month 格式错误，需为 YYYY-MM，实际值：{year_month!r}") from exc

        # 月份起止日期
        import calendar

        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        params: dict[str, Any] = {
            "tenant_ids": [str(t) for t in tenant_ids],
            "brand_id": str(brand_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # 品牌汇总（按 brand_id 聚合 mv_store_pnl）
        brand_summary_sql = text("""
            SELECT
                SUM(gross_revenue_fen)      AS revenue_fen,
                SUM(cogs_fen)               AS cost_fen,
                SUM(gross_profit_fen)       AS gross_profit_fen,
                SUM(net_profit_fen)         AS net_profit_fen,
                SUM(order_count)            AS order_count
            FROM mv_store_pnl
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND brand_id = :brand_id::uuid
              AND stat_date BETWEEN :start_date AND :end_date
        """)

        # 各门店明细
        store_detail_sql = text("""
            SELECT
                store_id,
                SUM(gross_revenue_fen)      AS revenue_fen,
                SUM(cogs_fen)               AS cost_fen,
                SUM(gross_profit_fen)       AS gross_profit_fen,
                SUM(net_profit_fen)         AS net_profit_fen,
                SUM(order_count)            AS order_count,
                AVG(gross_margin_rate)      AS gross_margin_rate
            FROM mv_store_pnl
            WHERE tenant_id = ANY(:tenant_ids::uuid[])
              AND brand_id = :brand_id::uuid
              AND stat_date BETWEEN :start_date AND :end_date
            GROUP BY store_id
            ORDER BY SUM(gross_revenue_fen) DESC
        """)

        try:
            summary_result = await db.execute(brand_summary_sql, params)
            store_result = await db.execute(store_detail_sql, params)
        except SQLAlchemyError as exc:
            logger.error(
                "hq_brand_analytics.get_brand_pnl.db_error",
                error=str(exc),
                brand_id=str(brand_id),
                year_month=year_month,
            )
            raise

        srow = summary_result.mappings().one_or_none()
        store_rows = store_result.mappings().all()

        # 无数据时返回空结构
        if srow is None or (srow["revenue_fen"] is None):
            logger.info(
                "hq_brand_analytics.get_brand_pnl.no_data",
                brand_id=str(brand_id),
                year_month=year_month,
            )
            return {
                "summary": None,
                "stores": [],
                "year_month": year_month,
            }

        revenue_fen = int(srow["revenue_fen"] or 0)
        cost_fen = int(srow["cost_fen"] or 0)
        gross_profit_fen = int(srow["gross_profit_fen"] or 0)
        net_profit_fen = int(srow["net_profit_fen"] or 0)

        gross_margin_pct = round(gross_profit_fen / revenue_fen, 4) if revenue_fen > 0 else 0.0
        net_margin_pct = round(net_profit_fen / revenue_fen, 4) if revenue_fen > 0 else 0.0

        summary = {
            "revenue_fen": revenue_fen,
            "cost_fen": cost_fen,
            "gross_profit_fen": gross_profit_fen,
            "gross_margin_pct": gross_margin_pct,
            "net_profit_fen": net_profit_fen,
            "net_margin_pct": net_margin_pct,
        }

        stores: list[dict[str, Any]] = []
        for sdr in store_rows:
            s_rev = int(sdr["revenue_fen"] or 0)
            s_gp = int(sdr["gross_profit_fen"] or 0)
            s_np = int(sdr["net_profit_fen"] or 0)
            stores.append(
                {
                    "store_id": str(sdr["store_id"]),
                    "revenue_fen": s_rev,
                    "cost_fen": int(sdr["cost_fen"] or 0),
                    "gross_profit_fen": s_gp,
                    "gross_margin_pct": round(float(sdr["gross_margin_rate"] or 0.0), 4),
                    "net_profit_fen": s_np,
                    "net_margin_pct": round(s_np / s_rev, 4) if s_rev > 0 else 0.0,
                }
            )

        logger.info(
            "hq_brand_analytics.get_brand_pnl.ok",
            brand_id=str(brand_id),
            year_month=year_month,
            store_count=len(stores),
        )
        return {
            "summary": summary,
            "stores": stores,
            "year_month": year_month,
        }
