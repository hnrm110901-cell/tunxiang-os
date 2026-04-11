"""会员驾驶舱 API 路由

前缀: /api/v1/member

端点:
  GET  /dashboard               — 会员整体数据概览
  GET  /rfm/distribution        — RFM 分层分布（注: 此端点与 rfm_routes 不冲突，此为 Mock 版本供驾驶舱页面使用）
  GET  /rfm/{level}/members     — 某层会员列表
  GET  /tags                    — 标签列表
  POST /tags                    — 创建标签
  POST /segments                — 创建人群包
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member", tags=["member-dashboard"])


# ─── Mock 数据 ───────────────────────────────────────────────

_MOCK_DASHBOARD = {
    "total_members": 128356,
    "total_members_mom": 0.06,
    "new_members_30d": 4218,
    "new_members_mom": 0.12,
    "active_members_30d": 52340,
    "active_rate": 0.408,
    "active_rate_mom": 0.03,
    "avg_clv_fen": 286000,
    "avg_clv_mom": 0.05,
    "total_stored_value_fen": 18520000000,
    "stored_value_mom": 0.04,
    "member_revenue_ratio": 0.72,
    "member_revenue_ratio_mom": 0.02,
    "gender_distribution": {"male": 0.42, "female": 0.55, "unknown": 0.03},
    "age_distribution": [
        {"range": "18-25", "ratio": 0.18},
        {"range": "26-35", "ratio": 0.38},
        {"range": "36-45", "ratio": 0.25},
        {"range": "46-55", "ratio": 0.12},
        {"range": "56+", "ratio": 0.07},
    ],
    "channel_source": [
        {"channel": "小程序", "count": 52800, "ratio": 0.41},
        {"channel": "门店扫码", "count": 38500, "ratio": 0.30},
        {"channel": "公众号", "count": 19200, "ratio": 0.15},
        {"channel": "抖音", "count": 10260, "ratio": 0.08},
        {"channel": "美团", "count": 7596, "ratio": 0.06},
    ],
}

_MOCK_RFM = [
    {"level": "重要价值客户", "code": "111", "count": 15800, "ratio": 0.123, "avg_frequency": 8.2, "avg_monetary_fen": 52000, "description": "高频高消费，近期活跃"},
    {"level": "重要发展客户", "code": "101", "count": 12400, "ratio": 0.097, "avg_frequency": 2.5, "avg_monetary_fen": 48000, "description": "高消费但频次低，近期活跃"},
    {"level": "重要保持客户", "code": "011", "count": 18200, "ratio": 0.142, "avg_frequency": 7.8, "avg_monetary_fen": 45000, "description": "高频高消费，近期沉默"},
    {"level": "重要挽留客户", "code": "001", "count": 9600, "ratio": 0.075, "avg_frequency": 1.8, "avg_monetary_fen": 42000, "description": "高消费，流失风险高"},
    {"level": "一般价值客户", "code": "110", "count": 22400, "ratio": 0.175, "avg_frequency": 6.5, "avg_monetary_fen": 18000, "description": "高频低消费，近期活跃"},
    {"level": "一般发展客户", "code": "100", "count": 16800, "ratio": 0.131, "avg_frequency": 2.0, "avg_monetary_fen": 15000, "description": "低消费低频，近期活跃"},
    {"level": "一般保持客户", "code": "010", "count": 19500, "ratio": 0.152, "avg_frequency": 5.2, "avg_monetary_fen": 12000, "description": "高频低消费，近期沉默"},
    {"level": "流失客户", "code": "000", "count": 13656, "ratio": 0.106, "avg_frequency": 1.2, "avg_monetary_fen": 8000, "description": "低频低消费，已沉默"},
]

_MOCK_MEMBERS = [
    {"member_id": "m001", "name": "张三", "phone": "138****1001", "rfm_level": "重要价值客户", "rfm_code": "111", "total_spent_fen": 128000, "visit_count": 12, "last_visit": "2026-04-08", "stored_value_fen": 50000, "tags": ["高频", "火锅爱好者"]},
    {"member_id": "m002", "name": "李四", "phone": "139****2002", "rfm_level": "重要价值客户", "rfm_code": "111", "total_spent_fen": 96000, "visit_count": 9, "last_visit": "2026-04-07", "stored_value_fen": 30000, "tags": ["高频", "商务宴请"]},
    {"member_id": "m003", "name": "王五", "phone": "136****3003", "rfm_level": "重要发展客户", "rfm_code": "101", "total_spent_fen": 85000, "visit_count": 3, "last_visit": "2026-04-05", "stored_value_fen": 20000, "tags": ["高客单"]},
    {"member_id": "m004", "name": "赵六", "phone": "135****4004", "rfm_level": "重要保持客户", "rfm_code": "011", "total_spent_fen": 110000, "visit_count": 15, "last_visit": "2026-03-15", "stored_value_fen": 8000, "tags": ["高频", "沉默预警"]},
    {"member_id": "m005", "name": "孙七", "phone": "137****5005", "rfm_level": "重要挽留客户", "rfm_code": "001", "total_spent_fen": 72000, "visit_count": 2, "last_visit": "2026-02-20", "stored_value_fen": 5000, "tags": ["流失风险"]},
    {"member_id": "m006", "name": "周八", "phone": "158****6006", "rfm_level": "一般价值客户", "rfm_code": "110", "total_spent_fen": 35000, "visit_count": 8, "last_visit": "2026-04-09", "stored_value_fen": 0, "tags": ["高频", "小吃控"]},
    {"member_id": "m007", "name": "吴九", "phone": "150****7007", "rfm_level": "一般发展客户", "rfm_code": "100", "total_spent_fen": 18000, "visit_count": 2, "last_visit": "2026-04-01", "stored_value_fen": 0, "tags": ["新客"]},
    {"member_id": "m008", "name": "郑十", "phone": "131****8008", "rfm_level": "一般保持客户", "rfm_code": "010", "total_spent_fen": 28000, "visit_count": 6, "last_visit": "2026-03-10", "stored_value_fen": 2000, "tags": ["沉默预警"]},
    {"member_id": "m009", "name": "钱十一", "phone": "132****9009", "rfm_level": "流失客户", "rfm_code": "000", "total_spent_fen": 12000, "visit_count": 1, "last_visit": "2026-01-05", "stored_value_fen": 0, "tags": ["流失"]},
    {"member_id": "m010", "name": "陈十二", "phone": "155****0010", "rfm_level": "重要价值客户", "rfm_code": "111", "total_spent_fen": 145000, "visit_count": 18, "last_visit": "2026-04-10", "stored_value_fen": 80000, "tags": ["VIP", "高频", "生日4月"]},
    {"member_id": "m011", "name": "林十三", "phone": "186****1111", "rfm_level": "一般价值客户", "rfm_code": "110", "total_spent_fen": 32000, "visit_count": 7, "last_visit": "2026-04-06", "stored_value_fen": 1000, "tags": ["午餐党"]},
    {"member_id": "m012", "name": "黄十四", "phone": "177****1212", "rfm_level": "重要保持客户", "rfm_code": "011", "total_spent_fen": 92000, "visit_count": 11, "last_visit": "2026-03-02", "stored_value_fen": 15000, "tags": ["沉默预警", "家庭聚餐"]},
]

_MOCK_TAGS = [
    {"tag_id": "t001", "name": "高频", "type": "behavior", "member_count": 38200, "created_at": "2026-01-15T10:00:00Z"},
    {"tag_id": "t002", "name": "高客单", "type": "behavior", "member_count": 15600, "created_at": "2026-01-15T10:00:00Z"},
    {"tag_id": "t003", "name": "火锅爱好者", "type": "preference", "member_count": 22100, "created_at": "2026-02-01T10:00:00Z"},
    {"tag_id": "t004", "name": "商务宴请", "type": "scene", "member_count": 8900, "created_at": "2026-02-01T10:00:00Z"},
    {"tag_id": "t005", "name": "沉默预警", "type": "lifecycle", "member_count": 19500, "created_at": "2026-03-01T10:00:00Z"},
    {"tag_id": "t006", "name": "流失风险", "type": "lifecycle", "member_count": 9600, "created_at": "2026-03-01T10:00:00Z"},
    {"tag_id": "t007", "name": "VIP", "type": "tier", "member_count": 5200, "created_at": "2026-01-15T10:00:00Z"},
    {"tag_id": "t008", "name": "新客", "type": "lifecycle", "member_count": 4218, "created_at": "2026-01-15T10:00:00Z"},
    {"tag_id": "t009", "name": "午餐党", "type": "behavior", "member_count": 16800, "created_at": "2026-03-15T10:00:00Z"},
    {"tag_id": "t010", "name": "家庭聚餐", "type": "scene", "member_count": 12400, "created_at": "2026-02-20T10:00:00Z"},
]


# ─── 请求模型 ────────────────────────────────────────────────

class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="标签名称")
    type: str = Field(..., description="标签类型: behavior/preference/scene/lifecycle/tier/custom")
    rules: list[dict] = Field(default_factory=list, description="标签规则条件")
    description: Optional[str] = None


class CreateSegmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="人群包名称")
    description: Optional[str] = None
    conditions: list[dict] = Field(..., min_length=1, description="筛选条件组合")
    tag_ids: list[str] = Field(default_factory=list, description="包含的标签ID")


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/dashboard")
async def member_dashboard(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """会员整体数据概览"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("member_dashboard", tenant_id=str(tenant_id))

    return {
        "ok": True,
        "data": {
            **_MOCK_DASHBOARD,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/rfm/distribution")
async def rfm_distribution_dashboard(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """RFM 分层分布（驾驶舱 Mock 版本）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("rfm_distribution_dashboard", tenant_id=str(tenant_id))

    total = sum(r["count"] for r in _MOCK_RFM)

    return {
        "ok": True,
        "data": {
            "distribution": _MOCK_RFM,
            "total": total,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/rfm/{level}/members")
async def rfm_level_members(
    level: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """某 RFM 层级的会员列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("rfm_level_members", tenant_id=str(tenant_id), level=level)

    # 验证层级存在
    valid_levels = {r["level"] for r in _MOCK_RFM}
    if level not in valid_levels:
        raise HTTPException(
            status_code=404,
            detail=f"RFM 层级不存在: {level}，可用层级: {sorted(valid_levels)}",
        )

    # 筛选对应层级会员
    filtered = [m for m in _MOCK_MEMBERS if m["rfm_level"] == level]
    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {
        "ok": True,
        "data": {
            "level": level,
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/tags")
async def list_tags(
    tag_type: Optional[str] = Query(None, description="标签类型筛选"),
    keyword: Optional[str] = Query(None, description="名称搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """标签列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_tags", tenant_id=str(tenant_id))

    filtered = list(_MOCK_TAGS)
    if tag_type:
        filtered = [t for t in filtered if t["type"] == tag_type]
    if keyword:
        filtered = [t for t in filtered if keyword in t["name"]]

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


@router.post("/tags")
async def create_tag(
    body: CreateTagRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """创建标签"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_tag", tenant_id=str(tenant_id), name=body.name, tag_type=body.type)

    tag_id = str(uuid.uuid4())
    new_tag = {
        "tag_id": tag_id,
        "name": body.name,
        "type": body.type,
        "rules": body.rules,
        "description": body.description,
        "member_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "ok": True,
        "data": new_tag,
    }


@router.post("/segments")
async def create_segment(
    body: CreateSegmentRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """创建人群包"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_segment", tenant_id=str(tenant_id), name=body.name)

    segment_id = str(uuid.uuid4())
    # Mock: 根据条件数量模拟估算人数
    estimated_count = max(500, 128356 // (len(body.conditions) * 3 + 1))

    new_segment = {
        "segment_id": segment_id,
        "name": body.name,
        "description": body.description,
        "conditions": body.conditions,
        "tag_ids": body.tag_ids,
        "estimated_count": estimated_count,
        "status": "computing",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "ok": True,
        "data": new_segment,
    }
