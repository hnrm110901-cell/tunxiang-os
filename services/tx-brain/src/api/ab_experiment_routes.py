"""Sprint G — A/B 实验平台 API

端点（11 个）：
  POST   /api/v1/brain/ab/experiments                        创建实验
  GET    /api/v1/brain/ab/experiments                        列表
  GET    /api/v1/brain/ab/experiments/{id}                   详情 + arms
  POST   /api/v1/brain/ab/experiments/{id}/start             开始
  POST   /api/v1/brain/ab/experiments/{id}/pause             暂停
  POST   /api/v1/brain/ab/experiments/{id}/terminate         手动终止
  GET    /api/v1/brain/ab/experiments/{id}/significance      显著性评估
  POST   /api/v1/brain/ab/assign                             entity → arm 分配
  POST   /api/v1/brain/ab/events                             事件摄入
  POST   /api/v1/brain/ab/circuit-breaker/sweep              cron 扫熔断
  GET    /api/v1/brain/ab/arms/{id}/stats                    单 arm 当前统计

熔断 sweep 设计为租户级同步调用；生产环境建议 cron 定时调用。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.ab_experiment_service import (
    ABExperimentService,
    ArmSpec,
    CreateExperimentInput,
    DisputeValidationError,
    RecordEventInput,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/brain/ab",
    tags=["brain-ab-experiments"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class ArmInput(BaseModel):
    arm_key: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    is_control: bool = False
    traffic_weight: int = Field(default=50, ge=0, le=100)
    description: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class CreateExperimentRequest(BaseModel):
    experiment_key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    arms: list[ArmInput] = Field(..., min_length=2)
    description: Optional[str] = None
    primary_metric: str = Field(default="conversion_rate")
    primary_metric_goal: str = Field(default="maximize")
    assignment_strategy: str = Field(default="deterministic_hash")
    entity_type: str = Field(default="customer")
    traffic_percentage: float = Field(default=100.0, ge=0, le=100)
    minimum_sample_size: int = Field(default=1000, ge=1)
    significance_level: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.80, gt=0, lt=1)
    min_detectable_effect: float = Field(default=0.05, gt=0)
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: float = Field(default=0.20, gt=0, lt=1)
    circuit_breaker_min_samples: int = Field(default=200, ge=1)


class TerminateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
    winner_arm_id: Optional[str] = None


class AssignRequest(BaseModel):
    experiment_key: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=100)


class RecordEventRequest(BaseModel):
    experiment_key: str
    entity_id: str
    event_type: str = Field(..., description="exposure|conversion|revenue|metric_value|error")
    revenue_fen: Optional[int] = Field(default=None, ge=0)
    numeric_value: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_at: Optional[datetime] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


# ── 端点 ────────────────────────────────────────────────────────


@router.post("/experiments", response_model=dict, status_code=201)
async def create_experiment(
    req: CreateExperimentRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if x_operator_id:
        _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        inp = CreateExperimentInput(
            experiment_key=req.experiment_key,
            name=req.name,
            arms=[
                ArmSpec(
                    arm_key=a.arm_key,
                    name=a.name,
                    is_control=a.is_control,
                    traffic_weight=a.traffic_weight,
                    description=a.description,
                    parameters=a.parameters,
                )
                for a in req.arms
            ],
            description=req.description,
            primary_metric=req.primary_metric,
            primary_metric_goal=req.primary_metric_goal,
            assignment_strategy=req.assignment_strategy,
            entity_type=req.entity_type,
            traffic_percentage=req.traffic_percentage,
            minimum_sample_size=req.minimum_sample_size,
            significance_level=req.significance_level,
            power=req.power,
            min_detectable_effect=req.min_detectable_effect,
            circuit_breaker_enabled=req.circuit_breaker_enabled,
            circuit_breaker_threshold=req.circuit_breaker_threshold,
            circuit_breaker_min_samples=req.circuit_breaker_min_samples,
            created_by=x_operator_id,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.create_experiment(inp)
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("ab_create_experiment_failed")
        raise HTTPException(
            status_code=500, detail=f"创建失败: {exc}"
        ) from exc

    return {"ok": True, "data": result}


@router.get("/experiments", response_model=dict)
async def list_experiments(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    conditions = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "is_deleted = false",
    ]
    params: dict[str, Any] = {"tenant_id": x_tenant_id}
    if status:
        conditions.append("status = :status")
        params["status"] = status
    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_row = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM ab_experiments WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        list_params = {**params, "limit": size, "offset": offset}
        rows = await db.execute(
            text(f"""
                SELECT id, experiment_key, name, status, primary_metric,
                       traffic_percentage, started_at, ended_at,
                       circuit_breaker_tripped, created_at, updated_at
                FROM ab_experiments
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            list_params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("ab_list_failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
    }


@router.get("/experiments/{experiment_id}", response_model=dict)
async def get_experiment(
    experiment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(experiment_id, "experiment_id")

    try:
        exp_row = await db.execute(
            text("""
                SELECT * FROM ab_experiments
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {"id": experiment_id, "tenant_id": x_tenant_id},
        )
        exp = exp_row.mappings().first()
        if not exp:
            raise HTTPException(status_code=404, detail="实验不存在")

        arms_row = await db.execute(
            text("""
                SELECT * FROM ab_experiment_arms
                WHERE experiment_id = CAST(:id AS uuid)
                  AND is_deleted = false
                ORDER BY is_control DESC, arm_key
            """),
            {"id": experiment_id},
        )
        arms = [dict(r) for r in arms_row.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("ab_get_failed")
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    return {
        "ok": True,
        "data": {"experiment": dict(exp), "arms": arms},
    }


@router.post("/experiments/{experiment_id}/start", response_model=dict)
async def start_experiment(
    experiment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(experiment_id, "experiment_id")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.start_experiment(experiment_id)
    except DisputeValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"启动失败: {exc}") from exc
    return {"ok": True, "data": result}


@router.post("/experiments/{experiment_id}/pause", response_model=dict)
async def pause_experiment(
    experiment_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(experiment_id, "experiment_id")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.pause_experiment(experiment_id)
    except DisputeValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"暂停失败: {exc}") from exc
    return {"ok": True, "data": result}


@router.post("/experiments/{experiment_id}/terminate", response_model=dict)
async def terminate_experiment(
    experiment_id: str,
    req: TerminateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(experiment_id, "experiment_id")
    if req.winner_arm_id:
        _parse_uuid(req.winner_arm_id, "winner_arm_id")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.terminate_experiment(
            experiment_id, reason=req.reason, winner_arm_id=req.winner_arm_id,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"终止失败: {exc}") from exc
    return {"ok": True, "data": result}


@router.get("/experiments/{experiment_id}/significance", response_model=dict)
async def experiment_significance(
    experiment_id: str,
    use_bayesian: bool = False,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(experiment_id, "experiment_id")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.evaluate_significance(
            experiment_id, use_bayesian=use_bayesian,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"评估失败: {exc}") from exc
    return {"ok": True, "data": result}


@router.post("/assign", response_model=dict)
async def assign(
    req: AssignRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """entity → arm 分配（稳定）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.assign(
            experiment_key=req.experiment_key,
            entity_id=req.entity_id,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"分配失败: {exc}") from exc
    return {
        "ok": True,
        "data": {
            "enrolled": result.enrolled,
            "arm_key": result.arm_key,
            "arm_id": result.arm_id,
            "arm_parameters": result.arm_parameters,
            "assignment_id": result.assignment_id,
            "was_new": result.was_new,
            "experiment_id": result.experiment_id,
            "experiment_status": result.experiment_status,
        },
    }


@router.post("/events", response_model=dict)
async def record_event(
    req: RecordEventRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    try:
        inp = RecordEventInput(
            entity_id=req.entity_id,
            event_type=req.event_type,
            revenue_fen=req.revenue_fen,
            numeric_value=req.numeric_value,
            metadata=req.metadata,
            event_at=req.event_at,
            idempotency_key=req.idempotency_key,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        result = await service.record_event(
            experiment_key=req.experiment_key, inp=inp,
        )
    except DisputeValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"记录失败: {exc}") from exc
    return {"ok": True, "data": result}


@router.post("/circuit-breaker/sweep", response_model=dict)
async def circuit_breaker_sweep(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """cron 端点：扫熔断并自动终止；返回每个被触发的实验详情"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    service = ABExperimentService(db, tenant_id=x_tenant_id)
    try:
        results = await service.evaluate_circuit_breakers()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"熔断扫描失败: {exc}") from exc
    tripped_count = sum(1 for r in results if r["should_trip"])
    return {
        "ok": True,
        "data": {
            "total_evaluated": len(results),
            "tripped_count": tripped_count,
            "results": results,
        },
    }


@router.get("/arms/{arm_id}/stats", response_model=dict)
async def arm_stats(
    arm_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(arm_id, "arm_id")
    try:
        row = await db.execute(
            text("""
                SELECT arm_key, name, is_control, traffic_weight,
                       exposure_count, conversion_count, revenue_sum_fen,
                       numeric_metric_sum, last_stats_refreshed_at
                FROM ab_experiment_arms
                WHERE id = CAST(:id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND is_deleted = false
            """),
            {"id": arm_id, "tenant_id": x_tenant_id},
        )
        arm = row.mappings().first()
        if not arm:
            raise HTTPException(status_code=404, detail="arm 不存在")
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc

    data = dict(arm)
    exposure = int(data.get("exposure_count") or 0)
    conversion = int(data.get("conversion_count") or 0)
    data["conversion_rate"] = (
        conversion / exposure if exposure > 0 else 0.0
    )
    return {"ok": True, "data": data}


# ── 辅助 ─────────────────────────────────────────────────────────


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
