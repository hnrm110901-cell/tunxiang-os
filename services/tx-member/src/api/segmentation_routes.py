"""人群细分 API — AM-1.1 AI 驱动的人群洞察

提供 AI 驱动的会员人群细分能力，供营销 Agent 和 BI 侧调用：
  GET    /api/v1/member/segments                — 列表（内置+自定义）
  POST   /api/v1/member/segments                — 创建自定义人群
  GET    /api/v1/member/segments/{id}           — 详情（含成员数）
  GET    /api/v1/member/segments/{id}/members   — 分页成员列表
  DELETE /api/v1/member/segments/{id}           — 删除自定义人群
  POST   /api/v1/member/segments/{id}/refresh   — 刷新人群缓存

与 tx-agent 人群洞察 Agent 联动：
  - Agent 分析后自动创建细分人群 → 写入此 API
  - 营销编排 Agent 读取人群 → 执行触达策略
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/segments", tags=["member-segmentation"])

# ─── 内置人群定义 ────────────────────────────────────────────────────────────

_BUILT_IN_SEGMENTS = [
    {
        "id": "builtin_all_members",
        "name": "全部会员",
        "description": "所有注册会员",
        "type": "builtin",
        "criteria": {},
        "icon": "👥",
        "color": "#5FA8E8",
    },
    {
        "id": "builtin_active_30d",
        "name": "30天活跃",
        "description": "近30天有到店消费记录的会员",
        "type": "builtin",
        "criteria": {"days_since_last_order__lte": 30},
        "icon": "🔥",
        "color": "#FF6B2C",
    },
    {
        "id": "builtin_dormant_30_90",
        "name": "30-90天沉睡",
        "description": "30-90天未到店但曾经消费过的会员",
        "type": "builtin",
        "criteria": {"days_since_last_order__gte": 30, "days_since_last_order__lte": 90},
        "icon": "💤",
        "color": "#F5A623",
    },
    {
        "id": "builtin_churn_risk_90",
        "name": "90天+流失风险",
        "description": "超过90天未到店的高流失风险会员",
        "type": "builtin",
        "criteria": {"days_since_last_order__gte": 90},
        "icon": "⚠️",
        "color": "#FF3B30",
    },
    {
        "id": "builtin_high_value",
        "name": "高价值会员",
        "description": "累计消费金额TOP20%的会员",
        "type": "builtin",
        "criteria": {"value_tier": "high"},
        "icon": "💎",
        "color": "#FFD700",
    },
    {
        "id": "builtin_new_7d",
        "name": "7日新客",
        "description": "最近7天内注册的新会员",
        "type": "builtin",
        "criteria": {"registered_days__lte": 7},
        "icon": "🌟",
        "color": "#0F6E56",
    },
]

# ─── Pydantic 模型 ───────────────────────────────────────────────────────────


class CreateSegmentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=100, description="人群名称")
    description: Optional[str] = Field(None, max_length=500, description="人群描述")
    criteria: dict[str, Any] = Field(default_factory=dict, description="筛选条件 JSON")
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$", description="显示颜色")


class UpdateSegmentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    criteria: Optional[dict[str, Any]] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _parse_uuid(raw: str, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} 格式无效: {raw}")


def _require_tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    return x_tenant_id


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.get("")
async def list_segments(
    tenant_id: str = Depends(_require_tenant),
    type_filter: Optional[str] = Query(None, alias="type", description="筛选类型: builtin / custom"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """返回内置人群 + 该租户的自定义人群列表。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    segments = list(_BUILT_IN_SEGMENTS)
    if type_filter == "builtin":
        return ok({"segments": segments, "total": len(segments)})

    # 从 DB 读取自定义人群
    try:
        rows = await db.execute(
            text("""
                SELECT id, name, description, criteria, color, member_count,
                       created_at, updated_at
                FROM member_segments
                WHERE tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT is_deleted
                ORDER BY updated_at DESC
            """),
        )
        for row in rows.mappings():
            segments.append({
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"] or "",
                "type": "custom",
                "criteria": row["criteria"] or {},
                "color": row["color"] or "#999999",
                "member_count": row["member_count"] or 0,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            })
    except Exception as exc:  # noqa: BLE001 — route-level handler
        logger.warning("list_segments_db_error", error=str(exc), exc_info=True)

    if type_filter == "custom":
        segments = [s for s in segments if s["type"] == "custom"]

    return ok({"segments": segments, "total": len(segments)})


@router.post("", status_code=201)
async def create_segment(
    body: CreateSegmentBody,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建自定义人群。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    seg_id = uuid.uuid4()
    try:
        await db.execute(
            text("""
                INSERT INTO member_segments (id, tenant_id, name, description, criteria, color)
                VALUES (:id, current_setting('app.tenant_id')::uuid, :name, :desc, :criteria, :color)
            """),
            {
                "id": seg_id,
                "name": body.name,
                "desc": body.description or "",
                "criteria": str(body.criteria) if body.criteria else "{}",
                "color": body.color or "#999999",
            },
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("create_segment_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="创建人群失败")

    return ok({
        "id": str(seg_id),
        "name": body.name,
        "type": "custom",
    })


@router.get("/{segment_id}")
async def get_segment(
    segment_id: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取单个人群详情。"""
    # 先查内置
    for s in _BUILT_IN_SEGMENTS:
        if s["id"] == segment_id:
            return ok(s)

    _parse_uuid(segment_id, "segment_id")
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    try:
        row = await db.execute(
            text("""
                SELECT id, name, description, criteria, color, member_count,
                       created_at, updated_at
                FROM member_segments
                WHERE id = :sid
                  AND tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT is_deleted
            """),
            {"sid": segment_id},
        )
        seg = row.mappings().one_or_none()
    except Exception as exc:
        logger.error("get_segment_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询人群失败")

    if not seg:
        raise HTTPException(status_code=404, detail="人群不存在")

    return ok({
        "id": str(seg["id"]),
        "name": seg["name"],
        "description": seg["description"] or "",
        "type": "custom",
        "criteria": seg["criteria"] or {},
        "color": seg["color"] or "#999999",
        "member_count": seg["member_count"] or 0,
        "created_at": seg["created_at"].isoformat() if seg["created_at"] else None,
        "updated_at": seg["updated_at"].isoformat() if seg["updated_at"] else None,
    })


@router.get("/{segment_id}/members")
async def list_segment_members(
    segment_id: str,
    tenant_id: str = Depends(_require_tenant),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """分页获取人群中的会员列表。"""
    _parse_uuid(segment_id, "segment_id")
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    try:
        # 读取人群表 → 从 member_segment_members 关联表分页
        count_row = await db.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM member_segment_members msm
                JOIN member_segments ms ON ms.id = msm.segment_id
                WHERE msm.segment_id = :sid
                  AND ms.tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT ms.is_deleted
            """),
            {"sid": segment_id},
        )
        total = count_row.scalar() or 0

        offset = (page - 1) * size
        rows = await db.execute(
            text("""
                SELECT msm.member_id, msm.added_at
                FROM member_segment_members msm
                JOIN member_segments ms ON ms.id = msm.segment_id
                WHERE msm.segment_id = :sid
                  AND ms.tenant_id = current_setting('app.tenant_id')::uuid
                  AND NOT ms.is_deleted
                ORDER BY msm.added_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"sid": segment_id, "limit": size, "offset": offset},
        )
        members = [
            {
                "member_id": str(r["member_id"]),
                "added_at": r["added_at"].isoformat() if r["added_at"] else None,
            }
            for r in rows.mappings()
        ]
    except Exception as exc:
        logger.error("list_segment_members_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询人群成员失败")

    return ok({
        "members": members,
        "total": total,
        "page": page,
        "size": size,
    })


@router.delete("/{segment_id}")
async def delete_segment(
    segment_id: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """软删除自定义人群。"""
    _parse_uuid(segment_id, "segment_id")
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    try:
        result = await db.execute(
            text("""
                UPDATE member_segments
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :sid
                  AND tenant_id = current_setting('app.tenant_id')::uuid
            """),
            {"sid": segment_id},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="人群不存在")
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("delete_segment_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="删除人群失败")

    return ok({"deleted": True})


@router.post("/{segment_id}/refresh")
async def refresh_segment(
    segment_id: str,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """刷新人群的 member_count 缓存（异步后台任务）。"""
    _parse_uuid(segment_id, "segment_id")
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    try:
        await db.execute(
            text("""
                UPDATE member_segments
                SET member_count = (
                    SELECT COUNT(*) FROM member_segment_members
                    WHERE segment_id = :sid
                ), updated_at = NOW()
                WHERE id = :sid
                  AND tenant_id = current_setting('app.tenant_id')::uuid
            """),
            {"sid": segment_id},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("refresh_segment_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="刷新人群失败")

    return ok({"refreshed": True})
