"""
PRD-11 sub-C split-attribution 死信看板 BFF

数据源: dlq_split_attribution_failed 表 (v437) — 由 tx-supply
IndexSplitProjector 在 share_split_rule 校验失败 / 非 dedup IntegrityError 时落盘
(参 services/tx-supply/src/projectors/index_split.py _dlq_insert).

GET  /api/v1/dlq/split-attribution?status=unack&limit=&offset=
     列死信 (默认 status=unack 倒序展示)

GET  /api/v1/dlq/split-attribution/{id}
     单死信详情

POST /api/v1/dlq/split-attribution/{id}/acknowledge
     确认 (写 acknowledged_at/by/ack_notes)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/api/v1/dlq/split-attribution",
    tags=["dlq", "split-attribution"],
)


async def _get_db_with_tenant(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _row_to_dict(row) -> dict:
    payload = row.payload
    if isinstance(payload, str):
        import json

        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = {}
    return {
        "id": str(row.id),
        "event_id": str(row.event_id),
        "event_type": row.event_type,
        "order_id": str(row.order_id) if row.order_id else None,
        "order_item_id": str(row.order_item_id) if row.order_item_id else None,
        "dish_id": str(row.dish_id) if row.dish_id else None,
        "error_class": row.error_class,
        "error_msg": row.error_msg,
        "payload": payload if isinstance(payload, dict) else {},
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "acknowledged_at": (
            row.acknowledged_at.isoformat() if row.acknowledged_at else None
        ),
        "acknowledged_by": (
            str(row.acknowledged_by) if row.acknowledged_by else None
        ),
        "ack_notes": row.ack_notes,
    }


@router.get("")
async def list_dlq_split_attribution(
    status: str = Query("unack", description="unack/ack/all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """列死信 — 默认 unack 倒序 (运营 ops 早起看夜间死信场景)."""
    where_clauses = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": x_tenant_id, "limit": limit, "offset": offset}
    if status == "unack":
        where_clauses.append("acknowledged_at IS NULL")
    elif status == "ack":
        where_clauses.append("acknowledged_at IS NOT NULL")
    elif status == "all":
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须是 unack/ack/all, 收到 {status!r}",
        )
    where_sql = " AND ".join(where_clauses)

    try:
        # 主查询用 COUNT(*) OVER () window function 单 SQL 同时取分页 rows + status filter
        # 下的精确总数 — 配合 web-admin sub-C 看板精确分页 (issue #725)
        result = await db.execute(
            text(
                f"""
                SELECT id, event_id, event_type, order_id, order_item_id, dish_id,
                       error_class, error_msg, payload, occurred_at, created_at,
                       acknowledged_at, acknowledged_by, ack_notes,
                       COUNT(*) OVER () AS total
                FROM dlq_split_attribution_failed
                WHERE {where_sql}
                ORDER BY occurred_at DESC
                LIMIT :limit OFFSET :offset
                """  # noqa: S608
            ),
            params,
        )
        rows = result.fetchall()
        items = [_row_to_dict(r) for r in rows]
        # window function 每行同值; rows 空时 (offset 超 total / 无匹配) 用独立 COUNT 兜底
        # 防止前端拿到 total=0 误判 "无数据" (实际是 offset 越界)
        if rows:
            page_total = int(rows[0].total)
        else:
            count_result = await db.execute(
                text(
                    f"""
                    SELECT COUNT(*)::int AS total
                    FROM dlq_split_attribution_failed
                    WHERE {where_sql}
                    """  # noqa: S608
                ),
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            )
            count_row = count_result.fetchone()
            page_total = int(count_row.total) if count_row else 0

        # 同时返回未确认总数 (sub-C 看板顶部红点)
        unack_result = await db.execute(
            text(
                """
                SELECT COUNT(*)::int AS unack_count
                FROM dlq_split_attribution_failed
                WHERE tenant_id = :tenant_id AND acknowledged_at IS NULL
                """
            ),
            {"tenant_id": x_tenant_id},
        )
        unack_row = unack_result.fetchone()
        unack_count = int(unack_row.unack_count) if unack_row else 0
    except SQLAlchemyError as exc:
        logger.warning("dlq_split_list_query_failed", error=str(exc))
        items = []
        page_total = 0
        unack_count = 0

    return {
        "ok": True,
        "data": {
            "items": items,
            "page": {
                "limit": limit,
                "offset": offset,
                "count": len(items),
                "total": page_total,
            },
            "summary": {
                "unack_count": unack_count,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("/{dlq_id}")
async def get_dlq_split_attribution_detail(
    dlq_id: str = Path(..., description="dlq row UUID"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """单死信详情 (含完整 payload + 错误信息)."""
    try:
        result = await db.execute(
            text(
                """
                SELECT id, event_id, event_type, order_id, order_item_id, dish_id,
                       error_class, error_msg, payload, occurred_at, created_at,
                       acknowledged_at, acknowledged_by, ack_notes
                FROM dlq_split_attribution_failed
                WHERE tenant_id = :tenant_id AND id = :dlq_id
                """
            ),
            {"tenant_id": x_tenant_id, "dlq_id": dlq_id},
        )
        row = result.fetchone()
    except SQLAlchemyError as exc:
        logger.warning(
            "dlq_split_detail_query_failed", dlq_id=dlq_id, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="DB 查询失败") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"dlq row {dlq_id} not found")

    return {
        "ok": True,
        "data": _row_to_dict(row),
    }


class AcknowledgeRequest(BaseModel):
    notes: str = Field(default="", description="确认备注")
    acknowledged_by_user_id: Optional[str] = Field(
        default=None, description="确认人 UUID (可选)"
    )


@router.post("/{dlq_id}/acknowledge")
async def acknowledge_dlq_split_attribution(
    req: AcknowledgeRequest,
    dlq_id: str = Path(..., description="dlq row UUID"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db_with_tenant),
) -> dict:
    """确认死信 — 写 acknowledged_at/by/ack_notes."""
    # 校验 acknowledged_by_user_id 是 UUID (None 允许 = 系统自动 ack)
    ack_by_uuid: Optional[UUID] = None
    if req.acknowledged_by_user_id:
        try:
            ack_by_uuid = UUID(req.acknowledged_by_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"acknowledged_by_user_id 非法 UUID: {req.acknowledged_by_user_id}",
            ) from exc

    try:
        result = await db.execute(
            text(
                """
                UPDATE dlq_split_attribution_failed
                SET acknowledged_at = NOW(),
                    acknowledged_by = :ack_by,
                    ack_notes = :notes
                WHERE tenant_id = :tenant_id
                  AND id = :dlq_id
                  AND acknowledged_at IS NULL
                RETURNING id
                """
            ),
            {
                "tenant_id": x_tenant_id,
                "dlq_id": dlq_id,
                "ack_by": ack_by_uuid,
                "notes": req.notes[:4000] if req.notes else "",
            },
        )
        updated_row = result.fetchone()
    except SQLAlchemyError as exc:
        logger.warning(
            "dlq_split_acknowledge_failed", dlq_id=dlq_id, error=str(exc)
        )
        raise HTTPException(status_code=500, detail="DB 更新失败") from exc

    if updated_row is None:
        # 兼容场景: 已经被 ack / 不存在 / 跨租户. 用 404 让前端区分 "已 ack" 与 "成功"
        raise HTTPException(
            status_code=404,
            detail=f"dlq row {dlq_id} 不存在或已 ack",
        )

    return {
        "ok": True,
        "data": {
            "id": str(updated_row.id),
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        },
    }
