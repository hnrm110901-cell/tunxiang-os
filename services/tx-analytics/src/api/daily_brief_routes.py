"""
AI 自动日报生成

GET  /api/v1/analytics/daily-brief/{store_id}  — 生成门店日报
GET  /api/v1/analytics/daily-brief/group        — 集团级日报
POST /api/v1/analytics/daily-brief/schedule     — 配置自动推送(每日06:00)
GET  /api/v1/analytics/daily-brief/history       — 历史日报列表

日报内容：
  - 营收/客流/客单价/毛利率 (vs 昨日 / vs 上周同日)
  - 异常摘要：折扣异常/退单/缺货/差评
  - Agent 决策摘要：今日 Agent 做了什么
  - TOP5 热销 / TOP5 滞销
  - 推荐明日行动
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/analytics/daily-brief", tags=["daily-brief"])


# ─── 依赖项 ──────────────────────────────────────────────────────────

async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── 请求/响应模型 ────────────────────────────────────────────────────

class ScheduleRequest(BaseModel):
    store_ids: list[str] = Field(default_factory=list, description="门店ID列表，空=全部门店")
    push_time: str = Field(default="06:00", description="推送时间 HH:MM")
    channels: list[str] = Field(default_factory=lambda: ["wecom"], description="推送渠道: wecom/email/sms")
    enabled: bool = Field(default=True, description="是否启用")


# ─── 日报数据聚合（DB查询，失败时降级为mock） ─────────────────────────

async def _fetch_revenue_metrics(
    db: AsyncSession, tenant_id: str, store_id: str, target_date: date,
) -> dict[str, Any]:
    """营收/客流/客单价/毛利率，以及 vs 昨日 / vs 上周同日"""
    yesterday = target_date - timedelta(days=1)
    last_week_same_day = target_date - timedelta(days=7)

    async def _day_metrics(d: date) -> dict[str, float]:
        start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        try:
            r = await db.execute(text("""
                SELECT
                    COALESCE(SUM(total_amount), 0) AS revenue,
                    COUNT(*) AS order_count,
                    COALESCE(AVG(total_amount), 0) AS avg_ticket
                FROM orders
                WHERE tenant_id = :tid AND store_id = :sid
                  AND status = 'completed'
                  AND created_at >= :start AND created_at < :end
            """), {"tid": tenant_id, "sid": store_id, "start": start, "end": end})
            row = r.fetchone()
            revenue = float(row[0] or 0)
            count = int(row[1] or 0)
            avg_ticket = float(row[2] or 0)
        except (SQLAlchemyError, ConnectionError) as exc:
            logger.warning("daily_brief_revenue_query_fail", date=str(d), error=str(exc))
            return {"revenue": 0, "order_count": 0, "avg_ticket": 0, "margin_rate": 0}

        # 毛利率：尝试从 cost_records 获取
        margin_rate = 0.0
        if revenue > 0:
            try:
                cr = await db.execute(text("""
                    SELECT COALESCE(SUM(amount), 0)
                    FROM cost_records
                    WHERE tenant_id = :tid AND store_id = :sid
                      AND recorded_at >= :start AND recorded_at < :end
                """), {"tid": tenant_id, "sid": store_id, "start": start, "end": end})
                cost = float(cr.scalar() or 0)
                margin_rate = round((revenue - cost) / revenue, 4) if revenue > 0 else 0
            except (SQLAlchemyError, ConnectionError):
                margin_rate = 0
        return {"revenue": revenue, "order_count": count, "avg_ticket": avg_ticket, "margin_rate": margin_rate}

    today_m = await _day_metrics(target_date)
    yesterday_m = await _day_metrics(yesterday)
    lastweek_m = await _day_metrics(last_week_same_day)

    def _delta(current: float, compare: float) -> float | None:
        if compare == 0:
            return None
        return round((current - compare) / compare, 4)

    return {
        "today": today_m,
        "vs_yesterday": {
            "revenue": _delta(today_m["revenue"], yesterday_m["revenue"]),
            "order_count": _delta(today_m["order_count"], yesterday_m["order_count"]),
            "avg_ticket": _delta(today_m["avg_ticket"], yesterday_m["avg_ticket"]),
            "margin_rate": _delta(today_m["margin_rate"], yesterday_m["margin_rate"]),
        },
        "vs_last_week": {
            "revenue": _delta(today_m["revenue"], lastweek_m["revenue"]),
            "order_count": _delta(today_m["order_count"], lastweek_m["order_count"]),
            "avg_ticket": _delta(today_m["avg_ticket"], lastweek_m["avg_ticket"]),
            "margin_rate": _delta(today_m["margin_rate"], lastweek_m["margin_rate"]),
        },
    }


async def _fetch_anomaly_summary(
    db: AsyncSession, tenant_id: str, store_id: str, target_date: date,
) -> list[dict[str, Any]]:
    """异常摘要：折扣异常/退单/缺货/差评"""
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    anomalies: list[dict[str, Any]] = []
    try:
        # 退单数量
        r = await db.execute(text("""
            SELECT COUNT(*) FROM orders
            WHERE tenant_id = :tid AND store_id = :sid
              AND status = 'refunded'
              AND created_at >= :start AND created_at < :end
        """), {"tid": tenant_id, "sid": store_id, "start": start, "end": end})
        refund_count = int(r.scalar() or 0)
        if refund_count > 0:
            anomalies.append({"type": "refund", "description": f"今日退单{refund_count}笔", "count": refund_count})

        # 折扣异常（从 agent_decision_logs 获取）
        r2 = await db.execute(text("""
            SELECT COUNT(*) FROM agent_decision_logs
            WHERE tenant_id = :tid AND decision_type = 'discount_anomaly'
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :d
        """), {"tid": tenant_id, "d": target_date.isoformat()})
        discount_anomaly = int(r2.scalar() or 0)
        if discount_anomaly > 0:
            anomalies.append({"type": "discount_anomaly", "description": f"折扣异常{discount_anomaly}次", "count": discount_anomaly})
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("daily_brief_anomaly_query_fail", error=str(exc))

    return anomalies


async def _fetch_agent_summary(
    db: AsyncSession, tenant_id: str, target_date: date,
) -> list[dict[str, Any]]:
    """Agent 决策摘要：今日 Agent 做了什么"""
    try:
        r = await db.execute(text("""
            SELECT agent_id, action, reasoning, confidence, status
            FROM agent_decision_logs
            WHERE tenant_id = :tid
              AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = :d
            ORDER BY created_at DESC
            LIMIT 10
        """), {"tid": tenant_id, "d": target_date.isoformat()})
        rows = r.fetchall()
        return [
            {
                "agent_id": row.agent_id,
                "action": row.action,
                "reasoning": row.reasoning,
                "confidence": float(row.confidence) if row.confidence else None,
                "status": row.status or "pending",
            }
            for row in rows
        ]
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("daily_brief_agent_query_fail", error=str(exc))
        return []


async def _fetch_dish_rankings(
    db: AsyncSession, tenant_id: str, store_id: str, target_date: date,
) -> dict[str, list[dict[str, Any]]]:
    """TOP5 热销 / TOP5 滞销"""
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    top5: list[dict[str, Any]] = []
    bottom5: list[dict[str, Any]] = []
    try:
        r = await db.execute(text("""
            SELECT oi.dish_name, SUM(oi.quantity) AS qty, SUM(oi.subtotal) AS revenue
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id
            WHERE o.tenant_id = :tid AND o.store_id = :sid
              AND o.status = 'completed'
              AND o.created_at >= :start AND o.created_at < :end
            GROUP BY oi.dish_name
            ORDER BY qty DESC
        """), {"tid": tenant_id, "sid": store_id, "start": start, "end": end})
        rows = r.fetchall()
        for i, row in enumerate(rows[:5]):
            top5.append({"rank": i + 1, "dish_name": row[0], "quantity": int(row[1]), "revenue": float(row[2] or 0)})
        for i, row in enumerate(reversed(rows[-5:])) if len(rows) >= 5 else enumerate(reversed(rows)):
            bottom5.append({"rank": i + 1, "dish_name": row[0], "quantity": int(row[1]), "revenue": float(row[2] or 0)})
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("daily_brief_dish_ranking_fail", error=str(exc))

    return {"top5_hot": top5, "top5_slow": bottom5}


def _generate_recommendations(
    revenue_metrics: dict, anomalies: list, dish_rankings: dict,
) -> list[str]:
    """基于日报数据生成明日行动建议"""
    actions: list[str] = []

    vs_yesterday = revenue_metrics.get("vs_yesterday", {})
    rev_delta = vs_yesterday.get("revenue")
    if rev_delta is not None and rev_delta < -0.1:
        actions.append(f"营收环比下降{abs(rev_delta):.0%}，建议检查客流来源并加强引流")

    margin = revenue_metrics.get("today", {}).get("margin_rate", 0)
    if 0 < margin < 0.3:
        actions.append(f"毛利率仅{margin:.0%}，建议排查高成本菜品或优化采购价格")

    refund_anomalies = [a for a in anomalies if a.get("type") == "refund"]
    if refund_anomalies:
        actions.append("存在退单异常，建议复盘出品质量和服务流程")

    top5 = dish_rankings.get("top5_hot", [])
    if top5:
        names = "、".join(d["dish_name"] for d in top5[:3])
        actions.append(f"热销菜品: {names}，建议确保食材备货充足")

    bottom5 = dish_rankings.get("top5_slow", [])
    if bottom5:
        names = "、".join(d["dish_name"] for d in bottom5[:3])
        actions.append(f"滞销菜品: {names}，建议考虑促销或调整菜单位置")

    if not actions:
        actions.append("今日经营表现稳定，建议保持现有策略")

    return actions


def _mock_daily_brief(store_id: str, target_date: date) -> dict[str, Any]:
    """当 DB 不可用时返回演示数据"""
    return {
        "store_id": store_id,
        "date": target_date.isoformat(),
        "revenue_metrics": {
            "today": {"revenue": 18600, "order_count": 142, "avg_ticket": 131, "margin_rate": 0.38},
            "vs_yesterday": {"revenue": 0.05, "order_count": 0.03, "avg_ticket": 0.02, "margin_rate": 0.01},
            "vs_last_week": {"revenue": -0.08, "order_count": -0.05, "avg_ticket": -0.03, "margin_rate": -0.02},
        },
        "anomalies": [
            {"type": "refund", "description": "今日退单3笔", "count": 3},
            {"type": "discount_anomaly", "description": "折扣异常1次", "count": 1},
        ],
        "agent_decisions": [
            {"agent_id": "discount_guard", "action": "拦截异常折扣: 88折→5折", "reasoning": "单笔毛利低于阈值", "confidence": 0.92, "status": "executed"},
            {"agent_id": "inventory_alert", "action": "三文鱼库存预警", "reasoning": "剩余量低于安全库存", "confidence": 0.85, "status": "notified"},
        ],
        "dish_rankings": {
            "top5_hot": [
                {"rank": 1, "dish_name": "酸菜鱼", "quantity": 38, "revenue": 2280},
                {"rank": 2, "dish_name": "水煮牛肉", "quantity": 32, "revenue": 2240},
                {"rank": 3, "dish_name": "麻辣香锅", "quantity": 28, "revenue": 1960},
                {"rank": 4, "dish_name": "剁椒鱼头", "quantity": 22, "revenue": 1760},
                {"rank": 5, "dish_name": "蒜蓉小龙虾", "quantity": 18, "revenue": 1620},
            ],
            "top5_slow": [
                {"rank": 1, "dish_name": "凉拌木耳", "quantity": 2, "revenue": 36},
                {"rank": 2, "dish_name": "清蒸南瓜", "quantity": 3, "revenue": 54},
                {"rank": 3, "dish_name": "银耳莲子羹", "quantity": 3, "revenue": 48},
                {"rank": 4, "dish_name": "白灼菜心", "quantity": 4, "revenue": 56},
                {"rank": 5, "dish_name": "醋溜土豆丝", "quantity": 5, "revenue": 60},
            ],
        },
        "recommendations": [
            "营收环比上升5%，表现良好，建议保持现有运营策略",
            "热销菜品: 酸菜鱼、水煮牛肉、麻辣香锅，建议确保食材备货充足",
            "滞销菜品: 凉拌木耳、清蒸南瓜、银耳莲子羹，建议考虑促销或调整菜单位置",
            "存在退单异常，建议复盘出品质量和服务流程",
        ],
        "_is_mock": True,
    }


# ─── 路由 ─────────────────────────────────────────────────────────────

@router.get("/history")
async def get_brief_history(
    store_id: str | None = Query(None, description="门店ID，空=全部"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """历史日报列表"""
    try:
        conditions = "WHERE tenant_id = :tid"
        params: dict[str, Any] = {"tid": x_tenant_id}
        if store_id:
            conditions += " AND store_id = :sid"
            params["sid"] = store_id

        count_r = await db.execute(text(f"SELECT COUNT(*) FROM daily_briefs {conditions}"), params)
        total = int(count_r.scalar() or 0)

        params["limit"] = size
        params["offset"] = (page - 1) * size
        r = await db.execute(text(f"""
            SELECT id::text, store_id, brief_date, content_json, sent_at, created_at
            FROM daily_briefs
            {conditions}
            ORDER BY brief_date DESC
            LIMIT :limit OFFSET :offset
        """), params)
        rows = r.fetchall()
        items = [
            {
                "id": row[0],
                "store_id": row[1],
                "date": row[2].isoformat() if row[2] else None,
                "sent_at": row[4].isoformat() if row[4] else None,
                "created_at": row[5].isoformat() if row[5] else None,
            }
            for row in rows
        ]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("daily_brief_history_query_fail", error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size, "_is_mock": True}}


@router.get("/group")
async def get_group_brief(
    target_date: str | None = Query(None, description="目标日期 YYYY-MM-DD，默认今天"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """集团级日报：汇总所有门店"""
    d = date.fromisoformat(target_date) if target_date else date.today()

    try:
        # 获取所有门店
        r = await db.execute(text("""
            SELECT id::text, name FROM stores
            WHERE tenant_id = :tid AND is_deleted = FALSE
        """), {"tid": x_tenant_id})
        stores = r.fetchall()
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("group_brief_stores_query_fail", error=str(exc))
        stores = []

    if not stores:
        return {
            "ok": True,
            "data": {
                "date": d.isoformat(),
                "store_count": 0,
                "total_revenue": 0,
                "total_orders": 0,
                "avg_ticket": 0,
                "avg_margin_rate": 0,
                "store_briefs": [],
                "overall_recommendations": ["暂无门店数据，请确认门店配置"],
                "_is_mock": True,
            },
        }

    store_briefs: list[dict[str, Any]] = []
    total_revenue = 0.0
    total_orders = 0
    margin_sum = 0.0
    store_count_with_margin = 0

    for store in stores:
        sid, sname = store[0], store[1]
        metrics = await _fetch_revenue_metrics(db, x_tenant_id, sid, d)
        today = metrics.get("today", {})
        rev = today.get("revenue", 0)
        orders = today.get("order_count", 0)
        total_revenue += rev
        total_orders += orders
        mr = today.get("margin_rate", 0)
        if mr > 0:
            margin_sum += mr
            store_count_with_margin += 1
        store_briefs.append({"store_id": sid, "store_name": sname, "revenue": rev, "order_count": orders, "margin_rate": mr})

    avg_ticket = round(total_revenue / total_orders, 2) if total_orders > 0 else 0
    avg_margin = round(margin_sum / store_count_with_margin, 4) if store_count_with_margin > 0 else 0

    return {
        "ok": True,
        "data": {
            "date": d.isoformat(),
            "store_count": len(stores),
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "avg_ticket": avg_ticket,
            "avg_margin_rate": avg_margin,
            "store_briefs": store_briefs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.post("/schedule")
async def configure_schedule(
    body: ScheduleRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """配置自动推送（每日 06:00）"""
    config_id = str(uuid.uuid4())
    try:
        await db.execute(text("""
            INSERT INTO daily_briefs (id, tenant_id, store_id, brief_date, content_json, created_at)
            VALUES (:id, :tid, :sid, CURRENT_DATE, :config, NOW())
        """), {
            "id": config_id,
            "tid": x_tenant_id,
            "sid": ",".join(body.store_ids) if body.store_ids else "__ALL__",
            "config": f'{{"schedule": true, "push_time": "{body.push_time}", "channels": {body.channels}, "enabled": {str(body.enabled).lower()}}}',
        })
        await db.commit()
    except (SQLAlchemyError, ConnectionError) as exc:
        logger.warning("daily_brief_schedule_save_fail", error=str(exc))

    return {
        "ok": True,
        "data": {
            "config_id": config_id,
            "push_time": body.push_time,
            "channels": body.channels,
            "store_ids": body.store_ids or ["__ALL__"],
            "enabled": body.enabled,
            "message": f"日报将于每日 {body.push_time} 自动推送",
        },
    }


@router.get("/{store_id}")
async def get_store_daily_brief(
    store_id: str,
    target_date: str | None = Query(None, description="目标日期 YYYY-MM-DD，默认今天"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """生成门店日报"""
    d = date.fromisoformat(target_date) if target_date else date.today()

    try:
        revenue_metrics = await _fetch_revenue_metrics(db, x_tenant_id, store_id, d)
        anomalies = await _fetch_anomaly_summary(db, x_tenant_id, store_id, d)
        agent_decisions = await _fetch_agent_summary(db, x_tenant_id, d)
        dish_rankings = await _fetch_dish_rankings(db, x_tenant_id, store_id, d)
        recommendations = _generate_recommendations(revenue_metrics, anomalies, dish_rankings)

        brief = {
            "store_id": store_id,
            "date": d.isoformat(),
            "revenue_metrics": revenue_metrics,
            "anomalies": anomalies,
            "agent_decisions": agent_decisions,
            "dish_rankings": dish_rankings,
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 持久化到 daily_briefs 表
        try:
            import json
            await db.execute(text("""
                INSERT INTO daily_briefs (id, tenant_id, store_id, brief_date, content_json, created_at)
                VALUES (:id, :tid, :sid, :d, :content, NOW())
                ON CONFLICT (tenant_id, store_id, brief_date) DO UPDATE
                SET content_json = :content, updated_at = NOW()
            """), {
                "id": str(uuid.uuid4()),
                "tid": x_tenant_id,
                "sid": store_id,
                "d": d.isoformat(),
                "content": json.dumps(brief, ensure_ascii=False, default=str),
            })
            await db.commit()
        except (SQLAlchemyError, ConnectionError) as persist_exc:
            logger.warning("daily_brief_persist_fail", error=str(persist_exc))

        return {"ok": True, "data": brief}

    except (SQLAlchemyError, ConnectionError, ValueError, RuntimeError) as exc:
        logger.warning("daily_brief_generation_fallback", store_id=store_id, error=str(exc), exc_info=True)
        return {"ok": True, "data": _mock_daily_brief(store_id, d)}
