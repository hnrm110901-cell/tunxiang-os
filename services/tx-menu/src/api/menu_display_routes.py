"""菜单展示 API — 为前端 DishCard/CategoryNav/SpecSheet 组件提供数据

GET  /api/v1/menu/display                     — 按分类返回完整菜单（POS/H5/Crew/TV 通用）
GET  /api/v1/menu/dishes/{id}/spec-sheet       — 菜品规格组（直接对接 SpecSheet 组件）
POST /api/v1/menu/dishes/batch-soldout         — 批量沽清/恢复
GET  /api/v1/menu/merchant-theme/{merchant_code} — 商户主题配置（品牌色/Logo/banner/样式/功能开关）

所有操作带 X-Tenant-ID 多租户隔离。
"""

from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/menu", tags=["menu-display"])


# ─── 鉴权依赖 ────────────────────────────────────────────────


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    """从请求头提取当前用户，写操作必须鉴权。"""
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


# ─── Pydantic 模型 ─────────────────────────────────────────────


class BatchSoldOutItem(BaseModel):
    dish_id: str
    sold_out: bool


class BatchSoldOutRequest(BaseModel):
    items: List[BatchSoldOutItem]
    store_id: str


# ─── 辅助 ──────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 菜单展示端点 ──────────────────────────────────────────────


@router.get("/display")
async def get_menu_display(
    channel: str = Query("pos", description="终端渠道: pos|h5|crew|tv"),
    store_id: Optional[str] = Query(None, description="门店ID，用于门店级价格/可用性"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回完整菜单数据，按分类组织，供前端 CategoryNav + DishCard 渲染。

    Response shape:
    {
      "ok": true,
      "data": {
        "categories": [{"id": "...", "name": "...", "icon": "...", "dish_count": N}],
        "dishes": [{"id": "...", "name": "...", "priceFen": N, "category": "...", ...}],
        "channel": "pos"
      }
    }
    """
    try:
        await _set_rls(db, x_tenant_id)

        # 1. 获取分类
        cat_result = await db.execute(
            text("""
                SELECT id, name, icon, sort_order
                FROM dish_categories
                WHERE tenant_id = :tid::uuid
                  AND is_deleted = false
                ORDER BY sort_order, name
            """),
            {"tid": x_tenant_id},
        )
        categories_raw = cat_result.mappings().all()

        # 2. 获取菜品
        channel_filter = ""
        if channel in ("h5", "tv"):
            channel_filter = " AND d.show_on_h5 = true"
        elif channel == "crew":
            channel_filter = " AND d.show_on_crew = true"

        store_filter = ""
        params: dict = {"tid": x_tenant_id}
        if store_id:
            store_filter = " AND d.store_id = :store_id::uuid"
            params["store_id"] = store_id

        dish_result = await db.execute(
            text(f"""
                SELECT d.id, d.name, d.category_id, d.price_fen, d.member_price_fen,
                       d.description, d.images, d.tags, d.allergens,
                       d.is_available, d.is_sold_out, d.pricing_method,
                       d.combo_type, d.sort_order,
                       c.name AS category_name
                FROM dishes d
                LEFT JOIN dish_categories c ON c.id = d.category_id AND c.tenant_id = d.tenant_id
                WHERE d.tenant_id = :tid::uuid
                  AND d.is_deleted = false
                  {channel_filter}
                  {store_filter}
                ORDER BY d.sort_order, d.name
            """),
            params,
        )
        dishes_raw = dish_result.mappings().all()

        # 3. 组装前端友好格式
        cat_dish_counts: dict[str, int] = {}
        dishes = []
        for d in dishes_raw:
            cat_id = str(d["category_id"]) if d["category_id"] else "uncategorized"
            cat_dish_counts[cat_id] = cat_dish_counts.get(cat_id, 0) + 1
            dishes.append(
                {
                    "id": str(d["id"]),
                    "name": d["name"],
                    "category": cat_id,
                    "priceFen": d["price_fen"] or 0,
                    "memberPriceFen": d["member_price_fen"],
                    "description": d["description"] or "",
                    "images": d["images"] or [],
                    "tags": d["tags"] or [],
                    "allergens": d["allergens"] or [],
                    "soldOut": bool(d["is_sold_out"]),
                    "pricingMethod": d["pricing_method"] or "normal",
                    "comboType": d["combo_type"],
                }
            )

        categories = [
            {
                "id": str(c["id"]),
                "name": c["name"],
                "icon": c["icon"] or "",
                "dishCount": cat_dish_counts.get(str(c["id"]), 0),
            }
            for c in categories_raw
        ]

        return {
            "ok": True,
            "data": {
                "categories": categories,
                "dishes": dishes,
                "channel": channel,
            },
        }

    except SQLAlchemyError as exc:
        log.error("menu_display.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ─── 菜品规格（SpecSheet 组件专用） ────────────────────────────


@router.get("/dishes/{dish_id}/spec-sheet")
async def get_dish_spec_sheet(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回菜品的规格组 + 做法，直接对接前端 SpecSheet 组件。

    Response shape matches SpecGroup[] interface:
    {
      "ok": true,
      "data": {
        "dish_id": "...",
        "dish_name": "...",
        "dish_price_fen": 8800,
        "dish_image": "...",
        "spec_groups": [
          {
            "id": "...",
            "name": "辣度",
            "type": "single",
            "required": true,
            "options": [
              {"id": "...", "label": "不辣", "extraPriceFen": 0},
              {"id": "...", "label": "微辣", "extraPriceFen": 0},
            ]
          }
        ]
      }
    }
    """
    try:
        await _set_rls(db, x_tenant_id)

        # 获取菜品基本信息
        dish_result = await db.execute(
            text("""
                SELECT id, name, price_fen, images
                FROM dishes
                WHERE id = :did::uuid
                  AND tenant_id = :tid::uuid
                  AND is_deleted = false
            """),
            {"did": dish_id, "tid": x_tenant_id},
        )
        dish = dish_result.mappings().one_or_none()
        if not dish:
            raise HTTPException(status_code=404, detail="菜品不存在")

        # 获取规格组 + 选项
        groups_result = await db.execute(
            text("""
                SELECT g.id, g.name, g.is_required, g.min_select, g.max_select, g.sort_order
                FROM dish_spec_groups g
                WHERE g.dish_id = :did::uuid
                  AND g.tenant_id = :tid::uuid
                  AND g.is_deleted = false
                ORDER BY g.sort_order, g.id
            """),
            {"did": dish_id, "tid": x_tenant_id},
        )
        groups_raw = groups_result.mappings().all()

        spec_groups = []
        for g in groups_raw:
            opts_result = await db.execute(
                text("""
                    SELECT id, name, price_delta_fen, sort_order
                    FROM dish_spec_options
                    WHERE group_id = :gid::uuid
                      AND tenant_id = :tid::uuid
                      AND is_deleted = false
                    ORDER BY sort_order, id
                """),
                {"gid": str(g["id"]), "tid": x_tenant_id},
            )
            opts = opts_result.mappings().all()

            spec_groups.append(
                {
                    "id": str(g["id"]),
                    "name": g["name"],
                    "type": "single" if (g["max_select"] or 1) == 1 else "multi",
                    "required": bool(g["is_required"]),
                    "options": [
                        {
                            "id": str(o["id"]),
                            "label": o["name"],
                            "extraPriceFen": o["price_delta_fen"] or 0,
                        }
                        for o in opts
                    ],
                }
            )

        # 获取做法（practices）作为额外规格组
        practice_result = await db.execute(
            text("""
                SELECT id, name, price_delta_fen, category, sort_order
                FROM dish_practices
                WHERE dish_id = :did::uuid
                  AND tenant_id = :tid::uuid
                  AND is_deleted = false
                ORDER BY category, sort_order, id
            """),
            {"did": dish_id, "tid": x_tenant_id},
        )
        practices = practice_result.mappings().all()

        # 按 category 分组做法
        practice_groups: dict[str, list] = {}
        for p in practices:
            cat = p["category"] or "做法"
            if cat not in practice_groups:
                practice_groups[cat] = []
            practice_groups[cat].append(
                {
                    "id": str(p["id"]),
                    "label": p["name"],
                    "extraPriceFen": p["price_delta_fen"] or 0,
                }
            )

        for cat, opts in practice_groups.items():
            spec_groups.append(
                {
                    "id": f"practice-{cat}",
                    "name": cat,
                    "type": "single",
                    "required": False,
                    "options": opts,
                }
            )

        images = dish["images"] or []
        return {
            "ok": True,
            "data": {
                "dish_id": str(dish["id"]),
                "dish_name": dish["name"],
                "dish_price_fen": dish["price_fen"] or 0,
                "dish_image": images[0] if images else None,
                "spec_groups": spec_groups,
            },
        }

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("spec_sheet.db_error", dish_id=dish_id, error=str(exc))
        raise HTTPException(status_code=500, detail="数据库查询失败")


# ─── 批量沽清 ──────────────────────────────────────────────────


@router.post("/dishes/batch-soldout")
async def batch_soldout(
    req: BatchSoldOutRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    current_user: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量标记/恢复菜品沽清状态（POS SoldOutPage 使用）。

    Body: { "items": [{"dish_id": "xxx", "sold_out": true}], "store_id": "..." }
    """
    try:
        await _set_rls(db, x_tenant_id)

        updated_ids = []
        for item in req.items:
            await db.execute(
                text("""
                    UPDATE dishes
                    SET is_sold_out = :sold_out,
                        updated_at = NOW()
                    WHERE id = :did::uuid
                      AND tenant_id = :tid::uuid
                      AND is_deleted = false
                """),
                {
                    "did": item.dish_id,
                    "sold_out": item.sold_out,
                    "tid": x_tenant_id,
                },
            )
            updated_ids.append(item.dish_id)

        await db.commit()

        log.info(
            "batch_soldout.success",
            store_id=req.store_id,
            count=len(updated_ids),
        )
        return {
            "ok": True,
            "data": {
                "updated_count": len(updated_ids),
                "updated_ids": updated_ids,
            },
        }

    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("batch_soldout.db_error", error=str(exc))
        raise HTTPException(status_code=500, detail="数据库操作失败")


# ─── 商户主题配置 ─────────────────────────────────────────────────


class DishCardStyleConfig(BaseModel):
    """菜品卡片样式"""

    variant: str = Field("default", description="default|elegant|compact|large-image")
    show_tag: bool = True
    show_description: bool = True
    price_color: str = "#FF6B35"
    background_color: str = "#132029"
    border_radius: str = "16rpx"


class BannerSlide(BaseModel):
    """Banner 轮播项"""

    id: str
    image_url: Optional[str] = None
    title: str
    subtitle: Optional[str] = None
    link: Optional[str] = None
    background_color: str = "#1A3A4A"


class FeatureToggles(BaseModel):
    """功能开关"""

    ai_recommend: bool = Field(True, description="AI推荐模块")
    reorder_banner: bool = Field(True, description="智能复购提醒")
    quick_entries: bool = Field(True, description="快捷入口区域")
    today_activities: bool = Field(True, description="今日活动")
    hot_dishes: bool = Field(True, description="热销推荐")
    ai_chat_assistant: bool = Field(True, description="AI点餐助手")


class MerchantThemeConfig(BaseModel):
    """商户主题配置"""

    merchant_code: str
    merchant_name: str
    # 品牌色
    brand_color: str = "#FF6B35"
    brand_color_dark: str = "#E55A2B"
    # Logo & Banner
    logo_url: Optional[str] = None
    banner_slides: list[BannerSlide] = Field(default_factory=list)
    # 导航栏
    nav_bar_color: str = "#0B1A20"
    nav_bar_text_color: str = "#E8F4F8"
    # 背景色
    page_background: str = "#0B1A20"
    card_background: str = "#132029"
    text_primary: str = "#E8F4F8"
    text_secondary: str = "#9EB5C0"
    # 菜品卡样式
    dish_card: DishCardStyleConfig = Field(default_factory=DishCardStyleConfig)
    # 功能开关
    features: FeatureToggles = Field(default_factory=FeatureToggles)


# ─── 默认/预置主题 ───────────────────────────────────────────────


_DEFAULT_THEME = MerchantThemeConfig(
    merchant_code="default",
    merchant_name="屯象OS",
    brand_color="#FF6B35",
    brand_color_dark="#E55A2B",
    banner_slides=[
        BannerSlide(id="1", title="春季新品上线", subtitle="限时特惠，先到先得", background_color="#1A3A4A"),
        BannerSlide(id="2", title="满100减20", subtitle="本周五六日全天有效", background_color="#1A2A3A"),
        BannerSlide(id="3", title="会员双倍积分", subtitle="消费即可累积，随时兑换", background_color="#2A1A3A"),
    ],
)

_PRESET_THEMES: dict[str, MerchantThemeConfig] = {
    "xuji": MerchantThemeConfig(
        merchant_code="xuji",
        merchant_name="徐记海鲜",
        brand_color="#C43A31",
        brand_color_dark="#A32D25",
        logo_url="https://cdn.tunxiangos.com/themes/xuji/logo.png",
        banner_slides=[
            BannerSlide(id="1", image_url="https://cdn.tunxiangos.com/themes/xuji/banner1.png", title="徐记海鲜·鲜味直达", subtitle="每日渔船直供，现杀现做", background_color="#2A1515"),
            BannerSlide(id="2", title="会员专享", subtitle="充值满赠，积分兑换专属好礼", background_color="#1A2020"),
            BannerSlide(id="3", title="宴席预订", subtitle="婚宴/商务宴/生日宴，尊享专属包间", background_color="#202020"),
        ],
        dish_card=DishCardStyleConfig(
            variant="elegant",
            show_tag=True,
            show_description=True,
            price_color="#C43A31",
            background_color="#1A2020",
            border_radius="20rpx",
        ),
        features=FeatureToggles(
            ai_recommend=True,
            reorder_banner=True,
            ai_chat_assistant=True,
        ),
    ),
    "zuiqianxian": MerchantThemeConfig(
        merchant_code="zuiqianxian",
        merchant_name="最黔线",
        brand_color="#D4A843",
        brand_color_dark="#B8922E",
        logo_url="https://cdn.tunxiangos.com/themes/zuiqianxian/logo.png",
        banner_slides=[
            BannerSlide(id="1", title="贵州风味·地道黔菜", subtitle="酸辣鲜香，开胃下饭", background_color="#2A2515"),
            BannerSlide(id="2", title="新菜品鉴", subtitle="主厨精选，限时尝鲜价", background_color="#1A2020"),
        ],
        dish_card=DishCardStyleConfig(
            variant="default",
            show_tag=True,
            show_description=True,
            price_color="#D4A843",
            background_color="#1A1A15",
            border_radius="16rpx",
        ),
        features=FeatureToggles(
            ai_recommend=True,
            reorder_banner=False,
            ai_chat_assistant=True,
        ),
    ),
    "shangshangongchu": MerchantThemeConfig(
        merchant_code="shangshangongchu",
        merchant_name="尚宫厨",
        brand_color="#8B4513",
        brand_color_dark="#6B3410",
        logo_url="https://cdn.tunxiangos.com/themes/shangshangongchu/logo.png",
        banner_slides=[
            BannerSlide(id="1", title="宫廷秘制·匠心出品", subtitle="传承经典，品味非凡", background_color="#1A1510"),
            BannerSlide(id="2", title="商务宴请首选", subtitle="雅致包间，尊享服务", background_color="#201510"),
        ],
        dish_card=DishCardStyleConfig(
            variant="elegant",
            show_tag=True,
            show_description=True,
            price_color="#8B4513",
            background_color="#1A1510",
            border_radius="24rpx",
        ),
        features=FeatureToggles(
            ai_recommend=True,
            reorder_banner=False,
            ai_chat_assistant=False,
        ),
    ),
}


def _get_merchant_theme(merchant_code: str) -> MerchantThemeConfig:
    """获取商户主题配置，未配置时返回默认主题降级。"""
    return _PRESET_THEMES.get(merchant_code, _DEFAULT_THEME)


# ─── 商户主题端点 ────────────────────────────────────────────────


@router.get("/merchant-theme/{merchant_code}")
async def get_merchant_theme(
    merchant_code: str,
) -> dict:
    """获取商户主题配置

    返回商户品牌色、Logo、Banner、菜品卡样式、功能开关等主题配置。
    如果商户未配置主题，使用默认主题降级。

    Args:
        merchant_code: 商户编码（如 xuji, zuiqianxian, shangshangongchu）

    Returns:
        {
          "ok": true,
          "data": {
            "merchant_code": "...",
            "merchant_name": "...",
            "brand_color": "#FF6B35",
            "brand_color_dark": "#E55A2B",
            ...
          }
        }
    """
    log.info("merchant_theme.fetch", merchant_code=merchant_code)

    try:
        theme = _get_merchant_theme(merchant_code)
        return {"ok": True, "data": theme.model_dump()}
    except Exception as exc:
        log.error("merchant_theme.fetch_failed", merchant_code=merchant_code, error=str(exc), exc_info=True)
        # 降级返回默认主题
        return {"ok": True, "data": _DEFAULT_THEME.model_dump()}
