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
from fastapi import APIRouter, Header, HTTPException, Query

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/store-health/radar", tags=["store-health-radar"])


# ─── Mock 数据 ───────────────────────────────────────────────

_MOCK_STORES = [
    {
        "store_id": "s001",
        "store_name": "尝在一起·五一广场店",
        "region": "华中",
        "city": "长沙",
        "level": "A",
        "health_score": 92,
        "radar": {
            "revenue": 95, "customer": 88, "cost": 90,
            "efficiency": 93, "quality": 94, "growth": 89,
        },
        "trend": "up",
        "risk_tags": [],
    },
    {
        "store_id": "s002",
        "store_name": "尝在一起·IFS店",
        "region": "华中",
        "city": "长沙",
        "level": "A",
        "health_score": 88,
        "radar": {
            "revenue": 91, "customer": 85, "cost": 87,
            "efficiency": 90, "quality": 88, "growth": 86,
        },
        "trend": "stable",
        "risk_tags": [],
    },
    {
        "store_id": "s003",
        "store_name": "最黔线·太平街店",
        "region": "华中",
        "city": "长沙",
        "level": "B",
        "health_score": 76,
        "radar": {
            "revenue": 78, "customer": 72, "cost": 80,
            "efficiency": 75, "quality": 79, "growth": 70,
        },
        "trend": "up",
        "risk_tags": ["客单偏低"],
    },
    {
        "store_id": "s004",
        "store_name": "最黔线·梅溪湖店",
        "region": "华中",
        "city": "长沙",
        "level": "B",
        "health_score": 73,
        "radar": {
            "revenue": 75, "customer": 70, "cost": 76,
            "efficiency": 72, "quality": 74, "growth": 68,
        },
        "trend": "down",
        "risk_tags": ["翻台下降"],
    },
    {
        "store_id": "s005",
        "store_name": "尚宫厨·国金店",
        "region": "华东",
        "city": "上海",
        "level": "A",
        "health_score": 90,
        "radar": {
            "revenue": 93, "customer": 90, "cost": 85,
            "efficiency": 91, "quality": 92, "growth": 88,
        },
        "trend": "up",
        "risk_tags": [],
    },
    {
        "store_id": "s006",
        "store_name": "尚宫厨·新天地店",
        "region": "华东",
        "city": "上海",
        "level": "C",
        "health_score": 62,
        "radar": {
            "revenue": 58, "customer": 65, "cost": 55,
            "efficiency": 60, "quality": 70, "growth": 52,
        },
        "trend": "down",
        "risk_tags": ["成本过高", "毛利预警"],
    },
    {
        "store_id": "s007",
        "store_name": "尝在一起·天河城店",
        "region": "华南",
        "city": "广州",
        "level": "B",
        "health_score": 78,
        "radar": {
            "revenue": 80, "customer": 76, "cost": 82,
            "efficiency": 74, "quality": 78, "growth": 75,
        },
        "trend": "stable",
        "risk_tags": [],
    },
    {
        "store_id": "s008",
        "store_name": "最黔线·春熙路店",
        "region": "西南",
        "city": "成都",
        "level": "D",
        "health_score": 48,
        "radar": {
            "revenue": 42, "customer": 50, "cost": 40,
            "efficiency": 45, "quality": 55, "growth": 38,
        },
        "trend": "down",
        "risk_tags": ["营收不达标", "人效过低", "客诉偏高"],
    },
    {
        "store_id": "s009",
        "store_name": "尝在一起·解放碑店",
        "region": "西南",
        "city": "重庆",
        "level": "C",
        "health_score": 60,
        "radar": {
            "revenue": 62, "customer": 58, "cost": 56,
            "efficiency": 63, "quality": 65, "growth": 55,
        },
        "trend": "stable",
        "risk_tags": ["成本过高"],
    },
    {
        "store_id": "s010",
        "store_name": "尚宫厨·西湖店",
        "region": "华东",
        "city": "杭州",
        "level": "B",
        "health_score": 74,
        "radar": {
            "revenue": 77, "customer": 73, "cost": 70,
            "efficiency": 76, "quality": 75, "growth": 72,
        },
        "trend": "up",
        "risk_tags": [],
    },
]

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


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/summary")
async def store_health_summary(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """红黄绿汇总 — 各等级门店数量及占比"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("store_health_summary", tenant_id=str(tenant_id))

    level_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for s in _MOCK_STORES:
        level_counts[s["level"]] += 1

    total = len(_MOCK_STORES)
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

    avg_score = round(sum(s["health_score"] for s in _MOCK_STORES) / total) if total else 0

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
):
    """门店健康度列表（支持 region/level 筛选 + 分页）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("store_health_list", tenant_id=str(tenant_id), region=region, level=level)

    filtered = _MOCK_STORES
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
):
    """门店六维雷达详情 — 含各维度得分、子指标、环比"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("store_health_detail", tenant_id=str(tenant_id), store_id=store_id)

    store = next((s for s in _MOCK_STORES if s["store_id"] == store_id), None)
    if not store:
        raise HTTPException(status_code=404, detail=f"门店不存在: {store_id}")

    # 构建六维详情（含子指标）
    dimensions = []
    sub_metrics_map = {
        "revenue": [
            {"key": "daily_revenue_fen", "label": "日均营收", "value": 3850000, "unit": "分", "mom": 0.05},
            {"key": "avg_ticket_fen", "label": "客单价", "value": 8800, "unit": "分", "mom": 0.02},
            {"key": "channel_online_ratio", "label": "线上占比", "value": 0.35, "unit": "%", "mom": 0.03},
        ],
        "customer": [
            {"key": "new_customer_rate", "label": "新客占比", "value": 0.22, "unit": "%", "mom": -0.01},
            {"key": "return_rate", "label": "复购率", "value": 0.38, "unit": "%", "mom": 0.04},
            {"key": "satisfaction", "label": "满意度", "value": 4.6, "unit": "分", "mom": 0.1},
        ],
        "cost": [
            {"key": "food_cost_ratio", "label": "食材成本率", "value": 0.33, "unit": "%", "mom": -0.02},
            {"key": "labor_cost_ratio", "label": "人工成本率", "value": 0.25, "unit": "%", "mom": 0.0},
            {"key": "rent_cost_ratio", "label": "租金成本率", "value": 0.12, "unit": "%", "mom": 0.0},
        ],
        "efficiency": [
            {"key": "turnover_rate", "label": "翻台率", "value": 3.2, "unit": "次", "mom": 0.1},
            {"key": "labor_efficiency_fen", "label": "人效", "value": 280000, "unit": "分/人/天", "mom": 0.03},
            {"key": "avg_service_min", "label": "平均用餐时长", "value": 52, "unit": "分钟", "mom": -2},
        ],
        "quality": [
            {"key": "complaint_rate", "label": "客诉率", "value": 0.008, "unit": "%", "mom": -0.002},
            {"key": "food_safety_score", "label": "食安评分", "value": 96, "unit": "分", "mom": 1},
            {"key": "dish_return_rate", "label": "退菜率", "value": 0.012, "unit": "%", "mom": -0.001},
        ],
        "growth": [
            {"key": "revenue_growth", "label": "营收同比增长", "value": 0.12, "unit": "%", "mom": 0.02},
            {"key": "member_growth", "label": "会员增长率", "value": 0.08, "unit": "%", "mom": 0.01},
            {"key": "new_channel_revenue", "label": "新渠道营收占比", "value": 0.15, "unit": "%", "mom": 0.03},
        ],
    }

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
