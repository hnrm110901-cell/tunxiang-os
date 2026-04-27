"""Agent 效果量化仪表盘 — 对标 Yum Byte "降缺货85%" 的ROI可视化

端点:
  GET  /api/v1/agent/roi/summary               — Agent整体ROI汇总
  GET  /api/v1/agent/roi/{agent_id}/detail      — 单个Agent效果明细（按日/周/月）
  GET  /api/v1/agent/roi/leaderboard            — Agent效能排行
  POST /api/v1/agent/roi/collect               — 每日采集并写入 agent_roi_metrics（由调度器触发）

核心指标:
  - 折扣守护: 拦截异常折扣金额(月累计) — 来源: orders.discount_amount_fen
  - 库存预警: 减少缺货次数/浪费金额 — 来源: agent_auto_executions
  - 排班优化: 节省人力小时数 — 来源: agent_auto_executions
  - 增长引擎: 召回会员带来的增量营收 — 来源: agent_auto_executions
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/roi", tags=["agent-roi"])

# ── Agent ROI 指标定义 ───────────────────────────────────────────────────────

AGENT_ROI_DEFINITIONS: dict[str, dict] = {
    "discount_guardian": {
        "name": "折扣守护",
        "metrics": [
            {
                "type": "intercepted_discount_fen",
                "label": "拦截异常折扣金额(分)",
                "unit": "分",
                "direction": "higher_better",
            },
            {"type": "intercept_count", "label": "拦截次数", "unit": "次", "direction": "higher_better"},
            {"type": "false_positive_rate", "label": "误拦截率", "unit": "%", "direction": "lower_better"},
        ],
    },
    "inventory_agent": {
        "name": "库存预警",
        "metrics": [
            {"type": "stockout_prevented_count", "label": "避免缺货次数", "unit": "次", "direction": "higher_better"},
            {"type": "waste_saved_fen", "label": "减少浪费金额(分)", "unit": "分", "direction": "higher_better"},
            {"type": "stockout_rate_reduction_pct", "label": "缺货率下降", "unit": "%", "direction": "higher_better"},
        ],
    },
    "scheduling_agent": {
        "name": "排班优化",
        "metrics": [
            {"type": "labor_hours_saved", "label": "节省人力小时", "unit": "小时", "direction": "higher_better"},
            {"type": "labor_cost_saved_fen", "label": "节省人力成本(分)", "unit": "分", "direction": "higher_better"},
            {"type": "coverage_rate_pct", "label": "排班覆盖率", "unit": "%", "direction": "higher_better"},
        ],
    },
    "member_insight": {
        "name": "增长引擎",
        "metrics": [
            {"type": "recalled_member_count", "label": "召回会员数", "unit": "人", "direction": "higher_better"},
            {"type": "incremental_revenue_fen", "label": "增量营收(分)", "unit": "分", "direction": "higher_better"},
            {"type": "churn_prevented_count", "label": "挽留流失会员数", "unit": "人", "direction": "higher_better"},
        ],
    },
    "smart_menu": {
        "name": "智能排菜",
        "metrics": [
            {
                "type": "menu_optimization_revenue_fen",
                "label": "排菜优化增收(分)",
                "unit": "分",
                "direction": "higher_better",
            },
            {"type": "poor_dish_removed_count", "label": "下架低效菜品数", "unit": "个", "direction": "higher_better"},
        ],
    },
    "serve_dispatch": {
        "name": "出餐调度",
        "metrics": [
            {
                "type": "avg_serve_time_reduction_sec",
                "label": "平均出餐时间缩短(秒)",
                "unit": "秒",
                "direction": "higher_better",
            },
            {
                "type": "overtime_prevented_count",
                "label": "避免超时出餐次数",
                "unit": "次",
                "direction": "higher_better",
            },
        ],
    },
    "finance_audit": {
        "name": "财务稽核",
        "metrics": [
            {"type": "anomaly_detected_fen", "label": "发现异常金额(分)", "unit": "分", "direction": "higher_better"},
            {"type": "audit_issue_count", "label": "发现问题数", "unit": "个", "direction": "higher_better"},
        ],
    },
    "store_inspect": {
        "name": "巡店质检",
        "metrics": [
            {"type": "violation_detected_count", "label": "发现违规次数", "unit": "次", "direction": "higher_better"},
            {"type": "rectification_rate_pct", "label": "整改完成率", "unit": "%", "direction": "higher_better"},
        ],
    },
    "private_ops": {
        "name": "私域运营",
        "metrics": [
            {"type": "campaign_sent_count", "label": "自动触达次数", "unit": "次", "direction": "higher_better"},
            {"type": "campaign_revenue_fen", "label": "营销带来营收(分)", "unit": "分", "direction": "higher_better"},
        ],
    },
}


# ── DB 依赖 ──────────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_roi_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    period: Literal["day", "week", "month"] = Query("month", description="统计周期"),
) -> dict:
    """Agent整体ROI汇总 — 各Agent关键指标的累计值。"""
    period_filter = {
        "day": "period_start >= CURRENT_DATE",
        "week": "period_start >= CURRENT_DATE - interval '7 days'",
        "month": "period_start >= CURRENT_DATE - interval '30 days'",
    }[period]

    try:
        result = await db.execute(
            text(f"""
            SELECT
                agent_id,
                metric_type,
                SUM(value)::float AS total_value,
                COUNT(*)::int AS data_points
            FROM agent_roi_metrics
            WHERE tenant_id = :tenant_id AND {period_filter}
            GROUP BY agent_id, metric_type
            ORDER BY agent_id, metric_type
        """),
            {"tenant_id": x_tenant_id},
        )
        rows = result.mappings().all()
    except (SQLAlchemyError, ConnectionError):
        rows = []

    # 按 agent_id 聚合
    agent_data: dict[str, dict] = {}
    for row in rows:
        aid = row["agent_id"]
        if aid not in agent_data:
            defn = AGENT_ROI_DEFINITIONS.get(aid, {"name": aid, "metrics": []})
            agent_data[aid] = {
                "agent_id": aid,
                "agent_name": defn["name"],
                "metrics": {},
                "total_value_fen": 0,
            }
        agent_data[aid]["metrics"][row["metric_type"]] = {
            "value": row["total_value"],
            "data_points": row["data_points"],
        }
        # 累计金额型指标（以 _fen 结尾的）
        if row["metric_type"].endswith("_fen"):
            agent_data[aid]["total_value_fen"] += int(row["total_value"])

    # 补充无数据的 Agent
    for aid, defn in AGENT_ROI_DEFINITIONS.items():
        if aid not in agent_data:
            agent_data[aid] = {
                "agent_id": aid,
                "agent_name": defn["name"],
                "metrics": {},
                "total_value_fen": 0,
            }

    # 总计
    total_value_fen = sum(a["total_value_fen"] for a in agent_data.values())

    return {
        "ok": True,
        "data": {
            "period": period,
            "total_value_fen": total_value_fen,
            "total_value_yuan": round(total_value_fen / 100, 2),
            "agents": list(agent_data.values()),
        },
    }


@router.get("/{agent_id}/detail")
async def get_agent_roi_detail(
    agent_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    granularity: Literal["day", "week", "month"] = Query("day", description="时间粒度"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
) -> dict:
    """单个Agent效果明细 — 按日/周/月的指标趋势。"""
    if agent_id not in AGENT_ROI_DEFINITIONS:
        return {"ok": False, "error": {"code": "UNKNOWN_AGENT", "message": f"未知Agent: {agent_id}"}}

    defn = AGENT_ROI_DEFINITIONS[agent_id]
    conditions = ["tenant_id = :tenant_id", "agent_id = :agent_id"]
    params: dict = {"tenant_id": x_tenant_id, "agent_id": agent_id}

    if start_date:
        conditions.append("period_start >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        conditions.append("period_end <= :end_date::date + interval '1 day'")
        params["end_date"] = end_date.isoformat()

    where = " AND ".join(conditions)

    # 按粒度聚合
    trunc = {"day": "day", "week": "week", "month": "month"}[granularity]
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        result = await db.execute(
            text(f"""
            SELECT
                date_trunc(:trunc, period_start) AS period,
                metric_type,
                SUM(value)::float AS total_value
            FROM agent_roi_metrics
            WHERE {where}
            GROUP BY period, metric_type
            ORDER BY period DESC, metric_type
            LIMIT :limit OFFSET :offset
        """),
            {**params, "trunc": trunc},
        )
        rows = result.mappings().all()
    except (SQLAlchemyError, ConnectionError):
        rows = []

    return {
        "ok": True,
        "data": {
            "agent_id": agent_id,
            "agent_name": defn["name"],
            "metric_definitions": defn["metrics"],
            "granularity": granularity,
            "items": [dict(r) for r in rows],
        },
    }


@router.get("/leaderboard")
async def get_agent_leaderboard(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    period: Literal["day", "week", "month"] = Query("month"),
) -> dict:
    """Agent效能排行 — 按金额价值排序。"""
    period_filter = {
        "day": "period_start >= CURRENT_DATE",
        "week": "period_start >= CURRENT_DATE - interval '7 days'",
        "month": "period_start >= CURRENT_DATE - interval '30 days'",
    }[period]

    try:
        result = await db.execute(
            text(f"""
            SELECT
                agent_id,
                SUM(value)::float AS total_value,
                COUNT(DISTINCT metric_type)::int AS metric_count,
                COUNT(*)::int AS data_points
            FROM agent_roi_metrics
            WHERE tenant_id = :tenant_id
              AND {period_filter}
              AND metric_type LIKE '%%_fen'
            GROUP BY agent_id
            ORDER BY total_value DESC
        """),
            {"tenant_id": x_tenant_id},
        )
        rows = result.mappings().all()
    except (SQLAlchemyError, ConnectionError):
        rows = []

    leaderboard = []
    for i, row in enumerate(rows, 1):
        defn = AGENT_ROI_DEFINITIONS.get(row["agent_id"], {"name": row["agent_id"]})
        leaderboard.append(
            {
                "rank": i,
                "agent_id": row["agent_id"],
                "agent_name": defn["name"],
                "total_value_fen": int(row["total_value"]),
                "total_value_yuan": round(row["total_value"] / 100, 2),
                "metric_count": row["metric_count"],
                "data_points": row["data_points"],
            }
        )

    return {
        "ok": True,
        "data": {
            "period": period,
            "leaderboard": leaderboard,
        },
    }


# ── 每日采集写入 ─────────────────────────────────────────────────────────────


@router.post("/collect")
async def collect_roi_metrics(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    target_date: date | None = Query(None, description="采集日期，默认昨日 YYYY-MM-DD"),
) -> dict:
    """每日采集 Agent ROI 指标并写入 agent_roi_metrics。

    幂等：已存在当日记录的 (agent_id, metric_type) 不重复写入。
    由调度器每日 05:00 触发（contrib recalc 04:00 之后）。

    数据来源：
    - discount_guardian: orders.discount_amount_fen（折扣守护实际处理的折扣金额）
    - 所有 Agent: agent_auto_executions（执行日志计数）
    """
    if target_date is None:
        from datetime import timedelta

        target_date = date.today() - timedelta(days=1)

    period_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    period_end = datetime.combine(target_date, datetime.max.time()).replace(tzinfo=timezone.utc)
    target_date_str = target_date.isoformat()

    # ── 幂等检查：若当日已有记录则跳过 ──────────────────────────────────────
    try:
        existing = await db.execute(
            text("""
            SELECT COUNT(*)::int FROM agent_roi_metrics
            WHERE tenant_id = :tid AND period_start::date = :d
        """),
            {"tid": x_tenant_id, "d": target_date_str},
        )
        if (existing.scalar() or 0) > 0:
            return {
                "ok": True,
                "data": {
                    "inserted_count": 0,
                    "skipped": True,
                    "reason": f"{target_date_str} 记录已存在，跳过采集",
                },
            }
    except SQLAlchemyError as exc:
        logger.warning("roi_collect_idempotency_check_failed", error=str(exc), exc_info=True)

    # ── 采集各 Agent 指标 ────────────────────────────────────────────────────
    metrics: list[dict] = []

    # 1. discount_guardian — 来源: orders 表
    try:
        r = await db.execute(
            text("""
            SELECT
                COALESCE(SUM(discount_amount_fen), 0)::bigint AS total_discount_fen,
                COUNT(*) FILTER (WHERE discount_amount_fen > 0)::int AS discount_order_count
            FROM orders
            WHERE tenant_id = :tid
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :d
              AND status = 'completed'
        """),
            {"tid": x_tenant_id, "d": target_date_str},
        )
        row = r.mappings().one()
        metrics.extend(
            [
                {
                    "agent_id": "discount_guardian",
                    "metric_type": "intercepted_discount_fen",
                    "value": row["total_discount_fen"],
                },
                {
                    "agent_id": "discount_guardian",
                    "metric_type": "intercept_count",
                    "value": row["discount_order_count"],
                },
            ]
        )
    except SQLAlchemyError as exc:
        logger.warning("roi_collect_discount_guardian_failed", error=str(exc), exc_info=True)

    # 2. 所有 Agent — 来源: agent_auto_executions（执行计数 + 结果聚合）
    try:
        r = await db.execute(
            text("""
            SELECT
                agent_id,
                COUNT(*)::int AS exec_count,
                COUNT(*) FILTER (WHERE status = 'executed')::int AS success_count,
                COUNT(*) FILTER (WHERE status = 'failed')::int AS fail_count
            FROM agent_auto_executions
            WHERE tenant_id = :tid
              AND DATE(executed_at AT TIME ZONE 'Asia/Shanghai') = :d
              AND is_deleted = FALSE
            GROUP BY agent_id
        """),
            {"tid": x_tenant_id, "d": target_date_str},
        )
        exec_rows = r.mappings().all()
    except SQLAlchemyError as exc:
        logger.warning("roi_collect_auto_executions_failed", error=str(exc), exc_info=True)
        exec_rows = []

    # 将执行日志映射为各 Agent 的 ROI 指标
    exec_by_agent: dict[str, dict] = {row["agent_id"]: dict(row) for row in exec_rows}

    EXEC_METRIC_MAP: dict[str, list[tuple[str, str]]] = {
        # agent_id → [(metric_type, exec_field), ...]
        "inventory_agent": [("stockout_prevented_count", "success_count")],
        "scheduling_agent": [("labor_hours_saved", "success_count")],
        "member_insight": [("recalled_member_count", "success_count"), ("churn_prevented_count", "exec_count")],
        "smart_menu": [("poor_dish_removed_count", "success_count")],
        "serve_dispatch": [("overtime_prevented_count", "success_count")],
        "finance_audit": [("audit_issue_count", "success_count")],
        "store_inspect": [("violation_detected_count", "success_count")],
        "private_ops": [("campaign_sent_count", "exec_count")],
    }

    for agent_id, metric_mappings in EXEC_METRIC_MAP.items():
        exec_data = exec_by_agent.get(agent_id, {})
        for metric_type, exec_field in metric_mappings:
            metrics.append(
                {
                    "agent_id": agent_id,
                    "metric_type": metric_type,
                    "value": exec_data.get(exec_field, 0),
                }
            )

    # ── 批量写入 ─────────────────────────────────────────────────────────────
    if not metrics:
        return {"ok": True, "data": {"inserted_count": 0, "skipped": False}}

    try:
        for m in metrics:
            await db.execute(
                text("""
                INSERT INTO agent_roi_metrics
                    (tenant_id, agent_id, metric_type, value, period_start, period_end, metadata)
                VALUES
                    (:tid, :agent_id, :metric_type, :value, :period_start, :period_end, :metadata::jsonb)
            """),
                {
                    "tid": x_tenant_id,
                    "agent_id": m["agent_id"],
                    "metric_type": m["metric_type"],
                    "value": m["value"],
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "metadata": '{"source": "daily_collect"}',
                },
            )
        await db.commit()
        logger.info(
            "roi_collect_completed",
            tenant_id=x_tenant_id,
            target_date=target_date_str,
            inserted_count=len(metrics),
        )
        return {
            "ok": True,
            "data": {
                "inserted_count": len(metrics),
                "skipped": False,
                "target_date": target_date_str,
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("roi_collect_insert_failed", error=str(exc), exc_info=True)
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="ROI 指标写入失败，请重试")


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D2：基于 agent_decision_logs ROI 字段 + mv_agent_roi_monthly 物化视图
#
# 与上方基于 agent_roi_metrics 表的旧接口共存。新接口路径 /decision-roi/* 明确
# 语义（"决策级 ROI" 而非"每日采集指标"）。
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/decision-roi/monthly", summary="D2: 按月聚合的决策 ROI（来自 mv_agent_roi_monthly）")
async def get_decision_roi_monthly(
    agent_id: str | None = Query(None, description="筛选单个 agent_id；不传则返回全部"),
    store_id: str | None = Query(None, description="筛选门店 UUID；不传则返回租户汇总"),
    months_back: int = Query(6, ge=1, le=13, description="回溯月数（mv 保留 13 个月）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict:
    """查询 mv_agent_roi_monthly：按 tenant/store/agent/month 的 ROI 聚合。

    返回每月一行：decision_count / saved_labor_hours_sum / prevented_loss_fen_sum /
                  revenue_uplift_fen_sum / nps_delta_avg / avg_confidence
    """
    filters = ["tenant_id = CAST(:tenant_id AS uuid)"]
    params: dict = {"tenant_id": x_tenant_id, "months_back": months_back}

    if agent_id:
        filters.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    if store_id:
        filters.append("store_id = CAST(:store_id AS uuid)")
        params["store_id"] = store_id

    # 只取回溯窗口内
    filters.append(
        "period_month >= DATE_TRUNC('month', CURRENT_DATE - :months_back * INTERVAL '1 month')::date"
    )
    where = " AND ".join(filters)

    try:
        result = await db.execute(text(f"""
            SELECT
                period_month,
                store_id::text AS store_id,
                agent_id,
                decision_count,
                avg_confidence,
                saved_labor_hours_sum,
                prevented_loss_fen_sum,
                revenue_uplift_fen_sum,
                nps_delta_avg
            FROM mv_agent_roi_monthly
            WHERE {where}
            ORDER BY period_month DESC, agent_id
        """), params)
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.error("d2_roi_monthly_query_failed", error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "查询 mv_agent_roi_monthly 失败"}}

    # 序列化 Decimal / date 为 JSON 友好类型
    for r in rows:
        pm = r.get("period_month")
        if pm is not None:
            r["period_month"] = pm.isoformat()
        for k in ("avg_confidence", "saved_labor_hours_sum", "nps_delta_avg"):
            if r.get(k) is not None:
                r[k] = float(r[k])

    return {"ok": True, "data": {
        "rows": rows,
        "filters": {"agent_id": agent_id, "store_id": store_id, "months_back": months_back},
    }}


@router.post("/decision-roi/refresh", summary="D2: 手工刷新 mv_agent_roi_monthly（运维用）")
async def refresh_decision_roi_mv(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict:
    """手工触发 `SELECT refresh_mv_agent_roi_monthly()`，通常由 cron 每日 02:00 调用。

    注：物化视图是跨租户共享的，任一租户调用此端点会刷新全部数据。生产环境
    建议通过独立 cron 调用，此端点仅用于排查或紧急重建。
    """
    try:
        await db.execute(text("SELECT refresh_mv_agent_roi_monthly()"))
        await db.commit()
        logger.info("d2_roi_mv_refreshed", triggered_by=x_tenant_id)
        return {"ok": True, "data": {"refreshed": True}}
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("d2_roi_mv_refresh_failed", error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": f"刷新失败: {exc}"}}


@router.get("/decision-roi/summary", summary="D2: 租户当月 ROI 快照")
async def get_decision_roi_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict:
    """租户当月各 Agent 累计 ROI 一屏汇总，首页"三条硬约束 ROI"展示卡用。"""
    try:
        result = await db.execute(text("""
            SELECT
                agent_id,
                SUM(decision_count)            AS decisions,
                SUM(saved_labor_hours_sum)     AS saved_hours,
                SUM(prevented_loss_fen_sum)    AS prevented_loss_fen,
                SUM(revenue_uplift_fen_sum)    AS revenue_uplift_fen,
                AVG(avg_confidence)            AS avg_confidence
            FROM mv_agent_roi_monthly
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND period_month = DATE_TRUNC('month', CURRENT_DATE)::date
            GROUP BY agent_id
            ORDER BY (
                SUM(prevented_loss_fen_sum)
                + SUM(revenue_uplift_fen_sum)
                + SUM(saved_labor_hours_sum) * 10000
            ) DESC
            LIMIT 20
        """), {"tenant_id": x_tenant_id})
        rows = [dict(r) for r in result.mappings()]
    except SQLAlchemyError as exc:
        logger.error("d2_roi_summary_failed", error=str(exc), exc_info=True)
        return {"ok": False, "error": {"message": "ROI 汇总查询失败"}}

    # 汇总维度
    total_saved_hours = sum(float(r.get("saved_hours") or 0) for r in rows)
    total_prevented_fen = sum(int(r.get("prevented_loss_fen") or 0) for r in rows)
    total_revenue_up_fen = sum(int(r.get("revenue_uplift_fen") or 0) for r in rows)

    for r in rows:
        for k in ("saved_hours", "avg_confidence"):
            if r.get(k) is not None:
                r[k] = float(r[k])

    return {"ok": True, "data": {
        "by_agent": rows,
        "aggregate": {
            "saved_labor_hours": round(total_saved_hours, 2),
            "prevented_loss_fen": total_prevented_fen,
            "prevented_loss_yuan": round(total_prevented_fen / 100, 2),
            "revenue_uplift_fen": total_revenue_up_fen,
            "revenue_uplift_yuan": round(total_revenue_up_fen / 100, 2),
        },
        "period": "current_month",
    }}
