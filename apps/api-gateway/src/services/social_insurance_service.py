"""
D12 合规 — 社保公积金计算引擎
------------------------------------------------
基于 `EmployeeSocialInsurance.personal_base_fen` 与 `SocialInsuranceConfig`
配置的区域费率，按月计算员工六险一金（五险 + 公积金）。

约束：
  1) 基数高于 base_ceiling_fen 按上限取；低于 base_floor_fen 按下限取
  2) 单险种若 has_xxx=False 则不计费
  3) 公积金个人比例若 housing_fund_pct_override 有值则覆盖区域默认
  4) 所有金额单位：分（int），伴生 _yuan 属性供展示
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.employee import Employee
from src.models.social_insurance import (
    EmployeeSocialInsurance,
    InsuranceType,
    PayrollSIRecord,
    SocialInsuranceConfig,
)
from src.services.base_service import BaseService

logger = structlog.get_logger()


def _clip_base_fen(base_fen: int, floor_fen: int, ceiling_fen: int) -> int:
    """裁剪缴费基数到 [floor, ceiling] 区间"""
    if ceiling_fen and base_fen > ceiling_fen:
        return ceiling_fen
    if floor_fen and base_fen < floor_fen:
        return floor_fen
    return base_fen


def _pct_to_fen(base_fen: int, pct: Optional[Any]) -> int:
    """按费率（百分比）计算分。pct 允许 None/Decimal/float/int"""
    if pct is None:
        return 0
    return int(base_fen * float(pct) / 100)


class SocialInsuranceService(BaseService):
    """社保公积金计算服务"""

    # ── 单人单月计算 ───────────────────────────────────────────
    async def calc_monthly_si(
        self,
        db: AsyncSession,
        employee_id: str,
        pay_month: str,
    ) -> Dict[str, Any]:
        """
        计算员工单月六险一金明细。

        Args:
            employee_id: 员工ID
            pay_month:   YYYY-MM

        Returns:
            dict 结构（金额单位=分）：
            {
              "employee_id": ..,
              "pay_month": "YYYY-MM",
              "base_fen": 裁剪后缴费基数,
              "region_code": 参保城市,
              "pension":     {"employer": int, "employee": int},
              "medical":     {"employer": int, "employee": int},
              "unemployment":{"employer": int, "employee": int},
              "injury":      {"employer": int, "employee": 0},
              "maternity":   {"employer": int, "employee": 0},
              "housing_fund":{"employer": int, "employee": int},
              "total_employer_fen": int,
              "total_employee_fen": int,
            }
        """
        year = int(pay_month[:4])

        emp_si = await self._get_emp_si(db, employee_id, year)
        if not emp_si:
            logger.info("si_not_enrolled", employee_id=employee_id, year=year)
            return self._empty_result(employee_id, pay_month)

        config = await self._get_config(db, emp_si.config_id)
        if not config:
            logger.warning(
                "si_config_missing",
                employee_id=employee_id,
                config_id=str(emp_si.config_id),
            )
            return self._empty_result(employee_id, pay_month)

        # 基数裁剪
        base_fen = _clip_base_fen(
            emp_si.personal_base_fen or 0,
            config.base_floor_fen or 0,
            config.base_ceiling_fen or 0,
        )

        # 五险
        pension_er = (
            _pct_to_fen(base_fen, config.pension_employer_pct) if emp_si.has_pension else 0
        )
        pension_ee = (
            _pct_to_fen(base_fen, config.pension_employee_pct) if emp_si.has_pension else 0
        )

        medical_er = (
            _pct_to_fen(base_fen, config.medical_employer_pct) if emp_si.has_medical else 0
        )
        medical_ee = (
            _pct_to_fen(base_fen, config.medical_employee_pct) if emp_si.has_medical else 0
        )

        unemp_er = (
            _pct_to_fen(base_fen, config.unemployment_employer_pct) if emp_si.has_unemployment else 0
        )
        unemp_ee = (
            _pct_to_fen(base_fen, config.unemployment_employee_pct) if emp_si.has_unemployment else 0
        )

        injury_er = (
            _pct_to_fen(base_fen, config.injury_employer_pct) if emp_si.has_injury else 0
        )

        maternity_er = (
            _pct_to_fen(base_fen, config.maternity_employer_pct) if emp_si.has_maternity else 0
        )

        # 公积金（个性化覆盖区域默认）
        if emp_si.has_housing_fund:
            hf_pct = (
                emp_si.housing_fund_pct_override
                if emp_si.housing_fund_pct_override is not None
                else config.housing_fund_employee_pct
            )
            hf_ee = _pct_to_fen(base_fen, hf_pct)
            # 企业端同样受 override 影响（合理假设：双边对齐）
            hf_er = _pct_to_fen(
                base_fen,
                emp_si.housing_fund_pct_override
                if emp_si.housing_fund_pct_override is not None
                else config.housing_fund_employer_pct,
            )
        else:
            hf_ee = 0
            hf_er = 0

        total_er = pension_er + medical_er + unemp_er + injury_er + maternity_er + hf_er
        total_ee = pension_ee + medical_ee + unemp_ee + hf_ee

        return {
            "employee_id": employee_id,
            "pay_month": pay_month,
            "base_fen": base_fen,
            "region_code": config.region_code,
            "pension": {"employer": pension_er, "employee": pension_ee},
            "medical": {"employer": medical_er, "employee": medical_ee},
            "unemployment": {"employer": unemp_er, "employee": unemp_ee},
            "injury": {"employer": injury_er, "employee": 0},
            "maternity": {"employer": maternity_er, "employee": 0},
            "housing_fund": {"employer": hf_er, "employee": hf_ee},
            "total_employer_fen": total_er,
            "total_employee_fen": total_ee,
            # 费率快照（用于写入 PayrollSIRecord 审计）
            "_rates": {
                InsuranceType.PENSION: (
                    float(config.pension_employer_pct or 0),
                    float(config.pension_employee_pct or 0),
                ),
                InsuranceType.MEDICAL: (
                    float(config.medical_employer_pct or 0),
                    float(config.medical_employee_pct or 0),
                ),
                InsuranceType.UNEMPLOYMENT: (
                    float(config.unemployment_employer_pct or 0),
                    float(config.unemployment_employee_pct or 0),
                ),
                InsuranceType.INJURY: (float(config.injury_employer_pct or 0), 0.0),
                InsuranceType.MATERNITY: (float(config.maternity_employer_pct or 0), 0.0),
                InsuranceType.HOUSING_FUND: (
                    float(
                        emp_si.housing_fund_pct_override
                        if emp_si.housing_fund_pct_override is not None
                        else (config.housing_fund_employer_pct or 0)
                    ),
                    float(
                        emp_si.housing_fund_pct_override
                        if emp_si.housing_fund_pct_override is not None
                        else (config.housing_fund_employee_pct or 0)
                    ),
                ),
            },
            "_has_flags": {
                InsuranceType.PENSION: emp_si.has_pension,
                InsuranceType.MEDICAL: emp_si.has_medical,
                InsuranceType.UNEMPLOYMENT: emp_si.has_unemployment,
                InsuranceType.INJURY: emp_si.has_injury,
                InsuranceType.MATERNITY: emp_si.has_maternity,
                InsuranceType.HOUSING_FUND: emp_si.has_housing_fund,
            },
            "store_id": emp_si.store_id,
        }

    # ── 门店批量计算 + 落库 ────────────────────────────────────
    async def calc_monthly_si_batch(
        self,
        db: AsyncSession,
        store_id: str,
        pay_month: str,
    ) -> Dict[str, Any]:
        """
        对门店所有在职员工批量计算并写入 PayrollSIRecord。
        每人每险种一行（已存在则更新）。
        """
        result = await db.execute(
            select(Employee).where(
                and_(Employee.store_id == store_id, Employee.is_active.is_(True))
            )
        )
        employees = result.scalars().all()

        success = 0
        total_er_fen = 0
        total_ee_fen = 0
        failed: List[Dict[str, Any]] = []

        for emp in employees:
            try:
                detail = await self.calc_monthly_si(db, emp.id, pay_month)
                if detail.get("base_fen", 0) <= 0:
                    continue
                await self._upsert_records(db, emp.id, store_id, pay_month, detail)
                success += 1
                total_er_fen += detail["total_employer_fen"]
                total_ee_fen += detail["total_employee_fen"]
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "si_batch_calc_failed", employee_id=emp.id, error=str(e)
                )
                failed.append({"employee_id": emp.id, "error": str(e)})

        await db.flush()
        return {
            "store_id": store_id,
            "pay_month": pay_month,
            "total_employees": len(employees),
            "success": success,
            "failed": failed,
            "total_employer_fen": total_er_fen,
            "total_employee_fen": total_ee_fen,
            "total_employer_yuan": round(total_er_fen / 100, 2),
            "total_employee_yuan": round(total_ee_fen / 100, 2),
        }

    # ── 内部方法 ──────────────────────────────────────────────
    async def _get_emp_si(
        self, db: AsyncSession, employee_id: str, year: int
    ) -> Optional[EmployeeSocialInsurance]:
        result = await db.execute(
            select(EmployeeSocialInsurance).where(
                and_(
                    EmployeeSocialInsurance.employee_id == employee_id,
                    EmployeeSocialInsurance.effective_year == year,
                    EmployeeSocialInsurance.is_active.is_(True),
                )
            )
        )
        return result.scalar_one_or_none()

    async def _get_config(
        self, db: AsyncSession, config_id
    ) -> Optional[SocialInsuranceConfig]:
        result = await db.execute(
            select(SocialInsuranceConfig).where(SocialInsuranceConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    async def _upsert_records(
        self,
        db: AsyncSession,
        employee_id: str,
        store_id: str,
        pay_month: str,
        detail: Dict[str, Any],
    ) -> None:
        """逐险种 upsert 到 payroll_si_records"""
        region_code = detail.get("region_code")
        base_fen = detail["base_fen"]
        rates = detail["_rates"]
        has_flags = detail["_has_flags"]

        # 遍历六险一金
        type_to_amounts = {
            InsuranceType.PENSION: detail["pension"],
            InsuranceType.MEDICAL: detail["medical"],
            InsuranceType.UNEMPLOYMENT: detail["unemployment"],
            InsuranceType.INJURY: detail["injury"],
            InsuranceType.MATERNITY: detail["maternity"],
            InsuranceType.HOUSING_FUND: detail["housing_fund"],
        }

        for itype, amounts in type_to_amounts.items():
            # 未参保 → 跳过写入
            if not has_flags.get(itype):
                continue

            existing = await db.execute(
                select(PayrollSIRecord).where(
                    and_(
                        PayrollSIRecord.employee_id == employee_id,
                        PayrollSIRecord.pay_month == pay_month,
                        PayrollSIRecord.insurance_type == itype,
                    )
                )
            )
            record = existing.scalar_one_or_none()
            if not record:
                record = PayrollSIRecord(
                    store_id=store_id,
                    employee_id=employee_id,
                    pay_month=pay_month,
                    insurance_type=itype,
                )
                db.add(record)

            er_pct, ee_pct = rates.get(itype, (0.0, 0.0))
            record.base_fen = base_fen
            record.employer_amount_fen = amounts["employer"]
            record.employee_amount_fen = amounts["employee"]
            record.employer_rate_pct = er_pct
            record.employee_rate_pct = ee_pct
            record.region_code = region_code

    def _empty_result(self, employee_id: str, pay_month: str) -> Dict[str, Any]:
        """未参保兜底结构"""
        zero = {"employer": 0, "employee": 0}
        return {
            "employee_id": employee_id,
            "pay_month": pay_month,
            "base_fen": 0,
            "region_code": None,
            "pension": zero,
            "medical": zero,
            "unemployment": zero,
            "injury": {"employer": 0, "employee": 0},
            "maternity": {"employer": 0, "employee": 0},
            "housing_fund": zero,
            "total_employer_fen": 0,
            "total_employee_fen": 0,
            "_rates": {},
            "_has_flags": {},
            "store_id": None,
        }
