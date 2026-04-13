"""
预算管理 API 路由

负责预算的全生命周期管理：创建/审批/科目分配/调整/执行率查询/快照/统计。
共12个端点，覆盖年度/月度预算管控全流程。
金额单位统一为分(fen)，展示层负责除以100转元。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.budget_service import BudgetService

router = APIRouter()
log = structlog.get_logger(__name__)

_budget_svc = BudgetService()


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------

async def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> UUID:
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的租户ID格式")


async def get_current_user(x_user_id: str = Header(..., alias="X-User-ID")) -> UUID:
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户ID格式")


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    budget_name: str = Field(..., max_length=200, description="预算名称")
    budget_year: int = Field(..., ge=2020, le=2100, description="预算年份")
    budget_month: Optional[int] = Field(
        None, ge=1, le=12,
        description="预算月份（不传=年度预算，1-12=月度预算）"
    )
    budget_type: str = Field(
        "expense",
        description="预算类型：expense/travel/procurement"
    )
    store_id: Optional[UUID] = Field(None, description="门店ID（不传=集团预算）")
    department: Optional[str] = Field(None, max_length=100, description="部门")
    total_amount: int = Field(..., gt=0, description="预算总额（分），1元=100分")
    status: str = Field("active", description="预算状态：draft/active")
    notes: Optional[str] = Field(None, description="备注")


class BudgetUpdate(BaseModel):
    budget_name: Optional[str] = Field(None, max_length=200)
    department: Optional[str] = Field(None, max_length=100)
    total_amount: Optional[int] = Field(None, gt=0, description="预算总额（分）")
    status: Optional[str] = Field(None, description="预算状态：draft/active/locked/expired")
    notes: Optional[str] = None


class AllocationCreate(BaseModel):
    category_code: str = Field(..., max_length=64, description="费用科目代码")
    amount: int = Field(..., gt=0, description="分配金额（分）")


class AdjustmentCreate(BaseModel):
    adjustment_type: str = Field(
        ..., description="调整类型：increase/decrease/reallocate"
    )
    amount: int = Field(..., description="调整金额（分，正增负减）")
    reason: Optional[str] = Field(None, description="调整原因")
    approved_by: Optional[UUID] = Field(None, description="审批人员工ID")


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_budget(
    body: BudgetCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    创建预算

    - budget_month 不传表示年度预算，传 1-12 表示月度预算
    - store_id 不传表示集团预算
    - 同一租户/年/月/类型/门店组合不允许重复（唯一约束）
    - 金额单位为分(fen)，1元=100分
    """
    try:
        result = await _budget_svc.create_budget(
            db=db,
            tenant_id=tenant_id,
            created_by=current_user_id,
            data=body.model_dump(),
        )
        await db.commit()
        log.info("budget_created_via_api", tenant_id=str(tenant_id), budget_id=str(result.id))
        return {"ok": True, "data": result}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("budget_create_db_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建预算失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        log.error("budget_create_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建预算失败，请稍后重试")


@router.get("")
async def list_budgets(
    year: Optional[int] = Query(None, description="预算年份过滤"),
    month: Optional[int] = Query(None, ge=0, le=12,
                                  description="月份过滤（0=年度预算，1-12=月度预算，不传=全部）"),
    budget_type: Optional[str] = Query(None, description="预算类型过滤：expense/travel/procurement"),
    store_id: Optional[UUID] = Query(None, description="门店ID过滤"),
    budget_status: Optional[str] = Query(None, alias="status",
                                          description="状态过滤：draft/active/locked/expired"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    预算列表

    支持按年份/月份/类型/门店/状态过滤，按年份倒序排列。
    """
    try:
        filters: Dict[str, Any] = {}
        if year is not None:
            filters["year"] = year
        if month is not None:
            filters["month"] = month
        if budget_type is not None:
            filters["budget_type"] = budget_type
        if store_id is not None:
            filters["store_id"] = store_id
        if budget_status is not None:
            filters["status"] = budget_status

        items = await _budget_svc.list_budgets(db=db, tenant_id=tenant_id, filters=filters)
        return {"ok": True, "data": items, "total": len(items)}
    except Exception as exc:
        log.error("budget_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取预算列表失败，请稍后重试")


@router.get("/stats")
async def get_budget_stats(
    year: int = Query(..., description="年份"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    年度预算统计

    返回指定年份的预算汇总：总预算额、总使用额、整体执行率、各月趋势、按类型分组。
    金额单位为分(fen)。
    """
    try:
        result = await _budget_svc.get_budget_stats(db=db, tenant_id=tenant_id, year=year)
        return {"ok": True, "data": result}
    except Exception as exc:
        log.error("budget_stats_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取年度预算统计失败，请稍后重试")


@router.get("/current")
async def get_current_budget(
    budget_type: str = Query("expense", description="预算类型：expense/travel/procurement"),
    store_id: Optional[UUID] = Query(None, description="门店ID（不传=集团预算）"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取当前预算

    查找当前年月的 active 预算：先找月度预算，找不到再找年度预算。
    store_id 不传时查集团预算。
    """
    try:
        budget = await _budget_svc.get_current_budget(
            db=db, tenant_id=tenant_id, budget_type=budget_type, store_id=store_id
        )
        if budget is None:
            return {"ok": True, "data": None, "message": "当前周期未找到匹配预算"}
        return {"ok": True, "data": budget}
    except Exception as exc:
        log.error("budget_current_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取当前预算失败，请稍后重试")


@router.post("/run-monthly-snapshot", status_code=status.HTTP_200_OK)
async def run_monthly_snapshot(
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    触发月末批量快照

    为租户下所有 active 预算创建今日快照，返回成功快照数量。
    通常在月末自动触发，也可手动调用。
    """
    try:
        count = await _budget_svc.run_monthly_snapshot(db=db, tenant_id=tenant_id)
        await db.commit()
        log.info(
            "budget_monthly_snapshot_triggered",
            tenant_id=str(tenant_id),
            operator=str(current_user_id),
            snapshot_count=count,
        )
        return {"ok": True, "data": {"snapshot_count": count}}
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("budget_monthly_snapshot_db_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="月末快照失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        log.error("budget_monthly_snapshot_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="月末快照失败，请稍后重试")


@router.get("/{budget_id}")
async def get_budget(
    budget_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取预算详情（含科目分配列表）"""
    try:
        budget = await _budget_svc.get_budget(db=db, tenant_id=tenant_id, budget_id=budget_id)
        return {"ok": True, "data": budget}
    except LookupError:
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except Exception as exc:
        log.error("budget_get_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取预算详情失败，请稍后重试")


@router.put("/{budget_id}")
async def update_budget(
    budget_id: UUID,
    body: BudgetUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新预算

    - 只允许更新 draft/active 状态的预算
    - locked/expired 状态不允许修改
    """
    try:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await _budget_svc.update_budget(
            db=db, tenant_id=tenant_id, budget_id=budget_id, data=update_data
        )
        await db.commit()
        log.info("budget_updated_via_api", tenant_id=str(tenant_id), budget_id=str(budget_id))
        return {"ok": True, "data": result}
    except LookupError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error("budget_update_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="更新预算失败，请稍后重试")


@router.post("/{budget_id}/approve")
async def approve_budget(
    budget_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    审批预算

    将预算状态从 draft 变更为 active，记录审批人。
    只允许审批 draft 状态的预算。
    """
    try:
        result = await _budget_svc.approve_budget(
            db=db, tenant_id=tenant_id, budget_id=budget_id, approved_by=current_user_id
        )
        await db.commit()
        log.info(
            "budget_approved_via_api",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            approved_by=str(current_user_id),
        )
        return {"ok": True, "data": result}
    except LookupError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error("budget_approve_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="审批预算失败，请稍后重试")


@router.post("/{budget_id}/allocations", status_code=status.HTTP_201_CREATED)
async def add_allocation(
    budget_id: UUID,
    body: AllocationCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    添加科目分配

    将预算总额按费用科目拆分。category_code 对应费用申请中的科目代码。
    金额单位为分(fen)。
    """
    try:
        result = await _budget_svc.add_allocation(
            db=db,
            tenant_id=tenant_id,
            budget_id=budget_id,
            category_code=body.category_code,
            amount=body.amount,
        )
        await db.commit()
        log.info(
            "budget_allocation_added_via_api",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            category_code=body.category_code,
        )
        return {"ok": True, "data": result}
    except LookupError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error("budget_allocation_add_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="添加科目分配失败，请稍后重试")


@router.post("/{budget_id}/adjustments", status_code=status.HTTP_201_CREATED)
async def adjust_budget(
    budget_id: UUID,
    body: AdjustmentCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    预算调整

    对预算总额进行调增/调减/重新分配，记录完整审计轨迹。
    - adjustment_type: increase（增加）/ decrease（减少）/ reallocate（重新分配）
    - amount: 调整金额（分），正值=增加，负值=减少
    """
    try:
        result = await _budget_svc.adjust_budget(
            db=db,
            tenant_id=tenant_id,
            budget_id=budget_id,
            adjustment_type=body.adjustment_type,
            amount=body.amount,
            reason=body.reason,
            approved_by=body.approved_by,
            created_by=current_user_id,
        )
        await db.commit()
        log.info(
            "budget_adjustment_via_api",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            adjustment_type=body.adjustment_type,
            amount=body.amount,
        )
        return {"ok": True, "data": result}
    except LookupError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        log.error("budget_adjust_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="预算调整失败，请稍后重试")


@router.get("/{budget_id}/execution")
async def get_execution_rate(
    budget_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    预算执行率详情

    返回预算总额、已使用、剩余、整体执行率，以及各科目分配执行明细。
    金额单位为分(fen)，rate 为小数（如 0.8567 = 85.67%）。
    """
    try:
        result = await _budget_svc.get_execution_rate(
            db=db, tenant_id=tenant_id, budget_id=budget_id
        )
        return {"ok": True, "data": result}
    except LookupError:
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except Exception as exc:
        log.error("budget_execution_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取执行率失败，请稍后重试")


@router.post("/{budget_id}/snapshot", status_code=status.HTTP_201_CREATED)
async def take_snapshot(
    budget_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    手动创建预算快照

    为指定预算创建今日快照，记录当前执行率和分配明细。
    月末会自动触发批量快照，也可按需手动创建。
    """
    try:
        result = await _budget_svc.take_snapshot(
            db=db, tenant_id=tenant_id, budget_id=budget_id
        )
        await db.commit()
        log.info(
            "budget_snapshot_via_api",
            tenant_id=str(tenant_id),
            budget_id=str(budget_id),
            operator=str(current_user_id),
        )
        return {"ok": True, "data": result}
    except LookupError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="预算不存在或无权访问")
    except Exception as exc:
        await db.rollback()
        log.error("budget_snapshot_failed", error=str(exc), budget_id=str(budget_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建快照失败，请稍后重试")
