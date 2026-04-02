"""加盟商财务结算 API

端点清单：
  POST  /franchise/settlements/generate          - 生成月结算单
  POST  /franchise/settlements/{id}/send         - 发送给加盟商（draft→sent）
  PUT   /franchise/settlements/{id}/confirm      - 加盟商确认（sent→confirmed）
  PUT   /franchise/settlements/{id}/pay          - 标记付款（confirmed→paid）
  GET   /franchise/settlements/overdue           - 逾期预警列表
  GET   /franchise/{franchisee_id}/statement     - 加盟商对账单（近12个月）

统一响应格式：{ "ok": bool, "data": {}, "error": {} }
认证：所有接口需传 X-Tenant-ID header
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.franchise_settlement_service import (
    FranchiseeStatement,
    FranchiseSettlement,
    FranchiseSettlementService,
    InvalidStatusTransitionError,
    SettlementNotFoundError,
)

router = APIRouter(
    prefix="/api/v1/franchise",
    tags=["franchise-settlement"],
)

_service = FranchiseSettlementService()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _require_tenant(x_tenant_id: Optional[str]) -> str:
    """从 Header 提取 tenant_id，缺失时返回 400。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header 不能为空")
    try:
        UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"X-Tenant-ID 格式无效（需 UUID）：{x_tenant_id}",
        )
    return x_tenant_id


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GenerateSettlementRequest(BaseModel):
    franchisee_id: str = Field(..., description="加盟商 UUID")
    year: int = Field(..., ge=2020, le=2099, description="年份")
    month: int = Field(..., ge=1, le=12, description="月份（1-12）")


class PaySettlementRequest(BaseModel):
    payment_ref: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="付款凭证号（如银行流水号）",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点实现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post(
    "/settlements/generate",
    summary="生成月结算单",
    description=(
        "为指定加盟商生成指定年月的结算单（幂等：已存在则返回已有记录）。"
        "生成后状态为 draft，需手动调用 /send 发送给加盟商。"
    ),
)
async def generate_settlement(
    req: GenerateSettlementRequest,
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,  # 实际注入：Depends(get_db)
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    try:
        settlement = await _service.generate_monthly_settlement(
            franchisee_id=req.franchisee_id,
            year=req.year,
            month=req.month,
            tenant_id=tenant_id,
            db=db,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _ok(settlement.model_dump(mode="json"))


@router.post(
    "/settlements/{settlement_id}/send",
    summary="发送结算单给加盟商",
    description="将 draft 结算单发送给加盟商（draft→sent），同时触发企业微信通知。",
)
async def send_settlement(
    settlement_id: str,
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    try:
        await _service.send_settlement_to_franchisee(
            settlement_id=settlement_id,
            tenant_id=tenant_id,
            db=db,
        )
    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ok({"settlement_id": settlement_id, "status": "sent"})


@router.put(
    "/settlements/{settlement_id}/confirm",
    summary="加盟商确认结算单",
    description="加盟商对结算单内容无异议后确认（sent→confirmed）。",
)
async def confirm_settlement(
    settlement_id: str,
    franchisee_id: str = Query(..., description="操作加盟商 ID"),
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    try:
        await _service.confirm_settlement(
            settlement_id=settlement_id,
            franchisee_id=franchisee_id,
            tenant_id=tenant_id,
            db=db,
        )
    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return _ok({"settlement_id": settlement_id, "status": "confirmed"})


@router.put(
    "/settlements/{settlement_id}/pay",
    summary="标记结算单已付款",
    description="总部财务确认收款后标记为已付（confirmed→paid），记录付款凭证。",
)
async def mark_as_paid(
    settlement_id: str,
    req: PaySettlementRequest,
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    try:
        await _service.mark_as_paid(
            settlement_id=settlement_id,
            payment_ref=req.payment_ref,
            tenant_id=tenant_id,
            db=db,
        )
    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidStatusTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ok({"settlement_id": settlement_id, "status": "paid"})


@router.get(
    "/settlements/overdue",
    summary="逾期预警列表",
    description=(
        "查询超期未付款的结算单（confirmed 且超期 N 天）。"
        "默认超期阈值 15 天，可通过 ?overdue_days=N 调整。"
    ),
)
async def get_overdue_settlements(
    overdue_days: int = Query(default=15, ge=1, le=365, description="逾期天数阈值"),
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    settlements: List[FranchiseSettlement] = await _service.get_overdue_settlements(
        tenant_id=tenant_id,
        overdue_days=overdue_days,
        db=db,
    )
    return _ok({
        "overdue_days": overdue_days,
        "count": len(settlements),
        "items": [s.model_dump(mode="json") for s in settlements],
    })


@router.get(
    "/{franchisee_id}/statement",
    summary="加盟商对账单",
    description=(
        "查询指定加盟商近 N 个月的对账报表，"
        "包含每月营业额/特许权金/管理费及累计欠款汇总。"
        "默认查近12个月，可通过 ?months=N 调整。"
    ),
)
async def get_franchisee_statement(
    franchisee_id: str,
    months: int = Query(default=12, ge=1, le=36, description="查询月数"),
    x_tenant_id: Optional[str] = Header(None),
    db: None = None,
) -> dict:
    tenant_id = _require_tenant(x_tenant_id)
    try:
        UUID(franchisee_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"franchisee_id 格式无效（需 UUID）：{franchisee_id}",
        )

    statement: FranchiseeStatement = await _service.get_franchisee_statement(
        franchisee_id=franchisee_id,
        tenant_id=tenant_id,
        months=months,
        db=db,
    )
    return _ok(statement.model_dump(mode="json"))
