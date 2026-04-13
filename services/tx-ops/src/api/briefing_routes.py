"""经营简报中心 API 路由（真实DB版）

数据源：
  列表/详情 → daily_business_reports（按日期/门店聚合生成简报摘要）
  订阅设置  → 无持久化表，返回确认响应

端点:
  GET   /api/v1/analytics/briefings              简报列表
  GET   /api/v1/analytics/briefings/{id}         简报详情
  POST  /api/v1/analytics/briefings/subscribe    订阅设置

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/analytics/briefings", tags=["analytics-briefings"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SubscribeRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    briefing_types: List[str] = Field(..., description="订阅的简报类型: daily/weekly/monthly/custom")
    channels: List[str] = Field(default_factory=lambda: ["app"], description="推送渠道: app/email/wecom/sms")
    store_ids: Optional[List[str]] = Field(None, description="关注的门店列表（空=全部）")
    push_time: Optional[str] = Field("08:00", description="推送时间 HH:MM")
    enabled: bool = Field(True, description="是否启用")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_briefing_summary(row: Any) -> Dict[str, Any]:
    """将 daily_business_reports 聚合行转为简报摘要对象。"""
    report_date = str(row.report_date)
    return {
        "id": f"daily-{report_date}",
        "type": "daily",
        "title": f"{report_date} 日经营简报",
        "subtitle": f"全品牌汇总数据",
        "generated_at": str(row.max_updated_at) if row.max_updated_at else None,
        "period": {"start": report_date, "end": report_date},
        "status": "published",
        "summary": (
            f"当日全品牌营收 {row.total_revenue_fen / 100:.0f} 元，"
            f"订单 {row.total_orders} 单，"
            f"客单价 {row.avg_ticket_fen / 100:.1f} 元。"
        ),
        "highlights": [],
        "kpis": {
            "total_revenue_fen": row.total_revenue_fen,
            "total_orders": row.total_orders,
            "avg_ticket_fen": row.avg_ticket_fen,
            "gross_margin_pct": (
                round(float(row.avg_gross_margin) * 100, 1)
                if row.avg_gross_margin is not None
                else None
            ),
        },
        "store_rankings": [],
        "ai_insights": [],
    }


def _row_to_briefing_detail(row: Any) -> Dict[str, Any]:
    """简报详情：与摘要相同结构（daily_business_reports 无额外详情字段）。"""
    return _row_to_briefing_summary(row)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("")
async def list_briefings(
    briefing_type: Optional[str] = Query(None, description="简报类型: daily/weekly/monthly/custom"),
    status: Optional[str] = Query(None, description="状态: draft/published"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """经营简报列表（从 daily_business_reports 按日期聚合）。"""
    log.info("briefings_listed", tenant_id=x_tenant_id, briefing_type=briefing_type)

    # 仅支持 daily 类型（daily_business_reports 为日报表）
    # 非 daily 请求直接返回空列表（weekly/monthly/custom 尚无专属表）
    if briefing_type and briefing_type != "daily":
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}
    # status=draft 暂不支持，daily_business_reports 均视为 published
    if status and status == "draft":
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}

    try:
        await _set_rls(db, x_tenant_id)

        count_result = await db.execute(
            text(
                "SELECT COUNT(DISTINCT report_date) AS cnt "
                "FROM daily_business_reports"
            )
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        rows_result = await db.execute(
            text(
                """
                SELECT
                    report_date,
                    SUM(revenue_fen)              AS total_revenue_fen,
                    SUM(order_count)              AS total_orders,
                    CASE WHEN SUM(order_count) > 0
                         THEN SUM(revenue_fen) / SUM(order_count)
                         ELSE 0 END               AS avg_ticket_fen,
                    AVG(gross_margin)             AS avg_gross_margin,
                    MAX(updated_at)               AS max_updated_at
                FROM daily_business_reports
                GROUP BY report_date
                ORDER BY report_date DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {"lim": size, "off": offset},
        )
        rows = rows_result.fetchall()

        items = [_row_to_briefing_summary(r) for r in rows]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("briefings_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.get("/{briefing_id}")
async def get_briefing_detail(
    briefing_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """简报详情（含完整KPI，从 daily_business_reports 聚合）。

    briefing_id 格式: daily-YYYY-MM-DD
    """
    log.info("briefing_detail_requested", briefing_id=briefing_id, tenant_id=x_tenant_id)

    # 解析日期：格式 daily-YYYY-MM-DD
    if not briefing_id.startswith("daily-"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="简报不存在")

    report_date_str = briefing_id[len("daily-"):]

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                """
                SELECT
                    report_date,
                    SUM(revenue_fen)              AS total_revenue_fen,
                    SUM(order_count)              AS total_orders,
                    CASE WHEN SUM(order_count) > 0
                         THEN SUM(revenue_fen) / SUM(order_count)
                         ELSE 0 END               AS avg_ticket_fen,
                    AVG(gross_margin)             AS avg_gross_margin,
                    MAX(updated_at)               AS max_updated_at
                FROM daily_business_reports
                WHERE report_date = :rd
                GROUP BY report_date
                """
            ),
            {"rd": report_date_str},
        )
        row = row_result.fetchone()

        if row is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="简报不存在")

        # 按门店排名
        ranking_result = await db.execute(
            text(
                """
                SELECT
                    store_id::text,
                    revenue_fen,
                    order_count,
                    ROW_NUMBER() OVER (ORDER BY revenue_fen DESC) AS rank
                FROM daily_business_reports
                WHERE report_date = :rd
                ORDER BY revenue_fen DESC
                LIMIT 10
                """
            ),
            {"rd": report_date_str},
        )
        store_rows = ranking_result.fetchall()

        briefing = _row_to_briefing_detail(row)
        briefing["store_rankings"] = [
            {
                "rank": int(sr.rank),
                "store_id": sr.store_id,
                "revenue_fen": sr.revenue_fen,
                "order_count": sr.order_count,
            }
            for sr in store_rows
        ]
        return {"ok": True, "data": briefing}

    except SQLAlchemyError as exc:
        log.error("briefing_detail_db_error", error=str(exc), briefing_id=briefing_id, tenant_id=x_tenant_id)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="数据库暂时不可用")


@router.post("/subscribe")
async def subscribe_briefings(
    body: SubscribeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """订阅/更新简报推送设置（订阅配置存储尚未落表，返回确认响应）。"""
    log.info("briefing_subscription_updated", user_id=body.user_id,
             types=body.briefing_types, channels=body.channels, tenant_id=x_tenant_id)

    from datetime import datetime, timezone
    return {
        "ok": True,
        "data": {
            "user_id": body.user_id,
            "briefing_types": body.briefing_types,
            "channels": body.channels,
            "store_ids": body.store_ids,
            "push_time": body.push_time,
            "enabled": body.enabled,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    }
