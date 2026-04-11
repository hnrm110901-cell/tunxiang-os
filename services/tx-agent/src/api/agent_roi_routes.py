"""Agent 效果量化仪表盘 — 对标 Yum Byte "降缺货85%" 的ROI可视化

端点:
  GET /api/v1/agent/roi/summary               — Agent整体ROI汇总
  GET /api/v1/agent/roi/{agent_id}/detail      — 单个Agent效果明细（按日/周/月）
  GET /api/v1/agent/roi/leaderboard            — Agent效能排行

核心指标:
  - 折扣守护: 拦截异常折扣金额(月累计)
  - 库存预警: 减少缺货次数/浪费金额
  - 排班优化: 节省人力成本小时数
  - 增长引擎: 召回会员带来的增量营收
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
            {"type": "intercepted_discount_fen", "label": "拦截异常折扣金额(分)", "unit": "分", "direction": "higher_better"},
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
            {"type": "menu_optimization_revenue_fen", "label": "排菜优化增收(分)", "unit": "分", "direction": "higher_better"},
            {"type": "poor_dish_removed_count", "label": "下架低效菜品数", "unit": "个", "direction": "higher_better"},
        ],
    },
    "serve_dispatch": {
        "name": "出餐调度",
        "metrics": [
            {"type": "avg_serve_time_reduction_sec", "label": "平均出餐时间缩短(秒)", "unit": "秒", "direction": "higher_better"},
            {"type": "overtime_prevented_count", "label": "避免超时出餐次数", "unit": "次", "direction": "higher_better"},
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
        result = await db.execute(text(f"""
            SELECT
                agent_id,
                metric_type,
                SUM(value)::float AS total_value,
                COUNT(*)::int AS data_points
            FROM agent_roi_metrics
            WHERE tenant_id = :tenant_id AND {period_filter}
            GROUP BY agent_id, metric_type
            ORDER BY agent_id, metric_type
        """), {"tenant_id": x_tenant_id})
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

    return {"ok": True, "data": {
        "period": period,
        "total_value_fen": total_value_fen,
        "total_value_yuan": round(total_value_fen / 100, 2),
        "agents": list(agent_data.values()),
    }}


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
        result = await db.execute(text(f"""
            SELECT
                date_trunc(:trunc, period_start) AS period,
                metric_type,
                SUM(value)::float AS total_value
            FROM agent_roi_metrics
            WHERE {where}
            GROUP BY period, metric_type
            ORDER BY period DESC, metric_type
            LIMIT :limit OFFSET :offset
        """), {**params, "trunc": trunc})
        rows = result.mappings().all()
    except (SQLAlchemyError, ConnectionError):
        rows = []

    return {"ok": True, "data": {
        "agent_id": agent_id,
        "agent_name": defn["name"],
        "metric_definitions": defn["metrics"],
        "granularity": granularity,
        "items": [dict(r) for r in rows],
    }}


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
        result = await db.execute(text(f"""
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
        """), {"tenant_id": x_tenant_id})
        rows = result.mappings().all()
    except (SQLAlchemyError, ConnectionError):
        rows = []

    leaderboard = []
    for i, row in enumerate(rows, 1):
        defn = AGENT_ROI_DEFINITIONS.get(row["agent_id"], {"name": row["agent_id"]})
        leaderboard.append({
            "rank": i,
            "agent_id": row["agent_id"],
            "agent_name": defn["name"],
            "total_value_fen": int(row["total_value"]),
            "total_value_yuan": round(row["total_value"] / 100, 2),
            "metric_count": row["metric_count"],
            "data_points": row["data_points"],
        })

    return {"ok": True, "data": {
        "period": period,
        "leaderboard": leaderboard,
    }}
