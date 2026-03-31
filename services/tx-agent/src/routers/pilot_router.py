"""试点验证闭环 API 路由 — /api/v1/pilots

GET    /pilots                     — 试点列表（支持 status 过滤）
POST   /pilots                     — 创建试点
GET    /pilots/{id}                — 试点详情
POST   /pilots/{id}/activate       — 激活试点
POST   /pilots/{id}/pause          — 暂停试点
GET    /pilots/{id}/metrics        — 指标时序数据
POST   /pilots/{id}/review         — 生成复盘报告
GET    /pilots/{id}/review         — 获取最新复盘报告
POST   /pilots/{id}/execute        — 执行复盘建议（rollout/abort/extend）
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/pilots", tags=["pilot-tracking"])


# ---------------------------------------------------------------------------
# 依赖项 / 工具函数
# ---------------------------------------------------------------------------

def _require_tenant(x_tenant_id: Optional[str]) -> uuid.UUID:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID format")


def _parse_pilot_id(pilot_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(pilot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pilot_id format")


def _get_db():
    """获取数据库会话（在实际项目中通过 FastAPI Depends 注入）"""
    raise NotImplementedError("请通过 FastAPI Depends 注入数据库会话")


def _get_pilot_service(db: Any = None) -> Any:
    """获取 PilotService 实例"""
    from ..services.pilot_service import PilotService
    return PilotService(db_session=db)


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------

class SuccessCriterionRequest(BaseModel):
    metric: str
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    threshold: float
    description: str = ""


class StoreRefRequest(BaseModel):
    store_id: str
    store_name: str


class PilotItemRequest(BaseModel):
    item_type: Literal["dish", "ingredient", "price"]
    item_ref_id: Optional[uuid.UUID] = None
    item_name: str
    action: Literal["add", "remove", "modify", "price_change"]
    action_config: dict = Field(default_factory=dict)


class CreatePilotRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200, description="试点名称")
    description: Optional[str] = None
    pilot_type: Literal["new_dish", "new_ingredient", "new_combo", "price_change", "menu_restructure"]
    recommendation_source: Literal["intel_report", "competitor_watch", "trend_signal", "manual"] = "manual"
    source_ref_id: Optional[uuid.UUID] = None
    hypothesis: Optional[str] = None
    target_stores: list[StoreRefRequest] = Field(..., min_length=1, description="至少1家目标门店")
    control_stores: Optional[list[StoreRefRequest]] = None
    start_date: date
    end_date: date
    success_criteria: list[SuccessCriterionRequest] = Field(default_factory=list)
    items: list[PilotItemRequest] = Field(default_factory=list)


class ExecuteRecommendationRequest(BaseModel):
    recommendation: Literal["rollout", "abort", "extend"]
    extend_days: int = Field(default=14, ge=1, le=90, description="仅 extend 时生效")


class GenerateReviewRequest(BaseModel):
    review_type: Literal["interim", "final"] = "interim"


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data}


def _err(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"ok": False, "error": msg})


# ---------------------------------------------------------------------------
# 路由实现
# ---------------------------------------------------------------------------

@router.get("", summary="试点列表")
async def list_pilots(
    status: Optional[str] = Query(None, description="状态过滤: draft/active/paused/completed/cancelled"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    svc = _get_pilot_service(db)
    result = await svc.list_pilots(tenant_id, status=status, page=page, size=size)
    return _ok(result)


@router.post("", summary="创建试点", status_code=201)
async def create_pilot(
    body: CreatePilotRequest,
    x_tenant_id: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    created_by = uuid.UUID(x_user_id) if x_user_id else None

    from ..services.pilot_service import PilotProgramCreate, StoreRef, SuccessCriterion, PilotItemCreate
    pilot_data = PilotProgramCreate(
        name=body.name,
        description=body.description,
        pilot_type=body.pilot_type,
        recommendation_source=body.recommendation_source,
        source_ref_id=body.source_ref_id,
        hypothesis=body.hypothesis,
        target_stores=[StoreRef(store_id=s.store_id, store_name=s.store_name) for s in body.target_stores],
        control_stores=[StoreRef(store_id=s.store_id, store_name=s.store_name) for s in body.control_stores] if body.control_stores else None,
        start_date=body.start_date,
        end_date=body.end_date,
        success_criteria=[
            SuccessCriterion(metric=c.metric, operator=c.operator, threshold=c.threshold, description=c.description)
            for c in body.success_criteria
        ],
        items=[
            PilotItemCreate(
                item_type=i.item_type, item_ref_id=i.item_ref_id,
                item_name=i.item_name, action=i.action, action_config=i.action_config,
            )
            for i in body.items
        ],
    )

    svc = _get_pilot_service(db)
    try:
        result = await svc.create_pilot(tenant_id, pilot_data, created_by=created_by)
    except ValueError as e:
        _err(str(e))
    return _ok(result)


@router.get("/{pilot_id}", summary="试点详情")
async def get_pilot(
    pilot_id: str,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)

    # 拉取主记录
    program = await svc._get_program(tenant_id, pid)
    if program is None:
        raise HTTPException(status_code=404, detail="试点不存在")

    # 附带 items
    if db is not None:
        items = await db.fetch_all(
            "SELECT * FROM pilot_items WHERE tenant_id = :t AND pilot_program_id = :p ORDER BY created_at",
            {"t": str(tenant_id), "p": str(pid)},
        )
        program["items"] = [dict(i) for i in items]

    return _ok(program)


@router.post("/{pilot_id}/activate", summary="激活试点")
async def activate_pilot(
    pilot_id: str,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)
    try:
        result = await svc.activate_pilot(tenant_id, pid)
    except ValueError as e:
        _err(str(e))
    return _ok(result)


@router.post("/{pilot_id}/pause", summary="暂停试点")
async def pause_pilot(
    pilot_id: str,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)
    try:
        result = await svc.pause_pilot(tenant_id, pid)
    except ValueError as e:
        _err(str(e))
    return _ok(result)


@router.get("/{pilot_id}/metrics", summary="指标时序数据")
async def get_pilot_metrics(
    pilot_id: str,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)

    sd: Optional[date] = None
    ed: Optional[date] = None
    if start_date:
        try:
            sd = date.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid start_date, use YYYY-MM-DD")
    if end_date:
        try:
            ed = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid end_date, use YYYY-MM-DD")

    svc = _get_pilot_service(db)
    result = await svc.get_metrics_timeseries(tenant_id, pid, sd, ed)
    return _ok(result)


@router.post("/{pilot_id}/review", summary="生成复盘报告", status_code=201)
async def generate_review(
    pilot_id: str,
    body: GenerateReviewRequest,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)
    try:
        result = await svc.generate_pilot_review(tenant_id, pid, review_type=body.review_type)
    except ValueError as e:
        _err(str(e), status=404)
    return _ok(result)


@router.get("/{pilot_id}/review", summary="获取最新复盘报告")
async def get_latest_review(
    pilot_id: str,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)
    result = await svc.get_latest_review(tenant_id, pid)
    if result is None:
        raise HTTPException(status_code=404, detail="该试点尚无复盘报告")
    return _ok(result)


@router.post("/{pilot_id}/execute", summary="执行复盘建议")
async def execute_recommendation(
    pilot_id: str,
    body: ExecuteRecommendationRequest,
    x_tenant_id: Optional[str] = Header(None),
    db: Any = None,
):
    tenant_id = _require_tenant(x_tenant_id)
    pid = _parse_pilot_id(pilot_id)
    svc = _get_pilot_service(db)
    try:
        result = await svc.execute_recommendation(
            tenant_id, pid,
            recommendation=body.recommendation,
            extend_days=body.extend_days,
        )
    except ValueError as e:
        _err(str(e))
    return _ok(result)
