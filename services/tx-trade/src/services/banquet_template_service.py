"""宴席套餐模板引擎服务 — v160

提供套餐模板的增删改查，以及从模板生成报价单的能力。
所有方法 async，纯 ORM，金额单位：分（整数）。
"""
import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.banquet import BanquetMenuTemplate, BanquetTemplateItem

logger = structlog.get_logger(__name__)


# ─── 内部序列化辅助 ──────────────────────────────────────────────────────────

def _item_to_dict(item: BanquetTemplateItem) -> dict:
    return {
        "id": str(item.id),
        "dish_name": item.dish_name,
        "dish_category": item.dish_category,
        "quantity": float(item.quantity),
        "unit": item.unit,
        "is_signature": item.is_signature,
        "is_optional": item.is_optional,
        "notes": item.notes,
        "sort_order": item.sort_order,
    }


def _template_to_dict(tpl: BanquetMenuTemplate, include_items: bool = True) -> dict:
    data: dict[str, Any] = {
        "id": str(tpl.id),
        "tenant_id": str(tpl.tenant_id),
        "store_id": str(tpl.store_id) if tpl.store_id else None,
        "name": tpl.name,
        "category": tpl.category,
        "description": tpl.description,
        "guest_count_min": tpl.guest_count_min,
        "guest_count_max": tpl.guest_count_max,
        "price_per_table_fen": tpl.price_per_table_fen,
        "price_per_person_fen": tpl.price_per_person_fen,
        "min_table_count": tpl.min_table_count,
        "deposit_rate": float(tpl.deposit_rate),
        "is_active": tpl.is_active,
        "sort_order": tpl.sort_order,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
    }
    if include_items:
        data["items"] = [_item_to_dict(i) for i in tpl.items if not i.is_deleted]
    return data


# ─── 公开 API ────────────────────────────────────────────────────────────────

async def create_template(
    name: str,
    category: str,
    description: str | None,
    guest_count_min: int,
    guest_count_max: int,
    price_per_table_fen: int,
    price_per_person_fen: int | None,
    min_table_count: int,
    deposit_rate: float,
    items: list[dict],
    store_id: str | None = None,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建宴席套餐模板（含菜品明细）"""
    log = logger.bind(action="create_template", tenant_id=tenant_id, name=name)

    tpl = BanquetMenuTemplate(
        tenant_id=uuid.UUID(tenant_id),
        store_id=uuid.UUID(store_id) if store_id else None,
        name=name,
        category=category,
        description=description,
        guest_count_min=guest_count_min,
        guest_count_max=guest_count_max,
        price_per_table_fen=price_per_table_fen,
        price_per_person_fen=price_per_person_fen,
        min_table_count=min_table_count,
        deposit_rate=Decimal(str(deposit_rate)),
        is_active=True,
    )
    db.add(tpl)
    await db.flush()  # 获取 tpl.id，不提交事务

    for idx, raw in enumerate(items):
        item = BanquetTemplateItem(
            tenant_id=uuid.UUID(tenant_id),
            template_id=tpl.id,
            dish_name=raw["dish_name"],
            dish_category=raw.get("dish_category"),
            quantity=Decimal(str(raw.get("quantity", 1))),
            unit=raw.get("unit", "道"),
            is_signature=bool(raw.get("is_signature", False)),
            is_optional=bool(raw.get("is_optional", False)),
            notes=raw.get("notes"),
            sort_order=raw.get("sort_order", idx),
        )
        db.add(item)

    await db.commit()
    await db.refresh(tpl)

    log.info("banquet_template_created", template_id=str(tpl.id))
    return _template_to_dict(tpl)


async def list_templates(
    category: str | None = None,
    store_id: str | None = None,
    guest_count: int | None = None,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """列出套餐模板（支持分类/门店/人数过滤）"""
    stmt = (
        select(BanquetMenuTemplate)
        .where(
            BanquetMenuTemplate.is_deleted == False,  # noqa: E712
            BanquetMenuTemplate.is_active == True,    # noqa: E712
        )
        .order_by(BanquetMenuTemplate.sort_order, BanquetMenuTemplate.created_at)
    )

    if category:
        stmt = stmt.where(BanquetMenuTemplate.category == category)

    if store_id:
        # 门店专属 + 集团通用
        stmt = stmt.where(
            (BanquetMenuTemplate.store_id == uuid.UUID(store_id))
            | (BanquetMenuTemplate.store_id.is_(None))
        )
    else:
        # 不限门店时，只返回集团通用
        stmt = stmt.where(BanquetMenuTemplate.store_id.is_(None))

    if guest_count is not None:
        stmt = stmt.where(
            BanquetMenuTemplate.guest_count_min <= guest_count,
            BanquetMenuTemplate.guest_count_max >= guest_count,
        )

    result = await db.execute(stmt)
    templates = result.scalars().all()
    return [_template_to_dict(t) for t in templates]


async def get_template(
    template_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取套餐模板详情"""
    result = await db.execute(
        select(BanquetMenuTemplate).where(
            BanquetMenuTemplate.id == uuid.UUID(template_id),
            BanquetMenuTemplate.is_deleted == False,  # noqa: E712
        )
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        raise ValueError(f"套餐模板不存在：{template_id}")
    return _template_to_dict(tpl)


async def update_template(
    template_id: str,
    updates: dict,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """更新套餐模板（支持部分更新，items 字段会完整替换）"""
    log = logger.bind(action="update_template", tenant_id=tenant_id, template_id=template_id)

    result = await db.execute(
        select(BanquetMenuTemplate).where(
            BanquetMenuTemplate.id == uuid.UUID(template_id),
            BanquetMenuTemplate.is_deleted == False,  # noqa: E712
        )
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        raise ValueError(f"套餐模板不存在：{template_id}")

    # 标量字段更新
    scalar_fields = {
        "name", "category", "description",
        "guest_count_min", "guest_count_max",
        "price_per_table_fen", "price_per_person_fen",
        "min_table_count", "is_active", "sort_order",
    }
    for field in scalar_fields:
        if field in updates:
            setattr(tpl, field, updates[field])

    if "deposit_rate" in updates:
        tpl.deposit_rate = Decimal(str(updates["deposit_rate"]))

    if "store_id" in updates:
        tpl.store_id = uuid.UUID(updates["store_id"]) if updates["store_id"] else None

    # 菜品明细完整替换
    if "items" in updates:
        # 软删除旧明细
        for old_item in tpl.items:
            old_item.is_deleted = True

        for idx, raw in enumerate(updates["items"]):
            item = BanquetTemplateItem(
                tenant_id=uuid.UUID(tenant_id),
                template_id=tpl.id,
                dish_name=raw["dish_name"],
                dish_category=raw.get("dish_category"),
                quantity=Decimal(str(raw.get("quantity", 1))),
                unit=raw.get("unit", "道"),
                is_signature=bool(raw.get("is_signature", False)),
                is_optional=bool(raw.get("is_optional", False)),
                notes=raw.get("notes"),
                sort_order=raw.get("sort_order", idx),
            )
            db.add(item)

    await db.commit()
    await db.refresh(tpl)

    log.info("banquet_template_updated", template_id=template_id)
    return _template_to_dict(tpl)


async def delete_template(
    template_id: str,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """软删除套餐模板"""
    log = logger.bind(action="delete_template", tenant_id=tenant_id, template_id=template_id)

    result = await db.execute(
        select(BanquetMenuTemplate).where(
            BanquetMenuTemplate.id == uuid.UUID(template_id),
            BanquetMenuTemplate.is_deleted == False,  # noqa: E712
        )
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        raise ValueError(f"套餐模板不存在：{template_id}")

    tpl.is_deleted = True
    await db.commit()

    log.info("banquet_template_deleted", template_id=template_id)


async def build_quotation_from_template(
    template_id: str,
    guest_count: int,
    table_count: int,
    adjustments: dict | None = None,
    *,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """从套餐模板生成宴席报价单（不落库，仅返回计算结果）

    Returns:
        {
            template_id, template_name, guest_count, table_count,
            price_per_table_fen, subtotal_fen, deposit_fen,
            items, adjustments, final_total_fen
        }
    """
    log = logger.bind(
        action="build_quotation_from_template",
        tenant_id=tenant_id,
        template_id=template_id,
    )

    result = await db.execute(
        select(BanquetMenuTemplate).where(
            BanquetMenuTemplate.id == uuid.UUID(template_id),
            BanquetMenuTemplate.is_deleted == False,  # noqa: E712
            BanquetMenuTemplate.is_active == True,    # noqa: E712
        )
    )
    tpl = result.scalar_one_or_none()
    if tpl is None:
        raise ValueError(f"套餐模板不存在或已停用：{template_id}")

    if table_count < tpl.min_table_count:
        raise ValueError(
            f"桌数不足：最低 {tpl.min_table_count} 桌，当前 {table_count} 桌"
        )

    subtotal_fen = tpl.price_per_table_fen * table_count
    deposit_fen = int(subtotal_fen * float(tpl.deposit_rate))

    # 处理价格调整（adjustments 支持 {"discount_fen": ..., "extra_fen": ...} 等）
    adj = adjustments or {}
    adjustment_delta = adj.get("discount_fen", 0) * -1 + adj.get("extra_fen", 0)
    final_total_fen = subtotal_fen + adjustment_delta

    active_items = [i for i in tpl.items if not i.is_deleted]
    items_payload = [_item_to_dict(i) for i in active_items]

    log.info(
        "quotation_built",
        template_id=template_id,
        table_count=table_count,
        subtotal_fen=subtotal_fen,
        final_total_fen=final_total_fen,
    )

    return {
        "template_id": str(tpl.id),
        "template_name": tpl.name,
        "category": tpl.category,
        "guest_count": guest_count,
        "table_count": table_count,
        "price_per_table_fen": tpl.price_per_table_fen,
        "price_per_person_fen": tpl.price_per_person_fen,
        "subtotal_fen": subtotal_fen,
        "deposit_rate": float(tpl.deposit_rate),
        "deposit_fen": deposit_fen,
        "items": items_payload,
        "adjustments": adj,
        "adjustment_delta_fen": adjustment_delta,
        "final_total_fen": final_total_fen,
    }
