"""weight_standard_routes — 商品扣秤标准库 API（PRD-02 / Tier 1 毛利底线）

接口列表：
  GET    /api/v1/supply/ingredients/{ingredient_id}/weight-standards
         列出某 ingredient 的扣秤标准（默认 only_active=False 看全部含草稿/已删）
  POST   /api/v1/supply/ingredients/{ingredient_id}/weight-standards
         新建扣秤标准（草稿态 approved_by=NULL）
  POST   /api/v1/supply/weight-standards/{std_id}/approve
         二级审批（不允许 self-approve）
  DELETE /api/v1/supply/weight-standards/{std_id}
         软删扣秤标准
  POST   /api/v1/supply/receiving/{order_id}/calculate-net-weight
         手动触发净重计算（收货员用 — 输入 ingredient_id + gross_weight_kg）
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.ingredient_weight_standard import (
    ApproveRequest,
    CalcNetWeightRequest,
    WeightStandardCreate,
)
from ..services.weight_standard_service import (
    approve_weight_standard,
    calculate_net_weight,
    create_weight_standard,
    get_weight_standard,
    list_weight_standards,
    soft_delete_weight_standard,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["ingredient-weight-standards"],
)


@router.get("/ingredients/{ingredient_id}/weight-standards")
async def list_ingredient_weight_standards(
    ingredient_id: str,
    only_active: bool = Query(False, description="只看已审批生效（默认 False — 含草稿/已删）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出某 ingredient 的扣秤标准。

    only_active=False（管理后台默认）：全部含草稿 + 已审批，不含 is_deleted=TRUE
    only_active=True：仅返回当前生效（已审批 + 时效窗内 + 未删除）
    """
    items = await list_weight_standards(
        db=db,
        tenant_id=x_tenant_id,
        ingredient_id=ingredient_id,
        only_active=only_active,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/ingredients/{ingredient_id}/weight-standards")
async def create_ingredient_weight_standard(
    ingredient_id: str,
    body: WeightStandardCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建扣秤标准（草稿态）。

    管理后台场景：采购总监录入海鲜 SKU 的冰块/塑料袋扣秤标准。
    创建后 approved_by=NULL（草稿态），必须独立审批人调 /approve 才生效。
    """
    try:
        item = await create_weight_standard(
            db=db,
            tenant_id=x_tenant_id,
            ingredient_id=ingredient_id,
            deduct_type=body.deduct_type.value,
            deduct_method=body.deduct_method.value,
            deduct_value=body.deduct_value,
            effective_from=body.effective_from,
            created_by=x_user_id,
            tolerance_pct=body.tolerance_pct,
            effective_to=body.effective_to,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "WEIGHT_STANDARD_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.post("/weight-standards/{std_id}/approve")
async def approve_ingredient_weight_standard(
    std_id: str,
    body: ApproveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """二级审批接口。

    管理后台场景：财务总监审批采购总监录入的扣秤标准。
    必须 approver_id != created_by（防 self-approve），重复审批返回 422。
    """
    try:
        item = await approve_weight_standard(
            db=db,
            tenant_id=x_tenant_id,
            std_id=std_id,
            approver_id=body.approver_id,
        )
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(
                status_code=404,
                detail={"code": "WEIGHT_STANDARD_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "WEIGHT_STANDARD_APPROVE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/weight-standards/{std_id}")
async def delete_ingredient_weight_standard(
    std_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删扣秤标准。

    软删后 calculate_net_weight 不再应用该标准。
    """
    deleted = await soft_delete_weight_standard(
        db=db, tenant_id=x_tenant_id, std_id=std_id
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "WEIGHT_STANDARD_NOT_FOUND", "message": f"std_id={std_id} 不存在或已删除"},
        )
    return {"ok": True, "data": {"std_id": std_id, "is_deleted": True}}


@router.post("/receiving/{order_id}/calculate-net-weight")
async def calc_net_weight_for_receiving(
    order_id: str,
    body: CalcNetWeightRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """手动触发净重计算（不写库存，只回返计算结果）。

    收货员场景：录入毛重 100kg → 系统应用 ice 8% / packaging 0.3kg 标准
    → 实时返回 net_weight_kg + 扣秤明细 → 收货员核对后确认入账。
    """
    try:
        net, applied = await calculate_net_weight(
            db=db,
            tenant_id=x_tenant_id,
            ingredient_id=body.ingredient_id,
            gross_weight_kg=body.gross_weight_kg,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "WEIGHT_STANDARD_CALC_INVALID", "message": str(e)},
        ) from e
    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "ingredient_id": body.ingredient_id,
            "gross_weight_kg": str(body.gross_weight_kg),
            "net_weight_kg": str(net),
            "deductions": applied,
        },
    }


# 默认导出 ─ get_weight_standard 给调试用（管理后台可加 detail 页面后再接入）
__all__ = ["router", "get_weight_standard"]
