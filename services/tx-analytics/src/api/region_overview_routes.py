"""区域经营总览 API 路由

前缀: /api/v1/analytics/region-overview

端点:
  GET  /                       — 区域/品牌维度汇总数据
  GET  /{region_id}/stores     — 区域内门店列表
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/region-overview", tags=["region-overview"])


# ─── Mock 数据 ───────────────────────────────────────────────

_MOCK_REGIONS = {
    "r001": {
        "region_id": "r001",
        "region_name": "华中大区",
        "manager": "张明",
        "store_count": 12,
        "metrics": {
            "revenue_fen": 462000000,
            "revenue_mom": 0.08,
            "avg_ticket_fen": 8500,
            "avg_ticket_mom": 0.03,
            "turnover_rate": 3.1,
            "turnover_mom": 0.05,
            "gross_margin": 0.62,
            "gross_margin_mom": -0.01,
            "labor_efficiency_fen": 265000,
            "labor_efficiency_mom": 0.04,
            "complaint_rate": 0.009,
            "complaint_mom": -0.002,
        },
        "brands": [
            {"brand": "尝在一起", "store_count": 6, "revenue_fen": 258000000, "revenue_mom": 0.10},
            {"brand": "最黔线", "store_count": 4, "revenue_fen": 136000000, "revenue_mom": 0.05},
            {"brand": "尚宫厨", "store_count": 2, "revenue_fen": 68000000, "revenue_mom": 0.06},
        ],
        "stores": [
            {"store_id": "s001", "store_name": "尝在一起·五一广场店", "city": "长沙", "revenue_fen": 52000000, "revenue_mom": 0.12, "health_level": "A"},
            {"store_id": "s002", "store_name": "尝在一起·IFS店", "city": "长沙", "revenue_fen": 48000000, "revenue_mom": 0.08, "health_level": "A"},
            {"store_id": "s003", "store_name": "最黔线·太平街店", "city": "长沙", "revenue_fen": 38000000, "revenue_mom": 0.05, "health_level": "B"},
            {"store_id": "s004", "store_name": "最黔线·梅溪湖店", "city": "长沙", "revenue_fen": 33000000, "revenue_mom": -0.02, "health_level": "B"},
            {"store_id": "s011", "store_name": "尝在一起·光谷店", "city": "武汉", "revenue_fen": 45000000, "revenue_mom": 0.09, "health_level": "A"},
            {"store_id": "s012", "store_name": "尝在一起·江汉路店", "city": "武汉", "revenue_fen": 42000000, "revenue_mom": 0.07, "health_level": "B"},
        ],
    },
    "r002": {
        "region_id": "r002",
        "region_name": "华东大区",
        "manager": "李娜",
        "store_count": 15,
        "metrics": {
            "revenue_fen": 610000000,
            "revenue_mom": 0.06,
            "avg_ticket_fen": 10200,
            "avg_ticket_mom": 0.02,
            "turnover_rate": 2.8,
            "turnover_mom": -0.02,
            "gross_margin": 0.58,
            "gross_margin_mom": -0.03,
            "labor_efficiency_fen": 290000,
            "labor_efficiency_mom": 0.02,
            "complaint_rate": 0.011,
            "complaint_mom": 0.001,
        },
        "brands": [
            {"brand": "尚宫厨", "store_count": 8, "revenue_fen": 380000000, "revenue_mom": 0.07},
            {"brand": "尝在一起", "store_count": 5, "revenue_fen": 162000000, "revenue_mom": 0.04},
            {"brand": "最黔线", "store_count": 2, "revenue_fen": 68000000, "revenue_mom": 0.03},
        ],
        "stores": [
            {"store_id": "s005", "store_name": "尚宫厨·国金店", "city": "上海", "revenue_fen": 68000000, "revenue_mom": 0.09, "health_level": "A"},
            {"store_id": "s006", "store_name": "尚宫厨·新天地店", "city": "上海", "revenue_fen": 35000000, "revenue_mom": -0.05, "health_level": "C"},
            {"store_id": "s010", "store_name": "尚宫厨·西湖店", "city": "杭州", "revenue_fen": 42000000, "revenue_mom": 0.06, "health_level": "B"},
            {"store_id": "s013", "store_name": "尝在一起·南京西路店", "city": "上海", "revenue_fen": 46000000, "revenue_mom": 0.05, "health_level": "B"},
            {"store_id": "s014", "store_name": "尝在一起·湖滨银泰店", "city": "杭州", "revenue_fen": 39000000, "revenue_mom": 0.04, "health_level": "B"},
        ],
    },
    "r003": {
        "region_id": "r003",
        "region_name": "华南大区",
        "manager": "王强",
        "store_count": 8,
        "metrics": {
            "revenue_fen": 320000000,
            "revenue_mom": 0.10,
            "avg_ticket_fen": 9200,
            "avg_ticket_mom": 0.04,
            "turnover_rate": 3.4,
            "turnover_mom": 0.08,
            "gross_margin": 0.60,
            "gross_margin_mom": 0.01,
            "labor_efficiency_fen": 275000,
            "labor_efficiency_mom": 0.06,
            "complaint_rate": 0.007,
            "complaint_mom": -0.003,
        },
        "brands": [
            {"brand": "尝在一起", "store_count": 4, "revenue_fen": 168000000, "revenue_mom": 0.12},
            {"brand": "最黔线", "store_count": 3, "revenue_fen": 108000000, "revenue_mom": 0.08},
            {"brand": "尚宫厨", "store_count": 1, "revenue_fen": 44000000, "revenue_mom": 0.05},
        ],
        "stores": [
            {"store_id": "s007", "store_name": "尝在一起·天河城店", "city": "广州", "revenue_fen": 46000000, "revenue_mom": 0.10, "health_level": "B"},
            {"store_id": "s015", "store_name": "尝在一起·万象城店", "city": "深圳", "revenue_fen": 52000000, "revenue_mom": 0.14, "health_level": "A"},
            {"store_id": "s016", "store_name": "最黔线·珠江新城店", "city": "广州", "revenue_fen": 40000000, "revenue_mom": 0.07, "health_level": "B"},
        ],
    },
    "r004": {
        "region_id": "r004",
        "region_name": "西南大区",
        "manager": "赵静",
        "store_count": 6,
        "metrics": {
            "revenue_fen": 215000000,
            "revenue_mom": -0.02,
            "avg_ticket_fen": 7600,
            "avg_ticket_mom": -0.01,
            "turnover_rate": 2.6,
            "turnover_mom": -0.05,
            "gross_margin": 0.55,
            "gross_margin_mom": -0.04,
            "labor_efficiency_fen": 230000,
            "labor_efficiency_mom": -0.02,
            "complaint_rate": 0.015,
            "complaint_mom": 0.004,
        },
        "brands": [
            {"brand": "最黔线", "store_count": 3, "revenue_fen": 105000000, "revenue_mom": -0.03},
            {"brand": "尝在一起", "store_count": 2, "revenue_fen": 72000000, "revenue_mom": 0.01},
            {"brand": "尚宫厨", "store_count": 1, "revenue_fen": 38000000, "revenue_mom": -0.05},
        ],
        "stores": [
            {"store_id": "s008", "store_name": "最黔线·春熙路店", "city": "成都", "revenue_fen": 22000000, "revenue_mom": -0.10, "health_level": "D"},
            {"store_id": "s009", "store_name": "尝在一起·解放碑店", "city": "重庆", "revenue_fen": 35000000, "revenue_mom": -0.03, "health_level": "C"},
            {"store_id": "s017", "store_name": "最黔线·宽窄巷子店", "city": "成都", "revenue_fen": 38000000, "revenue_mom": 0.02, "health_level": "B"},
            {"store_id": "s018", "store_name": "尝在一起·观音桥店", "city": "重庆", "revenue_fen": 37000000, "revenue_mom": 0.01, "health_level": "B"},
        ],
    },
}

# 指标中文名
_METRIC_LABELS = {
    "revenue_fen": "营收（分）",
    "avg_ticket_fen": "客单价（分）",
    "turnover_rate": "翻台率",
    "gross_margin": "毛利率",
    "labor_efficiency_fen": "人效（分/人/天）",
    "complaint_rate": "客诉率",
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

@router.get("/")
async def region_overview(
    dimension: str = Query("region", description="维度: region / brand"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """区域/品牌维度汇总数据"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("region_overview", tenant_id=str(tenant_id), dimension=dimension)

    if dimension == "brand":
        # 按品牌聚合
        brand_map: dict[str, dict] = {}
        for r in _MOCK_REGIONS.values():
            for b in r["brands"]:
                name = b["brand"]
                if name not in brand_map:
                    brand_map[name] = {
                        "brand": name,
                        "store_count": 0,
                        "revenue_fen": 0,
                        "regions": [],
                    }
                brand_map[name]["store_count"] += b["store_count"]
                brand_map[name]["revenue_fen"] += b["revenue_fen"]
                brand_map[name]["regions"].append(r["region_name"])

        return {
            "ok": True,
            "data": {
                "dimension": "brand",
                "items": list(brand_map.values()),
                "total": len(brand_map),
            },
        }

    # 按区域
    items = []
    for r in _MOCK_REGIONS.values():
        items.append({
            "region_id": r["region_id"],
            "region_name": r["region_name"],
            "manager": r["manager"],
            "store_count": r["store_count"],
            "metrics": r["metrics"],
            "brands": r["brands"],
        })

    # 全集团汇总
    total_revenue = sum(r["metrics"]["revenue_fen"] for r in _MOCK_REGIONS.values())
    total_stores = sum(r["store_count"] for r in _MOCK_REGIONS.values())

    return {
        "ok": True,
        "data": {
            "dimension": "region",
            "items": items,
            "total": len(items),
            "group_summary": {
                "total_stores": total_stores,
                "total_revenue_fen": total_revenue,
                "metric_labels": _METRIC_LABELS,
            },
        },
    }


@router.get("/{region_id}/stores")
async def region_stores(
    region_id: str,
    sort_by: str = Query("revenue_fen", description="排序: revenue_fen/health_level"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """区域内门店列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("region_stores", tenant_id=str(tenant_id), region_id=region_id)

    region = _MOCK_REGIONS.get(region_id)
    if not region:
        raise HTTPException(status_code=404, detail=f"区域不存在: {region_id}")

    stores = list(region["stores"])
    reverse = sort_order == "desc"
    if sort_by == "health_level":
        stores.sort(key=lambda s: s["health_level"], reverse=not reverse)
    else:
        stores.sort(key=lambda s: s.get("revenue_fen", 0), reverse=reverse)

    total = len(stores)
    offset = (page - 1) * size
    items = stores[offset: offset + size]

    return {
        "ok": True,
        "data": {
            "region_id": region["region_id"],
            "region_name": region["region_name"],
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }
