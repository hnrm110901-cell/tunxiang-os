"""
D12 合规 — 薪酬合规 API（社保/个税/银行代发）
------------------------------------------------
端点:
  POST /api/v1/payroll/calc-si/{pay_month}                         按门店批量算社保
  POST /api/v1/payroll/calc-tax/{pay_month}                        按门店批量算个税
  POST /api/v1/payroll/generate-disbursement/{pay_month}?bank=...  生成银行代发文件
  GET  /api/v1/payroll/disbursement/{batch_id}/download            下载代发文件

pay_month 格式：YYYY-MM
"""

from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.dependencies import get_current_active_user
from ..models.employee import Employee
from ..models.payroll import PayrollRecord
from ..models.user import User
from ..services.bank_disbursement_service import BankDisbursementService
from ..services.personal_tax_service import PersonalTaxService
from ..services.social_insurance_service import SocialInsuranceService

logger = structlog.get_logger()
router = APIRouter()


# ── 批量社保 ──────────────────────────────────────────────────
@router.post("/payroll/calc-si/{pay_month}")
async def calc_si_batch(
    pay_month: str,
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """按门店批量计算员工当月社保公积金并写入 payroll_si_records"""
    _validate_pay_month(pay_month)
    service = SocialInsuranceService(store_id=store_id)
    result = await service.calc_monthly_si_batch(db, store_id, pay_month)
    return result


# ── 批量个税 ──────────────────────────────────────────────────
@router.post("/payroll/calc-tax/{pay_month}")
async def calc_tax_batch(
    pay_month: str,
    store_id: str = Query(..., description="门店 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """
    按门店批量计算员工当月个税（基于已生成的 PayrollRecord 和社保明细）。
    注意：需要先 calc-si 再 calc-tax，再 calculate_payroll（或反之，由 payroll_service 串起来）。
    此端点为独立触发，直接读取 PayrollRecord.gross_salary_fen + social_insurance_fen + housing_fund_fen。
    """
    _validate_pay_month(pay_month)

    # 拉取门店本月所有工资单
    result = await db.execute(
        select(PayrollRecord, Employee)
        .join(Employee, PayrollRecord.employee_id == Employee.id)
        .where(
            and_(
                PayrollRecord.store_id == store_id,
                PayrollRecord.pay_month == pay_month,
            )
        )
    )
    rows = result.all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"门店 {store_id} {pay_month} 尚无工资单，请先运行 payroll calculate",
        )

    tax_service = PersonalTaxService(store_id=store_id)
    success = 0
    total_tax_fen = 0
    failed: List[Dict[str, Any]] = []

    for payroll_record, emp in rows:
        try:
            si_personal = (payroll_record.social_insurance_fen or 0) + (
                payroll_record.housing_fund_fen or 0
            )
            detail = await tax_service.calc_monthly_tax(
                db,
                employee_id=emp.id,
                pay_month=pay_month,
                gross_fen=payroll_record.gross_salary_fen or 0,
                si_personal_fen=si_personal,
            )
            success += 1
            total_tax_fen += detail["current_month_tax_fen"]
        except Exception as e:  # noqa: BLE001
            logger.warning("tax_calc_failed", employee_id=emp.id, error=str(e))
            failed.append({"employee_id": emp.id, "error": str(e)})

    return {
        "store_id": store_id,
        "pay_month": pay_month,
        "total_employees": len(rows),
        "success": success,
        "failed": failed,
        "total_tax_fen": total_tax_fen,
        "total_tax_yuan": round(total_tax_fen / 100, 2),
    }


# ── 银行代发 ──────────────────────────────────────────────────
@router.post("/payroll/generate-disbursement/{pay_month}")
async def generate_disbursement(
    pay_month: str,
    store_id: str = Query(..., description="门店 ID"),
    bank: str = Query("icbc", description="icbc | ccb | generic"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """生成银行代发文件（TXT / CSV），落到 /tmp/salary_disbursements/"""
    _validate_pay_month(pay_month)
    service = BankDisbursementService(store_id=store_id)

    bank_lower = (bank or "icbc").lower()
    if bank_lower == "icbc":
        return await service.generate_icbc_file(db, pay_month, store_id)
    if bank_lower == "ccb":
        return await service.generate_ccb_file(db, pay_month, store_id)
    if bank_lower == "generic":
        return await service.generate_generic_csv(db, pay_month, store_id)
    raise HTTPException(status_code=400, detail=f"不支持的银行: {bank}")


@router.get("/payroll/disbursement/{batch_id}/download")
async def download_disbursement_file(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """下载已生成的代发文件"""
    service = BankDisbursementService()
    record = await service.get_by_batch_id(db, batch_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"代发批次 {batch_id} 不存在")
    if not record.file_path:
        raise HTTPException(status_code=404, detail="文件路径为空")

    import os

    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=410, detail="文件已被清理，需重新生成")

    filename = os.path.basename(record.file_path)
    media_type = "text/plain" if record.file_format == "txt" else "text/csv"
    return FileResponse(
        record.file_path, media_type=media_type, filename=filename
    )


# ── 工具函数 ──────────────────────────────────────────────────
def _validate_pay_month(pay_month: str) -> None:
    if not pay_month or len(pay_month) != 7 or pay_month[4] != "-":
        raise HTTPException(
            status_code=400, detail=f"pay_month 格式应为 YYYY-MM，实际: {pay_month}"
        )
    try:
        int(pay_month[:4])
        m = int(pay_month[5:7])
        if m < 1 or m > 12:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"pay_month 无效: {pay_month}")
