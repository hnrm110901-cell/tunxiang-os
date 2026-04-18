"""
法人主体 API
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..services.legal_entity_service import LegalEntityService

router = APIRouter(prefix="/api/v1/hr/legal-entities", tags=["hr-legal-entity"])


class CreateEntityRequest(BaseModel):
    code: str
    name: str
    entity_type: str = "direct_operated"
    brand_id: Optional[str] = None
    unified_social_credit: Optional[str] = None
    legal_representative: Optional[str] = None
    registered_address: Optional[str] = None
    registered_capital_fen: Optional[int] = None
    establish_date: Optional[date] = None
    tax_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    contact_phone: Optional[str] = None
    remark: Optional[str] = None


class BindStoreRequest(BaseModel):
    store_id: str
    start_date: date
    end_date: Optional[date] = None
    is_primary: bool = True
    remark: Optional[str] = None


@router.get("", summary="列举法人主体")
async def list_entities(
    brand_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    rows = await LegalEntityService.list_by_brand(db, brand_id=brand_id, status=status)
    return {"items": rows, "total": len(rows)}


@router.post("", summary="新建法人主体")
async def create_entity(req: CreateEntityRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        entity = await LegalEntityService.create_entity(db, **req.dict())
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(entity.id), "code": entity.code}


@router.post("/{entity_id}/stores", summary="绑定门店")
async def bind_store(
    entity_id: uuid.UUID,
    req: BindStoreRequest,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    try:
        link = await LegalEntityService.bind_to_store(
            db,
            entity_id=entity_id,
            store_id=req.store_id,
            start_date=req.start_date,
            end_date=req.end_date,
            is_primary=req.is_primary,
            remark=req.remark,
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(link.id), "store_id": link.store_id}


@router.get("/by-store/{store_id}", summary="查门店生效主体")
async def get_active_for_store(
    store_id: str,
    as_of: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    data = await LegalEntityService.get_active_entity_for_store(db, store_id=store_id, as_of_date=as_of)
    if not data:
        raise HTTPException(status_code=404, detail="该门店未绑定生效法人")
    return data
