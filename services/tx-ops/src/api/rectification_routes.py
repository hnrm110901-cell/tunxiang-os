"""整改指挥中心 API 路由（Mock 数据版）

端点:
  GET   /api/v1/ops/rectification/summary                  统计汇总
  GET   /api/v1/ops/rectification/tasks                    任务列表（支持筛选）
  GET   /api/v1/ops/rectification/tasks/{task_id}          任务详情
  POST  /api/v1/ops/rectification/tasks                    从预警创建整改任务
  PATCH /api/v1/ops/rectification/tasks/{task_id}/status   更新状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/rectification", tags=["ops-rectification"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_STATUSES = {"pending", "in_progress", "submitted", "verified", "rejected", "overdue"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateRectificationTaskRequest(BaseModel):
    alert_id: str = Field(..., description="关联预警ID")
    store_id: str = Field(..., description="门店ID")
    store_name: str = Field(..., description="门店名称")
    title: str = Field(..., max_length=200, description="整改任务标题")
    description: str = Field(..., description="问题描述")
    severity: str = Field("medium", description="critical/high/medium/low")
    category: str = Field(..., description="整改类别: food_safety/hygiene/equipment/service/fire_safety")
    assigned_to: str = Field(..., description="责任人ID")
    assigned_name: str = Field(..., description="责任人姓名")
    deadline: str = Field(..., description="整改截止时间 ISO8601")
    evidence_required: bool = Field(True, description="是否需要整改凭证")
    region: Optional[str] = Field(None, description="区域")


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="目标状态: in_progress/submitted/verified/rejected")
    remark: Optional[str] = Field(None, description="备注说明")
    evidence_urls: Optional[List[str]] = Field(None, description="整改凭证图片")
    operator_id: Optional[str] = Field(None, description="操作人ID")
    operator_name: Optional[str] = Field(None, description="操作人姓名")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_TASKS: List[Dict[str, Any]] = [
    {
        "id": "rect-001",
        "alert_id": "alert-2001",
        "store_id": "store-001",
        "store_name": "尝在一起(芙蓉广场店)",
        "title": "后厨冰箱温度超标整改",
        "description": "3号冷藏柜温度持续高于8度，存在食安隐患。需检查压缩机、清洁散热器。",
        "severity": "critical",
        "category": "food_safety",
        "status": "in_progress",
        "assigned_to": "emp-101",
        "assigned_name": "张伟",
        "region": "长沙",
        "deadline": "2026-04-10T18:00:00+08:00",
        "created_at": "2026-04-09T10:30:00+08:00",
        "updated_at": "2026-04-09T14:00:00+08:00",
        "evidence_required": True,
        "evidence_urls": [],
        "remarks": [
            {"time": "2026-04-09T14:00:00+08:00", "operator": "张伟", "content": "已联系制冷维修师傅，预计下午到店"}
        ],
    },
    {
        "id": "rect-002",
        "alert_id": "alert-2002",
        "store_id": "store-002",
        "store_name": "尝在一起(五一广场店)",
        "title": "消毒柜未按规定使用",
        "description": "巡检发现消毒柜长时间未通电，餐具消毒记录缺失3天。",
        "severity": "high",
        "category": "hygiene",
        "status": "pending",
        "assigned_to": "emp-102",
        "assigned_name": "李娜",
        "region": "长沙",
        "deadline": "2026-04-11T12:00:00+08:00",
        "created_at": "2026-04-09T09:00:00+08:00",
        "updated_at": "2026-04-09T09:00:00+08:00",
        "evidence_required": True,
        "evidence_urls": [],
        "remarks": [],
    },
    {
        "id": "rect-003",
        "alert_id": "alert-2003",
        "store_id": "store-003",
        "store_name": "最黔线(河西店)",
        "title": "灭火器过期更换",
        "description": "前厅2个灭火器已过期，需立即更换并更新消防台账。",
        "severity": "high",
        "category": "fire_safety",
        "status": "submitted",
        "assigned_to": "emp-103",
        "assigned_name": "王强",
        "region": "长沙",
        "deadline": "2026-04-12T18:00:00+08:00",
        "created_at": "2026-04-08T16:00:00+08:00",
        "updated_at": "2026-04-10T09:00:00+08:00",
        "evidence_required": True,
        "evidence_urls": ["https://oss.tunxiang.com/rect/003-fire-ext-1.jpg", "https://oss.tunxiang.com/rect/003-fire-ext-2.jpg"],
        "remarks": [
            {"time": "2026-04-10T09:00:00+08:00", "operator": "王强", "content": "已更换2个灭火器，上传凭证照片"}
        ],
    },
    {
        "id": "rect-004",
        "alert_id": "alert-2004",
        "store_id": "store-001",
        "store_name": "尝在一起(芙蓉广场店)",
        "title": "收银台卫生不达标",
        "description": "收银台区域杂物堆放，台面有油渍，影响顾客体验。",
        "severity": "medium",
        "category": "hygiene",
        "status": "verified",
        "assigned_to": "emp-104",
        "assigned_name": "赵敏",
        "region": "长沙",
        "deadline": "2026-04-10T12:00:00+08:00",
        "created_at": "2026-04-08T11:00:00+08:00",
        "updated_at": "2026-04-09T16:00:00+08:00",
        "evidence_required": True,
        "evidence_urls": ["https://oss.tunxiang.com/rect/004-clean-1.jpg"],
        "remarks": [
            {"time": "2026-04-09T10:00:00+08:00", "operator": "赵敏", "content": "已清理完毕"},
            {"time": "2026-04-09T16:00:00+08:00", "operator": "区域经理陈刚", "content": "验收通过"},
        ],
    },
    {
        "id": "rect-005",
        "alert_id": "alert-2005",
        "store_id": "store-004",
        "store_name": "尚宫厨(万达店)",
        "title": "POS打印机频繁卡纸",
        "description": "商米T2主POS打印机连续3天出现卡纸，影响出单效率。",
        "severity": "medium",
        "category": "equipment",
        "status": "in_progress",
        "assigned_to": "emp-105",
        "assigned_name": "刘涛",
        "region": "株洲",
        "deadline": "2026-04-11T18:00:00+08:00",
        "created_at": "2026-04-09T08:00:00+08:00",
        "updated_at": "2026-04-09T11:00:00+08:00",
        "evidence_required": False,
        "evidence_urls": [],
        "remarks": [
            {"time": "2026-04-09T11:00:00+08:00", "operator": "刘涛", "content": "已申请备用打印机，明天到货"}
        ],
    },
    {
        "id": "rect-006",
        "alert_id": "alert-2006",
        "store_id": "store-002",
        "store_name": "尝在一起(五一广场店)",
        "title": "服务员未佩戴工牌",
        "description": "巡检发现2名服务员未按要求佩戴工牌，需加强管理。",
        "severity": "low",
        "category": "service",
        "status": "overdue",
        "assigned_to": "emp-106",
        "assigned_name": "孙丽",
        "region": "长沙",
        "deadline": "2026-04-08T18:00:00+08:00",
        "created_at": "2026-04-07T14:00:00+08:00",
        "updated_at": "2026-04-07T14:00:00+08:00",
        "evidence_required": False,
        "evidence_urls": [],
        "remarks": [],
    },
    {
        "id": "rect-007",
        "alert_id": "alert-2007",
        "store_id": "store-005",
        "store_name": "最黔线(岳麓店)",
        "title": "地面防滑垫破损更换",
        "description": "后厨入口处防滑垫严重磨损，存在滑倒风险，需更换。",
        "severity": "high",
        "category": "fire_safety",
        "status": "rejected",
        "assigned_to": "emp-107",
        "assigned_name": "周杰",
        "region": "长沙",
        "deadline": "2026-04-11T18:00:00+08:00",
        "created_at": "2026-04-08T10:00:00+08:00",
        "updated_at": "2026-04-10T08:00:00+08:00",
        "evidence_required": True,
        "evidence_urls": ["https://oss.tunxiang.com/rect/007-mat-1.jpg"],
        "remarks": [
            {"time": "2026-04-09T17:00:00+08:00", "operator": "周杰", "content": "已更换，上传照片"},
            {"time": "2026-04-10T08:00:00+08:00", "operator": "区域经理陈刚", "content": "驳回：照片模糊看不清，请重新拍摄"},
        ],
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/summary")
async def get_rectification_summary(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """整改任务统计汇总。"""
    log.info("rectification_summary_requested", tenant_id=x_tenant_id)

    status_counts: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {}
    category_counts: Dict[str, int] = {}
    overdue_count = 0
    store_counts: Dict[str, int] = {}

    for t in _MOCK_TASKS:
        status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1
        severity_counts[t["severity"]] = severity_counts.get(t["severity"], 0) + 1
        category_counts[t["category"]] = category_counts.get(t["category"], 0) + 1
        store_counts[t["store_id"]] = store_counts.get(t["store_id"], 0) + 1
        if t["status"] == "overdue":
            overdue_count += 1

    total = len(_MOCK_TASKS)
    completed = status_counts.get("verified", 0)
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0

    return {
        "ok": True,
        "data": {
            "total": total,
            "by_status": status_counts,
            "by_severity": severity_counts,
            "by_category": category_counts,
            "overdue_count": overdue_count,
            "completion_rate": completion_rate,
            "avg_resolve_hours": 18.5,
            "top_stores": [
                {"store_id": sid, "store_name": next((t["store_name"] for t in _MOCK_TASKS if t["store_id"] == sid), sid), "count": cnt}
                for sid, cnt in sorted(store_counts.items(), key=lambda x: -x[1])[:5]
            ],
        },
    }


@router.get("/tasks")
async def list_rectification_tasks(
    status: Optional[str] = Query(None, description="状态筛选"),
    severity: Optional[str] = Query(None, description="严重度筛选"),
    region: Optional[str] = Query(None, description="区域筛选"),
    store_id: Optional[str] = Query(None, description="门店ID筛选"),
    q: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """整改任务列表，支持多条件筛选。"""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")
    if severity and severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    log.info("rectification_tasks_listed", tenant_id=x_tenant_id,
             status=status, severity=severity, region=region, store_id=store_id)

    filtered = _MOCK_TASKS[:]
    if status:
        filtered = [t for t in filtered if t["status"] == status]
    if severity:
        filtered = [t for t in filtered if t["severity"] == severity]
    if region:
        filtered = [t for t in filtered if t.get("region") == region]
    if store_id:
        filtered = [t for t in filtered if t["store_id"] == store_id]
    if q:
        q_lower = q.lower()
        filtered = [t for t in filtered if q_lower in t["title"].lower() or q_lower in t["description"].lower()]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/tasks/{task_id}")
async def get_rectification_task(
    task_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """整改任务详情。"""
    log.info("rectification_task_detail", task_id=task_id, tenant_id=x_tenant_id)
    for t in _MOCK_TASKS:
        if t["id"] == task_id:
            return {"ok": True, "data": t}
    raise HTTPException(status_code=404, detail="整改任务不存在")


@router.post("/tasks", status_code=201)
async def create_rectification_task(
    body: CreateRectificationTaskRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """从预警创建整改任务。"""
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc).isoformat()
    new_task: Dict[str, Any] = {
        "id": f"rect-{uuid.uuid4().hex[:8]}",
        "alert_id": body.alert_id,
        "store_id": body.store_id,
        "store_name": body.store_name,
        "title": body.title,
        "description": body.description,
        "severity": body.severity,
        "category": body.category,
        "status": "pending",
        "assigned_to": body.assigned_to,
        "assigned_name": body.assigned_name,
        "region": body.region,
        "deadline": body.deadline,
        "created_at": now,
        "updated_at": now,
        "evidence_required": body.evidence_required,
        "evidence_urls": [],
        "remarks": [],
    }

    log.info("rectification_task_created", task_id=new_task["id"],
             store_id=body.store_id, severity=body.severity, tenant_id=x_tenant_id)
    return {"ok": True, "data": new_task}


@router.patch("/tasks/{task_id}/status")
async def update_rectification_status(
    task_id: str,
    body: UpdateStatusRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """更新整改任务状态。"""
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 必须是 {_VALID_STATUSES} 之一")

    log.info("rectification_status_updated", task_id=task_id,
             new_status=body.status, tenant_id=x_tenant_id)

    for t in _MOCK_TASKS:
        if t["id"] == task_id:
            # Mock: 返回更新后的任务（不实际修改内存数据）
            updated = {**t, "status": body.status, "updated_at": datetime.now(tz=timezone.utc).isoformat()}
            if body.evidence_urls:
                updated["evidence_urls"] = body.evidence_urls
            if body.remark:
                updated["remarks"] = t["remarks"] + [{
                    "time": datetime.now(tz=timezone.utc).isoformat(),
                    "operator": body.operator_name or "unknown",
                    "content": body.remark,
                }]
            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="整改任务不存在")
