"""海报数据生成器 — 为前端提供海报配置JSON

生成海报所需的结构化数据（标题、副标题、CTA、配色、图片URL等），
实际图片渲染由前端Canvas/SVG完成。

S3W11-12 Smart Content Factory
"""

from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 海报模板定义
# ---------------------------------------------------------------------------

POSTER_TEMPLATES: dict[str, dict] = {
    "new_dish": {
        "name": "新品上市",
        "description": "全新菜品发布海报，突出菜品卖点和首发优惠",
        "default_background": "#FF6B35",
        "accent_color": "#FFFFFF",
        "layout": "center_focus",
        "cta_default": "立即尝鲜",
    },
    "seasonal": {
        "name": "时令推荐",
        "description": "应季食材/菜品推荐，营造自然应季氛围",
        "default_background": "#2D5016",
        "accent_color": "#F5E6CC",
        "layout": "split_horizontal",
        "cta_default": "限时品鉴",
    },
    "holiday": {
        "name": "节日特惠",
        "description": "节假日营销海报，喜庆热闹风格",
        "default_background": "#C41E3A",
        "accent_color": "#FFD700",
        "layout": "festive",
        "cta_default": "节日特享",
    },
    "member_day": {
        "name": "会员日",
        "description": "会员专属福利日海报，突出尊享感",
        "default_background": "#1A1A2E",
        "accent_color": "#E94560",
        "layout": "premium",
        "cta_default": "会员专享",
    },
    "flash_sale": {
        "name": "限时抢购",
        "description": "限时折扣/秒杀海报，营造紧迫感",
        "default_background": "#FF4500",
        "accent_color": "#FFFF00",
        "layout": "countdown",
        "cta_default": "立即抢购",
    },
}


# ---------------------------------------------------------------------------
# PosterGenerator
# ---------------------------------------------------------------------------


class PosterGenerator:
    """海报数据生成器 — 为前端提供海报配置JSON"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 模板列表
    # ------------------------------------------------------------------

    def get_poster_templates(self) -> list[dict]:
        """返回所有可用海报模板及预览描述"""
        templates: list[dict] = []
        for key, tpl in POSTER_TEMPLATES.items():
            templates.append(
                {
                    "template_id": key,
                    "name": tpl["name"],
                    "description": tpl["description"],
                    "default_background": tpl["default_background"],
                    "accent_color": tpl["accent_color"],
                    "layout": tpl["layout"],
                }
            )
        return templates

    # ------------------------------------------------------------------
    # 生成海报数据
    # ------------------------------------------------------------------

    async def generate_poster_data(
        self,
        tenant_id: str,
        db: AsyncSession,
        dish_id: Optional[str] = None,
        event_name: Optional[str] = None,
        template: str = "default",
    ) -> dict:
        """生成海报配置JSON

        Returns:
            {
                title, subtitle, cta_text, background_color, accent_color,
                dish_image_url, brand_logo_url, qr_code_url, layout, template_id
            }
        """
        await self._set_tenant(db, tenant_id)

        # 匹配模板（未知模板回退到 new_dish）
        tpl = POSTER_TEMPLATES.get(template, POSTER_TEMPLATES["new_dish"])
        tpl_key = template if template in POSTER_TEMPLATES else "new_dish"

        # 获取品牌logo
        brand_row = await db.execute(
            text("""
                SELECT brand_name, logo_url
                FROM brand_strategies
                WHERE tenant_id = :tid AND is_deleted = false
                ORDER BY updated_at DESC LIMIT 1
            """),
            {"tid": tenant_id},
        )
        brand = brand_row.mappings().first()
        brand_name = brand["brand_name"] if brand and brand["brand_name"] else "品牌"
        brand_logo_url = brand["logo_url"] if brand and brand.get("logo_url") else ""

        # 菜品信息
        dish_name = ""
        dish_image_url = ""
        dish_price_display = ""

        if dish_id:
            dish_row = await db.execute(
                text("""
                    SELECT name, description, price_fen, image_url
                    FROM dishes
                    WHERE id = :did AND tenant_id = :tid AND is_deleted = false
                """),
                {"did": dish_id, "tid": tenant_id},
            )
            dish = dish_row.mappings().first()
            if dish:
                dish_name = dish["name"] or ""
                dish_image_url = dish["image_url"] if dish.get("image_url") else ""
                price_fen = dish["price_fen"] or 0
                dish_price_display = f"¥{price_fen / 100:.0f}"

        # 构建标题和副标题
        if dish_name and event_name:
            title = f"{event_name}"
            subtitle = f"{dish_name} {dish_price_display}".strip()
        elif dish_name:
            title = f"{tpl['name']}｜{dish_name}"
            subtitle = dish_price_display or f"{brand_name}诚意出品"
        elif event_name:
            title = event_name
            subtitle = f"{brand_name}邀您共享"
        else:
            title = f"{brand_name}{tpl['name']}"
            subtitle = "更多惊喜等你发现"

        return {
            "template_id": tpl_key,
            "title": title,
            "subtitle": subtitle,
            "cta_text": tpl["cta_default"],
            "background_color": tpl["default_background"],
            "accent_color": tpl["accent_color"],
            "layout": tpl["layout"],
            "dish_image_url": dish_image_url,
            "brand_logo_url": brand_logo_url,
            "brand_name": brand_name,
            "qr_code_url": "",
        }
