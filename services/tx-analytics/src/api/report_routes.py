"""通用报表API路由

GET  /api/v1/reports                        — 报表目录
GET  /api/v1/reports/{report_id}            — 报表元数据
POST /api/v1/reports/{report_id}/execute    — 执行报表
GET  /api/v1/reports/{report_id}/export     — 导出报表
POST /api/v1/reports/schedule               — 创建定时报表
GET  /api/v1/reports/schedules              — 定时列表
"""
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services.report_engine import (
    ExportFormat,
    ReportEngine,
    ReportInactiveError,
    ReportNotFoundError,
    ReportParamError,
    ReportRenderer,
    ReportScheduler,
    SortDirection,
)
from ..services.report_registry import create_default_registry

# ─── 初始化引擎 ───

_registry = create_default_registry()
_engine = ReportEngine(registry=_registry)
_renderer = ReportRenderer()
_scheduler = ReportScheduler(engine=_engine, renderer=_renderer)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


# ─── 请求/响应模型 ───

class ExecuteRequest(BaseModel):
    """报表执行请求"""
    params: dict[str, Any] = Field(default_factory=dict, description="查询参数")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=100, ge=1, le=1000, description="每页条数")
    sort_by: Optional[str] = Field(default=None, description="排序字段")
    sort_dir: Optional[str] = Field(default=None, description="排序方向: asc/desc")


class ScheduleRequest(BaseModel):
    """定时报表请求"""
    report_id: str
    cron_expression: str = Field(..., description="cron表达式，如 '0 8 * * *'")
    recipients: list[str] = Field(..., description="接收人列表")
    channel: str = Field(default="webhook", description="推送渠道: email/webhook/wechat")
    params: dict[str, Any] = Field(default_factory=dict)
    export_format: str = Field(default="json", description="导出格式: json/csv/excel")


# ─── 辅助函数 ───

def _require_tenant(tenant_id: Optional[str]) -> str:
    """校验 tenant_id 必填"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return tenant_id


# ─── 路由 ───

@router.get("")
async def api_list_reports(
    category: Optional[str] = Query(None, description="按分类过滤: revenue/dish/audit/margin/commission/finance/member/supply/operation"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """报表目录 — 列出所有可用报表"""
    tenant_id = _require_tenant(x_tenant_id)
    reports = await _engine.list_reports(category=category, tenant_id=tenant_id)
    return {"ok": True, "data": {"items": reports, "total": len(reports)}}


@router.get("/schedules")
async def api_list_schedules(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """定时报表列表"""
    tenant_id = _require_tenant(x_tenant_id)
    schedules = await _scheduler.get_schedule_list(tenant_id)
    return {"ok": True, "data": {"items": schedules, "total": len(schedules)}}


@router.get("/{report_id}")
async def api_report_metadata(
    report_id: str,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """报表元数据 — 获取报表定义详情"""
    _require_tenant(x_tenant_id)
    try:
        metadata = await _engine.get_report_metadata(report_id)
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    return {"ok": True, "data": metadata}


@router.post("/{report_id}/execute")
async def api_execute_report(
    report_id: str,
    body: ExecuteRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """执行报表 — 带参数查询并返回结果

    请求体示例:
    ```json
    {
        "params": {"store_id": "store_001", "target_date": "2026-03-27"},
        "page": 1,
        "page_size": 50,
        "sort_by": "revenue_fen",
        "sort_dir": "desc"
    }
    ```
    """
    tenant_id = _require_tenant(x_tenant_id)

    sort_dir = None
    if body.sort_dir:
        try:
            sort_dir = SortDirection(body.sort_dir)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid sort_dir: {body.sort_dir}, must be 'asc' or 'desc'")

    try:
        result = await _engine.execute_report(
            report_id=report_id,
            params=body.params,
            tenant_id=tenant_id,
            db=None,  # 实际部署时注入真实DB会话
            page=body.page,
            page_size=body.page_size,
            sort_by=body.sort_by,
            sort_dir=sort_dir,
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    except ReportInactiveError:
        raise HTTPException(status_code=403, detail=f"Report is inactive: {report_id}")
    except ReportParamError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True, "data": _renderer.to_json(result)}


@router.get("/{report_id}/export")
async def api_export_report(
    report_id: str,
    format: str = Query("csv", description="导出格式: csv/excel"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    store_id: Optional[str] = Query(None),
    target_date: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """导出报表 — 以CSV或Excel格式下载"""
    tenant_id = _require_tenant(x_tenant_id)

    # 从query params构建参数
    params: dict[str, Any] = {}
    if store_id:
        params["store_id"] = store_id
    if target_date:
        params["target_date"] = target_date
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    try:
        result = await _engine.execute_report(
            report_id=report_id,
            params=params,
            tenant_id=tenant_id,
            db=None,  # 实际部署时注入真实DB会话
            page=1,
            page_size=10000,  # 导出取更多数据
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    except ReportInactiveError:
        raise HTTPException(status_code=403, detail=f"Report is inactive: {report_id}")
    except ReportParamError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if format == "excel":
        try:
            content = _renderer.to_excel(result)
        except ImportError:
            raise HTTPException(status_code=501, detail="Excel export requires openpyxl")
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={report_id}.xlsx"},
        )
    else:
        content = _renderer.to_csv(result)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={report_id}.csv"},
        )


@router.post("/schedule")
async def api_create_schedule(
    body: ScheduleRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    """创建定时报表"""
    tenant_id = _require_tenant(x_tenant_id)

    try:
        export_fmt = ExportFormat(body.export_format)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid export_format: {body.export_format}")

    try:
        config = await _scheduler.schedule_report(
            report_id=body.report_id,
            cron_expression=body.cron_expression,
            recipients=body.recipients,
            channel=body.channel,
            tenant_id=tenant_id,
            db=None,  # 实际部署时注入真实DB会话
            params=body.params,
            export_format=export_fmt,
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail=f"Report not found: {body.report_id}")

    return {
        "ok": True,
        "data": {
            "schedule_id": config.schedule_id,
            "report_id": config.report_id,
            "cron_expression": config.cron_expression,
            "channel": config.channel,
            "is_active": config.is_active,
        },
    }
