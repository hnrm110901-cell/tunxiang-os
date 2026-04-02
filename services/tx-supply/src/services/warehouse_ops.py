"""移库与拆组服务

移库: 仓库间商品转移（持久化到 warehouse_transfers / warehouse_transfer_items）
拆分/组装: 原料拆分或组装成半成品
BOM拆分: 成品按配方拆分为原料

持久化层：
- warehouse_transfers 表 — 移库单头
- warehouse_transfer_items 表 — 移库明细
- 若 v064 迁移未运行（表不存在），create_transfer_order 自动降级为内存返回并记录 WARNING
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

_wt_db_mode: Optional[bool] = None  # None=未检测, True=DB, False=内存降级


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


async def _check_wt_db_mode(db: AsyncSession) -> bool:
    """检测 warehouse_transfers 表是否存在（v064 迁移是否已运行）"""
    global _wt_db_mode
    if _wt_db_mode is not None:
        return _wt_db_mode
    try:
        await db.execute(text("SELECT 1 FROM warehouse_transfers LIMIT 1"))
        _wt_db_mode = True
        log.info("warehouse_ops.mode", mode="db")
    except (ProgrammingError, OperationalError):
        _wt_db_mode = False
        log.warning(
            "warehouse_ops.fallback_to_memory",
            reason="warehouse_transfers table not found — run v064_wms_persistence migration",
        )
    return _wt_db_mode


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 移库单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_transfer_order(
    from_warehouse: str,
    to_warehouse: str,
    items: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建移库单，持久化到 warehouse_transfers / warehouse_transfer_items。

    Args:
        from_warehouse: 调出仓库 ID
        to_warehouse: 调入仓库 ID
        items: 移库明细 [{ingredient_id, name, quantity, unit, batch_no}]
        tenant_id: 租户 ID
        db: 数据库会话（AsyncSession）

    Returns:
        移库单
    """
    if from_warehouse == to_warehouse:
        raise ValueError("调出仓库和调入仓库不能相同")
    if not items:
        raise ValueError("移库单必须包含至少一项商品")

    transfer_id = _gen_id("wtf")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    total_qty = sum(i.get("quantity", 0) for i in items)

    record: Dict[str, Any] = {
        "transfer_id": transfer_id,
        "from_warehouse": from_warehouse,
        "to_warehouse": to_warehouse,
        "tenant_id": tenant_id,
        "status": "pending",
        "items": items,
        "item_count": len(items),
        "total_qty": round(total_qty, 2),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    use_db = await _check_wt_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        # v064 schema: from_store_id / to_store_id，主键为 UUID
        await db.execute(
            text("""
                INSERT INTO warehouse_transfers
                    (id, tenant_id, from_store_id, to_store_id,
                     status, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :tenant_id::uuid,
                     :from_store::uuid, :to_store::uuid,
                     'pending', :now, :now)
                RETURNING id
            """),
            {
                "tenant_id": tenant_id,
                "from_store": from_warehouse,
                "to_store": to_warehouse,
                "now": now,
            },
        )

        # 查回刚插入的 UUID（RETURNING）
        id_row = await db.execute(
            text("""
                SELECT id FROM warehouse_transfers
                WHERE tenant_id = :tenant_id::uuid
                  AND from_store_id = :from_store::uuid
                  AND to_store_id = :to_store::uuid
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {
                "tenant_id": tenant_id,
                "from_store": from_warehouse,
                "to_store": to_warehouse,
            },
        )
        db_id_row = id_row.mappings().one_or_none()
        if db_id_row:
            # 用 DB 分配的 UUID 覆盖 transfer_id（回写到 record）
            transfer_id = str(db_id_row["id"])
            record["transfer_id"] = transfer_id

        for item in items:
            await db.execute(
                text("""
                    INSERT INTO warehouse_transfer_items
                        (id, transfer_id, tenant_id, ingredient_id,
                         ingredient_name, unit, requested_qty,
                         created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :transfer_id::uuid, :tenant_id::uuid,
                         :ingredient_id::uuid,
                         :name, :unit, :quantity,
                         :now, :now)
                """),
                {
                    "transfer_id": transfer_id,
                    "tenant_id": tenant_id,
                    "ingredient_id": item.get("ingredient_id"),
                    "name": item.get("name", ""),
                    "quantity": item.get("quantity", 0),
                    "unit": item.get("unit", ""),
                    "now": now,
                },
            )

        await db.flush()

    log.info(
        "warehouse_transfer_created",
        transfer_id=transfer_id,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
        tenant_id=tenant_id,
        item_count=len(items),
        mode="db" if use_db else "memory",
    )
    return record


async def approve_transfer_order(
    transfer_id: str,
    approver_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """审批移库单（状态 pending → approved）。

    Args:
        transfer_id: 移库单 ID
        approver_id: 审批人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {transfer_id, status, approved_by, approved_at}
    """
    now = datetime.now(timezone.utc)
    use_db = await _check_wt_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        # v064: approved_by 为 UUID 类型；status 枚举: pending/in_transit/received/cancelled
        result = await db.execute(
            text("""
                UPDATE warehouse_transfers
                SET status = 'in_transit',
                    approved_by = :approver_id::uuid,
                    updated_at = :now
                WHERE id = :id::uuid AND tenant_id = :tenant_id::uuid
                  AND status = 'pending'
                RETURNING id, status
            """),
            {
                "id": transfer_id,
                "tenant_id": tenant_id,
                "approver_id": approver_id,
                "now": now,
            },
        )
        row = result.mappings().one_or_none()
        if not row:
            return {
                "ok": False,
                "error": f"Transfer {transfer_id} not found or not in pending status",
            }
        await db.flush()

    log.info(
        "warehouse_transfer_approved",
        transfer_id=transfer_id,
        approver_id=approver_id,
        tenant_id=tenant_id,
        mode="db" if use_db else "memory",
    )

    return {
        "ok": True,
        "transfer_id": transfer_id,
        "status": "approved",
        "approved_by": approver_id,
        "approved_at": now.isoformat(),
    }


async def receive_transfer_order(
    transfer_id: str,
    receiver_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """确认收货（状态 approved → completed）。

    Args:
        transfer_id: 移库单 ID
        receiver_id: 收货人 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        {transfer_id, status, received_by, received_at}
    """
    now = datetime.now(timezone.utc)
    use_db = await _check_wt_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        # v064: status 为 received（非 completed），无 received_by/received_at 列
        result = await db.execute(
            text("""
                UPDATE warehouse_transfers
                SET status = 'received',
                    updated_at = :now
                WHERE id = :id::uuid AND tenant_id = :tenant_id::uuid
                  AND status = 'in_transit'
                RETURNING id, status
            """),
            {
                "id": transfer_id,
                "tenant_id": tenant_id,
                "now": now,
            },
        )
        row = result.mappings().one_or_none()
        if not row:
            return {
                "ok": False,
                "error": f"Transfer {transfer_id} not found or not in in_transit status",
            }
        await db.flush()

    log.info(
        "warehouse_transfer_received",
        transfer_id=transfer_id,
        receiver_id=receiver_id,
        tenant_id=tenant_id,
        mode="db" if use_db else "memory",
    )

    return {
        "ok": True,
        "transfer_id": transfer_id,
        "status": "completed",
        "received_by": receiver_id,
        "received_at": now.isoformat(),
    }


async def get_transfer_order(
    transfer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """查询移库单详情。

    Args:
        transfer_id: 移库单 ID
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        移库单详情（含明细）
    """
    use_db = await _check_wt_db_mode(db)

    if use_db:
        await _set_tenant(db, tenant_id)

        # v064 schema: from_store_id / to_store_id，无 item_count / total_qty 聚合列
        header = await db.execute(
            text("""
                SELECT id, tenant_id, from_store_id, to_store_id,
                       status, approved_by,
                       created_at, updated_at
                FROM warehouse_transfers
                WHERE id = :id::uuid AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
            """),
            {"id": transfer_id, "tenant_id": tenant_id},
        )
        row = header.mappings().one_or_none()
        if not row:
            return {"ok": False, "error": f"Transfer {transfer_id} not found"}

        items_result = await db.execute(
            text("""
                SELECT ingredient_id, ingredient_name, requested_qty AS quantity,
                       actual_qty, unit
                FROM warehouse_transfer_items
                WHERE transfer_id = :transfer_id::uuid AND tenant_id = :tenant_id::uuid
                  AND is_deleted = FALSE
            """),
            {"transfer_id": transfer_id, "tenant_id": tenant_id},
        )
        items = [dict(r) for r in items_result.mappings().all()]

        return {
            "ok": True,
            "transfer_id": str(row["id"]),
            "from_warehouse": str(row["from_store_id"]),
            "to_warehouse": str(row["to_store_id"]),
            "status": row["status"],
            "item_count": len(items),
            "items": items,
            "approved_by": str(row["approved_by"]) if row["approved_by"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }

    return {"ok": False, "error": "DB not available — transfer orders are not persisted in memory mode"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 拆分/组装
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_split_assembly(
    item_id: str,
    op_type: str,
    components: List[Dict[str, Any]],
    tenant_id: str,
    db: Any,
) -> Dict[str, Any]:
    """创建拆分或组装单。

    拆分: 将一个原料拆分成多个子项 (如整鸡 → 鸡腿+鸡翅+鸡胸)
    组装: 将多个原料组装成一个半成品 (如鸡腿+调料 → 卤鸡腿)

    Args:
        item_id: 主商品 ID
        op_type: split (拆分) / assembly (组装)
        components: 组件明细 [{ingredient_id, name, quantity, unit}]
        tenant_id: 租户 ID
        db: 数据库会话

    Returns:
        拆组单
    """
    if op_type not in ("split", "assembly"):
        raise ValueError(f"op_type 必须为 split 或 assembly, 收到: {op_type}")
    if not components:
        raise ValueError("拆组单必须包含至少一项组件")

    sa_id = _gen_id("sa")
    now = _now_iso()

    record: Dict[str, Any] = {
        "sa_id": sa_id,
        "item_id": item_id,
        "op_type": op_type,
        "tenant_id": tenant_id,
        "status": "completed",
        "components": components,
        "component_count": len(components),
        "total_component_qty": round(
            sum(c.get("quantity", 0) for c in components), 4
        ),
        "created_at": now,
    }

    log.info(
        "split_assembly_created",
        sa_id=sa_id,
        item_id=item_id,
        op_type=op_type,
        tenant_id=tenant_id,
        component_count=len(components),
    )
    return record


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. BOM 拆分 (成品 → 原料)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def create_bom_split(
    dish_id: str,
    quantity: float,
    tenant_id: str,
    db: Any,
    *,
    bom: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """BOM 拆分: 按配方将成品拆分为原料需求。

    Args:
        dish_id: 菜品 ID
        quantity: 成品数量
        tenant_id: 租户 ID
        db: 数据库会话
        bom: BOM 配方 [{ingredient_id, name, qty_per_dish, unit, cost_fen}]

    Returns:
        拆分后的原料清单
    """
    if quantity <= 0:
        raise ValueError("拆分数量必须大于0")

    bom_data = bom or []
    if not bom_data:
        raise ValueError(f"菜品 {dish_id} 无 BOM 配方数据")

    split_id = _gen_id("bsplit")
    now = _now_iso()

    ingredients: List[Dict[str, Any]] = []
    total_cost_fen = 0
    for item in bom_data:
        qty = round(item.get("qty_per_dish", 0) * quantity, 4)
        cost = int(item.get("cost_fen", 0) * quantity)
        ingredients.append({
            "ingredient_id": item.get("ingredient_id"),
            "name": item.get("name", ""),
            "required_qty": qty,
            "unit": item.get("unit", ""),
            "estimated_cost_fen": cost,
        })
        total_cost_fen += cost

    record: Dict[str, Any] = {
        "split_id": split_id,
        "dish_id": dish_id,
        "quantity": quantity,
        "tenant_id": tenant_id,
        "status": "completed",
        "ingredients": ingredients,
        "ingredient_count": len(ingredients),
        "total_cost_fen": total_cost_fen,
        "created_at": now,
    }

    log.info(
        "bom_split_created",
        split_id=split_id,
        dish_id=dish_id,
        quantity=quantity,
        tenant_id=tenant_id,
        ingredient_count=len(ingredients),
        total_cost_fen=total_cost_fen,
    )
    return record
