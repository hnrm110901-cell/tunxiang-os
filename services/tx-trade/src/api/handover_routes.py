"""交班对账 API — 交班/现金清点/对账/渠道核对

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services.channel_verify import ChannelVerifyService
from ..services.shift_handover_service import ShiftHandoverService
from ..services.shift_reconciliation import ShiftReconciliationService

router = APIRouter(prefix="/api/v1", tags=["handover"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> dict:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


# ─── 请求模型 ───


class StartHandoverReq(BaseModel):
    cashier_id: str
    store_id: str


class CashCountReq(BaseModel):
    denominations: dict = Field(
        ...,
        description="按面额录入: {\"100\": 5, \"50\": 3, \"20\": 2}",
        examples=[{"100": 5, "50": 3, "20": 2, "10": 5, "1": 8}],
    )


# ─── 交班管理 ───


@router.post("/handover/start")
async def start_handover(
    req: StartHandoverReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """开始交班 — 创建交班记录，快照当前班次数据"""
    tenant_id = _get_tenant_id(request)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.start_handover(req.cashier_id, req.store_id)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/handover/{handover_id}/cash-count")
async def record_cash_count(
    handover_id: str,
    req: CashCountReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """录入实际现金清点"""
    tenant_id = _get_tenant_id(request)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.record_cash_count(handover_id, req.denominations)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.post("/handover/{handover_id}/finalize")
async def finalize_handover(
    handover_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """完成交班 — 计算差异，生成交班报告"""
    tenant_id = _get_tenant_id(request)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.finalize_handover(handover_id)
        await db.commit()
        return _ok(result)
    except ValueError as e:
        _err(str(e))


@router.get("/handover/{handover_id}/summary")
async def get_shift_summary(
    handover_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查看交班报告"""
    tenant_id = _get_tenant_id(request)
    try:
        svc = ShiftHandoverService(db, tenant_id)
        result = await svc.get_shift_summary(handover_id)
        return _ok(result)
    except ValueError as e:
        _err(str(e))


# ─── 对账 ───


@router.get("/handover/reconciliation/{handover_id}")
async def get_reconciliation(
    handover_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """班次对账详情 — 逐笔核对 + 可疑交易 + 现金长短款"""
    tenant_id = _get_tenant_id(request)
    try:
        recon_svc = ShiftReconciliationService(db, tenant_id)
        reconciliation = await recon_svc.reconcile_shift(handover_id)
        cash_detail = await recon_svc.get_cash_variance_detail(handover_id)
        suspicious = await recon_svc.flag_suspicious_transactions(handover_id)

        return _ok({
            "reconciliation": reconciliation,
            "cash_variance": cash_detail,
            "suspicious_transactions": suspicious,
        })
    except ValueError as e:
        _err(str(e))


# ─── 渠道核对 ───


@router.get("/handover/channels/{store_id}/{target_date}")
async def get_channel_report(
    store_id: str,
    target_date: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """渠道核对报告 — 微信/支付宝/现金/银联 逐渠道对比"""
    tenant_id = _get_tenant_id(request)
    try:
        svc = ChannelVerifyService(db, tenant_id)
        result = await svc.generate_channel_report(store_id, target_date)
        return _ok(result)
    except ValueError as e:
        _err(str(e))
