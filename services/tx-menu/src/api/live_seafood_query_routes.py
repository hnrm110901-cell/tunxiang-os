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


# ─── Mock 数据（数据库接入前使用）──────────────────────────────────────────────

_MOCK_TANKS = [
    {
        "zone_id": "00000000-0000-0000-0000-000000000001",
        "zone_code": "A1",
        "zone_name": "石斑鱼缸",
        "current_stock_count": 12,
        "current_stock_weight_g": 18500,
        "is_active": True,
        "featured_dish": "石斑鱼",
        "price_display": "¥128/斤",
        "pricing_method": "weight",
    },
    {
        "zone_id": "00000000-0000-0000-0000-000000000002",
        "zone_code": "B2",
        "zone_name": "对虾缸",
        "current_stock_count": 0,
        "current_stock_weight_g": 3500,
        "is_active": True,
        "featured_dish": "对虾",
        "price_display": "¥68/斤",
        "pricing_method": "weight",
    },
    {
        "zone_id": "00000000-0000-0000-0000-000000000003",
        "zone_code": "C1",
        "zone_name": "龙虾缸",
        "current_stock_count": 5,
        "current_stock_weight_g": 12000,
        "is_active": True,
        "featured_dish": "波士顿龙虾",
        "price_display": "¥298/头",
        "pricing_method": "count",
    },
    {
        "zone_id": "00000000-0000-0000-0000-000000000004",
        "zone_code": "D1",
        "zone_name": "蟹池",
        "current_stock_count": 0,
        "current_stock_weight_g": 0,
        "is_active": True,
        "featured_dish": "花蟹",
        "price_display": "¥88/斤",
        "pricing_method": "weight",
    },
]

_MOCK_DISHES: dict[str, list[dict]] = {
    "A1": [
        {
            "dish_id": "d-sf-001",
            "dish_name": "石斑鱼",
            "pricing_method": "weight",
            "price_per_unit_fen": 12800,
            "display_unit": "斤",
            "weight_unit": "jin",
            "live_stock_count": 12,
            "live_stock_weight_g": 18500,
            "min_order_qty": 0.5,
            "image_url": None,
            "price_display": "¥128/斤",
        },
    ],
    "B2": [
        {
            "dish_id": "d-sf-002",
            "dish_name": "对虾",
            "pricing_method": "weight",
            "price_per_unit_fen": 6800,
            "display_unit": "斤",
            "weight_unit": "jin",
            "live_stock_count": 0,
            "live_stock_weight_g": 3500,
            "min_order_qty": 0.5,
            "image_url": None,
            "price_display": "¥68/斤",
        },
    ],
    "C1": [
        {
            "dish_id": "d-sf-003",
            "dish_name": "波士顿龙虾",
            "pricing_method": "count",
            "price_per_unit_fen": 29800,
            "display_unit": "头",
            "weight_unit": None,
            "live_stock_count": 5,
            "live_stock_weight_g": 12000,
            "min_order_qty": 1.0,
            "image_url": None,
            "price_display": "¥298/头",
        },
        {
            "dish_id": "d-sf-004",
            "dish_name": "澳洲龙虾",
            "pricing_method": "weight",
            "price_per_unit_fen": 48000,
            "display_unit": "斤",
            "weight_unit": "jin",
            "live_stock_count": 2,
            "live_stock_weight_g": 4000,
            "min_order_qty": 1.0,
            "image_url": None,
            "price_display": "¥480/斤",
        },
    ],
    "D1": [
        {
            "dish_id": "d-sf-005",
            "dish_name": "花蟹",
            "pricing_method": "weight",
            "price_per_unit_fen": 8800,
            "display_unit": "斤",
            "weight_unit": "jin",
            "live_stock_count": 0,
            "live_stock_weight_g": 0,
            "min_order_qty": 0.5,
            "image_url": None,
            "price_display": "¥88/斤",
        },
    ],
}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/tanks", summary="门店鱼缸区域列表（含库存摘要）")
async def list_tanks(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回门店所有鱼缸区域及其库存摘要，供前端绘制鱼缸选品卡片列表。

    TODO: 替换 Mock 数据为真实数据库查询：
    ```sql
    SELECT
        tz.id AS zone_id,
        tz.zone_code,
        tz.zone_name,
        tz.is_active,
        COALESCE(SUM(d.live_stock_count), 0) AS current_stock_count,
        COALESCE(SUM(d.live_stock_weight_g), 0) AS current_stock_weight_g,
        (SELECT dish_name FROM dishes
         WHERE tank_zone_id = tz.id AND is_deleted = false
         ORDER BY live_stock_count DESC LIMIT 1) AS featured_dish,
        (SELECT price_per_unit_fen FROM dishes
         WHERE tank_zone_id = tz.id AND is_deleted = false
         ORDER BY live_stock_count DESC LIMIT 1) AS featured_price,
        (SELECT display_unit FROM dishes
         WHERE tank_zone_id = tz.id AND is_deleted = false
         ORDER BY live_stock_count DESC LIMIT 1) AS featured_unit,
        (SELECT pricing_method FROM dishes
         WHERE tank_zone_id = tz.id AND is_deleted = false
         ORDER BY live_stock_count DESC LIMIT 1) AS pricing_method
    FROM fish_tank_zones tz
    LEFT JOIN dishes d ON d.tank_zone_id = tz.id AND d.is_deleted = false
    WHERE tz.store_id = :store_id
      AND tz.tenant_id = :tenant_id
      AND tz.is_deleted = false
    GROUP BY tz.id, tz.zone_code, tz.zone_name, tz.is_active
    ORDER BY tz.sort_order, tz.zone_code
    ```
    """
    # ── Mock 数据（接入数据库后移除） ──────────────────────
    log.info("live_seafood.list_tanks.mock", store_id=store_id)
    return _ok({"tanks": _MOCK_TANKS})


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

    TODO: 替换 Mock 数据为真实数据库查询：
    ```sql
    SELECT
        d.id AS dish_id,
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
    JOIN fish_tank_zones tz ON tz.id = d.tank_zone_id
    WHERE tz.zone_code = :zone_code
      AND tz.store_id = :store_id
      AND tz.tenant_id = :tenant_id
      AND tz.is_deleted = false
      AND d.is_deleted = false
      AND d.pricing_method IN ('weight', 'count')
    ORDER BY d.live_stock_count DESC, d.dish_name
    ```
    """
    zone_code_upper = zone_code.upper()

    # ── Mock 数据（接入数据库后移除） ──────────────────────
    log.info("live_seafood.list_tank_dishes.mock", zone_code=zone_code, store_id=store_id)

    # 查找 zone 元数据
    tank = next((t for t in _MOCK_TANKS if t["zone_code"] == zone_code_upper), None)
    if not tank:
        raise HTTPException(status_code=404, detail=f"鱼缸区域 {zone_code} 不存在")

    dishes = _MOCK_DISHES.get(zone_code_upper, [])

    return _ok({
        "zone_code": zone_code_upper,
        "zone_name": tank["zone_name"],
        "dishes": dishes,
    })
