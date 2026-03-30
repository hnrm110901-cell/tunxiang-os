"""班次交班 API — 开始交班/现金清点/完成交班/班次报告

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header，通过 get_db_with_tenant 实现 RLS 租户隔离。
"""
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from ..services.shift_handover_service import ShiftHandoverService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/shifts", tags=["shifts"])


# ─── 通用辅助 ───


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """获取带租户隔离的 DB session"""
    tenant_id = _get_tenant_id(request)
    async for session in get_db_with_tenant(tenant_id):
        yield session


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


# ─── 请求模型 ───


class StartHandoverReq(BaseModel):
    cashier_id: str = Field(..., min_length=1, description="当前收银员ID")
    store_id: str = Field(..., min_length=1, description="门店ID")


class CashCountReq(BaseModel):
    denominations: dict = Field(
        ...,
        description='按面额录入张数: {"100": 5, "50": 3, "20": 2, "10": 5, "1": 8}',
        examples=[{"100": 5, "50": 3, "20": 2, "10": 5, "1": 8}],
    )


# ─── 1. 开始交班 ───


@router.post("/handover")
async def start_handover(
    body: StartHandoverReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """开始交班 -- 创建交班记录，快照当前班次数据"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(cashier_id=body.cashier_id, store_id=body.store_id, tenant_id=tenant_id)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.start_handover(
            cashier_id=body.cashier_id,
            store_id=body.store_id,
        )
        await db.commit()
        log.info("start_handover_api_ok", handover_id=result.get("handover_id"))
        return _ok(result)
    except ValueError as e:
        log.warning("start_handover_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 2. 现金清点 ───


@router.post("/handover/{handover_id}/cash-count")
async def record_cash_count(
    handover_id: str,
    body: CashCountReq,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """录入实际现金清点 -- 按面额逐项录入"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(handover_id=handover_id, tenant_id=tenant_id)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.record_cash_count(
            handover_id=handover_id,
            denominations=body.denominations,
        )
        await db.commit()
        log.info("record_cash_count_api_ok", actual_fen=result.get("cash_actual_fen"))
        return _ok(result)
    except ValueError as e:
        log.warning("record_cash_count_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 3. 完成交班 ───


@router.post("/handover/{handover_id}/finalize")
async def finalize_handover(
    handover_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_db_session),
):
    """完成交班 -- 计算现金差异，生成交班报告"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(handover_id=handover_id, tenant_id=tenant_id)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.finalize_handover(handover_id=handover_id)
        await db.commit()
        log.info(
            "finalize_handover_api_ok",
            variance_fen=result.get("variance_fen"),
            variance_alert=result.get("variance_alert"),
        )
        return _ok(result)
    except ValueError as e:
        log.warning("finalize_handover_api_fail", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ─── 4. 班次报告 ───


@router.get("/summary")
async def get_shift_summary(
    handover_id: str = Query(..., description="交班记录ID"),
    request: Request = None,
    db: AsyncSession = Depends(_get_db_session),
):
    """查看班次交班报告摘要"""
    tenant_id = _get_tenant_id(request)
    log = logger.bind(handover_id=handover_id, tenant_id=tenant_id)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.get_shift_summary(handover_id=handover_id)
        log.info("get_shift_summary_api_ok", handover_id=handover_id)
        return _ok(result)
    except ValueError as e:
        log.warning("get_shift_summary_api_fail", error=str(e))
        raise HTTPException(status_code=404, detail=str(e))
