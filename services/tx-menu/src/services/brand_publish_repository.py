"""品牌发布体系 Repository — 发布方案 / 门店微调 / 调价规则 DB 层

所有方法先调用 _set_tenant() 设置 RLS context，严格多租户隔离。
金额统一用 int（分）。
"""

import json
import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class BrandPublishRepository:
    """品牌→门店发布体系的数据访问层"""

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
    # 发布方案 (menu_publish_plans)
    # ══════════════════════════════════════════════════════

    async def create_publish_plan(
        self,
        plan_name: str,
        target_type: str,
        target_ids: Optional[list[str]],
        brand_id: Optional[str],
        created_by: Optional[str],
    ) -> dict:
        await self._set_tenant()
        plan_id = uuid.uuid4()
        brand_uuid = uuid.UUID(brand_id) if brand_id else None
        creator_uuid = uuid.UUID(created_by) if created_by else None
        result = await self.db.execute(
            text("""
                INSERT INTO menu_publish_plans
                    (id, tenant_id, brand_id, plan_name, target_type, target_ids,
                     status, created_by)
                VALUES
                    (:id, :tid, :brand_id, :plan_name, :target_type, :target_ids::jsonb,
                     'draft', :created_by)
                RETURNING id, plan_name, target_type, target_ids, status,
                          created_at, updated_at, brand_id, created_by
            """),
            {
                "id": plan_id,
                "tid": self._tid,
                "brand_id": brand_uuid,
                "plan_name": plan_name,
                "target_type": target_type,
                "target_ids": json.dumps(target_ids) if target_ids else None,
                "created_by": creator_uuid,
            },
        )
        row = result.fetchone()
        return self._plan_row_to_dict(row)

    async def get_publish_plan(self, plan_id: str) -> Optional[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, plan_name, target_type, target_ids, status,
                       published_at, created_at, updated_at, brand_id, created_by
                FROM menu_publish_plans
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._plan_row_to_dict(row) if row else None

    async def list_publish_plans(
        self,
        page: int,
        size: int,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        await self._set_tenant()
        filters = "WHERE p.tenant_id = :tid AND p.is_deleted = false"
        params: dict = {"tid": self._tid}
        if brand_id:
            filters += " AND p.brand_id = :brand_id"
            params["brand_id"] = uuid.UUID(brand_id)
        if status:
            filters += " AND p.status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM menu_publish_plans p {filters}"),
            params,
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        rows_result = await self.db.execute(
            text(f"""
                SELECT id, plan_name, target_type, target_ids, status,
                       published_at, created_at, updated_at, brand_id, created_by
                FROM menu_publish_plans p
                {filters}
                ORDER BY p.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [self._plan_row_to_dict(r) for r in rows_result.fetchall()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def update_plan_status(
        self,
        plan_id: str,
        status: str,
        published_at: Optional[datetime] = None,
    ) -> Optional[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                UPDATE menu_publish_plans
                SET status = :status,
                    published_at = COALESCE(:published_at, published_at),
                    updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
                RETURNING id, plan_name, target_type, target_ids, status,
                          published_at, created_at, updated_at, brand_id, created_by
            """),
            {
                "id": uuid.UUID(plan_id),
                "tid": self._tid,
                "status": status,
                "published_at": published_at,
            },
        )
        row = result.fetchone()
        return self._plan_row_to_dict(row) if row else None

    # ══════════════════════════════════════════════════════
    # 发布方案菜品 (menu_publish_plan_items)
    # ══════════════════════════════════════════════════════

    async def add_plan_items(
        self,
        plan_id: str,
        items: list[dict],
    ) -> list[dict]:
        """批量添加菜品到发布方案，已存在则更新覆盖价。"""
        await self._set_tenant()
        plan_uuid = uuid.UUID(plan_id)
        results = []
        for item in items:
            dish_uuid = uuid.UUID(item["dish_id"])
            override_price = item.get("override_price_fen")
            is_available = item.get("is_available", True)
            result = await self.db.execute(
                text("""
                    INSERT INTO menu_publish_plan_items
                        (id, tenant_id, plan_id, dish_id, override_price_fen, is_available)
                    VALUES
                        (:id, :tid, :plan_id, :dish_id, :override_price, :is_available)
                    ON CONFLICT (tenant_id, plan_id, dish_id) DO UPDATE SET
                        override_price_fen = EXCLUDED.override_price_fen,
                        is_available = EXCLUDED.is_available
                    RETURNING id, plan_id, dish_id, override_price_fen, is_available, created_at
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": self._tid,
                    "plan_id": plan_uuid,
                    "dish_id": dish_uuid,
                    "override_price": override_price,
                    "is_available": is_available,
                },
            )
            row = result.fetchone()
            if row:
                results.append(
                    {
                        "id": str(row[0]),
                        "plan_id": str(row[1]),
                        "dish_id": str(row[2]),
                        "override_price_fen": row[3],
                        "is_available": row[4],
                        "created_at": row[5].isoformat() if row[5] else None,
                    }
                )
        return results

    async def get_plan_items(self, plan_id: str) -> list[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT i.id, i.plan_id, i.dish_id, i.override_price_fen,
                       i.is_available, i.created_at,
                       d.dish_name, d.price_fen, d.image_url
                FROM menu_publish_plan_items i
                JOIN dishes d ON d.id = i.dish_id AND d.tenant_id = i.tenant_id
                WHERE i.plan_id = :plan_id AND i.tenant_id = :tid
                ORDER BY d.dish_name
            """),
            {"plan_id": uuid.UUID(plan_id), "tid": self._tid},
        )
        rows = result.fetchall()
        return [
            {
                "id": str(r[0]),
                "plan_id": str(r[1]),
                "dish_id": str(r[2]),
                "override_price_fen": r[3],
                "is_available": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "dish_name": r[6],
                "brand_price_fen": r[7],
                "effective_price_fen": r[3] if r[3] is not None else r[7],
                "image_url": r[8],
            }
            for r in rows
        ]

    async def get_plan_override_for_dish(self, dish_id: str, store_id: str) -> Optional[dict]:
        """查找最新一个已发布的方案中，指定菜品针对该门店的覆盖价。"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT i.override_price_fen, i.is_available, p.plan_name
                FROM menu_publish_plan_items i
                JOIN menu_publish_plans p ON p.id = i.plan_id
                    AND p.tenant_id = i.tenant_id
                WHERE i.tenant_id = :tid
                  AND i.dish_id = :dish_id
                  AND p.status = 'published'
                  AND p.is_deleted = false
                  AND (
                      p.target_type = 'all_stores'
                      OR (p.target_type = 'stores'
                          AND p.target_ids @> to_jsonb(:store_id::text))
                  )
                ORDER BY p.published_at DESC
                LIMIT 1
            """),
            {
                "tid": self._tid,
                "dish_id": uuid.UUID(dish_id),
                "store_id": store_id,
            },
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "override_price_fen": row[0],
            "is_available": row[1],
            "plan_name": row[2],
        }

    async def get_target_store_ids(self, plan_id: str) -> list[str]:
        """根据发布方案的 target_type 解析出最终的目标门店 ID 列表。"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT target_type, target_ids, brand_id
                FROM menu_publish_plans
                WHERE id = :id AND tenant_id = :tid AND is_deleted = false
            """),
            {"id": uuid.UUID(plan_id), "tid": self._tid},
        )
        row = result.fetchone()
        if not row:
            raise ValueError(f"发布方案不存在: {plan_id}")

        target_type: str = row[0]
        target_ids = row[1]  # JSON list
        brand_id = row[2]

        if target_type == "all_stores":
            # 查所有门店
            filter_sql = "WHERE tenant_id = :tid AND is_active = true"
            params: dict = {"tid": self._tid}
            if brand_id:
                filter_sql += " AND brand_id = :brand_id"
                params["brand_id"] = str(brand_id)
            stores_result = await self.db.execute(
                text(f"SELECT id FROM stores {filter_sql}"),
                params,
            )
            return [str(r[0]) for r in stores_result.fetchall()]

        elif target_type == "region":
            # 按 region 过滤
            if not target_ids:
                return []
            stores_result = await self.db.execute(
                text("""
                    SELECT id FROM stores
                    WHERE tenant_id = :tid
                      AND is_active = true
                      AND region = ANY(:regions)
                """),
                {"tid": self._tid, "regions": target_ids},
            )
            return [str(r[0]) for r in stores_result.fetchall()]

        else:  # "stores"
            return list(target_ids) if target_ids else []

    # ══════════════════════════════════════════════════════
    # 门店菜品微调 (store_dish_overrides)
    # ══════════════════════════════════════════════════════

    async def upsert_store_dish_override(
        self,
        store_id: str,
        dish_id: str,
        data: dict,
        updated_by: Optional[str] = None,
    ) -> dict:
        """创建或更新门店菜品微调（仅更新传入的字段）。"""
        await self._set_tenant()
        store_uuid = uuid.UUID(store_id)
        dish_uuid = uuid.UUID(dish_id)
        updater = uuid.UUID(updated_by) if updated_by else None

        # 构建动态 UPDATE SET 子句（只更新非 None 字段）
        allowed = {
            "local_price_fen",
            "local_name",
            "local_description",
            "local_image_url",
            "is_available",
            "sort_order",
        }
        updates = {k: v for k, v in data.items() if k in allowed}

        # 构建 ON CONFLICT DO UPDATE SET 子句
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        if set_clauses:
            set_clauses += ", updated_at = NOW(), updated_by = :updated_by"
        else:
            set_clauses = "updated_at = NOW(), updated_by = :updated_by"

        # INSERT 参数（含所有字段的默认值）
        insert_params: dict = {
            "id": uuid.uuid4(),
            "tid": self._tid,
            "store_id": store_uuid,
            "dish_id": dish_uuid,
            "updated_by": updater,
            "local_price_fen": updates.get("local_price_fen"),
            "local_name": updates.get("local_name"),
            "local_description": updates.get("local_description"),
            "local_image_url": updates.get("local_image_url"),
            "is_available": updates.get("is_available", True),
            "sort_order": updates.get("sort_order", 0),
        }

        result = await self.db.execute(
            text(f"""
                INSERT INTO store_dish_overrides
                    (id, tenant_id, store_id, dish_id, updated_by,
                     local_price_fen, local_name, local_description,
                     local_image_url, is_available, sort_order)
                VALUES
                    (:id, :tid, :store_id, :dish_id, :updated_by,
                     :local_price_fen, :local_name, :local_description,
                     :local_image_url, :is_available, :sort_order)
                ON CONFLICT (tenant_id, store_id, dish_id) DO UPDATE SET
                    {set_clauses}
                RETURNING id, store_id, dish_id, local_price_fen, local_name,
                          local_description, local_image_url, is_available,
                          sort_order, updated_at
            """),
            insert_params,
        )
        row = result.fetchone()
        return self._override_row_to_dict(row)

    async def get_store_dish_override(self, store_id: str, dish_id: str) -> Optional[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, store_id, dish_id, local_price_fen, local_name,
                       local_description, local_image_url, is_available,
                       sort_order, updated_at
                FROM store_dish_overrides
                WHERE tenant_id = :tid
                  AND store_id = :store_id
                  AND dish_id = :dish_id
            """),
            {
                "tid": self._tid,
                "store_id": uuid.UUID(store_id),
                "dish_id": uuid.UUID(dish_id),
            },
        )
        row = result.fetchone()
        return self._override_row_to_dict(row) if row else None

    async def list_store_overrides(self, store_id: str) -> list[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT o.id, o.store_id, o.dish_id,
                       o.local_price_fen, o.local_name, o.local_description,
                       o.local_image_url, o.is_available, o.sort_order, o.updated_at,
                       d.dish_name, d.price_fen AS brand_price_fen,
                       d.image_url AS brand_image_url, d.description AS brand_description
                FROM store_dish_overrides o
                JOIN dishes d ON d.id = o.dish_id AND d.tenant_id = o.tenant_id
                WHERE o.tenant_id = :tid
                  AND o.store_id = :store_id
                ORDER BY o.sort_order, d.dish_name
            """),
            {"tid": self._tid, "store_id": uuid.UUID(store_id)},
        )
        rows = result.fetchall()
        return [
            {
                "id": str(r[0]),
                "store_id": str(r[1]),
                "dish_id": str(r[2]),
                "local_price_fen": r[3],
                "local_name": r[4],
                "local_description": r[5],
                "local_image_url": r[6],
                "is_available": r[7],
                "sort_order": r[8],
                "updated_at": r[9].isoformat() if r[9] else None,
                # 合并后的显示字段
                "effective_name": r[4] or r[10],
                "effective_price_fen": r[3] if r[3] is not None else r[11],
                "effective_image_url": r[6] or r[12],
                "effective_description": r[5] or r[13],
                "brand_price_fen": r[11],
            }
            for r in rows
        ]

    async def batch_toggle_availability(
        self,
        store_id: str,
        dish_ids: list[str],
        is_available: bool,
        updated_by: Optional[str] = None,
    ) -> int:
        """批量更新门店菜品的上下架状态。"""
        await self._set_tenant()
        if not dish_ids:
            return 0
        dish_uuids = [uuid.UUID(d) for d in dish_ids]
        store_uuid = uuid.UUID(store_id)
        updater = uuid.UUID(updated_by) if updated_by else None
        placeholders = ", ".join(f":did_{i}" for i in range(len(dish_uuids)))
        params: dict = {
            "tid": self._tid,
            "store_id": store_uuid,
            "is_available": is_available,
            "updated_by": updater,
        }
        for i, d in enumerate(dish_uuids):
            params[f"did_{i}"] = d

        result = await self.db.execute(
            text(f"""
                INSERT INTO store_dish_overrides
                    (id, tenant_id, store_id, dish_id, is_available, updated_by)
                SELECT gen_random_uuid(), :tid, :store_id, d, :is_available, :updated_by
                FROM unnest(ARRAY[{placeholders}]::uuid[]) AS d
                ON CONFLICT (tenant_id, store_id, dish_id) DO UPDATE SET
                    is_available = EXCLUDED.is_available,
                    updated_at   = NOW(),
                    updated_by   = EXCLUDED.updated_by
            """),
            params,
        )
        return result.rowcount or len(dish_ids)

    # ══════════════════════════════════════════════════════
    # 调价规则 (price_adjustment_rules)
    # ══════════════════════════════════════════════════════

    async def create_price_rule(self, data: dict) -> dict:
        await self._set_tenant()
        rule_id = uuid.uuid4()
        store_uuid = uuid.UUID(data["store_id"]) if data.get("store_id") else None
        result = await self.db.execute(
            text("""
                INSERT INTO price_adjustment_rules
                    (id, tenant_id, store_id, rule_name, rule_type, channel,
                     time_start, time_end, date_start, date_end, weekdays,
                     adjustment_type, adjustment_value, priority, is_active)
                VALUES
                    (:id, :tid, :store_id, :rule_name, :rule_type, :channel,
                     :time_start, :time_end, :date_start, :date_end, :weekdays::jsonb,
                     :adjustment_type, :adjustment_value, :priority, :is_active)
                RETURNING id, store_id, rule_name, rule_type, channel,
                          time_start, time_end, date_start, date_end, weekdays,
                          adjustment_type, adjustment_value, priority, is_active,
                          created_at, updated_at
            """),
            {
                "id": rule_id,
                "tid": self._tid,
                "store_id": store_uuid,
                "rule_name": data["rule_name"],
                "rule_type": data["rule_type"],
                "channel": data.get("channel"),
                "time_start": data.get("time_start"),
                "time_end": data.get("time_end"),
                "date_start": data.get("date_start"),
                "date_end": data.get("date_end"),
                "weekdays": json.dumps(data.get("weekdays")) if data.get("weekdays") else None,
                "adjustment_type": data["adjustment_type"],
                "adjustment_value": data["adjustment_value"],
                "priority": data.get("priority", 0),
                "is_active": data.get("is_active", True),
            },
        )
        row = result.fetchone()
        return self._rule_row_to_dict(row)

    async def get_price_rule(self, rule_id: str) -> Optional[dict]:
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, store_id, rule_name, rule_type, channel,
                       time_start, time_end, date_start, date_end, weekdays,
                       adjustment_type, adjustment_value, priority, is_active,
                       created_at, updated_at
                FROM price_adjustment_rules
                WHERE id = :id AND tenant_id = :tid
            """),
            {"id": uuid.UUID(rule_id), "tid": self._tid},
        )
        row = result.fetchone()
        return self._rule_row_to_dict(row) if row else None

    async def list_price_rules(
        self,
        store_id: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> list[dict]:
        await self._set_tenant()
        where = "WHERE tenant_id = :tid"
        params: dict = {"tid": self._tid}
        if store_id:
            where += " AND (store_id = :store_id OR store_id IS NULL)"
            params["store_id"] = uuid.UUID(store_id)
        if is_active is not None:
            where += " AND is_active = :is_active"
            params["is_active"] = is_active
        result = await self.db.execute(
            text(f"""
                SELECT id, store_id, rule_name, rule_type, channel,
                       time_start, time_end, date_start, date_end, weekdays,
                       adjustment_type, adjustment_value, priority, is_active,
                       created_at, updated_at
                FROM price_adjustment_rules
                {where}
                ORDER BY priority DESC, created_at DESC
            """),
            params,
        )
        return [self._rule_row_to_dict(r) for r in result.fetchall()]

    async def update_price_rule(self, rule_id: str, data: dict) -> Optional[dict]:
        await self._set_tenant()
        allowed = {
            "rule_name",
            "channel",
            "time_start",
            "time_end",
            "date_start",
            "date_end",
            "weekdays",
            "adjustment_type",
            "adjustment_value",
            "priority",
            "is_active",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return await self.get_price_rule(rule_id)

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        result = await self.db.execute(
            text(f"""
                UPDATE price_adjustment_rules
                SET {set_clauses}, updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid
                RETURNING id, store_id, rule_name, rule_type, channel,
                          time_start, time_end, date_start, date_end, weekdays,
                          adjustment_type, adjustment_value, priority, is_active,
                          created_at, updated_at
            """),
            {"id": uuid.UUID(rule_id), "tid": self._tid, **updates},
        )
        row = result.fetchone()
        return self._rule_row_to_dict(row) if row else None

    # ══════════════════════════════════════════════════════
    # 菜品调价规则关联 (dish_price_adjustments)
    # ══════════════════════════════════════════════════════

    async def bind_dishes_to_rule(self, rule_id: str, dish_ids: list[str]) -> list[dict]:
        await self._set_tenant()
        rule_uuid = uuid.UUID(rule_id)
        results = []
        for dish_id in dish_ids:
            dish_uuid = uuid.UUID(dish_id)
            result = await self.db.execute(
                text("""
                    INSERT INTO dish_price_adjustments
                        (id, tenant_id, rule_id, dish_id)
                    VALUES
                        (:id, :tid, :rule_id, :dish_id)
                    ON CONFLICT (tenant_id, rule_id, dish_id) DO NOTHING
                    RETURNING id, rule_id, dish_id, created_at
                """),
                {
                    "id": uuid.uuid4(),
                    "tid": self._tid,
                    "rule_id": rule_uuid,
                    "dish_id": dish_uuid,
                },
            )
            row = result.fetchone()
            if row:
                results.append(
                    {
                        "id": str(row[0]),
                        "rule_id": str(row[1]),
                        "dish_id": str(row[2]),
                        "created_at": row[3].isoformat() if row[3] else None,
                    }
                )
        return results

    async def get_active_rules_for_dish(
        self,
        dish_id: str,
        store_id: str,
        channel: Optional[str],
        at_datetime: datetime,
    ) -> list[dict]:
        """查询对指定菜品、门店、渠道、时间点生效的调价规则（按优先级降序）。"""
        await self._set_tenant()
        at_time = at_datetime.time()
        at_date = at_datetime.date()
        at_weekday = at_datetime.isoweekday()  # 1=Mon ... 7=Sun

        params: dict = {
            "tid": self._tid,
            "dish_id": uuid.UUID(dish_id),
            "store_id": uuid.UUID(store_id),
            "channel": channel,
            "at_time": at_time,
            "at_date": at_date,
            "at_weekday": at_weekday,
        }

        result = await self.db.execute(
            text("""
                SELECT r.id, r.rule_type, r.channel, r.adjustment_type,
                       r.adjustment_value, r.priority,
                       r.time_start, r.time_end,
                       r.date_start, r.date_end, r.weekdays
                FROM price_adjustment_rules r
                JOIN dish_price_adjustments da
                  ON da.rule_id = r.id AND da.tenant_id = r.tenant_id
                WHERE r.tenant_id = :tid
                  AND da.dish_id = :dish_id
                  AND r.is_active = true
                  AND (r.store_id IS NULL OR r.store_id = :store_id)
                  AND (r.channel IS NULL OR r.channel = :channel)
                  AND (
                      -- 时段规则
                      (r.rule_type = 'time_period'
                       AND r.time_start IS NOT NULL
                       AND :at_time BETWEEN r.time_start AND r.time_end)
                      OR
                      -- 渠道规则（渠道匹配即命中）
                      (r.rule_type = 'channel' AND r.channel = :channel)
                      OR
                      -- 日期范围规则
                      (r.rule_type = 'date_range'
                       AND :at_date BETWEEN r.date_start AND r.date_end
                       AND (r.weekdays IS NULL
                            OR r.weekdays @> to_jsonb(:at_weekday)))
                      OR
                      -- 节假日规则（仅日期范围，不限星期）
                      (r.rule_type = 'holiday'
                       AND :at_date BETWEEN r.date_start AND r.date_end)
                  )
                ORDER BY r.priority DESC
            """),
            params,
        )
        rows = result.fetchall()
        return [
            {
                "id": str(r[0]),
                "rule_type": r[1],
                "channel": r[2],
                "adjustment_type": r[3],
                "adjustment_value": float(r[4]),
                "priority": r[5],
            }
            for r in rows
        ]

    # ══════════════════════════════════════════════════════
    # 内部工具方法
    # ══════════════════════════════════════════════════════

    @staticmethod
    def _plan_row_to_dict(row) -> dict:
        return {
            "id": str(row[0]),
            "plan_name": row[1],
            "target_type": row[2],
            "target_ids": row[3],
            "status": row[4],
            "published_at": row[5].isoformat() if row[5] else None,
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
            "brand_id": str(row[8]) if row[8] else None,
            "created_by": str(row[9]) if row[9] else None,
        }

    @staticmethod
    def _override_row_to_dict(row) -> dict:
        return {
            "id": str(row[0]),
            "store_id": str(row[1]),
            "dish_id": str(row[2]),
            "local_price_fen": row[3],
            "local_name": row[4],
            "local_description": row[5],
            "local_image_url": row[6],
            "is_available": row[7],
            "sort_order": row[8],
            "updated_at": row[9].isoformat() if row[9] else None,
        }

    @staticmethod
    def _rule_row_to_dict(row) -> dict:
        return {
            "id": str(row[0]),
            "store_id": str(row[1]) if row[1] else None,
            "rule_name": row[2],
            "rule_type": row[3],
            "channel": row[4],
            "time_start": str(row[5]) if row[5] else None,
            "time_end": str(row[6]) if row[6] else None,
            "date_start": str(row[7]) if row[7] else None,
            "date_end": str(row[8]) if row[8] else None,
            "weekdays": row[9],
            "adjustment_type": row[10],
            "adjustment_value": float(row[11]),
            "priority": row[12],
            "is_active": row[13],
            "created_at": row[14].isoformat() if row[14] else None,
            "updated_at": row[15].isoformat() if row[15] else None,
        }
