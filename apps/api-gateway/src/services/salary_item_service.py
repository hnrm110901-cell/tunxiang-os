"""
薪资项目服务 — D12 z66 移植自 tunxiang-os tx-org.salary_item_library

核心能力：
  1. 薪资项目库管理（创建/列表/按分类查询）
  2. 员工薪资项目分配（带生效时间窗）
  3. compute_employee_payroll_v3 — 按 tax_attribute 分类聚合单员工月度薪资
     · 应税收入（pre_tax_add 合计）
     · 免税收入（non_tax 合计）
     · 税前扣除（pre_tax_deduct 合计）
     · 税后扣除（after_tax_deduct 合计）
  4. 与 PersonalTaxService/SocialInsuranceService 集成

金额统一以分（fen）存储，对外字段同时提供 _yuan 伴生。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.salary_item import (
    TAX_ATTRIBUTES,
    EmployeeSalaryItem,
    PayslipLine,
    SalaryItemDefinition,
)
from src.services.base_service import BaseService

logger = structlog.get_logger(__name__)


def _fen_to_yuan(fen: int) -> float:
    """分转元（保留2位）"""
    return round((fen or 0) / 100.0, 2)


class SalaryItemService(BaseService):
    """薪资项目库 + 员工薪酬计算 V3"""

    # ────────────────────────────────────────────────────
    # 1) 薪资项目库管理
    # ────────────────────────────────────────────────────

    async def create_salary_item(
        self,
        db: AsyncSession,
        *,
        code: str,
        name: str,
        category: str,
        tax_attribute: str,
        brand_id: str,
        store_id: Optional[str] = None,
        formula: Optional[str] = None,
        formula_type: str = "fixed",
        calc_order: int = 50,
        remark: Optional[str] = None,
    ) -> SalaryItemDefinition:
        """创建薪资项目定义。"""
        if tax_attribute not in TAX_ATTRIBUTES:
            raise ValueError(
                f"invalid tax_attribute={tax_attribute}, must be one of {TAX_ATTRIBUTES}"
            )
        item = SalaryItemDefinition(
            id=uuid.uuid4(),
            brand_id=brand_id,
            store_id=store_id,
            item_code=code,
            item_name=name,
            item_category=category,
            tax_attribute=tax_attribute,
            calc_order=calc_order,
            formula=formula or "",
            formula_type=formula_type,
            remark=remark,
            is_active=True,
        )
        db.add(item)
        await db.flush()
        logger.info("salary_item_created", code=code, name=name)
        return item

    async def list_salary_items(
        self,
        db: AsyncSession,
        *,
        brand_id: str,
        category: Optional[str] = None,
        only_active: bool = True,
    ) -> List[SalaryItemDefinition]:
        """列出品牌下薪资项目（可按分类过滤）。"""
        sql = "SELECT id FROM salary_item_definitions WHERE brand_id = :brand_id"
        params: Dict[str, Any] = {"brand_id": brand_id}
        if only_active:
            sql += " AND is_active = TRUE"
        if category:
            sql += " AND item_category = :category"
            params["category"] = category
        sql += " ORDER BY calc_order ASC, item_code ASC"

        res = await db.execute(text(sql), params)
        ids = [row[0] for row in res.fetchall()]
        if not ids:
            return []
        # 二次 ORM 查询（列表接口可容忍）
        from sqlalchemy import select
        q = select(SalaryItemDefinition).where(SalaryItemDefinition.id.in_(ids))
        return list((await db.execute(q)).scalars().all())

    async def get_item_by_code(
        self, db: AsyncSession, brand_id: str, code: str
    ) -> Optional[SalaryItemDefinition]:
        from sqlalchemy import select
        q = select(SalaryItemDefinition).where(
            and_(
                SalaryItemDefinition.brand_id == brand_id,
                SalaryItemDefinition.item_code == code,
            )
        )
        return (await db.execute(q)).scalar_one_or_none()

    # ────────────────────────────────────────────────────
    # 2) 员工分配
    # ────────────────────────────────────────────────────

    async def assign_to_employee(
        self,
        db: AsyncSession,
        *,
        employee_id: str,
        brand_id: str,
        item_code: str,
        amount_fen: Optional[int] = None,
        effective_from: Optional[date] = None,
        effective_to: Optional[date] = None,
        remark: Optional[str] = None,
    ) -> EmployeeSalaryItem:
        """为员工分配某个薪资项目（按生效时间窗）。"""
        item = await self.get_item_by_code(db, brand_id, item_code)
        if not item:
            raise ValueError(f"salary_item not found: brand={brand_id}, code={item_code}")

        link = EmployeeSalaryItem(
            id=uuid.uuid4(),
            employee_id=employee_id,
            salary_item_id=item.id,
            amount_fen=amount_fen,
            effective_from=effective_from or date.today(),
            effective_to=effective_to,
            remark=remark,
        )
        db.add(link)
        await db.flush()
        logger.info(
            "salary_item_assigned",
            employee_id=employee_id,
            item_code=item_code,
            amount_fen=amount_fen,
        )
        return link

    async def _get_active_items_for_employee(
        self,
        db: AsyncSession,
        employee_id: str,
        pay_month: str,
    ) -> List[Dict[str, Any]]:
        """获取员工在指定月份生效的所有薪资项目 + 项目定义。"""
        # 月末作为生效判定日（含当月最后一天）
        year = int(pay_month[:4])
        month = int(pay_month[5:7])
        from calendar import monthrange
        last_day = date(year, month, monthrange(year, month)[1])

        sql = text(
            """
            SELECT esi.id, esi.amount_fen,
                   d.id AS def_id, d.item_code, d.item_name, d.item_category,
                   d.tax_attribute, d.formula, d.formula_type, d.calc_order
            FROM employee_salary_items esi
            JOIN salary_item_definitions d ON d.id = esi.salary_item_id
            WHERE esi.employee_id = :emp
              AND esi.effective_from <= :cutoff
              AND (esi.effective_to IS NULL OR esi.effective_to >= :cutoff)
              AND d.is_active = TRUE
            ORDER BY d.calc_order ASC, d.item_code ASC
            """
        )
        res = await db.execute(sql, {"emp": employee_id, "cutoff": last_day})
        rows = res.fetchall()
        return [
            {
                "assign_id": r[0],
                "override_amount_fen": r[1],
                "def_id": r[2],
                "code": r[3],
                "name": r[4],
                "category": r[5],
                "tax_attribute": r[6] or "pre_tax_add",
                "formula": r[7] or "",
                "formula_type": r[8] or "fixed",
                "calc_order": r[9] or 50,
            }
            for r in rows
        ]

    # ────────────────────────────────────────────────────
    # 3) 核心：payroll_engine_v3 单员工试算
    # ────────────────────────────────────────────────────

    async def compute_employee_payroll_v3(
        self,
        db: AsyncSession,
        *,
        employee_id: str,
        pay_month: str,
        context: Optional[Dict[str, Any]] = None,
        persist: bool = False,
        payroll_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        按员工所有生效 SalaryItem 计算月度薪资。

        Args:
            employee_id:  员工ID
            pay_month:    YYYY-MM
            context:      计算上下文（base_salary_fen、attendance_days、work_days_in_month 等）
                          — 供 formula_type='formula' 的项目引用
            persist:      True 时写入 payslip_lines
            payroll_id:   关联的 payroll_records.id（可选）

        Returns:
            {
              "lines": [...],                 # 每条工资条明细
              "totals_fen": {                 # 按 tax_attribute 聚合
                  "pre_tax_add": int,         # 应税收入合计（不含非税）
                  "non_tax": int,             # 免税收入
                  "pre_tax_deduct": int,      # 税前扣除（社保公积金个人）
                  "after_tax_add": int,       # 税后加项
                  "after_tax_deduct": int,    # 税后扣除
              },
              "totals_yuan": {...},           # 同上，单位元
              "gross_fen": int,               # 应发合计 = pre_tax_add + non_tax + after_tax_add
              "taxable_base_fen": int,        # 应税基数 = pre_tax_add - pre_tax_deduct
                                              # （传入 PersonalTaxService.gross_fen）
              "tax_free_income_fen": int,     # = non_tax
              "si_personal_fen": int,         # = pre_tax_deduct（传入 si_personal_fen）
            }
        """
        ctx = dict(context or {})
        items = await self._get_active_items_for_employee(db, employee_id, pay_month)

        lines: List[Dict[str, Any]] = []
        totals = {k: 0 for k in TAX_ATTRIBUTES}

        store_id = self.store_id or ctx.get("store_id") or ""

        for it in items:
            amount_fen = self._resolve_amount(it, ctx)
            lines.append(
                {
                    "salary_item_id": str(it["def_id"]),
                    "item_code": it["code"],
                    "item_name": it["name"],
                    "item_category": it["category"],
                    "tax_attribute": it["tax_attribute"],
                    "amount_fen": amount_fen,
                    "amount_yuan": _fen_to_yuan(amount_fen),
                    "calc_basis": {
                        "formula": it["formula"],
                        "formula_type": it["formula_type"],
                        "source": (
                            "override"
                            if it["override_amount_fen"] is not None
                            else it["formula_type"]
                        ),
                    },
                }
            )
            totals[it["tax_attribute"]] += amount_fen

            if persist:
                db.add(
                    PayslipLine(
                        id=uuid.uuid4(),
                        payroll_id=payroll_id,
                        store_id=store_id,
                        employee_id=employee_id,
                        pay_month=pay_month,
                        salary_item_id=it["def_id"],
                        item_code=it["code"],
                        item_name=it["name"],
                        item_category=it["category"],
                        tax_attribute=it["tax_attribute"],
                        amount_fen=amount_fen,
                        calc_basis=lines[-1]["calc_basis"],
                    )
                )

        if persist:
            await db.flush()

        gross_fen = (
            totals["pre_tax_add"] + totals["non_tax"] + totals["after_tax_add"]
        )
        taxable_base_fen = max(0, totals["pre_tax_add"] - totals["pre_tax_deduct"])

        return {
            "employee_id": employee_id,
            "pay_month": pay_month,
            "lines": lines,
            "totals_fen": totals,
            "totals_yuan": {k: _fen_to_yuan(v) for k, v in totals.items()},
            "gross_fen": gross_fen,
            "gross_yuan": _fen_to_yuan(gross_fen),
            "taxable_base_fen": taxable_base_fen,
            "taxable_base_yuan": _fen_to_yuan(taxable_base_fen),
            "tax_free_income_fen": totals["non_tax"],
            "tax_free_income_yuan": _fen_to_yuan(totals["non_tax"]),
            "si_personal_fen": totals["pre_tax_deduct"],
            "si_personal_yuan": _fen_to_yuan(totals["pre_tax_deduct"]),
        }

    # ────────────────────────────────────────────────────
    # 4) 公式解析（受限 eval）
    # ────────────────────────────────────────────────────

    _ALLOWED_CTX_KEYS = {
        "base_salary_fen",
        "attendance_days",
        "work_days_in_month",
        "social_base_fen",
        "housing_fund_base_fen",
        "housing_fund_rate",
        "overtime_hours",
        "hourly_rate_fen",
        "sales_amount_fen",
        "commission_rate",
        "late_count",
        "late_deduction_per_time_fen",
        "absent_days",
        "daily_rate_fen",
        "piece_count",
        "piece_rate_fen",
        "perf_coefficient",
        "seniority_months",
    }

    def _resolve_amount(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> int:
        """
        解析单项金额（分）。

        优先级：
          1. employee_salary_items.amount_fen（覆盖值）
          2. formula_type == 'formula' 时按 formula + ctx 求值
          3. formula_type == 'fixed' 时返回 0（需在 assign 时提供 amount_fen）
          4. formula_type == 'manual' 时需 ctx 通过 item_code 传入
        """
        override = item["override_amount_fen"]
        if override is not None:
            return int(override)

        code = item["code"]
        # 允许上下文直接按 item_code 传入金额（manual 录入）
        manual_key = f"item_{code}_fen"
        if manual_key in ctx:
            return int(ctx[manual_key] or 0)

        ftype = item["formula_type"]
        if ftype == "formula" and item["formula"]:
            safe_ctx = {k: ctx.get(k, 0) for k in self._ALLOWED_CTX_KEYS}
            # 特殊函数：工龄补贴阶梯
            safe_ctx["seniority_subsidy"] = self._seniority_subsidy
            try:
                # 公式只允许算术、内置函数 min/max
                val = eval(  # noqa: S307 — formula whitelisted via safe_ctx
                    item["formula"],
                    {"__builtins__": {}, "min": min, "max": max, "int": int, "float": float},
                    safe_ctx,
                )
                return max(0, int(val))
            except Exception as exc:
                logger.warning(
                    "formula_eval_failed",
                    code=code,
                    formula=item["formula"],
                    err=str(exc),
                )
                return 0
        return 0

    @staticmethod
    def _seniority_subsidy(seniority_months: int) -> int:
        """工龄补贴阶梯（分）：<12个月=0；12~35=100元；36~59=200元；60+=300元。"""
        m = int(seniority_months or 0)
        if m < 12:
            return 0
        if m < 36:
            return 10000
        if m < 60:
            return 20000
        return 30000
