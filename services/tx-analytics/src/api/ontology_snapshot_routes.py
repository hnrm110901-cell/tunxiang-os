"""Ontology快照 API 路由

6大实体周期性聚合快照的查询与触发接口。

端点列表：
  POST /ontology-snapshots/compute                  — 触发计算（指定日期+快照类型）
  GET  /ontology-snapshots/{entity_type}/trend      — 趋势查询
  GET  /ontology-snapshots/cross-brand              — 跨品牌指标对比
  GET  /ontology-snapshots/{entity_type}/latest     — 集团最新快照
  GET  /ontology-snapshots/summary                  — 集团所有实体最新快照汇总

鉴权：X-Tenant-ID header 必填
响应格式：{"ok": bool, "data": {}, "error": {}}
金额单位：分(fen)
"""
from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from ..services.ontology_snapshot_service import (
    OntologySnapshotService,
    ENTITY_TYPES,
    SNAPSHOT_TYPES,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/ontology-snapshots", tags=["ontology-snapshots"])

_svc = OntologySnapshotService()


# ─── 公共辅助 ──────────────────────────────────────────────────────────────────


def _require_tenant(x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 必填")
    return x_tenant_id


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _validate_entity_type(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"entity_type 不合法，合法值: {sorted(ENTITY_TYPES)}",
        )
    return entity_type


def _validate_snapshot_type(snapshot_type: str) -> str:
    if snapshot_type not in SNAPSHOT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"snapshot_type 不合法，合法值: {sorted(SNAPSHOT_TYPES)}",
        )
    return snapshot_type


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _err(detail: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"ok": False, "error": detail})


# ─── 请求体模型 ────────────────────────────────────────────────────────────────


class ComputeSnapshotRequest(BaseModel):
    tenant_id: UUID = Field(description="租户 UUID")
    snapshot_date: date = Field(description="快照日期，如 2026-03-31")
    snapshot_type: str = Field(default="daily", description="daily / weekly / monthly")


# ─── 1. 触发计算 ───────────────────────────────────────────────────────────────


@router.post("/compute")
async def api_compute_snapshots(
    body: ComputeSnapshotRequest,
    x_tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """触发计算指定日期的所有实体快照（集团级）。

    请求体：
    - tenant_id: UUID
    - snapshot_date: date（如 2026-03-31）
    - snapshot_type: daily / weekly / monthly

    返回：
    - 各实体计算结果摘要
    """
    _validate_snapshot_type(body.snapshot_type)

    # X-Tenant-ID 与 body.tenant_id 必须一致（防止跨租户写入）
    if str(body.tenant_id) != x_tenant_id:
        raise _err("body.tenant_id 与 X-Tenant-ID 不匹配", status_code=403)

    logger.info(
        "ontology_snapshot.api.compute",
        tenant_id=str(body.tenant_id),
        snapshot_date=body.snapshot_date.isoformat(),
        snapshot_type=body.snapshot_type,
    )

    summary = await _svc.compute_daily_snapshots(
        tenant_id=body.tenant_id,
        snapshot_date=body.snapshot_date,
        db=db,
    )

    succeeded = [k for k, v in summary.items() if v.get("ok")]
    failed = [k for k, v in summary.items() if not v.get("ok")]

    return _ok({
        "snapshot_date": body.snapshot_date.isoformat(),
        "snapshot_type": body.snapshot_type,
        "succeeded_entities": succeeded,
        "failed_entities": failed,
        "detail": summary,
    })


# ─── 2. 趋势查询 ───────────────────────────────────────────────────────────────


@router.get("/{entity_type}/trend")
async def api_entity_trend(
    entity_type: str,
    start_date: date = Query(..., description="开始日期，如 2026-03-01"),
    end_date: date = Query(..., description="结束日期，如 2026-03-31"),
    snapshot_type: str = Query(default="daily", description="daily / weekly / monthly"),
    brand_id: Optional[UUID] = Query(default=None, description="品牌 UUID，不填=集团级"),
    store_id: Optional[UUID] = Query(default=None, description="门店 UUID，不填=品牌/集团级"),
    x_tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询指定实体在时间范围内的趋势数据（按日期升序）。

    路径参数：
    - entity_type: customer / dish / store / order / ingredient / employee

    Query 参数：
    - start_date / end_date: 日期范围（含两端）
    - snapshot_type: daily（默认）/ weekly / monthly
    - brand_id: 品牌级筛选（可选）
    - store_id: 门店级筛选（可选）

    返回：
    - [{"snapshot_date": "2026-03-01", "metrics": {...}}, ...]
    """
    _validate_entity_type(entity_type)
    _validate_snapshot_type(snapshot_type)

    if start_date > end_date:
        raise _err("start_date 不能晚于 end_date")

    trend = await _svc.get_entity_trend(
        tenant_id=UUID(x_tenant_id),
        entity_type=entity_type,
        brand_id=brand_id,
        store_id=store_id,
        start_date=start_date,
        end_date=end_date,
        snapshot_type=snapshot_type,
        db=db,
    )

    return _ok({
        "entity_type": entity_type,
        "snapshot_type": snapshot_type,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "count": len(trend),
        "items": trend,
    })


# ─── 3. 跨品牌对比 ─────────────────────────────────────────────────────────────


@router.get("/cross-brand")
async def api_cross_brand_comparison(
    entity_type: str = Query(..., description="实体类型"),
    snapshot_date: date = Query(..., description="对比日期，如 2026-03-31"),
    metric_key: str = Query(..., description="对比指标键，如 total_revenue_fen"),
    x_tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """跨品牌对比：同一天同一实体指标的各品牌排行（降序）。

    Query 参数：
    - entity_type: 实体类型
    - snapshot_date: 对比日期
    - metric_key: 指标键名（如 total_revenue_fen / active_count）

    返回：
    - [{"brand_id": "...", "metric_value": 123, "rank": 1}, ...]
    """
    _validate_entity_type(entity_type)

    comparison = await _svc.get_cross_brand_comparison(
        tenant_id=UUID(x_tenant_id),
        entity_type=entity_type,
        snapshot_date=snapshot_date,
        metric_key=metric_key,
        db=db,
    )

    return _ok({
        "entity_type": entity_type,
        "snapshot_date": snapshot_date.isoformat(),
        "metric_key": metric_key,
        "count": len(comparison),
        "ranking": comparison,
    })


# ─── 4. 集团最新快照 ──────────────────────────────────────────────────────────


@router.get("/{entity_type}/latest")
async def api_latest_group_snapshot(
    entity_type: str,
    x_tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取指定实体的集团级最新快照。

    路径参数：
    - entity_type: customer / dish / store / order / ingredient / employee

    返回：
    - {"snapshot_date": "...", "snapshot_type": "...", "metrics": {...}}
    - 无数据时返回 null
    """
    _validate_entity_type(entity_type)

    snapshot = await _svc.get_latest_group_snapshot(
        tenant_id=UUID(x_tenant_id),
        entity_type=entity_type,
        db=db,
    )

    return _ok(snapshot)


# ─── 5. 集团所有实体最新快照汇总 ──────────────────────────────────────────────


@router.get("/summary")
async def api_group_snapshot_summary(
    x_tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取集团所有6大实体的最新快照汇总。

    返回：
    - {"customer": {...}, "dish": {...}, "store": {...}, "order": {...},
       "ingredient": {...}, "employee": {...}}
    - 无数据的实体返回 null
    """
    summary = await _svc.get_all_latest_group_snapshots(
        tenant_id=UUID(x_tenant_id),
        db=db,
    )

    return _ok({
        "tenant_id": x_tenant_id,
        "entities": summary,
    })
