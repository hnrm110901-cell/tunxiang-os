"""Sprint G — 实验框架 HTTP 路由

端点：
  POST   /api/v1/experiments/{key}/bucket               主动判桶
  GET    /api/v1/experiments/{key}/dashboard            指标显著性汇总
  GET    /api/v1/experiments/{key}/exposures            历史暴露查询
  GET    /api/v1/experiments/{key}/circuit-breaker      当前熔断状态
  POST   /api/v1/experiments/{key}/circuit-breaker/reset 管理员手动重置

鉴权（CLAUDE.md §13 RLS 强制）：
  - 所有端点要求 X-Tenant-ID Header
  - body 中如带 tenant_id 必须与 Header 一致（三方一致性）
  - circuit-breaker/reset 额外要求 X-Role-Code = ADMIN（最小化权限）

依赖注入风格：
  本路由不在模块顶层 new orchestrator/dashboard/circuit_breaker；通过 FastAPI
  Depends 让运维（main.py）传具体实现，便于 monkeypatch 测试。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..experiment.circuit_breaker import (
    CircuitBreakerEvaluator,
    CircuitBreakerStatus,
)
from ..experiment.dashboard import ExperimentDashboard, TimeWindow
from ..experiment.orchestrator import (
    ExperimentOrchestrator,
    ExperimentSubject,
    OrchestratorBucketResult,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


# ── 依赖：运行时由 main.py 通过 app.dependency_overrides 注入 ──────────────


def get_orchestrator() -> ExperimentOrchestrator:
    """运行时注入。测试用 dependency_overrides 即可 mock。"""
    raise HTTPException(
        status_code=503,
        detail="ExperimentOrchestrator 未注入。运维需在 main.py lifespan 内注册。",
    )


def get_dashboard() -> ExperimentDashboard:
    raise HTTPException(
        status_code=503,
        detail="ExperimentDashboard 未注入。",
    )


def get_circuit_breaker() -> CircuitBreakerEvaluator:
    raise HTTPException(
        status_code=503,
        detail="CircuitBreakerEvaluator 未注入。",
    )


# ── 鉴权辅助 ─────────────────────────────────────────────────────────────


def _require_tenant(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


def _require_admin(
    x_role_code: Optional[str] = Header(None, alias="X-Role-Code"),
) -> str:
    if not x_role_code or x_role_code.upper() not in {"ADMIN", "L3", "OWNER"}:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return x_role_code


def _check_tenant_match(header_tenant: str, body_tenant: Optional[str]) -> None:
    """body 中 tenant_id 若存在，必须与 header 一致（防越权）。"""
    if body_tenant and body_tenant != header_tenant:
        raise HTTPException(
            status_code=403,
            detail=f"tenant_id 三方一致性校验失败：header={header_tenant} body={body_tenant}",
        )


# ── 请求/响应模型 ────────────────────────────────────────────────────────


class BucketRequest(BaseModel):
    tenant_id: Optional[str] = None  # 可选；若提供则与 header 校验
    subject_type: str = Field(..., min_length=1, max_length=32)
    subject_id: str = Field(..., min_length=1, max_length=128)
    store_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None


class BucketResponse(BaseModel):
    bucket: str
    bucket_position: int
    is_new_exposure: bool
    fallback_reason: Optional[str]
    experiment_enabled: bool
    circuit_breaker_tripped: bool


class CircuitBreachResponse(BaseModel):
    variant: str
    metric_key: str
    drop_pct: float
    threshold_pct: float


class CircuitBreakerResponse(BaseModel):
    experiment_key: str
    tripped: bool
    threshold_pct: float
    breaches: list[CircuitBreachResponse]
    evaluated_at: str


class CircuitBreakerResetRequest(BaseModel):
    tenant_id: Optional[str] = None
    actor: str = Field(..., min_length=1, max_length=128)


# ── 端点 ────────────────────────────────────────────────────────────────


@router.post("/{key}/bucket")
async def bucket_assign(
    key: str,
    body: BucketRequest = Body(...),
    tenant_id: str = Depends(_require_tenant),
    orchestrator: ExperimentOrchestrator = Depends(get_orchestrator),
) -> dict:
    """主动判桶。idempotent：同 subject 重复请求返回历史 bucket。"""
    _check_tenant_match(tenant_id, body.tenant_id)

    result: OrchestratorBucketResult = await orchestrator.get_bucket(
        tenant_id=tenant_id,
        experiment_key=key,
        subject=ExperimentSubject(
            subject_type=body.subject_type, subject_id=body.subject_id
        ),
        store_id=body.store_id,
        context=body.context or {},
    )
    return {
        "ok": True,
        "data": BucketResponse(
            bucket=result.bucket,
            bucket_position=result.bucket_position,
            is_new_exposure=result.is_new_exposure,
            fallback_reason=result.fallback_reason,
            experiment_enabled=result.experiment_enabled,
            circuit_breaker_tripped=result.circuit_breaker_tripped,
        ).model_dump(),
    }


@router.get("/{key}/dashboard")
async def dashboard_summary(
    key: str,
    metric: list[str] = Query(..., description="监控指标键（可多个）"),
    from_iso: Optional[str] = Query(None, alias="from"),
    to_iso: Optional[str] = Query(None, alias="to"),
    tenant_id: str = Depends(_require_tenant),
    dashboard: ExperimentDashboard = Depends(get_dashboard),
) -> dict:
    """跨变体显著性汇总。默认窗口为最近 24 小时。"""
    end = (
        datetime.fromisoformat(to_iso) if to_iso else datetime.now(timezone.utc)
    )
    start = (
        datetime.fromisoformat(from_iso)
        if from_iso
        else (end - timedelta(hours=24))
    )
    if start >= end:
        raise HTTPException(status_code=400, detail="from 必须早于 to")

    summary = await dashboard.summarize(
        tenant_id=tenant_id,
        experiment_key=key,
        metric_keys=metric,
        time_window=TimeWindow(start=start, end=end),
    )

    return {
        "ok": True,
        "data": {
            "experiment_key": summary.experiment_key,
            "time_window": {
                "start": summary.time_window.start.isoformat(),
                "end": summary.time_window.end.isoformat(),
            },
            "variant_subject_counts": {
                v: len(ids) for v, ids in summary.variant_subjects.items()
            },
            "cells": [
                {
                    "variant": c.variant,
                    "metric_key": c.metric_key,
                    "n": c.n,
                    "mean": c.mean,
                }
                for c in summary.cells
            ],
            "pairs": [
                {
                    "metric_key": p.metric_key,
                    "control_variant": p.control_variant,
                    "test_variant": p.test_variant,
                    "lift_pct": p.lift_pct,
                    "p_value": p.welch.p_value,
                    "t_statistic": p.welch.t_statistic,
                    "df": p.welch.df,
                    "effect_size_cohens_d": p.welch.effect_size_cohens_d,
                    "ci_95_low": p.welch.ci_95_low,
                    "ci_95_high": p.welch.ci_95_high,
                    "n_a": p.welch.n_a,
                    "n_b": p.welch.n_b,
                    "is_significant_at_005": p.welch.is_significant_at_005,
                }
                for p in summary.pairs
            ],
        },
    }


@router.get("/{key}/exposures")
async def exposures_lookup(
    key: str,
    subject_id: str = Query(..., min_length=1),
    subject_type: str = Query("user", min_length=1, max_length=32),
    tenant_id: str = Depends(_require_tenant),
    orchestrator: ExperimentOrchestrator = Depends(get_orchestrator),
) -> dict:
    """查 subject 在某实验的历史 bucket（无副作用，不写新暴露）。"""
    bucket = None
    try:
        bucket = await orchestrator._exp_repo.get_existing(  # noqa: SLF001 — 路由层只读
            tenant_id=tenant_id,
            experiment_key=key,
            subject_type=subject_type,
            subject_id=subject_id,
        )
    except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
        logger.warning("exposures_lookup_failed", error=str(e))
        raise HTTPException(status_code=500, detail="查询失败")

    return {
        "ok": True,
        "data": {
            "experiment_key": key,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "bucket": bucket,
            "exposed": bucket is not None,
        },
    }


@router.get("/{key}/circuit-breaker")
async def circuit_breaker_status(
    key: str,
    threshold_pct: float = Query(-20.0, le=0.0, ge=-100.0),
    tenant_id: str = Depends(_require_tenant),
    breaker: CircuitBreakerEvaluator = Depends(get_circuit_breaker),
) -> dict:
    """评估并返回当前熔断状态（不自动 trip；只读）。"""
    status: CircuitBreakerStatus = await breaker.evaluate(
        tenant_id=tenant_id,
        experiment_key=key,
        threshold_pct=threshold_pct,
    )
    return {
        "ok": True,
        "data": CircuitBreakerResponse(
            experiment_key=status.experiment_key,
            tripped=status.tripped,
            threshold_pct=status.threshold_pct,
            breaches=[
                CircuitBreachResponse(
                    variant=b.variant,
                    metric_key=b.metric_key,
                    drop_pct=b.drop_pct,
                    threshold_pct=b.threshold_pct,
                )
                for b in status.breaches
            ],
            evaluated_at=status.evaluated_at.isoformat(),
        ).model_dump(),
    }


@router.post("/{key}/circuit-breaker/reset")
async def circuit_breaker_reset(
    key: str,
    body: CircuitBreakerResetRequest = Body(...),
    tenant_id: str = Depends(_require_tenant),
    _role: str = Depends(_require_admin),
    breaker: CircuitBreakerEvaluator = Depends(get_circuit_breaker),
) -> dict:
    """管理员手动重置熔断（删 flag 文件 + 发 RESET 事件）。

    注意：本端点不会自动重新启用 enabled=True；需通过实验定义管理 API 显式启用，
    避免熔断条件未消除前误重启。
    """
    _check_tenant_match(tenant_id, body.tenant_id)
    await breaker.reset(tenant_id=tenant_id, experiment_key=key, actor=body.actor)
    return {
        "ok": True,
        "data": {
            "experiment_key": key,
            "reset_by": body.actor,
            "reset_at": datetime.now(timezone.utc).isoformat(),
        },
    }
