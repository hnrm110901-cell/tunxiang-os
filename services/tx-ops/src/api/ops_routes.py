"""日清日结操作层 API 路由 — E1/E2/E4/E5/E7 端点

约 15 个端点，覆盖开店、巡航、异常、闭店、复盘。
统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/daily-ops", tags=["daily-ops"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CheckItemRequest(BaseModel):
    item_id: str
    status: str = Field(..., pattern="^(checked|skipped)$")
    result: str = Field("pass", pattern="^(pass|fail|na)$")
    note: Optional[str] = None


class ApproveOpeningRequest(BaseModel):
    manager_id: str


class PatrolRequest(BaseModel):
    operator_id: str
    findings: List[Dict[str, Any]]


class StocktakeItem(BaseModel):
    ingredient_id: str
    name: str
    expected_qty: float
    actual_qty: float
    unit: str = ""


class WasteItem(BaseModel):
    ingredient_id: str
    name: str
    qty: float
    unit: str = ""
    reason: str = ""
    cost_fen: int = 0


class FinalizeClosingRequest(BaseModel):
    manager_id: str


class ExceptionReportRequest(BaseModel):
    type: str
    detail: Dict[str, Any] = {}
    reporter_id: str


class EscalateRequest(BaseModel):
    to_level: int


class ResolveRequest(BaseModel):
    resolution: Dict[str, Any]
    resolver_id: str


class ActionItemRequest(BaseModel):
    title: str
    description: str = ""
    assignee_id: str = ""
    priority: str = "medium"
    due_date: str = ""


class SubmitActionItemsRequest(BaseModel):
    items: List[ActionItemRequest]
    manager_id: str


class SignOffRequest(BaseModel):
    manager_id: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E1 开店准备
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stores/{store_id}/opening/checklist")
async def create_opening_checklist(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E1: 生成当日开店检查单"""
    from ..services.store_opening import create_opening_checklist as svc

    try:
        result = await svc(store_id, date.today(), x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/stores/{store_id}/opening/checklist/{checklist_id}/items/{item_id}")
async def check_opening_item(
    store_id: str,
    checklist_id: str,
    item_id: str,
    body: CheckItemRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E1: 逐项打勾"""
    from ..services.store_opening import check_item as svc

    try:
        result = await svc(
            checklist_id, item_id, body.status, body.result,
            db=None, result=body.result, note=body.note, tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stores/{store_id}/opening/status")
async def get_opening_status(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E1: 开店检查进度"""
    from ..services.store_opening import get_opening_status as svc

    result = svc(store_id, date.today(), x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/opening/approve")
async def approve_opening(
    store_id: str,
    body: ApproveOpeningRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E1: 店长确认开店放行"""
    from ..services.store_opening import approve_opening as svc

    try:
        result = await svc(store_id, body.manager_id, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E2 营业巡航
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/stores/{store_id}/cruise/dashboard")
async def get_cruise_dashboard(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E2: 实时经营看板"""
    from ..services.cruise_monitor import get_realtime_dashboard as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/cruise/patrol")
async def record_patrol(
    store_id: str,
    body: PatrolRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E2: 记录巡台发现"""
    from ..services.cruise_monitor import record_patrol as svc

    result = await svc(store_id, body.operator_id, body.findings, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E4 异常处置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stores/{store_id}/exceptions")
async def report_exception(
    store_id: str,
    body: ExceptionReportRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E4: 上报异常"""
    from ..services.exception_workflow import report_exception as svc

    try:
        result = await svc(store_id, body.type, body.detail, body.reporter_id, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/exceptions/{exception_id}/escalate")
async def escalate_exception(
    exception_id: str,
    body: EscalateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E4: 升级异常"""
    from ..services.exception_workflow import escalate_exception as svc

    try:
        result = await svc(exception_id, body.to_level, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/exceptions/{exception_id}/resolve")
async def resolve_exception(
    exception_id: str,
    body: ResolveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E4: 关闭异常"""
    from ..services.exception_workflow import resolve_exception as svc

    try:
        result = await svc(exception_id, body.resolution, body.resolver_id, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stores/{store_id}/exceptions")
async def get_open_exceptions(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E4: 未关闭异常列表"""
    from ..services.exception_workflow import get_open_exceptions as svc

    result = await svc(store_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E5 闭店盘点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/stores/{store_id}/closing/checklist")
async def create_closing_checklist(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E5: 生成闭店检查单"""
    from ..services.store_closing import create_closing_checklist as svc

    try:
        result = await svc(store_id, date.today(), x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stores/{store_id}/closing/stocktake")
async def record_stocktake(
    store_id: str,
    items: List[StocktakeItem],
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E5: 原料盘点"""
    from ..services.store_closing import record_closing_stocktake as svc

    result = await svc(store_id, [i.model_dump() for i in items], x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/closing/waste")
async def record_waste(
    store_id: str,
    items: List[WasteItem],
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E5: 损耗上报"""
    from ..services.store_closing import record_waste_report as svc

    result = await svc(store_id, [i.model_dump() for i in items], x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/closing/finalize")
async def finalize_closing(
    store_id: str,
    body: FinalizeClosingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E5: 闭店放行"""
    from ..services.store_closing import finalize_closing as svc

    try:
        result = await svc(store_id, body.manager_id, x_tenant_id, db=None)
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  E7 店长复盘
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/stores/{store_id}/review/{review_date}")
async def get_daily_review(
    store_id: str,
    review_date: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E7: 生成日度复盘"""
    from ..services.daily_review import generate_daily_review as svc

    d = date.fromisoformat(review_date)
    result = await svc(store_id, d, x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/review/{review_date}/actions")
async def submit_action_items(
    store_id: str,
    review_date: str,
    body: SubmitActionItemsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E7: 提交次日行动项"""
    from ..services.daily_review import submit_action_items as svc

    result = await svc(
        store_id,
        [i.model_dump() for i in body.items],
        body.manager_id,
        x_tenant_id,
        db=None,
    )
    return {"ok": True, "data": result}


@router.get("/stores/{store_id}/review/history")
async def get_review_history(
    store_id: str,
    days: int = 7,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E7: 历史复盘列表"""
    from ..services.daily_review import get_review_history as svc

    result = await svc(store_id, days, x_tenant_id, db=None)
    return {"ok": True, "data": result}


@router.post("/stores/{store_id}/review/{review_date}/sign-off")
async def sign_off_review(
    store_id: str,
    review_date: str,
    body: SignOffRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """E7: 店长签发复盘"""
    from ..services.daily_review import sign_off_review as svc

    d = date.fromisoformat(review_date)
    result = await svc(store_id, d, body.manager_id, x_tenant_id, db=None)
    return {"ok": True, "data": result}
