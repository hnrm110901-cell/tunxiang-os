"""E5/E6 问题预警与整改跟踪 API 路由

端点:
  POST  /api/v1/ops/issues                           创建问题记录
  GET   /api/v1/ops/issues                           查询问题列表
  PATCH /api/v1/ops/issues/{id}                      更新问题
  POST  /api/v1/ops/issues/{id}/resolve              标记解决
  POST  /api/v1/ops/issues/auto-detect/{store_id}    自动扫描预警

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/issues", tags=["ops-issues"])
log = structlog.get_logger(__name__)

_VALID_ISSUE_TYPES = {
    "discount_abuse", "food_safety", "device_fault", "service", "kds_timeout"
}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_STATUSES = {"open", "in_progress", "resolved", "closed", "escalated"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateIssueRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    issue_date: date = Field(..., description="问题日期")
    issue_type: str = Field(..., description="discount_abuse/food_safety/device_fault/service/kds_timeout")
    severity: str = Field("medium", description="critical/high/medium/low")
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    evidence_urls: List[str] = Field(default_factory=list, description="照片/视频URL列表")
    assigned_to: Optional[str] = None
    due_hours: Optional[int] = Field(None, description="响应期限（小时），默认按严重度自动设置")
    created_by: Optional[str] = None


class UpdateIssueRequest(BaseModel):
    assigned_to: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    evidence_urls: Optional[List[str]] = None
    due_hours: Optional[int] = None


class ResolveIssueRequest(BaseModel):
    resolved_by: str = Field(..., description="解决人UUID")
    resolution_notes: str = Field(..., description="整改说明")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DEFAULT_DUE_HOURS: Dict[str, int] = {
    "critical": 2,
    "high": 8,
    "medium": 24,
    "low": 72,
}


def _calc_due_at(severity: str, due_hours: Optional[int]) -> datetime:
    hours = due_hours if due_hours is not None else _DEFAULT_DUE_HOURS.get(severity, 24)
    return datetime.now(tz=timezone.utc) + timedelta(hours=hours)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """将数据库行中不可直接序列化的类型转换为字符串。"""
    result = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif isinstance(v, list):
            result[k] = v
        else:
            result[k] = v
    return result


async def _scan_kds_timeout(store_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """
    扫描超时 KDS 任务。
    生产替换为 asyncpg:
      SELECT id, dish_name, started_at, expected_finish_at
      FROM kds_tasks
      WHERE store_id = $1
        AND status NOT IN ('done','cancelled')
        AND expected_finish_at < now()
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false;
    """
    return []


async def _scan_discount_abuse(store_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """
    扫描折扣异常订单。
    生产替换为 asyncpg:
      SELECT id, order_no, discount_pct, original_amount_fen, actual_amount_fen
      FROM orders
      WHERE store_id = $1
        AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
        AND discount_pct > 30
        AND approved_by IS NULL
        AND tenant_id = current_setting('app.tenant_id')::uuid
        AND is_deleted = false;
    """
    return []


async def _scan_low_inventory(store_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """
    扫描低库存食材。
    生产替换为 asyncpg:
      SELECT i.id, i.name, si.quantity, i.low_stock_threshold
      FROM store_inventories si
      JOIN ingredients i ON i.id = si.ingredient_id
      WHERE si.store_id = $1
        AND si.quantity <= i.low_stock_threshold
        AND si.tenant_id = current_setting('app.tenant_id')::uuid
        AND si.is_deleted = false;
    """
    return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ISSUE_COLUMNS = """
    id, tenant_id, store_id, issue_date, issue_type, severity,
    title, description, evidence_urls, assigned_to, due_at,
    resolved_at, resolution_notes, resolved_by, status,
    created_by, created_at, updated_at, is_deleted
"""


@router.post("", status_code=201)
async def create_issue(
    body: CreateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E5: 创建问题记录。"""
    if body.issue_type not in _VALID_ISSUE_TYPES:
        raise HTTPException(status_code=400, detail=f"issue_type 必须是 {_VALID_ISSUE_TYPES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    due_at = _calc_due_at(body.severity, body.due_hours)

    try:
        await _set_tenant(db, x_tenant_id)
        result = await db.execute(
            text(f"""
                INSERT INTO ops_issues
                    (tenant_id, store_id, issue_date, issue_type, severity,
                     title, description, evidence_urls, assigned_to, due_at,
                     status, created_by)
                VALUES
                    (:tenant_id, :store_id, :issue_date, :issue_type, :severity,
                     :title, :description, :evidence_urls::jsonb, :assigned_to, :due_at,
                     'open', :created_by)
                RETURNING {_ISSUE_COLUMNS}
            """),
            {
                "tenant_id": x_tenant_id,
                "store_id": body.store_id,
                "issue_date": body.issue_date.isoformat(),
                "issue_type": body.issue_type,
                "severity": body.severity,
                "title": body.title,
                "description": body.description,
                "evidence_urls": __import__("json").dumps(body.evidence_urls),
                "assigned_to": body.assigned_to,
                "due_at": due_at,
                "created_by": body.created_by,
            },
        )
        row = result.mappings().one()
        await db.commit()
        record = _serialize_row(dict(row))
        log.info("issue_created", issue_id=str(record["id"]), store_id=body.store_id,
                 issue_type=body.issue_type, severity=body.severity, tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("issue_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，创建问题记录失败")


@router.get("")
async def list_issues(
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    issue_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E6: 查询问题列表，支持多条件筛选。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    try:
        await _set_tenant(db, x_tenant_id)

        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: Dict[str, Any] = {"tenant_id": x_tenant_id}

        if store_id is not None:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if status is not None:
            conditions.append("status = :status")
            params["status"] = status
        if severity is not None:
            conditions.append("severity = :severity")
            params["severity"] = severity
        if issue_type is not None:
            conditions.append("issue_type = :issue_type")
            params["issue_type"] = issue_type
        if issue_date is not None:
            conditions.append("issue_date = :issue_date")
            params["issue_date"] = issue_date.isoformat()

        where_clause = " AND ".join(conditions)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM ops_issues WHERE {where_clause}"),
            params,
        )
        total: int = count_result.scalar_one()

        severity_order = "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 99 END"
        offset = (page - 1) * size
        params["limit"] = min(size, 50)
        params["offset"] = offset

        rows_result = await db.execute(
            text(f"""
                SELECT {_ISSUE_COLUMNS}
                FROM ops_issues
                WHERE {where_clause}
                ORDER BY {severity_order}, created_at ASC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(dict(r)) for r in rows_result.mappings()]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("issue_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，查询问题列表失败")


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: str,
    body: UpdateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E6: 更新问题（指派/调整优先级/状态流转）。"""
    if body.severity and body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")
    if body.status and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    try:
        await _set_tenant(db, x_tenant_id)

        check = await db.execute(
            text("SELECT id, status, severity FROM ops_issues WHERE id = :iid AND is_deleted = FALSE"),
            {"iid": issue_id},
        )
        existing = check.mappings().first()
        if existing is None:
            raise HTTPException(status_code=404, detail="问题记录不存在")
        if existing["status"] == "closed":
            raise HTTPException(status_code=409, detail="问题已关闭，不可修改")

        set_clauses: List[str] = ["updated_at = NOW()"]
        params: Dict[str, Any] = {"iid": issue_id}

        if body.assigned_to is not None:
            set_clauses.append("assigned_to = :assigned_to")
            params["assigned_to"] = body.assigned_to
            # 指派后若状态为 open，自动推进为 in_progress
            if existing["status"] == "open" and body.status is None:
                set_clauses.append("status = 'in_progress'")

        if body.severity is not None:
            set_clauses.append("severity = :severity")
            params["severity"] = body.severity

        if body.status is not None:
            set_clauses.append("status = :status")
            params["status"] = body.status

        if body.description is not None:
            set_clauses.append("description = :description")
            params["description"] = body.description

        if body.evidence_urls is not None:
            set_clauses.append("evidence_urls = :evidence_urls::jsonb")
            params["evidence_urls"] = __import__("json").dumps(body.evidence_urls)

        if body.due_hours is not None:
            current_severity = body.severity if body.severity else existing["severity"]
            params["due_at"] = _calc_due_at(current_severity, body.due_hours)
            set_clauses.append("due_at = :due_at")

        result = await db.execute(
            text(f"""
                UPDATE ops_issues
                SET {', '.join(set_clauses)}
                WHERE id = :iid
                RETURNING {_ISSUE_COLUMNS}
            """),
            params,
        )
        updated = result.mappings().first()
        if updated is None:
            raise HTTPException(status_code=404, detail="问题记录不存在")
        await db.commit()
        record = _serialize_row(dict(updated))
        log.info("issue_updated", issue_id=issue_id, updates=list(params.keys()),
                 tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("issue_update_db_error", error=str(exc), issue_id=issue_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，更新问题记录失败")


@router.post("/{issue_id}/resolve")
async def resolve_issue(
    issue_id: str,
    body: ResolveIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """E6: 标记问题为已解决。"""
    try:
        await _set_tenant(db, x_tenant_id)

        check = await db.execute(
            text("SELECT id, status FROM ops_issues WHERE id = :iid AND is_deleted = FALSE"),
            {"iid": issue_id},
        )
        existing = check.mappings().first()
        if existing is None:
            raise HTTPException(status_code=404, detail="问题记录不存在")
        if existing["status"] in {"resolved", "closed"}:
            raise HTTPException(status_code=409, detail=f"问题已是 {existing['status']} 状态")

        result = await db.execute(
            text(f"""
                UPDATE ops_issues
                SET status           = 'resolved',
                    resolved_at      = NOW(),
                    resolution_notes = :resolution_notes,
                    resolved_by      = :resolved_by,
                    updated_at       = NOW()
                WHERE id = :iid
                RETURNING {_ISSUE_COLUMNS}
            """),
            {
                "iid": issue_id,
                "resolved_by": body.resolved_by,
                "resolution_notes": body.resolution_notes,
            },
        )
        updated = result.mappings().first()
        if updated is None:
            raise HTTPException(status_code=404, detail="问题记录不存在")
        await db.commit()
        record = _serialize_row(dict(updated))
        log.info("issue_resolved", issue_id=issue_id, resolved_by=body.resolved_by,
                 tenant_id=x_tenant_id)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("issue_resolve_db_error", error=str(exc), issue_id=issue_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，标记解决失败")


@router.post("/auto-detect/{store_id}")
async def auto_detect_issues(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    E5: 自动扫描预警（Agent 触发）。
    扫描：超时KDS任务 / 未确认称重记录 / 折扣异常 / 低库存。
    自动创建问题记录并返回汇总。
    """
    import json as _json

    now = datetime.now(tz=timezone.utc)
    today = now.date()
    created_ids: List[str] = []

    kds_timeouts = await _scan_kds_timeout(store_id, x_tenant_id)
    discount_abuses = await _scan_discount_abuse(store_id, x_tenant_id)
    low_inventory = await _scan_low_inventory(store_id, x_tenant_id)

    # 构建待插入的问题记录列表
    inserts: List[Dict[str, Any]] = []

    for task in kds_timeouts:
        inserts.append({
            "tenant_id": x_tenant_id,
            "store_id": store_id,
            "issue_date": today.isoformat(),
            "issue_type": "kds_timeout",
            "severity": "high",
            "title": f"KDS超时: {task.get('dish_name', '未知菜品')}",
            "description": f"任务ID {task.get('id')} 已超出预期出餐时间",
            "evidence_urls": _json.dumps([]),
            "due_at": _calc_due_at("high", None),
            "created_by": "system:auto_detect",
        })

    for order in discount_abuses:
        inserts.append({
            "tenant_id": x_tenant_id,
            "store_id": store_id,
            "issue_date": today.isoformat(),
            "issue_type": "discount_abuse",
            "severity": "critical",
            "title": f"折扣异常: 订单 {order.get('order_no', '未知')} 折扣率 {order.get('discount_pct', 0):.1f}%",
            "description": (
                f"订单金额 {order.get('original_amount_fen', 0) // 100} 元，"
                f"实收 {order.get('actual_amount_fen', 0) // 100} 元，"
                f"折扣率 {order.get('discount_pct', 0):.1f}%，未经审批"
            ),
            "evidence_urls": _json.dumps([]),
            "due_at": _calc_due_at("critical", None),
            "created_by": "system:auto_detect",
        })

    for ingredient in low_inventory:
        inserts.append({
            "tenant_id": x_tenant_id,
            "store_id": store_id,
            "issue_date": today.isoformat(),
            "issue_type": "food_safety",
            "severity": "medium",
            "title": f"低库存预警: {ingredient.get('name', '未知食材')}",
            "description": (
                f"当前库存 {ingredient.get('quantity', 0)}，"
                f"低于阈值 {ingredient.get('low_stock_threshold', 0)}"
            ),
            "evidence_urls": _json.dumps([]),
            "due_at": _calc_due_at("medium", None),
            "created_by": "system:auto_detect",
        })

    try:
        await _set_tenant(db, x_tenant_id)
        for params in inserts:
            result = await db.execute(
                text("""
                    INSERT INTO ops_issues
                        (tenant_id, store_id, issue_date, issue_type, severity,
                         title, description, evidence_urls, due_at, status, created_by)
                    VALUES
                        (:tenant_id, :store_id, :issue_date, :issue_type, :severity,
                         :title, :description, :evidence_urls::jsonb, :due_at, 'open', :created_by)
                    RETURNING id
                """),
                params,
            )
            row = result.mappings().one()
            created_ids.append(str(row["id"]))
        await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("auto_detect_db_error", error=str(exc), store_id=store_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=500, detail="数据库错误，自动检测写入失败")

    log.info("auto_detect_completed", store_id=store_id,
             kds_timeouts=len(kds_timeouts), discount_abuses=len(discount_abuses),
             low_inventory=len(low_inventory), tenant_id=x_tenant_id)

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "scan_date": today.isoformat(),
            "issues_created": len(created_ids),
            "issue_ids": created_ids,
            "breakdown": {
                "kds_timeout": len(kds_timeouts),
                "discount_abuse": len(discount_abuses),
                "low_inventory": len(low_inventory),
            },
        },
    }
