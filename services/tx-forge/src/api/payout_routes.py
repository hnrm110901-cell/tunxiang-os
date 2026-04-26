from __future__ import annotations
from typing import Any, Dict, Optional
from uuid import UUID
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/forge/payouts", tags=["payouts"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


@router.post("")
async def request_payout(
    body: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.payouts (tenant_id, developer_id, amount, currency, status)
                VALUES (:tid, :developer_id, :amount, :currency, 'pending') RETURNING *"""),
        {"tid": x_tenant_id, "developer_id": body["developer_id"],
         "amount": body["amount"], "currency": body.get("currency", "CNY")},
    )
    await db.commit()
    return dict(result.mappings().one())


@router.get("")
async def payout_history(
    developer_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    await _set_tenant(db, x_tenant_id)
    where = "tenant_id = :tid"
    params: Dict[str, Any] = {"tid": x_tenant_id}
    if developer_id:
        where += " AND developer_id = :did"; params["did"] = developer_id
    rows = await db.execute(text(f"SELECT * FROM forge.payouts WHERE {where} ORDER BY created_at DESC"), params)
    return {"items": [dict(r) for r in rows.mappings().all()]}
