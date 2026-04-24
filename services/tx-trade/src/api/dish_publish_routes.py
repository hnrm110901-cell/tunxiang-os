"""Sprint E2 — 菜品一键发布 API

端点：
  POST /api/v1/trade/delivery/publish
    首次发布 / 全量更新（dish_spec + targets[]）

  POST /api/v1/trade/delivery/publish/{dish_id}/price
    更新价格（price_fen + platforms[]）

  POST /api/v1/trade/delivery/publish/{dish_id}/stock
    更新库存（stock + platforms[]，stock=null 表示不限库存）

  POST /api/v1/trade/delivery/publish/{dish_id}/pause
    停售（platforms[]）

  POST /api/v1/trade/delivery/publish/{dish_id}/resume
    恢复售卖（platforms[], 可选 stock）

  POST /api/v1/trade/delivery/publish/{dish_id}/unpublish
    下架（platforms[]）

  GET  /api/v1/trade/delivery/publish/{dish_id}
    查一道菜在各平台的发布状态

  GET  /api/v1/trade/delivery/publish
    分页列表（platform / status / error 过滤）

  GET  /api/v1/trade/delivery/publish/{dish_id}/tasks
    发布任务历史
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.adapters.delivery_publish import (
    DishPublishSpec,
    PublishOperation,
)
from shared.adapters.delivery_publish.base import PublishError
from shared.ontology.src.database import get_db

from ..services.dish_publish_orchestrator import (
    DishPublishOrchestrator,
    PlatformTarget,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/trade/delivery/publish",
    tags=["trade-delivery-publish"],
)


# ── 请求模型 ─────────────────────────────────────────────────────


class DishSpecInput(BaseModel):
    dish_id: str
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., max_length=100)
    price_fen: int = Field(..., ge=0)
    description: Optional[str] = None
    original_price_fen: Optional[int] = Field(default=None, ge=0)
    stock: Optional[int] = Field(default=None, ge=0)
    image_urls: list[str] = Field(default_factory=list)
    cover_image_url: Optional[str] = None
    modifiers: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    packaging_fee_fen: int = Field(default=0, ge=0)
    weight_g: Optional[int] = Field(default=None, ge=0)
    allergens: list[str] = Field(default_factory=list)
    calories_kcal: Optional[int] = Field(default=None, ge=0)
    platform_overrides: dict[str, dict] = Field(default_factory=dict)


class PlatformTargetInput(BaseModel):
    platform: str = Field(
        ..., description="meituan|eleme|douyin|xiaohongshu|wechat"
    )
    platform_shop_id: str = Field(..., min_length=1, max_length=100)
    brand_id: Optional[str] = None
    store_id: Optional[str] = None


class PublishRequest(BaseModel):
    spec: DishSpecInput
    targets: list[PlatformTargetInput] = Field(..., min_length=1)


class PriceUpdateRequest(BaseModel):
    price_fen: int = Field(..., ge=0)
    original_price_fen: Optional[int] = Field(default=None, ge=0)
    platforms: list[str] = Field(..., min_length=1)


class StockUpdateRequest(BaseModel):
    stock: Optional[int] = Field(default=None, ge=0)
    platforms: list[str] = Field(..., min_length=1)


class PlatformsRequest(BaseModel):
    platforms: list[str] = Field(..., min_length=1)


# ── 端点 ────────────────────────────────────────────────────────


@router.post("", response_model=dict)
async def publish_dish(
    req: PublishRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """首次发布 / 全量更新到多个平台"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    if x_operator_id:
        _parse_uuid(x_operator_id, "X-Operator-ID")

    try:
        spec = DishPublishSpec(**req.spec.model_dump())
    except PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    targets = [
        PlatformTarget(
            platform=t.platform,
            platform_shop_id=t.platform_shop_id,
            brand_id=t.brand_id,
            store_id=t.store_id,
        )
        for t in req.targets
    ]

    orchestrator = DishPublishOrchestrator(db, tenant_id=x_tenant_id)
    try:
        outcomes = await orchestrator.orchestrate_publish(
            spec=spec,
            targets=targets,
            triggered_by=x_operator_id,
            trigger_source="api",
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dish_publish_failed")
        raise HTTPException(
            status_code=500, detail=f"发布失败: {exc}"
        ) from exc

    succeeded = sum(1 for o in outcomes if o.result.ok)
    return {
        "ok": True,
        "data": {
            "dish_id": spec.dish_id,
            "total_targets": len(outcomes),
            "succeeded": succeeded,
            "failed": len(outcomes) - succeeded,
            "outcomes": [o.to_dict() for o in outcomes],
        },
    }


@router.post("/{dish_id}/price", response_model=dict)
async def update_dish_price(
    dish_id: str,
    req: PriceUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")

    # 构造最小 spec，仅含 price
    try:
        spec = DishPublishSpec(
            dish_id=dish_id,
            name="[price_update]",
            category="unknown",
            price_fen=req.price_fen,
            original_price_fen=req.original_price_fen,
        )
    except PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _run_operation(
        db=db,
        tenant_id=x_tenant_id,
        dish_id=dish_id,
        operation=PublishOperation.UPDATE_PRICE,
        platforms=req.platforms,
        spec=spec,
        triggered_by=x_operator_id,
    )


@router.post("/{dish_id}/stock", response_model=dict)
async def update_dish_stock(
    dish_id: str,
    req: StockUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")

    try:
        spec = DishPublishSpec(
            dish_id=dish_id,
            name="[stock_update]",
            category="unknown",
            price_fen=0,
            stock=req.stock,
        )
    except PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _run_operation(
        db=db,
        tenant_id=x_tenant_id,
        dish_id=dish_id,
        operation=PublishOperation.UPDATE_STOCK,
        platforms=req.platforms,
        spec=spec,
        triggered_by=x_operator_id,
    )


@router.post("/{dish_id}/pause", response_model=dict)
async def pause_dish(
    dish_id: str,
    req: PlatformsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")
    return await _run_operation(
        db=db,
        tenant_id=x_tenant_id,
        dish_id=dish_id,
        operation=PublishOperation.PAUSE,
        platforms=req.platforms,
        spec=None,
        triggered_by=x_operator_id,
    )


@router.post("/{dish_id}/resume", response_model=dict)
async def resume_dish(
    dish_id: str,
    req: StockUpdateRequest,  # 复用：含 stock
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")
    try:
        spec = DishPublishSpec(
            dish_id=dish_id,
            name="[resume]",
            category="unknown",
            price_fen=0,
            stock=req.stock,
        )
    except PublishError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _run_operation(
        db=db,
        tenant_id=x_tenant_id,
        dish_id=dish_id,
        operation=PublishOperation.RESUME,
        platforms=req.platforms,
        spec=spec,
        triggered_by=x_operator_id,
    )


@router.post("/{dish_id}/unpublish", response_model=dict)
async def unpublish_dish(
    dish_id: str,
    req: PlatformsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_operator_id: Optional[str] = Header(default=None, alias="X-Operator-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")
    return await _run_operation(
        db=db,
        tenant_id=x_tenant_id,
        dish_id=dish_id,
        operation=PublishOperation.UNPUBLISH,
        platforms=req.platforms,
        spec=None,
        triggered_by=x_operator_id,
    )


@router.get("/{dish_id}", response_model=dict)
async def get_dish_publish_status(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查一道菜在各平台的发布状态"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")

    try:
        rows = await db.execute(
            text("""
                SELECT id, platform, platform_sku_id, platform_shop_id,
                       status, target_price_fen, published_price_fen,
                       original_price_fen, stock_target, stock_available,
                       last_sync_at, last_sync_operation, last_error,
                       error_count, consecutive_error_count, updated_at
                FROM dish_publish_registry
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND dish_id = CAST(:dish_id AS uuid)
                  AND is_deleted = false
                ORDER BY platform
            """),
            {"tenant_id": x_tenant_id, "dish_id": dish_id},
        )
        registry = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dish_publish_get_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "platform_count": len(registry),
            "registry": registry,
        },
    }


@router.get("", response_model=dict)
async def list_dish_publish(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    errors_only: bool = False,
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
    params: dict = {"tenant_id": x_tenant_id}
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if errors_only:
        conditions.append("consecutive_error_count > 0")

    where = " AND ".join(conditions)
    offset = (page - 1) * size

    try:
        count_row = await db.execute(
            text(f"SELECT COUNT(*) AS total FROM dish_publish_registry WHERE {where}"),
            params,
        )
        total = count_row.scalar() or 0

        list_params = {**params, "limit": size, "offset": offset}
        rows = await db.execute(
            text(f"""
                SELECT id, dish_id, platform, platform_sku_id, status,
                       target_price_fen, published_price_fen,
                       stock_target, stock_available,
                       last_sync_at, consecutive_error_count, updated_at
                FROM dish_publish_registry
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
            """),
            list_params,
        )
        items = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dish_publish_list_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/{dish_id}/tasks", response_model=dict)
async def list_dish_publish_tasks(
    dish_id: str,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发布任务历史（审计 trail）"""
    _parse_uuid(x_tenant_id, "X-Tenant-ID")
    _parse_uuid(dish_id, "dish_id")

    conditions = [
        "tenant_id = CAST(:tenant_id AS uuid)",
        "dish_id = CAST(:dish_id AS uuid)",
    ]
    params: dict = {
        "tenant_id": x_tenant_id,
        "dish_id": dish_id,
        "limit": limit,
    }
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    try:
        rows = await db.execute(
            text(f"""
                SELECT id, platform, operation, status, attempts,
                       started_at, completed_at, error_message,
                       triggered_by, trigger_source, created_at
                FROM dish_publish_tasks
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        )
        tasks = [dict(r) for r in rows.mappings()]
    except SQLAlchemyError as exc:
        logger.exception("dish_publish_tasks_failed")
        raise HTTPException(
            status_code=500, detail=f"查询失败: {exc}"
        ) from exc

    return {
        "ok": True,
        "data": {"dish_id": dish_id, "tasks": tasks, "count": len(tasks)},
    }


# ── 辅助 ─────────────────────────────────────────────────────────


async def _run_operation(
    *,
    db: AsyncSession,
    tenant_id: str,
    dish_id: str,
    operation: PublishOperation,
    platforms: list[str],
    spec: Optional[DishPublishSpec],
    triggered_by: Optional[str],
) -> dict:
    orchestrator = DishPublishOrchestrator(db, tenant_id=tenant_id)
    try:
        outcomes = await orchestrator.orchestrate_operation(
            dish_id=dish_id,
            operation=operation,
            platforms=platforms,
            spec=spec,
            triggered_by=triggered_by,
            trigger_source="api",
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("dish_publish_op_failed")
        raise HTTPException(
            status_code=500, detail=f"{operation.value} 失败: {exc}"
        ) from exc

    succeeded = sum(1 for o in outcomes if o.result.ok)
    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "operation": operation.value,
            "total_targets": len(outcomes),
            "succeeded": succeeded,
            "failed": len(outcomes) - succeeded,
            "outcomes": [o.to_dict() for o in outcomes],
        },
    }


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{field_name} 非法 UUID: {value!r}"
        ) from exc
