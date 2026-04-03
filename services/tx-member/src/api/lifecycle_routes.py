"""会员生命周期 API 端点

6 个路由：
  GET  /lifecycle/stats?store_id=          - 各阶段统计（数量 + 占比）
  GET  /lifecycle/members?stage=&store_id= - 按阶段查会员列表
  POST /lifecycle/reclassify               - 触发批量重分类（夜批/手动）
  GET  /lifecycle/events?member_id=        - 单会员生命周期事件历史
  GET  /lifecycle/config                   - 查询所有阶段配置（阈值 + 自动动作）
  PUT  /lifecycle/config/{stage}           - 更新指定阶段配置

# ROUTER REGISTRATION (在 tx-member/src/main.py 中添加):
# from .api.lifecycle_routes import router as lifecycle_router
# app.include_router(lifecycle_router, prefix="/api/v1/lifecycle")
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.lifecycle_service import LifecycleService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/lifecycle", tags=["member-lifecycle"])

_service = LifecycleService()


# ── 工具函数 ──────────────────────────────────────────────────


def _parse_tenant(x_tenant_id: str) -> uuid.UUID:
    """解析并验证 X-Tenant-ID header"""
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


# ── 请求/响应模型 ─────────────────────────────────────────────


class LifecycleConfigUpdateReq(BaseModel):
    """更新阶段配置请求体"""

    days_threshold: Optional[int] = Field(
        None, ge=1, description="判断天数阈值（天）"
    )
    auto_action: Optional[str] = Field(
        None, description="自动触发动作：coupon / wecom_message / sms / none"
    )
    coupon_template_id: Optional[str] = Field(
        None, description="发券时使用的券模板 UUID"
    )
    message_template: Optional[str] = Field(
        None, description="企微/短信推送消息模板"
    )
    is_active: Optional[bool] = Field(None, description="是否启用该阶段规则")


# ── 1. 各阶段统计 ─────────────────────────────────────────────


@router.get("/stats")
async def get_lifecycle_stats(
    store_id: Optional[str] = Query(None, description="门店 UUID，不传则查全部门店"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询各生命周期阶段的会员数量和占比。

    Returns:
        {ok, data: {new, active, dormant, churned, reactivated, total,
                    ratios: {new: float, ...}, as_of: str}}
    """
    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    stats = await _service.get_lifecycle_stats(
        tenant_id=str(tenant_id),
        store_id=store_id,
        db=db,
    )

    from datetime import datetime, timezone

    logger.info(
        "lifecycle_stats_queried",
        tenant_id=str(tenant_id),
        store_id=store_id,
        total=stats.get("total", 0),
    )

    return {
        "ok": True,
        "data": {
            **stats,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── 2. 按阶段查会员列表 ────────────────────────────────────────


@router.get("/members")
async def get_lifecycle_members(
    stage: str = Query(..., description="阶段：new / active / dormant / churned / reactivated"),
    store_id: Optional[str] = Query(None, description="门店 UUID 过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询指定生命周期阶段的会员列表（分页）。

    Returns:
        {ok, data: {items: [...], total, page, size}}
    """
    valid_stages = ("new", "active", "dormant", "churned", "reactivated")
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"stage 必须是 {valid_stages} 之一，got: {stage!r}",
        )

    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    where_store = "AND store_id = :store_id" if store_id else ""
    count_sql = text(f"""
        SELECT count(*)
        FROM customers
        WHERE tenant_id = :tid
          AND is_deleted = FALSE
          AND lifecycle_stage = :stage
          {where_store}
    """)
    list_sql = text(f"""
        SELECT id, display_name, primary_phone, lifecycle_stage,
               first_order_at, last_order_at, rfm_level, total_order_count
        FROM customers
        WHERE tenant_id = :tid
          AND is_deleted = FALSE
          AND lifecycle_stage = :stage
          {where_store}
        ORDER BY last_order_at DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """)

    params: dict[str, Any] = {
        "tid": str(tenant_id),
        "stage": stage,
        "limit": size,
        "offset": (page - 1) * size,
    }
    if store_id:
        params["store_id"] = store_id

    count_result = await db.execute(count_sql, params)
    total = count_result.scalar() or 0

    rows_result = await db.execute(list_sql, params)
    items = [
        {
            "customer_id": str(row[0]),
            "display_name": row[1],
            "primary_phone": row[2],
            "lifecycle_stage": row[3],
            "first_order_at": row[4].isoformat() if row[4] else None,
            "last_order_at": row[5].isoformat() if row[5] else None,
            "rfm_level": row[6],
            "total_order_count": row[7],
        }
        for row in rows_result.fetchall()
    ]

    logger.info(
        "lifecycle_members_queried",
        tenant_id=str(tenant_id),
        stage=stage,
        store_id=store_id,
        total=total,
        page=page,
    )

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ── 3. 触发批量重分类 ─────────────────────────────────────────


@router.post("/reclassify")
async def trigger_reclassify(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动触发批量重分类（夜批可直接调用此接口）。

    Returns:
        {ok, data: {new, active, dormant, churned, reactivated, changed, elapsed_seconds}}
    """
    import time

    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    logger.info("lifecycle_reclassify_triggered", tenant_id=str(tenant_id))

    t0 = time.monotonic()
    result = await _service.batch_reclassify(
        tenant_id=str(tenant_id), db=db
    )
    elapsed = round(time.monotonic() - t0, 3)

    logger.info(
        "lifecycle_reclassify_done",
        tenant_id=str(tenant_id),
        elapsed_seconds=elapsed,
        **result,
    )

    return {
        "ok": True,
        "data": {**result, "elapsed_seconds": elapsed},
    }


# ── 4. 单会员事件历史 ─────────────────────────────────────────


@router.get("/events")
async def get_lifecycle_events(
    member_id: str = Query(..., description="会员 UUID"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询单个会员的生命周期事件历史（阶段变更记录）。

    Returns:
        {ok, data: {items: [...], total, page, size}}
    """
    tenant_id = _parse_tenant(x_tenant_id)

    # 校验 member_id 格式
    try:
        uuid.UUID(member_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"member_id 必须是有效 UUID，got: {member_id!r}",
        ) from exc

    await _set_rls(db, tenant_id)

    count_result = await db.execute(
        text("""
            SELECT count(*)
            FROM lifecycle_events
            WHERE tenant_id = :tid AND member_id = :mid
        """),
        {"tid": str(tenant_id), "mid": member_id},
    )
    total = count_result.scalar() or 0

    rows_result = await db.execute(
        text("""
            SELECT id, from_stage, to_stage, trigger_reason,
                   action_taken, created_at
            FROM lifecycle_events
            WHERE tenant_id = :tid AND member_id = :mid
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "tid": str(tenant_id),
            "mid": member_id,
            "limit": size,
            "offset": (page - 1) * size,
        },
    )

    items = [
        {
            "event_id": str(row[0]),
            "from_stage": row[1],
            "to_stage": row[2],
            "trigger_reason": row[3],
            "action_taken": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
        }
        for row in rows_result.fetchall()
    ]

    return {
        "ok": True,
        "data": {
            "member_id": member_id,
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


# ── 5. 查询阶段配置 ────────────────────────────────────────────


@router.get("/config")
async def get_lifecycle_config(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询所有阶段的生命周期配置（阈值 + 自动触发动作）。

    若某阶段无自定义配置，则返回系统默认值。

    Returns:
        {ok, data: {configs: [{stage, days_threshold, auto_action, ...}]}}
    """
    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    rows_result = await db.execute(
        text("""
            SELECT stage, days_threshold, auto_action,
                   coupon_template_id, message_template, is_active
            FROM lifecycle_configs
            WHERE tenant_id = :tid
            ORDER BY stage
        """),
        {"tid": str(tenant_id)},
    )
    rows = rows_result.fetchall()

    db_configs = {
        row[0]: {
            "stage": row[0],
            "days_threshold": row[1],
            "auto_action": row[2],
            "coupon_template_id": str(row[3]) if row[3] else None,
            "message_template": row[4],
            "is_active": row[5],
        }
        for row in rows
    }

    # 补全缺失阶段（使用系统默认值）
    default_thresholds = LifecycleService.DEFAULT_THRESHOLDS
    configs = []
    for stage in ("new", "active", "dormant", "churned"):
        if stage in db_configs:
            configs.append(db_configs[stage])
        else:
            configs.append({
                "stage": stage,
                "days_threshold": default_thresholds.get(stage),
                "auto_action": "none",
                "coupon_template_id": None,
                "message_template": None,
                "is_active": False,
                "_is_default": True,
            })

    return {"ok": True, "data": {"configs": configs}}


# ── 6. 更新阶段配置 ────────────────────────────────────────────


@router.put("/config/{stage}")
async def update_lifecycle_config(
    stage: str,
    body: LifecycleConfigUpdateReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新指定阶段的生命周期配置（UPSERT）。

    Returns:
        {ok, data: {stage, days_threshold, auto_action, ...}}
    """
    valid_stages = ("new", "active", "dormant", "churned")
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"stage 必须是 {valid_stages} 之一，got: {stage!r}",
        )

    valid_actions = ("coupon", "wecom_message", "sms", "none")
    if body.auto_action is not None and body.auto_action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"auto_action 必须是 {valid_actions} 之一",
        )

    tenant_id = _parse_tenant(x_tenant_id)
    await _set_rls(db, tenant_id)

    upsert_sql = text("""
        INSERT INTO lifecycle_configs
            (tenant_id, stage, days_threshold, auto_action,
             coupon_template_id, message_template, is_active)
        VALUES
            (:tid, :stage, :threshold, :action,
             :coupon_tpl, :msg_tpl, :active)
        ON CONFLICT (tenant_id, stage)
        DO UPDATE SET
            days_threshold     = COALESCE(EXCLUDED.days_threshold, lifecycle_configs.days_threshold),
            auto_action        = COALESCE(EXCLUDED.auto_action, lifecycle_configs.auto_action),
            coupon_template_id = COALESCE(EXCLUDED.coupon_template_id, lifecycle_configs.coupon_template_id),
            message_template   = COALESCE(EXCLUDED.message_template, lifecycle_configs.message_template),
            is_active          = COALESCE(EXCLUDED.is_active, lifecycle_configs.is_active),
            updated_at         = NOW()
        RETURNING stage, days_threshold, auto_action,
                  coupon_template_id, message_template, is_active
    """)

    result = await db.execute(
        upsert_sql,
        {
            "tid": str(tenant_id),
            "stage": stage,
            "threshold": body.days_threshold,
            "action": body.auto_action,
            "coupon_tpl": body.coupon_template_id,
            "msg_tpl": body.message_template,
            "active": body.is_active,
        },
    )
    await db.commit()

    row = result.fetchone()

    logger.info(
        "lifecycle_config_updated",
        tenant_id=str(tenant_id),
        stage=stage,
        auto_action=row[2] if row else None,
    )

    updated = {
        "stage": row[0],
        "days_threshold": row[1],
        "auto_action": row[2],
        "coupon_template_id": str(row[3]) if row[3] else None,
        "message_template": row[4],
        "is_active": row[5],
    } if row else {"stage": stage, "updated": True}

    return {"ok": True, "data": updated}
