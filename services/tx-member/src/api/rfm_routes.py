"""RFM 管理 API 端点

提供三个接口：
  POST /api/v1/member/rfm/trigger-update    手动触发全量 RFM 更新（管理端）
  GET  /api/v1/member/rfm/distribution      查询当前 RFM 等级分布（各等级人数）
  GET  /api/v1/member/rfm/changes           查询今日 RFM 等级变化（升级/降级列表）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from workers.rfm_updater import RFMUpdater

from shared.ontology.src.database import get_db
from shared.ontology.src.entities import Customer

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/rfm", tags=["member-rfm"])


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


# ── 1. 手动触发 RFM 更新 ──────────────────────────────────────


@router.post("/trigger-update")
async def trigger_rfm_update(
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动触发 RFM 全量更新（管理端专用）

    - 有 X-Tenant-ID：仅更新指定租户
    - 无 X-Tenant-ID / 传 "all"：更新所有租户（慎用）

    Returns:
        {ok, data: {total_tenants, total_updated, elapsed_seconds}}
    """
    updater = RFMUpdater()

    if x_tenant_id and x_tenant_id.strip() and x_tenant_id.lower() != "all":
        tenant_id = _parse_tenant(x_tenant_id)
        logger.info("rfm_manual_trigger", tenant_id=str(tenant_id))

        # 设置 RLS 上下文
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        updated = await updater.update_tenant_rfm(tenant_id, db)
        result: dict[str, Any] = {
            "total_tenants": 1,
            "total_updated": updated,
            "elapsed_seconds": None,
        }
    else:
        logger.info("rfm_manual_trigger_all")
        result = await updater.update_all_tenants(db)

    return {"ok": True, "data": result}


# ── 2. 查询 RFM 等级分布 ──────────────────────────────────────


@router.get("/distribution")
async def get_rfm_distribution(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询当前 RFM 等级分布（各等级人数及占比）

    Returns:
        {ok, data: {distribution: [{level, count, ratio}], total}}
    """
    tenant_id = _parse_tenant(x_tenant_id)

    # 设置 RLS 上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )

    # 按 rfm_level 分组统计
    result = await db.execute(
        select(
            func.coalesce(Customer.rfm_level, "S3").label("level"),
            func.count(Customer.id).label("count"),
        )
        .where(Customer.tenant_id == tenant_id)
        .where(Customer.is_deleted == False)  # noqa: E712
        .where(Customer.is_merged == False)  # noqa: E712
        .group_by(Customer.rfm_level)
        .order_by(func.coalesce(Customer.rfm_level, "S3"))
    )
    rows = result.all()

    total = sum(row[1] for row in rows)

    distribution = [
        {
            "level": row[0],
            "count": row[1],
            "ratio": round(row[1] / total, 4) if total > 0 else 0.0,
        }
        for row in rows
    ]

    # 补全缺失等级（保证前端始终拿到 S1-S5 五个节点）
    existing_levels = {d["level"] for d in distribution}
    for lvl in ("S1", "S2", "S3", "S4", "S5"):
        if lvl not in existing_levels:
            distribution.append({"level": lvl, "count": 0, "ratio": 0.0})
    distribution.sort(key=lambda x: x["level"])

    logger.info(
        "rfm_distribution_queried",
        tenant_id=str(tenant_id),
        total=total,
        levels={d["level"]: d["count"] for d in distribution},
    )

    return {
        "ok": True,
        "data": {
            "distribution": distribution,
            "total": total,
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    }


# ── 3. 查询今日 RFM 等级变化 ──────────────────────────────────


@router.get("/changes")
async def get_rfm_changes(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    direction: str = Query("all", description="upgrade / downgrade / all"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """查询今日 RFM 等级变化列表（升级 / 降级）

    通过对比 rfm_updated_at 在今日且 rfm_level 不为初始值 S3 来近似判断。
    精确历史对比需要 rfm_change_logs 表（如已建立则使用）。

    Returns:
        {ok, data: {items: [...], total, page, size}}
    """
    tenant_id = _parse_tenant(x_tenant_id)

    # 设置 RLS 上下文
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 尝试从 rfm_change_logs 表查询（如不存在则降级为简易查询）
    try:
        change_sql = text("""
            SELECT
                cl.customer_id,
                c.display_name,
                c.primary_phone,
                cl.old_level,
                cl.new_level,
                cl.changed_at
            FROM rfm_change_logs cl
            JOIN customers c ON c.id = cl.customer_id
            WHERE cl.tenant_id = :tenant_id
              AND cl.changed_at >= :today_start
              AND (:direction = 'all'
                   OR (:direction = 'upgrade' AND cl.new_level < cl.old_level)
                   OR (:direction = 'downgrade' AND cl.new_level > cl.old_level))
            ORDER BY cl.changed_at DESC
            LIMIT :size OFFSET :offset
        """)

        count_sql = text("""
            SELECT count(*)
            FROM rfm_change_logs cl
            WHERE cl.tenant_id = :tenant_id
              AND cl.changed_at >= :today_start
              AND (:direction = 'all'
                   OR (:direction = 'upgrade' AND cl.new_level < cl.old_level)
                   OR (:direction = 'downgrade' AND cl.new_level > cl.old_level))
        """)

        params = {
            "tenant_id": str(tenant_id),
            "today_start": today_start,
            "direction": direction,
            "size": size,
            "offset": (page - 1) * size,
        }

        count_result = await db.execute(count_sql, params)
        total = count_result.scalar() or 0

        rows_result = await db.execute(change_sql, params)
        items = [
            {
                "customer_id": str(row[0]),
                "display_name": row[1],
                "primary_phone": row[2],
                "old_level": row[3],
                "new_level": row[4],
                "changed_at": row[5].isoformat() if row[5] else None,
                "direction": "upgrade" if row[4] < row[3] else "downgrade",
            }
            for row in rows_result.all()
        ]

    except (ProgrammingError, SQLAlchemyError):  # 表不存在时降级
        # rfm_change_logs 表不存在时，返回今日已更新 RFM 的会员列表
        logger.warning(
            "rfm_change_logs_unavailable",
            tenant_id=str(tenant_id),
            hint="table rfm_change_logs may not exist, returning today-updated customers",
            exc_info=True,
        )

        base_query = (
            select(
                Customer.id,
                Customer.display_name,
                Customer.primary_phone,
                Customer.rfm_level,
                Customer.rfm_updated_at,
                Customer.r_score,
            )
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)  # noqa: E712
            .where(Customer.rfm_updated_at >= today_start)
        )

        count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
        total = count_result.scalar() or 0

        page_result = await db.execute(
            base_query.order_by(Customer.rfm_updated_at.desc()).offset((page - 1) * size).limit(size)
        )
        items = [
            {
                "customer_id": str(row[0]),
                "display_name": row[1],
                "primary_phone": row[2],
                "rfm_level": row[3],
                "rfm_updated_at": row[4].isoformat() if row[4] else None,
                "old_level": None,
                "new_level": row[3],
                "direction": "unknown",
            }
            for row in page_result.all()
        ]

    logger.info(
        "rfm_changes_queried",
        tenant_id=str(tenant_id),
        direction=direction,
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
