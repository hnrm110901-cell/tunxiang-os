"""
加盟商合同+收费管理路由（DB持久化，v217表）

端点清单：
  ─ 合同管理 ─
  GET    /api/v1/org/franchise/contracts              — 合同列表（franchisee_id/status/expiring过滤）
  GET    /api/v1/org/franchise/contracts/expiring     — 即将到期合同
  GET    /api/v1/org/franchise/contracts/{id}         — 合同详情
  POST   /api/v1/org/franchise/contracts              — 创建合同（自动生成contract_no）
  PUT    /api/v1/org/franchise/contracts/{id}         — 更新合同
  POST   /api/v1/org/franchise/contracts/{id}/send-alert  — 触发到期提醒

  ─ 收费收缴管理 ─
  POST   /api/v1/org/franchise/contracts/{id}/fee-schedule — 设置收费计划
  GET    /api/v1/org/franchise/contracts/{id}/fees         — 查看应收费用明细
  POST   /api/v1/org/franchise/contracts/{id}/collect      — 记录收款
  GET    /api/v1/org/franchise/fee-summary                 — 加盟费收缴汇总报表

  ─ 旧收费端点（兼容） ─
  GET    /api/v1/org/franchise/fees                   — 收费记录列表
  POST   /api/v1/org/franchise/fees                   — 新增收费记录
  PUT    /api/v1/org/franchise/fees/{id}/pay          — 标记付款
  GET    /api/v1/org/franchise/fees/overdue           — 逾期未付记录
  GET    /api/v1/org/franchise/fees/stats             — 收费统计

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
金额单位：分（int）。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/franchise", tags=["franchise-contracts"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ContractCreate(BaseModel):
    franchisee_id: str
    franchisee_name: Optional[str] = None
    contract_type: str = Field(
        ..., description="initial / renewal / amendment"
    )
    sign_date: str
    start_date: str
    end_date: str
    contract_amount_fen: int = Field(default=0, ge=0)
    file_url: Optional[str] = None
    alert_days_before: int = Field(default=30, ge=1)
    notes: Optional[str] = None


class ContractUpdate(BaseModel):
    contract_type: Optional[str] = None
    sign_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    contract_amount_fen: Optional[int] = Field(default=None, ge=0)
    file_url: Optional[str] = None
    status: Optional[str] = None
    alert_days_before: Optional[int] = Field(default=None, ge=1)
    notes: Optional[str] = None


class FeeRecordCreate(BaseModel):
    franchisee_id: str
    franchisee_name: Optional[str] = None
    contract_id: Optional[str] = None
    fee_type: str = Field(
        ...,
        description="joining_fee/royalty/management_fee/marketing_fee/brand_fee/deposit",
    )
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    amount_fen: int = Field(..., gt=0)
    due_date: Optional[str] = None
    notes: Optional[str] = None


class FeePayRequest(BaseModel):
    paid_fen: int = Field(..., gt=0, description="本次实际付款金额（分）")
    receipt_no: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


class FeeScheduleItem(BaseModel):
    fee_type: str = Field(..., description="joining_fee/royalty/management_fee/marketing_fee/brand_fee/deposit")
    amount_fen: int = Field(..., gt=0, description="金额（分）")
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None


class FeeScheduleRequest(BaseModel):
    items: list[FeeScheduleItem] = Field(..., min_length=1, description="收费计划明细列表")


class CollectRequest(BaseModel):
    fee_id: str = Field(..., description="收费记录ID")
    paid_fen: int = Field(..., gt=0, description="本次收款金额（分）")
    receipt_no: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _generate_contract_no() -> str:
    ym = datetime.now(timezone.utc).strftime("%Y%m")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"FC-{ym}-{suffix}"


def _db_unavailable_response() -> dict:
    return {
        "ok": False,
        "error": {
            "code": "DB_UNAVAILABLE",
            "message": "加盟合同服务暂时不可用，请稍后重试",
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  合同管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/contracts/expiring")
async def get_expiring_contracts(
    days: int = Query(default=30, ge=1, description="N天内到期"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """即将到期合同列表（end_date <= today + days）。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, contract_no, contract_type, franchisee_id, franchisee_name,
                       sign_date, start_date, end_date, contract_amount_fen,
                       file_url, status, alert_days_before, notes, created_by,
                       is_deleted, created_at, updated_at,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts
                WHERE is_deleted = FALSE
                  AND status = 'active'
                  AND (end_date - CURRENT_DATE) BETWEEN 0 AND :days
                ORDER BY (end_date - CURRENT_DATE) ASC
            """),
            {"days": days},
        )
        rows = [dict(r) for r in result.mappings().all()]

        for r in rows:
            r["warning"] = True

        logger.info("franchise_contracts_expiring_queried", tenant_id=x_tenant_id,
                     days=days, count=len(rows))
        return {"ok": True, "data": {"items": rows, "total": len(rows)}}

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("expiring_contracts_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/contracts")
async def list_contracts(
    franchisee_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    expiring: Optional[int] = Query(default=None, description="N天内到期过滤"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """合同列表，支持多维过滤。"""
    try:
        where_clauses = ["is_deleted = FALSE"]
        params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

        if franchisee_id:
            where_clauses.append("franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id
        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if expiring is not None:
            where_clauses.append("(end_date - CURRENT_DATE) BETWEEN 0 AND :expiring")
            params["expiring"] = expiring

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, contract_no, contract_type, franchisee_id, franchisee_name,
                       sign_date, start_date, end_date, contract_amount_fen,
                       file_url, status, alert_days_before, notes, created_by,
                       is_deleted, created_at, updated_at,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM franchise_contracts WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        logger.info("franchise_contracts_listed", tenant_id=x_tenant_id, total=total, page=page)
        return {"ok": True, "data": {"items": rows, "total": total}}

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("contracts_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/contracts/{contract_id}")
async def get_contract(
    contract_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """合同详情。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, contract_no, contract_type, franchisee_id, franchisee_name,
                       sign_date, start_date, end_date, contract_amount_fen,
                       file_url, status, alert_days_before, notes, created_by,
                       is_deleted, created_at, updated_at,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts
                WHERE id = :contract_id AND is_deleted = FALSE
            """),
            {"contract_id": contract_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}},
            )
        return {"ok": True, "data": dict(row)}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("contract_detail_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/contracts")
async def create_contract(
    body: ContractCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """创建合同，自动生成合同编号。"""
    try:
        contract_no = _generate_contract_no()
        new_id = str(uuid.uuid4())

        await db.execute(
            text("""
                INSERT INTO franchise_contracts
                    (id, tenant_id, contract_no, contract_type, franchisee_id,
                     franchisee_name, sign_date, start_date, end_date,
                     contract_amount_fen, file_url, alert_days_before, notes)
                VALUES
                    (:id, :tenant_id, :contract_no, :contract_type, :franchisee_id,
                     :franchisee_name, :sign_date, :start_date, :end_date,
                     :contract_amount_fen, :file_url, :alert_days_before, :notes)
            """),
            {
                "id": new_id,
                "tenant_id": x_tenant_id,
                "contract_no": contract_no,
                "contract_type": body.contract_type,
                "franchisee_id": body.franchisee_id,
                "franchisee_name": body.franchisee_name or "",
                "sign_date": body.sign_date,
                "start_date": body.start_date,
                "end_date": body.end_date,
                "contract_amount_fen": body.contract_amount_fen,
                "file_url": body.file_url,
                "alert_days_before": body.alert_days_before,
                "notes": body.notes,
            },
        )
        await db.commit()

        # 回读
        result = await db.execute(
            text("""
                SELECT id, contract_no, contract_type, franchisee_id, franchisee_name,
                       sign_date, start_date, end_date, contract_amount_fen,
                       file_url, status, alert_days_before, notes, created_by,
                       is_deleted, created_at, updated_at,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts WHERE id = :id
            """),
            {"id": new_id},
        )
        row = result.mappings().first()

        logger.info("franchise_contract_created", tenant_id=x_tenant_id,
                     contract_id=new_id, contract_no=contract_no)
        return {"ok": True, "data": dict(row)}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("contract_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.put("/contracts/{contract_id}")
async def update_contract(
    contract_id: str,
    body: ContractUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """更新合同信息。"""
    try:
        # 检查存在
        check = await db.execute(
            text("SELECT id FROM franchise_contracts WHERE id = :id AND is_deleted = FALSE"),
            {"id": contract_id},
        )
        if check.mappings().first() is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}},
            )

        update_data = body.model_dump(exclude_none=True)
        if not update_data:
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "error": {"code": "NO_UPDATE", "message": "未提供任何更新字段"}},
            )

        set_parts = [f"{k} = :{k}" for k in update_data]
        set_parts.append("updated_at = NOW()")
        set_sql = ", ".join(set_parts)
        update_data["id"] = contract_id

        await db.execute(
            text(f"UPDATE franchise_contracts SET {set_sql} WHERE id = :id"),
            update_data,
        )
        await db.commit()

        result = await db.execute(
            text("""
                SELECT id, contract_no, contract_type, franchisee_id, franchisee_name,
                       sign_date, start_date, end_date, contract_amount_fen,
                       file_url, status, alert_days_before, notes, created_by,
                       is_deleted, created_at, updated_at,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts WHERE id = :id
            """),
            {"id": contract_id},
        )
        row = result.mappings().first()

        logger.info("franchise_contract_updated", tenant_id=x_tenant_id,
                     contract_id=contract_id, fields=list(body.model_dump(exclude_none=True).keys()))
        return {"ok": True, "data": dict(row)}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("contract_update_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/contracts/{contract_id}/send-alert")
async def send_contract_alert(
    contract_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """触发到期提醒（模拟发送企微通知）。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, contract_no, franchisee_id, franchisee_name, end_date,
                       (end_date - CURRENT_DATE) AS days_to_expire
                FROM franchise_contracts
                WHERE id = :contract_id AND is_deleted = FALSE
            """),
            {"contract_id": contract_id},
        )
        row = result.mappings().first()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}},
            )

        days_left = row["days_to_expire"]
        alert_msg = (
            f"【屯象OS合同到期提醒】加盟商「{row['franchisee_name'] or row['franchisee_id']}」"
            f"合同（{row['contract_no']}）将于 {row['end_date']} 到期，"
            f"距今还有 {days_left} 天，请及时跟进续签事宜。"
        )

        logger.info(
            "franchise_contract_alert_sent",
            tenant_id=x_tenant_id,
            contract_id=contract_id,
            contract_no=row["contract_no"],
            days_to_expire=days_left,
            channel="wecom_mock",
        )

        return {
            "ok": True,
            "data": {
                "contract_id": contract_id,
                "contract_no": row["contract_no"],
                "days_to_expire": days_left,
                "alert_sent": True,
                "channel": "wecom_mock",
                "message": alert_msg,
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("contract_alert_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  收费收缴流程端点（新增 v217）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/contracts/{contract_id}/fee-schedule")
async def set_fee_schedule(
    contract_id: str,
    body: FeeScheduleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """设置收费计划（加盟费/管理费/品牌使用费等），批量创建收费记录。"""
    try:
        # 验证合同存在
        contract_check = await db.execute(
            text("""
                SELECT id, franchisee_id, franchisee_name
                FROM franchise_contracts
                WHERE id = :contract_id AND is_deleted = FALSE
            """),
            {"contract_id": contract_id},
        )
        contract = contract_check.mappings().first()
        if contract is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "合同不存在"}},
            )

        created_ids = []
        for item in body.items:
            fee_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO franchise_fee_records
                        (id, tenant_id, contract_id, franchisee_id, franchisee_name,
                         fee_type, amount_fen, period_start, period_end, due_date, notes)
                    VALUES
                        (:id, :tenant_id, :contract_id, :franchisee_id, :franchisee_name,
                         :fee_type, :amount_fen, :period_start, :period_end, :due_date, :notes)
                """),
                {
                    "id": fee_id,
                    "tenant_id": x_tenant_id,
                    "contract_id": contract_id,
                    "franchisee_id": str(contract["franchisee_id"]),
                    "franchisee_name": contract["franchisee_name"] or "",
                    "fee_type": item.fee_type,
                    "amount_fen": item.amount_fen,
                    "period_start": item.period_start,
                    "period_end": item.period_end,
                    "due_date": item.due_date,
                    "notes": item.notes,
                },
            )
            created_ids.append(fee_id)

        await db.commit()

        logger.info("franchise_fee_schedule_set", tenant_id=x_tenant_id,
                     contract_id=contract_id, count=len(created_ids))

        return {
            "ok": True,
            "data": {
                "contract_id": contract_id,
                "created_count": len(created_ids),
                "fee_ids": created_ids,
            },
        }

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("fee_schedule_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/contracts/{contract_id}/fees")
async def get_contract_fees(
    contract_id: str,
    status: Optional[str] = Query(default=None),
    fee_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """查看某合同下的应收费用明细。"""
    try:
        where_clauses = ["contract_id = :contract_id", "is_deleted = FALSE"]
        params: dict[str, Any] = {
            "contract_id": contract_id,
            "limit": size,
            "offset": (page - 1) * size,
        }

        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if fee_type:
            where_clauses.append("fee_type = :fee_type")
            params["fee_type"] = fee_type

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, period_start, period_end, amount_fen, paid_fen,
                       due_date, status, receipt_no, receipt_url, notes,
                       created_at, updated_at
                FROM franchise_fee_records
                WHERE {where_sql}
                ORDER BY due_date ASC NULLS LAST, created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM franchise_fee_records WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        # 汇总
        summary_result = await db.execute(
            text("""
                SELECT COALESCE(SUM(amount_fen), 0) AS total_amount_fen,
                       COALESCE(SUM(paid_fen), 0) AS total_paid_fen
                FROM franchise_fee_records
                WHERE contract_id = :contract_id AND is_deleted = FALSE
            """),
            {"contract_id": contract_id},
        )
        summary = summary_result.mappings().first()

        return {
            "ok": True,
            "data": {
                "items": rows,
                "total": total,
                "summary": {
                    "total_amount_fen": summary["total_amount_fen"],
                    "total_paid_fen": summary["total_paid_fen"],
                    "total_unpaid_fen": summary["total_amount_fen"] - summary["total_paid_fen"],
                },
            },
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("contract_fees_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/contracts/{contract_id}/collect")
async def collect_fee(
    contract_id: str,
    body: CollectRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """记录收款：指定收费记录ID，增加已付金额。"""
    try:
        # 验证收费记录存在且属于该合同
        result = await db.execute(
            text("""
                SELECT id, contract_id, amount_fen, paid_fen, status, fee_type
                FROM franchise_fee_records
                WHERE id = :fee_id AND contract_id = :contract_id AND is_deleted = FALSE
            """),
            {"fee_id": body.fee_id, "contract_id": contract_id},
        )
        fee = result.mappings().first()

        if fee is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND",
                        "message": "收费记录不存在或不属于该合同"}},
            )

        new_paid = fee["paid_fen"] + body.paid_fen
        if new_paid > fee["amount_fen"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "ok": False,
                    "error": {
                        "code": "OVERPAYMENT",
                        "message": f"付款金额超出应收。应收：{fee['amount_fen']}分，已付：{fee['paid_fen']}分，本次：{body.paid_fen}分",
                    },
                },
            )

        new_status = "paid" if new_paid >= fee["amount_fen"] else "partial"

        update_params: dict[str, Any] = {
            "fee_id": body.fee_id,
            "paid_fen": new_paid,
            "status": new_status,
        }
        set_parts = ["paid_fen = :paid_fen", "status = :status", "updated_at = NOW()"]

        if body.receipt_no:
            set_parts.append("receipt_no = :receipt_no")
            update_params["receipt_no"] = body.receipt_no
        if body.receipt_url:
            set_parts.append("receipt_url = :receipt_url")
            update_params["receipt_url"] = body.receipt_url
        if body.notes:
            set_parts.append("notes = :notes")
            update_params["notes"] = body.notes

        await db.execute(
            text(f"UPDATE franchise_fee_records SET {', '.join(set_parts)} WHERE id = :fee_id"),
            update_params,
        )
        await db.commit()

        # 回读
        updated = await db.execute(
            text("""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, amount_fen, paid_fen, status, receipt_no, receipt_url,
                       notes, updated_at
                FROM franchise_fee_records WHERE id = :fee_id
            """),
            {"fee_id": body.fee_id},
        )
        row = updated.mappings().first()

        logger.info("franchise_fee_collected", tenant_id=x_tenant_id,
                     contract_id=contract_id, fee_id=body.fee_id,
                     paid_fen=body.paid_fen, new_status=new_status)
        return {"ok": True, "data": dict(row)}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("fee_collect_db_error", error=str(exc), contract_id=contract_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/fee-summary")
async def get_fee_summary(
    franchisee_id: Optional[str] = Query(default=None),
    fee_type: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """加盟费收缴汇总报表：按加盟商+费用类型汇总应收/已收/逾期。"""
    try:
        where_clauses = ["is_deleted = FALSE"]
        params: dict[str, Any] = {}

        if franchisee_id:
            where_clauses.append("franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id
        if fee_type:
            where_clauses.append("fee_type = :fee_type")
            params["fee_type"] = fee_type

        where_sql = " AND ".join(where_clauses)

        # 总计
        total_result = await db.execute(
            text(f"""
                SELECT COALESCE(SUM(amount_fen), 0) AS total_amount_fen,
                       COALESCE(SUM(paid_fen), 0) AS total_paid_fen,
                       COALESCE(SUM(CASE WHEN status = 'overdue' THEN amount_fen - paid_fen ELSE 0 END), 0)
                           AS total_overdue_fen,
                       COUNT(*) AS total_records
                FROM franchise_fee_records
                WHERE {where_sql}
            """),
            params,
        )
        totals = dict(total_result.mappings().first())

        # 按费用类型汇总
        by_type_result = await db.execute(
            text(f"""
                SELECT fee_type,
                       SUM(amount_fen) AS amount_fen,
                       SUM(paid_fen) AS paid_fen,
                       SUM(CASE WHEN status = 'overdue' THEN amount_fen - paid_fen ELSE 0 END) AS overdue_fen,
                       COUNT(*) AS record_count
                FROM franchise_fee_records
                WHERE {where_sql}
                GROUP BY fee_type
                ORDER BY fee_type
            """),
            params,
        )
        by_type = [dict(r) for r in by_type_result.mappings().all()]

        # 按加盟商汇总
        by_franchisee_result = await db.execute(
            text(f"""
                SELECT franchisee_id, franchisee_name,
                       SUM(amount_fen) AS amount_fen,
                       SUM(paid_fen) AS paid_fen,
                       SUM(CASE WHEN status = 'overdue' THEN amount_fen - paid_fen ELSE 0 END) AS overdue_fen,
                       COUNT(*) AS record_count
                FROM franchise_fee_records
                WHERE {where_sql}
                GROUP BY franchisee_id, franchisee_name
                ORDER BY overdue_fen DESC
            """),
            params,
        )
        by_franchisee = [dict(r) for r in by_franchisee_result.mappings().all()]

        logger.info("franchise_fee_summary_queried", tenant_id=x_tenant_id,
                     total_records=totals["total_records"])
        return {
            "ok": True,
            "data": {
                "total_amount_fen": totals["total_amount_fen"],
                "total_paid_fen": totals["total_paid_fen"],
                "total_unpaid_fen": totals["total_amount_fen"] - totals["total_paid_fen"],
                "total_overdue_fen": totals["total_overdue_fen"],
                "total_records": totals["total_records"],
                "by_type": by_type,
                "by_franchisee": by_franchisee,
            },
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("fee_summary_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  旧收费管理端点（兼容保留）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/fees/overdue")
async def get_overdue_fees(
    franchisee_id: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """逾期未付收费记录。"""
    try:
        where_clauses = ["status = 'overdue'", "is_deleted = FALSE"]
        params: dict[str, Any] = {}

        if franchisee_id:
            where_clauses.append("franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, period_start, period_end, amount_fen, paid_fen,
                       due_date, status, receipt_no, receipt_url, notes,
                       created_at, updated_at
                FROM franchise_fee_records
                WHERE {where_sql}
                ORDER BY due_date ASC
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        total_overdue_fen = sum(r["amount_fen"] - r["paid_fen"] for r in rows)

        logger.info("franchise_fees_overdue_queried", tenant_id=x_tenant_id,
                     count=len(rows), total_overdue_fen=total_overdue_fen)
        return {
            "ok": True,
            "data": {
                "items": rows,
                "total": len(rows),
                "total_overdue_fen": total_overdue_fen,
            },
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("fees_overdue_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/fees/stats")
async def get_fee_stats(
    franchisee_id: Optional[str] = Query(default=None),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """收费统计：按类型汇总应收/已收/逾期金额。"""
    try:
        where_clauses = ["is_deleted = FALSE"]
        params: dict[str, Any] = {}

        if franchisee_id:
            where_clauses.append("franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id

        where_sql = " AND ".join(where_clauses)

        total_result = await db.execute(
            text(f"""
                SELECT COALESCE(SUM(amount_fen), 0) AS total_amount_fen,
                       COALESCE(SUM(paid_fen), 0) AS total_paid_fen,
                       COALESCE(SUM(CASE WHEN status = 'overdue' THEN amount_fen - paid_fen ELSE 0 END), 0)
                           AS total_overdue_fen
                FROM franchise_fee_records
                WHERE {where_sql}
            """),
            params,
        )
        totals = dict(total_result.mappings().first())

        by_type_result = await db.execute(
            text(f"""
                SELECT fee_type,
                       SUM(amount_fen) AS amount_fen,
                       SUM(paid_fen) AS paid_fen,
                       SUM(CASE WHEN status = 'overdue' THEN amount_fen - paid_fen ELSE 0 END) AS overdue_fen
                FROM franchise_fee_records
                WHERE {where_sql}
                GROUP BY fee_type
                ORDER BY fee_type
            """),
            params,
        )
        by_type = [dict(r) for r in by_type_result.mappings().all()]

        logger.info("franchise_fees_stats_queried", tenant_id=x_tenant_id,
                     total_amount_fen=totals["total_amount_fen"])
        return {
            "ok": True,
            "data": {
                "total_amount_fen": totals["total_amount_fen"],
                "total_paid_fen": totals["total_paid_fen"],
                "total_unpaid_fen": totals["total_amount_fen"] - totals["total_paid_fen"],
                "total_overdue_fen": totals["total_overdue_fen"],
                "by_type": by_type,
            },
        }

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("fees_stats_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.get("/fees")
async def list_fees(
    franchisee_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    fee_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """收费记录列表，支持多维过滤。"""
    try:
        where_clauses = ["is_deleted = FALSE"]
        params: dict[str, Any] = {"limit": size, "offset": (page - 1) * size}

        if franchisee_id:
            where_clauses.append("franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id
        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if fee_type:
            where_clauses.append("fee_type = :fee_type")
            params["fee_type"] = fee_type

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, period_start, period_end, amount_fen, paid_fen,
                       due_date, status, receipt_no, receipt_url, notes,
                       created_at, updated_at
                FROM franchise_fee_records
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM franchise_fee_records WHERE {where_sql}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar_one()

        logger.info("franchise_fees_listed", tenant_id=x_tenant_id, total=total, page=page)
        return {"ok": True, "data": {"items": rows, "total": total}}

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        logger.error("fees_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.post("/fees")
async def create_fee_record(
    body: FeeRecordCreate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """新增收费记录。"""
    try:
        new_id = str(uuid.uuid4())

        await db.execute(
            text("""
                INSERT INTO franchise_fee_records
                    (id, tenant_id, franchisee_id, franchisee_name, contract_id,
                     fee_type, period_start, period_end, amount_fen, due_date, notes)
                VALUES
                    (:id, :tenant_id, :franchisee_id, :franchisee_name, :contract_id,
                     :fee_type, :period_start, :period_end, :amount_fen, :due_date, :notes)
            """),
            {
                "id": new_id,
                "tenant_id": x_tenant_id,
                "franchisee_id": body.franchisee_id,
                "franchisee_name": body.franchisee_name or "",
                "contract_id": body.contract_id,
                "fee_type": body.fee_type,
                "period_start": body.period_start,
                "period_end": body.period_end,
                "amount_fen": body.amount_fen,
                "due_date": body.due_date,
                "notes": body.notes,
            },
        )
        await db.commit()

        result = await db.execute(
            text("""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, period_start, period_end, amount_fen, paid_fen,
                       due_date, status, receipt_no, receipt_url, notes,
                       created_at, updated_at
                FROM franchise_fee_records WHERE id = :id
            """),
            {"id": new_id},
        )
        row = result.mappings().first()

        logger.info("franchise_fee_record_created", tenant_id=x_tenant_id,
                     fee_id=new_id, fee_type=body.fee_type, amount_fen=body.amount_fen)
        return {"ok": True, "data": dict(row)}

    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("fee_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())


@router.put("/fees/{fee_id}/pay")
async def pay_fee_record(
    fee_id: str,
    body: FeePayRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> dict[str, Any]:
    """标记付款：更新 paid_fen / status / receipt_no。"""
    try:
        result = await db.execute(
            text("""
                SELECT id, amount_fen, paid_fen, status
                FROM franchise_fee_records
                WHERE id = :fee_id AND is_deleted = FALSE
            """),
            {"fee_id": fee_id},
        )
        fee = result.mappings().first()

        if fee is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "error": {"code": "NOT_FOUND", "message": "收费记录不存在"}},
            )

        new_paid = fee["paid_fen"] + body.paid_fen
        if new_paid > fee["amount_fen"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "ok": False,
                    "error": {
                        "code": "OVERPAYMENT",
                        "message": f"付款金额超出应收金额。应收：{fee['amount_fen']}分，已付：{fee['paid_fen']}分，本次：{body.paid_fen}分",
                    },
                },
            )

        new_status = "paid" if new_paid >= fee["amount_fen"] else "partial"

        update_params: dict[str, Any] = {
            "fee_id": fee_id,
            "paid_fen": new_paid,
            "status": new_status,
        }
        set_parts = ["paid_fen = :paid_fen", "status = :status", "updated_at = NOW()"]

        if body.receipt_no:
            set_parts.append("receipt_no = :receipt_no")
            update_params["receipt_no"] = body.receipt_no
        if body.receipt_url:
            set_parts.append("receipt_url = :receipt_url")
            update_params["receipt_url"] = body.receipt_url
        if body.notes:
            set_parts.append("notes = :notes")
            update_params["notes"] = body.notes

        await db.execute(
            text(f"UPDATE franchise_fee_records SET {', '.join(set_parts)} WHERE id = :fee_id"),
            update_params,
        )
        await db.commit()

        updated = await db.execute(
            text("""
                SELECT id, contract_id, franchisee_id, franchisee_name,
                       fee_type, amount_fen, paid_fen, due_date, status,
                       receipt_no, receipt_url, notes, created_at, updated_at
                FROM franchise_fee_records WHERE id = :fee_id
            """),
            {"fee_id": fee_id},
        )
        row = updated.mappings().first()

        logger.info("franchise_fee_paid", tenant_id=x_tenant_id, fee_id=fee_id,
                     paid_fen=body.paid_fen, new_status=new_status)
        return {"ok": True, "data": dict(row)}

    except HTTPException:
        raise
    except (OperationalError, InterfaceError, ProgrammingError) as exc:
        await db.rollback()
        logger.error("fee_pay_db_error", error=str(exc), fee_id=fee_id)
        raise HTTPException(status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=_db_unavailable_response())
