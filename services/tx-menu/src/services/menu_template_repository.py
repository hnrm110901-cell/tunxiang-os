"""菜单模板 Repository — 内存 → DB 迁移（v095）

覆盖 menu_template.py 的五块内存存储：
  _templates       → menu_templates + menu_template_dishes
  _store_menus     → store_menu_publishes（JOIN menu_template_dishes 查询）
  _channel_prices  → menu_channel_prices
  _seasonal_menus  → store_seasonal_menus
  _room_menus      → store_room_menus

所有方法调用 _set_tenant() 设置 RLS context，确保多租户隔离。
金额统一用 int（分）。
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

VALID_CHANNELS = {"dine_in", "takeout", "delivery", "miniapp"}
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}
VALID_ROOM_TYPES = {"standard", "vip", "luxury", "banquet"}


class MenuTemplateRepository:
    """菜单模板数据访问层"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════
    # 菜单模板 CRUD
    # ══════════════════════════════════════════════════════

    async def create_template(
        self,
        name: str,
        dishes: list[dict],
        rules: Optional[dict] = None,
    ) -> dict:
        """创建菜单模板（主表 + 菜品明细行）"""
        await self._set_tenant()
        template_id = uuid.uuid4()

        await self.db.execute(
            text("""
                INSERT INTO menu_templates (id, tenant_id, name, rules, status)
                VALUES (:id, :tid, :name, :rules::jsonb, 'draft')
            """),
            {
                "id": template_id,
                "tid": self._tid,
                "name": name.strip(),
                "rules": json.dumps(rules or {}),
            },
        )

        for dish in dishes:
            dish_id_str = dish.get("dish_id", "")
            if not dish_id_str:
                continue
            await self.db.execute(
                text("""
                    INSERT INTO menu_template_dishes
                        (id, tenant_id, template_id, dish_id, sort_order, dish_data)
                    VALUES
                        (:id, :tid, :template_id, :dish_id, :sort_order, :dish_data::jsonb)
                    ON CONFLICT (tenant_id, template_id, dish_id) DO UPDATE
                        SET sort_order = EXCLUDED.sort_order,
                            dish_data  = EXCLUDED.dish_data
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": self._tid,
                    "template_id": template_id,
                    "dish_id": uuid.UUID(dish_id_str),
                    "sort_order": dish.get("sort_order", 0),
                    "dish_data": json.dumps({k: v for k, v in dish.items() if k != "dish_id"}),
                },
            )

        await self.db.flush()
        result = await self.get_template(str(template_id))
        log.info(
            "menu_template.created", tenant_id=self.tenant_id, template_id=str(template_id), dish_count=len(dishes)
        )
        return result  # type: ignore[return-value]

    async def get_template(self, template_id: str) -> Optional[dict]:
        """获取模板详情（含菜品列表）"""
        await self._set_tenant()
        tid_uuid = uuid.UUID(template_id)

        row_result = await self.db.execute(
            text("""
                SELECT id, name, rules, status, created_at, updated_at
                FROM menu_templates
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": tid_uuid, "tid": self._tid},
        )
        row = row_result.fetchone()
        if not row:
            return None

        dishes_result = await self.db.execute(
            text("""
                SELECT dish_id, sort_order, dish_data
                FROM menu_template_dishes
                WHERE template_id = :tid_val AND tenant_id = :tid
                ORDER BY sort_order
            """),
            {"tid_val": tid_uuid, "tid": self._tid},
        )
        dishes = []
        for d in dishes_result.fetchall():
            dish_entry = {"dish_id": str(d.dish_id), "sort_order": d.sort_order}
            if d.dish_data:
                extra = d.dish_data if isinstance(d.dish_data, dict) else json.loads(d.dish_data)
                dish_entry.update(extra)
            dishes.append(dish_entry)

        # 查询已发布门店列表
        pub_result = await self.db.execute(
            text("""
                SELECT store_id FROM store_menu_publishes
                WHERE template_id = :tid_val AND tenant_id = :tid AND status = 'active'
            """),
            {"tid_val": tid_uuid, "tid": self._tid},
        )
        published_stores = [str(r.store_id) for r in pub_result.fetchall()]

        return {
            "template_id": str(row.id),
            "name": row.name,
            "rules": row.rules if isinstance(row.rules, dict) else json.loads(row.rules or "{}"),
            "status": row.status,
            "dishes": dishes,
            "published_stores": published_stores,
            "tenant_id": self.tenant_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def list_templates(self) -> list[dict]:
        """列出租户所有模板（含各模板菜品数量）"""
        await self._set_tenant()

        result = await self.db.execute(
            text("""
                SELECT t.id, t.name, t.rules, t.status, t.created_at, t.updated_at,
                       COUNT(d.id) AS dish_count
                FROM menu_templates t
                LEFT JOIN menu_template_dishes d
                    ON d.template_id = t.id AND d.tenant_id = t.tenant_id
                WHERE t.tenant_id = :tid AND t.is_deleted = false
                GROUP BY t.id, t.name, t.rules, t.status, t.created_at, t.updated_at
                ORDER BY t.created_at DESC
            """),
            {"tid": self._tid},
        )
        rows = result.fetchall()
        return [
            {
                "template_id": str(r.id),
                "name": r.name,
                "rules": r.rules if isinstance(r.rules, dict) else json.loads(r.rules or "{}"),
                "status": r.status,
                "dish_count": r.dish_count,
                "tenant_id": self.tenant_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]

    # ══════════════════════════════════════════════════════
    # 门店发布
    # ══════════════════════════════════════════════════════

    async def publish_to_store(self, template_id: str, store_id: str) -> dict:
        """将菜单模板发布到门店（UPSERT，覆盖旧发布记录）"""
        await self._set_tenant()
        tid_uuid = uuid.UUID(template_id)
        store_uuid = uuid.UUID(store_id)

        # 确认模板存在
        check = await self.db.execute(
            text("""
                SELECT id, name FROM menu_templates
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": tid_uuid, "tid": self._tid},
        )
        tpl_row = check.fetchone()
        if not tpl_row:
            raise ValueError(f"模板不存在: {template_id}")

        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                INSERT INTO store_menu_publishes
                    (id, tenant_id, store_id, template_id, published_at, status)
                VALUES
                    (:id, :tid, :store_id, :template_id, :now, 'active')
                ON CONFLICT (tenant_id, store_id) DO UPDATE
                    SET template_id  = EXCLUDED.template_id,
                        published_at = EXCLUDED.published_at,
                        status       = 'active'
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "store_id": store_uuid,
                "template_id": tid_uuid,
                "now": now,
            },
        )

        # 将模板状态更新为 published
        await self.db.execute(
            text("""
                UPDATE menu_templates
                SET status = 'published', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": tid_uuid, "tid": self._tid},
        )

        dish_count_result = await self.db.execute(
            text("SELECT COUNT(*) FROM menu_template_dishes WHERE template_id = :id AND tenant_id = :tid"),
            {"id": tid_uuid, "tid": self._tid},
        )
        dish_count = dish_count_result.scalar() or 0

        await self.db.flush()
        log.info(
            "menu_template.published",
            tenant_id=self.tenant_id,
            template_id=template_id,
            store_id=store_id,
            dish_count=dish_count,
        )
        return {
            "store_id": store_id,
            "template_id": template_id,
            "dish_count": dish_count,
            "published_at": now.isoformat(),
            "status": "success",
        }

    async def get_store_menu(self, store_id: str, channel: str) -> dict:
        """获取门店当前菜单（按渠道，叠加渠道差异价）"""
        await self._set_tenant()
        store_uuid = uuid.UUID(store_id)

        # 查找当前发布的模板
        pub_result = await self.db.execute(
            text("""
                SELECT template_id FROM store_menu_publishes
                WHERE store_id = :store_id AND tenant_id = :tid AND status = 'active'
            """),
            {"store_id": store_uuid, "tid": self._tid},
        )
        pub_row = pub_result.fetchone()
        if not pub_row:
            return {"store_id": store_id, "channel": channel, "dishes": [], "dish_count": 0}

        template_id = pub_row.template_id

        # 查询模板菜品
        dishes_result = await self.db.execute(
            text("""
                SELECT dish_id, sort_order, dish_data
                FROM menu_template_dishes
                WHERE template_id = :tid_val AND tenant_id = :tid
                ORDER BY sort_order
            """),
            {"tid_val": template_id, "tid": self._tid},
        )
        dish_rows = dishes_result.fetchall()
        if not dish_rows:
            return {"store_id": store_id, "channel": channel, "dishes": [], "dish_count": 0}

        # 批量查渠道差异价
        dish_ids = [r.dish_id for r in dish_rows]
        prices_result = await self.db.execute(
            text("""
                SELECT dish_id, price_fen FROM menu_channel_prices
                WHERE tenant_id = :tid AND channel = :channel
                  AND dish_id = ANY(:dish_ids)
            """),
            {"tid": self._tid, "channel": channel, "dish_ids": dish_ids},
        )
        channel_prices = {str(r.dish_id): r.price_fen for r in prices_result.fetchall()}

        dishes = []
        for d in dish_rows:
            dish_entry = {"dish_id": str(d.dish_id), "sort_order": d.sort_order}
            if d.dish_data:
                extra = d.dish_data if isinstance(d.dish_data, dict) else json.loads(d.dish_data)
                dish_entry.update(extra)
            dish_id_str = str(d.dish_id)
            dish_entry["channel_price_fen"] = channel_prices.get(dish_id_str, dish_entry.get("price_fen", 0))
            dish_entry["channel"] = channel
            dishes.append(dish_entry)

        return {"store_id": store_id, "channel": channel, "dishes": dishes, "dish_count": len(dishes)}

    # ══════════════════════════════════════════════════════
    # 渠道差异价
    # ══════════════════════════════════════════════════════

    async def set_channel_price(self, dish_id: str, channel: str, price_fen: int) -> dict:
        """设置菜品在某渠道的差异价（UPSERT）"""
        await self._set_tenant()
        now = datetime.now(timezone.utc)
        await self.db.execute(
            text("""
                INSERT INTO menu_channel_prices (id, tenant_id, dish_id, channel, price_fen, updated_at)
                VALUES (:id, :tid, :dish_id, :channel, :price_fen, :now)
                ON CONFLICT (tenant_id, dish_id, channel) DO UPDATE
                    SET price_fen  = EXCLUDED.price_fen,
                        updated_at = EXCLUDED.updated_at
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "dish_id": uuid.UUID(dish_id),
                "channel": channel,
                "price_fen": price_fen,
                "now": now,
            },
        )
        await self.db.flush()
        log.info("channel_price.set", tenant_id=self.tenant_id, dish_id=dish_id, channel=channel, price_fen=price_fen)
        return {
            "dish_id": dish_id,
            "channel": channel,
            "price_fen": price_fen,
            "tenant_id": self.tenant_id,
            "updated_at": now.isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # 季节菜单
    # ══════════════════════════════════════════════════════

    async def set_seasonal_menu(self, store_id: str, season: str, dishes: list[dict]) -> dict:
        """设置门店季节菜单（UPSERT）"""
        await self._set_tenant()
        now = datetime.now(timezone.utc)
        store_uuid = uuid.UUID(store_id)
        await self.db.execute(
            text("""
                INSERT INTO store_seasonal_menus
                    (id, tenant_id, store_id, season, dishes, dish_count, status, updated_at)
                VALUES
                    (:id, :tid, :store_id, :season, :dishes::jsonb, :dish_count, 'active', :now)
                ON CONFLICT (tenant_id, store_id, season) DO UPDATE
                    SET dishes     = EXCLUDED.dishes,
                        dish_count = EXCLUDED.dish_count,
                        status     = 'active',
                        updated_at = EXCLUDED.updated_at
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "store_id": store_uuid,
                "season": season,
                "dishes": json.dumps(dishes),
                "dish_count": len(dishes),
                "now": now,
            },
        )
        await self.db.flush()
        log.info(
            "seasonal_menu.set", tenant_id=self.tenant_id, store_id=store_id, season=season, dish_count=len(dishes)
        )
        return {
            "store_id": store_id,
            "season": season,
            "dishes": dishes,
            "dish_count": len(dishes),
            "tenant_id": self.tenant_id,
            "status": "active",
            "updated_at": now.isoformat(),
        }

    async def get_seasonal_menu(self, store_id: str, season: str) -> Optional[dict]:
        """获取门店季节菜单"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT store_id, season, dishes, dish_count, status, updated_at
                FROM store_seasonal_menus
                WHERE store_id = :store_id AND season = :season AND tenant_id = :tid
            """),
            {"store_id": uuid.UUID(store_id), "season": season, "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "store_id": store_id,
            "season": row.season,
            "dishes": row.dishes if isinstance(row.dishes, list) else json.loads(row.dishes or "[]"),
            "dish_count": row.dish_count,
            "tenant_id": self.tenant_id,
            "status": row.status,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ══════════════════════════════════════════════════════
    # 包厢菜单
    # ══════════════════════════════════════════════════════

    async def set_room_menu(self, store_id: str, room_type: str, dishes: list[dict]) -> dict:
        """设置门店包厢专属菜单（UPSERT）"""
        await self._set_tenant()
        now = datetime.now(timezone.utc)
        store_uuid = uuid.UUID(store_id)
        await self.db.execute(
            text("""
                INSERT INTO store_room_menus
                    (id, tenant_id, store_id, room_type, dishes, dish_count, status, updated_at)
                VALUES
                    (:id, :tid, :store_id, :room_type, :dishes::jsonb, :dish_count, 'active', :now)
                ON CONFLICT (tenant_id, store_id, room_type) DO UPDATE
                    SET dishes     = EXCLUDED.dishes,
                        dish_count = EXCLUDED.dish_count,
                        status     = 'active',
                        updated_at = EXCLUDED.updated_at
            """),
            {
                "id": uuid.uuid4(),
                "tid": self._tid,
                "store_id": store_uuid,
                "room_type": room_type,
                "dishes": json.dumps(dishes),
                "dish_count": len(dishes),
                "now": now,
            },
        )
        await self.db.flush()
        log.info(
            "room_menu.set", tenant_id=self.tenant_id, store_id=store_id, room_type=room_type, dish_count=len(dishes)
        )
        return {
            "store_id": store_id,
            "room_type": room_type,
            "dishes": dishes,
            "dish_count": len(dishes),
            "tenant_id": self.tenant_id,
            "status": "active",
            "updated_at": now.isoformat(),
        }

    async def get_room_menu(self, store_id: str, room_type: str) -> Optional[dict]:
        """获取门店包厢菜单"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT store_id, room_type, dishes, dish_count, status, updated_at
                FROM store_room_menus
                WHERE store_id = :store_id AND room_type = :room_type AND tenant_id = :tid
            """),
            {"store_id": uuid.UUID(store_id), "room_type": room_type, "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "store_id": store_id,
            "room_type": row.room_type,
            "dishes": row.dishes if isinstance(row.dishes, list) else json.loads(row.dishes or "[]"),
            "dish_count": row.dish_count,
            "tenant_id": self.tenant_id,
            "status": row.status,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ══════════════════════════════════════════════════════
    # 宴席套餐（复用 create_template）
    # ══════════════════════════════════════════════════════

    async def create_banquet_package(
        self,
        name: str,
        dishes: list[dict],
        package_price_fen: int,
        guest_count: int,
        description: Optional[str] = None,
    ) -> dict:
        """创建宴席套餐（底层复用模板机制）"""
        rules = {
            "type": "banquet",
            "package_price_fen": package_price_fen,
            "guest_count": guest_count,
            "description": description,
        }
        template = await self.create_template(name=name, dishes=dishes, rules=rules)
        template["package_price_fen"] = package_price_fen
        template["guest_count"] = guest_count
        template["description"] = description
        log.info(
            "banquet_package.created",
            tenant_id=self.tenant_id,
            template_id=template["template_id"],
            guest_count=guest_count,
            price_fen=package_price_fen,
        )
        return template
