"""资金分账 API 路由

端点：
  POST  /api/v1/finance/split-rules                    — 创建分账规则
  GET   /api/v1/finance/split-rules                    — 查询规则列表
  POST  /api/v1/finance/split/order/{order_id}         — 单笔订单分账
  POST  /api/v1/finance/split/batch                    — 批量分账
  POST  /api/v1/finance/settlements                    — 生成结算批次
  GET   /api/v1/finance/settlements                    — 结算批次列表
  GET   /api/v1/finance/settlements/{batch_id}/summary — 结算汇总
  POST  /api/v1/finance/settlements/{batch_id}/confirm — 确认结算
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from ..services.fund_settlement_service import FundSettlementService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/finance", tags=["fund-settlement"])

_service = FundSettlementService()


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class CreateSplitRuleRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    rule_type: str = Field(..., description="规则类型: platform_fee/brand_royalty/franchise_share")
    rate_permil: int = Field(..., ge=0, le=1000, description="费率千分比，50=5.0%")
    fixed_fee_fen: int = Field(0, ge=0, description="每笔固定费用（分）")
    effective_from: str = Field(..., description="生效起始日期 YYYY-MM-DD")
    effective_to: Optional[str] = Field(None, description="生效截止日期 YYYY-MM-DD，不传表示长期有效")


class BatchSplitRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    start_date: str = Field(..., description="起始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="截止日期 YYYY-MM-DD")


class CreateSettlementRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    period_start: str = Field(..., description="结算周期起始日期 YYYY-MM-DD")
    period_end: str = Field(..., description="结算周期截止日期 YYYY-MM-DD")


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


def _parse_date(val: str, field_name: str) -> date:
    try:
        return date.fromisoformat(val)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"日期格式错误 {field_name}: {val}，请使用 YYYY-MM-DD",
        ) from exc


# ─── POST /split-rules ───────────────────────────────────────────────────────

@router.post("/split-rules", summary="创建分账规则")
async def create_split_rule(
    body: CreateSplitRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """创建门店分账规则。

    - rule_type: platform_fee（平台费）/ brand_royalty（品牌费）/ franchise_share（加盟商分成）
    - rate_permil: 费率千分比，如 50 表示 5.0%
    - fixed_fee_fen: 每笔订单固定扣除金额（分）
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")
    eff_from = _parse_date(body.effective_from, "effective_from")
    eff_to = _parse_date(body.effective_to, "effective_to") if body.effective_to else None

    try:
        result = await _service.create_split_rule(
            db=db,
            tenant_id=tid,
            store_id=sid,
            rule_type=body.rule_type,
            rate_permil=body.rate_permil,
            fixed_fee_fen=body.fixed_fee_fen,
            effective_from=eff_from,
            effective_to=eff_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── GET /split-rules ────────────────────────────────────────────────────────

@router.get("/split-rules", summary="查询分账规则")
async def list_split_rules(
    store_id: Optional[str] = Query(None, description="门店ID"),
    rule_type: Optional[str] = Query(None, description="规则类型"),
    active_only: bool = Query(True, description="是否只返回启用的规则"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """查询分账规则列表，支持按门店、规则类型筛选。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id") if store_id else None

    try:
        rules = await _service.list_split_rules(
            db=db,
            tenant_id=tid,
            store_id=sid,
            rule_type=rule_type,
            active_only=active_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": {"items": rules, "total": len(rules)}, "error": None}


# ─── POST /split/order/{order_id} ────────────────────────────────────────────

@router.post("/split/order/{order_id}", summary="单笔订单分账")
async def split_order(
    order_id: str = Path(..., description="订单ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """对单笔订单执行分账计算，根据门店分账规则拆分金额到平台/品牌/加盟商。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    oid = _parse_uuid(order_id, "order_id")

    try:
        result = await _service.split_order(db=db, tenant_id=tid, order_id=oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── POST /split/batch ───────────────────────────────────────────────────────

@router.post("/split/batch", summary="批量分账")
async def batch_split(
    body: BatchSplitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """批量分账：对指定门店、日期范围内未分账的订单执行分账。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")
    s_date = _parse_date(body.start_date, "start_date")
    e_date = _parse_date(body.end_date, "end_date")

    try:
        result = await _service.batch_split(
            db=db,
            tenant_id=tid,
            store_id=sid,
            start_date=s_date,
            end_date=e_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── POST /settlements ───────────────────────────────────────────────────────

@router.post("/settlements", summary="生成结算批次")
async def create_settlement(
    body: CreateSettlementRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """生成结算批次：汇总指定门店、周期内的分账流水，生成结算单。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")
    p_start = _parse_date(body.period_start, "period_start")
    p_end = _parse_date(body.period_end, "period_end")

    try:
        result = await _service.create_settlement_batch(
            db=db,
            tenant_id=tid,
            store_id=sid,
            period_start=p_start,
            period_end=p_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── GET /settlements ────────────────────────────────────────────────────────

@router.get("/settlements", summary="结算批次列表")
async def list_settlements(
    store_id: Optional[str] = Query(None, description="门店ID"),
    status: Optional[str] = Query(None, description="状态: draft/confirmed/paid"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """结算批次列表，支持按门店、状态筛选，分页返回。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(store_id, "store_id") if store_id else None

    try:
        result = await _service.list_settlement_batches(
            db=db,
            tenant_id=tid,
            store_id=sid,
            status=status,
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── GET /settlements/{batch_id}/summary ─────────────────────────────────────

@router.get("/settlements/{batch_id}/summary", summary="结算汇总")
async def get_settlement_summary(
    batch_id: str = Path(..., description="结算批次ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """获取结算批次的汇总详情，含各方分账金额统计。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    bid = _parse_uuid(batch_id, "batch_id")

    try:
        result = await _service.get_settlement_summary(
            db=db, tenant_id=tid, batch_id=bid
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}


# ─── POST /settlements/{batch_id}/confirm ────────────────────────────────────

@router.post("/settlements/{batch_id}/confirm", summary="确认结算")
async def confirm_settlement(
    batch_id: str = Path(..., description="结算批次ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """确认结算批次，将状态从 draft 更新为 confirmed，关联流水标记为 settled。"""
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    bid = _parse_uuid(batch_id, "batch_id")

    try:
        result = await _service.confirm_settlement(
            db=db, tenant_id=tid, batch_id=bid
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "data": result, "error": None}
