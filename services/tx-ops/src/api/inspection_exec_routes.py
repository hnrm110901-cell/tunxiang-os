"""巡检执行 API 路由（Mock 数据版）

与 inspection_routes.py（巡店质检历史报告）不同，本文件聚焦于 **当日巡检执行流程**。

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

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

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
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_TODAY_OVERVIEW: Dict[str, Any] = {
    "date": "2026-04-10",
    "stores_total": 12,
    "stores_inspected": 5,
    "stores_pending": 7,
    "overall_pass_rate": 88.5,
    "critical_issues_found": 2,
    "inspectors_active": 3,
    "stores": [
        {"store_id": "store-001", "store_name": "尝在一起(芙蓉广场店)", "status": "completed", "score": 92, "inspector": "巡检员陈刚"},
        {"store_id": "store-002", "store_name": "尝在一起(五一广场店)", "status": "in_progress", "score": None, "inspector": "巡检员陈刚"},
        {"store_id": "store-003", "store_name": "最黔线(河西店)", "status": "completed", "score": 85, "inspector": "巡检员王磊"},
        {"store_id": "store-004", "store_name": "尚宫厨(万达店)", "status": "completed", "score": 78, "inspector": "巡检员王磊"},
        {"store_id": "store-005", "store_name": "最黔线(岳麓店)", "status": "pending", "score": None, "inspector": None},
        {"store_id": "store-006", "store_name": "尝在一起(梅溪湖店)", "status": "skip", "score": None, "inspector": None},
    ],
}

_MOCK_ITEMS: List[Dict[str, Any]] = [
    {
        "id": "insp-item-001",
        "category": "food_safety",
        "category_name": "食品安全",
        "name": "冷藏设备温度检查",
        "description": "检查所有冷藏柜温度是否在0-5度范围内，冷冻柜是否在-18度以下",
        "weight": 10,
        "is_critical": True,
        "store_id": "store-002",
        "result": None,
        "score": None,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 1,
    },
    {
        "id": "insp-item-002",
        "category": "food_safety",
        "category_name": "食品安全",
        "name": "食材保质期检查",
        "description": "检查所有食材标签是否完整，是否有过期或临期食材",
        "weight": 10,
        "is_critical": True,
        "store_id": "store-002",
        "result": None,
        "score": None,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 2,
    },
    {
        "id": "insp-item-003",
        "category": "food_safety",
        "category_name": "食品安全",
        "name": "消毒记录检查",
        "description": "检查餐具消毒记录、消毒液配比是否达标",
        "weight": 8,
        "is_critical": True,
        "store_id": "store-002",
        "result": "fail",
        "score": 40,
        "remark": "消毒柜未通电，消毒记录缺失3天",
        "evidence_urls": ["https://oss.tunxiang.com/insp/003-disinfect.jpg"],
        "sort_order": 3,
    },
    {
        "id": "insp-item-004",
        "category": "hygiene",
        "category_name": "环境卫生",
        "name": "后厨地面清洁",
        "description": "检查后厨地面是否干净无积水、无油渍",
        "weight": 6,
        "is_critical": False,
        "store_id": "store-002",
        "result": "pass",
        "score": 90,
        "remark": "地面整洁",
        "evidence_urls": [],
        "sort_order": 4,
    },
    {
        "id": "insp-item-005",
        "category": "hygiene",
        "category_name": "环境卫生",
        "name": "前厅桌面及地面",
        "description": "检查前厅用餐区桌面清洁度、地面卫生",
        "weight": 6,
        "is_critical": False,
        "store_id": "store-002",
        "result": "pass",
        "score": 85,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 5,
    },
    {
        "id": "insp-item-006",
        "category": "hygiene",
        "category_name": "环境卫生",
        "name": "洗手间卫生",
        "description": "检查洗手间清洁度、洗手液/纸巾是否充足",
        "weight": 5,
        "is_critical": False,
        "store_id": "store-002",
        "result": None,
        "score": None,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 6,
    },
    {
        "id": "insp-item-007",
        "category": "service",
        "category_name": "服务规范",
        "name": "员工仪容仪表",
        "description": "检查在岗员工是否统一着装、佩戴工牌、个人卫生达标",
        "weight": 5,
        "is_critical": False,
        "store_id": "store-002",
        "result": "pass",
        "score": 80,
        "remark": "1人未戴工牌，已提醒",
        "evidence_urls": [],
        "sort_order": 7,
    },
    {
        "id": "insp-item-008",
        "category": "service",
        "category_name": "服务规范",
        "name": "服务流程执行",
        "description": "检查迎宾、点餐、上菜、结账流程是否按SOP执行",
        "weight": 5,
        "is_critical": False,
        "store_id": "store-002",
        "result": None,
        "score": None,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 8,
    },
    {
        "id": "insp-item-009",
        "category": "fire_safety",
        "category_name": "消防安全",
        "name": "灭火器/消防栓检查",
        "description": "检查灭火器是否在有效期内、消防栓是否可用、安全通道是否畅通",
        "weight": 8,
        "is_critical": True,
        "store_id": "store-002",
        "result": "pass",
        "score": 95,
        "remark": "全部合格",
        "evidence_urls": [],
        "sort_order": 9,
    },
    {
        "id": "insp-item-010",
        "category": "equipment",
        "category_name": "设备状态",
        "name": "POS/KDS设备运行",
        "description": "检查POS机、KDS屏、打印机是否正常运行",
        "weight": 5,
        "is_critical": False,
        "store_id": "store-002",
        "result": "pass",
        "score": 100,
        "remark": None,
        "evidence_urls": [],
        "sort_order": 10,
    },
]

_MOCK_MY_RECTIFICATION_TASKS: List[Dict[str, Any]] = [
    {
        "id": "rect-my-001",
        "title": "消毒柜未按规定使用",
        "store_id": "store-002",
        "store_name": "尝在一起(五一广场店)",
        "severity": "high",
        "status": "pending",
        "deadline": "2026-04-11T12:00:00+08:00",
        "source": "巡检发现",
        "inspection_item_id": "insp-item-003",
        "created_at": "2026-04-10T14:00:00+08:00",
        "progress_pct": 0,
        "feedbacks": [],
    },
    {
        "id": "rect-my-002",
        "title": "后厨排油烟管道清洁",
        "store_id": "store-004",
        "store_name": "尚宫厨(万达店)",
        "severity": "medium",
        "status": "in_progress",
        "deadline": "2026-04-12T18:00:00+08:00",
        "source": "巡检发现",
        "inspection_item_id": None,
        "created_at": "2026-04-09T16:00:00+08:00",
        "progress_pct": 50,
        "feedbacks": [
            {
                "time": "2026-04-10T10:00:00+08:00",
                "type": "progress",
                "operator": "王强",
                "content": "已联系清洁公司，预计明天上午到店施工",
                "progress_pct": 50,
            },
        ],
    },
    {
        "id": "rect-my-003",
        "title": "员工更衣室储物柜损坏维修",
        "store_id": "store-003",
        "store_name": "最黔线(河西店)",
        "severity": "low",
        "status": "completed",
        "deadline": "2026-04-10T18:00:00+08:00",
        "source": "员工反馈",
        "inspection_item_id": None,
        "created_at": "2026-04-08T09:00:00+08:00",
        "progress_pct": 100,
        "feedbacks": [
            {
                "time": "2026-04-09T14:00:00+08:00",
                "type": "completed",
                "operator": "刘涛",
                "content": "储物柜已更换锁芯并修复门板",
                "progress_pct": 100,
                "evidence_urls": ["https://oss.tunxiang.com/rect/my003-fixed.jpg"],
            },
        ],
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/api/v1/ops/inspection/today")
async def get_today_inspection(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """今日巡检概览。"""
    log.info("inspection_today_requested", tenant_id=x_tenant_id)
    return {"ok": True, "data": _MOCK_TODAY_OVERVIEW}


@router.get("/api/v1/ops/inspection/items")
async def list_inspection_items(
    store_id: Optional[str] = Query(None, description="门店ID"),
    category: Optional[str] = Query(None, description="类别筛选"),
    result: Optional[str] = Query(None, description="结果筛选: pass/fail/na"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """巡检项列表。"""
    log.info("inspection_items_listed", tenant_id=x_tenant_id, store_id=store_id)

    filtered = _MOCK_ITEMS[:]
    if store_id:
        filtered = [i for i in filtered if i["store_id"] == store_id]
    if category:
        filtered = [i for i in filtered if i["category"] == category]
    if result:
        filtered = [i for i in filtered if i["result"] == result]

    # 按类别分组
    categories: Dict[str, List[Dict[str, Any]]] = {}
    for item in filtered:
        cat = item["category_name"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    total = len(filtered)
    checked = sum(1 for i in filtered if i["result"] is not None)
    passed = sum(1 for i in filtered if i["result"] == "pass")

    return {
        "ok": True,
        "data": {
            "items": filtered,
            "by_category": categories,
            "total": total,
            "checked": checked,
            "passed": passed,
            "failed": sum(1 for i in filtered if i["result"] == "fail"),
            "progress_pct": round(checked / total * 100, 1) if total > 0 else 0,
        },
    }


@router.patch("/api/v1/ops/inspection/items/{item_id}")
async def update_inspection_item(
    item_id: str,
    body: UpdateInspectionItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """更新单个巡检项检查结果。"""
    if body.result not in {"pass", "fail", "na"}:
        raise HTTPException(status_code=400, detail="result 必须是 pass/fail/na 之一")

    log.info("inspection_item_updated", item_id=item_id, result=body.result, tenant_id=x_tenant_id)

    for item in _MOCK_ITEMS:
        if item["id"] == item_id:
            updated = {
                **item,
                "result": body.result,
                "score": body.score,
                "remark": body.remark,
                "evidence_urls": body.evidence_urls or item["evidence_urls"],
            }
            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="巡检项不存在")


@router.post("/api/v1/ops/inspection/submit")
async def submit_inspection(
    body: SubmitInspectionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """提交巡检报告。"""
    log.info("inspection_submitted", store_id=body.store_id,
             inspector_id=body.inspector_id, tenant_id=x_tenant_id)

    report_id = f"report-{uuid.uuid4().hex[:8]}"
    return {
        "ok": True,
        "data": {
            "report_id": report_id,
            "store_id": body.store_id,
            "inspector_id": body.inspector_id,
            "inspector_name": body.inspector_name,
            "overall_score": body.overall_score or 85,
            "items_checked": len(body.item_ids),
            "summary": body.summary or "巡检完成，发现2项不合格需整改",
            "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
            "rectification_tasks_created": 1,
        },
    }


@router.get("/api/v1/ops/rectification/my-tasks")
async def get_my_rectification_tasks(
    status: Optional[str] = Query(None, description="状态筛选: pending/in_progress/completed"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """我的整改任务列表。"""
    log.info("my_rectification_tasks_requested", tenant_id=x_tenant_id)

    filtered = _MOCK_MY_RECTIFICATION_TASKS[:]
    if status:
        filtered = [t for t in filtered if t["status"] == status]

    return {
        "ok": True,
        "data": {
            "items": filtered,
            "total": len(filtered),
            "pending": sum(1 for t in _MOCK_MY_RECTIFICATION_TASKS if t["status"] == "pending"),
            "in_progress": sum(1 for t in _MOCK_MY_RECTIFICATION_TASKS if t["status"] == "in_progress"),
            "completed": sum(1 for t in _MOCK_MY_RECTIFICATION_TASKS if t["status"] == "completed"),
        },
    }


@router.patch("/api/v1/ops/rectification/tasks/{task_id}/feedback")
async def submit_rectification_feedback(
    task_id: str,
    body: RectificationFeedbackRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """提交整改反馈（进度更新/完成报告/求助）。"""
    if body.feedback_type not in {"progress", "completed", "need_help"}:
        raise HTTPException(status_code=400, detail="feedback_type 必须是 progress/completed/need_help 之一")

    log.info("rectification_feedback_submitted", task_id=task_id,
             feedback_type=body.feedback_type, tenant_id=x_tenant_id)

    for task in _MOCK_MY_RECTIFICATION_TASKS:
        if task["id"] == task_id:
            now = datetime.now(tz=timezone.utc).isoformat()
            new_feedback = {
                "time": now,
                "type": body.feedback_type,
                "operator": body.operator_name,
                "content": body.content,
                "progress_pct": body.progress_pct,
            }
            if body.evidence_urls:
                new_feedback["evidence_urls"] = body.evidence_urls

            updated = {
                **task,
                "progress_pct": body.progress_pct if body.progress_pct is not None else task["progress_pct"],
                "feedbacks": task["feedbacks"] + [new_feedback],
            }
            if body.feedback_type == "completed":
                updated["status"] = "completed"
                updated["progress_pct"] = 100

            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="整改任务不存在")
