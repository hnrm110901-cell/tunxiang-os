"""菜品 Repository — 真实 DB 查询层

封装 Dish / DishCategory 的 CRUD，使用 SQLAlchemy async 查询。
所有方法设置 RLS tenant context 后执行查询。
"""
import uuid
from typing import Optional

from sqlalchemy import select, func, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Dish, DishCategory, DishIngredient


class DishRepository:
    """菜品 Repository — 封装真实 DB 查询"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        """设置 RLS tenant context"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ─── 菜品 CRUD ───

    async def list_dishes(
        self,
        store_id: str,
        category_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询菜品列表"""
        await self._set_tenant()

        base = (
            select(Dish)
            .where(Dish.tenant_id == self._tenant_uuid)
            .where(Dish.is_deleted == False)  # noqa: E712
        )
        count_base = (
            select(func.count(Dish.id))
            .where(Dish.tenant_id == self._tenant_uuid)
            .where(Dish.is_deleted == False)  # noqa: E712
        )

        if category_id:
            cat_uuid = uuid.UUID(category_id)
            base = base.where(Dish.category_id == cat_uuid)
            count_base = count_base.where(Dish.category_id == cat_uuid)

        # total
        total_result = await self.db.execute(count_base)
        total = total_result.scalar() or 0

        # items
        offset = (page - 1) * size
        query = base.order_by(Dish.sort_order, Dish.created_at.desc()).offset(offset).limit(size)
        result = await self.db.execute(query)
        rows = result.scalars().all()

        items = [self._dish_to_dict(d) for d in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_dish(self, dish_id: str) -> Optional[dict]:
        """查询单个菜品详情"""
        await self._set_tenant()

        result = await self.db.execute(
            select(Dish)
            .where(Dish.id == uuid.UUID(dish_id))
            .where(Dish.tenant_id == self._tenant_uuid)
            .where(Dish.is_deleted == False)  # noqa: E712
        )
        dish = result.scalar_one_or_none()
        if not dish:
            return None
        return self._dish_to_dict(dish)

    async def create_dish(self, data: dict) -> dict:
        """创建菜品"""
        await self._set_tenant()

        dish = Dish(
            id=uuid.uuid4(),
            tenant_id=self._tenant_uuid,
            dish_name=data["dish_name"],
            dish_code=data["dish_code"],
            price_fen=data["price_fen"],
            category_id=uuid.UUID(data["category_id"]) if data.get("category_id") else None,
            kitchen_station=data.get("kitchen_station"),
            preparation_time=data.get("preparation_time"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            unit=data.get("unit", "份"),
            is_available=data.get("is_available", True),
        )
        self.db.add(dish)
        await self.db.flush()
        return self._dish_to_dict(dish)

    async def update_dish(self, dish_id: str, data: dict) -> dict:
        """更新菜品"""
        await self._set_tenant()

        result = await self.db.execute(
            select(Dish)
            .where(Dish.id == uuid.UUID(dish_id))
            .where(Dish.tenant_id == self._tenant_uuid)
            .where(Dish.is_deleted == False)  # noqa: E712
        )
        dish = result.scalar_one_or_none()
        if not dish:
            raise ValueError(f"Dish not found: {dish_id}")

        updatable_fields = [
            "dish_name", "price_fen", "original_price_fen", "cost_fen",
            "description", "image_url", "kitchen_station", "preparation_time",
            "unit", "spicy_level", "is_available", "is_recommended", "sort_order",
            "tags", "allergens", "calories",
        ]
        for field in updatable_fields:
            if field in data:
                setattr(dish, field, data[field])

        if "category_id" in data:
            dish.category_id = uuid.UUID(data["category_id"]) if data["category_id"] else None

        await self.db.flush()
        return self._dish_to_dict(dish)

    async def delete_dish(self, dish_id: str) -> bool:
        """软删除菜品"""
        await self._set_tenant()

        result = await self.db.execute(
            update(Dish)
            .where(Dish.id == uuid.UUID(dish_id))
            .where(Dish.tenant_id == self._tenant_uuid)
            .where(Dish.is_deleted == False)  # noqa: E712
            .values(is_deleted=True)
        )
        return result.rowcount > 0

    # ─── 分类 ───

    async def list_categories(self, store_id: str) -> list:
        """查询菜品分类列表"""
        await self._set_tenant()

        result = await self.db.execute(
            select(DishCategory)
            .where(DishCategory.tenant_id == self._tenant_uuid)
            .where(DishCategory.is_deleted == False)  # noqa: E712
            .order_by(DishCategory.sort_order, DishCategory.name)
        )
        rows = result.scalars().all()
        return [
            {
                "id": str(c.id),
                "name": c.name,
                "code": c.code,
                "parent_id": str(c.parent_id) if c.parent_id else None,
                "sort_order": c.sort_order,
                "is_active": c.is_active,
            }
            for c in rows
        ]

    # ─── 内部工具 ───

    @staticmethod
    def _dish_to_dict(dish: Dish) -> dict:
        return {
            "id": str(dish.id),
            "dish_name": dish.dish_name,
            "dish_code": dish.dish_code,
            "category_id": str(dish.category_id) if dish.category_id else None,
            "price_fen": dish.price_fen,
            "original_price_fen": dish.original_price_fen,
            "cost_fen": dish.cost_fen,
            "profit_margin": float(dish.profit_margin) if dish.profit_margin else None,
            "description": dish.description,
            "image_url": dish.image_url,
            "kitchen_station": dish.kitchen_station,
            "preparation_time": dish.preparation_time,
            "unit": dish.unit,
            "spicy_level": dish.spicy_level,
            "is_available": dish.is_available,
            "is_recommended": dish.is_recommended,
            "sort_order": dish.sort_order,
            "total_sales": dish.total_sales,
            "total_revenue_fen": dish.total_revenue_fen,
            "rating": float(dish.rating) if dish.rating else None,
            "tags": dish.tags,
            "created_at": dish.created_at.isoformat() if dish.created_at else None,
        }
