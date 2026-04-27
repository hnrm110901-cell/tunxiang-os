"""食安巡检 API — safety-compliance Skill（DB 化版本）

端点：
  POST /api/v1/ops/safety/inspections/                  → start_inspection      开始巡检
  GET  /api/v1/ops/safety/inspections/                  → list_inspections      巡检列表
  GET  /api/v1/ops/safety/inspections/{id}              → get_inspection        巡检详情
  POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/score → score_item   对单项打分
  POST /api/v1/ops/safety/inspections/{id}/complete     → complete_inspection   完成巡检
  POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/correct → correct_item 提交整改
  GET  /api/v1/ops/safety/reports/monthly               → monthly_report        月度报表
  GET  /api/v1/ops/safety/templates/                    → list_templates        巡检模板列表

complete_inspection 业务逻辑：
  1. 加权平均分 = sum(score * weight) / sum(weight)
  2. 有 is_critical=TRUE 且 result='fail' → is_passed=FALSE（一票否决）
  3. 否则 is_passed = (overall_score >= pass_threshold)
  4. 发射 safety.inspection.completed 或 safety.inspection.failed 事件

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import asyncpg
import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import SafetyInspectionEventType

router = APIRouter(prefix="/api/v1/ops/safety", tags=["safety-inspection"])
log = structlog.get_logger(__name__)

_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/tunxiang",
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部工具
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _get_conn(tenant_id: str) -> asyncpg.Connection:
    """获取已设置 RLS 上下文的数据库连接。"""
    conn = await asyncpg.connect(_DB_URL)
    await conn.execute("SELECT set_config('app.tenant_id', $1, TRUE)", tenant_id)
    return conn


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class StartInspectionReq(BaseModel):
    store_id: str = Field(..., description="门店ID（UUID）")
    inspector_id: str = Field(..., description="巡检员ID（sys_staff UUID）")
    inspection_type: str = Field(
        ...,
        description="daily_open / daily_close / weekly / surprise / government",
    )
    inspection_date: date = Field(default_factory=date.today, description="巡检日期")
    pass_threshold: float = Field(default=80.0, ge=0, le=100, description="合格分数线")
    template_id: Optional[str] = Field(None, description="关联模板ID（可选）")
    notes: Optional[str] = None


class ScoreItemReq(BaseModel):
    score: Optional[float] = Field(None, ge=0, le=100, description="得分（0-100，None=跳过）")
    result: str = Field(..., description="pass / fail / na")
    photo_url: Optional[str] = None
    issue_description: Optional[str] = None
    corrective_action: Optional[str] = None


class CorrectItemReq(BaseModel):
    corrective_action: str = Field(..., description="整改措施描述")
    corrected_at: Optional[datetime] = Field(None, description="整改完成时间，默认当前时间")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/inspections/", status_code=201)
async def start_inspection(
    req: StartInspectionReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """开始一次巡检，状态设为 in_progress，返回 inspection_id。"""
    inspection_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    conn = await _get_conn(x_tenant_id)
    try:
        await conn.execute(
            """
            INSERT INTO biz_food_safety_inspections
                (id, tenant_id, store_id, inspector_id, inspection_type,
                 inspection_date, started_at, status, pass_threshold, notes,
                 created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'in_progress',$8,$9,now(),now())
            """,
            uuid.UUID(inspection_id),
            uuid.UUID(x_tenant_id),
            uuid.UUID(req.store_id),
            uuid.UUID(req.inspector_id),
            req.inspection_type,
            req.inspection_date,
            now,
            req.pass_threshold,
            req.notes,
        )
    finally:
        await conn.close()

    asyncio.create_task(
        emit_event(
            event_type=SafetyInspectionEventType.INSPECTION_STARTED,
            tenant_id=x_tenant_id,
            stream_id=inspection_id,
            payload={
                "inspection_id": inspection_id,
                "store_id": req.store_id,
                "inspector_id": req.inspector_id,
                "inspection_type": req.inspection_type,
                "inspection_date": req.inspection_date.isoformat(),
            },
            store_id=req.store_id,
            source_service="tx-ops",
            metadata={"stat_date": req.inspection_date.isoformat()},
        )
    )

    log.info(
        "safety_inspection_started",
        inspection_id=inspection_id,
        store_id=req.store_id,
        inspection_type=req.inspection_type,
    )

    return {
        "ok": True,
        "data": {
            "inspection_id": inspection_id,
            "store_id": req.store_id,
            "inspection_type": req.inspection_type,
            "inspection_date": req.inspection_date.isoformat(),
            "status": "in_progress",
            "started_at": now.isoformat(),
        },
    }


@router.get("/inspections/")
async def list_inspections(
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    status: Optional[str] = Query(None, description="pending/in_progress/completed/failed"),
    inspection_date_from: Optional[date] = Query(None),
    inspection_date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """巡检列表（支持门店/状态/日期区间过滤，分页）。"""
    conditions: list[str] = ["tenant_id = $1"]
    params: list[Any] = [uuid.UUID(x_tenant_id)]
    idx = 2

    if store_id:
        conditions.append(f"store_id = ${idx}")
        params.append(uuid.UUID(store_id))
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if inspection_date_from:
        conditions.append(f"inspection_date >= ${idx}")
        params.append(inspection_date_from)
        idx += 1
    if inspection_date_to:
        conditions.append(f"inspection_date <= ${idx}")
        params.append(inspection_date_to)
        idx += 1

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    conn = await _get_conn(x_tenant_id)
    try:
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM biz_food_safety_inspections WHERE {where_clause}",
            *params,
        )
        total = total_row["cnt"] if total_row else 0

        rows = await conn.fetch(
            f"""
            SELECT id, store_id, inspector_id, inspection_type, inspection_date,
                   started_at, completed_at, overall_score, status,
                   pass_threshold, is_passed, notes, created_at
            FROM biz_food_safety_inspections
            WHERE {where_clause}
            ORDER BY inspection_date DESC, created_at DESC
            LIMIT {size} OFFSET {offset}
            """,
            *params,
        )
    finally:
        await conn.close()

    items = [
        {
            "inspection_id": str(r["id"]),
            "store_id": str(r["store_id"]),
            "inspector_id": str(r["inspector_id"]),
            "inspection_type": r["inspection_type"],
            "inspection_date": r["inspection_date"].isoformat(),
            "status": r["status"],
            "overall_score": float(r["overall_score"]) if r["overall_score"] is not None else None,
            "is_passed": r["is_passed"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        }
        for r in rows
    ]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """巡检详情（含所有巡检项目明细）。"""
    conn = await _get_conn(x_tenant_id)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, store_id, inspector_id, inspection_type, inspection_date,
                   started_at, completed_at, overall_score, status,
                   pass_threshold, is_passed, notes, created_at, updated_at
            FROM biz_food_safety_inspections
            WHERE tenant_id = $1 AND id = $2
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"巡检记录不存在: {inspection_id}")

        items = await conn.fetch(
            """
            SELECT id, item_code, item_name, category, weight, score,
                   is_critical, result, photo_url, issue_description,
                   corrective_action, corrected_at, created_at
            FROM biz_food_safety_items
            WHERE tenant_id = $1 AND inspection_id = $2
            ORDER BY item_code
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
        )
    finally:
        await conn.close()

    inspection_data = {
        "inspection_id": str(row["id"]),
        "store_id": str(row["store_id"]),
        "inspector_id": str(row["inspector_id"]),
        "inspection_type": row["inspection_type"],
        "inspection_date": row["inspection_date"].isoformat(),
        "status": row["status"],
        "overall_score": float(row["overall_score"]) if row["overall_score"] is not None else None,
        "pass_threshold": float(row["pass_threshold"]),
        "is_passed": row["is_passed"],
        "notes": row["notes"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "items": [
            {
                "item_id": str(i["id"]),
                "item_code": i["item_code"],
                "item_name": i["item_name"],
                "category": i["category"],
                "weight": float(i["weight"]),
                "score": float(i["score"]) if i["score"] is not None else None,
                "is_critical": i["is_critical"],
                "result": i["result"],
                "photo_url": i["photo_url"],
                "issue_description": i["issue_description"],
                "corrective_action": i["corrective_action"],
                "corrected_at": i["corrected_at"].isoformat() if i["corrected_at"] else None,
            }
            for i in items
        ],
    }

    return {"ok": True, "data": inspection_data}


@router.post("/inspections/{inspection_id}/items/{item_id}/score", status_code=200)
async def score_item(
    inspection_id: str,
    item_id: str,
    req: ScoreItemReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """对单个巡检项目打分并记录结果/问题照片/整改措施。"""
    conn = await _get_conn(x_tenant_id)
    try:
        result = await conn.execute(
            """
            UPDATE biz_food_safety_items
            SET score = $1, result = $2, photo_url = $3,
                issue_description = $4, corrective_action = $5
            WHERE tenant_id = $6 AND inspection_id = $7 AND id = $8
            """,
            req.score,
            req.result,
            req.photo_url,
            req.issue_description,
            req.corrective_action,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
            uuid.UUID(item_id),
        )
    finally:
        await conn.close()

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail=f"巡检项目不存在: {item_id}")

    # 检查关键项不合格时发射告警事件
    if req.result == "fail":
        conn2 = await _get_conn(x_tenant_id)
        try:
            item_row = await conn2.fetchrow(
                "SELECT is_critical, item_code, item_name FROM biz_food_safety_items WHERE tenant_id = $1 AND id = $2",
                uuid.UUID(x_tenant_id),
                uuid.UUID(item_id),
            )
        finally:
            await conn2.close()

        if item_row and item_row["is_critical"]:
            asyncio.create_task(
                emit_event(
                    event_type=SafetyInspectionEventType.CRITICAL_ITEM_FAILED,
                    tenant_id=x_tenant_id,
                    stream_id=inspection_id,
                    payload={
                        "inspection_id": inspection_id,
                        "item_id": item_id,
                        "item_code": item_row["item_code"],
                        "item_name": item_row["item_name"],
                        "issue_description": req.issue_description,
                    },
                    source_service="tx-ops",
                    metadata={"requires_immediate_action": True},
                )
            )

    return {
        "ok": True,
        "data": {
            "item_id": item_id,
            "inspection_id": inspection_id,
            "score": req.score,
            "result": req.result,
        },
    }


@router.post("/inspections/{inspection_id}/complete", status_code=200)
async def complete_inspection(
    inspection_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """完成巡检：计算加权平均分，判定是否合格，发射相应事件。

    业务规则：
    1. 加权平均分 = sum(score * weight) / sum(weight)（仅 result != 'na' 且 score IS NOT NULL）
    2. 存在 is_critical=TRUE 且 result='fail' → is_passed=FALSE（一票否决）
    3. 否则 is_passed = (overall_score >= pass_threshold)
    """
    conn = await _get_conn(x_tenant_id)
    try:
        inspection_row = await conn.fetchrow(
            """
            SELECT id, store_id, inspector_id, inspection_type,
                   inspection_date, pass_threshold, status
            FROM biz_food_safety_inspections
            WHERE tenant_id = $1 AND id = $2
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
        )
        if not inspection_row:
            raise HTTPException(status_code=404, detail=f"巡检记录不存在: {inspection_id}")

        if inspection_row["status"] not in ("in_progress", "pending"):
            raise HTTPException(
                status_code=400,
                detail=f"巡检状态为 {inspection_row['status']}，无法完成",
            )

        # 查询所有有效打分项
        items = await conn.fetch(
            """
            SELECT score, weight, is_critical, result
            FROM biz_food_safety_items
            WHERE tenant_id = $1 AND inspection_id = $2
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
        )
    finally:
        await conn.close()

    # 计算加权平均分
    weighted_sum = 0.0
    total_weight = 0.0
    has_critical_fail = False

    for item in items:
        if item["result"] == "fail" and item["is_critical"]:
            has_critical_fail = True
        if item["result"] != "na" and item["score"] is not None:
            w = float(item["weight"])
            weighted_sum += float(item["score"]) * w
            total_weight += w

    overall_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    pass_threshold = float(inspection_row["pass_threshold"])

    if has_critical_fail:
        is_passed = False
    else:
        is_passed = overall_score >= pass_threshold

    final_status = "completed" if is_passed else "failed"
    now = datetime.now(timezone.utc)

    conn2 = await _get_conn(x_tenant_id)
    try:
        await conn2.execute(
            """
            UPDATE biz_food_safety_inspections
            SET overall_score = $1, is_passed = $2, status = $3,
                completed_at = $4, updated_at = now()
            WHERE tenant_id = $5 AND id = $6
            """,
            overall_score,
            is_passed,
            final_status,
            now,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
        )
    finally:
        await conn2.close()

    event_type = (
        SafetyInspectionEventType.INSPECTION_COMPLETED if is_passed else SafetyInspectionEventType.INSPECTION_FAILED
    )
    asyncio.create_task(
        emit_event(
            event_type=event_type,
            tenant_id=x_tenant_id,
            stream_id=inspection_id,
            payload={
                "inspection_id": inspection_id,
                "store_id": str(inspection_row["store_id"]),
                "inspector_id": str(inspection_row["inspector_id"]),
                "inspection_type": inspection_row["inspection_type"],
                "inspection_date": inspection_row["inspection_date"].isoformat(),
                "overall_score": round(overall_score, 2),
                "pass_threshold": pass_threshold,
                "is_passed": is_passed,
                "has_critical_fail": has_critical_fail,
            },
            store_id=str(inspection_row["store_id"]),
            source_service="tx-ops",
            metadata={"stat_date": inspection_row["inspection_date"].isoformat()},
        )
    )

    log.info(
        "safety_inspection_completed",
        inspection_id=inspection_id,
        overall_score=round(overall_score, 2),
        is_passed=is_passed,
        has_critical_fail=has_critical_fail,
    )

    return {
        "ok": True,
        "data": {
            "inspection_id": inspection_id,
            "overall_score": round(overall_score, 2),
            "pass_threshold": pass_threshold,
            "is_passed": is_passed,
            "has_critical_fail": has_critical_fail,
            "status": final_status,
            "completed_at": now.isoformat(),
        },
    }


@router.post("/inspections/{inspection_id}/items/{item_id}/correct", status_code=200)
async def correct_item(
    inspection_id: str,
    item_id: str,
    req: CorrectItemReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """提交巡检项目整改完成（填写整改措施 + 完成时间）。"""
    corrected_at = req.corrected_at or datetime.now(timezone.utc)

    conn = await _get_conn(x_tenant_id)
    try:
        result = await conn.execute(
            """
            UPDATE biz_food_safety_items
            SET corrective_action = $1, corrected_at = $2
            WHERE tenant_id = $3 AND inspection_id = $4 AND id = $5
            """,
            req.corrective_action,
            corrected_at,
            uuid.UUID(x_tenant_id),
            uuid.UUID(inspection_id),
            uuid.UUID(item_id),
        )
    finally:
        await conn.close()

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail=f"巡检项目不存在: {item_id}")

    log.info(
        "safety_item_corrected",
        item_id=item_id,
        inspection_id=inspection_id,
        corrected_at=corrected_at.isoformat(),
    )

    return {
        "ok": True,
        "data": {
            "item_id": item_id,
            "inspection_id": inspection_id,
            "corrective_action": req.corrective_action,
            "corrected_at": corrected_at.isoformat(),
        },
    }


@router.get("/reports/monthly")
async def monthly_report(
    store_id: str = Query(..., description="门店ID"),
    year: int = Query(..., description="年份，如 2026"),
    month: int = Query(..., ge=1, le=12, description="月份（1-12）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """月度食安报表：汇总本月巡检次数、平均得分、合格率、整改完成率。"""
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    date_from = date(year, month, 1)
    date_to = date(year, month, last_day)

    conn = await _get_conn(x_tenant_id)
    try:
        summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_inspections,
                COUNT(*) FILTER (WHERE is_passed = TRUE) AS passed_count,
                COUNT(*) FILTER (WHERE is_passed = FALSE) AS failed_count,
                AVG(overall_score) AS avg_score,
                COUNT(*) FILTER (WHERE status IN ('completed','failed')) AS completed_count
            FROM biz_food_safety_inspections
            WHERE tenant_id = $1 AND store_id = $2
              AND inspection_date >= $3 AND inspection_date <= $4
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(store_id),
            date_from,
            date_to,
        )

        # 整改完成率：有 result='fail' 的项目中，已有 corrected_at 的比例
        correction_summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_fail_items,
                COUNT(*) FILTER (WHERE corrected_at IS NOT NULL) AS corrected_items
            FROM biz_food_safety_items fi
            JOIN biz_food_safety_inspections ins
              ON fi.inspection_id = ins.id AND fi.tenant_id = ins.tenant_id
            WHERE fi.tenant_id = $1 AND ins.store_id = $2
              AND fi.result = 'fail'
              AND ins.inspection_date >= $3 AND ins.inspection_date <= $4
            """,
            uuid.UUID(x_tenant_id),
            uuid.UUID(store_id),
            date_from,
            date_to,
        )
    finally:
        await conn.close()

    total = summary["total_inspections"] or 0
    passed = summary["passed_count"] or 0
    total_fail_items = correction_summary["total_fail_items"] or 0
    corrected_items = correction_summary["corrected_items"] or 0

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "year": year,
            "month": month,
            "total_inspections": total,
            "passed_count": passed,
            "failed_count": summary["failed_count"] or 0,
            "pass_rate": round(passed / total, 4) if total > 0 else None,
            "avg_score": round(float(summary["avg_score"]), 2) if summary["avg_score"] else None,
            "correction_total_fail_items": total_fail_items,
            "correction_completed_items": corrected_items,
            "correction_rate": (round(corrected_items / total_fail_items, 4) if total_fail_items > 0 else None),
        },
    }


@router.get("/templates/")
async def list_templates(
    brand_id: Optional[str] = Query(None, description="按品牌筛选"),
    inspection_type: Optional[str] = Query(None, description="按巡检类型筛选"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """巡检模板列表（仅返回 is_active=TRUE 的模板）。"""
    conditions = ["tenant_id = $1", "is_active = TRUE"]
    params: list[Any] = [uuid.UUID(x_tenant_id)]
    idx = 2

    if brand_id:
        conditions.append(f"brand_id = ${idx}")
        params.append(uuid.UUID(brand_id))
        idx += 1
    if inspection_type:
        conditions.append(f"inspection_type = ${idx}")
        params.append(inspection_type)
        idx += 1

    where_clause = " AND ".join(conditions)

    conn = await _get_conn(x_tenant_id)
    try:
        rows = await conn.fetch(
            f"""
            SELECT id, brand_id, name, inspection_type, items, created_at
            FROM biz_food_safety_templates
            WHERE {where_clause}
            ORDER BY name
            """,
            *params,
        )
    finally:
        await conn.close()

    import json

    templates = [
        {
            "template_id": str(r["id"]),
            "brand_id": str(r["brand_id"]),
            "name": r["name"],
            "inspection_type": r["inspection_type"],
            "item_count": len(r["items"]) if r["items"] else 0,
            "items": r["items"] if isinstance(r["items"], list) else json.loads(r["items"] or "[]"),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

    return {"ok": True, "data": {"items": templates, "total": len(templates)}}
