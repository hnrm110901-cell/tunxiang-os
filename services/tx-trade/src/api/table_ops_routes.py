"""桌台操作 API — 转台等高级桌台功能

POST /api/v1/orders/{order_id}/transfer-table  转台
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.cashier_engine import CashierEngine

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["table-ops"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class TransferTableReq(BaseModel):
    target_table_no: str
    operator_id: Optional[str] = None


# ─── 端点 ───


@router.post("/orders/{order_id}/transfer-table")
async def transfer_table(
    order_id: str,
    req: TransferTableReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """转台 — 将订单从当前桌转移到目标空闲桌

    校验目标桌空闲 → 更新Order桌号 → 释放原桌 → 锁定新桌。
    原桌号记录到 order.table_transfer_from 字段以供审计追溯。
    """
    tenant_id = _get_tenant_id(request)
    engine = CashierEngine(db, tenant_id)

    try:
        result = await engine.transfer_table(
            order_id=order_id,
            target_table_no=req.target_table_no,
            operator_id=req.operator_id,
        )
        await db.commit()
        return _ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
