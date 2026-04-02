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

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/inspections", tags=["ops-inspections"])
log = structlog.get_logger(__name__)

_VALID_STATUSES = {"draft", "submitted", "acknowledged", "closed"}

# ─── 内存存储────────────────────────────────────────────────────────────────
_reports: Dict[str, Dict[str, Any]] = {}


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
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calc_overall_score(dimensions: List[Dict[str, Any]]) -> Optional[float]:
    if not dimensions:
        return None
    total_score = sum(d.get("score", 0) for d in dimensions)
    total_max = sum(d.get("max_score", 0) for d in dimensions)
    if total_max == 0:
        return None
    return round(total_score / total_max * 100, 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  注意：rankings 和 {id} 路由顺序，rankings 必须在 {id} 前
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/rankings")
async def get_inspection_rankings(
    start_date: date = Query(..., description="起始日期"),
    end_date: date = Query(..., description="截止日期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E8: 门店评分排名（总部全局视角）。按均分降序。"""
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    store_scores: Dict[str, List[float]] = {}
    store_counts: Dict[str, int] = {}

    for r in _reports.values():
        if r["tenant_id"] != x_tenant_id:
            continue
        if r.get("is_deleted") or r["status"] not in {"submitted", "acknowledged", "closed"}:
            continue
        if not (start_str <= r["inspection_date"] <= end_str):
            continue
        sid = r["store_id"]
        score = r.get("overall_score")
        if score is not None:
            store_scores.setdefault(sid, []).append(float(score))
            store_counts[sid] = store_counts.get(sid, 0) + 1

    rankings = []
    for store_id, scores in store_scores.items():
        avg = round(sum(scores) / len(scores), 1)
        rankings.append({
            "store_id": store_id,
            "avg_score": avg,
            "inspection_count": store_counts[store_id],
            "min_score": round(min(scores), 1),
            "max_score": round(max(scores), 1),
        })

    rankings.sort(key=lambda r: r["avg_score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    return {
        "ok": True,
        "data": {
            "start_date": start_str,
            "end_date": end_str,
            "store_count": len(rankings),
            "rankings": rankings,
        },
    }


@router.post("", status_code=201)
async def create_inspection(
    body: CreateInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E8: 创建巡店报告（草稿状态）。"""
    report_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    dimensions_data = [d.model_dump() for d in body.dimensions]
    overall_score = _calc_overall_score(dimensions_data)

    record: Dict[str, Any] = {
        "id": report_id,
        "tenant_id": x_tenant_id,
        "store_id": body.store_id,
        "inspection_date": body.inspection_date.isoformat(),
        "inspector_id": body.inspector_id,
        "overall_score": overall_score,
        "dimensions": dimensions_data,
        "photos": [p.model_dump() for p in body.photos],
        "action_items": [a.model_dump() for a in body.action_items],
        "status": "draft",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "is_deleted": False,
    }
    _reports[report_id] = record

    log.info("inspection_created", report_id=report_id, store_id=body.store_id,
             inspector_id=body.inspector_id, overall_score=overall_score,
             tenant_id=x_tenant_id)
    return {"ok": True, "data": record}


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
) -> Dict[str, Any]:
    """E8: 查询巡店历史列表。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    start_str = start_date.isoformat() if start_date else None
    end_str = end_date.isoformat() if end_date else None

    items = [
        r for r in _reports.values()
        if r["tenant_id"] == x_tenant_id
        and not r.get("is_deleted", False)
        and (store_id is None or r["store_id"] == store_id)
        and (inspector_id is None or r["inspector_id"] == inspector_id)
        and (status is None or r["status"] == status)
        and (start_str is None or r["inspection_date"] >= start_str)
        and (end_str is None or r["inspection_date"] <= end_str)
    ]

    items.sort(key=lambda r: r["inspection_date"], reverse=True)

    total = len(items)
    start = (page - 1) * size
    paginated = items[start: start + size]

    return {"ok": True, "data": {"items": paginated, "total": total, "page": page, "size": size}}


@router.get("/{report_id}")
async def get_inspection(
    report_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E8: 巡店报告详情。"""
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="巡店报告不存在")
    if report["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权查看该巡店报告")
    return {"ok": True, "data": report}


@router.post("/{report_id}/submit")
async def submit_inspection(
    report_id: str,
    body: SubmitInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E8: 提交巡店报告（草稿→已提交）。提交后门店可见。"""
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="巡店报告不存在")
    if report["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该巡店报告")
    if report["status"] != "draft":
        raise HTTPException(status_code=409, detail=f"报告当前状态 {report['status']}，只有草稿可提交")

    now = datetime.now(tz=timezone.utc)
    report.update(status="submitted", updated_at=now.isoformat())
    if body.final_notes:
        existing = report.get("notes") or ""
        report["notes"] = (existing + "\n" + body.final_notes).strip()

    log.info("inspection_submitted", report_id=report_id,
             store_id=report["store_id"], tenant_id=x_tenant_id)
    return {"ok": True, "data": report}


@router.post("/{report_id}/acknowledge")
async def acknowledge_inspection(
    report_id: str,
    body: AcknowledgeInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """E8: 门店确认收到巡店报告。"""
    report = _reports.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="巡店报告不存在")
    if report["tenant_id"] != x_tenant_id:
        raise HTTPException(status_code=403, detail="无权操作该巡店报告")
    if report["status"] != "submitted":
        raise HTTPException(status_code=409, detail=f"报告当前状态 {report['status']}，只有已提交状态可确认")

    now = datetime.now(tz=timezone.utc)
    report.update(
        status="acknowledged",
        acknowledged_by=body.acknowledged_by,
        acknowledged_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    if body.ack_notes:
        existing = report.get("ack_notes") or ""
        report["ack_notes"] = (existing + "\n" + body.ack_notes).strip()

    log.info("inspection_acknowledged", report_id=report_id,
             acknowledged_by=body.acknowledged_by, tenant_id=x_tenant_id)
    return {"ok": True, "data": report}
