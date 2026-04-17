"""
D12 合规 — 个人所得税累计预扣法计算引擎
------------------------------------------------
依据《国家税务总局 2018 第61号公告》，工资薪金所得按"累计预扣预缴法"计算：

    累计应纳税所得额 = 累计收入 - 累计免税收入
                     - 累计减除费用(5000 × 在职月数)
                     - 累计社保公积金个人
                     - 累计专项附加扣除
    累计应纳税额     = 累计应纳税所得额 × 税率 - 速算扣除数
    本月应扣税额     = 累计应纳税额 - 截至上月累计已预扣税额

注意:
  - 数据库统一存分(int)；税率表按"元"维护，便于与国税局表对齐。
  - 中途入职：以当前年度内首次出现的 PersonalTaxRecord 月数为准（累计月份 = 本月纳税次数）。

"7 级超额累进预扣率表"（年度累计应纳税所得额，元）：
    [0, 36000]        3%    速扣 0
    (36000, 144000]   10%   速扣 2520
    (144000, 300000]  20%   速扣 16920
    (300000, 420000]  25%   速扣 31920
    (420000, 660000]  30%   速扣 52920
    (660000, 960000]  35%   速扣 85920
    > 960000          45%   速扣 181920
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tax import PersonalTaxRecord, SpecialAdditionalDeduction
from src.services.base_service import BaseService

logger = structlog.get_logger()


# ── 税率表（元）─ (upper_yuan, rate, quick_deduction_yuan) ───────
TAX_BRACKETS_YUAN: List[Tuple[float, float, int]] = [
    (36000, 0.03, 0),
    (144000, 0.10, 2520),
    (300000, 0.20, 16920),
    (420000, 0.25, 31920),
    (660000, 0.30, 52920),
    (960000, 0.35, 85920),
    (float("inf"), 0.45, 181920),
]

# 基本减除费用（月度 / 元）
MONTHLY_BASIC_DEDUCTION_YUAN = 5000
MONTHLY_BASIC_DEDUCTION_FEN = 500000


def compute_cumulative_tax_fen(
    cumulative_taxable_fen: int,
) -> Tuple[int, float, int]:
    """
    根据累计应纳税所得额（分），返回 (累计应纳税额分, 税率, 速算扣除数分)。
    """
    if cumulative_taxable_fen <= 0:
        return (0, 0.0, 0)
    taxable_yuan = cumulative_taxable_fen / 100
    for upper_yuan, rate, quick_yuan in TAX_BRACKETS_YUAN:
        if taxable_yuan <= upper_yuan:
            tax_yuan = taxable_yuan * rate - quick_yuan
            if tax_yuan < 0:
                tax_yuan = 0
            return (int(round(tax_yuan * 100)), rate, quick_yuan * 100)
    # 不应到达
    rate = 0.45
    quick_yuan = 181920
    tax_yuan = max(0.0, taxable_yuan * rate - quick_yuan)
    return (int(round(tax_yuan * 100)), rate, quick_yuan * 100)


class PersonalTaxService(BaseService):
    """个税累计预扣计算服务"""

    async def calc_monthly_tax(
        self,
        db: AsyncSession,
        employee_id: str,
        pay_month: str,
        gross_fen: int,
        si_personal_fen: int,
        tax_free_income_fen: int = 0,
    ) -> Dict[str, Any]:
        """
        计算员工单月个税，并写入 PersonalTaxRecord。

        Args:
            employee_id:           员工ID
            pay_month:             YYYY-MM
            gross_fen:             本月应税收入（应发 - 免税 - 罚款等，调用方负责预处理）
            si_personal_fen:       本月社保+公积金个人缴纳合计（分）
            tax_free_income_fen:   本月免税收入（分），默认为0

        Returns:
            dict 计算明细，含 current_month_tax_fen / cumulative_* 等字段。
        """
        year = int(pay_month[:4])
        month = int(pay_month[5:7])
        store_id = self.store_id or ""

        # 1) 当月专项附加扣除（据员工生效期过滤）
        monthly_special_fen = await self._get_monthly_special_deduction(
            db, employee_id, pay_month
        )

        # 2) 拉取历史累计记录（同一纳税年度、当月之前）
        prev_records = await self._get_prev_year_records(db, employee_id, year, month)

        prev_cumulative_income_fen = 0
        prev_cumulative_tax_free_fen = 0
        prev_cumulative_basic_deduction_fen = 0
        prev_cumulative_si_fen = 0
        prev_cumulative_special_fen = 0
        prev_cumulative_tax_fen = 0
        prev_month_num = 0

        if prev_records:
            last = prev_records[-1]  # 按 tax_month_num 升序，最后一条 = 上月
            prev_cumulative_income_fen = last.cumulative_income_fen
            prev_cumulative_tax_free_fen = last.cumulative_tax_free_income_fen
            prev_cumulative_basic_deduction_fen = last.cumulative_basic_deduction_fen
            prev_cumulative_si_fen = last.cumulative_si_deduction_fen
            prev_cumulative_special_fen = last.cumulative_special_deduction_fen
            prev_cumulative_tax_fen = last.cumulative_tax_fen
            prev_month_num = last.tax_month_num

        # 3) 本月纳税次数 = 历史次数 + 1（处理中途入职）
        current_month_num = prev_month_num + 1

        # 4) 累计字段
        cumulative_income_fen = prev_cumulative_income_fen + max(0, gross_fen)
        cumulative_tax_free_fen = prev_cumulative_tax_free_fen + max(
            0, tax_free_income_fen
        )
        cumulative_basic_deduction_fen = (
            prev_cumulative_basic_deduction_fen + MONTHLY_BASIC_DEDUCTION_FEN
        )
        cumulative_si_fen = prev_cumulative_si_fen + max(0, si_personal_fen)
        cumulative_special_fen = prev_cumulative_special_fen + max(0, monthly_special_fen)

        cumulative_taxable_fen = max(
            0,
            cumulative_income_fen
            - cumulative_tax_free_fen
            - cumulative_basic_deduction_fen
            - cumulative_si_fen
            - cumulative_special_fen,
        )

        cumulative_tax_fen, rate, quick_fen = compute_cumulative_tax_fen(
            cumulative_taxable_fen
        )

        current_month_tax_fen = max(0, cumulative_tax_fen - prev_cumulative_tax_fen)

        # 5) upsert PersonalTaxRecord
        existing = await db.execute(
            select(PersonalTaxRecord).where(
                and_(
                    PersonalTaxRecord.employee_id == employee_id,
                    PersonalTaxRecord.tax_year == year,
                    PersonalTaxRecord.tax_month_num == current_month_num,
                )
            )
        )
        record = existing.scalar_one_or_none()
        if not record:
            record = PersonalTaxRecord(
                store_id=store_id,
                employee_id=employee_id,
                tax_year=year,
                tax_month_num=current_month_num,
                pay_month=pay_month,
            )
            db.add(record)

        record.pay_month = pay_month
        record.monthly_income_fen = max(0, gross_fen)
        record.monthly_tax_free_income_fen = max(0, tax_free_income_fen)
        record.monthly_si_personal_fen = max(0, si_personal_fen)
        record.monthly_special_deduction_fen = max(0, monthly_special_fen)

        record.cumulative_income_fen = cumulative_income_fen
        record.cumulative_tax_free_income_fen = cumulative_tax_free_fen
        record.cumulative_basic_deduction_fen = cumulative_basic_deduction_fen
        record.cumulative_si_deduction_fen = cumulative_si_fen
        record.cumulative_special_deduction_fen = cumulative_special_fen
        record.cumulative_taxable_income_fen = cumulative_taxable_fen
        record.cumulative_tax_fen = cumulative_tax_fen
        record.cumulative_prepaid_tax_fen = prev_cumulative_tax_fen
        record.current_month_tax_fen = current_month_tax_fen

        record.tax_rate_pct = Decimal(str(rate * 100))
        record.quick_deduction_fen = int(quick_fen)

        record.calculation_detail = {
            "pay_month": pay_month,
            "tax_year": year,
            "tax_month_num": current_month_num,
            "monthly_income_yuan": round(max(0, gross_fen) / 100, 2),
            "monthly_si_personal_yuan": round(max(0, si_personal_fen) / 100, 2),
            "monthly_special_deduction_yuan": round(max(0, monthly_special_fen) / 100, 2),
            "cumulative_taxable_yuan": round(cumulative_taxable_fen / 100, 2),
            "cumulative_tax_yuan": round(cumulative_tax_fen / 100, 2),
            "prev_cumulative_tax_yuan": round(prev_cumulative_tax_fen / 100, 2),
            "current_month_tax_yuan": round(current_month_tax_fen / 100, 2),
            "rate": rate,
            "quick_deduction_yuan": round(quick_fen / 100, 2),
            "calculated_at": datetime.utcnow().isoformat(),
        }

        await db.flush()

        return {
            "employee_id": employee_id,
            "pay_month": pay_month,
            "tax_year": year,
            "tax_month_num": current_month_num,
            "current_month_tax_fen": current_month_tax_fen,
            "current_month_tax_yuan": round(current_month_tax_fen / 100, 2),
            "cumulative_tax_fen": cumulative_tax_fen,
            "cumulative_taxable_income_fen": cumulative_taxable_fen,
            "rate": rate,
            "quick_deduction_fen": int(quick_fen),
        }

    # ── 专项附加扣除 ─────────────────────────────────────────
    async def _get_monthly_special_deduction(
        self,
        db: AsyncSession,
        employee_id: str,
        pay_month: str,
    ) -> int:
        """
        汇总员工当月所有生效的专项附加扣除（分）。
        生效条件: effective_month <= pay_month AND (expire_month IS NULL OR expire_month >= pay_month)
        """
        stmt = select(
            func.coalesce(func.sum(SpecialAdditionalDeduction.monthly_amount_fen), 0)
        ).where(
            and_(
                SpecialAdditionalDeduction.employee_id == employee_id,
                SpecialAdditionalDeduction.is_active.is_(True),
                SpecialAdditionalDeduction.effective_month <= pay_month,
            )
        )
        # expire_month 可能为 null（长期）或 >= pay_month
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                SpecialAdditionalDeduction.expire_month.is_(None),
                SpecialAdditionalDeduction.expire_month >= pay_month,
            )
        )
        result = await db.execute(stmt)
        return int(result.scalar() or 0)

    async def _get_prev_year_records(
        self,
        db: AsyncSession,
        employee_id: str,
        year: int,
        month: int,
    ) -> List[PersonalTaxRecord]:
        """查年度内当月之前的税表（按税务月份升序）"""
        stmt = (
            select(PersonalTaxRecord)
            .where(
                and_(
                    PersonalTaxRecord.employee_id == employee_id,
                    PersonalTaxRecord.tax_year == year,
                    PersonalTaxRecord.pay_month < f"{year}-{month:02d}",
                )
            )
            .order_by(PersonalTaxRecord.tax_month_num.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
