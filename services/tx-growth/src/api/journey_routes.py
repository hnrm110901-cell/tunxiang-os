"""Journey Engine API — 旅程触发引擎路由

端点：
  GET    /api/v1/journey/definitions              → 旅程定义列表
  POST   /api/v1/journey/definitions              → 创建旅程定义
  GET    /api/v1/journey/definitions/{id}         → 旅程定义详情
  PUT    /api/v1/journey/definitions/{id}         → 更新旅程定义
  DELETE /api/v1/journey/definitions/{id}         → 软删除旅程定义
  POST   /api/v1/journey/definitions/{id}/activate   → 激活旅程
  POST   /api/v1/journey/definitions/{id}/deactivate → 停用旅程
  POST   /api/v1/journey/definitions/import_template → 导入内置模板
  GET    /api/v1/journey/enrollments              → 客户参与旅程列表
  GET    /api/v1/journey/enrollments/{id}         → enrollment 详情
  GET    /api/v1/journey/enrollments/{id}/steps   → 某 enrollment 的步骤执行历史
  POST   /api/v1/journey/trigger                  → 手动触发测试事件
"""

import uuid
from typing import Any, Optional

import structlog
from engine.journey_engine import JourneyEngine
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from shared.ontology.src.database import async_session_factory

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/journey", tags=["journey"])

_engine = JourneyEngine()


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def err(msg: str) -> dict:
    return {"ok": False, "error": {"message": msg}}


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class TriggerCondition(BaseModel):
    field: str
    operator: str = "eq"
    value: Any


class JourneyStep(BaseModel):
    step_id: str
    action_type: str
    action_config: dict = Field(default_factory=dict)
    wait_hours: int = 0
    next_steps: list[str] = Field(default_factory=list)


class CreateJourneyRequest(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_event: str
    trigger_conditions: list[TriggerCondition] = Field(default_factory=list)
    steps: list[JourneyStep]
    target_segment: Optional[str] = None


class UpdateJourneyRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_conditions: Optional[list[TriggerCondition]] = None
    steps: Optional[list[JourneyStep]] = None
    target_segment: Optional[str] = None


class TriggerEventRequest(BaseModel):
    event_type: str
    customer_id: uuid.UUID
    context: dict = Field(default_factory=dict)


class ImportTemplateRequest(BaseModel):
    template_name: str  # first_visit_welcome / dormant_recall / birthday_vip / post_banquet / high_value_nurture


# ---------------------------------------------------------------------------
# 旅程定义端点
# ---------------------------------------------------------------------------


@router.get("/definitions")
async def list_journey_definitions(
    is_active: Optional[bool] = Query(None),
    trigger_event: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出旅程定义（支持按 is_active / trigger_event 筛选）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    offset = (page - 1) * size

    conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}

    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active

    if trigger_event:
        conditions.append("trigger_event = :trigger_event")
        params["trigger_event"] = trigger_event

    where = " AND ".join(conditions)

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM journey_definitions WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT id, name, description, trigger_event, trigger_conditions,
                       steps, target_segment, is_active, version, created_at, updated_at
                FROM journey_definitions
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = rows_result.fetchall()

    items = [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2],
            "trigger_event": r[3],
            "trigger_conditions": r[4] or [],
            "steps": r[5] or [],
            "target_segment": r[6],
            "is_active": r[7],
            "version": r[8],
            "created_at": r[9].isoformat() if r[9] else None,
            "updated_at": r[10].isoformat() if r[10] else None,
        }
        for r in rows
    ]

    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/definitions")
async def create_journey_definition(
    body: CreateJourneyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """创建旅程定义（初始 is_active=FALSE，需手动激活）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    if not body.steps:
        raise HTTPException(status_code=422, detail="旅程至少需要一个步骤")

    import json

    def_id = uuid.uuid4()
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        await db.execute(
            text("""
                INSERT INTO journey_definitions
                    (id, tenant_id, name, description, trigger_event,
                     trigger_conditions, steps, target_segment, is_active, version)
                VALUES
                    (:id, :tenant_id, :name, :description, :trigger_event,
                     :conditions::jsonb, :steps::jsonb, :segment, FALSE, 1)
            """),
            {
                "id": str(def_id),
                "tenant_id": str(tenant_id),
                "name": body.name,
                "description": body.description,
                "trigger_event": body.trigger_event,
                "conditions": json.dumps(
                    [c.model_dump() for c in body.trigger_conditions],
                    ensure_ascii=False,
                ),
                "steps": json.dumps(
                    [s.model_dump() for s in body.steps],
                    ensure_ascii=False,
                ),
                "segment": body.target_segment,
            },
        )
        await db.commit()

    logger.info("journey_definition_created", def_id=str(def_id), name=body.name)
    return ok({"id": str(def_id), "name": body.name, "is_active": False})


@router.get("/definitions/{def_id}")
async def get_journey_definition(
    def_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取旅程定义详情。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text("""
                SELECT id, name, description, trigger_event, trigger_conditions,
                       steps, target_segment, is_active, version, created_at, updated_at
                FROM journey_definitions
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(def_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="旅程定义不存在")

    return ok(
        {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "trigger_event": row[3],
            "trigger_conditions": row[4] or [],
            "steps": row[5] or [],
            "target_segment": row[6],
            "is_active": row[7],
            "version": row[8],
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }
    )


@router.put("/definitions/{def_id}")
async def update_journey_definition(
    def_id: uuid.UUID,
    body: UpdateJourneyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """更新旅程定义（激活状态下不允许更新步骤，会先自动停用）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    import json

    set_clauses = ["updated_at = NOW()", "version = version + 1"]
    params: dict[str, Any] = {"id": str(def_id), "tenant_id": str(tenant_id)}

    if body.name is not None:
        set_clauses.append("name = :name")
        params["name"] = body.name
    if body.description is not None:
        set_clauses.append("description = :description")
        params["description"] = body.description
    if body.trigger_conditions is not None:
        set_clauses.append("trigger_conditions = :conditions::jsonb")
        params["conditions"] = json.dumps([c.model_dump() for c in body.trigger_conditions], ensure_ascii=False)
    if body.steps is not None:
        set_clauses.append("steps = :steps::jsonb")
        params["steps"] = json.dumps([s.model_dump() for s in body.steps], ensure_ascii=False)
        # 更新步骤时自动停用，防止正在运行的 enrollment 读到旧步骤
        set_clauses.append("is_active = FALSE")
    if body.target_segment is not None:
        set_clauses.append("target_segment = :segment")
        params["segment"] = body.target_segment

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text(f"""
                UPDATE journey_definitions
                SET {", ".join(set_clauses)}
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
                RETURNING id, name, is_active, version
            """),
            params,
        )
        row = result.fetchone()
        if not row:
            await db.rollback()
            raise HTTPException(status_code=404, detail="旅程定义不存在")
        await db.commit()

    return ok({"id": str(row[0]), "name": row[1], "is_active": row[2], "version": row[3]})


@router.delete("/definitions/{def_id}")
async def delete_journey_definition(
    def_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """软删除旅程定义（同时停用）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text("""
                UPDATE journey_definitions
                SET is_deleted = TRUE, is_active = FALSE, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": str(def_id), "tenant_id": str(tenant_id)},
        )
        if not result.fetchone():
            await db.rollback()
            raise HTTPException(status_code=404, detail="旅程定义不存在")
        await db.commit()

    return ok({"id": str(def_id), "deleted": True})


@router.post("/definitions/{def_id}/activate")
async def activate_journey(
    def_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """激活旅程（is_active=TRUE）。激活前校验步骤不为空。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})

        check = await db.execute(
            text("""
                SELECT steps FROM journey_definitions
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
            """),
            {"id": str(def_id), "tenant_id": str(tenant_id)},
        )
        row = check.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="旅程定义不存在")

        steps = row[0] or []
        if not steps:
            raise HTTPException(status_code=422, detail="旅程无步骤，不可激活")

        await db.execute(
            text("""
                UPDATE journey_definitions
                SET is_active = TRUE, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": str(def_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

    logger.info("journey_activated", def_id=str(def_id), tenant_id=str(tenant_id))
    return ok({"id": str(def_id), "is_active": True})


@router.post("/definitions/{def_id}/deactivate")
async def deactivate_journey(
    def_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """停用旅程（is_active=FALSE，已加入的 enrollment 继续运行直到完成）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text("""
                UPDATE journey_definitions
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": str(def_id), "tenant_id": str(tenant_id)},
        )
        if not result.fetchone():
            await db.rollback()
            raise HTTPException(status_code=404, detail="旅程定义不存在")
        await db.commit()

    return ok({"id": str(def_id), "is_active": False})


@router.post("/definitions/import_template")
async def import_journey_template(
    body: ImportTemplateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """导入内置旅程模板（自动创建 journey_definition，is_active=FALSE）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    from templates.journey_templates import TEMPLATES

    template = TEMPLATES.get(body.template_name)
    if not template:
        available = list(TEMPLATES.keys())
        raise HTTPException(
            status_code=404,
            detail=f"模板不存在: {body.template_name}，可用模板: {available}",
        )

    import json

    def_id = uuid.uuid4()
    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        await db.execute(
            text("""
                INSERT INTO journey_definitions
                    (id, tenant_id, name, description, trigger_event,
                     trigger_conditions, steps, target_segment, is_active, version)
                VALUES
                    (:id, :tenant_id, :name, :description, :trigger_event,
                     :conditions::jsonb, :steps::jsonb, :segment, FALSE, 1)
            """),
            {
                "id": str(def_id),
                "tenant_id": str(tenant_id),
                "name": template["name"],
                "description": template.get("description"),
                "trigger_event": template["trigger_event"],
                "conditions": json.dumps(template.get("trigger_conditions", []), ensure_ascii=False),
                "steps": json.dumps(template["steps"], ensure_ascii=False),
                "segment": template.get("target_segment"),
            },
        )
        await db.commit()

    logger.info(
        "journey_template_imported",
        template_name=body.template_name,
        def_id=str(def_id),
        tenant_id=str(tenant_id),
    )
    return ok(
        {
            "id": str(def_id),
            "name": template["name"],
            "template_name": body.template_name,
            "is_active": False,
            "message": "模板已导入，请检查配置后激活",
        }
    )


# ---------------------------------------------------------------------------
# Enrollment 端点
# ---------------------------------------------------------------------------


@router.get("/enrollments")
async def list_enrollments(
    journey_definition_id: Optional[uuid.UUID] = Query(None),
    customer_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """列出 enrollment（支持按旅程/客户/状态筛选）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    offset = (page - 1) * size
    conditions = ["e.tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": size, "offset": offset}

    if journey_definition_id:
        conditions.append("e.journey_definition_id = :jd_id")
        params["jd_id"] = str(journey_definition_id)
    if customer_id:
        conditions.append("e.customer_id = :customer_id")
        params["customer_id"] = str(customer_id)
    if status:
        conditions.append("e.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM journey_enrollments e WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(f"""
                SELECT e.id, e.journey_definition_id, e.customer_id, e.phone,
                       e.current_step_id, e.status, e.enrolled_at, e.completed_at,
                       e.exited_at, e.next_step_at, d.name AS journey_name
                FROM journey_enrollments e
                LEFT JOIN journey_definitions d ON d.id = e.journey_definition_id
                WHERE {where}
                ORDER BY e.enrolled_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = rows_result.fetchall()

    items = [
        {
            "id": str(r[0]),
            "journey_definition_id": str(r[1]),
            "customer_id": str(r[2]),
            "phone": r[3],
            "current_step_id": r[4],
            "status": r[5],
            "enrolled_at": r[6].isoformat() if r[6] else None,
            "completed_at": r[7].isoformat() if r[7] else None,
            "exited_at": r[8].isoformat() if r[8] else None,
            "next_step_at": r[9].isoformat() if r[9] else None,
            "journey_name": r[10],
        }
        for r in rows
    ]

    return ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/enrollments/{enrollment_id}")
async def get_enrollment(
    enrollment_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取 enrollment 详情（含上下文数据）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text("""
                SELECT e.id, e.journey_definition_id, e.customer_id, e.phone,
                       e.current_step_id, e.status, e.enrolled_at, e.completed_at,
                       e.exited_at, e.context_data, e.next_step_at, d.name AS journey_name
                FROM journey_enrollments e
                LEFT JOIN journey_definitions d ON d.id = e.journey_definition_id
                WHERE e.id = :id AND e.tenant_id = :tenant_id
            """),
            {"id": str(enrollment_id), "tenant_id": str(tenant_id)},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="enrollment 不存在")

    return ok(
        {
            "id": str(row[0]),
            "journey_definition_id": str(row[1]),
            "customer_id": str(row[2]),
            "phone": row[3],
            "current_step_id": row[4],
            "status": row[5],
            "enrolled_at": row[6].isoformat() if row[6] else None,
            "completed_at": row[7].isoformat() if row[7] else None,
            "exited_at": row[8].isoformat() if row[8] else None,
            "context_data": row[9] or {},
            "next_step_at": row[10].isoformat() if row[10] else None,
            "journey_name": row[11],
        }
    )


@router.get("/enrollments/{enrollment_id}/steps")
async def get_enrollment_steps(
    enrollment_id: uuid.UUID,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取 enrollment 的步骤执行历史（可审计）。"""
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        result = await db.execute(
            text("""
                SELECT id, step_id, action_type, action_config, status,
                       scheduled_at, executed_at, result, error_message, created_at
                FROM journey_step_executions
                WHERE enrollment_id = :enrollment_id AND tenant_id = :tenant_id
                ORDER BY scheduled_at ASC
            """),
            {"enrollment_id": str(enrollment_id), "tenant_id": str(tenant_id)},
        )
        rows = result.fetchall()

    steps = [
        {
            "id": str(r[0]),
            "step_id": r[1],
            "action_type": r[2],
            "action_config": r[3] or {},
            "status": r[4],
            "scheduled_at": r[5].isoformat() if r[5] else None,
            "executed_at": r[6].isoformat() if r[6] else None,
            "result": r[7],
            "error_message": r[8],
            "created_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]

    return ok({"enrollment_id": str(enrollment_id), "steps": steps, "total": len(steps)})


# ---------------------------------------------------------------------------
# 手动触发测试事件
# ---------------------------------------------------------------------------


@router.post("/trigger")
async def manual_trigger(
    body: TriggerEventRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """
    手动触发测试事件（用于调试旅程配置）。

    不依赖 EventBridge，直接调用 JourneyEngine.handle_event()。
    """
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式错误")

    async with async_session_factory() as db:
        try:
            result = await _engine.handle_event(
                tenant_id=tenant_id,
                event_type=body.event_type,
                customer_id=body.customer_id,
                context=body.context,
                db=db,
            )
            await db.commit()
        except (OSError, RuntimeError, ValueError) as exc:
            await db.rollback()
            logger.error(
                "manual_trigger_error",
                event_type=body.event_type,
                customer_id=str(body.customer_id),
                error=str(exc),
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=f"触发失败: {exc}")

    logger.info(
        "manual_trigger_success",
        event_type=body.event_type,
        customer_id=str(body.customer_id),
        enrollments_created=result.get("enrollments_created", 0),
    )
    return ok(result)
