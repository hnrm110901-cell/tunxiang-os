"""请假管理 API 路由

端点列表：
  POST /api/v1/leave-requests                创建请假申请（触发审批流）
  GET  /api/v1/leave-requests                请假列表
  GET  /api/v1/leave-requests/balance        员工假期余额
  GET  /api/v1/leave-requests/{id}           请假详情
  POST /api/v1/leave-requests/{id}/cancel    撤销申请
  POST /api/v1/leave-requests/{id}/approve-callback    审批通过回调（审批引擎调用）
  POST /api/v1/leave-requests/{id}/reject-callback     审批拒绝回调

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.leave_repository import (
    BALANCE_CHECKED_TYPES,
    cancel_leave_request,
    create_leave_request,
    get_all_leave_balances,
    get_leave_balance,
    get_leave_request,
    list_leave_requests,
    on_leave_approved,
    on_leave_rejected,
    update_leave_request_approval_instance,
)
from ..services.leave_service import (
    VALID_LEAVE_TYPES,
    count_leave_work_days,
    validate_leave_request,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["leave-requests"])

# 审批流业务类型
_LEAVE_BUSINESS_TYPE = "leave"


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateLeaveReq(BaseModel):
    employee_id: str = Field(..., description="申请人员工 ID")
    store_id: str = Field(..., description="门店 ID")
    leave_type: str = Field(
        ...,
        description=f"假期类型: {', '.join(sorted(VALID_LEAVE_TYPES))}",
    )
    start_date: date = Field(..., description="开始日期")
    end_date: date = Field(..., description="结束日期")
    start_half_day: bool = Field(default=False, description="开始日下午起休（半天）")
    end_half_day: bool = Field(default=False, description="结束日上午止休（半天）")
    reason: Optional[str] = Field(None, description="请假原因")
    attachments: Optional[list[str]] = Field(None, description="附件 URL 列表（病假条等）")
    initiator_id: Optional[str] = Field(None, description="发起人 ID（留空默认=employee_id）")

    @model_validator(mode="after")
    def validate_dates(self) -> "CreateLeaveReq":
        if self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class CancelLeaveReq(BaseModel):
    employee_id: str = Field(..., description="员工 ID（鉴权用）")


class ApproveCallbackReq(BaseModel):
    approval_instance_id: str = Field(..., description="审批流实例 ID")


class RejectCallbackReq(BaseModel):
    approval_instance_id: str = Field(..., description="审批流实例 ID")
    reject_reason: Optional[str] = Field(None, description="拒绝原因")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.post("/api/v1/leave-requests")
async def create_leave(
    req: CreateLeaveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/leave-requests — 提交请假申请

    流程：
    1. 验证假期类型
    2. 计算工作日天数（排除周末/节假日）
    3. 校验年假/调休余额
    4. 创建 leave_request（status=pending）
    5. 调用审批流引擎创建审批实例
    6. 绑定 approval_instance_id
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 1. 校验假期类型
    errors = validate_leave_request(
        leave_type=req.leave_type,
        start_datetime=datetime.combine(req.start_date, datetime.min.time()),
        end_datetime=datetime.combine(req.end_date, datetime.max.time()),
        days=1.0,  # 初步校验，天数后续计算
    )
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    # 2. 计算工作日天数
    start_dt = datetime.combine(req.start_date, datetime.min.time())
    end_dt = datetime.combine(req.end_date, datetime.max.time())
    work_days = count_leave_work_days(start_dt, end_dt)

    # 半天处理
    half_day_deduction = 0.0
    if req.start_half_day:
        half_day_deduction += 0.5
    if req.end_half_day:
        half_day_deduction += 0.5
    # 两端均为半天且同一天，取0.5而非1.0
    if req.start_half_day and req.end_half_day and req.start_date == req.end_date:
        work_days = 0.5
    else:
        work_days = max(0.5, work_days - half_day_deduction)

    if work_days <= 0:
        raise HTTPException(status_code=400, detail="请假天数为 0，请检查日期范围或节假日设置")

    # 3. 校验余额（年假/调休）
    if req.leave_type in BALANCE_CHECKED_TYPES:
        balance = await get_leave_balance(
            employee_id=req.employee_id,
            year=req.start_date.year,
            leave_type=req.leave_type,
            tenant_id=tenant_id,
            db=db,
        )
        if not balance:
            raise HTTPException(
                status_code=400,
                detail=f"员工 {req.employee_id} 无 {req.leave_type} 余额记录，请联系 HR 初始化",
            )
        if float(balance["remaining_days"]) < work_days:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{req.leave_type} 余额不足：剩余 {balance['remaining_days']} 天，"
                    f"申请 {work_days} 天"
                ),
            )

    # 4. 创建 leave_request
    leave = await create_leave_request(
        tenant_id=tenant_id,
        store_id=req.store_id,
        employee_id=req.employee_id,
        leave_type=req.leave_type,
        start_date=req.start_date,
        end_date=req.end_date,
        days_requested=work_days,
        reason=req.reason,
        start_half_day=req.start_half_day,
        end_half_day=req.end_half_day,
        attachments=req.attachments,
        db=db,
    )

    # 5. 调用审批流引擎（始终尝试，引擎无模板时自动降级为单级店长审批）
    approval_instance_id: Optional[str] = None
    initiator_id = req.initiator_id or req.employee_id
    try:
        from ..services.approval_workflow_engine import ApprovalEngine
        instance = await ApprovalEngine.create_instance(
            tenant_id=tenant_id,
            business_type=_LEAVE_BUSINESS_TYPE,
            business_id=str(leave["id"]),
            title=f"{req.employee_id} 申请 {req.leave_type} {work_days} 天",
            initiator_id=initiator_id,
            context_data={
                "leave_request_id": str(leave["id"]),
                "employee_id": req.employee_id,
                "store_id": req.store_id,
                "leave_type": req.leave_type,
                "days": work_days,
                "start_date": req.start_date.isoformat(),
                "end_date": req.end_date.isoformat(),
            },
            db=db,
        )
        approval_instance_id = str(instance.get("id", ""))
    except (ValueError, KeyError, AttributeError) as exc:
        log.warning(
            "leave_approval_submit_failed",
            extra={"leave_id": str(leave["id"]), "error": str(exc)},
        )

    # 6. 绑定审批流实例
    if approval_instance_id:
        await update_leave_request_approval_instance(
            leave_request_id=str(leave["id"]),
            approval_instance_id=approval_instance_id,
            tenant_id=tenant_id,
            db=db,
        )

    return _ok({
        "id": str(leave["id"]),
        "employee_id": req.employee_id,
        "leave_type": req.leave_type,
        "start_date": req.start_date.isoformat(),
        "end_date": req.end_date.isoformat(),
        "days_requested": work_days,
        "status": "pending",
        "approval_instance_id": approval_instance_id,
    })


@router.get("/api/v1/leave-requests/balance")
async def get_balance(
    employee_id: str = Query(..., description="员工 ID"),
    year: Optional[int] = Query(None, description="年份（留空=当前年）"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/leave-requests/balance — 员工假期余额查询"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    target_year = year or date.today().year
    balances = await get_all_leave_balances(employee_id, target_year, tenant_id, db)

    return _ok({
        "employee_id": employee_id,
        "year": target_year,
        "balances": balances,
        "total": len(balances),
    })


@router.get("/api/v1/leave-requests")
async def list_leaves(
    employee_id: Optional[str] = Query(None, description="员工 ID"),
    store_id: Optional[str] = Query(None, description="门店 ID"),
    status: Optional[str] = Query(None, description="状态过滤: pending/approved/rejected/cancelled"),
    year: Optional[int] = Query(None, description="年份"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/leave-requests — 请假记录列表"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    result = await list_leave_requests(
        tenant_id=tenant_id,
        db=db,
        employee_id=employee_id,
        store_id=store_id,
        status=status,
        year=year,
        page=page,
        size=size,
    )
    return _ok(result)


@router.get("/api/v1/leave-requests/{leave_id}")
async def get_leave(
    leave_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GET /api/v1/leave-requests/{id} — 请假详情"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    leave = await get_leave_request(leave_id, tenant_id, db)
    if not leave:
        raise HTTPException(status_code=404, detail=f"请假申请不存在: {leave_id}")
    return _ok(leave)


@router.post("/api/v1/leave-requests/{leave_id}/cancel")
async def cancel_leave(
    leave_id: str,
    req: CancelLeaveReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/leave-requests/{id}/cancel — 撤销请假申请（仅 pending 状态）"""
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    try:
        result = await cancel_leave_request(leave_id, req.employee_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _ok(result)


@router.post("/api/v1/leave-requests/{leave_id}/approve-callback")
async def approve_callback(
    leave_id: str,
    req: ApproveCallbackReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/leave-requests/{id}/approve-callback — 审批通过回调

    由审批流引擎在审批通过后调用。
    执行：扣减余额 + 更新 daily_attendance 为 on_leave。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    try:
        result = await on_leave_approved(leave_id, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log.info(
        "leave_approve_callback",
        extra={"leave_id": leave_id, "instance_id": req.approval_instance_id},
    )
    return _ok(result)


@router.post("/api/v1/leave-requests/{leave_id}/reject-callback")
async def reject_callback(
    leave_id: str,
    req: RejectCallbackReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """POST /api/v1/leave-requests/{id}/reject-callback — 审批拒绝回调

    由审批流引擎在审批拒绝后调用。
    """
    tenant_id = _get_tenant_id(request)
    await _set_tenant(db, tenant_id)

    try:
        result = await on_leave_rejected(leave_id, req.reject_reason, tenant_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _ok(result)
