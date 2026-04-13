"""门店健康度雷达 API 路由

前缀: /api/v1/store-health/radar

端点:
  GET  /summary              — 红黄绿汇总（各等级门店数量）
  GET  /list                 — 门店列表（支持 region/level 筛选）
  GET  /{store_id}           — 门店六维雷达详情
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/store-health/radar", tags=["store-health-radar"])


# ─── 常量 ────────────────────────────────────────────────────

# 等级→颜色映射
_LEVEL_COLOR = {"A": "green", "B": "yellow", "C": "orange", "D": "red"}

# 六维指标中文名
_DIMENSION_LABELS = {
    "revenue": "营收能力",
    "customer": "客户运营",
    "cost": "成本控制",
    "efficiency": "运营效率",
    "quality": "品质管控",
    "growth": "增长潜力",
}


# ─── 依赖注入 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── DB 查询函数 ─────────────────────────────────────────────

def _compute_level(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _compute_trend(recent_revenue: int, prior_revenue: int) -> str:
    if prior_revenue == 0:
        return "stable"
    ratio = (recent_revenue - prior_revenue) / prior_revenue
    if ratio > 0.05:
        return "up"
    if ratio < -0.05:
        return "down"
    return "stable"


async def _fetch_store_health_list(db: AsyncSession) -> list[dict]:
    """从 DB 计算每个门店的健康度数据。"""
    try:
        # 1. 获取所有活跃门店
        stores_result = await db.execute(text("""
            SELECT id, store_name, region, city
            FROM stores
            WHERE status = 'active'
            ORDER BY store_name
        """))
        stores = stores_result.mappings().all()

        if not stores:
            return []

        store_ids = [str(row["id"]) for row in stores]
        store_ids_sql = ", ".join(f"'{sid}'" for sid in store_ids)

        # 2. 合规预警统计（open 状态告警数，按 store_id 分组）
        alerts_result = await db.execute(text(f"""
            SELECT store_id::text, COUNT(*) AS open_count
            FROM compliance_alerts
            WHERE store_id::text IN ({store_ids_sql})
              AND status = 'open'
            GROUP BY store_id
        """))
        alerts_by_store: dict[str, int] = {
            row["store_id"]: int(row["open_count"])
            for row in alerts_result.mappings().all()
        }

        # 3. 近7天 vs 前7天 销售额（分）
        sales_result = await db.execute(text(f"""
            SELECT
                store_id::text,
                SUM(CASE WHEN created_at >= NOW() - INTERVAL '7 days'
                         THEN total_fen ELSE 0 END) AS recent_revenue,
                SUM(CASE WHEN created_at >= NOW() - INTERVAL '14 days'
                         AND created_at < NOW() - INTERVAL '7 days'
                         THEN total_fen ELSE 0 END) AS prior_revenue
            FROM orders
            WHERE store_id::text IN ({store_ids_sql})
              AND status = 'paid'
              AND created_at >= NOW() - INTERVAL '14 days'
            GROUP BY store_id
        """))
        sales_by_store: dict[str, dict] = {
            row["store_id"]: {
                "recent": int(row["recent_revenue"] or 0),
                "prior": int(row["prior_revenue"] or 0),
            }
            for row in sales_result.mappings().all()
        }

        # 4. 培训完成率（join employees 获取 store_id）
        training_result = await db.execute(text(f"""
            SELECT
                e.store_id::text,
                COUNT(*) AS total_trainings,
                SUM(CASE WHEN et.status = 'completed' THEN 1 ELSE 0 END) AS completed_trainings
            FROM employee_trainings et
            JOIN employees e ON et.employee_id = e.id
            WHERE e.store_id::text IN ({store_ids_sql})
            GROUP BY e.store_id
        """))
        training_by_store: dict[str, dict] = {
            row["store_id"]: {
                "total": int(row["total_trainings"] or 0),
                "completed": int(row["completed_trainings"] or 0),
            }
            for row in training_result.mappings().all()
        }

        # 5. 组装健康度数据
        result = []
        for store in stores:
            sid = str(store["id"])

            # 合规得分：没有 open 告警=100，每个 open 告警扣 10 分，最低 0
            open_alerts = alerts_by_store.get(sid, 0)
            compliance_score = max(0, 100 - open_alerts * 10)

            # 销售趋势得分：recent vs prior（score 50~100）
            sales = sales_by_store.get(sid, {"recent": 0, "prior": 0})
            if sales["prior"] > 0:
                sales_ratio = sales["recent"] / sales["prior"]
                sales_score = min(100, max(0, int(50 + (sales_ratio - 1) * 100)))
            elif sales["recent"] > 0:
                sales_score = 75
            else:
                sales_score = 50

            # 培训完成率得分
            training = training_by_store.get(sid, {"total": 0, "completed": 0})
            if training["total"] > 0:
                training_score = int(training["completed"] / training["total"] * 100)
            else:
                training_score = 80  # 无培训数据时中性分

            # 六维得分（revenue/growth 用销售得分；cost/quality 用合规得分；
            # efficiency/customer 用培训得分，略加随机偏移以区分维度）
            radar = {
                "revenue": min(100, int(sales_score * 0.95)),
                "customer": min(100, int(training_score * 0.95)),
                "cost": min(100, int(compliance_score * 0.9 + sales_score * 0.1)),
                "efficiency": min(100, int(training_score * 0.7 + sales_score * 0.3)),
                "quality": min(100, int(compliance_score * 0.95)),
                "growth": min(100, int(sales_score * 0.8 + training_score * 0.2)),
            }

            health_score = int(
                compliance_score * 0.35
                + sales_score * 0.40
                + training_score * 0.25
            )
            level = _compute_level(health_score)
            trend = _compute_trend(sales["recent"], sales["prior"])

            risk_tags = []
            if open_alerts >= 3:
                risk_tags.append("合规告警偏多")
            if sales["recent"] == 0:
                risk_tags.append("近期无销售记录")
            elif sales["prior"] > 0 and sales["recent"] / sales["prior"] < 0.8:
                risk_tags.append("营收下滑")
            if training["total"] > 0 and training_score < 60:
                risk_tags.append("培训完成率低")

            result.append({
                "store_id": sid,
                "store_name": store["store_name"],
                "region": store["region"] or "",
                "city": store["city"] or "",
                "level": level,
                "health_score": health_score,
                "radar": radar,
                "trend": trend,
                "risk_tags": risk_tags,
            })

        return result

    except SQLAlchemyError:
        logger.exception("store_health_db_error")
        return []


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/summary")
async def store_health_summary(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """红黄绿汇总 — 各等级门店数量及占比"""
    tenant_id_str = _require_tenant(x_tenant_id)
    logger.info("store_health_summary", tenant_id=tenant_id_str)

    stores = await _fetch_store_health_list(db)

    level_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for s in stores:
        level_counts[s["level"]] += 1

    total = len(stores)
    summary = [
        {
            "level": lvl,
            "label": {"A": "优秀", "B": "良好", "C": "预警", "D": "严重"}[lvl],
            "color": _LEVEL_COLOR[lvl],
            "count": cnt,
            "ratio": round(cnt / total, 4) if total > 0 else 0.0,
        }
        for lvl, cnt in level_counts.items()
    ]

    avg_score = round(sum(s["health_score"] for s in stores) / total) if total else 0

    return {
        "ok": True,
        "data": {
            "summary": summary,
            "total_stores": total,
            "avg_health_score": avg_score,
            "risk_store_count": level_counts["C"] + level_counts["D"],
        },
    }


@router.get("/list")
async def store_health_list(
    region: Optional[str] = Query(None, description="区域筛选: 华中/华东/华南/西南"),
    level: Optional[str] = Query(None, description="等级筛选: A/B/C/D"),
    sort_by: str = Query("health_score", description="排序字段: health_score/store_name"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店健康度列表（支持 region/level 筛选 + 分页）"""
    tenant_id_str = _require_tenant(x_tenant_id)
    logger.info("store_health_list", tenant_id=tenant_id_str, region=region, level=level)

    stores = await _fetch_store_health_list(db)

    filtered = stores
    if region:
        filtered = [s for s in filtered if s["region"] == region]
    if level:
        filtered = [s for s in filtered if s["level"] == level.upper()]

    reverse = sort_order == "desc"
    if sort_by == "store_name":
        filtered = sorted(filtered, key=lambda s: s["store_name"], reverse=reverse)
    else:
        filtered = sorted(filtered, key=lambda s: s["health_score"], reverse=reverse)

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/{store_id}")
async def store_health_detail(
    store_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店六维雷达详情 — 含各维度得分、子指标、环比"""
    tenant_id_str = _require_tenant(x_tenant_id)
    logger.info("store_health_detail", tenant_id=tenant_id_str, store_id=store_id)

    stores = await _fetch_store_health_list(db)
    store = next((s for s in stores if s["store_id"] == store_id), None)
    if not store:
        raise HTTPException(status_code=404, detail=f"门店不存在: {store_id}")

    # 构建六维详情（子指标为静态模板，实际数值从 DB 导出；此处保留结构供前端渲染）
    sub_metrics_map = {
        "revenue": [
            {"key": "daily_revenue_fen", "label": "日均营收", "value": None, "unit": "分", "mom": None},
            {"key": "avg_ticket_fen", "label": "客单价", "value": None, "unit": "分", "mom": None},
            {"key": "channel_online_ratio", "label": "线上占比", "value": None, "unit": "%", "mom": None},
        ],
        "customer": [
            {"key": "new_customer_rate", "label": "新客占比", "value": None, "unit": "%", "mom": None},
            {"key": "return_rate", "label": "复购率", "value": None, "unit": "%", "mom": None},
            {"key": "satisfaction", "label": "满意度", "value": None, "unit": "分", "mom": None},
        ],
        "cost": [
            {"key": "food_cost_ratio", "label": "食材成本率", "value": None, "unit": "%", "mom": None},
            {"key": "labor_cost_ratio", "label": "人工成本率", "value": None, "unit": "%", "mom": None},
            {"key": "rent_cost_ratio", "label": "租金成本率", "value": None, "unit": "%", "mom": None},
        ],
        "efficiency": [
            {"key": "turnover_rate", "label": "翻台率", "value": None, "unit": "次", "mom": None},
            {"key": "labor_efficiency_fen", "label": "人效", "value": None, "unit": "分/人/天", "mom": None},
            {"key": "avg_service_min", "label": "平均用餐时长", "value": None, "unit": "分钟", "mom": None},
        ],
        "quality": [
            {"key": "complaint_rate", "label": "客诉率", "value": None, "unit": "%", "mom": None},
            {"key": "food_safety_score", "label": "食安评分", "value": None, "unit": "分", "mom": None},
            {"key": "dish_return_rate", "label": "退菜率", "value": None, "unit": "%", "mom": None},
        ],
        "growth": [
            {"key": "revenue_growth", "label": "营收同比增长", "value": None, "unit": "%", "mom": None},
            {"key": "member_growth", "label": "会员增长率", "value": None, "unit": "%", "mom": None},
            {"key": "new_channel_revenue", "label": "新渠道营收占比", "value": None, "unit": "%", "mom": None},
        ],
    }

    dimensions = []
    for dim_key, score in store["radar"].items():
        dimensions.append({
            "key": dim_key,
            "label": _DIMENSION_LABELS[dim_key],
            "score": score,
            "max_score": 100,
            "sub_metrics": sub_metrics_map.get(dim_key, []),
        })

    return {
        "ok": True,
        "data": {
            "store_id": store["store_id"],
            "store_name": store["store_name"],
            "region": store["region"],
            "city": store["city"],
            "level": store["level"],
            "level_label": {"A": "优秀", "B": "良好", "C": "预警", "D": "严重"}[store["level"]],
            "health_score": store["health_score"],
            "trend": store["trend"],
            "risk_tags": store["risk_tags"],
            "dimensions": dimensions,
        },
    }
