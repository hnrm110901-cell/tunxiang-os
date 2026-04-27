"""储值分账结算 API 路由

端点：
  POST   /api/v1/finance/sv-settlement/rules              创建分账规则
  GET    /api/v1/finance/sv-settlement/rules              查询分账规则列表
  PUT    /api/v1/finance/sv-settlement/rules/{rule_id}    更新分账规则
  GET    /api/v1/finance/sv-settlement/ledger             分账流水列表
  GET    /api/v1/finance/sv-settlement/batches            结算批次列表
  GET    /api/v1/finance/sv-settlement/batches/{batch_id} 结算批次详情
  POST   /api/v1/finance/sv-settlement/batches/run-daily  触发每日结算
  POST   /api/v1/finance/sv-settlement/batches/{batch_id}/confirm  确认结算
  POST   /api/v1/finance/sv-settlement/batches/{batch_id}/settle   标记已打款
  GET    /api/v1/finance/sv-settlement/dashboard          分账看板
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.settlement_notify_service import SettlementNotifyService
from ..services.stored_value_split_service import (
    StoredValueSplitService,
)
from ..tasks.settlement_scheduler import SettlementScheduler

router = APIRouter(
    prefix="/api/v1/finance/sv-settlement",
    tags=["stored-value-settlement"],
)


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────


async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _split_svc(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> StoredValueSplitService:
    return StoredValueSplitService(db, x_tenant_id)


def _scheduler(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> SettlementScheduler:
    return SettlementScheduler(db, x_tenant_id)


def _notify_svc(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> SettlementNotifyService:
    return SettlementNotifyService(db, x_tenant_id)


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class CreateSplitRuleReq(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    recharge_store_ratio: float = Field(default=0.1500, ge=0, le=1, description="充值店比例（小数，如 0.15 = 15%）")
    consume_store_ratio: float = Field(default=0.7000, ge=0, le=1, description="消费店比例")
    hq_ratio: float = Field(default=0.1500, ge=0, le=1, description="总部比例")
    scope_type: str = Field(
        default="brand",
        description="适用范围: brand | region | custom",
    )
    applicable_store_ids: Optional[List[str]] = Field(None, description="适用门店 ID 列表（scope_type=custom 时必填）")
    is_default: bool = Field(False, description="是否为默认兜底规则")
    effective_from: Optional[str] = Field(None, description="生效日期 YYYY-MM-DD")
    effective_to: Optional[str] = Field(None, description="失效日期 YYYY-MM-DD")


class UpdateSplitRuleReq(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=100)
    recharge_store_ratio: float = Field(default=0.1500, ge=0, le=1)
    consume_store_ratio: float = Field(default=0.7000, ge=0, le=1)
    hq_ratio: float = Field(default=0.1500, ge=0, le=1)
    scope_type: str = Field(default="brand")
    applicable_store_ids: Optional[List[str]] = None
    is_default: bool = False
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


class RunDailySettlementReq(BaseModel):
    settlement_date: Optional[str] = Field(
        None,
        description="结算日期 YYYY-MM-DD，默认为昨天",
    )


# ─── 分账规则 ─────────────────────────────────────────────────────────────────


@router.post("/rules", summary="创建分账规则", status_code=201)
async def create_split_rule(
    body: CreateSplitRuleReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """创建储值跨店分账规则。

    三方比例（recharge_store_ratio + consume_store_ratio + hq_ratio）之和必须为 1.0000。
    """
    svc = StoredValueSplitService(db, x_tenant_id)
    try:
        rule = await svc.create_rule(body.model_dump())
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": rule}


@router.get("/rules", summary="查询分账规则列表")
async def list_split_rules(
    scope_type: Optional[str] = Query(None, description="按 scope_type 过滤"),
    is_default: Optional[bool] = Query(None, description="是否默认规则"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询当前租户的分账规则列表。"""
    svc = StoredValueSplitService(db, x_tenant_id)
    rules = await svc.list_rules(scope_type=scope_type, is_default=is_default)
    return {"ok": True, "data": {"items": rules, "total": len(rules)}}


@router.put("/rules/{rule_id}", summary="更新分账规则")
async def update_split_rule(
    body: UpdateSplitRuleReq,
    rule_id: str = Path(..., description="规则 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """更新分账规则。三方比例之和必须为 1.0000。"""
    svc = StoredValueSplitService(db, x_tenant_id)
    try:
        rule = await svc.update_rule(rule_id, body.model_dump())
        if not rule:
            raise HTTPException(status_code=404, detail=f"规则不存在: {rule_id}")
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": rule}


# ─── 分账流水 ─────────────────────────────────────────────────────────────────


@router.get("/ledger", summary="分账流水列表")
async def list_split_ledger(
    store_id: Optional[str] = Query(None, description="门店 ID（充值店或消费店）"),
    settlement_status: Optional[str] = Query(None, description="状态: pending/settled/disputed"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询储值分账流水，支持按门店/状态/日期筛选。"""
    svc = StoredValueSplitService(db, x_tenant_id)
    result = await svc.list_ledger(
        store_id=store_id,
        settlement_status=settlement_status,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


# ─── 结算批次 ─────────────────────────────────────────────────────────────────


@router.get("/batches", summary="结算批次列表")
async def list_settlement_batches(
    status: Optional[str] = Query(None, description="状态: draft/confirmed/settled/disputed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询储值分账结算批次列表。"""
    scheduler = SettlementScheduler(db, x_tenant_id)
    result = await scheduler.list_batches(status=status, page=page, size=size)
    return {"ok": True, "data": result}


@router.get("/batches/{batch_id}", summary="结算批次详情")
async def get_settlement_batch(
    batch_id: str = Path(..., description="批次 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """查询单个结算批次详情。"""
    scheduler = SettlementScheduler(db, x_tenant_id)
    batch = await scheduler.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"结算批次不存在: {batch_id}")
    return {"ok": True, "data": batch}


@router.post("/batches/run-daily", summary="触发每日结算")
async def run_daily_settlement(
    body: RunDailySettlementReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """手动触发每日结算（也可由 cron 调用）。

    默认结算昨天的分账流水。可通过 settlement_date 指定日期。
    """
    scheduler = SettlementScheduler(db, x_tenant_id)
    notify = SettlementNotifyService(db, x_tenant_id)

    settlement_date = None
    if body.settlement_date:
        settlement_date = date.fromisoformat(body.settlement_date)

    try:
        result = await scheduler.run_daily_settlement(settlement_date=settlement_date)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 如果生成了批次，发送通知
    if result.get("batch_id"):
        await notify.notify_batch_created(
            batch_id=result["batch_id"],
            batch_no=result["batch_no"],
            total_records=result["total_records"],
            total_amount_fen=result["total_amount_fen"],
            period_start=result["period_start"],
            period_end=result["period_end"],
        )

    return {"ok": True, "data": result}


@router.post("/batches/{batch_id}/confirm", summary="确认结算批次")
async def confirm_settlement_batch(
    batch_id: str = Path(..., description="批次 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """确认结算批次（draft -> confirmed），关联流水标记为 settled。"""
    scheduler = SettlementScheduler(db, x_tenant_id)
    notify = SettlementNotifyService(db, x_tenant_id)

    try:
        result = await scheduler.confirm_settlement_batch(batch_id)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 发送确认通知
    await notify.notify_batch_confirmed(
        batch_id=batch_id,
        batch_no=result["batch_no"],
        settled_count=result["settled_count"],
        total_amount_fen=result["total_amount_fen"],
    )

    return {"ok": True, "data": result}


@router.post("/batches/{batch_id}/settle", summary="标记已打款")
async def settle_batch(
    batch_id: str = Path(..., description="批次 ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """实际打款完成后将批次标记为 settled（confirmed -> settled）。"""
    scheduler = SettlementScheduler(db, x_tenant_id)
    notify = SettlementNotifyService(db, x_tenant_id)

    try:
        result = await scheduler.settle_batch(batch_id)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await notify.notify_batch_settled(
        batch_id=batch_id,
        batch_no=result["batch_no"],
    )

    return {"ok": True, "data": result}


# ─── 分账看板 ─────────────────────────────────────────────────────────────────


@router.get("/dashboard", summary="分账看板")
async def get_dashboard(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
) -> Dict[str, Any]:
    """分账看板：汇总统计（总金额/各方分配/pending/settled 计数）。"""
    svc = StoredValueSplitService(db, x_tenant_id)
    result = await svc.get_dashboard(start_date=start_date, end_date=end_date)
    return {"ok": True, "data": result}
