"""market_survey_routes — Market Survey 调研双轨 API（PRD-13 sub-A / Phase 2 W11 / T2 normal）

接口列表 (15 endpoints):

  主表 CRUD + transition (7):
    POST   /api/v1/supply/market-surveys                          新建调研 (默认 draft)
    GET    /api/v1/supply/market-surveys                          列表 (?market_type=&status=&limit=&offset=)
    GET    /api/v1/supply/market-surveys/{survey_id}              单条主表
    GET    /api/v1/supply/market-surveys/{survey_id}/detail       主表 + items + photos 聚合
    PATCH  /api/v1/supply/market-surveys/{survey_id}              更新主表 (status 不可改)
    DELETE /api/v1/supply/market-surveys/{survey_id}              软删
    POST   /api/v1/supply/market-surveys/{survey_id}/transition   status 转换 (走合法图)

  明细 CRUD (4):
    POST   /api/v1/supply/market-surveys/{survey_id}/items        新增明细
    GET    /api/v1/supply/market-surveys/{survey_id}/items        列出明细
    PATCH  /api/v1/supply/market-surveys/items/{item_id}          更新明细
    DELETE /api/v1/supply/market-surveys/items/{item_id}          软删明细

  照片 CRUD (4):
    POST   /api/v1/supply/market-surveys/{survey_id}/photos       新增照片
    GET    /api/v1/supply/market-surveys/{survey_id}/photos       列出照片
    PATCH  /api/v1/supply/market-surveys/photos/{photo_id}        更新照片 caption / exif
    DELETE /api/v1/supply/market-surveys/photos/{photo_id}        软删照片

错误码映射 (lesson 沿用 PRD-08/11):
  - ValueError("不存在") → 404
  - ValueError("非法 status 转换") → 422
  - 其他 ValueError → 422
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.market_survey_models import (
    MarketSurveyCreate,
    MarketSurveyItemCreate,
    MarketSurveyItemUpdate,
    MarketSurveyPhotoCreate,
    MarketSurveyPhotoUpdate,
    MarketSurveyUpdate,
    StatusTransitionRequest,
)
from ..services.market_survey_service import (
    add_item,
    add_photo,
    create_survey,
    delete_item,
    delete_photo,
    delete_survey,
    get_photo,
    get_survey,
    get_survey_detail,
    list_items_by_survey,
    list_photos_by_survey,
    list_surveys,
    transition_status,
    update_item,
    update_photo,
    update_survey,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply/market-surveys",
    tags=["market-surveys"],
)


def _map_value_error(exc: ValueError, *, default_code: str) -> HTTPException:
    """统一 ValueError → HTTPException 映射 (lesson 沿用)."""
    msg = str(exc)
    if "不存在" in msg:
        return HTTPException(
            status_code=404,
            detail={"code": "SURVEY_NOT_FOUND", "message": msg},
        )
    if "非法 status 转换" in msg or "状态" in msg:
        return HTTPException(
            status_code=422,
            detail={"code": "INVALID_STATUS_TRANSITION", "message": msg},
        )
    return HTTPException(
        status_code=422,
        detail={"code": default_code, "message": msg},
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. 主表 CRUD + transition
# ═════════════════════════════════════════════════════════════════════════════


@router.post("")
async def create_market_survey(
    body: MarketSurveyCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建调研 (status 默认 draft)."""
    try:
        item = await create_survey(
            db=db,
            tenant_id=x_tenant_id,
            surveyor_id=str(body.surveyor_id),
            market_type=body.market_type.value,
            location_name=body.location_name,
            surveyed_at=body.surveyed_at,
            notes=body.notes,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="SURVEY_CREATE_INVALID") from e
    return {"ok": True, "data": item}


@router.get("")
async def list_market_surveys(
    market_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """调研列表 — surveyed_at 倒序; 可选过滤 market_type / status."""
    try:
        items = await list_surveys(
            db=db,
            tenant_id=x_tenant_id,
            market_type=market_type,
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="SURVEY_LIST_INVALID") from e
    return {"ok": True, "data": items}


@router.get("/{survey_id}/detail")
async def get_market_survey_detail(
    survey_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """聚合详情 — 主表 + items + photos."""
    detail = await get_survey_detail(db=db, tenant_id=x_tenant_id, survey_id=survey_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SURVEY_NOT_FOUND",
                "message": f"survey_id={survey_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": detail}


@router.get("/{survey_id}")
async def get_market_survey(
    survey_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """单条调研主表."""
    item = await get_survey(db=db, tenant_id=x_tenant_id, survey_id=survey_id)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SURVEY_NOT_FOUND",
                "message": f"survey_id={survey_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": item}


@router.patch("/{survey_id}")
async def update_market_survey(
    survey_id: str,
    body: MarketSurveyUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新调研主表 (status 不可改, 走 /transition)."""
    raw_updates = body.model_dump(exclude_unset=True)
    if "market_type" in raw_updates and raw_updates["market_type"] is not None:
        raw_updates["market_type"] = raw_updates["market_type"].value
    try:
        item = await update_survey(
            db=db,
            tenant_id=x_tenant_id,
            survey_id=survey_id,
            updates=raw_updates,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="SURVEY_UPDATE_INVALID") from e
    return {"ok": True, "data": item}


@router.delete("/{survey_id}")
async def delete_market_survey(
    survey_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删调研."""
    ok = await delete_survey(db=db, tenant_id=x_tenant_id, survey_id=survey_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SURVEY_NOT_FOUND",
                "message": f"survey_id={survey_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "survey_id": survey_id}}


@router.post("/{survey_id}/transition")
async def transition_market_survey_status(
    survey_id: str,
    body: StatusTransitionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """status 转换 — 合法路径: draft↔submitted / submitted→verified / verified=终态."""
    try:
        item = await transition_status(
            db=db,
            tenant_id=x_tenant_id,
            survey_id=survey_id,
            target_status=body.target_status.value,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="STATUS_TRANSITION_INVALID") from e
    return {"ok": True, "data": item}


# ═════════════════════════════════════════════════════════════════════════════
# 2. 明细 CRUD
# ═════════════════════════════════════════════════════════════════════════════


@router.post("/{survey_id}/items")
async def add_market_survey_item(
    survey_id: str,
    body: MarketSurveyItemCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新增调研明细."""
    try:
        item = await add_item(
            db=db,
            tenant_id=x_tenant_id,
            survey_id=survey_id,
            ingredient_id=str(body.ingredient_id) if body.ingredient_id else None,
            ingredient_name=body.ingredient_name,
            unit_price_fen=body.unit_price_fen,
            qty_per_unit=body.qty_per_unit,
            unit=body.unit,
            notes=body.notes,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="ITEM_CREATE_INVALID") from e
    return {"ok": True, "data": item}


@router.get("/{survey_id}/items")
async def list_market_survey_items(
    survey_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出某调研所有明细 (created_at 升序)."""
    items = await list_items_by_survey(
        db=db, tenant_id=x_tenant_id, survey_id=survey_id
    )
    return {"ok": True, "data": items}


@router.patch("/items/{item_id}")
async def update_market_survey_item(
    item_id: str,
    body: MarketSurveyItemUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新明细."""
    raw_updates = body.model_dump(exclude_unset=True)
    # UUID/Decimal pydantic 自动序列化, 但 ingredient_id 是 UUID 类型需转 str
    if "ingredient_id" in raw_updates and raw_updates["ingredient_id"] is not None:
        raw_updates["ingredient_id"] = str(raw_updates["ingredient_id"])
    try:
        item = await update_item(
            db=db,
            tenant_id=x_tenant_id,
            item_id=item_id,
            updates=raw_updates,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="ITEM_UPDATE_INVALID") from e
    return {"ok": True, "data": item}


@router.delete("/items/{item_id}")
async def delete_market_survey_item(
    item_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删明细."""
    ok = await delete_item(db=db, tenant_id=x_tenant_id, item_id=item_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ITEM_NOT_FOUND",
                "message": f"item_id={item_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "item_id": item_id}}


# ═════════════════════════════════════════════════════════════════════════════
# 3. 照片 CRUD
# ═════════════════════════════════════════════════════════════════════════════


@router.post("/{survey_id}/photos")
async def add_market_survey_photo(
    survey_id: str,
    body: MarketSurveyPhotoCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新增照片. item_id NULL = 调研封面图."""
    try:
        item = await add_photo(
            db=db,
            tenant_id=x_tenant_id,
            survey_id=survey_id,
            item_id=str(body.item_id) if body.item_id else None,
            photo_url=body.photo_url,
            caption=body.caption,
            exif_meta=body.exif_meta,
            uploaded_at=body.uploaded_at,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="PHOTO_CREATE_INVALID") from e
    return {"ok": True, "data": item}


@router.get("/{survey_id}/photos")
async def list_market_survey_photos(
    survey_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出某调研所有照片 (uploaded_at 升序)."""
    items = await list_photos_by_survey(
        db=db, tenant_id=x_tenant_id, survey_id=survey_id
    )
    return {"ok": True, "data": items}


@router.patch("/photos/{photo_id}")
async def update_market_survey_photo(
    photo_id: str,
    body: MarketSurveyPhotoUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """更新照片 — 仅 caption / exif_meta."""
    raw_updates = body.model_dump(exclude_unset=True)
    try:
        item = await update_photo(
            db=db,
            tenant_id=x_tenant_id,
            photo_id=photo_id,
            updates=raw_updates,
        )
    except ValueError as e:
        raise _map_value_error(e, default_code="PHOTO_UPDATE_INVALID") from e
    return {"ok": True, "data": item}


@router.delete("/photos/{photo_id}")
async def delete_market_survey_photo(
    photo_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删照片."""
    ok = await delete_photo(db=db, tenant_id=x_tenant_id, photo_id=photo_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PHOTO_NOT_FOUND",
                "message": f"photo_id={photo_id} 不存在或已删除",
            },
        )
    return {"ok": True, "data": {"deleted": True, "photo_id": photo_id}}


__all__ = ["router"]
