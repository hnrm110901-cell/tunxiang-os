"""分解型 BOM 计算服务 — PRD-09 整件拆零

纯计算函数，不写库存、不写 DB（dry-run）。
写库存是 warehouse_ops 职责；本模块仅提供分解比例计算。

场景：
  10kg 整鱼（yield_qty=10）→ 鱼柳 5kg + 鱼骨 2kg + 内脏 3kg
  按比例计算：input_qty=5kg → 鱼柳 2.5kg + 鱼骨 1kg + 内脏 1.5kg
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


@dataclass
class DisassemblyOutputItem:
    ingredient_name: str
    ingredient_code: str | None
    output_qty: float
    unit: str


@dataclass
class DisassemblyResult:
    bom_id: str
    input_qty: float
    yield_qty: float
    outputs: List[DisassemblyOutputItem]


async def disassemble_ingredient(
    bom_id: str,
    input_qty: float,
    tenant_id: str,
    db: AsyncSession,
) -> DisassemblyResult:
    """按分解型 BOM 计算各产出组件数量（dry-run，不写 DB）。

    Args:
        bom_id: dish_boms.id，必须 assembly_type='disassembly'
        input_qty: 投入整件数量（如 5.0 kg 整鱼）
        tenant_id: 租户 ID（RLS 已设置，此处用于查询过滤）
        db: async DB session（RLS 须已由调用方 _set_tenant 设好）

    Returns:
        DisassemblyResult 包含各组件按比例计算的产出量

    Raises:
        ValueError: BOM 不存在、assembly_type 不是 disassembly、
                    或产出总量超过 yield_qty、或 items 为空
    """
    # 查 dish_boms（已由 RLS 隔离）
    bom_row = await db.execute(
        text(
            """
            SELECT id, yield_qty, assembly_type
            FROM dish_boms
            WHERE id = :bom_id
              AND tenant_id = :tid
              AND is_deleted = false
        """
        ),
        {"bom_id": bom_id, "tid": tenant_id},
    )
    bom = bom_row.mappings().first()
    if not bom:
        raise ValueError(f"BOM {bom_id} 不存在或已删除")

    if bom["assembly_type"] != "disassembly":
        raise ValueError(
            f"BOM {bom_id} 的类型为 '{bom['assembly_type']}'，不是分解型 BOM"
        )

    yield_qty = float(bom["yield_qty"])
    if yield_qty <= 0:
        raise ValueError(f"BOM {bom_id} 的产出量 yield_qty={yield_qty} 无效（必须 > 0）")

    # 查 dish_bom_items（产出明细行）
    items_row = await db.execute(
        text(
            """
            SELECT ingredient_name, ingredient_code, quantity, unit
            FROM dish_bom_items
            WHERE bom_id = :bom_id
              AND tenant_id = :tid
            ORDER BY sort_order, created_at
        """
        ),
        {"bom_id": bom_id, "tid": tenant_id},
    )
    items = items_row.mappings().all()

    if not items:
        raise ValueError(f"BOM {bom_id} 没有明细行，无法计算分解产出")

    # 校验：sum(quantity) <= yield_qty（产出组件总量不超过整件投入量）
    total_component_qty = sum(float(it["quantity"]) for it in items)
    if total_component_qty > yield_qty + 1e-9:  # 浮点容差
        raise ValueError(
            f"分解型 BOM {bom_id} 产出组件总量 {total_component_qty} "
            f"超过整件产出量 {yield_qty}，校验失败"
        )

    # 按比例计算各组件产出量：output_qty = (item.quantity / yield_qty) * input_qty
    outputs: List[DisassemblyOutputItem] = []
    for it in items:
        ratio = float(it["quantity"]) / yield_qty
        output_qty = round(ratio * input_qty, 4)
        outputs.append(
            DisassemblyOutputItem(
                ingredient_name=it["ingredient_name"],
                ingredient_code=it["ingredient_code"],
                output_qty=output_qty,
                unit=it["unit"],
            )
        )

    result = DisassemblyResult(
        bom_id=bom_id,
        input_qty=input_qty,
        yield_qty=yield_qty,
        outputs=outputs,
    )

    log.info(
        "bom_disassembly_calculated",
        bom_id=bom_id,
        input_qty=input_qty,
        yield_qty=yield_qty,
        output_count=len(outputs),
        tenant_id=tenant_id,
    )

    return result
