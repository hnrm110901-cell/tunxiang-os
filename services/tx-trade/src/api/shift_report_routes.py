"""班次KDS生产报表 API

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。

路由前缀：/api/v1/shifts/{store_id}
- GET  /shifts/{store_id}/config           班次配置列表
- POST /shifts/{store_id}/config           创建班次配置
- GET  /shifts/{store_id}/report           班次报表 (?date=&shift_id=)
- GET  /shifts/{store_id}/trend            趋势 (?shift_id=&days=)
- GET  /shifts/{store_id}/operators        厨师绩效 (?date=&shift_id=)
- GET  /shifts/{store_id}/export           导出CSV (?date=&shift_id=)
"""

import csv
import io
from datetime import date, time
from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.shift_report import ShiftReportService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/shifts", tags=["shift-report"])


# ─── 通用辅助 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    return {"ok": False, "data": None, "error": {"message": msg, "code": code}}


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────


class CreateShiftConfigReq(BaseModel):
    shift_name: str = Field(..., min_length=1, max_length=50, description="班次名称")
    start_time: str = Field(..., description="开始时间 HH:MM，如 11:00")
    end_time: str = Field(..., description="结束时间 HH:MM，如 14:00")
    color: str = Field(default="#FF6B35", max_length=10, description="前端显示色")


def _parse_time(value: str) -> time:
    """解析 HH:MM 格式的时间字符串。"""
    parts = value.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=422, detail=f"时间格式错误，期望 HH:MM，实际: {value!r}")
    try:
        return time(hour=int(parts[0]), minute=int(parts[1]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"时间格式错误: {exc}") from exc


def _config_to_dict(config) -> dict:
    return {
        "id": str(config.id),
        "store_id": str(config.store_id),
        "shift_name": config.shift_name,
        "start_time": config.start_time.strftime("%H:%M"),
        "end_time": config.end_time.strftime("%H:%M"),
        "color": config.color,
        "is_active": config.is_active,
        "created_at": config.created_at.isoformat() if config.created_at else None,
    }


def _summary_to_dict(summary) -> dict:
    return {
        "shift_id": summary.shift_id,
        "shift_name": summary.shift_name,
        "date": summary.date,
        "total_tasks": summary.total_tasks,
        "finished_tasks": summary.finished_tasks,
        "avg_duration_seconds": round(summary.avg_duration_seconds, 1),
        "timeout_count": summary.timeout_count,
        "remake_count": summary.remake_count,
        "timeout_rate": round(summary.timeout_rate * 100, 1),
        "remake_rate": round(summary.remake_rate * 100, 1),
        "dept_stats": [_dept_to_dict(d) for d in summary.dept_stats],
        "operator_stats": [_op_to_dict(o) for o in summary.operator_stats],
    }


def _dept_to_dict(dept) -> dict:
    return {
        "dept_id": dept.dept_id,
        "dept_name": dept.dept_name,
        "total_tasks": dept.total_tasks,
        "finished_tasks": dept.finished_tasks,
        "avg_duration_seconds": round(dept.avg_duration_seconds, 1),
        "timeout_count": dept.timeout_count,
        "remake_count": dept.remake_count,
        "timeout_rate": round(dept.timeout_rate * 100, 1),
        "remake_rate": round(dept.remake_rate * 100, 1),
    }


def _op_to_dict(op) -> dict:
    return {
        "operator_id": op.operator_id,
        "operator_name": op.operator_name,
        "total_tasks": op.total_tasks,
        "finished_tasks": op.finished_tasks,
        "avg_duration_seconds": round(op.avg_duration_seconds, 1),
        "remake_count": op.remake_count,
        "remake_rate": round(op.remake_rate * 100, 1),
    }


# ─── 班次配置接口 ────────────────────────────────────────────────────────────


@router.get("/{store_id}/config")
async def list_shift_configs(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
) -> dict:
    """获取门店所有班次配置"""
    tenant_id = _get_tenant_id(request)
    svc = ShiftReportService(db, tenant_id)
    configs = await svc.list_shift_configs(store_id)
    return _ok([_config_to_dict(c) for c in configs])


@router.post("/{store_id}/config")
async def create_shift_config(
    store_id: str,
    body: CreateShiftConfigReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
) -> dict:
    """创建班次配置"""
    tenant_id = _get_tenant_id(request)
    start_time = _parse_time(body.start_time)
    end_time = _parse_time(body.end_time)
    svc = ShiftReportService(db, tenant_id)
    config = await svc.create_shift_config(
        store_id=store_id,
        shift_name=body.shift_name,
        start_time=start_time,
        end_time=end_time,
        color=body.color,
    )
    return _ok(_config_to_dict(config))


# ─── 报表接口 ────────────────────────────────────────────────────────────────


@router.get("/{store_id}/report")
async def get_shift_report(
    store_id: str,
    request: Request,
    date_str: str = Query(..., alias="date", description="日期 YYYY-MM-DD"),
    shift_id: str = Query(..., description="班次ID"),
    db: AsyncSession = Depends(_get_db_session),
) -> dict:
    """获取班次 KDS 生产报表"""
    tenant_id = _get_tenant_id(request)
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式错误: {exc}") from exc

    svc = ShiftReportService(db, tenant_id)
    summary = await svc.get_shift_summary(store_id, target_date, shift_id)
    return _ok(_summary_to_dict(summary))


@router.get("/{store_id}/trend")
async def get_shift_trend(
    store_id: str,
    request: Request,
    shift_id: str = Query(..., description="班次ID"),
    days: int = Query(default=7, ge=1, le=90, description="近N天"),
    db: AsyncSession = Depends(_get_db_session),
) -> dict:
    """获取近N天同班次趋势"""
    tenant_id = _get_tenant_id(request)
    svc = ShiftReportService(db, tenant_id)
    summaries = await svc.get_shift_trend(store_id, shift_id, days=days)
    return _ok([_summary_to_dict(s) for s in summaries])


@router.get("/{store_id}/operators")
async def get_operator_performance(
    store_id: str,
    request: Request,
    date_str: str = Query(..., alias="date", description="日期 YYYY-MM-DD"),
    shift_id: Optional[str] = Query(default=None, description="班次ID（可选）"),
    db: AsyncSession = Depends(_get_db_session),
) -> dict:
    """获取厨师个人绩效"""
    tenant_id = _get_tenant_id(request)
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式错误: {exc}") from exc

    svc = ShiftReportService(db, tenant_id)
    operators = await svc.get_operator_performance(store_id, target_date, shift_id)
    return _ok([_op_to_dict(o) for o in operators])


@router.get("/{store_id}/export")
async def export_shift_report(
    store_id: str,
    request: Request,
    date_str: str = Query(..., alias="date", description="日期 YYYY-MM-DD"),
    shift_id: str = Query(..., description="班次ID"),
    fmt: str = Query(default="csv", alias="format", description="导出格式（当前仅支持 csv）"),
    db: AsyncSession = Depends(_get_db_session),
) -> StreamingResponse:
    """导出班次报表（返回 CSV；PDF 后续实现）"""
    tenant_id = _get_tenant_id(request)
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式错误: {exc}") from exc

    svc = ShiftReportService(db, tenant_id)
    summary = await svc.get_shift_summary(store_id, target_date, shift_id)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # 摘要行
    writer.writerow(["班次报表"])
    writer.writerow(["班次名称", summary.shift_name])
    writer.writerow(["日期", summary.date])
    writer.writerow(["总单量", summary.total_tasks])
    writer.writerow(["完成单量", summary.finished_tasks])
    writer.writerow(["平均出品时间(秒)", round(summary.avg_duration_seconds, 1)])
    writer.writerow(["超时率(%)", round(summary.timeout_rate * 100, 1)])
    writer.writerow(["重做率(%)", round(summary.remake_rate * 100, 1)])
    writer.writerow([])

    # 档口对比
    writer.writerow(["档口对比"])
    writer.writerow(["档口ID", "档口名称", "总单量", "完成单量", "平均出品时间(秒)", "超时率(%)", "重做率(%)"])
    for dept in summary.dept_stats:
        writer.writerow(
            [
                dept.dept_id,
                dept.dept_name,
                dept.total_tasks,
                dept.finished_tasks,
                round(dept.avg_duration_seconds, 1),
                round(dept.timeout_rate * 100, 1),
                round(dept.remake_rate * 100, 1),
            ]
        )
    writer.writerow([])

    # 厨师绩效
    writer.writerow(["厨师绩效"])
    writer.writerow(["厨师ID", "姓名", "总单量", "完成单量", "平均出品时间(秒)", "重做率(%)"])
    for op in summary.operator_stats:
        writer.writerow(
            [
                op.operator_id,
                op.operator_name,
                op.total_tasks,
                op.finished_tasks,
                round(op.avg_duration_seconds, 1),
                round(op.remake_rate * 100, 1),
            ]
        )

    buf.seek(0)
    filename = f"shift_report_{summary.shift_name}_{summary.date}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
