"""考勤深度合规 API 路由

端点列表：
  POST /api/v1/attendance-compliance/scan           运行全部合规检测
  POST /api/v1/attendance-compliance/scan/gps        GPS异常扫描
  POST /api/v1/attendance-compliance/scan/same-device 同设备检测
  POST /api/v1/attendance-compliance/scan/overtime    加班超时检测
  GET  /api/v1/attendance-compliance/violations       违规记录列表
  GET  /api/v1/attendance-compliance/violations/{id}  违规详情
  PUT  /api/v1/attendance-compliance/violations/{id}/confirm 确认违规
  PUT  /api/v1/attendance-compliance/violations/{id}/dismiss 驳回
  GET  /api/v1/attendance-compliance/stats            合规统计

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.attendance_compliance_service import (
    AttendanceComplianceLogService,
    check_gps_anomaly,
    check_overtime_compliance,
    check_same_device,
)

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/attendance-compliance",
    tags=["attendance-compliance"],
)


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID", "")
    if not tid:
        tid = request.query_params.get("tenant_id", "")
    return tid


# ── Pydantic Models ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    date: str = Field(default_factory=lambda: date.today().isoformat(), description="检测日期 YYYY-MM-DD")
    store_id: Optional[str] = Field(default=None, description="门店ID")


class GpsScanRequest(BaseModel):
    employee_id: str
    clock_location: dict = Field(description="打卡GPS坐标 {lat, lng}")


class SameDeviceScanRequest(BaseModel):
    employee_id: str
    device_fingerprint: str
    clock_time: str


class OvertimeScanRequest(BaseModel):
    store_id: str
    week_start: str = Field(description="周起始日 YYYY-MM-DD")


class ConfirmRequest(BaseModel):
    confirmer_id: str


class DismissRequest(BaseModel):
    reason: str


# ── 路由 ─────────────────────────────────────────────────────────────────────

@router.post("/scan")
async def scan_full(
    body: ScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """运行全部合规检测"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.run_full_scan(body.date, body.store_id)
    return {"ok": True, "data": result}


@router.post("/scan/gps")
async def scan_gps(
    body: GpsScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """GPS异常扫描（单人实时检测）"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    result = await check_gps_anomaly(db, tid, body.employee_id, body.clock_location)
    return {"ok": True, "data": result}


@router.post("/scan/same-device")
async def scan_same_device(
    body: SameDeviceScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """同设备检测"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    result = await check_same_device(db, tid, body.employee_id, body.device_fingerprint, body.clock_time)
    return {"ok": True, "data": result}


@router.post("/scan/overtime")
async def scan_overtime(
    body: OvertimeScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """加班超时检测"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    result = await check_overtime_compliance(db, tid, body.store_id, body.week_start)
    return {"ok": True, "data": result}


@router.get("/violations")
async def list_violations(
    request: Request,
    store_id: Optional[str] = Query(None),
    violation_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """违规记录列表"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.list_violations(
        store_id=store_id,
        violation_type=violation_type,
        status=status,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.get("/violations/{log_id}")
async def get_violation(
    log_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """违规详情"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.get_violation(log_id)
    if not result:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "记录不存在"}}
    return {"ok": True, "data": result}


@router.put("/violations/{log_id}/confirm")
async def confirm_violation(
    log_id: str,
    body: ConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """确认违规"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.confirm_violation(log_id, body.confirmer_id)
    return result


@router.put("/violations/{log_id}/dismiss")
async def dismiss_violation(
    log_id: str,
    body: DismissRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """驳回/申诉"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.dismiss_violation(log_id, body.reason)
    return result


@router.get("/stats")
async def compliance_stats(
    request: Request,
    month: Optional[str] = Query(None, description="月份 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    """合规统计"""
    tid = _tenant_id(request)
    if not tid:
        return {"ok": False, "error": {"code": "MISSING_TENANT", "message": "缺少 X-Tenant-ID"}}

    svc = AttendanceComplianceLogService(db, tid)
    result = await svc.get_compliance_stats(month)
    return {"ok": True, "data": result}
