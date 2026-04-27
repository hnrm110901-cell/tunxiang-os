"""
合同台账 API 路由

负责合同登记、查询、付款计划管理、到期预警、统计看板。
共10个端点，覆盖合同全生命周期（登记→付款→预警→终止）。

金额约定：所有金额字段单位为分(fen)，1元=100分，展示层负责转换。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

try:
    from src.services.contract_ledger_service import ContractLedgerService

    _contract_svc = ContractLedgerService()
except ImportError:
    _contract_svc = None  # type: ignore[assignment]

router = APIRouter()


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


def _get_svc() -> "ContractLedgerService":
    if _contract_svc is None:
        raise HTTPException(status_code=503, detail="合同台账服务暂不可用，请稍后重试")
    return _contract_svc


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------


class ContractCreate(BaseModel):
    contract_no: Optional[str] = Field(None, max_length=64, description="合同编号（租户内唯一）")
    contract_name: str = Field(..., max_length=200, description="合同名称")
    contract_type: Optional[str] = Field(None, description="合同类型：rental/equipment/service/labor/other")
    counterparty_name: Optional[str] = Field(None, max_length=200, description="乙方/甲方名称")
    counterparty_contact: Optional[str] = Field(None, max_length=100, description="对方联系人")
    total_amount: Optional[int] = Field(None, description="合同总金额（分），1元=100分")
    start_date: Optional[date] = Field(None, description="合同开始日期")
    end_date: Optional[date] = Field(None, description="合同结束日期")
    auto_renew: bool = Field(False, description="是否自动续约")
    renewal_notice_days: int = Field(30, ge=1, le=365, description="提前N天提醒续签")
    status: str = Field("active", description="合同状态：draft/active")
    store_id: Optional[UUID] = Field(None, description="关联门店ID")
    responsible_person: Optional[UUID] = Field(None, description="合同负责人员工ID")
    file_url: Optional[str] = Field(None, description="合同附件URL")
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    contract_no: Optional[str] = Field(None, max_length=64)
    contract_name: Optional[str] = Field(None, max_length=200)
    contract_type: Optional[str] = None
    counterparty_name: Optional[str] = Field(None, max_length=200)
    counterparty_contact: Optional[str] = Field(None, max_length=100)
    total_amount: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    auto_renew: Optional[bool] = None
    renewal_notice_days: Optional[int] = Field(None, ge=1, le=365)
    status: Optional[str] = None
    store_id: Optional[UUID] = None
    responsible_person: Optional[UUID] = None
    file_url: Optional[str] = None
    notes: Optional[str] = None


class TerminateContractRequest(BaseModel):
    reason: str = Field(..., max_length=500, description="终止原因")


class PaymentPlanCreate(BaseModel):
    period_name: Optional[str] = Field(None, max_length=100, description="期次名称，如'2026年Q1'")
    due_date: date = Field(..., description="计划付款日期")
    planned_amount: int = Field(..., gt=0, description="计划付款金额（分），1元=100分")
    notes: Optional[str] = None


class MarkPaymentPaidRequest(BaseModel):
    actual_amount: int = Field(..., gt=0, description="实际付款金额（分），1元=100分")


# ---------------------------------------------------------------------------
# 端点实现
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建合同")
async def create_contract(
    body: ContractCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    登记新合同

    - 覆盖门店租约、设备采购、服务外包、劳务等各类合同
    - total_amount 单位为分(fen)，例如：10000分 = 100元
    - auto_renew=true 时系统将在 renewal_notice_days 天前推送自动续约预警
    """
    svc = _get_svc()
    try:
        data = body.model_dump()
        result = await svc.create_contract(
            db=db,
            tenant_id=tenant_id,
            created_by=current_user_id,
            data=data,
        )
        await db.commit()
        logger.info(
            "contract_created_via_api",
            tenant_id=str(tenant_id),
            contract_id=str(result.id),
        )
        return {"ok": True, "data": {"id": str(result.id), "contract_name": result.contract_name}}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("contract_create_db_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建合同失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        logger.error("contract_create_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="创建合同失败，请稍后重试")


@router.get("", summary="合同列表")
async def list_contracts(
    contract_status: Optional[str] = Query(
        None, alias="status", description="状态过滤：draft/active/expired/terminated"
    ),
    contract_type: Optional[str] = Query(None, description="类型过滤：rental/equipment/service/labor/other"),
    store_id: Optional[UUID] = Query(None, description="门店ID过滤"),
    expiring_within_days: Optional[int] = Query(None, ge=1, le=365, description="N天内到期的合同"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查询合同列表

    支持按状态、类型、门店、到期时间过滤。
    expiring_within_days=30 返回30天内即将到期的合同。
    """
    svc = _get_svc()
    try:
        filters: Dict[str, Any] = {}
        if contract_status is not None:
            filters["status"] = contract_status
        if contract_type is not None:
            filters["contract_type"] = contract_type
        if store_id is not None:
            filters["store_id"] = store_id
        if expiring_within_days is not None:
            filters["expiring_within_days"] = expiring_within_days

        items = await svc.list_contracts(db=db, tenant_id=tenant_id, filters=filters)
        return {"ok": True, "data": items, "total": len(items)}
    except Exception as exc:
        logger.error("contract_list_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询合同列表失败，请稍后重试")


@router.get("/expiring", summary="即将到期合同")
async def get_expiring_contracts(
    within_days: int = Query(30, ge=1, le=365, description="查询N天内到期的合同"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    查询即将到期的合同

    默认返回30天内到期的 active 合同，按到期日升序排列。
    支持 auto_renew=true 的合同会额外标注自动续约标志。
    """
    svc = _get_svc()
    try:
        items = await svc.list_contracts(
            db=db,
            tenant_id=tenant_id,
            filters={"status": "active", "expiring_within_days": within_days},
        )
        return {"ok": True, "data": items, "total": len(items), "within_days": within_days}
    except Exception as exc:
        logger.error("expiring_contracts_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="查询即将到期合同失败，请稍后重试")


@router.get("/calendar", summary="付款日历")
async def get_payment_calendar(
    year: int = Query(..., ge=2020, le=2099, description="年份"),
    month: int = Query(..., ge=1, le=12, description="月份"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取指定月份的付款日历

    按日期汇总当月所有付款计划，金额单位为分(fen)。
    """
    svc = _get_svc()
    try:
        result = await svc.get_payment_calendar(db=db, tenant_id=tenant_id, year=year, month=month)
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.error("payment_calendar_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取付款日历失败，请稍后重试")


@router.get("/stats", summary="合同统计看板")
async def get_stats(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    合同台账统计看板

    返回：合同总数、按状态/类型分布、总金额、已付金额、30天内到期数、逾期付款笔数。
    金额单位为分(fen)。
    """
    svc = _get_svc()
    try:
        result = await svc.get_stats(db=db, tenant_id=tenant_id)
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.error("contract_stats_failed", error=str(exc), tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取统计数据失败，请稍后重试")


@router.get("/{contract_id}", summary="合同详情")
async def get_contract(
    contract_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """获取合同详情，包含付款计划和预警记录。"""
    svc = _get_svc()
    try:
        result = await svc.get_contract(db=db, tenant_id=tenant_id, contract_id=contract_id)
        return {"ok": True, "data": result}
    except LookupError:
        raise HTTPException(status_code=404, detail="合同不存在或无权访问")
    except Exception as exc:
        logger.error("contract_get_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="获取合同详情失败，请稍后重试")


@router.put("/{contract_id}", summary="更新合同")
async def update_contract(
    contract_id: UUID,
    body: ContractUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    更新合同信息

    - 已终止（terminated）的合同不允许更新，请使用 /terminate 端点
    - 金额字段单位为分(fen)
    """
    svc = _get_svc()
    try:
        data = {k: v for k, v in body.model_dump().items() if v is not None}
        result = await svc.update_contract(db=db, tenant_id=tenant_id, contract_id=contract_id, data=data)
        await db.commit()
        logger.info(
            "contract_updated_via_api",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
        )
        return {"ok": True, "data": {"id": str(result.id), "contract_name": result.contract_name}}
    except LookupError:
        raise HTTPException(status_code=404, detail="合同不存在或无权访问")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("contract_update_db_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="更新合同失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        logger.error("contract_update_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="更新合同失败，请稍后重试")


@router.post("/{contract_id}/terminate", summary="终止合同")
async def terminate_contract(
    contract_id: UUID,
    body: TerminateContractRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    终止合同

    将合同状态置为 terminated，并将终止原因追加到 notes。
    """
    svc = _get_svc()
    try:
        result = await svc.terminate_contract(
            db=db,
            tenant_id=tenant_id,
            contract_id=contract_id,
            reason=body.reason,
        )
        await db.commit()
        logger.info(
            "contract_terminated_via_api",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
        )
        return {"ok": True, "data": {"id": str(result.id), "status": result.status}}
    except LookupError:
        raise HTTPException(status_code=404, detail="合同不存在或无权访问")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("contract_terminate_db_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="终止合同失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        logger.error("contract_terminate_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="终止合同失败，请稍后重试")


@router.post("/{contract_id}/payment-plans", status_code=status.HTTP_201_CREATED, summary="添加付款计划")
async def add_payment_plan(
    contract_id: UUID,
    body: PaymentPlanCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    为合同添加付款计划期次

    - planned_amount 单位为分(fen)
    - 可为同一合同添加多个付款期次（季度/月度/里程碑等）
    """
    svc = _get_svc()
    try:
        data = body.model_dump()
        result = await svc.add_payment_plan(db=db, tenant_id=tenant_id, contract_id=contract_id, data=data)
        await db.commit()
        logger.info(
            "payment_plan_added_via_api",
            tenant_id=str(tenant_id),
            contract_id=str(contract_id),
            payment_id=str(result.id),
        )
        return {"ok": True, "data": {"id": str(result.id), "due_date": str(result.due_date)}}
    except LookupError:
        raise HTTPException(status_code=404, detail="合同不存在或无权访问")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("payment_plan_add_db_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="添加付款计划失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        logger.error("payment_plan_add_failed", error=str(exc), contract_id=str(contract_id), exc_info=True)
        raise HTTPException(status_code=500, detail="添加付款计划失败，请稍后重试")


@router.post("/payment-plans/{payment_id}/pay", summary="标记付款计划已付")
async def mark_payment_paid(
    payment_id: UUID,
    body: MarkPaymentPaidRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    current_user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    标记付款计划已付

    - actual_amount 为实际付款金额（分），可与计划金额不同
    - 标记已付后自动累计更新合同的 paid_amount 总额
    """
    svc = _get_svc()
    try:
        result = await svc.mark_payment_paid(
            db=db,
            tenant_id=tenant_id,
            payment_id=payment_id,
            actual_amount=body.actual_amount,
        )
        await db.commit()
        logger.info(
            "payment_marked_paid_via_api",
            tenant_id=str(tenant_id),
            payment_id=str(payment_id),
            actual_amount=body.actual_amount,
        )
        return {
            "ok": True,
            "data": {
                "id": str(result.id),
                "status": result.status,
                "actual_amount": result.actual_amount,
                "paid_at": result.paid_at.isoformat() if result.paid_at else None,
            },
        }
    except LookupError:
        raise HTTPException(status_code=404, detail="付款计划不存在或无权访问")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("mark_payment_paid_db_failed", error=str(exc), payment_id=str(payment_id), exc_info=True)
        raise HTTPException(status_code=500, detail="标记付款失败（数据库错误），请稍后重试")
    except Exception as exc:
        await db.rollback()
        logger.error("mark_payment_paid_failed", error=str(exc), payment_id=str(payment_id), exc_info=True)
        raise HTTPException(status_code=500, detail="标记付款失败，请稍后重试")
