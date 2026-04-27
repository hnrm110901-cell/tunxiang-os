"""
加购推荐话术路由 — AI个性化菜单增强

5个端点：
  POST /for-cart          — 根据购物车获取加购推荐+话术
  GET  /prompts           — 查询话术列表（分页，含转化率）
  POST /generate-batch    — 批量生成高亲和菜品对的话术
  POST /impression        — 记录话术曝光
  POST /conversion        — 记录话术转化
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.upsell_generator import (
    batch_generate_prompts,
    get_upsell_for_cart,
    record_conversion,
    record_impression,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/menu/upsell", tags=["upsell"])


# ─── Request / Response Models ──────────────────────────────────────────────


class CartRequest(BaseModel):
    store_id: str
    cart_dish_ids: list[str] = Field(..., min_length=1, max_length=50)
    limit: int = Field(default=3, ge=1, le=10)


class BatchGenerateRequest(BaseModel):
    store_id: str
    top_n: int = Field(default=20, ge=1, le=100)
    period: str = Field(default="last_30d")
    prompt_type: str = Field(default="add_on")


class ImpressionRequest(BaseModel):
    prompt_id: str


class ConversionRequest(BaseModel):
    prompt_id: str


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/for-cart")
async def upsell_for_cart(
    req: CartRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """根据购物车已选菜品返回AI加购推荐+话术"""
    try:
        suggestions = await get_upsell_for_cart(
            db=db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            cart_dish_ids=req.cart_dish_ids,
            limit=req.limit,
        )
        return {"ok": True, "data": {"items": suggestions, "total": len(suggestions)}}
    except SQLAlchemyError as exc:
        logger.error("upsell_for_cart_error", error=str(exc))
        raise HTTPException(status_code=500, detail="获取加购推荐失败")


@router.get("/prompts")
async def list_upsell_prompts(
    store_id: Optional[str] = Query(None),
    prompt_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """查询话术列表（分页），含转化率统计"""
    try:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(x_tenant_id)},
        )

        # 构建动态WHERE条件
        conditions = ["up.tenant_id = :tenant_id", "up.is_deleted = FALSE"]
        params: dict = {"tenant_id": str(x_tenant_id)}

        if store_id:
            conditions.append("up.store_id = :store_id")
            params["store_id"] = str(store_id)
        if prompt_type:
            conditions.append("up.prompt_type = :prompt_type")
            params["prompt_type"] = prompt_type

        where_clause = " AND ".join(conditions)

        # 总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM upsell_prompts up WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * size
        params["offset"] = offset
        params["size"] = size

        result = await db.execute(
            text(f"""
                SELECT
                    up.id, up.trigger_dish_id, up.suggest_dish_id,
                    up.prompt_text, up.prompt_type, up.is_enabled,
                    up.conversion_count, up.impression_count,
                    up.priority, up.store_id, up.metadata,
                    up.created_at, up.updated_at,
                    CASE WHEN up.impression_count > 0
                         THEN ROUND(up.conversion_count::numeric / up.impression_count, 4)
                         ELSE 0 END AS conversion_rate,
                    td.dish_name AS trigger_dish_name,
                    sd.dish_name AS suggest_dish_name
                FROM upsell_prompts up
                LEFT JOIN dishes td ON td.id = up.trigger_dish_id AND td.is_deleted = FALSE
                LEFT JOIN dishes sd ON sd.id = up.suggest_dish_id AND sd.is_deleted = FALSE
                WHERE {where_clause}
                ORDER BY up.impression_count DESC, up.created_at DESC
                OFFSET :offset LIMIT :size
            """),
            params,
        )
        rows = result.mappings().all()

        items = [
            {
                "id": str(r["id"]),
                "trigger_dish_id": str(r["trigger_dish_id"]),
                "trigger_dish_name": r["trigger_dish_name"],
                "suggest_dish_id": str(r["suggest_dish_id"]),
                "suggest_dish_name": r["suggest_dish_name"],
                "prompt_text": r["prompt_text"],
                "prompt_type": r["prompt_type"],
                "is_enabled": r["is_enabled"],
                "conversion_count": r["conversion_count"],
                "impression_count": r["impression_count"],
                "conversion_rate": float(r["conversion_rate"]),
                "priority": r["priority"],
                "store_id": str(r["store_id"]) if r["store_id"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return {"ok": True, "data": {"items": items, "total": total}}

    except SQLAlchemyError as exc:
        logger.error("list_upsell_prompts_error", error=str(exc))
        raise HTTPException(status_code=500, detail="查询话术列表失败")


@router.post("/generate-batch")
async def generate_batch(
    req: BatchGenerateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """批量生成高亲和菜品对的加购话术"""
    try:
        stats = await batch_generate_prompts(
            db=db,
            tenant_id=x_tenant_id,
            store_id=req.store_id,
            top_n=req.top_n,
            period=req.period,
            prompt_type=req.prompt_type,
        )
        return {"ok": True, "data": stats}
    except SQLAlchemyError as exc:
        logger.error("generate_batch_error", error=str(exc))
        raise HTTPException(status_code=500, detail="批量生成话术失败")


@router.post("/impression")
async def track_impression(
    req: ImpressionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """记录话术曝光"""
    try:
        await record_impression(db=db, tenant_id=x_tenant_id, prompt_id=req.prompt_id)
        return {"ok": True, "data": {}}
    except SQLAlchemyError as exc:
        logger.error("track_impression_error", error=str(exc))
        raise HTTPException(status_code=500, detail="记录曝光失败")


@router.post("/conversion")
async def track_conversion(
    req: ConversionRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """记录话术转化"""
    try:
        await record_conversion(db=db, tenant_id=x_tenant_id, prompt_id=req.prompt_id)
        return {"ok": True, "data": {}}
    except SQLAlchemyError as exc:
        logger.error("track_conversion_error", error=str(exc))
        raise HTTPException(status_code=500, detail="记录转化失败")
