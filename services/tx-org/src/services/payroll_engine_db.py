"""薪资计算引擎（DB 版）— 全链路异步实现

与现有计算层的分工：
  payroll_engine.py      — 纯函数计算层（无 DB 依赖）
  payroll_engine_v2.py   — 单员工内存计算编排
  payroll_engine_db.py   — 本模块：DB 读写 + 月度批量计算 + 状态机管理

所有 DB 操作通过显式传入 tenant_id 隔离，配合 RLS 双重保障。
金额统一以"分"（int）作为内部单位，DB 存储同为分。
"""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import UniversalPublisher, OrgEventType

from services.payroll_engine import (
    compute_absence_deduction,
    compute_base_salary,
    compute_commission,
    compute_early_leave_deduction,
    compute_full_attendance_bonus,
    compute_late_deduction,
    compute_overtime_pay,
    compute_performance_bonus,
    compute_seniority_subsidy,
    derive_hourly_rate,
    count_work_days,
)
from services.social_insurance import SocialInsuranceCalculator
from services.income_tax import IncomeTaxCalculator

log = structlog.get_logger(__name__)


# ── 数据传输对象 ───────────────────────────────────────────────────────────────


@dataclass
class SIResult:
    """五险一金计算结果"""
    personal_total_fen: int      # 个人合计（分）
    employer_total_fen: int      # 企业合计（分）
    pension_personal_fen: int
    pension_employer_fen: int
    medical_personal_fen: int
    medical_employer_fen: int
    unemployment_personal_fen: int
    unemployment_employer_fen: int
    housing_fund_personal_fen: int
    housing_fund_employer_fen: int


@dataclass
class SocialInsuranceConfig:
    """从 DB 读取的社保配置"""
    region: str
    pension_rate_employee: float
    pension_rate_employer: float
    medical_rate_employee: float
    medical_rate_employer: float
    unemployment_rate_employee: float
    unemployment_rate_employer: float
    housing_fund_rate: float


@dataclass
class PayrollRecord:
    """月度薪资计算结果（对应 payroll_records_v2 表）"""
    tenant_id: UUID
    store_id: UUID
    employee_id: UUID
    period_year: int
    period_month: int
    work_days: int
    work_hours: float
    overtime_hours: float
    base_salary_fen: int
    commission_fen: int
    overtime_pay_fen: int
    bonus_fen: int
    deductions_fen: int
    social_insurance_fen: int     # 个人五险
    housing_fund_fen: int         # 个人公积金
    gross_salary_fen: int
    net_salary_fen: int
    status: str = "draft"
    confirmed_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    id: Optional[UUID] = None


@dataclass
class PayrollSummary:
    """门店月度薪资汇总"""
    tenant_id: UUID
    store_id: UUID
    period_year: int
    period_month: int
    employee_count: int
    total_gross_fen: int
    total_net_fen: int
    total_si_fen: int             # 个人五险一金合计
    total_employer_si_fen: int    # 企业承担社保合计（人力成本用）
    by_position: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Payslip:
    """个人工资条详情"""
    employee_id: UUID
    period_year: int
    period_month: int
    record: PayrollRecord
    items: List[Dict[str, Any]] = field(default_factory=list)   # 明细行


# ── 引擎 ─────────────────────────────────────────────────────────────────────


class PayrollEngine:
    """薪资计算引擎（异步 DB 版）

    用法::

        engine = PayrollEngine()
        records = await engine.calculate_monthly_payroll(
            db, tenant_id, store_id, 2026, 3
        )
    """

    def __init__(self) -> None:
        self._si_calc = SocialInsuranceCalculator()
        self._tax_calc = IncomeTaxCalculator()

    # ─────────────────────────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────────────────────────

    async def calculate_monthly_payroll(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        year: int,
        month: int,
    ) -> List[PayrollRecord]:
        """月度薪资计算（全门店）

        流程：
          1. 读取门店员工列表及其薪资配置
          2. 读取当月考勤汇总（attendance_records）
          3. 按薪资方案类型计算各员工薪资
          4. 查询对应地区社保配置并计算五险一金
          5. 生成 payroll_records_v2 草稿记录（upsert）
        """
        log.info(
            "payroll.calculate_monthly_payroll.start",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            year=year,
            month=month,
        )
        # 1. 门店员工薪资配置
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])

        emp_configs = await self._fetch_employee_salary_configs(
            db, tenant_id, store_id, period_start
        )
        if not emp_configs:
            log.warning(
                "payroll.calculate_monthly_payroll.no_employees",
                store_id=str(store_id),
            )
            return []

        # 2. 考勤汇总
        attendance_map = await self._fetch_attendance_summary(
            db, tenant_id, store_id, year, month
        )

        # 3. 社保配置
        si_config = await self._fetch_si_config(db, tenant_id, period_start)

        # 4. 标准工作日数
        standard_work_days = count_work_days(year, month)

        records: List[PayrollRecord] = []
        for emp_cfg in emp_configs:
            employee_id: UUID = emp_cfg["employee_id"]
            att = attendance_map.get(str(employee_id), {})

            try:
                record = self._compute_one_employee(
                    tenant_id=tenant_id,
                    store_id=store_id,
                    employee_id=employee_id,
                    year=year,
                    month=month,
                    emp_cfg=emp_cfg,
                    att=att,
                    standard_work_days=standard_work_days,
                    si_config=si_config,
                )
                records.append(record)
            except (ValueError, ZeroDivisionError, KeyError) as exc:
                log.error(
                    "payroll.calculate_monthly_payroll.employee_error",
                    employee_id=str(employee_id),
                    error=str(exc),
                    exc_info=True,
                )

        # 5. 持久化（upsert）
        await self._upsert_payroll_records(db, records)

        log.info(
            "payroll.calculate_monthly_payroll.done",
            store_id=str(store_id),
            count=len(records),
        )

        if records:
            total_amount_fen = sum(r.net_salary_fen for r in records)
            asyncio.create_task(UniversalPublisher.publish(
                event_type=OrgEventType.PAYROLL_GENERATED,
                tenant_id=tenant_id,
                store_id=store_id,
                entity_id=store_id,
                event_data={"year_month": f"{year}-{month:02d}", "employee_count": len(records), "total_amount_fen": total_amount_fen},
                source_service="tx-org",
            ))

        return records

    async def confirm_payroll(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        period_year: int,
        period_month: int,
        store_id: Optional[UUID] = None,
    ) -> int:
        """确认薪资（draft → confirmed）

        Returns:
            确认条数
        """
        where_store = "AND store_id = :store_id" if store_id else ""
        params: Dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "year": period_year,
            "month": period_month,
            "confirmed_at": datetime.now(),
        }
        if store_id:
            params["store_id"] = str(store_id)

        result = await db.execute(
            text(f"""
                UPDATE payroll_records_v2
                SET status = 'confirmed',
                    confirmed_at = :confirmed_at,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND period_year = :year
                  AND period_month = :month
                  AND status = 'draft'
                  AND is_deleted = FALSE
                  {where_store}
            """),
            params,
        )
        count: int = result.rowcount  # type: ignore[assignment]
        log.info(
            "payroll.confirm_payroll",
            tenant_id=str(tenant_id),
            year=period_year,
            month=period_month,
            count=count,
        )
        return count

    async def mark_paid(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        payroll_ids: List[UUID],
    ) -> int:
        """批量标记已发放（confirmed → paid）

        Returns:
            成功标记条数
        """
        if not payroll_ids:
            return 0

        id_list = [str(pid) for pid in payroll_ids]
        result = await db.execute(
            text("""
                UPDATE payroll_records_v2
                SET status = 'paid',
                    paid_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = ANY(:ids)
                  AND status = 'confirmed'
                  AND is_deleted = FALSE
            """),
            {"tenant_id": str(tenant_id), "ids": id_list},
        )
        count: int = result.rowcount  # type: ignore[assignment]
        log.info(
            "payroll.mark_paid",
            tenant_id=str(tenant_id),
            requested=len(payroll_ids),
            updated=count,
        )
        return count

    async def get_payroll_summary(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        year: int,
        month: int,
    ) -> PayrollSummary:
        """门店月度薪资汇总

        Returns:
            PayrollSummary（总人数、总薪资、社保合计、实发合计，以及按岗位分组统计）
        """
        row = await db.execute(
            text("""
                SELECT
                    COUNT(*)                        AS employee_count,
                    COALESCE(SUM(gross_salary_fen), 0) AS total_gross_fen,
                    COALESCE(SUM(net_salary_fen), 0)   AS total_net_fen,
                    COALESCE(SUM(social_insurance_fen + housing_fund_fen), 0) AS total_si_fen
                FROM payroll_records_v2
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND period_year = :year
                  AND period_month = :month
                  AND is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "year": year,
                "month": month,
            },
        )
        agg = row.mappings().one()

        # 按岗位分组（关联 employees 表，如存在）
        by_pos_rows = await db.execute(
            text("""
                SELECT
                    COALESCE(e.role_name, 'unknown')  AS position,
                    COUNT(*)                           AS headcount,
                    COALESCE(SUM(p.gross_salary_fen), 0) AS gross_fen,
                    COALESCE(SUM(p.net_salary_fen), 0)   AS net_fen
                FROM payroll_records_v2 p
                LEFT JOIN employees e
                       ON e.id = p.employee_id
                      AND e.tenant_id = p.tenant_id
                      AND e.is_deleted = FALSE
                WHERE p.tenant_id = :tenant_id
                  AND p.store_id = :store_id
                  AND p.period_year = :year
                  AND p.period_month = :month
                  AND p.is_deleted = FALSE
                GROUP BY e.role_name
                ORDER BY gross_fen DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "year": year,
                "month": month,
            },
        )
        by_position = [dict(r) for r in by_pos_rows.mappings().all()]

        return PayrollSummary(
            tenant_id=tenant_id,
            store_id=store_id,
            period_year=year,
            period_month=month,
            employee_count=int(agg["employee_count"]),
            total_gross_fen=int(agg["total_gross_fen"]),
            total_net_fen=int(agg["total_net_fen"]),
            total_si_fen=int(agg["total_si_fen"]),
            total_employer_si_fen=0,  # 企业侧社保需从独立字段汇总，暂留 0
            by_position=by_position,
        )

    async def get_employee_payslip(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        employee_id: UUID,
        year: int,
        month: int,
    ) -> Optional[Payslip]:
        """个人工资条详情

        Returns:
            Payslip 或 None（未找到）
        """
        row = await db.execute(
            text("""
                SELECT *
                FROM payroll_records_v2
                WHERE tenant_id = :tenant_id
                  AND employee_id = :employee_id
                  AND period_year = :year
                  AND period_month = :month
                  AND is_deleted = FALSE
                LIMIT 1
            """),
            {
                "tenant_id": str(tenant_id),
                "employee_id": str(employee_id),
                "year": year,
                "month": month,
            },
        )
        mapping = row.mappings().first()
        if not mapping:
            return None

        record = self._row_to_payroll_record(mapping)

        # 拼装明细行（工资条展示用）
        items = _build_payslip_items(record)

        return Payslip(
            employee_id=employee_id,
            period_year=year,
            period_month=month,
            record=record,
            items=items,
        )

    def calculate_social_insurance(
        self,
        base_fen: int,
        config: SocialInsuranceConfig,
    ) -> SIResult:
        """五险一金计算

        Args:
            base_fen: 社保缴费基数（分）
            config:   地区费率配置

        Returns:
            SIResult（个人+企业各险种分项及合计）
        """
        def _fen(rate: float) -> int:
            return int(base_fen * rate)

        pension_personal = _fen(config.pension_rate_employee)
        pension_employer = _fen(config.pension_rate_employer)
        medical_personal = _fen(config.medical_rate_employee)
        medical_employer = _fen(config.medical_rate_employer)
        unemployment_personal = _fen(config.unemployment_rate_employee)
        unemployment_employer = _fen(config.unemployment_rate_employer)
        housing_personal = _fen(config.housing_fund_rate)
        housing_employer = _fen(config.housing_fund_rate)

        personal_total = (
            pension_personal + medical_personal + unemployment_personal + housing_personal
        )
        employer_total = (
            pension_employer + medical_employer + unemployment_employer + housing_employer
        )
        return SIResult(
            personal_total_fen=personal_total,
            employer_total_fen=employer_total,
            pension_personal_fen=pension_personal,
            pension_employer_fen=pension_employer,
            medical_personal_fen=medical_personal,
            medical_employer_fen=medical_employer,
            unemployment_personal_fen=unemployment_personal,
            unemployment_employer_fen=unemployment_employer,
            housing_fund_personal_fen=housing_personal,
            housing_fund_employer_fen=housing_employer,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 内部辅助方法
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_one_employee(
        self,
        *,
        tenant_id: UUID,
        store_id: UUID,
        employee_id: UUID,
        year: int,
        month: int,
        emp_cfg: Dict[str, Any],
        att: Dict[str, Any],
        standard_work_days: int,
        si_config: Optional[SocialInsuranceConfig],
    ) -> PayrollRecord:
        """单员工月度薪资计算（纯内存，无 DB 调用）"""
        scheme_type: str = emp_cfg.get("scheme_type", "monthly")
        base_salary_fen: int = emp_cfg.get("base_salary_fen", 0)
        hourly_rate_fen: int = emp_cfg.get("hourly_rate_fen", 0)
        commission_rate: float = float(emp_cfg.get("commission_rate", 0.0))
        si_base_fen: int = emp_cfg.get("social_insurance_base_fen", 0) or base_salary_fen

        # 考勤数据
        work_days: int = int(att.get("work_days", 0))
        work_hours: float = float(att.get("work_hours", 0))
        overtime_hours: float = float(att.get("overtime_hours", 0))
        absence_days: float = float(att.get("absence_days", 0))
        late_count: int = int(att.get("late_count", 0))
        early_leave_count: int = int(att.get("early_leave_count", 0))
        sales_amount_fen: int = int(att.get("sales_amount_fen", 0))

        # ── 基本工资（按薪资方案类型）
        if scheme_type == "monthly":
            base_pay_fen = compute_base_salary(base_salary_fen, work_days, standard_work_days)
        elif scheme_type == "hourly":
            effective_rate = hourly_rate_fen or derive_hourly_rate(base_salary_fen, standard_work_days)
            base_pay_fen = int(effective_rate * work_hours)
        else:  # commission
            base_pay_fen = compute_base_salary(base_salary_fen, work_days, standard_work_days)

        # ── 提成
        commission_fen = compute_commission(sales_amount_fen, commission_rate)

        # ── 加班费（工作日 1.5x，简化：所有加班统一用 1.5x，实际可扩展）
        overtime_hourly = derive_hourly_rate(base_salary_fen, standard_work_days)
        overtime_pay_fen = compute_overtime_pay(overtime_hourly, overtime_hours, "weekday")

        # ── 全勤奖（无缺勤/迟到/早退）
        full_attend_fen = compute_full_attendance_bonus(
            absence_days, late_count, early_leave_count, 30_000  # 默认 300元全勤奖
        )

        # ── 考勤扣款
        absence_deduction_fen = compute_absence_deduction(base_salary_fen, absence_days, standard_work_days)
        late_deduction_fen = compute_late_deduction(late_count, 5_000)
        early_leave_deduction_fen = compute_early_leave_deduction(early_leave_count, 5_000)
        deductions_fen = absence_deduction_fen + late_deduction_fen + early_leave_deduction_fen

        # ── 应发工资
        gross_salary_fen = max(
            0,
            base_pay_fen + commission_fen + overtime_pay_fen + full_attend_fen - deductions_fen,
        )

        # ── 五险一金
        if si_config:
            si_result = self.calculate_social_insurance(si_base_fen, si_config)
            social_insurance_fen = (
                si_result.pension_personal_fen
                + si_result.medical_personal_fen
                + si_result.unemployment_personal_fen
            )
            housing_fund_fen = si_result.housing_fund_personal_fen
        else:
            # 降级：使用内置 SocialInsuranceCalculator
            raw = self._si_calc.calculate(gross_salary_fen=si_base_fen)
            social_insurance_fen = raw.get("personal_total", 0)
            housing_fund_fen = 0

        # ── 实发
        net_salary_fen = max(0, gross_salary_fen - social_insurance_fen - housing_fund_fen)

        return PayrollRecord(
            tenant_id=tenant_id,
            store_id=store_id,
            employee_id=employee_id,
            period_year=year,
            period_month=month,
            work_days=work_days,
            work_hours=work_hours,
            overtime_hours=overtime_hours,
            base_salary_fen=base_pay_fen,
            commission_fen=commission_fen,
            overtime_pay_fen=overtime_pay_fen,
            bonus_fen=full_attend_fen,
            deductions_fen=deductions_fen,
            social_insurance_fen=social_insurance_fen,
            housing_fund_fen=housing_fund_fen,
            gross_salary_fen=gross_salary_fen,
            net_salary_fen=net_salary_fen,
            status="draft",
        )

    async def _fetch_employee_salary_configs(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        period_start: date,
    ) -> List[Dict[str, Any]]:
        """从 DB 读取门店员工薪资配置（当前有效配置）"""
        rows = await db.execute(
            text("""
                SELECT
                    e.id               AS employee_id,
                    esc.scheme_id,
                    ss.scheme_type,
                    COALESCE(esc.base_salary_fen, ss.base_salary_fen, 0)  AS base_salary_fen,
                    COALESCE(ss.hourly_rate_fen, 0)                        AS hourly_rate_fen,
                    COALESCE(esc.commission_rate, 0)                       AS commission_rate,
                    COALESCE(esc.social_insurance_base_fen, esc.base_salary_fen, 0)
                                                                           AS social_insurance_base_fen
                FROM employees e
                LEFT JOIN employee_salary_configs esc
                       ON esc.employee_id = e.id
                      AND esc.tenant_id = e.tenant_id
                      AND esc.effective_from <= :period_start
                      AND (esc.effective_to IS NULL OR esc.effective_to >= :period_start)
                      AND esc.is_deleted = FALSE
                LEFT JOIN salary_schemes ss
                       ON ss.id = esc.scheme_id
                      AND ss.tenant_id = e.tenant_id
                      AND ss.is_deleted = FALSE
                WHERE e.tenant_id = :tenant_id
                  AND e.store_id = :store_id
                  AND e.is_deleted = FALSE
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "period_start": period_start.isoformat(),
            },
        )
        return [dict(r) for r in rows.mappings().all()]

    async def _fetch_attendance_summary(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        year: int,
        month: int,
    ) -> Dict[str, Dict[str, Any]]:
        """读取门店当月考勤汇总，返回 {employee_id: {...}}

        从 attendance_records 汇总各员工月度考勤数据：
        - work_days: 正常出勤天数（absence_type IS NULL）
        - work_hours: 实际工时合计
        - overtime_hours: 加班工时合计
        - absence_days: 缺勤天数（旷工+病假+事假，不含节假日/调休）
        - late_count: 迟到次数（从 clock_records 获取，降级到 0）
        - early_leave_count: 早退次数（从 clock_records 获取，降级到 0）
        """
        rows = await db.execute(
            text("""
                SELECT
                    ar.employee_id,
                    COUNT(*) FILTER (WHERE ar.absence_type IS NULL)        AS work_days,
                    COALESCE(SUM(ar.work_hours), 0)                        AS work_hours,
                    COALESCE(SUM(ar.overtime_hours), 0)                    AS overtime_hours,
                    COUNT(*) FILTER (
                        WHERE ar.absence_type IS NOT NULL
                          AND ar.absence_type NOT IN ('holiday', 'compensatory')
                    )                                                       AS absence_days
                FROM attendance_records ar
                JOIN employees e
                       ON e.id = ar.employee_id
                      AND e.store_id = :store_id
                      AND e.tenant_id = ar.tenant_id
                      AND e.is_deleted = FALSE
                WHERE ar.tenant_id = :tenant_id
                  AND EXTRACT(YEAR  FROM ar.work_date) = :year
                  AND EXTRACT(MONTH FROM ar.work_date) = :month
                  AND ar.is_deleted = FALSE
                GROUP BY ar.employee_id
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "year": year,
                "month": month,
            },
        )
        base_map: Dict[str, Dict[str, Any]] = {
            str(r["employee_id"]): dict(r) for r in rows.mappings().all()
        }

        # 尝试从 clock_records 补充迟到/早退次数（表可能不存在，安全降级）
        try:
            late_rows = await db.execute(
                text("""
                    SELECT
                        cr.employee_id,
                        COUNT(*) FILTER (WHERE cr.is_late = TRUE)        AS late_count,
                        COUNT(*) FILTER (WHERE cr.is_early_leave = TRUE)  AS early_leave_count
                    FROM clock_records cr
                    JOIN employees e
                           ON e.id = cr.employee_id
                          AND e.store_id = :store_id
                          AND e.tenant_id = cr.tenant_id
                          AND e.is_deleted = FALSE
                    WHERE cr.tenant_id = :tenant_id
                      AND EXTRACT(YEAR  FROM cr.clock_date) = :year
                      AND EXTRACT(MONTH FROM cr.clock_date) = :month
                      AND cr.is_deleted = FALSE
                    GROUP BY cr.employee_id
                """),
                {
                    "tenant_id": str(tenant_id),
                    "store_id": str(store_id),
                    "year": year,
                    "month": month,
                },
            )
            for row in late_rows.mappings().all():
                emp_key = str(row["employee_id"])
                if emp_key in base_map:
                    base_map[emp_key]["late_count"] = int(row["late_count"] or 0)
                    base_map[emp_key]["early_leave_count"] = int(row["early_leave_count"] or 0)
        except Exception:  # noqa: BLE001 — clock_records 表可能不存在或结构不同，安全降级到 0
            log.warning(
                "payroll.fetch_attendance_summary.clock_records_unavailable",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                year=year,
                month=month,
                exc_info=True,
            )

        # 确保所有记录都有 late_count / early_leave_count / sales_amount_fen 字段
        for att in base_map.values():
            att.setdefault("late_count", 0)
            att.setdefault("early_leave_count", 0)
            att.setdefault("sales_amount_fen", 0)

        return base_map

    async def _fetch_si_config(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        period_start: date,
    ) -> Optional[SocialInsuranceConfig]:
        """读取最新生效的社保配置（优先 DB，降级到内置默认值）"""
        row = await db.execute(
            text("""
                SELECT *
                FROM social_insurance_configs
                WHERE tenant_id = :tenant_id
                  AND effective_from <= :period_start
                  AND is_deleted = FALSE
                ORDER BY effective_from DESC
                LIMIT 1
            """),
            {"tenant_id": str(tenant_id), "period_start": period_start.isoformat()},
        )
        mapping = row.mappings().first()
        if not mapping:
            return None
        return SocialInsuranceConfig(
            region=mapping["region"],
            pension_rate_employee=float(mapping["pension_rate_employee"]),
            pension_rate_employer=float(mapping["pension_rate_employer"]),
            medical_rate_employee=float(mapping["medical_rate_employee"]),
            medical_rate_employer=float(mapping["medical_rate_employer"]),
            unemployment_rate_employee=float(mapping["unemployment_rate_employee"]),
            unemployment_rate_employer=float(mapping["unemployment_rate_employer"]),
            housing_fund_rate=float(mapping["housing_fund_rate"]),
        )

    async def _upsert_payroll_records(
        self,
        db: AsyncSession,
        records: List[PayrollRecord],
    ) -> None:
        """将计算结果写入 payroll_records_v2（有则更新草稿，无则插入）"""
        for rec in records:
            await db.execute(
                text("""
                    INSERT INTO payroll_records_v2 (
                        tenant_id, store_id, employee_id,
                        period_year, period_month,
                        work_days, work_hours, overtime_hours,
                        base_salary_fen, commission_fen, overtime_pay_fen,
                        bonus_fen, deductions_fen,
                        social_insurance_fen, housing_fund_fen,
                        gross_salary_fen, net_salary_fen,
                        status, updated_at
                    ) VALUES (
                        :tenant_id, :store_id, :employee_id,
                        :year, :month,
                        :work_days, :work_hours, :overtime_hours,
                        :base_salary_fen, :commission_fen, :overtime_pay_fen,
                        :bonus_fen, :deductions_fen,
                        :social_insurance_fen, :housing_fund_fen,
                        :gross_salary_fen, :net_salary_fen,
                        'draft', NOW()
                    )
                    ON CONFLICT (tenant_id, employee_id, period_year, period_month)
                    DO UPDATE SET
                        work_days          = EXCLUDED.work_days,
                        work_hours         = EXCLUDED.work_hours,
                        overtime_hours     = EXCLUDED.overtime_hours,
                        base_salary_fen    = EXCLUDED.base_salary_fen,
                        commission_fen     = EXCLUDED.commission_fen,
                        overtime_pay_fen   = EXCLUDED.overtime_pay_fen,
                        bonus_fen          = EXCLUDED.bonus_fen,
                        deductions_fen     = EXCLUDED.deductions_fen,
                        social_insurance_fen = EXCLUDED.social_insurance_fen,
                        housing_fund_fen   = EXCLUDED.housing_fund_fen,
                        gross_salary_fen   = EXCLUDED.gross_salary_fen,
                        net_salary_fen     = EXCLUDED.net_salary_fen,
                        updated_at         = NOW()
                    WHERE payroll_records_v2.status = 'draft'
                """),
                {
                    "tenant_id": str(rec.tenant_id),
                    "store_id": str(rec.store_id),
                    "employee_id": str(rec.employee_id),
                    "year": rec.period_year,
                    "month": rec.period_month,
                    "work_days": rec.work_days,
                    "work_hours": rec.work_hours,
                    "overtime_hours": rec.overtime_hours,
                    "base_salary_fen": rec.base_salary_fen,
                    "commission_fen": rec.commission_fen,
                    "overtime_pay_fen": rec.overtime_pay_fen,
                    "bonus_fen": rec.bonus_fen,
                    "deductions_fen": rec.deductions_fen,
                    "social_insurance_fen": rec.social_insurance_fen,
                    "housing_fund_fen": rec.housing_fund_fen,
                    "gross_salary_fen": rec.gross_salary_fen,
                    "net_salary_fen": rec.net_salary_fen,
                },
            )

    @staticmethod
    def _row_to_payroll_record(row: Any) -> PayrollRecord:
        """将 DB 行映射为 PayrollRecord 数据对象"""
        return PayrollRecord(
            id=UUID(str(row["id"])),
            tenant_id=UUID(str(row["tenant_id"])),
            store_id=UUID(str(row["store_id"])),
            employee_id=UUID(str(row["employee_id"])),
            period_year=int(row["period_year"]),
            period_month=int(row["period_month"]),
            work_days=int(row["work_days"]),
            work_hours=float(row["work_hours"]),
            overtime_hours=float(row["overtime_hours"]),
            base_salary_fen=int(row["base_salary_fen"]),
            commission_fen=int(row["commission_fen"]),
            overtime_pay_fen=int(row["overtime_pay_fen"]),
            bonus_fen=int(row["bonus_fen"]),
            deductions_fen=int(row["deductions_fen"]),
            social_insurance_fen=int(row["social_insurance_fen"]),
            housing_fund_fen=int(row["housing_fund_fen"]),
            gross_salary_fen=int(row["gross_salary_fen"]),
            net_salary_fen=int(row["net_salary_fen"]),
            status=row["status"],
            confirmed_at=row.get("confirmed_at"),
            paid_at=row.get("paid_at"),
        )


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _build_payslip_items(record: PayrollRecord) -> List[Dict[str, Any]]:
    """将薪资记录展开为工资条明细行列表（展示用）"""
    items: List[Dict[str, Any]] = []

    def _add(label: str, fen: int, is_deduction: bool = False) -> None:
        if fen != 0:
            items.append({
                "label": label,
                "amount_fen": fen,
                "amount_yuan": round(fen / 100, 2),
                "is_deduction": is_deduction,
            })

    _add("基本工资", record.base_salary_fen)
    _add("提成", record.commission_fen)
    _add("加班费", record.overtime_pay_fen)
    _add("奖金", record.bonus_fen)
    _add("考勤扣款", record.deductions_fen, is_deduction=True)
    _add("养老/医疗/失业险（个人）", record.social_insurance_fen, is_deduction=True)
    _add("住房公积金（个人）", record.housing_fund_fen, is_deduction=True)
    items.append({
        "label": "应发合计",
        "amount_fen": record.gross_salary_fen,
        "amount_yuan": round(record.gross_salary_fen / 100, 2),
        "is_deduction": False,
        "is_summary": True,
    })
    items.append({
        "label": "实发合计",
        "amount_fen": record.net_salary_fen,
        "amount_yuan": round(record.net_salary_fen / 100, 2),
        "is_deduction": False,
        "is_summary": True,
    })
    return items
