"""
D8 收货质检服务 — Should-Fix P1

关键流程：
  1. create_receipt: 创建收货单 + 明细
  2. quality_check: 逐项标记 pass/reject/partial，拒收部分生成 WasteEvent
  3. post_receipt: 过账，写 InventoryTransaction（按实收数量入库）

金额统一分存储。
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.goods_receipt import (
    GoodsReceipt,
    GoodsReceiptItem,
    QCStatus,
    ReceiptStatus,
)
from ..models.inventory import InventoryItem, InventoryTransaction, TransactionType
from ..models.supply_chain import PurchaseOrder
from ..models.waste_event import WasteEvent, WasteEventStatus, WasteEventType

logger = structlog.get_logger()


def _to_decimal(v) -> Decimal:
    return Decimal(str(v or 0))


class GoodsReceiptService:
    """收货质检服务"""

    async def create_receipt(
        self,
        po_id: str,
        items: List[Dict[str, Any]],
        received_by: str,
        db: AsyncSession,
        receipt_no: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> GoodsReceipt:
        """创建收货单

        items: [{"ingredient_id","ordered_qty","received_qty","unit","unit_cost_fen",
                 "temperature","prod_date"(YYYY-MM-DD),"expiry_date"(YYYY-MM-DD)}]
        """
        po = await db.get(PurchaseOrder, po_id)
        if not po:
            raise ValueError(f"采购单不存在: {po_id}")
        if po.status not in ("approved", "ordered", "shipped", "delivered"):
            raise ValueError(f"采购单状态不允许收货: {po.status}")

        if not receipt_no:
            receipt_no = f"GR-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        receipt = GoodsReceipt(
            id=uuid.uuid4(),
            po_id=po_id,
            receipt_no=receipt_no,
            received_by=received_by,
            total_amount_fen=0,
            qc_status=QCStatus.PENDING.value,
            status=ReceiptStatus.DRAFT.value,
            notes=notes,
        )
        db.add(receipt)
        await db.flush()

        total_fen = 0
        for it in items:
            received = _to_decimal(it.get("received_qty") or 0)
            unit_cost_fen = int(it.get("unit_cost_fen") or 0)
            total_fen += int(received * unit_cost_fen)

            def _parse_date(v):
                if not v:
                    return None
                if isinstance(v, date_type):
                    return v
                return datetime.strptime(v, "%Y-%m-%d").date()

            row = GoodsReceiptItem(
                id=uuid.uuid4(),
                receipt_id=receipt.id,
                ingredient_id=it["ingredient_id"],
                ordered_qty=_to_decimal(it.get("ordered_qty") or 0),
                received_qty=received,
                rejected_qty=Decimal("0"),
                unit=it.get("unit"),
                unit_cost_fen=unit_cost_fen,
                qc_status=QCStatus.PENDING.value,
                temperature=it.get("temperature"),
                prod_date=_parse_date(it.get("prod_date")),
                expiry_date=_parse_date(it.get("expiry_date")),
            )
            db.add(row)

        receipt.total_amount_fen = total_fen
        await db.commit()
        await db.refresh(receipt)
        logger.info("goods_receipt.created", receipt_id=str(receipt.id), po_id=po_id)
        return receipt

    async def quality_check(
        self,
        receipt_id: str,
        items_qc: List[Dict[str, Any]],
        db: AsyncSession,
    ) -> GoodsReceipt:
        """逐项质检 — items_qc: [{"item_id","qc_status","rejected_qty","qc_remark"}]

        rejected_qty>0 且存在门店信息时自动生成 WasteEvent（QUALITY_REJECT）。
        """
        receipt = await db.get(GoodsReceipt, receipt_id)
        if not receipt:
            raise ValueError(f"收货单不存在: {receipt_id}")
        if receipt.status == ReceiptStatus.POSTED.value:
            raise ValueError("已过账收货单不可再质检")

        po = await db.get(PurchaseOrder, receipt.po_id)
        store_id = po.store_id if po else None

        # 加载明细
        stmt = select(GoodsReceiptItem).where(GoodsReceiptItem.receipt_id == receipt.id)
        rows = {str(r.id): r for r in (await db.execute(stmt)).scalars().all()}

        pass_cnt = 0
        reject_cnt = 0
        partial_cnt = 0

        for qc in items_qc:
            row = rows.get(str(qc["item_id"]))
            if not row:
                continue
            status = qc.get("qc_status", QCStatus.PASS.value)
            rejected_qty = _to_decimal(qc.get("rejected_qty") or 0)
            row.qc_status = status
            row.rejected_qty = rejected_qty
            row.qc_remark = qc.get("qc_remark")

            if status == QCStatus.PASS.value:
                row.rejected_qty = Decimal("0")
                pass_cnt += 1
            elif status == QCStatus.REJECT.value:
                row.rejected_qty = row.received_qty
                reject_cnt += 1
            elif status == QCStatus.PARTIAL.value:
                partial_cnt += 1

            # 生成 WasteEvent（拒收部分）
            if rejected_qty > 0 or status == QCStatus.REJECT.value:
                reject_amount = row.rejected_qty if status == QCStatus.REJECT.value else rejected_qty
                if reject_amount and reject_amount > 0 and store_id:
                    wid = uuid.uuid4()
                    waste = WasteEvent(
                        id=wid,
                        event_id=f"WE-{uuid.uuid4().hex[:10].upper()}",
                        store_id=store_id,
                        event_type=WasteEventType.QUALITY_REJECT,
                        status=WasteEventStatus.PENDING,
                        ingredient_id=row.ingredient_id,
                        quantity=reject_amount,
                        unit=row.unit or "kg",
                        occurred_at=datetime.utcnow(),
                        reported_by=receipt.received_by,
                        notes="收货质检拒收",
                        evidence={
                            "source": "goods_receipt",
                            "receipt_id": str(receipt.id),
                            "receipt_item_id": str(row.id),
                            "loss_amount_fen": int(reject_amount * (row.unit_cost_fen or 0)),
                        },
                    )
                    db.add(waste)
                    row.waste_event_id = wid

        # 聚合质检状态
        if reject_cnt and not (pass_cnt or partial_cnt):
            receipt.qc_status = QCStatus.REJECT.value
        elif partial_cnt or (reject_cnt and pass_cnt):
            receipt.qc_status = QCStatus.PARTIAL.value
        else:
            receipt.qc_status = QCStatus.PASS.value
        receipt.status = ReceiptStatus.QC_IN_PROGRESS.value

        await db.commit()
        await db.refresh(receipt)
        logger.info(
            "goods_receipt.qc_done",
            receipt_id=str(receipt.id),
            qc_status=receipt.qc_status,
        )
        return receipt

    async def post_receipt(
        self,
        receipt_id: str,
        db: AsyncSession,
    ) -> GoodsReceipt:
        """过账入库：按实收-拒收 写入 InventoryTransaction"""
        receipt = await db.get(GoodsReceipt, receipt_id)
        if not receipt:
            raise ValueError(f"收货单不存在: {receipt_id}")
        if receipt.status == ReceiptStatus.POSTED.value:
            raise ValueError("收货单已过账")
        if receipt.qc_status == QCStatus.PENDING.value:
            raise ValueError("未完成质检不允许过账")

        po = await db.get(PurchaseOrder, receipt.po_id)
        store_id = po.store_id if po else None
        if not store_id:
            raise ValueError("采购单缺少门店 ID")

        stmt = select(GoodsReceiptItem).where(GoodsReceiptItem.receipt_id == receipt.id)
        for row in (await db.execute(stmt)).scalars().all():
            net_qty = float((row.received_qty or Decimal("0")) - (row.rejected_qty or Decimal("0")))
            if net_qty <= 0:
                continue

            # 尝试获取库存项用于 quantity_before
            inv = await db.get(InventoryItem, row.ingredient_id)
            quantity_before = float(inv.current_quantity) if inv else 0.0
            quantity_after = quantity_before + net_qty

            tx = InventoryTransaction(
                id=uuid.uuid4(),
                item_id=row.ingredient_id,
                store_id=store_id,
                transaction_type=TransactionType.PURCHASE.value,
                quantity=net_qty,
                unit_cost=row.unit_cost_fen or 0,
                total_cost=int(Decimal(str(net_qty)) * (row.unit_cost_fen or 0)),
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                reference_id=receipt.receipt_no,
                notes=f"收货过账 {receipt.receipt_no}",
                performed_by=receipt.received_by,
                transaction_time=datetime.utcnow(),
            )
            db.add(tx)
            if inv is not None:
                inv.current_quantity = quantity_after

        receipt.status = ReceiptStatus.POSTED.value
        receipt.posted_at = datetime.utcnow()
        if po is not None:
            po.status = "completed"
            po.actual_delivery = datetime.utcnow()

        await db.commit()
        await db.refresh(receipt)
        logger.info("goods_receipt.posted", receipt_id=str(receipt.id))
        return receipt

    async def get_receipt(self, receipt_id: str, db: AsyncSession) -> Optional[GoodsReceipt]:
        return await db.get(GoodsReceipt, receipt_id)

    async def list_receipts(
        self,
        po_id: Optional[str],
        db: AsyncSession,
        limit: int = 50,
    ) -> List[GoodsReceipt]:
        stmt = select(GoodsReceipt).order_by(GoodsReceipt.created_at.desc()).limit(limit)
        if po_id:
            stmt = stmt.where(GoodsReceipt.po_id == po_id)
        return list((await db.execute(stmt)).scalars().all())


goods_receipt_service = GoodsReceiptService()
