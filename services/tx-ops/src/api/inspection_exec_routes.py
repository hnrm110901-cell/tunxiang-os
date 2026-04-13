"""巡检执行 API 路由（真实DB版）

与 inspection_routes.py（巡店质检历史报告）不同，本文件聚焦于 **当日巡检执行流程**。

数据源：
  patrol_records        — 巡检记录（今日概览 + 巡检项）
  patrol_record_items   — 巡检结果明细
  patrol_template_items — 模板检查项（items 列表）
  patrol_issues         — 整改任务（my-tasks）
  stores                — 门店名称
  compliance_alerts     — 严重问题数

端点:
  GET   /api/v1/ops/inspection/today                     今日巡检概览
  GET   /api/v1/ops/inspection/items                     巡检项列表
  PATCH /api/v1/ops/inspection/items/{id}                更新检查结果
  POST  /api/v1/ops/inspection/submit                    提交巡检报告
  GET   /api/v1/ops/rectification/my-tasks               我的整改任务
  PATCH /api/v1/ops/rectification/tasks/{id}/feedback    整改反馈

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(tags=["ops-inspection-exec"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class UpdateInspectionItemRequest(BaseModel):
    result: str = Field(..., description="检查结果: pass/fail/na")
    score: Optional[int] = Field(None, ge=0, le=100, description="评分(0-100)")
    remark: Optional[str] = Field(None, description="备注")
    evidence_urls: Optional[List[str]] = Field(None, description="拍照凭证")
    inspector_id: Optional[str] = Field(None, description="检查人ID")


class SubmitInspectionRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    inspector_id: str = Field(..., description="巡检员ID")
    inspector_name: str = Field(..., description="巡检员姓名")
    overall_score: Optional[int] = Field(None, ge=0, le=100, description="总评分")
    summary: Optional[str] = Field(None, description="巡检总结")
    item_ids: List[str] = Field(..., description="已完成的巡检项ID列表")


class RectificationFeedbackRequest(BaseModel):
    feedback_type: str = Field(..., description="反馈类型: progress/completed/need_help")
    content: str = Field(..., description="反馈内容")
    evidence_urls: Optional[List[str]] = Field(None, description="凭证图片")
    progress_pct: Optional[int] = Field(None, ge=0, le=100, description="完成进度百分比")
    operator_id: str = Field(..., description="操作人ID")
    operator_name: str = Field(..., description="操作人姓名")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _map_record_status(db_status: str) -> str:
    """将 patrol_records.status 映射为前端展示状态。"""
    mapping = {
        "submitted": "completed",
        "reviewed": "completed",
        "in_progress": "in_progress",
        "draft": "pending",
    }
    return mapping.get(db_status, db_status)


def _row_to_item(row: Any) -> Dict[str, Any]:
    """将 patrol_record_items 行转换为巡检项对象。"""
    photo_urls: List[str] = []
    if row.photo_urls:
        try:
            photo_urls = row.photo_urls if isinstance(row.photo_urls, list) else json.loads(row.photo_urls)
        except (ValueError, TypeError):
            photo_urls = []

    result_val: Optional[str] = None
    if row.is_passed is True:
        result_val = "pass"
    elif row.is_passed is False:
        result_val = "fail"

    return {
        "id": str(row.id),
        "category": getattr(row, "category", "general"),
        "category_name": getattr(row, "category_name", row.item_name),
        "name": row.item_name,
        "description": getattr(row, "description", ""),
        "weight": float(row.max_score) if row.max_score else 10,
        "is_critical": getattr(row, "is_required", False),
        "store_id": str(getattr(row, "store_id", "")),
        "result": result_val,
        "score": int(row.actual_score) if row.actual_score is not None else None,
        "remark": row.notes,
        "evidence_urls": photo_urls,
        "sort_order": getattr(row, "sort_order", 0),
    }


def _row_to_issue(row: Any) -> Dict[str, Any]:
    """将 patrol_issues 行转换为整改任务对象。"""
    severity_map = {"critical": "high", "major": "medium", "minor": "low"}
    status_map = {"open": "pending", "in_progress": "in_progress", "resolved": "completed", "closed": "completed"}

    feedbacks: List[Dict[str, Any]] = []
    if hasattr(row, "feedbacks") and row.feedbacks:
        try:
            feedbacks = row.feedbacks if isinstance(row.feedbacks, list) else json.loads(row.feedbacks)
        except (ValueError, TypeError):
            feedbacks = []

    return {
        "id": str(row.id),
        "title": row.item_name,
        "store_id": str(row.store_id),
        "store_name": getattr(row, "store_name", ""),
        "severity": severity_map.get(row.severity, "medium"),
        "status": status_map.get(row.status, "pending"),
        "deadline": str(row.due_date) + "T18:00:00+08:00" if row.due_date else None,
        "source": "巡检发现" if row.record_id else "其他",
        "inspection_item_id": str(row.record_id) if row.record_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "progress_pct": 100 if row.status in ("resolved", "closed") else (50 if row.status == "in_progress" else 0),
        "feedbacks": feedbacks,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/api/v1/ops/inspection/today")
async def get_today_inspection(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """今日巡检概览。"""
    log.info("inspection_today_requested", tenant_id=x_tenant_id)
    today = date.today()

    try:
        await _set_rls(db, x_tenant_id)

        # 今日巡检记录 + 门店名称
        records_result = await db.execute(
            text("""
                SELECT
                    pr.id,
                    pr.store_id,
                    s.store_name,
                    pr.status,
                    pr.total_score,
                    pr.patroller_id
                FROM patrol_records pr
                LEFT JOIN stores s ON s.id = pr.store_id AND s.tenant_id = pr.tenant_id
                WHERE pr.tenant_id = :tid
                  AND pr.patrol_date = :today
                  AND pr.is_deleted = FALSE
                ORDER BY pr.created_at
            """),
            {"tid": x_tenant_id, "today": str(today)},
        )
        records = records_result.fetchall()

        # 今日严重问题数（patrol_issues created today）
        critical_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM patrol_issues
                WHERE tenant_id = :tid
                  AND DATE(created_at) = :today
                  AND severity = 'critical'
                  AND is_deleted = FALSE
            """),
            {"tid": x_tenant_id, "today": str(today)},
        )
        critical_count = critical_result.scalar() or 0

        # 门店总数
        stores_result = await db.execute(
            text("SELECT COUNT(*) FROM stores WHERE tenant_id = :tid AND is_deleted = FALSE"),
            {"tid": x_tenant_id},
        )
        stores_total = stores_result.scalar() or 0

        # 活跃巡检员（今日有记录的不重复 patroller_id）
        active_patrollers = len({str(r.patroller_id) for r in records if r.patroller_id})

        stores_inspected = sum(1 for r in records if r.status in ("submitted", "reviewed"))
        stores_pending = max(0, stores_total - stores_inspected)

        scores = [float(r.total_score) for r in records if r.total_score is not None]
        pass_rate = round(sum(scores) / len(scores), 1) if scores else 0.0

        stores_summary = []
        for r in records:
            api_status = _map_record_status(r.status)
            stores_summary.append({
                "store_id": str(r.store_id),
                "store_name": r.store_name or str(r.store_id),
                "status": api_status,
                "score": float(r.total_score) if r.total_score is not None else None,
                "inspector": str(r.patroller_id) if r.patroller_id else None,
            })

        return {
            "ok": True,
            "data": {
                "date": str(today),
                "stores_total": stores_total,
                "stores_inspected": stores_inspected,
                "stores_pending": stores_pending,
                "overall_pass_rate": pass_rate,
                "critical_issues_found": critical_count,
                "inspectors_active": active_patrollers,
                "stores": stores_summary,
            },
        }
    except SQLAlchemyError as exc:
        log.error("inspection_today_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "date": str(today),
                "stores_total": 0,
                "stores_inspected": 0,
                "stores_pending": 0,
                "overall_pass_rate": 0,
                "critical_issues_found": 0,
                "inspectors_active": 0,
                "stores": [],
            },
        }


@router.get("/api/v1/ops/inspection/items")
async def list_inspection_items(
    store_id: Optional[str] = Query(None, description="门店ID"),
    category: Optional[str] = Query(None, description="类别筛选"),
    result: Optional[str] = Query(None, description="结果筛选: pass/fail/na"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """巡检项列表（取今日最新巡检记录的明细）。"""
    log.info("inspection_items_listed", tenant_id=x_tenant_id, store_id=store_id)
    today = date.today()

    try:
        await _set_rls(db, x_tenant_id)

        # 取今日最新 in_progress 或 draft 记录
        record_q = """
            SELECT pr.id, pr.store_id
            FROM patrol_records pr
            WHERE pr.tenant_id = :tid
              AND pr.patrol_date = :today
              AND pr.is_deleted = FALSE
        """
        params: Dict[str, Any] = {"tid": x_tenant_id, "today": str(today)}

        if store_id:
            record_q += " AND pr.store_id = :store_id::uuid"
            params["store_id"] = store_id

        record_q += " ORDER BY pr.created_at DESC LIMIT 1"
        record_result = await db.execute(text(record_q), params)
        record_row = record_result.fetchone()

        if not record_row:
            return {
                "ok": True,
                "data": {
                    "items": [],
                    "by_category": {},
                    "total": 0,
                    "checked": 0,
                    "passed": 0,
                    "failed": 0,
                    "progress_pct": 0,
                },
            }

        # 取该记录的检查项明细
        items_q = """
            SELECT
                pri.id,
                pri.item_name,
                pri.actual_score,
                pri.max_score,
                pri.is_passed,
                pri.photo_urls,
                pri.notes,
                pti.sort_order,
                pti.is_required,
                pr.store_id
            FROM patrol_record_items pri
            LEFT JOIN patrol_template_items pti ON pti.id = pri.template_item_id
            LEFT JOIN patrol_records pr ON pr.id = pri.record_id
            WHERE pri.record_id = :record_id
              AND pri.is_deleted = FALSE
            ORDER BY pti.sort_order ASC NULLS LAST, pri.created_at ASC
        """
        items_result = await db.execute(text(items_q), {"record_id": str(record_row.id)})
        rows = items_result.fetchall()

        items = [_row_to_item(r) for r in rows]

        # Apply result filter if given
        if result:
            items = [i for i in items if i["result"] == result]
        if category:
            items = [i for i in items if i["category"] == category]

        # 按 category_name 分组
        categories: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            cat = item["category_name"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)

        total = len(items)
        checked = sum(1 for i in items if i["result"] is not None)
        passed = sum(1 for i in items if i["result"] == "pass")

        return {
            "ok": True,
            "data": {
                "items": items,
                "by_category": categories,
                "total": total,
                "checked": checked,
                "passed": passed,
                "failed": sum(1 for i in items if i["result"] == "fail"),
                "progress_pct": round(checked / total * 100, 1) if total > 0 else 0,
            },
        }
    except SQLAlchemyError as exc:
        log.error("inspection_items_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "items": [],
                "by_category": {},
                "total": 0,
                "checked": 0,
                "passed": 0,
                "failed": 0,
                "progress_pct": 0,
            },
        }


@router.patch("/api/v1/ops/inspection/items/{item_id}")
async def update_inspection_item(
    item_id: str,
    body: UpdateInspectionItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新单个巡检项检查结果。"""
    if body.result not in {"pass", "fail", "na"}:
        raise HTTPException(status_code=400, detail="result 必须是 pass/fail/na 之一")

    log.info("inspection_item_updated", item_id=item_id, result=body.result, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        # Verify item exists (RLS ensures tenant scope)
        check_result = await db.execute(
            text("SELECT id FROM patrol_record_items WHERE id = :iid AND is_deleted = FALSE"),
            {"iid": item_id},
        )
        if not check_result.fetchone():
            raise HTTPException(status_code=404, detail="巡检项不存在")

        is_passed: Optional[bool] = None
        if body.result == "pass":
            is_passed = True
        elif body.result == "fail":
            is_passed = False

        photo_urls_json = json.dumps(body.evidence_urls) if body.evidence_urls else None

        update_q = """
            UPDATE patrol_record_items
            SET is_passed    = :is_passed,
                actual_score = :score,
                notes        = :remark,
                photo_urls   = COALESCE(:photos::jsonb, photo_urls),
                updated_at   = NOW()
            WHERE id = :iid
            RETURNING id, item_name, actual_score, max_score, is_passed, photo_urls, notes
        """
        result_row = await db.execute(
            text(update_q),
            {
                "is_passed": is_passed,
                "score": body.score,
                "remark": body.remark,
                "photos": photo_urls_json,
                "iid": item_id,
            },
        )
        await db.commit()
        updated_row = result_row.fetchone()
        if not updated_row:
            raise HTTPException(status_code=404, detail="巡检项不存在")

        return {"ok": True, "data": _row_to_item(updated_row)}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("inspection_item_update_db_error", error=str(exc), item_id=item_id)
        raise HTTPException(status_code=500, detail="数据库错误，请重试")


@router.post("/api/v1/ops/inspection/submit")
async def submit_inspection(
    body: SubmitInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """提交巡检报告——将 patrol_records 状态更新为 submitted。"""
    log.info("inspection_submitted", store_id=body.store_id,
             inspector_id=body.inspector_id, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        today = date.today()
        # 找到该门店今日的草稿记录
        record_result = await db.execute(
            text("""
                SELECT id FROM patrol_records
                WHERE tenant_id = :tid
                  AND store_id = :store_id::uuid
                  AND patrol_date = :today
                  AND status IN ('draft', 'in_progress')
                  AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tid": x_tenant_id, "store_id": body.store_id, "today": str(today)},
        )
        record_row = record_result.fetchone()

        if record_row:
            # 更新为 submitted 并写入总分
            await db.execute(
                text("""
                    UPDATE patrol_records
                    SET status = 'submitted',
                        total_score = :score,
                        patroller_id = :patroller_id::uuid,
                        updated_at = NOW()
                    WHERE id = :rid
                """),
                {
                    "score": body.overall_score,
                    "patroller_id": body.inspector_id,
                    "rid": str(record_row.id),
                },
            )
            await db.commit()
            report_id = str(record_row.id)
        else:
            # 无草稿则创建一条 submitted 记录
            new_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO patrol_records
                        (id, tenant_id, store_id, patrol_date, patroller_id, status, total_score)
                    VALUES
                        (:id, :tid, :store_id::uuid, :today, :patroller_id::uuid, 'submitted', :score)
                """),
                {
                    "id": new_id,
                    "tid": x_tenant_id,
                    "store_id": body.store_id,
                    "today": str(today),
                    "patroller_id": body.inspector_id,
                    "score": body.overall_score,
                },
            )
            await db.commit()
            report_id = new_id

        # 统计因此产生的整改任务数
        tasks_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM patrol_issues
                WHERE record_id = :rid AND is_deleted = FALSE
            """),
            {"rid": report_id},
        )
        tasks_count = tasks_result.scalar() or 0

        return {
            "ok": True,
            "data": {
                "report_id": report_id,
                "store_id": body.store_id,
                "inspector_id": body.inspector_id,
                "inspector_name": body.inspector_name,
                "overall_score": body.overall_score,
                "items_checked": len(body.item_ids),
                "summary": body.summary or "巡检报告已提交",
                "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
                "rectification_tasks_created": tasks_count,
            },
        }
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("inspection_submit_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="提交失败，数据库错误")


@router.get("/api/v1/ops/rectification/my-tasks")
async def get_my_rectification_tasks(
    status: Optional[str] = Query(None, description="状态筛选: pending/in_progress/completed"),
    assignee_id: Optional[str] = Query(None, description="责任人ID（不传默认返回全部）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """我的整改任务列表（来自 patrol_issues）。"""
    log.info("my_rectification_tasks_requested", tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        db_status_map = {
            "pending": ("open",),
            "in_progress": ("in_progress",),
            "completed": ("resolved", "closed"),
        }

        issues_q = """
            SELECT
                pi.id,
                pi.item_name,
                pi.store_id,
                s.store_name,
                pi.severity,
                pi.status,
                pi.due_date,
                pi.record_id,
                pi.created_at,
                pi.resolution_notes
            FROM patrol_issues pi
            LEFT JOIN stores s ON s.id = pi.store_id AND s.tenant_id = pi.tenant_id
            WHERE pi.tenant_id = :tid
              AND pi.is_deleted = FALSE
        """
        params: Dict[str, Any] = {"tid": x_tenant_id}

        if assignee_id:
            issues_q += " AND pi.assignee_id = :assignee_id::uuid"
            params["assignee_id"] = assignee_id

        if status and status in db_status_map:
            db_statuses = db_status_map[status]
            placeholders = ", ".join(f":s{i}" for i in range(len(db_statuses)))
            issues_q += f" AND pi.status IN ({placeholders})"
            for i, s in enumerate(db_statuses):
                params[f"s{i}"] = s

        issues_q += " ORDER BY pi.created_at DESC"

        issues_result = await db.execute(text(issues_q), params)
        rows = issues_result.fetchall()

        items = [_row_to_issue(r) for r in rows]

        # Aggregate counts across all tasks (regardless of filter)
        all_result = await db.execute(
            text("""
                SELECT status, COUNT(*) AS cnt
                FROM patrol_issues
                WHERE tenant_id = :tid AND is_deleted = FALSE
                GROUP BY status
            """),
            {"tid": x_tenant_id},
        )
        counts: Dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0}
        for row in all_result.fetchall():
            s = row.status
            if s == "open":
                counts["pending"] += row.cnt
            elif s == "in_progress":
                counts["in_progress"] += row.cnt
            elif s in ("resolved", "closed"):
                counts["completed"] += row.cnt

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": len(items),
                "pending": counts["pending"],
                "in_progress": counts["in_progress"],
                "completed": counts["completed"],
            },
        }
    except SQLAlchemyError as exc:
        log.error("my_rectification_tasks_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "pending": 0,
                "in_progress": 0,
                "completed": 0,
            },
        }


@router.patch("/api/v1/ops/rectification/tasks/{task_id}/feedback")
async def submit_rectification_feedback(
    task_id: str,
    body: RectificationFeedbackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """提交整改反馈（进度更新/完成报告/求助）——写入 patrol_issues.resolution_notes。"""
    if body.feedback_type not in {"progress", "completed", "need_help"}:
        raise HTTPException(status_code=400, detail="feedback_type 必须是 progress/completed/need_help 之一")

    log.info("rectification_feedback_submitted", task_id=task_id,
             feedback_type=body.feedback_type, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        task_result = await db.execute(
            text("""
                SELECT pi.id, pi.status, pi.resolution_notes, pi.store_id,
                       pi.item_name, pi.severity, pi.due_date, pi.record_id,
                       pi.created_at, s.store_name
                FROM patrol_issues pi
                LEFT JOIN stores s ON s.id = pi.store_id AND s.tenant_id = pi.tenant_id
                WHERE pi.id = :tid AND pi.tenant_id = :tenant AND pi.is_deleted = FALSE
            """),
            {"tid": task_id, "tenant": x_tenant_id},
        )
        task_row = task_result.fetchone()
        if not task_row:
            raise HTTPException(status_code=404, detail="整改任务不存在")

        now = datetime.now(tz=timezone.utc).isoformat()

        # 追加反馈记录到 resolution_notes（JSONB list）
        existing_notes: List[Dict[str, Any]] = []
        if task_row.resolution_notes:
            try:
                parsed = json.loads(task_row.resolution_notes) if isinstance(task_row.resolution_notes, str) else task_row.resolution_notes
                if isinstance(parsed, list):
                    existing_notes = parsed
            except (ValueError, TypeError):
                existing_notes = []

        new_entry: Dict[str, Any] = {
            "time": now,
            "type": body.feedback_type,
            "operator": body.operator_name,
            "content": body.content,
            "progress_pct": body.progress_pct,
        }
        if body.evidence_urls:
            new_entry["evidence_urls"] = body.evidence_urls
        existing_notes.append(new_entry)

        new_status = task_row.status
        if body.feedback_type == "completed":
            new_status = "resolved"

        await db.execute(
            text("""
                UPDATE patrol_issues
                SET status           = :status,
                    resolution_notes = :notes,
                    resolved_at      = CASE WHEN :status = 'resolved' THEN NOW() ELSE resolved_at END,
                    updated_at       = NOW()
                WHERE id = :iid
            """),
            {
                "status": new_status,
                "notes": json.dumps(existing_notes, ensure_ascii=False),
                "iid": task_id,
            },
        )
        await db.commit()

        # Return updated task view
        severity_map = {"critical": "high", "major": "medium", "minor": "low"}
        status_map = {"open": "pending", "in_progress": "in_progress", "resolved": "completed", "closed": "completed"}

        return {
            "ok": True,
            "data": {
                "id": str(task_row.id),
                "title": task_row.item_name,
                "store_id": str(task_row.store_id),
                "store_name": task_row.store_name or "",
                "severity": severity_map.get(task_row.severity, "medium"),
                "status": status_map.get(new_status, "pending"),
                "deadline": str(task_row.due_date) + "T18:00:00+08:00" if task_row.due_date else None,
                "source": "巡检发现" if task_row.record_id else "其他",
                "inspection_item_id": str(task_row.record_id) if task_row.record_id else None,
                "created_at": task_row.created_at.isoformat() if task_row.created_at else None,
                "progress_pct": 100 if new_status == "resolved" else (body.progress_pct or 0),
                "feedbacks": existing_notes,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("rectification_feedback_db_error", error=str(exc), task_id=task_id)
        raise HTTPException(status_code=500, detail="数据库错误，请重试")
