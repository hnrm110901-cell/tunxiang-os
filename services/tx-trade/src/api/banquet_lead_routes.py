"""宴会商机漏斗路由（Track D / Sprint R1）

端点：
    POST /api/v1/banquet-leads
        创建商机 → stage=all + CREATED 事件
    POST /api/v1/banquet-leads/{lead_id}/transition
        阶段变更 → STAGE_CHANGED 事件
    POST /api/v1/banquet-leads/{lead_id}/convert
        转预订 → CONVERTED 事件 + 关联 reservation_id
    GET  /api/v1/banquet-leads
        分页查询：?sales_employee_id=&stage=&source_channel=&page=&size=
    GET  /api/v1/banquet-leads/funnel
        漏斗统计：?group_by=sales_employee_id|source_channel
                  &period_start=ISO&period_end=ISO
    GET  /api/v1/banquet-leads/attribution
        渠道归因：?period_start=ISO&period_end=ISO

统一响应：{"ok": bool, "data": {...}, "error": {...}}
统一鉴权：X-Tenant-ID（缺失返回 400）
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared.ontology.src.extensions.banquet_leads import (
    BanquetType,
    LeadStage,
    SourceChannel,
)

from ..repositories.banquet_lead_repo import (
    BanquetLeadRepositoryBase,
    InMemoryBanquetLeadRepository,
)
from ..services.banquet_lead_service import (
    BanquetLeadError,
    BanquetLeadNotFoundError,
    BanquetLeadService,
    InvalidationReasonMissingError,
    InvalidStageTransitionError,
    ReservationIdMissingError,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/banquet-leads", tags=["banquet-lead"])


# ──────────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: str = "BAD_REQUEST") -> dict[str, Any]:
    return {"ok": False, "data": None, "error": {"code": code, "message": msg}}


def _require_tenant(request: Request) -> uuid.UUID:
    raw = getattr(request.state, "tenant_id", None) or request.headers.get(
        "X-Tenant-ID", ""
    )
    if not raw:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID")
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid X-Tenant-ID: {exc}"
        ) from exc


def _optional_store_id(request: Request) -> Optional[uuid.UUID]:
    raw = request.headers.get("X-Store-ID", "")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# 服务依赖注入
# ──────────────────────────────────────────────────────────────────────────

# 进程内默认 repo（生产环境在 main lifespan 中可替换为 SQL 版本）
_default_repo: BanquetLeadRepositoryBase = InMemoryBanquetLeadRepository()


def get_repo() -> BanquetLeadRepositoryBase:
    """Repository provider. 路由测试可通过 app.dependency_overrides 替换。"""
    return _default_repo


def get_service(
    repo: BanquetLeadRepositoryBase = Depends(get_repo),
) -> BanquetLeadService:
    return BanquetLeadService(repo=repo)


# ──────────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────────────────────────────────


class CreateLeadReq(BaseModel):
    customer_id: uuid.UUID = Field(..., description="客户ID（Golden Customer）")
    banquet_type: BanquetType = Field(..., description="宴会类型")
    source_channel: SourceChannel = Field(
        default=SourceChannel.BOOKING_DESK, description="渠道来源"
    )
    sales_employee_id: Optional[uuid.UUID] = Field(
        default=None, description="跟进销售员工ID"
    )
    estimated_amount_fen: int = Field(default=0, ge=0, description="预估金额（分）")
    estimated_tables: int = Field(default=0, ge=0, description="预估桌数")
    scheduled_date: Optional[_date] = Field(default=None, description="预计宴会日期")
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransitionReq(BaseModel):
    next_stage: LeadStage = Field(..., description="目标阶段")
    operator_id: Optional[uuid.UUID] = Field(
        default=None, description="操作人员工ID（审计）"
    )
    invalidation_reason: Optional[str] = Field(
        default=None, max_length=200, description="失效原因（next_stage=invalid 时必填）"
    )


class ConvertReq(BaseModel):
    reservation_id: uuid.UUID = Field(..., description="关联 reservation_id")
    operator_id: Optional[uuid.UUID] = Field(default=None)


# ──────────────────────────────────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────────────────────────────────


@router.post("")
async def create_lead(
    payload: CreateLeadReq,
    request: Request,
    service: BanquetLeadService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    store_id = _optional_store_id(request)
    try:
        lead = await service.create_lead(
            customer_id=payload.customer_id,
            banquet_type=payload.banquet_type,
            source_channel=payload.source_channel,
            sales_employee_id=payload.sales_employee_id,
            estimated_amount_fen=payload.estimated_amount_fen,
            estimated_tables=payload.estimated_tables,
            scheduled_date=payload.scheduled_date,
            tenant_id=tenant_id,
            store_id=store_id,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        return _err(str(exc), code="VALIDATION_ERROR")
    return _ok(lead.model_dump(mode="json"))


@router.post("/{lead_id}/transition")
async def transition(
    lead_id: uuid.UUID,
    payload: TransitionReq,
    request: Request,
    service: BanquetLeadService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        lead = await service.transition_stage(
            lead_id=lead_id,
            next_stage=payload.next_stage,
            operator_id=payload.operator_id,
            tenant_id=tenant_id,
            invalidation_reason=payload.invalidation_reason,
        )
    except BanquetLeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidStageTransitionError, InvalidationReasonMissingError) as exc:
        return _err(str(exc), code=exc.code)
    except BanquetLeadError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(lead.model_dump(mode="json"))


@router.post("/{lead_id}/convert")
async def convert(
    lead_id: uuid.UUID,
    payload: ConvertReq,
    request: Request,
    service: BanquetLeadService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    try:
        lead = await service.convert_to_reservation(
            lead_id=lead_id,
            reservation_id=payload.reservation_id,
            operator_id=payload.operator_id,
            tenant_id=tenant_id,
        )
    except BanquetLeadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        InvalidStageTransitionError,
        ReservationIdMissingError,
        InvalidationReasonMissingError,
    ) as exc:
        return _err(str(exc), code=exc.code)
    except BanquetLeadError as exc:
        return _err(str(exc), code=exc.code)
    return _ok(lead.model_dump(mode="json"))


@router.get("")
async def list_leads(
    request: Request,
    sales_employee_id: Optional[uuid.UUID] = Query(default=None),
    stage: Optional[LeadStage] = Query(default=None),
    source_channel: Optional[SourceChannel] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    repo: BanquetLeadRepositoryBase = Depends(get_repo),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    offset = (page - 1) * size

    # 三条件优先级：sales_employee_id > source_channel > stage
    if sales_employee_id is not None:
        items, total = await repo.list_by_sales_employee(
            tenant_id=tenant_id,
            sales_employee_id=sales_employee_id,
            stage=stage,
            offset=offset,
            limit=size,
        )
    elif source_channel is not None:
        items, total = await repo.list_by_source_channel(
            tenant_id=tenant_id,
            source_channel=source_channel,
            offset=offset,
            limit=size,
        )
    elif stage is not None:
        items, total = await repo.list_by_stage(
            tenant_id=tenant_id,
            stage=stage,
            offset=offset,
            limit=size,
        )
    else:
        return _err(
            "Must provide one of: sales_employee_id / stage / source_channel",
            code="VALIDATION_ERROR",
        )

    return _ok(
        {
            "items": [i.model_dump(mode="json") for i in items],
            "total": total,
            "page": page,
            "size": size,
        }
    )


def _parse_iso(v: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(v)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid {field}: {exc}"
        ) from exc
    return dt


@router.get("/funnel")
async def funnel(
    request: Request,
    group_by: Literal["sales_employee_id", "source_channel"] = Query(...),
    period_start: str = Query(..., description="ISO 8601"),
    period_end: str = Query(..., description="ISO 8601"),
    service: BanquetLeadService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    start_dt = _parse_iso(period_start, "period_start")
    end_dt = _parse_iso(period_end, "period_end")
    if start_dt > end_dt:
        return _err("period_start must be <= period_end", code="VALIDATION_ERROR")
    result = await service.compute_conversion_rate(
        tenant_id=tenant_id,
        period_start=start_dt,
        period_end=end_dt,
        group_by=group_by,
    )
    return _ok(
        {
            "group_by": group_by,
            "period_start": start_dt.isoformat(),
            "period_end": end_dt.isoformat(),
            "groups": result,
        }
    )


@router.get("/attribution")
async def attribution(
    request: Request,
    period_start: str = Query(..., description="ISO 8601"),
    period_end: str = Query(..., description="ISO 8601"),
    service: BanquetLeadService = Depends(get_service),
) -> dict[str, Any]:
    tenant_id = _require_tenant(request)
    start_dt = _parse_iso(period_start, "period_start")
    end_dt = _parse_iso(period_end, "period_end")
    if start_dt > end_dt:
        return _err("period_start must be <= period_end", code="VALIDATION_ERROR")
    rows = await service.source_attribution(
        tenant_id=tenant_id,
        period_start=start_dt,
        period_end=end_dt,
    )
    return _ok(
        {
            "period_start": start_dt.isoformat(),
            "period_end": end_dt.isoformat(),
            "channels": rows,
        }
    )


__all__ = ["router"]
