"""E8 巡店质检 API 路由

端点:
  POST /api/v1/ops/inspections                    创建巡店报告
  GET  /api/v1/ops/inspections                    查询巡店历史
  GET  /api/v1/ops/inspections/rankings           门店评分排名
  GET  /api/v1/ops/inspections/{id}               报告详情
  POST /api/v1/ops/inspections/{id}/submit        提交报告
  POST /api/v1/ops/inspections/{id}/acknowledge   门店确认收到

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/inspections", tags=["ops-inspections"])
log = structlog.get_logger(__name__)

_VALID_STATUSES = {"draft", "submitted", "acknowledged", "closed"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """将 DB 行中的非 JSON 原生类型序列化为字符串。"""
    result = dict(row)
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return result


def _calc_overall_score(dimensions: List[Dict[str, Any]]) -> Optional[float]:
    if not dimensions:
        return None
    total_score = sum(d.get("score", 0) for d in dimensions)
    total_max = sum(d.get("max_score", 0) for d in dimensions)
    if total_max == 0:
        return None
    return round(total_score / total_max * 100, 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class DimensionScore(BaseModel):
    name: str
    score: float = Field(..., ge=0)
    max_score: float = Field(..., gt=0)
    issues: List[str] = Field(default_factory=list)


class PhotoItem(BaseModel):
    url: str
    caption: str = ""
    issue_id: Optional[str] = None


class ActionItem(BaseModel):
    item: str
    deadline: str = Field(..., description="ISO date string")
    owner: str


class CreateInspectionRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    inspection_date: date = Field(..., description="巡店日期")
    inspector_id: str = Field(..., description="巡店人UUID")
    dimensions: List[DimensionScore] = Field(default_factory=list)
    photos: List[PhotoItem] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)


class SubmitInspectionRequest(BaseModel):
    final_notes: Optional[str] = None


class AcknowledgeInspectionRequest(BaseModel):
    acknowledged_by: str = Field(..., description="门店确认人UUID")
    ack_notes: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  注意：rankings 和 {id} 路由顺序，rankings 必须在 {id} 前
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/rankings")
async def get_inspection_rankings(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="截止日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 门店评分排名（总部全局视角）。按均分降序。"""
    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text("""
                SELECT
                    store_id,
                    AVG(overall_score)   AS avg_score,
                    COUNT(*)             AS inspection_count,
                    MIN(overall_score)   AS min_score,
                    MAX(overall_score)   AS max_score
                FROM inspection_reports
                WHERE inspection_date BETWEEN :start_date AND :end_date
                  AND status IN ('submitted', 'acknowledged', 'closed')
                  AND overall_score IS NOT NULL
                  AND is_deleted = FALSE
                GROUP BY store_id
                ORDER BY avg_score DESC
            """),
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        rows = result.mappings().all()
        rankings = []
        for i, row in enumerate(rows, start=1):
            rankings.append(
                {
                    "rank": i,
                    "store_id": str(row["store_id"]),
                    "avg_score": round(float(row["avg_score"]), 1),
                    "inspection_count": row["inspection_count"],
                    "min_score": round(float(row["min_score"]), 1),
                    "max_score": round(float(row["max_score"]), 1),
                }
            )
        return {
            "ok": True,
            "data": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "store_count": len(rankings),
                "rankings": rankings,
            },
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_rankings_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，获取排名失败")


@router.post("", status_code=201)
async def create_inspection(
    body: CreateInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 创建巡店报告（草稿状态）。"""
    dimensions_data = [d.model_dump() for d in body.dimensions]
    overall_score = _calc_overall_score(dimensions_data)

    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text("""
                INSERT INTO inspection_reports
                    (tenant_id, store_id, inspection_date, inspector_id,
                     overall_score, dimensions, photos, action_items, status)
                VALUES
                    (:tenant_id, :store_id, :inspection_date, :inspector_id,
                     :overall_score, :dimensions::jsonb, :photos::jsonb,
                     :action_items::jsonb, 'draft')
                RETURNING id, tenant_id, store_id, inspection_date, inspector_id,
                          overall_score, dimensions, photos, action_items,
                          notes, ack_notes, status,
                          acknowledged_by, acknowledged_at,
                          created_at, updated_at, is_deleted
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "inspection_date": body.inspection_date.isoformat(),
                "inspector_id": body.inspector_id,
                "overall_score": overall_score,
                "dimensions": json.dumps(dimensions_data),
                "photos": json.dumps([p.model_dump() for p in body.photos]),
                "action_items": json.dumps([a.model_dump() for a in body.action_items]),
            },
        )
        row = result.mappings().one()
        await db.commit()
        record = _serialize_row(row)
        log.info(
            "inspection_created",
            report_id=str(record["id"]),
            store_id=body.store_id,
            inspector_id=body.inspector_id,
            overall_score=overall_score,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，创建巡店报告失败")


@router.get("")
async def list_inspections(
    store_id: Optional[str] = Query(None),
    inspector_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 查询巡店历史列表。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    conditions = ["is_deleted = FALSE"]
    params: Dict[str, Any] = {}

    if store_id:
        conditions.append("store_id = :store_id")
        params["store_id"] = store_id
    if inspector_id:
        conditions.append("inspector_id = :inspector_id")
        params["inspector_id"] = inspector_id
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if start_date:
        conditions.append("inspection_date >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        conditions.append("inspection_date <= :end_date")
        params["end_date"] = end_date.isoformat()

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        await _set_tenant(db, x_tenant_id)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM inspection_reports WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        list_params = {**params, "limit": size, "offset": offset}
        rows_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, inspection_date, inspector_id,
                       overall_score, dimensions, photos, action_items,
                       notes, ack_notes, status,
                       acknowledged_by, acknowledged_at,
                       created_at, updated_at, is_deleted
                FROM inspection_reports
                WHERE {where_clause}
                ORDER BY inspection_date DESC, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            list_params,
        )
        items = [_serialize_row(r) for r in rows_result.mappings().all()]

        return {
            "ok": True,
            "data": {"items": items, "total": total, "page": page, "size": size},
        }
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，查询巡店列表失败")


@router.get("/{report_id}")
async def get_inspection(
    report_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 巡店报告详情。"""
    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, inspection_date, inspector_id,
                       overall_score, dimensions, photos, action_items,
                       notes, ack_notes, status,
                       acknowledged_by, acknowledged_at,
                       created_at, updated_at, is_deleted
                FROM inspection_reports
                WHERE id = :rid AND is_deleted = FALSE
            """),
            {"rid": report_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="巡店报告不存在")
        return {"ok": True, "data": _serialize_row(row)}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_get_db_error", error=str(exc), report_id=report_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，获取报告详情失败")


@router.post("/{report_id}/submit")
async def submit_inspection(
    report_id: str,
    body: SubmitInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 提交巡店报告（草稿→已提交）。提交后门店可见。"""
    try:
        await _set_tenant(db, x_tenant_id)

        check = await db.execute(
            text("SELECT status FROM inspection_reports WHERE id = :rid AND is_deleted = FALSE"),
            {"rid": report_id},
        )
        existing = check.mappings().one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="巡店报告不存在")
        if existing["status"] != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"报告当前状态 {existing['status']}，只有草稿可提交",
            )

        result = await db.execute(
            text("""
                UPDATE inspection_reports
                SET status     = 'submitted',
                    notes      = CASE
                                    WHEN :final_notes IS NOT NULL
                                    THEN TRIM(COALESCE(notes, '') || E'\n' || :final_notes)
                                    ELSE notes
                                 END,
                    updated_at = NOW()
                WHERE id = :rid
                RETURNING id, tenant_id, store_id, inspection_date, inspector_id,
                          overall_score, dimensions, photos, action_items,
                          notes, ack_notes, status,
                          acknowledged_by, acknowledged_at,
                          created_at, updated_at, is_deleted
            """),
            {"rid": report_id, "final_notes": body.final_notes},
        )
        row = result.mappings().one()
        await db.commit()
        record = _serialize_row(row)
        log.info("inspection_submitted", report_id=report_id, store_id=str(record["store_id"]), tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_submit_db_error", error=str(exc), report_id=report_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，提交报告失败")


@router.post("/{report_id}/acknowledge")
async def acknowledge_inspection(
    report_id: str,
    body: AcknowledgeInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E8: 门店确认收到巡店报告。"""
    try:
        await _set_tenant(db, x_tenant_id)

        check = await db.execute(
            text("SELECT status FROM inspection_reports WHERE id = :rid AND is_deleted = FALSE"),
            {"rid": report_id},
        )
        existing = check.mappings().one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="巡店报告不存在")
        if existing["status"] != "submitted":
            raise HTTPException(
                status_code=409,
                detail=f"报告当前状态 {existing['status']}，只有已提交状态可确认",
            )

        result = await db.execute(
            text("""
                UPDATE inspection_reports
                SET status          = 'acknowledged',
                    acknowledged_by = :acknowledged_by,
                    acknowledged_at = NOW(),
                    ack_notes       = CASE
                                         WHEN :ack_notes IS NOT NULL
                                         THEN TRIM(COALESCE(ack_notes, '') || E'\n' || :ack_notes)
                                         ELSE ack_notes
                                      END,
                    updated_at      = NOW()
                WHERE id = :rid
                RETURNING id, tenant_id, store_id, inspection_date, inspector_id,
                          overall_score, dimensions, photos, action_items,
                          notes, ack_notes, status,
                          acknowledged_by, acknowledged_at,
                          created_at, updated_at, is_deleted
            """),
            {
                "rid": report_id,
                "acknowledged_by": body.acknowledged_by,
                "ack_notes": body.ack_notes,
            },
        )
        row = result.mappings().one()
        await db.commit()
        record = _serialize_row(row)
        log.info(
            "inspection_acknowledged", report_id=report_id, acknowledged_by=body.acknowledged_by, tenant_id=x_tenant_id
        )
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("inspection_acknowledge_db_error", error=str(exc), report_id=report_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，确认报告失败")
