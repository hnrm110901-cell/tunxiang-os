"""
D8 收货质检 API — Should-Fix P1

端点：
  POST /api/v1/goods-receipt/create
  POST /api/v1/goods-receipt/qc
  POST /api/v1/goods-receipt/post
  GET  /api/v1/goods-receipt/get/{receipt_id}
  GET  /api/v1/goods-receipt/list
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.goods_receipt_service import goods_receipt_service

router = APIRouter(prefix="/goods-receipt", tags=["goods-receipt"])


class CreateReceiptRequest(BaseModel):
    po_id: str
    received_by: str
    items: List[Dict[str, Any]] = Field(..., description="明细：ingredient_id/ordered_qty/received_qty/unit/unit_cost_fen/temperature/prod_date/expiry_date")
    receipt_no: Optional[str] = None
    notes: Optional[str] = None


class QCRequest(BaseModel):
    receipt_id: str
    items_qc: List[Dict[str, Any]] = Field(..., description="{item_id,qc_status,rejected_qty,qc_remark}")


class PostRequest(BaseModel):
    receipt_id: str


def _serialize(receipt) -> Dict[str, Any]:
    return {
        "id": str(receipt.id),
        "po_id": receipt.po_id,
        "receipt_no": receipt.receipt_no,
        "total_amount_fen": receipt.total_amount_fen,
        "total_amount_yuan": receipt.total_amount_yuan,
        "received_by": receipt.received_by,
        "qc_status": receipt.qc_status,
        "status": receipt.status,
        "posted_at": receipt.posted_at.isoformat() if receipt.posted_at else None,
        "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
    }


@router.post("/create")
async def create_receipt(req: CreateReceiptRequest, db: AsyncSession = Depends(get_db)):
    try:
        r = await goods_receipt_service.create_receipt(
            po_id=req.po_id,
            items=req.items,
            received_by=req.received_by,
            db=db,
            receipt_no=req.receipt_no,
            notes=req.notes,
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/qc")
async def qc(req: QCRequest, db: AsyncSession = Depends(get_db)):
    try:
        r = await goods_receipt_service.quality_check(
            receipt_id=req.receipt_id, items_qc=req.items_qc, db=db
        )
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/post")
async def post_receipt(req: PostRequest, db: AsyncSession = Depends(get_db)):
    try:
        r = await goods_receipt_service.post_receipt(receipt_id=req.receipt_id, db=db)
        return _serialize(r)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/get/{receipt_id}")
async def get_receipt(receipt_id: str, db: AsyncSession = Depends(get_db)):
    r = await goods_receipt_service.get_receipt(receipt_id, db)
    if not r:
        raise HTTPException(status_code=404, detail="收货单不存在")
    return _serialize(r)


@router.get("/list")
async def list_receipts(
    po_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    rows = await goods_receipt_service.list_receipts(po_id=po_id, db=db, limit=limit)
    return {"items": [_serialize(r) for r in rows], "total": len(rows)}
