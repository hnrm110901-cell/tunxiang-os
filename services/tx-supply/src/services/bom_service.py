"""BOM 模板管理服务 — CRUD + 版本激活

封装 bom_templates / bom_items 的查询与管理。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func, update, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class BOMService:
    """BOM 模板 CRUD 服务"""

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

    # ─── 创建 BOM 模板 ───

    async def create_bom_template(
        self,
        dish_id: str,
        items: list[dict],
        *,
        store_id: str,
        version: str = "v1",
        yield_rate: float = 1.0,
        standard_portion: Optional[float] = None,
        prep_time_minutes: Optional[int] = None,
        scope: str = "store",
        notes: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        """创建 BOM 模板 + 明细行

        Args:
            dish_id: 菜品 ID
            items: BOM 明细列表, 每项需包含:
                - ingredient_id: str
                - standard_qty: float
                - unit: str
                - unit_cost_fen: int (可选)
                - raw_qty: float (可选)
                - waste_factor: float (可选, 默认0)
                - is_key_ingredient: bool (可选)
                - is_optional: bool (可选)
                - prep_notes: str (可选)
            store_id: 门店 ID
            version: 版本号
        """
        await self._set_tenant()

        template_id = uuid.uuid4()
        dish_uuid = uuid.UUID(dish_id)
        store_uuid = uuid.UUID(store_id)
        now = datetime.now(timezone.utc)

        # 插入 bom_templates
        await self.db.execute(
            text("""
                INSERT INTO bom_templates (
                    id, tenant_id, store_id, dish_id, version,
                    yield_rate, standard_portion, prep_time_minutes,
                    scope, notes, created_by,
                    is_active, is_approved, is_deleted,
                    created_at, updated_at, effective_date
                ) VALUES (
                    :id, :tenant_id, :store_id, :dish_id, :version,
                    :yield_rate, :standard_portion, :prep_time_minutes,
                    :scope, :notes, :created_by,
                    false, false, false,
                    :now, :now, :now
                )
            """),
            {
                "id": template_id,
                "tenant_id": self._tenant_uuid,
                "store_id": store_uuid,
                "dish_id": dish_uuid,
                "version": version,
                "yield_rate": yield_rate,
                "standard_portion": standard_portion,
                "prep_time_minutes": prep_time_minutes,
                "scope": scope,
                "notes": notes,
                "created_by": created_by,
                "now": now,
            },
        )

        # 插入 bom_items
        created_items = []
        for item in items:
            item_id = uuid.uuid4()
            ingredient_uuid = uuid.UUID(item["ingredient_id"])

            await self.db.execute(
                text("""
                    INSERT INTO bom_items (
                        id, tenant_id, bom_id, store_id, ingredient_id,
                        standard_qty, raw_qty, unit, unit_cost_fen,
                        is_key_ingredient, is_optional, waste_factor,
                        prep_notes, item_action, is_deleted,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :bom_id, :store_id, :ingredient_id,
                        :standard_qty, :raw_qty, :unit, :unit_cost_fen,
                        :is_key_ingredient, :is_optional, :waste_factor,
                        :prep_notes, 'ADD', false,
                        :now, :now
                    )
                """),
                {
                    "id": item_id,
                    "tenant_id": self._tenant_uuid,
                    "bom_id": template_id,
                    "store_id": store_uuid,
                    "ingredient_id": ingredient_uuid,
                    "standard_qty": item["standard_qty"],
                    "raw_qty": item.get("raw_qty"),
                    "unit": item["unit"],
                    "unit_cost_fen": item.get("unit_cost_fen"),
                    "is_key_ingredient": item.get("is_key_ingredient", False),
                    "is_optional": item.get("is_optional", False),
                    "waste_factor": item.get("waste_factor", 0),
                    "prep_notes": item.get("prep_notes"),
                    "now": now,
                },
            )
            created_items.append({
                "id": str(item_id),
                "ingredient_id": item["ingredient_id"],
                "standard_qty": item["standard_qty"],
                "unit": item["unit"],
                "unit_cost_fen": item.get("unit_cost_fen"),
            })

        await self.db.flush()

        log.info(
            "bom_template_created",
            template_id=str(template_id),
            dish_id=dish_id,
            version=version,
            item_count=len(items),
        )

        return {
            "id": str(template_id),
            "dish_id": dish_id,
            "store_id": store_id,
            "version": version,
            "yield_rate": yield_rate,
            "is_active": False,
            "items": created_items,
        }

    # ─── 获取 BOM 模板（含明细） ───

    async def get_bom_template(self, template_id: str) -> Optional[dict]:
        """获取单个 BOM 模板及其所有明细行"""
        await self._set_tenant()

        template_uuid = uuid.UUID(template_id)

        # 查询模板
        result = await self.db.execute(
            text("""
                SELECT id, tenant_id, store_id, dish_id, version,
                       effective_date, expiry_date, yield_rate,
                       standard_portion, prep_time_minutes,
                       is_active, is_approved, approved_by, approved_at,
                       scope, notes, created_by, created_at, updated_at
                FROM bom_templates
                WHERE id = :id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid},
        )
        row = result.mappings().first()
        if not row:
            return None

        # 查询明细
        items_result = await self.db.execute(
            text("""
                SELECT id, ingredient_id, standard_qty, raw_qty, unit,
                       unit_cost_fen, is_key_ingredient, is_optional,
                       waste_factor, prep_notes, item_action
                FROM bom_items
                WHERE bom_id = :bom_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
                ORDER BY created_at
            """),
            {"bom_id": template_uuid, "tenant_id": self._tenant_uuid},
        )
        items_rows = items_result.mappings().all()

        return {
            "id": str(row["id"]),
            "store_id": str(row["store_id"]),
            "dish_id": str(row["dish_id"]),
            "version": row["version"],
            "effective_date": row["effective_date"].isoformat() if row["effective_date"] else None,
            "expiry_date": row["expiry_date"].isoformat() if row["expiry_date"] else None,
            "yield_rate": float(row["yield_rate"]) if row["yield_rate"] else 1.0,
            "standard_portion": float(row["standard_portion"]) if row["standard_portion"] else None,
            "prep_time_minutes": row["prep_time_minutes"],
            "is_active": row["is_active"],
            "is_approved": row["is_approved"],
            "scope": row["scope"],
            "notes": row["notes"],
            "created_by": row["created_by"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "items": [
                {
                    "id": str(ir["id"]),
                    "ingredient_id": str(ir["ingredient_id"]),
                    "standard_qty": float(ir["standard_qty"]),
                    "raw_qty": float(ir["raw_qty"]) if ir["raw_qty"] else None,
                    "unit": ir["unit"],
                    "unit_cost_fen": ir["unit_cost_fen"],
                    "is_key_ingredient": ir["is_key_ingredient"],
                    "is_optional": ir["is_optional"],
                    "waste_factor": float(ir["waste_factor"]) if ir["waste_factor"] else 0,
                    "prep_notes": ir["prep_notes"],
                    "item_action": ir["item_action"],
                }
                for ir in items_rows
            ],
        }

    # ─── 列表查询 ───

    async def list_bom_templates(
        self,
        dish_id: Optional[str] = None,
        store_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询 BOM 模板列表"""
        await self._set_tenant()

        # 构建 WHERE 条件
        conditions = ["tenant_id = :tenant_id", "is_deleted = false"]
        params: dict = {"tenant_id": self._tenant_uuid}

        if dish_id:
            conditions.append("dish_id = :dish_id")
            params["dish_id"] = uuid.UUID(dish_id)
        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = uuid.UUID(store_id)
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where_clause = " AND ".join(conditions)

        # 计数
        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM bom_templates WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar() or 0

        # 分页查询
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await self.db.execute(
            text(f"""
                SELECT id, store_id, dish_id, version, yield_rate,
                       is_active, is_approved, scope, created_at
                FROM bom_templates
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        items = [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "dish_id": str(r["dish_id"]),
                "version": r["version"],
                "yield_rate": float(r["yield_rate"]) if r["yield_rate"] else 1.0,
                "is_active": r["is_active"],
                "is_approved": r["is_approved"],
                "scope": r["scope"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

        return {"items": items, "total": total, "page": page, "size": size}

    # ─── 更新 BOM 模板 ───

    async def update_bom_template(
        self,
        template_id: str,
        items: list[dict],
        *,
        yield_rate: Optional[float] = None,
        standard_portion: Optional[float] = None,
        prep_time_minutes: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """更新 BOM 模板：替换所有明细行 + 可选更新模板字段

        采用"先软删旧明细, 再插入新明细"策略。
        """
        await self._set_tenant()

        template_uuid = uuid.UUID(template_id)
        now = datetime.now(timezone.utc)

        # 确认模板存在
        check = await self.db.execute(
            text("""
                SELECT id, store_id, dish_id, version
                FROM bom_templates
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid},
        )
        template_row = check.mappings().first()
        if not template_row:
            return None

        store_uuid = template_row["store_id"]

        # 更新模板字段
        update_fields = ["updated_at = :now"]
        update_params: dict = {"id": template_uuid, "tenant_id": self._tenant_uuid, "now": now}

        if yield_rate is not None:
            update_fields.append("yield_rate = :yield_rate")
            update_params["yield_rate"] = yield_rate
        if standard_portion is not None:
            update_fields.append("standard_portion = :standard_portion")
            update_params["standard_portion"] = standard_portion
        if prep_time_minutes is not None:
            update_fields.append("prep_time_minutes = :prep_time_minutes")
            update_params["prep_time_minutes"] = prep_time_minutes
        if notes is not None:
            update_fields.append("notes = :notes")
            update_params["notes"] = notes

        await self.db.execute(
            text(f"""
                UPDATE bom_templates
                SET {', '.join(update_fields)}
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            update_params,
        )

        # 软删除旧明细
        await self.db.execute(
            text("""
                UPDATE bom_items
                SET is_deleted = true, updated_at = :now
                WHERE bom_id = :bom_id AND tenant_id = :tenant_id
            """),
            {"bom_id": template_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )

        # 插入新明细
        created_items = []
        for item in items:
            item_id = uuid.uuid4()
            ingredient_uuid = uuid.UUID(item["ingredient_id"])

            await self.db.execute(
                text("""
                    INSERT INTO bom_items (
                        id, tenant_id, bom_id, store_id, ingredient_id,
                        standard_qty, raw_qty, unit, unit_cost_fen,
                        is_key_ingredient, is_optional, waste_factor,
                        prep_notes, item_action, is_deleted,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :bom_id, :store_id, :ingredient_id,
                        :standard_qty, :raw_qty, :unit, :unit_cost_fen,
                        :is_key_ingredient, :is_optional, :waste_factor,
                        :prep_notes, 'ADD', false,
                        :now, :now
                    )
                """),
                {
                    "id": item_id,
                    "tenant_id": self._tenant_uuid,
                    "bom_id": template_uuid,
                    "store_id": store_uuid,
                    "ingredient_id": ingredient_uuid,
                    "standard_qty": item["standard_qty"],
                    "raw_qty": item.get("raw_qty"),
                    "unit": item["unit"],
                    "unit_cost_fen": item.get("unit_cost_fen"),
                    "is_key_ingredient": item.get("is_key_ingredient", False),
                    "is_optional": item.get("is_optional", False),
                    "waste_factor": item.get("waste_factor", 0),
                    "prep_notes": item.get("prep_notes"),
                    "now": now,
                },
            )
            created_items.append({
                "id": str(item_id),
                "ingredient_id": item["ingredient_id"],
                "standard_qty": item["standard_qty"],
                "unit": item["unit"],
                "unit_cost_fen": item.get("unit_cost_fen"),
            })

        await self.db.flush()

        log.info(
            "bom_template_updated",
            template_id=template_id,
            item_count=len(items),
        )

        return {
            "id": template_id,
            "dish_id": str(template_row["dish_id"]),
            "version": template_row["version"],
            "items": created_items,
        }

    # ─── 软删除 ───

    async def delete_bom_template(self, template_id: str) -> bool:
        """软删除 BOM 模板及其明细"""
        await self._set_tenant()

        template_uuid = uuid.UUID(template_id)
        now = datetime.now(timezone.utc)

        # 确认存在
        check = await self.db.execute(
            text("""
                SELECT id FROM bom_templates
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid},
        )
        if not check.scalar_one_or_none():
            return False

        # 软删除模板
        await self.db.execute(
            text("""
                UPDATE bom_templates
                SET is_deleted = true, is_active = false, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )

        # 软删除明细
        await self.db.execute(
            text("""
                UPDATE bom_items
                SET is_deleted = true, updated_at = :now
                WHERE bom_id = :bom_id AND tenant_id = :tenant_id
            """),
            {"bom_id": template_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )

        await self.db.flush()

        log.info("bom_template_deleted", template_id=template_id)
        return True

    # ─── 激活版本 ───

    async def activate_version(self, template_id: str) -> Optional[dict]:
        """激活指定 BOM 版本, 同时停用同菜品的其他版本"""
        await self._set_tenant()

        template_uuid = uuid.UUID(template_id)
        now = datetime.now(timezone.utc)

        # 查询模板
        result = await self.db.execute(
            text("""
                SELECT id, dish_id, version, store_id
                FROM bom_templates
                WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid},
        )
        row = result.mappings().first()
        if not row:
            return None

        dish_id = row["dish_id"]

        # 先停用同菜品所有版本
        await self.db.execute(
            text("""
                UPDATE bom_templates
                SET is_active = false, updated_at = :now
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"dish_id": dish_id, "tenant_id": self._tenant_uuid, "now": now},
        )

        # 激活指定版本
        await self.db.execute(
            text("""
                UPDATE bom_templates
                SET is_active = true, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": template_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )

        await self.db.flush()

        log.info(
            "bom_version_activated",
            template_id=template_id,
            dish_id=str(dish_id),
            version=row["version"],
        )

        return {
            "id": template_id,
            "dish_id": str(dish_id),
            "version": row["version"],
            "is_active": True,
        }
