"""活鲜查询 API — 前端点单专用（服务员端 / POS 端）

路由前缀: /api/v1/live-seafood
用途: 为前端点单流程提供简洁的活鲜数据查询接口。
      与 live_seafood_routes.py 的后台管理接口分离，保持各自独立演化。

Endpoints:
  GET /api/v1/live-seafood/tanks?store_id=          — 门店鱼缸列表（含库存摘要）
  GET /api/v1/live-seafood/tanks/{zone_code}/dishes?store_id=  — 指定鱼缸当前可点菜品
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/live-seafood", tags=["live-seafood-query"])


# ─── 工具 ─────────────────────────────────────────────────────────────────────


def _tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _price_display(price_per_unit_fen: Optional[int], display_unit: Optional[str]) -> str:
    """生成简洁价格文本，如 ¥128/斤"""
    if not price_per_unit_fen:
        return "时价"
    yuan = price_per_unit_fen / 100
    price_str = f"{int(yuan)}" if yuan == int(yuan) else f"{yuan:.1f}"
    return f"¥{price_str}/{display_unit or '份'}"


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/tanks", summary="门店鱼缸区域列表（含库存摘要）")
async def list_tanks(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回门店所有鱼缸区域及其库存摘要，供前端绘制鱼缸选品卡片列表。
    """
    tenant_id = _tenant(request)
    await _set_rls(db, tenant_id)

    try:
        result = await db.execute(
            text("""
                SELECT
                    tz.id::TEXT         AS zone_id,
                    tz.zone_code,
                    tz.zone_name,
                    tz.is_active,
                    COALESCE(SUM(d.live_stock_count), 0)    AS current_stock_count,
                    COALESCE(SUM(d.live_stock_weight_g), 0) AS current_stock_weight_g,
                    (
                        SELECT dish_name FROM dishes
                        WHERE tank_zone_id = tz.id AND is_deleted = false
                        ORDER BY live_stock_count DESC LIMIT 1
                    ) AS featured_dish,
                    (
                        SELECT price_per_unit_fen FROM dishes
                        WHERE tank_zone_id = tz.id AND is_deleted = false
                        ORDER BY live_stock_count DESC LIMIT 1
                    ) AS featured_price,
                    (
                        SELECT display_unit FROM dishes
                        WHERE tank_zone_id = tz.id AND is_deleted = false
                        ORDER BY live_stock_count DESC LIMIT 1
                    ) AS featured_unit,
                    (
                        SELECT pricing_method FROM dishes
                        WHERE tank_zone_id = tz.id AND is_deleted = false
                        ORDER BY live_stock_count DESC LIMIT 1
                    ) AS pricing_method
                FROM fish_tank_zones tz
                LEFT JOIN dishes d ON d.tank_zone_id = tz.id AND d.is_deleted = false
                WHERE tz.store_id  = :store_id
                  AND tz.tenant_id = :tenant_id
                  AND tz.is_deleted = false
                GROUP BY tz.id, tz.zone_code, tz.zone_name, tz.is_active
                ORDER BY tz.sort_order, tz.zone_code
            """),
            {"store_id": store_id, "tenant_id": tenant_id},
        )
        rows = result.fetchall()
    except SQLAlchemyError as exc:
        log.error("live_seafood.list_tanks.db_error", store_id=store_id, error=str(exc))
        return _ok({"tanks": []})

    tanks = [
        {
            "zone_id": r[0],
            "zone_code": r[1],
            "zone_name": r[2],
            "is_active": r[3],
            "current_stock_count": int(r[4]),
            "current_stock_weight_g": int(r[5]),
            "featured_dish": r[6],
            "price_display": _price_display(r[7], r[8]),
            "pricing_method": r[9],
        }
        for r in rows
    ]

    log.info("live_seafood.list_tanks", store_id=store_id, count=len(tanks))
    return _ok({"tanks": tanks})


@router.get("/tanks/{zone_code}/dishes", summary="指定鱼缸区域的可点活鲜菜品")
async def list_tank_dishes(
    zone_code: str,
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回指定鱼缸区域当前可点的活鲜菜品（含实时库存）。
    服务员扫描鱼缸QR码后跳转到此接口获取菜品列表。
    """
    tenant_id = _tenant(request)
    await _set_rls(db, tenant_id)
    zone_code_upper = zone_code.upper()

    try:
        # 查鱼缸区域元数据
        zone_result = await db.execute(
            text("""
                SELECT id::TEXT, zone_code, zone_name
                FROM fish_tank_zones
                WHERE zone_code  = :zone_code
                  AND store_id   = :store_id
                  AND tenant_id  = :tenant_id
                  AND is_deleted = false
                LIMIT 1
            """),
            {"zone_code": zone_code_upper, "store_id": store_id, "tenant_id": tenant_id},
        )
        zone_row = zone_result.fetchone()
    except SQLAlchemyError as exc:
        log.error("live_seafood.list_tank_dishes.db_error", zone_code=zone_code, store_id=store_id, error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败") from exc

    if not zone_row:
        raise HTTPException(status_code=404, detail=f"鱼缸区域 {zone_code} 不存在")

    zone_id = zone_row[0]
    zone_name = zone_row[2]

    try:
        dishes_result = await db.execute(
            text("""
                SELECT
                    d.id::TEXT          AS dish_id,
                    d.dish_name,
                    d.pricing_method,
                    d.price_per_unit_fen,
                    d.display_unit,
                    d.weight_unit,
                    d.live_stock_count,
                    d.live_stock_weight_g,
                    d.min_order_qty,
                    d.image_url
                FROM dishes d
                WHERE d.tank_zone_id = :zone_id
                  AND d.tenant_id    = :tenant_id
                  AND d.is_deleted   = false
                  AND d.pricing_method IN ('weight', 'count')
                ORDER BY d.live_stock_count DESC, d.dish_name
            """),
            {"zone_id": zone_id, "tenant_id": tenant_id},
        )
        dish_rows = dishes_result.fetchall()
    except SQLAlchemyError as exc:
        log.error("live_seafood.list_tank_dishes.dishes_db_error", zone_id=zone_id, error=str(exc))
        dish_rows = []

    dishes = [
        {
            "dish_id": r[0],
            "dish_name": r[1],
            "pricing_method": r[2],
            "price_per_unit_fen": r[3],
            "display_unit": r[4],
            "weight_unit": r[5],
            "live_stock_count": r[6],
            "live_stock_weight_g": r[7],
            "min_order_qty": float(r[8]) if r[8] else 1.0,
            "image_url": r[9],
            "price_display": _price_display(r[3], r[4]),
        }
        for r in dish_rows
    ]

    log.info("live_seafood.list_tank_dishes", zone_code=zone_code_upper, store_id=store_id, dish_count=len(dishes))
    return _ok(
        {
            "zone_code": zone_code_upper,
            "zone_name": zone_name,
            "dishes": dishes,
        }
    )
