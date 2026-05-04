"""电视点菜墙 API 路由"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..services import tv_menu_service

router = APIRouter(prefix="/api/v1/tv-menu", tags=["TV菜单墙"])


def _tenant(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(400, "X-Tenant-ID required")
    return x_tenant_id


@router.get("/layout/{store_id}")
async def get_layout(store_id: str, screens: int = Query(4), tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_menu_wall_layout(store_id, screens, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/screen/{store_id}/{screen_id}")
async def get_screen(
    store_id: str, screen_id: int, zone: str = "signature", tenant_id: str = Header(alias="X-Tenant-ID")
):
    data = await tv_menu_service.get_screen_content(store_id, screen_id, zone, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/status/{store_id}")
async def get_status(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_realtime_status(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/recommend/{store_id}")
async def get_recommend(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_time_based_recommendation(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/weather/{store_id}")
async def get_weather(store_id: str, weather: str = "normal", tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_weather_recommendation(store_id, weather, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/smart-layout/{store_id}")
async def get_smart(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_smart_layout(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


class TVOrderRequest(BaseModel):
    store_id: str
    table_id: str
    items: list[dict]
    customer_id: Optional[str] = None


@router.post("/order")
async def tv_order(req: TVOrderRequest, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.trigger_order_from_tv(
        req.store_id, req.table_id, req.items, req.customer_id, tenant_id, db=None
    )
    return {"ok": True, "data": data}


class ScreenRegisterRequest(BaseModel):
    store_id: str
    screen_id: str
    ip: str
    position: str
    size_inches: int = 55


@router.post("/screen/register")
async def register_screen(req: ScreenRegisterRequest, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.register_screen(
        req.store_id, req.screen_id, req.ip, req.position, req.size_inches, tenant_id, db=None
    )
    return {"ok": True, "data": data}


@router.get("/config/{store_id}")
async def get_config(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_screen_group_config(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/seafood-board/{store_id}")
async def seafood_board(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_seafood_price_board(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/ranking/{store_id}")
async def ranking(store_id: str, metric: str = "hot_sales", tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_ranking_board(store_id, metric, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/waitlist/{store_id}")
async def waitlist_current(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_waitlist_current(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/waitlist-detail/{store_id}")
async def waitlist_detailed(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_waitlist_detailed(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/categories/{store_id}")
async def categories(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_categories(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/dishes/{store_id}/{category_id}")
async def dishes_by_category(
    store_id: str,
    category_id: str,
    is_available: bool = Query(False),
    tenant_id: str = Header(alias="X-Tenant-ID"),
):
    data = await tv_menu_service.get_dishes_by_category(
        store_id, category_id, is_available, tenant_id, db=None
    )
    return {"ok": True, "data": data}


@router.get("/sales-today/{store_id}")
async def sales_today(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_sales_today(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/combos/{store_id}")
async def combos(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_combo_showcase(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/festival/{store_id}")
async def festival_theme(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_festival_theme(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/weather-mock")
async def weather_mock(city: str = Query("beijing")):
    """Mock 天气端点 — 不依赖租户，单纯 mock 天气数据"""
    data = await tv_menu_service.get_weather_mock(city)
    return {"ok": True, "data": data}


class ScreenHeartbeatRequest(BaseModel):
    store_id: str
    screen_id: str


@router.post("/screen/heartbeat")
async def screen_heartbeat(req: ScreenHeartbeatRequest, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.screen_heartbeat(req.store_id, req.screen_id, tenant_id, db=None)
    return {"ok": True, "data": data}


class ScreenUnregisterRequest(BaseModel):
    store_id: str
    screen_id: str


@router.post("/screen/unregister")
async def screen_unregister(req: ScreenUnregisterRequest, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.screen_unregister(req.store_id, req.screen_id, tenant_id, db=None)
    return {"ok": True, "data": data}


class MarkSoldOutRequest(BaseModel):
    store_id: str
    dish_ids: list[str]


@router.post("/sold-out")
async def mark_sold_out(req: MarkSoldOutRequest, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.mark_sold_out(req.store_id, req.dish_ids, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/sold-out/{store_id}")
async def sold_out_list(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_sold_out_list(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/timeslot/{store_id}")
async def timeslot_switch(store_id: str, tenant_id: str = Header(alias="X-Tenant-ID")):
    data = await tv_menu_service.get_timeslot_switch(store_id, tenant_id, db=None)
    return {"ok": True, "data": data}


@router.get("/health")
async def health():
    """TV 菜单服务健康检查 — 不需要租户"""
    data = await tv_menu_service.get_health()
    return {"ok": True, "data": data}
