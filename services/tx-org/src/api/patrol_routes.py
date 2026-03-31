"""巡店管理 API 路由

端点列表：
  POST /api/v1/patrol/templates              创建巡检模板
  GET  /api/v1/patrol/templates              模板列表
  POST /api/v1/patrol/records                开始巡检
  PUT  /api/v1/patrol/records/{id}/submit    提交巡检结果
  GET  /api/v1/patrol/rankings               门店排名
  GET  /api/v1/patrol/issues                 整改任务列表
  POST /api/v1/patrol/issues                 手动创建整改任务
  PUT  /api/v1/patrol/issues/{id}            更新整改状态

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.ontology.src.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.patrol_service import (
    VALID_CATEGORIES,
    VALID_ISSUE_STATUSES,
    VALID_ITEM_TYPES,
    VALID_SEVERITIES,
    PatrolService,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["patrol"])


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


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class TemplateItemReq(BaseModel):
    item_name: str = Field(..., max_length=200, description="检查项名称")
    item_type: str = Field(default="score", description="check/score/photo/text")
    max_score: float = Field(default=10.0, ge=0, description="满分值")
    is_required: bool = Field(default=True, description="是否必填")
    sort_order: int = Field(default=0, description="排序序号")


class CreateTemplateReq(BaseModel):
    brand_id: str | None = Field(None, description="品牌ID，为空则适用所有品牌")
    name: str = Field(..., max_length=200, description="模板名称")
    description: str | None = Field(None, description="模板描述")
    category: str = Field(..., description="safety/hygiene/service/equipment")
    items: list[TemplateItemReq] = Field(default_factory=list, description="检查项列表")


class StartPatrolReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    template_id: str = Field(..., description="巡检模板ID")
    patroller_id: str = Field(..., description="巡检员工ID")
    patrol_date: date | None = Field(None, description="巡检日期，默认今日")


class SubmitItemReq(BaseModel):
    template_item_id: str = Field(..., description="模板检查项ID")
    actual_score: float | None = Field(None, ge=0, description="实际得分")
    photo_urls: list[str] = Field(default_factory=list, description="现场照片URL列表")
    notes: str | None = Field(None, description="备注")


class SubmitPatrolReq(BaseModel):
    items: list[SubmitItemReq] = Field(..., min_length=1, description="检查项结果列表")


class CreateIssueReq(BaseModel):
    record_id: str | None = Field(None, description="关联巡检记录ID（可选）")
    store_id: str = Field(..., description="门店ID")
    item_name: str = Field(..., max_length=200, description="检查项名称")
    severity: str = Field(..., description="critical/major/minor")
    description: str | None = Field(None, description="问题描述")
    photo_urls: list[str] = Field(default_factory=list, description="现场照片URL列表")
    initiator_id: str | None = Field(None, description="发起人员工ID")


class UpdateIssueReq(BaseModel):
    status: str = Field(..., description="open/in_progress/resolved/closed")
    resolution_notes: str | None = Field(None, description="整改说明")


# ── 模板端点 ──────────────────────────────────────────────────────────────────


@router.post("/patrol/templates")
async def create_template(
    req: CreateTemplateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/patrol/templates — 创建巡检模板"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await PatrolService.create_template(
            tenant_id=tenant_id,
            brand_id=req.brand_id,
            name=req.name,
            description=req.description,
            category=req.category,
            items=[item.model_dump() for item in req.items],
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/patrol/templates")
async def list_templates(
    request: Request,
    brand_id: str | None = Query(None, description="按品牌过滤"),
    category: str | None = Query(None, description="按类别过滤：safety/hygiene/service/equipment"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/patrol/templates — 巡检模板列表"""
    tenant_id = _get_tenant_id(request)
    result = await PatrolService.list_templates(
        tenant_id=tenant_id,
        brand_id=brand_id,
        category=category,
        page=page,
        size=size,
        db=db,
    )
    return _ok(result)


# ── 巡检记录端点 ──────────────────────────────────────────────────────────────


@router.post("/patrol/records")
async def start_patrol(
    req: StartPatrolReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/patrol/records — 开始巡检，创建巡检记录"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await PatrolService.start_patrol(
            tenant_id=tenant_id,
            store_id=req.store_id,
            template_id=req.template_id,
            patroller_id=req.patroller_id,
            patrol_date=req.patrol_date,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/patrol/records/{record_id}/submit")
async def submit_patrol(
    record_id: str,
    req: SubmitPatrolReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/patrol/records/{id}/submit — 提交巡检结果"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await PatrolService.submit_patrol(
            tenant_id=tenant_id,
            record_id=record_id,
            items=[item.model_dump() for item in req.items],
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 排名端点 ──────────────────────────────────────────────────────────────────


@router.get("/patrol/rankings")
async def get_store_patrol_ranking(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="统计时间窗口（天）"),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/patrol/rankings — 门店巡检排名（按平均分降序）"""
    tenant_id = _get_tenant_id(request)
    result = await PatrolService.get_store_patrol_ranking(
        tenant_id=tenant_id,
        days=days,
        db=db,
    )
    return _ok({"items": result, "total": len(result)})


# ── 整改任务端点 ──────────────────────────────────────────────────────────────


@router.get("/patrol/issues")
async def list_issues(
    request: Request,
    store_id: str | None = Query(None, description="按门店过滤"),
    status: str | None = Query(None, description="open/in_progress/resolved/closed"),
    severity: str | None = Query(None, description="critical/major/minor"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """GET /api/v1/patrol/issues — 整改任务列表"""
    tenant_id = _get_tenant_id(request)
    result = await PatrolService.list_issues(
        tenant_id=tenant_id,
        store_id=store_id,
        status=status,
        severity=severity,
        page=page,
        size=size,
        db=db,
    )
    return _ok(result)


@router.post("/patrol/issues")
async def create_issue(
    req: CreateIssueReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """POST /api/v1/patrol/issues — 手动创建整改任务"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await PatrolService.create_issue(
            tenant_id=tenant_id,
            record_id=req.record_id,
            store_id=req.store_id,
            item_name=req.item_name,
            severity=req.severity,
            description=req.description,
            photo_urls=req.photo_urls,
            initiator_id=req.initiator_id,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/patrol/issues/{issue_id}")
async def update_issue(
    issue_id: str,
    req: UpdateIssueReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """PUT /api/v1/patrol/issues/{id} — 更新整改任务状态"""
    tenant_id = _get_tenant_id(request)
    try:
        result = await PatrolService.update_issue_status(
            tenant_id=tenant_id,
            issue_id=issue_id,
            new_status=req.status,
            resolution_notes=req.resolution_notes,
            db=db,
        )
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
