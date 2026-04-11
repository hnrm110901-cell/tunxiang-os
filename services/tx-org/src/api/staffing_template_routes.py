"""Staffing Template CRUD — Human Hub / store_staffing_templates

端点列表：
  GET    /api/v1/staffing-templates              编制模板列表（分页+筛选）
  POST   /api/v1/staffing-templates              创建编制模板
  GET    /api/v1/staffing-templates/summary       编制模板汇总（按店型分组）
  POST   /api/v1/staffing-templates/batch         批量创建/更新（UPSERT）
  POST   /api/v1/staffing-templates/copy          复制模板到其他店型
  GET    /api/v1/staffing-templates/{template_id} 模板详情
  PUT    /api/v1/staffing-templates/{template_id} 更新模板
  DELETE /api/v1/staffing-templates/{template_id} 软删除
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, Optional, List
from uuid import uuid4
from datetime import datetime, timezone
import structlog

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(tags=["staffing-templates"])


# ── helpers ──────────────────────────────────────────────────────────
def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


def _row_to_dict(r) -> dict:
    """Convert a row mapping to a serialisable dict."""
    d = dict(r)
    if d.get("created_at") is not None:
        d["created_at"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
    if d.get("updated_at") is not None:
        d["updated_at"] = d["updated_at"].isoformat() if hasattr(d["updated_at"], "isoformat") else str(d["updated_at"])
    return d


# ── column list (reused across queries) ──────────────────────────────
_SELECT_COLS = """
    id::text AS template_id, tenant_id, store_type, position, shift,
    day_type, min_count, recommended_count, peak_buffer,
    min_skill_level, notes, is_active, is_deleted,
    created_at, updated_at
"""


# ── request models ───────────────────────────────────────────────────
class CreateStaffingTemplateReq(BaseModel):
    store_type: str = Field(..., min_length=1, max_length=50)
    position: str = Field(..., min_length=1, max_length=100)
    shift: str = Field(..., min_length=1, max_length=50)
    day_type: Optional[str] = Field(None, max_length=50)
    min_count: Optional[int] = Field(None, ge=0)
    recommended_count: Optional[int] = Field(None, ge=0)
    peak_buffer: Optional[int] = Field(None, ge=0)
    min_skill_level: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    is_active: Optional[bool] = True


class UpdateStaffingTemplateReq(BaseModel):
    store_type: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=100)
    shift: Optional[str] = Field(None, max_length=50)
    day_type: Optional[str] = Field(None, max_length=50)
    min_count: Optional[int] = Field(None, ge=0)
    recommended_count: Optional[int] = Field(None, ge=0)
    peak_buffer: Optional[int] = Field(None, ge=0)
    min_skill_level: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CopyTemplateReq(BaseModel):
    source_store_type: str = Field(..., min_length=1, max_length=50)
    target_store_type: str = Field(..., min_length=1, max_length=50)


# ── GET /summary (must be before /{template_id} to avoid route clash)
@router.get("/api/v1/staffing-templates/summary")
async def staffing_template_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """编制模板汇总 — 按店型分组统计，用于 dashboard 展示。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text("""
        SELECT
            store_type,
            COUNT(*)::int                          AS total_positions,
            COALESCE(SUM(min_count), 0)::int       AS total_min_count,
            COALESCE(SUM(recommended_count), 0)::int AS total_recommended_count
        FROM store_staffing_templates
        WHERE tenant_id = :tid AND is_deleted = FALSE AND is_active = TRUE
        GROUP BY store_type
        ORDER BY store_type
    """)
    rows = (await db.execute(sql, {"tid": tenant_id})).mappings().all()

    by_store_type = [
        {
            "store_type": r["store_type"],
            "total_positions": r["total_positions"],
            "total_min_count": r["total_min_count"],
            "total_recommended_count": r["total_recommended_count"],
        }
        for r in rows
    ]

    return _ok({
        "by_store_type": by_store_type,
        "total_positions": sum(r["total_positions"] for r in by_store_type),
        "total_min_count": sum(r["total_min_count"] for r in by_store_type),
        "total_recommended_count": sum(r["total_recommended_count"] for r in by_store_type),
    })


# ── POST /batch (before /{template_id} to avoid route clash) ────────
@router.post("/api/v1/staffing-templates/batch", status_code=201)
async def batch_upsert_staffing_templates(
    body: List[CreateStaffingTemplateReq],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """批量创建/更新编制模板 — INSERT ... ON CONFLICT DO UPDATE。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if not body:
        raise HTTPException(status_code=400, detail="Empty template list")

    now = datetime.now(timezone.utc)
    created = 0
    updated = 0

    sql = text("""
        INSERT INTO store_staffing_templates
            (id, tenant_id, store_type, position, shift, day_type,
             min_count, recommended_count, peak_buffer, min_skill_level,
             notes, is_active, is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :store_type, :position, :shift, :day_type,
             :min_count, :recommended_count, :peak_buffer, :min_skill_level,
             :notes, :is_active, FALSE, :now, :now)
        ON CONFLICT ON CONSTRAINT uq_staffing_tpl_composite
        DO UPDATE SET
             min_count          = EXCLUDED.min_count,
             recommended_count  = EXCLUDED.recommended_count,
             peak_buffer        = EXCLUDED.peak_buffer,
             min_skill_level    = EXCLUDED.min_skill_level,
             notes              = EXCLUDED.notes,
             is_active          = EXCLUDED.is_active,
             is_deleted         = FALSE,
             updated_at         = EXCLUDED.updated_at
        RETURNING (xmax = 0) AS is_insert
    """)

    for item in body:
        new_id = str(uuid4())
        result = (await db.execute(sql, {
            "id": new_id, "tid": tenant_id,
            "store_type": item.store_type, "position": item.position,
            "shift": item.shift, "day_type": item.day_type,
            "min_count": item.min_count, "recommended_count": item.recommended_count,
            "peak_buffer": item.peak_buffer, "min_skill_level": item.min_skill_level,
            "notes": item.notes, "is_active": item.is_active, "now": now,
        })).mappings().first()

        if result and result["is_insert"]:
            created += 1
        else:
            updated += 1

    await db.commit()

    log.info("staffing_template.batch_upsert", created=created, updated=updated,
             total=len(body), tenant_id=tenant_id)

    return _ok({"created": created, "updated": updated, "total": len(body)})


# ── POST /copy (before /{template_id} to avoid route clash) ─────────
@router.post("/api/v1/staffing-templates/copy", status_code=201)
async def copy_staffing_templates(
    body: CopyTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """复制模板到其他店型 — 将 source_store_type 的所有活跃模板复制到 target_store_type。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    if body.source_store_type == body.target_store_type:
        raise HTTPException(status_code=400, detail="source and target store_type must differ")

    now = datetime.now(timezone.utc)

    # Fetch active templates from source
    fetch_sql = text(f"""
        SELECT {_SELECT_COLS}
        FROM store_staffing_templates
        WHERE tenant_id = :tid
          AND store_type = :source_type
          AND is_active = TRUE
          AND is_deleted = FALSE
    """)
    rows = (await db.execute(fetch_sql, {
        "tid": tenant_id, "source_type": body.source_store_type,
    })).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No active templates found for source store_type")

    insert_sql = text("""
        INSERT INTO store_staffing_templates
            (id, tenant_id, store_type, position, shift, day_type,
             min_count, recommended_count, peak_buffer, min_skill_level,
             notes, is_active, is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :store_type, :position, :shift, :day_type,
             :min_count, :recommended_count, :peak_buffer, :min_skill_level,
             :notes, :is_active, FALSE, :now, :now)
        ON CONFLICT ON CONSTRAINT uq_staffing_tpl_composite DO NOTHING
    """)

    copied = 0
    for r in rows:
        new_id = str(uuid4())
        result = await db.execute(insert_sql, {
            "id": new_id, "tid": tenant_id,
            "store_type": body.target_store_type,
            "position": r["position"], "shift": r["shift"],
            "day_type": r["day_type"],
            "min_count": r["min_count"], "recommended_count": r["recommended_count"],
            "peak_buffer": r["peak_buffer"], "min_skill_level": r["min_skill_level"],
            "notes": r["notes"], "is_active": r["is_active"], "now": now,
        })
        if result.rowcount > 0:
            copied += 1

    await db.commit()

    log.info("staffing_template.copied", source=body.source_store_type,
             target=body.target_store_type, copied=copied, tenant_id=tenant_id)

    return _ok({
        "source_store_type": body.source_store_type,
        "target_store_type": body.target_store_type,
        "copied": copied,
    })


# ── GET / list ───────────────────────────────────────────────────────
@router.get("/api/v1/staffing-templates")
async def list_staffing_templates(
    request: Request,
    store_type: Optional[str] = Query(None),
    position: Optional[str] = Query(None),
    day_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(True),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """编制模板列表 — 分页 + 多条件筛选。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid", "is_deleted = FALSE"]
    params: dict[str, Any] = {"tid": tenant_id}

    if store_type is not None:
        conditions.append("store_type = :store_type")
        params["store_type"] = store_type
    if position is not None:
        conditions.append("position = :position")
        params["position"] = position
    if day_type is not None:
        conditions.append("day_type = :day_type")
        params["day_type"] = day_type
    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active

    where = " AND ".join(conditions)

    count_sql = text(f"SELECT COUNT(*) FROM store_staffing_templates WHERE {where}")
    total = (await db.execute(count_sql, params)).scalar() or 0

    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    data_sql = text(f"""
        SELECT {_SELECT_COLS}
        FROM store_staffing_templates
        WHERE {where}
        ORDER BY store_type, position, shift
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(data_sql, params)).mappings().all()

    items = [_row_to_dict(r) for r in rows]

    return _ok({"items": items, "total": total, "page": page, "size": size})


# ── POST / create ────────────────────────────────────────────────────
@router.post("/api/v1/staffing-templates", status_code=201)
async def create_staffing_template(
    body: CreateStaffingTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建编制模板 — 检查唯一约束（tenant_id + store_type + position + shift + day_type）。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # Check uniqueness
    dup_sql = text("""
        SELECT id FROM store_staffing_templates
        WHERE tenant_id = :tid
          AND store_type = :store_type
          AND position = :position
          AND shift = :shift
          AND COALESCE(day_type, '') = COALESCE(:day_type, '')
          AND is_deleted = FALSE
    """)
    dup = (await db.execute(dup_sql, {
        "tid": tenant_id, "store_type": body.store_type,
        "position": body.position, "shift": body.shift,
        "day_type": body.day_type,
    })).first()
    if dup:
        raise HTTPException(
            status_code=409,
            detail="Duplicate template: same store_type + position + shift + day_type already exists",
        )

    new_id = str(uuid4())
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO store_staffing_templates
            (id, tenant_id, store_type, position, shift, day_type,
             min_count, recommended_count, peak_buffer, min_skill_level,
             notes, is_active, is_deleted, created_at, updated_at)
        VALUES
            (:id, :tid, :store_type, :position, :shift, :day_type,
             :min_count, :recommended_count, :peak_buffer, :min_skill_level,
             :notes, :is_active, FALSE, :now, :now)
        RETURNING id::text AS template_id
    """)
    result = (await db.execute(sql, {
        "id": new_id, "tid": tenant_id,
        "store_type": body.store_type, "position": body.position,
        "shift": body.shift, "day_type": body.day_type,
        "min_count": body.min_count, "recommended_count": body.recommended_count,
        "peak_buffer": body.peak_buffer, "min_skill_level": body.min_skill_level,
        "notes": body.notes, "is_active": body.is_active, "now": now,
    })).mappings().first()

    await db.commit()

    log.info("staffing_template.created", template_id=new_id, tenant_id=tenant_id,
             store_type=body.store_type, position=body.position)

    return _ok({"template_id": str(result["template_id"])})


# ── GET /{template_id} ──────────────────────────────────────────────
@router.get("/api/v1/staffing-templates/{template_id}")
async def get_staffing_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """模板详情 — 返回单条记录或 404。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    sql = text(f"""
        SELECT {_SELECT_COLS}
        FROM store_staffing_templates
        WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
    """)
    row = (await db.execute(sql, {"id": template_id, "tid": tenant_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Staffing template not found")

    return _ok(_row_to_dict(row))


# ── PUT /{template_id} ──────────────────────────────────────────────
@router.put("/api/v1/staffing-templates/{template_id}")
async def update_staffing_template(
    template_id: str,
    body: UpdateStaffingTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新模板 — 动态 SET 子句，仅更新传入字段。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    now = datetime.now(timezone.utc)
    fields["updated_at"] = now

    set_clauses = [f"{k} = :{k}" for k in fields]
    set_sql = ", ".join(set_clauses)

    sql = text(f"""
        UPDATE store_staffing_templates
        SET {set_sql}
        WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text AS template_id
    """)
    params = {**fields, "id": template_id, "tid": tenant_id}
    result = (await db.execute(sql, params)).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Staffing template not found")

    await db.commit()

    log.info("staffing_template.updated", template_id=template_id, tenant_id=tenant_id,
             updated_fields=list(fields.keys()))

    return _ok({"template_id": template_id})


# ── DELETE /{template_id} (soft) ────────────────────────────────────
@router.delete("/api/v1/staffing-templates/{template_id}")
async def delete_staffing_template(
    template_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """软删除 — 设置 is_deleted = TRUE, is_active = FALSE。"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    now = datetime.now(timezone.utc)
    sql = text("""
        UPDATE store_staffing_templates
        SET is_deleted = TRUE, is_active = FALSE, updated_at = :now
        WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
        RETURNING id::text AS template_id
    """)
    result = (await db.execute(sql, {"id": template_id, "tid": tenant_id, "now": now})).mappings().first()

    if not result:
        raise HTTPException(status_code=404, detail="Staffing template not found")

    await db.commit()

    log.info("staffing_template.deleted", template_id=template_id, tenant_id=tenant_id)

    return _ok({"template_id": template_id})
