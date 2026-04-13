"""客户旅程编排 API 路由

前缀: /api/v1/growth/journeys

端点:
  GET   /                      — 旅程列表
  GET   /{journey_id}          — 旅程详情（含节点）
  POST  /                      — 创建旅程
  PUT   /{journey_id}          — 更新旅程
  PATCH /{journey_id}/status   — 启动/暂停/结束
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/growth/journeys", tags=["journey-designer"])


# ─── 请求模型 ────────────────────────────────────────────────

class JourneyNodeConfig(BaseModel):
    node_id: str = Field(..., description="节点唯一ID")
    type: str = Field(..., description="节点类型: trigger/delay/condition/action")
    name: str = Field(..., description="节点名称")
    config: dict = Field(default_factory=dict, description="节点配置")
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0}, description="画布位置")
    next_nodes: list[str] = Field(default_factory=list, description="后续节点ID列表")


class CreateJourneyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="旅程名称")
    description: Optional[str] = None
    trigger: dict = Field(..., description="触发条件配置")
    target_segment: Optional[str] = Field(None, description="目标人群")
    nodes: list[JourneyNodeConfig] = Field(..., min_length=1, description="旅程节点列表")


class UpdateJourneyRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="旅程名称")
    description: Optional[str] = None
    trigger: Optional[dict] = None
    target_segment: Optional[str] = None
    nodes: Optional[list[JourneyNodeConfig]] = None


class StatusChangeRequest(BaseModel):
    action: str = Field(..., description="操作: start/pause/stop")


# ─── 辅助函数 ────────────────────────────────────────────────

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID must be a valid UUID")


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _row_to_journey(row: Any, *, include_nodes: bool = True) -> dict:
    """Convert a DB row from journey_definitions into the API response shape."""
    # Derive status from is_active + is_deleted
    if row.is_deleted:
        status = "stopped"
    elif row.is_active:
        status = "running"
    else:
        status = "draft"

    # trigger shape: store trigger_event + trigger_conditions together
    trigger = {
        "event": row.trigger_event,
        "conditions": row.trigger_conditions if row.trigger_conditions else [],
    }

    steps = row.steps if row.steps else []

    result: dict[str, Any] = {
        "journey_id": str(row.id),
        "name": row.name,
        "description": row.description,
        "status": status,
        "trigger": trigger,
        "target_segment": row.target_segment,
        "enrolled_count": row.enrolled_count or 0,
        "completed_count": row.completed_count or 0,
        "conversion_rate": (
            round(row.completed_count / row.enrolled_count, 2)
            if (row.enrolled_count and row.enrolled_count > 0)
            else 0.0
        ),
        "node_count": len(steps),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "version": row.version,
    }

    if include_nodes:
        result["nodes"] = steps

    return result


_JOURNEY_SELECT = """
    SELECT
        d.id,
        d.name,
        d.description,
        d.is_active,
        d.is_deleted,
        d.trigger_event,
        d.trigger_conditions,
        d.steps,
        d.target_segment,
        d.version,
        d.created_at,
        d.updated_at,
        COUNT(e.id) FILTER (WHERE e.status IN ('active', 'completed', 'exited', 'failed'))
            AS enrolled_count,
        COUNT(e.id) FILTER (WHERE e.status = 'completed')
            AS completed_count
    FROM journey_definitions d
    LEFT JOIN journey_enrollments e
           ON e.journey_definition_id = d.id
          AND e.tenant_id = d.tenant_id
"""

_JOURNEY_GROUP = """
    GROUP BY d.id, d.name, d.description, d.is_active, d.is_deleted,
             d.trigger_event, d.trigger_conditions, d.steps, d.target_segment,
             d.version, d.created_at, d.updated_at
"""


# ─── 端点 ────────────────────────────────────────────────────

@router.get("/")
async def list_journeys(
    status: Optional[str] = Query(None, description="状态筛选: draft/running/paused/stopped"),
    keyword: Optional[str] = Query(None, description="名称搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """旅程列表"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("list_journeys", tenant_id=str(tenant_id), status=status)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        conditions = ["d.is_deleted = false"]
        params: dict = {"size": size, "offset": (page - 1) * size}

        # Map status filter to DB columns
        if status == "running":
            conditions.append("d.is_active = true")
        elif status in ("draft", "paused"):
            conditions.append("d.is_active = false")
        elif status == "stopped":
            # stopped journeys have is_deleted = true; exclude from default list
            conditions = ["d.is_deleted = true"]

        if keyword:
            conditions.append(
                "(d.name ILIKE :keyword OR d.description ILIKE :keyword)"
            )
            params["keyword"] = f"%{keyword}%"

        where_clause = " AND ".join(conditions)

        rows = (
            await db.execute(
                text(
                    f"""
                    {_JOURNEY_SELECT}
                    WHERE {where_clause}
                    {_JOURNEY_GROUP}
                    ORDER BY d.updated_at DESC
                    LIMIT :size OFFSET :offset
                    """
                ),
                params,
            )
        ).fetchall()

        count_row = (
            await db.execute(
                text(
                    f"SELECT COUNT(*) AS cnt FROM journey_definitions d WHERE {where_clause}"
                ),
                {k: v for k, v in params.items() if k not in ("size", "offset")},
            )
        ).fetchone()

        total = count_row.cnt if count_row else 0
        items = [_row_to_journey(row, include_nodes=False) for row in rows]

        return ok({"items": items, "total": total, "page": page, "size": size})

    except SQLAlchemyError as exc:
        logger.error("list_journeys.db_error", error=str(exc))
        return ok({"items": [], "total": 0, "page": page, "size": size, "_degraded": True})


@router.get("/{journey_id}")
async def get_journey(
    journey_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """旅程详情（含节点定义）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("get_journey", tenant_id=str(tenant_id), journey_id=journey_id)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        row = (
            await db.execute(
                text(
                    f"""
                    {_JOURNEY_SELECT}
                    WHERE d.id = :journey_id::uuid
                    {_JOURNEY_GROUP}
                    """
                ),
                {"journey_id": journey_id},
            )
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

        return ok(_row_to_journey(row, include_nodes=True))

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_journey.db_error", journey_id=journey_id, error=str(exc))
        raise HTTPException(status_code=503, detail="旅程查询暂时不可用，请稍后重试")


@router.post("/")
async def create_journey(
    body: CreateJourneyRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建旅程"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("create_journey", tenant_id=str(tenant_id), name=body.name)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        trigger_event = body.trigger.get("event", "manual")
        trigger_conditions = body.trigger.get("conditions", [])
        nodes_data = [n.model_dump() for n in body.nodes]

        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO journey_definitions (
                        tenant_id, name, description,
                        trigger_event, trigger_conditions, steps,
                        target_segment, is_active
                    ) VALUES (
                        :tenant_id::uuid, :name, :description,
                        :trigger_event, :trigger_conditions::jsonb, :steps::jsonb,
                        :target_segment, false
                    )
                    RETURNING id, name, description, is_active, is_deleted,
                              trigger_event, trigger_conditions, steps, target_segment,
                              version, created_at, updated_at
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "name": body.name,
                    "description": body.description,
                    "trigger_event": trigger_event,
                    "trigger_conditions": json.dumps(trigger_conditions, ensure_ascii=False),
                    "steps": json.dumps(nodes_data, ensure_ascii=False),
                    "target_segment": body.target_segment,
                },
            )
        ).fetchone()

        await db.commit()

        # Synthesise a response row-like object with zero enrollment counts
        class _FakeRow:
            pass

        fake = _FakeRow()
        for col in ("id", "name", "description", "is_active", "is_deleted",
                    "trigger_event", "trigger_conditions", "steps",
                    "target_segment", "version", "created_at", "updated_at"):
            setattr(fake, col, getattr(row, col))
        fake.enrolled_count = 0  # type: ignore[attr-defined]
        fake.completed_count = 0  # type: ignore[attr-defined]

        return ok(_row_to_journey(fake, include_nodes=True))

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_journey.db_error", error=str(exc))
        raise HTTPException(status_code=503, detail="旅程创建暂时不可用，请稍后重试")


@router.put("/{journey_id}")
async def update_journey(
    journey_id: str,
    body: UpdateJourneyRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新旅程（运行中的旅程不允许修改节点）"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info("update_journey", tenant_id=str(tenant_id), journey_id=journey_id)

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        # Fetch current row to validate
        current = (
            await db.execute(
                text(
                    "SELECT id, is_active, is_deleted FROM journey_definitions "
                    "WHERE id = :jid::uuid AND is_deleted = false"
                ),
                {"jid": journey_id},
            )
        ).fetchone()

        if not current:
            raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

        if current.is_active and body.nodes is not None:
            raise HTTPException(
                status_code=422,
                detail="运行中的旅程不允许修改节点，请先暂停",
            )

        # Build SET clause dynamically
        set_parts = ["updated_at = NOW()", "version = version + 1"]
        params: dict = {"jid": journey_id}

        if body.name is not None:
            set_parts.append("name = :name")
            params["name"] = body.name
        if body.description is not None:
            set_parts.append("description = :description")
            params["description"] = body.description
        if body.trigger is not None:
            set_parts.append("trigger_event = :trigger_event")
            set_parts.append("trigger_conditions = :trigger_conditions::jsonb")
            params["trigger_event"] = body.trigger.get("event", "manual")
            params["trigger_conditions"] = json.dumps(
                body.trigger.get("conditions", []), ensure_ascii=False
            )
        if body.target_segment is not None:
            set_parts.append("target_segment = :target_segment")
            params["target_segment"] = body.target_segment
        if body.nodes is not None:
            set_parts.append("steps = :steps::jsonb")
            params["steps"] = json.dumps(
                [n.model_dump() for n in body.nodes], ensure_ascii=False
            )

        row = (
            await db.execute(
                text(
                    f"""
                    UPDATE journey_definitions
                    SET {', '.join(set_parts)}
                    WHERE id = :jid::uuid AND is_deleted = false
                    RETURNING id, name, description, is_active, is_deleted,
                              trigger_event, trigger_conditions, steps, target_segment,
                              version, created_at, updated_at
                    """
                ),
                params,
            )
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

        await db.commit()

        # Fetch enrollment counts separately
        enroll_row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status IN ('active','completed','exited','failed')) AS enrolled_count,
                        COUNT(*) FILTER (WHERE status = 'completed') AS completed_count
                    FROM journey_enrollments
                    WHERE journey_definition_id = :jid::uuid
                    """
                ),
                {"jid": journey_id},
            )
        ).fetchone()

        class _FakeRow:
            pass

        fake = _FakeRow()
        for col in ("id", "name", "description", "is_active", "is_deleted",
                    "trigger_event", "trigger_conditions", "steps",
                    "target_segment", "version", "created_at", "updated_at"):
            setattr(fake, col, getattr(row, col))
        fake.enrolled_count = enroll_row.enrolled_count if enroll_row else 0  # type: ignore[attr-defined]
        fake.completed_count = enroll_row.completed_count if enroll_row else 0  # type: ignore[attr-defined]

        return ok(_row_to_journey(fake, include_nodes=True))

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("update_journey.db_error", journey_id=journey_id, error=str(exc))
        raise HTTPException(status_code=503, detail="旅程更新暂时不可用，请稍后重试")


@router.patch("/{journey_id}/status")
async def change_journey_status(
    journey_id: str,
    body: StatusChangeRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """启动/暂停/结束旅程"""
    tenant_id = _require_tenant(x_tenant_id)
    logger.info(
        "change_journey_status",
        tenant_id=str(tenant_id),
        journey_id=journey_id,
        action=body.action,
    )

    valid_transitions: dict[str, set[str]] = {
        "start": {"draft", "paused"},
        "pause": {"running"},
        "stop": {"running", "paused"},
    }

    if body.action not in valid_transitions:
        raise HTTPException(
            status_code=422,
            detail=f"无效操作: {body.action}，可用操作: start/pause/stop",
        )

    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

        current = (
            await db.execute(
                text(
                    "SELECT id, is_active, is_deleted FROM journey_definitions "
                    "WHERE id = :jid::uuid"
                ),
                {"jid": journey_id},
            )
        ).fetchone()

        if not current:
            raise HTTPException(status_code=404, detail=f"旅程不存在: {journey_id}")

        # Derive current status
        if current.is_deleted:
            current_status = "stopped"
        elif current.is_active:
            current_status = "running"
        else:
            current_status = "draft"

        allowed_from = valid_transitions[body.action]
        if current_status not in allowed_from:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"当前状态 {current_status} 不允许执行 {body.action}，"
                    f"要求状态: {', '.join(sorted(allowed_from))}"
                ),
            )

        # Compute new DB state
        if body.action == "start":
            new_is_active = True
            new_is_deleted = False
            new_status = "running"
        elif body.action == "pause":
            new_is_active = False
            new_is_deleted = False
            new_status = "paused"
        else:  # stop
            new_is_active = False
            new_is_deleted = True
            new_status = "stopped"

        await db.execute(
            text(
                """
                UPDATE journey_definitions
                SET is_active = :is_active,
                    is_deleted = :is_deleted,
                    updated_at = NOW()
                WHERE id = :jid::uuid
                """
            ),
            {
                "jid": journey_id,
                "is_active": new_is_active,
                "is_deleted": new_is_deleted,
            },
        )
        await db.commit()

        return ok(
            {
                "journey_id": journey_id,
                "previous_status": current_status,
                "current_status": new_status,
                "action": body.action,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "change_journey_status.db_error",
            journey_id=journey_id,
            action=body.action,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail="旅程状态变更暂时不可用，请稍后重试")
