"""报表配置化引擎API路由 — S5 无代码报表构建

GET    /api/v1/analytics/report-builder/templates               — 模板列表
GET    /api/v1/analytics/report-builder/templates/{template_id} — 模板详情
POST   /api/v1/analytics/report-builder/templates               — 创建模板
PUT    /api/v1/analytics/report-builder/templates/{template_id} — 更新模板
POST   /api/v1/analytics/report-builder/execute                 — 执行报表
POST   /api/v1/analytics/report-builder/instances               — 创建实例
GET    /api/v1/analytics/report-builder/instances               — 实例列表
PUT    /api/v1/analytics/report-builder/instances/{id}/schedule — 设置定时
POST   /api/v1/analytics/report-builder/export                  — 导出报表
POST   /api/v1/analytics/report-builder/subscribe               — 订阅
GET    /api/v1/analytics/report-builder/data-sources            — 数据源列表
GET    /api/v1/analytics/report-builder/dimensions/{source}     — 维度选项
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.report_builder_service import (
    DataSourceNotAllowedError,
    InstanceNotFoundError,
    ReportBuilderService,
    ReportBuilderValidationError,
    TemplateNotFoundError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/report-builder", tags=["report-builder"])

_service = ReportBuilderService()


# ─── DB 依赖 ────────────────────────────────────────────────────────────────


async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ─── Pydantic 模型 ───────────────────────────────────────────────────────────


class TemplateCreateRequest(BaseModel):
    """创建报表模板请求"""
    template_code: str = Field(..., max_length=50, description="模板编码(唯一)")
    template_name: str = Field(..., max_length=200, description="模板名称")
    category: str = Field(default="custom", description="分类")
    description: Optional[str] = Field(default=None, description="描述")
    data_source: str = Field(..., max_length=100, description="数据源")
    dimensions: list[dict[str, Any]] = Field(default_factory=list, description="维度定义")
    measures: list[dict[str, Any]] = Field(default_factory=list, description="度量定义")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="筛选器定义")
    default_sort: Optional[dict[str, str]] = Field(default=None, description="默认排序")
    chart_type: Optional[str] = Field(default=None, description="图表类型")
    layout: Optional[dict[str, Any]] = Field(default=None, description="布局配置")


class TemplateUpdateRequest(BaseModel):
    """更新报表模板请求"""
    template_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    data_source: Optional[str] = None
    dimensions: Optional[list[dict[str, Any]]] = None
    measures: Optional[list[dict[str, Any]]] = None
    filters: Optional[list[dict[str, Any]]] = None
    default_sort: Optional[dict[str, str]] = None
    chart_type: Optional[str] = None
    layout: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class ExecuteRequest(BaseModel):
    """执行报表请求"""
    template_id: str = Field(..., description="模板ID")
    filters: Optional[dict[str, Any]] = Field(default=None, description="筛选条件")
    dimensions: Optional[list[str]] = Field(default=None, description="维度列")
    measures: Optional[list[str]] = Field(default=None, description="度量列")
    sort: Optional[dict[str, str]] = Field(default=None, description="排序 {key, direction}")
    page: int = Field(default=1, ge=1, description="页码")
    size: int = Field(default=100, ge=1, le=5000, description="每页条数")


class InstanceCreateRequest(BaseModel):
    """创建报表实例请求"""
    template_id: str = Field(..., description="模板ID")
    instance_name: str = Field(..., max_length=200, description="实例名称")
    custom_filters: Optional[dict[str, Any]] = Field(default=None, description="自定义筛选")
    custom_dimensions: Optional[list[str]] = Field(default=None, description="自定义维度")
    custom_measures: Optional[list[str]] = Field(default=None, description="自定义度量")
    created_by: str = Field(..., description="创建者ID")


class ScheduleRequest(BaseModel):
    """设置定时推送请求"""
    schedule_type: str = Field(default="none", description="定时类型: none/daily/weekly/monthly")
    config: Optional[dict[str, Any]] = Field(default=None, description="定时配置")
    recipients: Optional[list[dict[str, Any]]] = Field(default=None, description="接收人列表")


class ExportRequest(BaseModel):
    """导出报表请求"""
    template_id: str = Field(..., description="模板ID")
    filters: Optional[dict[str, Any]] = Field(default=None, description="筛选条件")
    export_format: str = Field(default="csv", description="导出格式: pdf/excel/csv")
    requested_by: Optional[str] = Field(default=None, description="请求者ID")


class SubscribeRequest(BaseModel):
    """订阅请求"""
    instance_id: str = Field(..., description="实例ID")
    subscriber_id: str = Field(..., description="订阅人ID")
    channel: str = Field(..., description="渠道: email/wechat/dingtalk/im")


# ─── 模板接口 ────────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(None, description="按分类筛选"),
    search: Optional[str] = Query(None, description="搜索关键字"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取报表模板列表（系统预置 + 租户自定义）"""
    try:
        result = await _service.list_templates(
            db, x_tenant_id,
            category=category,
            search=search,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取模板详情"""
    try:
        result = await _service.get_template(db, x_tenant_id, template_id)
        return {"ok": True, "data": result}
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/templates")
async def create_template(
    body: TemplateCreateRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建自定义报表模板"""
    try:
        result = await _service.create_template(
            db, x_tenant_id,
            body.model_dump(exclude_none=True),
        )
        return {"ok": True, "data": result}
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DataSourceNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """更新报表模板（仅租户自定义模板可修改）"""
    try:
        result = await _service.update_template(
            db, x_tenant_id, template_id,
            body.model_dump(exclude_none=True),
        )
        return {"ok": True, "data": result}
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 报表执行 ────────────────────────────────────────────────────────────────


@router.post("/execute")
async def execute_report(
    body: ExecuteRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """执行报表查询（动态SQL生成）"""
    try:
        result = await _service.execute_report(
            db, x_tenant_id, body.template_id,
            filters=body.filters,
            dimensions=body.dimensions,
            measures=body.measures,
            sort=body.sort,
            page=body.page,
            size=body.size,
        )
        return {"ok": True, "data": result}
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ReportBuilderValidationError, DataSourceNotAllowedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 实例接口 ────────────────────────────────────────────────────────────────


@router.post("/instances")
async def create_instance(
    body: InstanceCreateRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """创建报表实例（保存筛选条件组合）"""
    try:
        result = await _service.create_instance(
            db, x_tenant_id, body.template_id,
            body.model_dump(),
        )
        return {"ok": True, "data": result}
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/instances")
async def list_instances(
    template_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取报表实例列表"""
    result = await _service.list_instances(
        db, x_tenant_id,
        template_id=template_id,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.put("/instances/{instance_id}/schedule")
async def schedule_instance(
    instance_id: str,
    body: ScheduleRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """设置报表实例定时推送"""
    try:
        result = await _service.schedule_instance(
            db, x_tenant_id, instance_id,
            body.model_dump(),
        )
        return {"ok": True, "data": result}
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 导出接口 ────────────────────────────────────────────────────────────────


@router.post("/export")
async def export_report(
    body: ExportRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> Response:
    """导出报表为 PDF/Excel/CSV"""
    try:
        result = await _service.export_report(
            db, x_tenant_id, body.template_id,
            filters=body.filters,
            export_format=body.export_format,
            requested_by=body.requested_by or x_tenant_id,
        )

        content = result["content"]
        if isinstance(content, str):
            content = content.encode("utf-8-sig")  # BOM for Chinese Excel compatibility

        return Response(
            content=content,
            media_type=result["content_type"],
            headers={
                "Content-Disposition": f'attachment; filename="{result["file_name"]}"',
                "X-Export-Id": result["export_id"],
                "X-Rows-Exported": str(result["rows_exported"]),
            },
        )
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 订阅接口 ────────────────────────────────────────────────────────────────


@router.post("/subscribe")
async def subscribe(
    body: SubscribeRequest,
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """订阅报表实例推送"""
    try:
        result = await _service.subscribe(
            db, x_tenant_id,
            body.instance_id,
            body.subscriber_id,
            body.channel,
        )
        return {"ok": True, "data": result}
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ─── 数据源接口 ──────────────────────────────────────────────────────────────


@router.get("/data-sources")
async def get_data_sources() -> dict[str, Any]:
    """获取可用数据源列表"""
    sources = await _service.get_data_sources()
    return {"ok": True, "data": sources}


@router.get("/dimensions/{source}")
async def get_dimension_options(
    source: str,
    dimension_key: str = Query(..., description="维度字段名"),
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict[str, Any]:
    """获取维度可选值"""
    try:
        options = await _service.get_dimension_options(
            db, x_tenant_id, source, dimension_key,
        )
        return {"ok": True, "data": options}
    except DataSourceNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReportBuilderValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
