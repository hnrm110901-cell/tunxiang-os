"""Boss BI 集团驾驶舱服务层

总部视角多品牌/多门店聚合分析：
  - 今日集团核心KPI（营业额/客单价/翻台率/毛利率）
  - 多品牌对标排名（含环比增长）
  - 异常门店预警（偏差 > threshold 触发）
  - AI 每日简报（仅在有预警或营业额变化 > 15% 时调用 ModelRouter）

金额单位：分(fen)，前端展示时 /100 转元。
AI 调用约束（CLAUDE.md）：
  - 所有 AI 调用通过 ModelRouter.complete(task_type, prompt)
  - 无预警且营业额变化 ≤ 15% 时跳过 AI 调用，节省成本
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ─── 触发 AI 摘要的营业额变化阈值 ───
AI_REVENUE_CHANGE_THRESHOLD_PCT = 15.0
# ─── 默认预警偏差阈值 ───
DEFAULT_ALERT_THRESHOLD_PCT = 0.20


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  数据模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GroupKPISnapshot(BaseModel):
    """集团今日 KPI 快照"""

    tenant_id: str
    date: str = Field(description="业务日期 ISO8601 格式，如 2026-03-31")
    total_revenue_fen: int = Field(ge=0, description="今日集团总营业额（分）")
    avg_ticket_fen: int = Field(ge=0, description="集团平均客单价（分）")
    table_turnover_rate: float = Field(ge=0.0, description="集团平均翻台率（次/天）")
    gross_margin_pct: float = Field(ge=0.0, le=100.0, description="集团平均毛利率（%）")
    active_store_count: int = Field(ge=0, description="今日有营业记录的门店数")
    alert_count: int = Field(ge=0, description="今日预警门店数")
    revenue_wow_pct: Optional[float] = Field(default=None, description="营业额周同比变化（%），无上期数据时为 None")


class BrandPerformance(BaseModel):
    """单品牌经营表现（用于多品牌排名）"""

    rank: int = Field(ge=1, description="排名（从 1 开始）")
    brand_id: str
    brand_name: str
    revenue_fen: int = Field(ge=0, description="区间内总营业额（分）")
    order_count: int = Field(ge=0, description="区间内总订单数")
    avg_ticket_fen: int = Field(ge=0, description="平均客单价（分）")
    store_count: int = Field(ge=1, description="品牌下门店数")
    revenue_wow_pct: Optional[float] = Field(default=None, description="环比增长率（%），无上期数据时为 None")


class StoreAlert(BaseModel):
    """门店异常预警"""

    store_id: str
    store_name: str
    brand_id: Optional[str] = None
    brand_name: Optional[str] = None
    metric_name: str = Field(description="预警指标：revenue / ticket / turnover / margin")
    actual_value: float = Field(ge=0, description="实际值")
    baseline_value: float = Field(ge=0, description="基准值（品牌/集团均值）")
    deviation_pct: float = Field(description="偏差百分比，负数表示低于基准")
    severity: str = Field(description="严重程度：critical / warning / info")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助纯函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calc_deviation_pct(actual: float, baseline: float) -> Optional[float]:
    """计算实际值相对基准的偏差百分比。

    Args:
        actual: 实际值
        baseline: 基准值（品牌/集团均值）

    Returns:
        偏差百分比（负数表示低于基准），baseline 为 0 时返回 None
    """
    if baseline <= 0:
        return None
    return round((actual - baseline) / baseline * 100, 1)


def _determine_severity(deviation_pct: float) -> str:
    """根据偏差幅度确定预警级别。

    Rules:
      deviation ≤ -40% → critical
      deviation ≤ -20% → warning
      otherwise        → info（内部兜底，调用方不应传入无偏差值）
    """
    if deviation_pct <= -40.0:
        return "critical"
    if deviation_pct <= -20.0:
        return "warning"
    return "info"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GroupDashboardService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GroupDashboardService:
    """集团驾驶舱数据聚合服务。

    db=None 时返回空值降级数据（零值/空列表），不使用硬编码 mock。
    """

    # ── 今日集团核心 KPI ──────────────────────────────────

    async def get_today_group_kpi(
        self,
        tenant_id: str,
        db: Optional[AsyncSession],
    ) -> GroupKPISnapshot:
        """聚合今日集团核心 KPI 快照。

        Args:
            tenant_id: 租户 ID
            db: 数据库会话，None 时使用 mock 数据

        Returns:
            GroupKPISnapshot
        """
        log.info("group_dashboard.get_today_group_kpi", tenant_id=tenant_id)
        today = datetime.now().date()

        if db is None:
            return self._degraded_group_kpi(tenant_id, today.isoformat())

        try:
            row = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(o.final_amount_fen), 0)          AS total_revenue_fen,
                        COUNT(o.id)                                    AS total_orders,
                        CASE WHEN COUNT(o.id) > 0
                             THEN COALESCE(SUM(o.final_amount_fen), 0) / COUNT(o.id)
                             ELSE 0 END                                AS avg_ticket_fen,
                        COUNT(DISTINCT o.store_id)                     AS active_stores
                    FROM orders o
                    WHERE o.tenant_id  = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :today
                      AND o.status     = 'paid'
                      AND o.is_deleted = FALSE
                """),
                {"tenant_id": tenant_id, "today": today},
            )
            rev_row = row.mappings().first()

            # 翻台率：今日桌台总会话数 / 总桌台数
            table_row = await db.execute(
                text("""
                    SELECT
                        COUNT(ts.id)                              AS session_count,
                        COALESCE(MAX(s.table_count), 1)           AS total_tables
                    FROM table_sessions ts
                    JOIN stores s ON s.tenant_id = ts.tenant_id
                    WHERE ts.tenant_id  = :tenant_id
                      AND DATE(ts.started_at) = :today
                      AND ts.is_deleted = FALSE
                """),
                {"tenant_id": tenant_id, "today": today},
            )
            tbl = table_row.mappings().first()

            # 毛利率：(营收 - 食材成本) / 营收
            margin_row = await db.execute(
                text("""
                    SELECT
                        COALESCE(SUM(oi.cost_fen * oi.quantity), 0) AS total_cost_fen
                    FROM order_items oi
                    JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
                    WHERE o.tenant_id  = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :today
                      AND o.status     = 'paid'
                      AND oi.is_deleted = FALSE
                """),
                {"tenant_id": tenant_id, "today": today},
            )
            margin_data = margin_row.mappings().first()

            # 今日预警数（通过 get_store_alerts 统计）
            alerts = await self.get_store_alerts(tenant_id, DEFAULT_ALERT_THRESHOLD_PCT, db)

            # 上周同日营收（用于周同比）
            last_week = today - timedelta(days=7)
            wow_row = await db.execute(
                text("""
                    SELECT COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
                    FROM orders o
                    WHERE o.tenant_id  = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) = :last_week
                      AND o.status     = 'paid'
                      AND o.is_deleted = FALSE
                """),
                {"tenant_id": tenant_id, "last_week": last_week},
            )
            wow_data = wow_row.mappings().first()

            # 组装数据
            total_revenue = int(rev_row["total_revenue_fen"]) if rev_row else 0
            total_orders = int(rev_row["total_orders"]) if rev_row else 0
            avg_ticket = int(rev_row["avg_ticket_fen"]) if rev_row else 0
            active_stores = int(rev_row["active_stores"]) if rev_row else 0

            sessions = int(tbl["session_count"]) if tbl else 0
            tables = int(tbl["total_tables"]) if tbl else 1
            turnover_rate = round(sessions / tables, 2) if tables > 0 else 0.0

            total_cost = int(margin_data["total_cost_fen"]) if margin_data else 0
            margin_pct = round((total_revenue - total_cost) / total_revenue * 100, 1) if total_revenue > 0 else 0.0

            wow_revenue = int(wow_data["revenue_fen"]) if wow_data else 0
            revenue_wow = _calc_deviation_pct(total_revenue, wow_revenue)

            return GroupKPISnapshot(
                tenant_id=tenant_id,
                date=today.isoformat(),
                total_revenue_fen=total_revenue,
                avg_ticket_fen=avg_ticket,
                table_turnover_rate=turnover_rate,
                gross_margin_pct=max(0.0, min(margin_pct, 100.0)),
                active_store_count=active_stores,
                alert_count=len(alerts),
                revenue_wow_pct=revenue_wow,
            )

        except SQLAlchemyError:
            log.error(
                "group_dashboard.get_today_group_kpi.db_error",
                tenant_id=tenant_id,
                exc_info=True,
            )
            return GroupKPISnapshot(
                tenant_id=tenant_id,
                date=today.isoformat(),
                total_revenue_fen=0,
                avg_ticket_fen=0,
                table_turnover_rate=0.0,
                gross_margin_pct=0.0,
                active_store_count=0,
                alert_count=0,
            )

    # ── 多品牌排名 ─────────────────────────────────────────

    async def get_brand_ranking(
        self,
        tenant_id: str,
        days: int,
        db: Optional[AsyncSession],
    ) -> list[BrandPerformance]:
        """多品牌经营表现排名（按营业额倒序）。

        Args:
            tenant_id: 租户 ID
            days: 统计天数（7 / 30 等）
            db: 数据库会话，None 时使用 mock 数据

        Returns:
            list[BrandPerformance]，按营业额倒序，rank 从 1 开始
        """
        log.info("group_dashboard.get_brand_ranking", tenant_id=tenant_id, days=days)

        if db is None:
            return self._degraded_brand_ranking(tenant_id, days)

        today = datetime.now().date()
        start_date = today - timedelta(days=days - 1)
        prev_start = start_date - timedelta(days=days)
        prev_end = start_date - timedelta(days=1)

        try:
            # 当期品牌汇总
            row = await db.execute(
                text("""
                    SELECT
                        s.brand_id,
                        COALESCE(MAX(s.brand_name), s.brand_id)  AS brand_name,
                        COALESCE(SUM(o.final_amount_fen), 0)     AS revenue_fen,
                        COUNT(o.id)                              AS order_count,
                        COUNT(DISTINCT s.id)                     AS store_count,
                        CASE WHEN COUNT(o.id) > 0
                             THEN COALESCE(SUM(o.final_amount_fen), 0) / COUNT(o.id)
                             ELSE 0 END                          AS avg_ticket_fen
                    FROM stores s
                    LEFT JOIN orders o
                           ON o.store_id  = s.id
                          AND o.tenant_id = s.tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :today
                          AND o.status     = 'paid'
                          AND o.is_deleted = FALSE
                    WHERE s.tenant_id  = :tenant_id
                      AND s.is_deleted = FALSE
                      AND s.brand_id  IS NOT NULL
                    GROUP BY s.brand_id
                    ORDER BY revenue_fen DESC
                """),
                {"tenant_id": tenant_id, "start_date": start_date, "today": today},
            )
            current_brands = row.mappings().all()

            # 上期品牌营收（用于环比）
            prev_row = await db.execute(
                text("""
                    SELECT
                        s.brand_id,
                        COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen
                    FROM stores s
                    LEFT JOIN orders o
                           ON o.store_id  = s.id
                          AND o.tenant_id = s.tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :prev_start AND :prev_end
                          AND o.status     = 'paid'
                          AND o.is_deleted = FALSE
                    WHERE s.tenant_id  = :tenant_id
                      AND s.is_deleted = FALSE
                      AND s.brand_id  IS NOT NULL
                    GROUP BY s.brand_id
                """),
                {"tenant_id": tenant_id, "prev_start": prev_start, "prev_end": prev_end},
            )
            prev_map: dict[str, int] = {r["brand_id"]: int(r["revenue_fen"]) for r in prev_row.mappings().all()}

            results = []
            for idx, brand in enumerate(current_brands, start=1):
                current_rev = int(brand["revenue_fen"])
                prev_rev = prev_map.get(brand["brand_id"], 0)
                wow_pct = _calc_deviation_pct(current_rev, prev_rev)
                results.append(
                    BrandPerformance(
                        rank=idx,
                        brand_id=brand["brand_id"],
                        brand_name=brand["brand_name"],
                        revenue_fen=current_rev,
                        order_count=int(brand["order_count"]),
                        avg_ticket_fen=int(brand["avg_ticket_fen"]),
                        store_count=max(1, int(brand["store_count"])),
                        revenue_wow_pct=wow_pct,
                    )
                )
            return results

        except SQLAlchemyError:
            log.error(
                "group_dashboard.get_brand_ranking.db_error",
                tenant_id=tenant_id,
                exc_info=True,
            )
            return []

    # ── 异常门店预警 ───────────────────────────────────────

    async def get_store_alerts(
        self,
        tenant_id: str,
        threshold_pct: float,
        db: Optional[AsyncSession],
    ) -> list[StoreAlert]:
        """检测今日异常门店（营业额偏差超过阈值则触发预警）。

        Args:
            tenant_id: 租户 ID
            threshold_pct: 偏差阈值（0.20 = 低于集团均值 20% 触发）
            db: 数据库会话，None 时使用 mock 数据

        Returns:
            list[StoreAlert]，按偏差幅度倒序（最严重的在前）
        """
        log.info(
            "group_dashboard.get_store_alerts",
            tenant_id=tenant_id,
            threshold_pct=threshold_pct,
        )

        if db is None:
            return self._degraded_store_alerts(tenant_id, threshold_pct)

        today = datetime.now().date()

        try:
            # 查询今日各门店营业额
            row = await db.execute(
                text("""
                    SELECT
                        s.id            AS store_id,
                        s.store_name,
                        s.brand_id,
                        COALESCE(s.brand_name, '')            AS brand_name,
                        COALESCE(SUM(o.final_amount_fen), 0)  AS revenue_fen
                    FROM stores s
                    LEFT JOIN orders o
                           ON o.store_id  = s.id
                          AND o.tenant_id = s.tenant_id
                          AND COALESCE(o.biz_date, DATE(o.created_at)) = :today
                          AND o.status     = 'paid'
                          AND o.is_deleted = FALSE
                    WHERE s.tenant_id  = :tenant_id
                      AND s.is_deleted = FALSE
                    GROUP BY s.id, s.store_name, s.brand_id, s.brand_name
                """),
                {"tenant_id": tenant_id, "today": today},
            )
            stores = row.mappings().all()

            if not stores:
                return []

            # 计算集团均值作为基准
            revenues = [int(s["revenue_fen"]) for s in stores]
            baseline = sum(revenues) / len(revenues) if revenues else 0

            if baseline <= 0:
                return []

            alerts: list[StoreAlert] = []
            for store in stores:
                store_revenue = int(store["revenue_fen"])
                deviation = _calc_deviation_pct(store_revenue, baseline)

                if deviation is None:
                    continue

                # 低于基准 threshold_pct × 100% 时触发
                if deviation <= -(threshold_pct * 100):
                    alerts.append(
                        StoreAlert(
                            store_id=store["store_id"],
                            store_name=store["store_name"],
                            brand_id=store.get("brand_id"),
                            brand_name=store.get("brand_name") or None,
                            metric_name="revenue",
                            actual_value=float(store_revenue),
                            baseline_value=float(baseline),
                            deviation_pct=deviation,
                            severity=_determine_severity(deviation),
                        )
                    )

            # 按偏差幅度升序（最严重的偏差最小，排最前）
            alerts.sort(key=lambda a: a.deviation_pct)
            return alerts

        except SQLAlchemyError:
            log.error(
                "group_dashboard.get_store_alerts.db_error",
                tenant_id=tenant_id,
                exc_info=True,
            )
            return []

    # ── AI 每日简报 ────────────────────────────────────────

    async def get_ai_daily_brief(
        self,
        tenant_id: str,
        kpi: GroupKPISnapshot,
        alerts: list[StoreAlert],
        model_router: Any,
    ) -> str:
        """生成集团每日 AI 简报。

        触发条件（满足任一即调用 ModelRouter）：
          1. alerts 数量 > 0
          2. kpi.revenue_wow_pct 绝对值 > 15%

        AI 调用约束（CLAUDE.md）：
          - 通过 model_router.complete(task_type, prompt) 调用
          - model_router 为 None 时静默跳过，返回空字符串

        Args:
            tenant_id: 租户 ID
            kpi: 今日 KPI 快照
            alerts: 预警列表
            model_router: ModelRouter 实例（None 时跳过 AI 调用）

        Returns:
            AI 生成的简报文本，不触发或不可用时返回 ""
        """
        if model_router is None:
            log.warning(
                "group_dashboard.get_ai_daily_brief.model_router_not_available",
                tenant_id=tenant_id,
            )
            return ""

        # 判断是否需要触发 AI
        revenue_change_pct = abs(kpi.revenue_wow_pct or 0.0)
        should_call_ai = len(alerts) > 0 or revenue_change_pct > AI_REVENUE_CHANGE_THRESHOLD_PCT

        if not should_call_ai:
            log.debug(
                "group_dashboard.get_ai_daily_brief.skipped",
                tenant_id=tenant_id,
                alert_count=len(alerts),
                revenue_wow_pct=kpi.revenue_wow_pct,
            )
            return ""

        # 构建 prompt
        revenue_yuan = kpi.total_revenue_fen / 100
        ticket_yuan = kpi.avg_ticket_fen / 100
        wow_str = f"{kpi.revenue_wow_pct:+.1f}%" if kpi.revenue_wow_pct is not None else "N/A"

        alert_lines = []
        for a in alerts[:5]:  # 最多展示前 5 条预警
            alert_lines.append(f"- 门店【{a.store_name}】{a.metric_name} 偏差 {a.deviation_pct:+.1f}%（{a.severity}）")

        prompt = (
            f"请为集团今日经营情况生成一份简洁的中文执行摘要（150字内），"
            f"重点说明关键指标变化、异常原因分析和行动建议。\n\n"
            f"今日集团核心指标：\n"
            f"- 营业额：{revenue_yuan:.0f}元（周同比 {wow_str}）\n"
            f"- 客单价：{ticket_yuan:.1f}元\n"
            f"- 翻台率：{kpi.table_turnover_rate:.2f}次/天\n"
            f"- 毛利率：{kpi.gross_margin_pct:.1f}%\n"
            f"- 活跃门店：{kpi.active_store_count}家\n"
        )
        if alert_lines:
            prompt += f"\n今日预警（共 {len(alerts)} 条）：\n" + "\n".join(alert_lines) + "\n"

        log.info(
            "group_dashboard.get_ai_daily_brief.calling_model_router",
            tenant_id=tenant_id,
            alert_count=len(alerts),
            revenue_wow_pct=kpi.revenue_wow_pct,
        )

        try:
            summary: str = await model_router.complete(
                task_type="kpi_summary",
                prompt=prompt,
            )
            return summary or ""
        except (ValueError, RuntimeError):
            log.error(
                "group_dashboard.get_ai_daily_brief.ai_call_failed",
                tenant_id=tenant_id,
                exc_info=True,
            )
            return ""

    # ── 门店趋势（单店，供 API 路由直接调用） ──────────────

    async def get_store_trend(
        self,
        tenant_id: str,
        store_id: str,
        days: int,
        db: Optional[AsyncSession],
    ) -> list[dict]:
        """查询单店近 N 天营业额趋势。

        Args:
            tenant_id: 租户 ID
            store_id: 门店 ID
            days: 统计天数（最大 90）
            db: 数据库会话，None 时使用 mock 数据

        Returns:
            [{date, revenue_fen, order_count, avg_ticket_fen}] 按日期升序
        """
        log.info(
            "group_dashboard.get_store_trend",
            tenant_id=tenant_id,
            store_id=store_id,
            days=days,
        )
        days = min(days, 90)  # 上限 90 天

        if db is None:
            return self._degraded_store_trend(store_id, days)

        today = datetime.now().date()
        start_date = today - timedelta(days=days - 1)

        try:
            row = await db.execute(
                text("""
                    SELECT
                        COALESCE(o.biz_date, DATE(o.created_at))    AS biz_date,
                        COALESCE(SUM(o.final_amount_fen), 0)        AS revenue_fen,
                        COUNT(o.id)                                  AS order_count,
                        CASE WHEN COUNT(o.id) > 0
                             THEN COALESCE(SUM(o.final_amount_fen), 0) / COUNT(o.id)
                             ELSE 0 END                              AS avg_ticket_fen
                    FROM orders o
                    WHERE o.store_id   = :store_id
                      AND o.tenant_id  = :tenant_id
                      AND COALESCE(o.biz_date, DATE(o.created_at)) BETWEEN :start_date AND :today
                      AND o.status     = 'paid'
                      AND o.is_deleted = FALSE
                    GROUP BY biz_date
                    ORDER BY biz_date ASC
                """),
                {
                    "store_id": store_id,
                    "tenant_id": tenant_id,
                    "start_date": start_date,
                    "today": today,
                },
            )
            return [
                {
                    "date": str(r["biz_date"]),
                    "revenue_fen": int(r["revenue_fen"]),
                    "order_count": int(r["order_count"]),
                    "avg_ticket_fen": int(r["avg_ticket_fen"]),
                }
                for r in row.mappings().all()
            ]

        except SQLAlchemyError:
            log.error(
                "group_dashboard.get_store_trend.db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                exc_info=True,
            )
            return []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  无 DB 会话时的空值降级（db=None 时使用）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _degraded_group_kpi(tenant_id: str, date: str) -> GroupKPISnapshot:
        """db=None 时返回空 KPI 快照（无硬编码数据，零值降级）"""
        return GroupKPISnapshot(
            tenant_id=tenant_id,
            date=date,
            total_revenue_fen=0,
            avg_ticket_fen=0,
            table_turnover_rate=0.0,
            gross_margin_pct=0.0,
            active_store_count=0,
            alert_count=0,
            revenue_wow_pct=None,
        )

    @staticmethod
    def _degraded_brand_ranking(tenant_id: str, days: int) -> list[BrandPerformance]:
        """db=None 时返回空品牌排名列表（无硬编码数据）"""
        return []

    @staticmethod
    def _degraded_store_alerts(tenant_id: str, threshold_pct: float) -> list[StoreAlert]:
        """db=None 时返回空预警列表（无硬编码数据）"""
        return []

    @staticmethod
    def _degraded_store_trend(store_id: str, days: int) -> list[dict]:
        """db=None 时返回空趋势列表（无硬编码数据）"""
        return []
