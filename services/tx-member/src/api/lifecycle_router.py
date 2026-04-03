"""会员生命周期新增路由

GET  /api/v1/members/lifecycle/distribution   生命周期分布统计
GET  /api/v1/members/lifecycle/at-risk        流失风险会员列表
POST /api/v1/members/lifecycle/batch-update   触发批量更新
GET  /api/v1/members/{id}/lifecycle           单个会员生命周期详情
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.lifecycle_service import LifecycleService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/members", tags=["member-lifecycle-v2"])

_service = LifecycleService()


# ── 工具函数 ──────────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    """解析并校验 X-Tenant-ID header"""
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"X-Tenant-ID must be a valid UUID, got: {x_tenant_id!r}",
        ) from exc


async def _set_rls(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """设置 PostgreSQL RLS 上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


# ── 1. 生命周期分布统计 ───────────────────────────────────────────


@router.get("/lifecycle/distribution")
async def get_lifecycle_distribution(
    store_id: Optional[str] = Query(None, description="门店 UUID，不传则查全部门店"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """会员生命周期分布统计，返回各阶段人数和占比。

    生命周期阶段：new_member / active / at_risk / churned / reactivated

    Returns:
        {ok, data: {stages: [{stage, count, ratio}], total, as_of, store_id}}
    """
    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    where_store = "AND store_id = :store_id" if store_id else ""
    sql = text(f"""
        SELECT lifecycle_stage, count(*) AS cnt
        FROM customers
        WHERE tenant_id = :tid
          AND is_deleted = FALSE
          {where_store}
        GROUP BY lifecycle_stage
    """)
    params: dict[str, Any] = {"tid": str(tenant_id)}
    if store_id:
        params["store_id"] = store_id

    result = await db.execute(sql, params)
    rows = result.fetchall()

    # 累计所有阶段（含项目定义的5个阶段）
    stage_order = ("new_member", "active", "at_risk", "churned", "reactivated")
    counts: dict[str, int] = dict.fromkeys(stage_order, 0)
    total = 0
    for stage, cnt in rows:
        key = stage or "active"
        if key in counts:
            counts[key] = int(cnt)
        else:
            counts[key] = int(cnt)
        total += int(cnt)

    stages = [
        {
            "stage": s,
            "count": counts.get(s, 0),
            "ratio": round(counts.get(s, 0) / total, 4) if total > 0 else 0.0,
        }
        for s in stage_order
    ]

    logger.info(
        "lifecycle_distribution_queried",
        tenant_id=str(tenant_id),
        store_id=store_id,
        total=total,
    )

    return {
        "ok": True,
        "data": {
            "stages": stages,
            "total": total,
            "store_id": store_id,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── 2. 流失风险会员列表 ───────────────────────────────────────────


@router.get("/lifecycle/at-risk")
async def get_at_risk_members(
    store_id: Optional[str] = Query(None, description="门店 UUID 过滤"),
    limit: int = Query(100, ge=1, le=500, description="返回条数上限"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取流失风险会员列表（at_risk + churned 阶段）。

    包含：最后消费时间、消费频次、推荐触达方式。

    Returns:
        {ok, data: {items: [MemberRiskProfile], total}}
    """
    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    where_store = "AND store_id = :store_id" if store_id else ""
    sql = text(f"""
        SELECT
            id,
            display_name,
            primary_phone,
            lifecycle_stage,
            last_order_at,
            total_order_count,
            rfm_level
        FROM customers
        WHERE tenant_id = :tid
          AND is_deleted = FALSE
          AND lifecycle_stage IN ('at_risk', 'churned', 'dormant')
          {where_store}
        ORDER BY last_order_at ASC NULLS LAST
        LIMIT :limit
    """)
    params: dict[str, Any] = {"tid": str(tenant_id), "limit": limit}
    if store_id:
        params["store_id"] = store_id

    result = await db.execute(sql, params)
    rows = result.fetchall()

    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        member_id, display_name, phone, stage, last_order_at, order_count, rfm = row
        last_order_at_tz = last_order_at
        if last_order_at_tz and last_order_at_tz.tzinfo is None:
            last_order_at_tz = last_order_at_tz.replace(tzinfo=timezone.utc)
        days_since_last = (
            (now - last_order_at_tz).days if last_order_at_tz else None
        )

        # 推荐触达方式：流失>90天用企微消息，30-90天用优惠券
        if days_since_last is not None and days_since_last > 90:
            recommended_action = "wecom_message"
        elif days_since_last is not None and days_since_last > 30:
            recommended_action = "coupon"
        else:
            recommended_action = "coupon"

        items.append({
            "member_id": str(member_id),
            "display_name": display_name,
            "primary_phone": phone,
            "lifecycle_stage": stage,
            "last_order_at": last_order_at.isoformat() if last_order_at else None,
            "days_since_last_order": days_since_last,
            "total_order_count": order_count,
            "rfm_level": rfm,
            "recommended_action": recommended_action,
        })

    logger.info(
        "lifecycle_at_risk_queried",
        tenant_id=str(tenant_id),
        store_id=store_id,
        count=len(items),
    )

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": len(items),
        },
    }


# ── 3. 触发批量更新 ──────────────────────────────────────────────


@router.post("/lifecycle/batch-update")
async def batch_update_lifecycle_stages(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """触发批量更新所有会员的生命周期状态（适合每日定时任务调用）。

    Returns:
        {ok, data: {new, active, dormant, churned, reactivated, changed, elapsed_seconds}}
    """
    import time

    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    logger.info("lifecycle_batch_update_triggered", tenant_id=str(tenant_id))

    t0 = time.monotonic()
    result = await _service.batch_reclassify(
        tenant_id=str(tenant_id), db=db
    )
    elapsed = round(time.monotonic() - t0, 3)

    logger.info(
        "lifecycle_batch_update_done",
        tenant_id=str(tenant_id),
        elapsed_seconds=elapsed,
        **result,
    )

    return {
        "ok": True,
        "data": {**result, "elapsed_seconds": elapsed},
    }


# ── 4. 单个会员生命周期详情 ──────────────────────────────────────


@router.get("/{member_id}/lifecycle")
async def get_member_lifecycle(
    member_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取单个会员的生命周期详情。

    自动判断生命周期阶段：
    - new_member: 注册 <30 天
    - active:     近30天有消费
    - at_risk:    30-90天无消费（曾经活跃）
    - churned:    >90天无消费
    - reactivated: 曾经流失后重新消费

    Returns:
        {ok, data: {member_id, lifecycle_stage, days_since_last_order,
                    first_order_at, last_order_at, total_order_count, ...}}
    """
    tenant_id = _parse_tenant(x_tenant_id)

    try:
        uuid.UUID(member_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"member_id 必须是有效 UUID，got: {member_id!r}",
        ) from exc

    await _set_rls(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT
                id, display_name, primary_phone,
                lifecycle_stage, first_order_at, last_order_at,
                total_order_count, rfm_level, created_at
            FROM customers
            WHERE id = :mid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"mid": member_id, "tid": str(tenant_id)},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="会员不存在")

    (
        cid, display_name, phone, stage,
        first_order_at, last_order_at,
        order_count, rfm_level, created_at,
    ) = row

    now = datetime.now(timezone.utc)

    def _days(dt: Optional[datetime]) -> Optional[int]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).days

    days_since_last = _days(last_order_at)
    days_since_join = _days(created_at)

    # 重新计算阶段（基于任务规格的5阶段逻辑）
    computed_stage = stage  # 默认使用 DB 存储值
    if first_order_at is None or days_since_join is not None and days_since_join <= 30:
        computed_stage = "new_member"
    elif days_since_last is not None and days_since_last <= 30:
        computed_stage = "active"
    elif days_since_last is not None and days_since_last <= 90:
        computed_stage = "at_risk"
    elif days_since_last is not None and days_since_last > 90:
        computed_stage = "churned"

    logger.info(
        "lifecycle_member_detail_queried",
        member_id=member_id,
        tenant_id=str(tenant_id),
        stage=computed_stage,
    )

    return {
        "ok": True,
        "data": {
            "member_id": str(cid),
            "display_name": display_name,
            "primary_phone": phone,
            "lifecycle_stage": computed_stage,
            "db_lifecycle_stage": stage,
            "days_since_last_order": days_since_last,
            "days_since_join": days_since_join,
            "first_order_at": first_order_at.isoformat() if first_order_at else None,
            "last_order_at": last_order_at.isoformat() if last_order_at else None,
            "total_order_count": order_count,
            "rfm_level": rfm_level,
            "as_of": now.isoformat(),
        },
    }
