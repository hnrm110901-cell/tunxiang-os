"""yield_standard_routes — 商品出料率标准库 API（PRD-06 / Tier 1 毛利底线）

接口列表：
  GET    /api/v1/supply/ingredients/{ingredient_id}/yield-standards
         列出某 ingredient 的出料率标准（默认 only_active=False 看全部含草稿/已删）
  POST   /api/v1/supply/ingredients/{ingredient_id}/yield-standards
         新建出料率标准（草稿态 approved_by=NULL）
  POST   /api/v1/supply/yield-standards/{std_id}/approve
         二级审批（不允许 self-approve）
  DELETE /api/v1/supply/yield-standards/{std_id}
         软删出料率标准
  POST   /api/v1/supply/yield-standards/calculate-purchase-qty
         BOM 反算购买量（输入净菜量 → 输出毛菜采购量）
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db as _get_db

from ..models.ingredient_yield_standard import (
    ApproveRequest,
    CalcPurchaseQtyRequest,
    YieldStandardCreate,
)
from ..services.yield_standard_service import (
    approve_yield_standard,
    calculate_purchase_qty,
    create_yield_standard,
    list_yield_standards,
    soft_delete_yield_standard,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["ingredient-yield-standards"],
)


@router.get("/ingredients/{ingredient_id}/yield-standards")
async def list_ingredient_yield_standards(
    ingredient_id: str,
    only_active: bool = Query(False, description="只看已审批生效（默认 False — 含草稿/已删）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """列出某 ingredient 的出料率标准。

    only_active=False（管理后台默认）：全部含草稿 + 已审批，不含 is_deleted=TRUE
    only_active=True：仅返回当前生效（已审批 + 时效窗内 + 未删除）
    """
    items = await list_yield_standards(
        db=db,
        tenant_id=x_tenant_id,
        ingredient_id=ingredient_id,
        only_active=only_active,
    )
    return {"ok": True, "data": {"items": items, "total": len(items)}}


@router.post("/ingredients/{ingredient_id}/yield-standards")
async def create_ingredient_yield_standard(
    ingredient_id: str,
    body: YieldStandardCreate,
    x_user_id: str = Header(..., alias="X-User-ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """新建出料率标准（草稿态）。

    管理后台场景：采购总监录入菠菜春/夏季节出料率标准。
    创建后 approved_by=NULL（草稿态），必须独立审批人调 /approve 才生效。
    """
    try:
        item = await create_yield_standard(
            db=db,
            tenant_id=x_tenant_id,
            ingredient_id=ingredient_id,
            yield_rate=body.yield_rate,
            season=body.season.value,
            effective_from=body.effective_from,
            created_by=x_user_id,
            tolerance_pct=body.tolerance_pct,
            effective_to=body.effective_to,
            process_id=body.process_id,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "YIELD_STANDARD_VALIDATION", "message": str(e)},
        ) from e
    return {"ok": True, "data": item}


@router.post("/yield-standards/{std_id}/approve")
async def approve_ingredient_yield_standard(
    std_id: str,
    body: ApproveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """二级审批接口。

    管理后台场景：财务总监审批采购总监录入的出料率标准。
    必须 approver_id != created_by（防 self-approve），重复审批返回 422。
    """
    try:
        item = await approve_yield_standard(
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
                detail={"code": "YIELD_STANDARD_NOT_FOUND", "message": msg},
            ) from e
        raise HTTPException(
            status_code=422,
            detail={"code": "YIELD_STANDARD_APPROVE_INVALID", "message": msg},
        ) from e
    return {"ok": True, "data": item}


@router.delete("/yield-standards/{std_id}")
async def delete_ingredient_yield_standard(
    std_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """软删出料率标准。

    软删后 calculate_purchase_qty 不再应用该标准（fallback BOM 原值）。
    """
    deleted = await soft_delete_yield_standard(
        db=db, tenant_id=x_tenant_id, std_id=std_id
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "YIELD_STANDARD_NOT_FOUND", "message": f"std_id={std_id} 不存在或已删除"},
        )
    return {"ok": True, "data": {"std_id": std_id, "is_deleted": True}}


@router.post("/yield-standards/calculate-purchase-qty")
async def calc_purchase_qty_for_bom(
    body: CalcPurchaseQtyRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """BOM 反算购买量。

    采购员场景：BOM 需 60kg 净菠菜 → 系统按春季出料率 0.65 反算
    → 实时返回 purchase_qty_kg ≈ 92.3kg + 应用的标准明细。
    """
    try:
        purchase_qty, meta = await calculate_purchase_qty(
            db=db,
            tenant_id=x_tenant_id,
            ingredient_id=body.ingredient_id,
            required_net_qty_kg=body.required_net_qty_kg,
            season=body.season.value,
            today=body.today,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "YIELD_STANDARD_CALC_INVALID", "message": str(e)},
        ) from e
    return {
        "ok": True,
        "data": {
            "ingredient_id": body.ingredient_id,
            "required_net_qty_kg": str(body.required_net_qty_kg),
            "purchase_qty_kg": str(purchase_qty),
            "standard_id": meta["standard_id"],
            "yield_rate": str(meta["yield_rate"]) if meta["yield_rate"] is not None else None,
            "season_matched": meta["season_matched"],
            "anomaly_detected": meta["anomaly_detected"],
        },
    }


__all__ = ["router"]
