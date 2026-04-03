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

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/issues", tags=["ops-issues"])
log = structlog.get_logger(__name__)

_VALID_ISSUE_TYPES = {
    "discount_abuse", "food_safety", "device_fault", "service", "kds_timeout"
}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_STATUSES = {"open", "in_progress", "resolved", "closed", "escalated"}

# ─── 内存存储────────────────────────────────────────────────────────────────
_issues: Dict[str, Dict[str, Any]] = {}


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


def _calc_due_at(severity: str, due_hours: Optional[int]) -> str:
    hours = due_hours if due_hours is not None else _DEFAULT_DUE_HOURS.get(severity, 24)
    return (datetime.now(tz=timezone.utc) + timedelta(hours=hours)).isoformat()


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


@router.post("", status_code=201)
async def create_issue(
    body: CreateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E5: 创建问题记录。"""
    if body.issue_type not in _VALID_ISSUE_TYPES:
        raise HTTPException(status_code=400, detail=f"issue_type 必须是 {_VALID_ISSUE_TYPES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    issue_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    record: Dict[str, Any] = {
        "id": issue_id,
        "tenant_id": x_tenant_id,
        "store_id": body.store_id,
        "issue_date": body.issue_date.isoformat(),
        "issue_type": body.issue_type,
        "severity": body.severity,
        "title": body.title,
        "description": body.description,
        "evidence_urls": body.evidence_urls,
        "assigned_to": body.assigned_to,
        "due_at": _calc_due_at(body.severity, body.due_hours),
        "resolved_at": None,
        "resolution_notes": None,
        "status": "open",
        "created_by": body.created_by,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "is_deleted": False,
    }
    _issues[issue_id] = record

    log.info("issue_created", issue_id=issue_id, store_id=body.store_id,
             issue_type=body.issue_type, severity=body.severity, tenant_id=x_tenant_id)
    return {"ok": True, "data": record}


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
) -> Dict[str, Any]:
    """E6: 查询问题列表，支持多条件筛选。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    items = [
        s for s in _issues.values()
        if s["tenant_id"] == x_tenant_id
        and not s.get("is_deleted", False)
        and (store_id is None or s["store_id"] == store_id)
        and (status is None or s["status"] == status)
        and (severity is None or s["severity"] == severity)
        and (issue_type is None or s["issue_type"] == issue_type)
        and (issue_date is None or s["issue_date"] == issue_date.isoformat())
    ]

    # 按严重度和创建时间排序
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda s: (severity_order.get(s["severity"], 99), s["created_at"]))

    total = len(items)
    start = (page - 1) * size
    paginated = items[start: start + size]

    return {"ok": True, "data": {"items": paginated, "total": total, "page": page, "size": size}}


@router.patch("/{issue_id}")
async def update_issue(
    issue_id: str,
    body: UpdateIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E6: 更新问题（指派/调整优先级/状态流转）。"""
    issue = _issues.get(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    if issue["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该问题记录")
    if issue["status"] in {"closed"}:
        raise HTTPException(status_code=409, detail="问题已关闭，不可修改")

    if body.severity and body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")
    if body.status and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    now = datetime.now(tz=timezone.utc)
    updates: Dict[str, Any] = {"updated_at": now.isoformat()}

    if body.assigned_to is not None:
        updates["assigned_to"] = body.assigned_to
        if issue["status"] == "open":
            updates["status"] = "in_progress"
    if body.severity is not None:
        updates["severity"] = body.severity
    if body.status is not None:
        updates["status"] = body.status
    if body.description is not None:
        updates["description"] = body.description
    if body.evidence_urls is not None:
        updates["evidence_urls"] = body.evidence_urls
    if body.due_hours is not None:
        updates["due_at"] = _calc_due_at(issue.get("severity", "medium"), body.due_hours)

    issue.update(updates)
    log.info("issue_updated", issue_id=issue_id, updates=list(updates.keys()),
             tenant_id=x_tenant_id)
    return {"ok": True, "data": issue}


@router.post("/{issue_id}/resolve")
async def resolve_issue(
    issue_id: str,
    body: ResolveIssueRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E6: 标记问题为已解决。"""
    issue = _issues.get(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    if issue["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该问题记录")
    if issue["status"] in {"resolved", "closed"}:
        raise HTTPException(status_code=409, detail=f"问题已是 {issue['status']} 状态")

    now = datetime.now(tz=timezone.utc)
    issue.update(
        status="resolved",
        resolved_at=now.isoformat(),
        resolution_notes=body.resolution_notes,
        updated_at=now.isoformat(),
    )
    log.info("issue_resolved", issue_id=issue_id, resolved_by=body.resolved_by,
             tenant_id=x_tenant_id)
    return {"ok": True, "data": issue}


@router.post("/auto-detect/{store_id}")
async def auto_detect_issues(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """
    E5: 自动扫描预警（Agent 触发）。
    扫描：超时KDS任务 / 未确认称重记录 / 折扣异常 / 低库存。
    自动创建问题记录并返回汇总。
    """
    now = datetime.now(tz=timezone.utc)
    today = now.date()
    created_ids: List[str] = []

    # 1. 超时 KDS 任务
    kds_timeouts = await _scan_kds_timeout(store_id, x_tenant_id)
    for task in kds_timeouts:
        issue_id = str(uuid.uuid4())
        record = {
            "id": issue_id,
            "tenant_id": x_tenant_id,
            "store_id": store_id,
            "issue_date": today.isoformat(),
            "issue_type": "kds_timeout",
            "severity": "high",
            "title": f"KDS超时: {task.get('dish_name', '未知菜品')}",
            "description": f"任务ID {task.get('id')} 已超出预期出餐时间",
            "evidence_urls": [],
            "assigned_to": None,
            "due_at": _calc_due_at("high", None),
            "resolved_at": None,
            "resolution_notes": None,
            "status": "open",
            "created_by": "system:auto_detect",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "is_deleted": False,
        }
        _issues[issue_id] = record
        created_ids.append(issue_id)

    # 2. 折扣异常
    discount_abuses = await _scan_discount_abuse(store_id, x_tenant_id)
    for order in discount_abuses:
        issue_id = str(uuid.uuid4())
        record = {
            "id": issue_id,
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
            "evidence_urls": [],
            "assigned_to": None,
            "due_at": _calc_due_at("critical", None),
            "resolved_at": None,
            "resolution_notes": None,
            "status": "open",
            "created_by": "system:auto_detect",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "is_deleted": False,
        }
        _issues[issue_id] = record
        created_ids.append(issue_id)

    # 3. 低库存
    low_inventory = await _scan_low_inventory(store_id, x_tenant_id)
    for ingredient in low_inventory:
        issue_id = str(uuid.uuid4())
        record = {
            "id": issue_id,
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
            "evidence_urls": [],
            "assigned_to": None,
            "due_at": _calc_due_at("medium", None),
            "resolved_at": None,
            "resolution_notes": None,
            "status": "open",
            "created_by": "system:auto_detect",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "is_deleted": False,
        }
        _issues[issue_id] = record
        created_ids.append(issue_id)

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
