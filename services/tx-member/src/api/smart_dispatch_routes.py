"""会员等级智能调度 API 端点

7 个端点：个性化首页、等级菜单、排队调度、个性化优惠、预订调度、应用等级权益、升级机会
"""
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/member/dispatch", tags=["member-dispatch"])


# ── 请求模型 ──────────────────────────────────────────────────

class ReservationRequest(BaseModel):
    customer_id: str
    store_id: str
    party_size: int = Field(ge=1, le=50, default=2)
    date: str
    time: str = ""
    room_preference: str = ""


class ApplyBenefitsRequest(BaseModel):
    customer_id: str
    order_id: str


# ── 1. 个性化首页 ────────────────────────────────────────────

@router.get("/home/{customer_id}")
async def get_personalized_home(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """按等级+历史+场景定制个性化首页"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.get_personalized_home
    from services.smart_dispatcher import LEVEL_NAMES_CN, _get_banner, _get_available_benefits, _get_scene_actions

    # 占位逻辑：默认 normal 等级
    level = "normal"
    level_cn = LEVEL_NAMES_CN.get(level, "会员")

    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "level": level,
            "greeting": f"尊敬的{level_cn}",
            "exclusive_banner": _get_banner(level),
            "recommended_dishes": [],
            "available_benefits": _get_available_benefits(level),
            "upgrade_progress": {
                "has_next_level": True,
                "next_level": "silver",
                "next_level_cn": "银卡会员",
                "remaining_fen": 500_000,
                "progress_percent": 0.0,
                "message": "再消费5000元即可升级银卡会员",
            },
            "scene_actions": _get_scene_actions(level),
        },
    }


# ── 2. 等级菜单 ──────────────────────────────────────────────

@router.get("/menu/{customer_id}/{store_id}")
async def get_level_menu(
    customer_id: str,
    store_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """按等级展示专属菜品/价格"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.dispatch_menu
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "store_id": store_id,
            "level": "normal",
            "menu_type": "standard",
            "price_tag": "standard",
            "sections": ["standard"],
            "show_upgrade_banner": True,
            "perks": ["标准菜单"],
            "upgrade_hint": "开通会员即可享受会员价优惠",
        },
    }


# ── 3. 排队调度 ──────────────────────────────────────────────

@router.get("/queue/{customer_id}/{store_id}")
async def get_queue_dispatch(
    customer_id: str,
    store_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """VIP 快速通道排队调度"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.dispatch_queue
    return {
        "ok": True,
        "data": {
            "queue_ticket": "PLACEHOLDER",
            "customer_id": customer_id,
            "store_id": store_id,
            "level": "normal",
            "priority_score": 0,
            "queue_type": "normal",
            "estimated_wait_minutes": 20,
            "message": "您好，已为您取号，请耐心等候",
            "perks": ["正常排队"],
        },
    }


# ── 4. 个性化优惠 ────────────────────────────────────────────

@router.get("/offers/{customer_id}")
async def get_personalized_offers(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """按等级推送个性化优惠"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.dispatch_offer
    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "level": "normal",
            "offers": [
                {"type": "new_customer", "name": "新客满100减20", "threshold_fen": 10000, "amount_fen": 2000},
                {"type": "upgrade_guide", "name": "升级银卡享会员价", "target_level": "silver"},
            ],
        },
    }


# ── 5. 预订调度 ──────────────────────────────────────────────

@router.post("/reservation")
async def create_reservation_dispatch(
    body: ReservationRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """高等级会员优先分配包厢"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.dispatch_reservation
    return {
        "ok": True,
        "data": {
            "reservation_id": "placeholder",
            "customer_id": body.customer_id,
            "level": "normal",
            "party_size": body.party_size,
            "requested_date": body.date,
            "store_id": body.store_id,
            "room_type": "standard",
            "priority": "normal",
            "free_upgrade": False,
            "perks": ["正常排期", "包厢需加收"],
            "room_surcharge": True,
        },
    }


# ── 6. 应用等级权益 ──────────────────────────────────────────

@router.post("/apply-benefits")
async def apply_benefits(
    body: ApplyBenefitsRequest,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """自动应用等级权益到订单（无需用户操作）"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.apply_level_benefits
    return {
        "ok": True,
        "data": {
            "customer_id": body.customer_id,
            "order_id": body.order_id,
            "level": "normal",
            "applied_benefits": [],
            "benefits_count": 0,
            "auto_applied": True,
        },
    }


# ── 7. 升级机会 ──────────────────────────────────────────────

@router.get("/upgrade/{customer_id}")
async def get_upgrade_opportunity(
    customer_id: str,
    x_tenant_id: str = Header("", alias="X-Tenant-ID"),
):
    """升级机会检测: 购物车/结账页面的升级激励"""
    # TODO: 注入真实 DB session 后调用 smart_dispatcher.check_upgrade_opportunity
    from services.smart_dispatcher import LEVEL_NAMES_CN

    return {
        "ok": True,
        "data": {
            "customer_id": customer_id,
            "current_level": "normal",
            "current_level_cn": LEVEL_NAMES_CN["normal"],
            "total_growth_value": 0,
            "has_next_level": True,
            "next_level": "silver",
            "next_level_cn": LEVEL_NAMES_CN["silver"],
            "remaining_fen": 500_000,
            "progress_percent": 0.0,
            "message": "再消费5000元即可升级银卡会员",
        },
    }
