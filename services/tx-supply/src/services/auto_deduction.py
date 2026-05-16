"""自动扣料引擎 -- 订单完成 -> BOM自动扣料 -> 库存减少

核心流程：
1. 订单完成时，根据每道菜的 BOM 配方（dish_ingredients / bom_items）
2. 自动创建 ingredient_transactions (type=consume)
3. 扣减 ingredients.current_quantity
4. 库存不足时记录告警但不阻塞（允许负库存）

金额单位：分(fen)

PRD-08（2026-05-15）：deduct_for_dish / deduct_for_order 增加 dept_id 可选参数 —
当 dept_id 提供时，扣料前 BOM 每行 ingredient 经 dept_whitelist_service 校验；
违反 raise IngredientNotAllowedError，savepoint 回滚整单。
caller (tx-trade) 当前未传 dept_id（保 backward compat），激活为 follow-up。

PRD-11 sub-A（2026-05-15）：deduct_for_dish / deduct_for_order 增加 share_split 可选参数 —
当 caller 提供 ShareSplitSpec (method/count/weights/amounts_fen) + dish_id 时,
扣料后 emit inventory.split_attributed event 携 cost 切分到 N share. BOM 物理消耗
**不变** (1 dish 仍消耗 1 份 BOM, 只是 cost 分摊到多 share). caller (tx-trade) 当前
未传 share_split (保 backward compat); 激活为 PR-B follow-up.

PRD-11 sub-B.2（2026-05-16 / Tier 1 第 30 例）：deduct_for_dish / deduct_for_order 增加
source_event_id 可选参数 — projector 路径必传, 由 IndexSplitProjector 消费
ITEMS_SETTLED 调用. 内部派生 uuid5 per-row source_event_id (基于 event_id +
order_item_id + dish_id + ingredient_id + line_idx). v437 UNIQUE
(tenant_id, source_event_id) WHERE NOT NULL 让重放命中 → IntegrityError →
projector savepoint rollback + 推进 checkpoint = 防 F2 重复扣料 P0.
非 projector 路径不传, source_event_id 写 NULL, UNIQUE 不参与, backward compat.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import (
    DishIngredient,
    Ingredient,
    IngredientTransaction,
)
from shared.ontology.src.enums import InventoryStatus

log = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  自动扣料引擎
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置当前租户上下文（RLS）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _get_bom_for_dish(
    db: AsyncSession,
    dish_id: uuid.UUID,
    tenant_uuid: uuid.UUID,
) -> list[dict[str, Any]]:
    """获取一道菜的 BOM 配方行

    优先查 dish_ingredients 表（简单BOM），返回 ingredient_id + quantity + unit。
    """
    result = await db.execute(
        select(DishIngredient)
        .where(DishIngredient.dish_id == dish_id)
        .where(DishIngredient.tenant_id == tenant_uuid)
        .where(DishIngredient.is_deleted == False)  # noqa: E712
    )
    rows = result.scalars().all()
    return [
        {
            "ingredient_id": row.ingredient_id,
            "quantity": float(row.quantity),
            "unit": row.unit,
        }
        for row in rows
    ]


def _calc_status(current: float, min_qty: float) -> str:
    """根据库存量计算状态"""
    if current <= 0:
        return InventoryStatus.out_of_stock.value
    if current <= min_qty * 0.3:
        return InventoryStatus.critical.value
    if current <= min_qty:
        return InventoryStatus.low.value
    return InventoryStatus.normal.value


# ─── 单道菜扣料 ───


async def deduct_for_dish(
    dish_id: str,
    quantity: int,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    dept_id: Optional[str] = None,
    share_split: Optional[dict[str, Any]] = None,
    order_id_for_event: Optional[str] = None,
    order_item_id_for_event: Optional[str] = None,
    source_event_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    """对单道菜执行 BOM 扣料

    Args:
        dish_id: 菜品 UUID
        quantity: 菜品份数
        store_id: 门店 UUID
        tenant_id: 租户 UUID
        db: 数据库会话（调用方管理事务）
        dept_id: PRD-08 —当上层 caller 提供制作菜品的档口 ID 时，扣料前
                 经 dept_whitelist_service 校验 BOM 每行 ingredient；违反
                 raise IngredientNotAllowedError（毛利底线硬约束）。当前
                 caller (tx-trade) 未传，None 默认跳过校验保 backward compat。
        share_split: PRD-11 sub-A — caller (PR-B tx-trade) 提供 ShareSplitSpec dict
                     (method/count/weights/amounts_fen) 时, 扣料后 emit
                     inventory.split_attributed event 携 cost 切分到 N share.
                     BOM 物理消耗**不变**, 只是 cost 分摊到多 share. 当前 caller
                     未传 None 默认跳过保 backward compat. 提供时经 share_split_service
                     .apply_split 双层校验 (规则+spec) 再 resolve.
        order_id_for_event: PRD-11 — event payload order_id (caller PR-B 传)
        order_item_id_for_event: PRD-11 — event payload order_item_id (caller PR-B 传)
        source_event_id: PRD-11 sub-B.2 — projector (IndexSplitProjector) 消费
                         ITEMS_SETTLED 时传 event.event_id. 内部 uuid5 派生 per-row
                         IngredientTransaction.source_event_id 让 v437 UNIQUE
                         (tenant_id, source_event_id) WHERE NOT NULL 在重放时触
                         IntegrityError, projector savepoint rollback 防 F2 重复扣料.
                         None 默认 (非 projector 路径) 保 backward compat.

    Returns:
        {deducted: [...], missing_bom: bool, insufficient_stock: [...],
         split_attribution?: {method, count, shares} — 当 share_split 提供时}

    Raises:
        IngredientNotAllowedError: 当 dept_id 提供且该档口未授权某 BOM ingredient 时
        ValueError: 当 share_split 提供但 dish 未配置 rule / allow_share=FALSE /
                    超 max_share_count / sum(amounts_fen) != bom_cost_total_fen
    """
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    store_uuid = uuid.UUID(store_id)

    await _set_tenant(db, tenant_id)

    bom_lines = await _get_bom_for_dish(db, dish_uuid, tenant_uuid)
    if not bom_lines:
        log.warning("bom_not_found", dish_id=dish_id)
        return {"deducted": [], "missing_bom": True, "insufficient_stock": []}

    # PRD-08 白名单硬阻塞 — dept_id 提供时, BOM 每行 ingredient 经白名单校验
    # 违反 raise IngredientNotAllowedError, 调用方事务 rollback 整单
    #
    # §19 round-1 P1-2 follow-up (caller 激活前必修):
    # 当前逐行串行 await validate_ingredient_allowed — 200 桌 × 5 dish × 5 ingredient
    # = 5000 次 service 调用. Tier 1 P99 < 200ms 门槛会破. tx-trade 激活 dept_id 透传
    # 前必须先改为 batch SELECT `WHERE (dept_id, ingredient_id) IN (...)`
    # + in-memory 校验, 或 request-scoped 缓存. 见 PRD-08 follow-up issue.
    if dept_id is not None:
        from .dept_whitelist_service import validate_ingredient_allowed

        for line in bom_lines:
            line_ing_id = line.get("ingredient_id")
            if not line_ing_id:
                continue
            try:
                uuid.UUID(line_ing_id)
            except (ValueError, TypeError):
                continue  # broken row 跳过 (与 L131 内部一致)
            line_qty = line.get("quantity") or 0
            line_total = (
                Decimal(str(line_qty)) * Decimal(str(quantity))
                if line_qty
                else None
            )
            await validate_ingredient_allowed(
                db,
                tenant_id,
                dept_id=str(dept_id),
                ingredient_id=str(line_ing_id),
                qty=line_total,
                raise_on_violation=True,
            )

    deducted: list[dict[str, Any]] = []
    insufficient_stock: list[dict[str, Any]] = []

    # Tier 1 行锁防 ABBA 死锁（audit doc §4.3 P0）：
    # 一道菜的 BOM 可含多个 ingredient（如红烧鱼 = 鱼 + 葱姜蒜 + 酱油），
    # 两单同时完成不同菜品但 BOM 共享 ingredient → 锁顺序不同会 ABBA 死锁.
    # 范本：tx-member/stored_value_service.py transfer 函数 2 卡同锁 sorted([from, to]).
    # 跳过无效 ingredient_id 的 BOM 行（保留原 broken-row 日志行为）.
    sorted_bom_lines: list[dict[str, Any]] = []
    for line in bom_lines:
        ing_id = line["ingredient_id"]
        try:
            uuid.UUID(ing_id)
        except ValueError:
            log.warning("invalid_ingredient_id", ingredient_id=ing_id, dish_id=dish_id)
            continue
        sorted_bom_lines.append(line)
    sorted_bom_lines.sort(key=lambda x: str(x["ingredient_id"]))

    for line_idx, line in enumerate(sorted_bom_lines):
        ing_id = line["ingredient_id"]
        consume_qty = line["quantity"] * quantity  # BOM用量 x 份数
        ing_uuid = uuid.UUID(ing_id)

        result = await db.execute(
            select(Ingredient)
            .where(Ingredient.id == ing_uuid)
            .where(Ingredient.store_id == store_uuid)
            .where(Ingredient.tenant_id == tenant_uuid)
            .where(Ingredient.is_deleted == False)  # noqa: E712
            .with_for_update()
        )
        ingredient = result.scalar_one_or_none()
        if ingredient is None:
            log.warning("ingredient_not_in_store", ingredient_id=ing_id, store_id=store_id)
            continue

        old_qty = ingredient.current_quantity
        new_qty = old_qty - consume_qty

        # 库存不足：记录告警但不阻塞（允许负库存）
        if new_qty < 0:
            insufficient_stock.append(
                {
                    "ingredient_id": str(ingredient.id),
                    "ingredient_name": ingredient.ingredient_name,
                    "required_qty": consume_qty,
                    "available_qty": old_qty,
                    "shortage_qty": abs(new_qty),
                }
            )
            log.warning(
                "insufficient_stock",
                ingredient_name=ingredient.ingredient_name,
                required=consume_qty,
                available=old_qty,
            )

        # 扣减库存
        ingredient.current_quantity = new_qty
        ingredient.status = _calc_status(new_qty, ingredient.min_quantity)

        # 创建消费流水
        # PRD-11 sub-B.2: source_event_id 派生 — 当 caller (projector) 传 source_event_id 时
        # 每行 BOM 派生确定性 uuid5 (基于 event_id + order_item_id + dish_id + ingredient_id
        # + line_idx); 同 event 重放生成相同 UUID, v437 UNIQUE WHERE NOT NULL 触
        # IntegrityError, projector savepoint rollback. 非 projector 路径 None → NULL 写入.
        per_row_source_event_id: Optional[uuid.UUID] = None
        if source_event_id is not None:
            seed = (
                f"{source_event_id}|"
                f"{order_item_id_for_event or 'na'}|"
                f"{dish_id}|"
                f"{ingredient.id}|"
                f"{line_idx}"
            )
            per_row_source_event_id = uuid.uuid5(source_event_id, seed)
        txn = IngredientTransaction(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            ingredient_id=ingredient.id,
            store_id=store_uuid,
            transaction_type="consume",
            quantity=-consume_qty,
            unit_cost_fen=ingredient.unit_price_fen,
            total_cost_fen=(int(consume_qty * ingredient.unit_price_fen) if ingredient.unit_price_fen else None),
            quantity_before=old_qty,
            quantity_after=new_qty,
            performed_by="auto_deduction",
            notes=f"BOM扣料: dish={dish_id}, qty={quantity}",
            source_event_id=per_row_source_event_id,
        )
        db.add(txn)

        deducted.append(
            {
                "ingredient_id": str(ingredient.id),
                "ingredient_name": ingredient.ingredient_name,
                "consumed_qty": consume_qty,
                "unit": ingredient.unit,
                "stock_before": old_qty,
                "stock_after": new_qty,
                "transaction_id": str(txn.id),
                # PRD-11 sub-A: 暴露 total_cost_fen 让 share_split 路径汇总分摊
                "total_cost_fen": txn.total_cost_fen,
            }
        )

    await db.flush()

    result: dict[str, Any] = {
        "deducted": deducted,
        "missing_bom": False,
        "insufficient_stock": insufficient_stock,
    }

    # PRD-11 sub-A: share_split 提供时 emit inventory.split_attributed event
    # BOM 物理扣料**不变** (loop 已完成), 只是 cost attribution 切分到多 share
    if share_split is not None:
        try:
            from pydantic import ValidationError as _PydanticValidationError

            from .share_split_service import apply_split
            from ..models.share_split_models import ShareSplitSpec
            from shared.events.src.emitter import emit_event
            from shared.events.src.event_types import InventoryEventType

            # §19 round-1 P1-2 fix: pydantic v2 ValidationError 不是 ValueError 子类,
            # 须显式转 ValueError 让 caller (sub-B cashier_engine) route 层 422
            # 映射. 不放进 (ImportError, RuntimeError) fail-open 列表 — caller 显式
            # 传了 split_spec 期望生效, 配置错应 fail-loud 拒绝整次下单 (徐记 200 桌
            # 峰值场景每分钟数百次调用 — 4xx 而非 5xx 才能保下单成功率 SLI).
            try:
                spec = ShareSplitSpec(**share_split)
            except _PydanticValidationError as ve:
                raise ValueError(
                    f"share_split 参数无效: {ve.errors()}"
                ) from ve
            total_bom_cost_fen = sum(
                d.get("total_cost_fen") or 0 for d in deducted
            )
            split_result = await apply_split(
                db,
                tenant_id,
                dish_id=dish_id,
                spec=spec,
                bom_cost_total_fen=total_bom_cost_fen,
            )
            # event fire-and-forget (CLAUDE.md §15: asyncio.create_task)
            asyncio.create_task(
                emit_event(
                    event_type=InventoryEventType.SPLIT_ATTRIBUTED,
                    tenant_id=tenant_id,
                    stream_id=order_id_for_event or dish_id,
                    payload={
                        "order_id": order_id_for_event,
                        "order_item_id": order_item_id_for_event,
                        "dish_id": dish_id,
                        "method": split_result.method.value,
                        "count": split_result.count,
                        "bom_cost_total_fen": split_result.bom_cost_total_fen,
                        "shares": [
                            {
                                "share_index": s.share_index,
                                "weight": str(s.weight),
                                "attributed_cost_fen": s.attributed_cost_fen,
                            }
                            for s in split_result.shares
                        ],
                    },
                    store_id=store_id,
                    source_service="tx-supply",
                )
            )
            result["split_attribution"] = {
                "method": split_result.method.value,
                "count": split_result.count,
                "bom_cost_total_fen": split_result.bom_cost_total_fen,
                "shares": [
                    {
                        "share_index": s.share_index,
                        "weight": str(s.weight),
                        "attributed_cost_fen": s.attributed_cost_fen,
                    }
                    for s in split_result.shares
                ],
            }
            log.info(
                "share_split_attributed",
                dish_id=dish_id,
                order_id=order_id_for_event,
                method=split_result.method.value,
                count=split_result.count,
                bom_cost_total_fen=split_result.bom_cost_total_fen,
            )
        except ValueError:
            # 规则/spec 校验失败 — 业务异常, 让 caller 处理 (route 422)
            raise
        except (ImportError, RuntimeError) as exc:
            # 事件 emitter 不可用 — fail-open 记 warning 不阻塞 BOM 扣料
            log.warning(
                "share_split_event_emit_failed",
                dish_id=dish_id,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

    return result


# ─── 订单级扣料（事务性） ───


async def deduct_for_order(
    order_id: str,
    order_items: list[dict[str, Any]],
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    dept_id: Optional[str] = None,
    source_event_id: Optional[uuid.UUID] = None,
) -> dict[str, Any]:
    """订单完成时的批量扣料

    事务性保证：一个订单的扣料要么全部成功要么全部回滚。
    调用方应在外层管理 begin/commit/rollback。

    Args:
        order_id: 订单 UUID
        order_items: [{dish_id, quantity, item_name}, ...]
        store_id: 门店 UUID
        tenant_id: 租户 UUID
        db: 数据库会话
        dept_id: PRD-08 — 透传给 deduct_for_dish 用于 BOM 行白名单校验；
                 None 默认跳过校验（caller (tx-trade) 当前未传，激活为 follow-up）
        source_event_id: PRD-11 sub-B.2 — IndexSplitProjector 消费 ITEMS_SETTLED 时
                         传 event.event_id, 透传到每个 deduct_for_dish 派生 per-row
                         IngredientTransaction.source_event_id (v437 UNIQUE F2 P0 防重放).
                         None 默认 (非 projector 路径) 保 backward compat.

    Returns:
        {
            order_id, deducted_items: [...],
            missing_bom: [...], insufficient_stock: [...]
        }

    Raises:
        IngredientNotAllowedError: 当 dept_id 提供且任一 dish 的 BOM 行未授权时；
                                  begin_nested savepoint 回滚整单（无半状态）
    """
    log.info("deduct_for_order.start", order_id=order_id, item_count=len(order_items))

    all_deducted: list[dict[str, Any]] = []
    all_missing_bom: list[dict[str, Any]] = []
    all_insufficient: list[dict[str, Any]] = []

    tenant_uuid = uuid.UUID(tenant_id)
    store_uuid = uuid.UUID(store_id)

    # 使用 savepoint 保证原子性
    async with db.begin_nested():
        # Tier 1 跨 dish ABBA 防护（Issue #549, audit doc §4.3 P0 下游）:
        # 订单含多 dish 共享同 ingredient 时, 若每个 dish 内部 sorted 但跨 dish 顺序不同
        # (订单 A=[dish1, dish2] vs B=[dish2, dish1]) 仍可 ABBA 死锁.
        # 修法: 在 deduct_for_dish 业务循环前预聚合所有 BOM ingredient_id, 去重 + sorted(key=str)
        # 升序逐行 SELECT FOR UPDATE 预锁. 后续 deduct_for_dish 内部 sorted SELECT 是 reentrant
        # 同事务无害, 保留作 defense in depth (单 dish 直接路径仍需该防御).
        # 范本: services/tx-member/src/services/stored_value_service.py transfer 2 卡 sorted([from, to]).
        # `key=str` 必须与 deduct_for_dish L131 内部 sorted key 一致, 否则一致性破坏防御失效.
        await _set_tenant(db, tenant_id)
        bom_cache: dict[uuid.UUID, list[dict[str, Any]]] = {}
        all_ing_ids: set[uuid.UUID] = set()
        for item in order_items:
            dish_id_str = item.get("dish_id")
            if not dish_id_str:
                continue
            try:
                dish_uuid = uuid.UUID(dish_id_str)
            except (ValueError, TypeError):
                continue
            if dish_uuid not in bom_cache:
                bom_cache[dish_uuid] = await _get_bom_for_dish(db, dish_uuid, tenant_uuid)
            for line in bom_cache[dish_uuid]:
                ing_id_str = line.get("ingredient_id")
                if not ing_id_str:
                    continue
                try:
                    all_ing_ids.add(uuid.UUID(ing_id_str))
                except (ValueError, TypeError):
                    # 跳 broken row — 与 deduct_for_dish L127 行为一致
                    continue

        for ing_uuid in sorted(all_ing_ids, key=str):
            await db.execute(
                select(Ingredient.id)
                .where(Ingredient.id == ing_uuid)
                .where(Ingredient.store_id == store_uuid)
                .where(Ingredient.tenant_id == tenant_uuid)
                .where(Ingredient.is_deleted == False)  # noqa: E712
                .with_for_update()
            )

        for item in order_items:
            dish_id = item.get("dish_id")
            quantity = item.get("quantity", 1)
            item_name = item.get("item_name", "")

            if not dish_id:
                log.warning("order_item_no_dish_id", item_name=item_name)
                continue

            # PRD-11 sub-A: 透传 share_split + order_item_id 元数据 (caller 在 item dict 上传)
            item_share_split = item.get("share_split")
            item_order_item_id = item.get("order_item_id")
            result = await deduct_for_dish(
                dish_id=dish_id,
                quantity=quantity,
                store_id=store_id,
                tenant_id=tenant_id,
                db=db,
                dept_id=dept_id,
                share_split=item_share_split,
                order_id_for_event=order_id,
                order_item_id_for_event=item_order_item_id,
                source_event_id=source_event_id,
            )

            if result["missing_bom"]:
                all_missing_bom.append(
                    {
                        "dish_id": dish_id,
                        "item_name": item_name,
                        "quantity": quantity,
                    }
                )
            else:
                for d in result["deducted"]:
                    d["order_id"] = order_id
                    d["dish_id"] = dish_id
                all_deducted.extend(result["deducted"])

            all_insufficient.extend(result["insufficient_stock"])

        # 记录订单级 reference 到所有流水
        # （已在 deduct_for_dish 的 notes 中记录）

    log.info(
        "deduct_for_order.done",
        order_id=order_id,
        deducted_count=len(all_deducted),
        missing_bom_count=len(all_missing_bom),
        insufficient_count=len(all_insufficient),
    )

    return {
        "order_id": order_id,
        "deducted_items": all_deducted,
        "missing_bom": all_missing_bom,
        "insufficient_stock": all_insufficient,
    }


# ─── 扣料回滚（退菜/退单） ───


async def rollback_deduction(
    order_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """回滚指定订单的所有扣料

    查找该订单产生的所有 consume 类型流水，逐条反向回补库存。

    Args:
        order_id: 订单 UUID
        tenant_id: 租户 UUID
        db: 数据库会话

    Returns:
        {order_id, rolled_back_count, restored_items: [...]}
    """
    tenant_uuid = uuid.UUID(tenant_id)
    await _set_tenant(db, tenant_id)

    log.info("rollback_deduction.start", order_id=order_id)

    # 查找该订单产生的所有 consume 流水（通过 notes 中的 order 信息匹配）
    # 更优的方案：通过 reference_id 关联
    result = await db.execute(
        select(IngredientTransaction)
        .where(IngredientTransaction.tenant_id == tenant_uuid)
        .where(IngredientTransaction.transaction_type == "consume")
        .where(IngredientTransaction.is_deleted == False)  # noqa: E712
        .where(IngredientTransaction.reference_id == order_id)
    )
    consume_txns = result.scalars().all()

    # 如果没有通过 reference_id 找到，尝试通过 notes 模糊匹配
    if not consume_txns:
        result = await db.execute(
            select(IngredientTransaction)
            .where(IngredientTransaction.tenant_id == tenant_uuid)
            .where(IngredientTransaction.transaction_type == "consume")
            .where(IngredientTransaction.is_deleted == False)  # noqa: E712
            .where(IngredientTransaction.notes.contains(order_id))
        )
        consume_txns = result.scalars().all()

    if not consume_txns:
        log.warning("rollback_no_transactions", order_id=order_id)
        return {
            "order_id": order_id,
            "rolled_back_count": 0,
            "restored_items": [],
        }

    restored_items: list[dict[str, Any]] = []

    async with db.begin_nested():
        for txn in consume_txns:
            restore_qty = abs(txn.quantity)  # consume 流水 quantity 为负

            # 恢复库存
            ing_result = await db.execute(
                select(Ingredient)
                .where(Ingredient.id == txn.ingredient_id)
                .where(Ingredient.tenant_id == tenant_uuid)
                .where(Ingredient.is_deleted == False)  # noqa: E712
            )
            ingredient = ing_result.scalar_one_or_none()
            if ingredient is None:
                log.warning("rollback_ingredient_missing", ingredient_id=str(txn.ingredient_id))
                continue

            old_qty = ingredient.current_quantity
            new_qty = old_qty + restore_qty
            ingredient.current_quantity = new_qty
            ingredient.status = _calc_status(new_qty, ingredient.min_quantity)

            # 创建回滚流水
            rollback_txn = IngredientTransaction(
                id=uuid.uuid4(),
                tenant_id=tenant_uuid,
                ingredient_id=ingredient.id,
                store_id=txn.store_id,
                transaction_type="rollback",
                quantity=restore_qty,
                unit_cost_fen=txn.unit_cost_fen,
                total_cost_fen=(int(restore_qty * txn.unit_cost_fen) if txn.unit_cost_fen else None),
                quantity_before=old_qty,
                quantity_after=new_qty,
                performed_by="auto_rollback",
                reference_id=order_id,
                notes=f"回滚扣料: order={order_id}, 原流水={txn.id}",
            )
            db.add(rollback_txn)

            # 标记原流水为已删除
            txn.is_deleted = True

            restored_items.append(
                {
                    "ingredient_id": str(ingredient.id),
                    "ingredient_name": ingredient.ingredient_name,
                    "restored_qty": restore_qty,
                    "stock_before": old_qty,
                    "stock_after": new_qty,
                }
            )

    await db.flush()

    log.info(
        "rollback_deduction.done",
        order_id=order_id,
        rolled_back_count=len(restored_items),
    )

    return {
        "order_id": order_id,
        "rolled_back_count": len(restored_items),
        "restored_items": restored_items,
    }
