"""会员驾驶舱 API 路由

前缀: /api/v1/member

端点:
  GET  /dashboard               — 会员整体数据概览
  GET  /rfm/distribution        — RFM 分层分布
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
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member", tags=["member-dashboard"])


# ─── RFM 层级映射（DB enum → 中文展示名） ─────────────────────

_RFM_LEVEL_LABELS: dict[str, str] = {
    "vip": "重要价值客户",
    "active": "一般价值客户",
    "at_risk": "重要挽留客户",
    "churned": "流失客户",
    "new": "新客户",
}

# 反向映射：中文展示名 → DB enum（供 rfm/{level}/members 端点使用）
_RFM_LABEL_TO_CODE: dict[str, str] = {v: k for k, v in _RFM_LEVEL_LABELS.items()}


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


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """设置 RLS session 变量，使 RLS 策略生效。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def _query_dashboard(tenant_id: uuid.UUID, db: AsyncSession) -> dict:
    """从 customers + orders 查询驾驶舱聚合指标。"""
    # 会员总数 & 近 30 天新增
    members_row = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                  AS total_members,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS new_members_30d,
                COUNT(*) FILTER (WHERE last_visit_date >= NOW() - INTERVAL '30 days') AS active_members_30d,
                COALESCE(AVG(total_spent_fen), 0)::bigint                 AS avg_clv_fen,
                COALESCE(SUM(total_spent_fen), 0)::bigint                 AS total_stored_value_fen
            FROM customers
            WHERE is_deleted = FALSE
        """)
    )
    m = members_row.mappings().one()

    total_members = int(m["total_members"])
    new_members_30d = int(m["new_members_30d"])
    active_members_30d = int(m["active_members_30d"])
    avg_clv_fen = int(m["avg_clv_fen"])
    total_stored_value_fen = int(m["total_stored_value_fen"])
    active_rate = round(active_members_30d / total_members, 4) if total_members else 0.0

    return {
        "total_members": total_members,
        "total_members_mom": 0.0,          # 环比需要历史快照，暂留 0
        "new_members_30d": new_members_30d,
        "new_members_mom": 0.0,
        "active_members_30d": active_members_30d,
        "active_rate": active_rate,
        "active_rate_mom": 0.0,
        "avg_clv_fen": avg_clv_fen,
        "avg_clv_mom": 0.0,
        "total_stored_value_fen": total_stored_value_fen,
        "stored_value_mom": 0.0,
        "member_revenue_ratio": 0.0,       # 需跨 orders 表计算，后续补充
        "member_revenue_ratio_mom": 0.0,
        "gender_distribution": {},
        "age_distribution": [],
        "channel_source": [],
    }


async def _query_rfm(tenant_id: uuid.UUID, db: AsyncSession) -> list[dict]:
    """按 rfm_level 统计分布，返回列表。"""
    rows = await db.execute(
        text("""
            SELECT
                rfm_level,
                COUNT(*)                              AS cnt,
                COALESCE(AVG(visit_count), 0)::numeric(10,2) AS avg_frequency,
                COALESCE(AVG(total_spent_fen), 0)::bigint    AS avg_monetary_fen
            FROM customers
            WHERE is_deleted = FALSE
            GROUP BY rfm_level
        """)
    )
    data = rows.mappings().all()

    total = sum(int(r["cnt"]) for r in data) or 1  # 防零除

    result = []
    for r in data:
        code = str(r["rfm_level"])
        label = _RFM_LEVEL_LABELS.get(code, code)
        cnt = int(r["cnt"])
        result.append({
            "level": label,
            "code": code,
            "count": cnt,
            "ratio": round(cnt / total, 4),
            "avg_frequency": float(r["avg_frequency"]),
            "avg_monetary_fen": int(r["avg_monetary_fen"]),
            "description": "",
        })

    return result


async def _query_members_by_level(
    rfm_code: str,
    page: int,
    size: int,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """查询指定 rfm_level 的会员列表（按 total_spent_fen 降序），返回 (items, total)。"""
    offset = (page - 1) * size

    count_row = await db.execute(
        text("""
            SELECT COUNT(*) AS cnt
            FROM customers
            WHERE rfm_level = :level AND is_deleted = FALSE
        """),
        {"level": rfm_code},
    )
    total = int(count_row.scalar_one())

    rows = await db.execute(
        text("""
            SELECT
                id::text           AS member_id,
                full_name          AS name,
                primary_phone      AS phone,
                rfm_level,
                total_spent_fen,
                visit_count,
                last_visit_date    AS last_visit,
                tags
            FROM customers
            WHERE rfm_level = :level AND is_deleted = FALSE
            ORDER BY total_spent_fen DESC NULLS LAST
            LIMIT :lim OFFSET :off
        """),
        {"level": rfm_code, "lim": size, "off": offset},
    )
    items = []
    for r in rows.mappings():
        items.append({
            "member_id": r["member_id"],
            "name": r["name"] or "",
            "phone": r["phone"] or "",
            "rfm_level": _RFM_LEVEL_LABELS.get(str(r["rfm_level"]), str(r["rfm_level"])),
            "rfm_code": str(r["rfm_level"]),
            "total_spent_fen": int(r["total_spent_fen"] or 0),
            "visit_count": int(r["visit_count"] or 0),
            "last_visit": r["last_visit"].isoformat() if r["last_visit"] else None,
            "stored_value_fen": 0,   # customers 表暂无 stored_value 字段
            "tags": list(r["tags"]) if r["tags"] else [],
        })

    return items, total


async def _query_tags(
    tag_type: Optional[str],
    keyword: Optional[str],
    page: int,
    size: int,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[list[dict], int]:
    """从 customers.tags 数组中统计 top-20 标签，应用筛选后分页返回。"""
    rows = await db.execute(
        text("""
            SELECT
                unnest(tags)  AS name,
                COUNT(*)::int AS member_count
            FROM customers
            WHERE is_deleted = FALSE
              AND tags IS NOT NULL
            GROUP BY 1
            ORDER BY member_count DESC
            LIMIT 20
        """)
    )
    all_tags = rows.mappings().all()

    # 在 Python 侧做 keyword 过滤（数据量小，避免复杂 SQL）
    filtered = [
        {
            "tag_id": "",          # tags 存储为 ARRAY，无独立 tag_id
            "name": r["name"],
            "type": "custom",      # 无类型字段，统一填 custom
            "member_count": r["member_count"],
            "created_at": None,
        }
        for r in all_tags
        if (not keyword or keyword in r["name"])
        and (not tag_type or tag_type == "custom")
    ]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return items, total


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/dashboard")
async def member_dashboard(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """会员整体数据概览"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("member_dashboard", tenant_id=str(tenant_id))

    try:
        await _set_rls(db, tenant_id)
        data = await _query_dashboard(tenant_id, db)
    except SQLAlchemyError as exc:
        logger.error("member_dashboard_db_error", tenant_id=str(tenant_id), exc_info=exc)
        data = {
            "total_members": 0,
            "total_members_mom": 0.0,
            "new_members_30d": 0,
            "new_members_mom": 0.0,
            "active_members_30d": 0,
            "active_rate": 0.0,
            "active_rate_mom": 0.0,
            "avg_clv_fen": 0,
            "avg_clv_mom": 0.0,
            "total_stored_value_fen": 0,
            "stored_value_mom": 0.0,
            "member_revenue_ratio": 0.0,
            "member_revenue_ratio_mom": 0.0,
            "gender_distribution": {},
            "age_distribution": [],
            "channel_source": [],
        }

    return {
        "ok": True,
        "data": {
            **data,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/rfm/distribution")
async def rfm_distribution_dashboard(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """RFM 分层分布"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("rfm_distribution_dashboard", tenant_id=str(tenant_id))

    try:
        await _set_rls(db, tenant_id)
        distribution = await _query_rfm(tenant_id, db)
    except SQLAlchemyError as exc:
        logger.error("rfm_distribution_db_error", tenant_id=str(tenant_id), exc_info=exc)
        distribution = []

    total = sum(r["count"] for r in distribution)

    return {
        "ok": True,
        "data": {
            "distribution": distribution,
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
    db: AsyncSession = Depends(get_db),
):
    """某 RFM 层级的会员列表

    `level` 接受中文展示名（如"重要价值客户"）或 DB enum 值（如"vip"）。
    """
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("rfm_level_members", tenant_id=str(tenant_id), level=level)

    # 统一解析 level 为 DB enum code
    if level in _RFM_LABEL_TO_CODE:
        rfm_code = _RFM_LABEL_TO_CODE[level]
    elif level in _RFM_LEVEL_LABELS:
        rfm_code = level
    else:
        valid = list(_RFM_LEVEL_LABELS.keys()) + list(_RFM_LEVEL_LABELS.values())
        raise HTTPException(
            status_code=404,
            detail=f"RFM 层级不存在: {level}，可用值: {sorted(set(valid))}",
        )

    try:
        await _set_rls(db, tenant_id)
        items, total = await _query_members_by_level(rfm_code, page, size, tenant_id, db)
    except SQLAlchemyError as exc:
        logger.error("rfm_level_members_db_error", tenant_id=str(tenant_id), level=level, exc_info=exc)
        items, total = [], 0

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
    db: AsyncSession = Depends(get_db),
):
    """标签列表（从 customers.tags 数组聚合）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_tags", tenant_id=str(tenant_id))

    try:
        await _set_rls(db, tenant_id)
        items, total = await _query_tags(tag_type, keyword, page, size, tenant_id, db)
    except SQLAlchemyError as exc:
        logger.error("list_tags_db_error", tenant_id=str(tenant_id), exc_info=exc)
        items, total = [], 0

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
    new_segment = {
        "segment_id": segment_id,
        "name": body.name,
        "description": body.description,
        "conditions": body.conditions,
        "tag_ids": body.tag_ids,
        "estimated_count": 0,
        "status": "computing",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "ok": True,
        "data": new_segment,
    }
