"""宴会原料 API"""

from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.banquet_material_service import BanquetMaterialService


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid

async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_with_tenant(_get_tenant_id(request)):
        yield session

def _ok(data: object) -> dict:
    return {"ok": True, "data": data, "error": None}

def _err(msg: str, code: int = 400) -> None:
    raise HTTPException(status_code=code, detail={"ok": False, "data": None, "error": {"message": msg}})


router = APIRouter(prefix="/api/v1/banquet/materials", tags=["banquet-material"])


class BOMReq(BaseModel):
    banquet_id: str

class PurchaseOrderReq(BaseModel):
    banquet_id: str
    supplier_id: Optional[str] = None
    required_by: Optional[str] = None

class UpdatePOStatusReq(BaseModel):
    status: str

class ReceiveReq(BaseModel):
    received_items: list[dict] = []


@router.post("/decompose")
async def decompose_bom(req: BOMReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.decompose_bom(req.banquet_id))
    except ValueError as e:
        _err(str(e))

@router.post("/check-inventory")
async def check_inventory(req: BOMReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.check_inventory(req.banquet_id))
    except ValueError as e:
        _err(str(e))

@router.post("/reserve")
async def reserve_inventory(req: BOMReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.reserve_inventory(req.banquet_id))

@router.post("/purchase-order")
async def generate_purchase_order(req: PurchaseOrderReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    from datetime import date as date_cls
    rby = date_cls.fromisoformat(req.required_by) if req.required_by else None
    try:
        return _ok(await svc.generate_purchase_order(req.banquet_id, req.supplier_id, rby))
    except ValueError as e:
        _err(str(e))

@router.get("/summary/{banquet_id}")
async def get_material_summary(banquet_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_material_summary(banquet_id))

@router.get("/purchase-orders/{banquet_id}")
async def list_purchase_orders(banquet_id: str, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.get_purchase_orders(banquet_id))

@router.patch("/purchase-orders/{po_id}/status")
async def update_po_status(po_id: str, req: UpdatePOStatusReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    try:
        return _ok(await svc.update_purchase_status(po_id, req.status))
    except ValueError as e:
        _err(str(e))

@router.post("/purchase-orders/{po_id}/receive")
async def mark_received(po_id: str, req: ReceiveReq, request: Request, db: AsyncSession = Depends(_get_db_session)):
    svc = BanquetMaterialService(db=db, tenant_id=_get_tenant_id(request))
    return _ok(await svc.mark_received(po_id, req.received_items))
