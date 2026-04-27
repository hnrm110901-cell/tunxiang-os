"""CFO驾驶舱 — 集团财务全貌

V1迁入 550行 + 新写合并报表。
所有金额单位：分（fen）。

功能矩阵：
1. 现金流量表 (Cash Flow Statement)
2. 多品牌合并报表 (Multi-brand Consolidation)
3. 税务总览 (Tax Overview)
4. 成本结构分析 (Cost Analytics)
5. 财务KPI (Financial KPIs)
6. 预算对比 (Budget vs Actual)
7. 财务预测 (Forecast)
8. 高管摘要 (Executive Summary)
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _fen_to_yuan(fen: int) -> float:
    return round(fen / 100, 2)


def _format_fen(fen: int) -> str:
    """格式化分为元字符串，带千分位。"""
    yuan = fen / 100
    if yuan >= 10000:
        return f"{yuan / 10000:.1f}万元"
    return f"{yuan:,.0f}元"


class CFODashboardService:
    """CFO驾驶舱 — 集团财务全貌

    现金流+税务+成本率+多品牌合并报表
    """

    # ══════════════════════════════════════════════════════════════
    # 1. Cash Flow — 现金流量表
    # ══════════════════════════════════════════════════════════════

    def get_cash_flow(
        self,
        brand_id: str,
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成现金流量表。

        Args:
            brand_id: 品牌ID
            period: 期间 (YYYY-MM 或 YYYY-Q1 等)
            data: 原始财务数据，包含:
                operating: {revenue, cogs, opex, tax_paid, working_capital_change}
                investing: {equipment_purchase, renovation, asset_disposal}
                financing: {loan_proceeds, loan_repayment, equity_injection, dividends}
                opening_cash: int (期初现金)

        Returns:
            完整现金流量表
        """
        if data is None:
            data = {}

        op = data.get("operating", {})
        inv = data.get("investing", {})
        fin = data.get("financing", {})
        opening_cash = data.get("opening_cash", 0)

        # 经营活动现金流
        op_revenue = op.get("revenue", 0)
        op_cogs = op.get("cogs", 0)
        op_opex = op.get("opex", 0)
        op_tax = op.get("tax_paid", 0)
        op_wc_change = op.get("working_capital_change", 0)
        operating_cf = op_revenue - op_cogs - op_opex - op_tax - op_wc_change

        # 投资活动现金流
        inv_equipment = inv.get("equipment_purchase", 0)
        inv_renovation = inv.get("renovation", 0)
        inv_disposal = inv.get("asset_disposal", 0)
        investing_cf = inv_disposal - inv_equipment - inv_renovation

        # 筹资活动现金流
        fin_loan_in = fin.get("loan_proceeds", 0)
        fin_loan_out = fin.get("loan_repayment", 0)
        fin_equity = fin.get("equity_injection", 0)
        fin_dividends = fin.get("dividends", 0)
        financing_cf = fin_loan_in - fin_loan_out + fin_equity - fin_dividends

        net_cash_change = operating_cf + investing_cf + financing_cf
        closing_cash = opening_cash + net_cash_change

        result = {
            "brand_id": brand_id,
            "period": period,
            "operating": {
                "revenue_collected": op_revenue,
                "cogs_paid": op_cogs,
                "opex_paid": op_opex,
                "tax_paid": op_tax,
                "working_capital_change": op_wc_change,
                "net_operating_cf": operating_cf,
            },
            "investing": {
                "equipment_purchase": inv_equipment,
                "renovation": inv_renovation,
                "asset_disposal": inv_disposal,
                "net_investing_cf": investing_cf,
            },
            "financing": {
                "loan_proceeds": fin_loan_in,
                "loan_repayment": fin_loan_out,
                "equity_injection": fin_equity,
                "dividends": fin_dividends,
                "net_financing_cf": financing_cf,
            },
            "summary": {
                "net_cash_change": net_cash_change,
                "opening_cash": opening_cash,
                "closing_cash": closing_cash,
            },
        }

        logger.info(
            "cash_flow_generated",
            brand_id=brand_id,
            period=period,
            net_cash_change=net_cash_change,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 2. Multi-brand Consolidation — 多品牌合并报表
    # ══════════════════════════════════════════════════════════════

    def consolidate_brands(
        self,
        brand_ids: list[str],
        period: str,
        brand_pnls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """多品牌合并报表。

        Args:
            brand_ids: 品牌ID列表
            period: 期间
            brand_pnls: 各品牌P&L数据列表，每项包含:
                brand_id, revenue{}, cogs{}, opex{}, other_expenses{},
                gross_profit, operating_profit, net_profit, kpi{},
                inter_brand_revenue (品牌间交易收入，需抵消)

        Returns:
            合并报表 + 品牌明细
        """
        if brand_pnls is None:
            brand_pnls = []

        if not brand_pnls:
            return {
                "consolidated": {},
                "brand_breakdown": [],
                "eliminations": {},
                "brand_count": 0,
                "period": period,
            }

        # 汇总各品牌
        total_revenue = sum(p.get("revenue", {}).get("total", 0) for p in brand_pnls)
        total_cogs = sum(p.get("cogs", {}).get("total", 0) for p in brand_pnls)
        total_opex = sum(p.get("opex", {}).get("total", 0) for p in brand_pnls)
        total_other = sum(p.get("other_expenses", {}).get("total", 0) for p in brand_pnls)

        # 品牌间交易抵消
        inter_brand_revenue = sum(p.get("inter_brand_revenue", 0) for p in brand_pnls)
        inter_brand_cogs = sum(p.get("inter_brand_cogs", 0) for p in brand_pnls)

        # 合并后数值
        consolidated_revenue = total_revenue - inter_brand_revenue
        consolidated_cogs = total_cogs - inter_brand_cogs
        consolidated_gross_profit = consolidated_revenue - consolidated_cogs
        consolidated_opex = total_opex
        consolidated_op_profit = consolidated_gross_profit - consolidated_opex
        consolidated_net_profit = consolidated_op_profit - total_other

        # 品牌明细
        brand_breakdown = []
        for pnl in brand_pnls:
            brand_rev = pnl.get("revenue", {}).get("total", 0)
            brand_np = pnl.get("net_profit", 0)
            brand_breakdown.append(
                {
                    "brand_id": pnl.get("brand_id", "unknown"),
                    "revenue": brand_rev,
                    "net_profit": brand_np,
                    "net_margin": _safe_ratio(brand_np, brand_rev),
                    "revenue_share": _safe_ratio(brand_rev, consolidated_revenue),
                    "store_count": pnl.get("store_count", 0),
                }
            )

        result = {
            "period": period,
            "brand_count": len(brand_ids),
            "consolidated": {
                "revenue": consolidated_revenue,
                "cogs": consolidated_cogs,
                "gross_profit": consolidated_gross_profit,
                "gross_margin": _safe_ratio(consolidated_gross_profit, consolidated_revenue),
                "opex": consolidated_opex,
                "operating_profit": consolidated_op_profit,
                "operating_margin": _safe_ratio(consolidated_op_profit, consolidated_revenue),
                "other_expenses": total_other,
                "net_profit": consolidated_net_profit,
                "net_margin": _safe_ratio(consolidated_net_profit, consolidated_revenue),
            },
            "eliminations": {
                "inter_brand_revenue": inter_brand_revenue,
                "inter_brand_cogs": inter_brand_cogs,
                "net_elimination": inter_brand_revenue - inter_brand_cogs,
            },
            "brand_breakdown": brand_breakdown,
        }

        logger.info(
            "brands_consolidated",
            brand_count=len(brand_ids),
            period=period,
            consolidated_revenue=consolidated_revenue,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 3. Tax Overview — 税务总览
    # ══════════════════════════════════════════════════════════════

    def get_tax_summary(
        self,
        brand_id: str,
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """税务总览。

        Args:
            brand_id: 品牌ID
            period: 期间
            data: 税务相关数据:
                revenue: int (含税收入)
                taxable_income: int (应纳税所得额)
                payroll_total: int (工资总额)
                property_value: int (房产原值)
                deductible_items: list[{name, amount}] (可抵扣项)

        Returns:
            税务汇总
        """
        if data is None:
            data = {}

        revenue = data.get("revenue", 0)
        taxable_income = data.get("taxable_income", 0)
        payroll_total = data.get("payroll_total", 0)
        property_value = data.get("property_value", 0)
        deductible_items = data.get("deductible_items", [])

        # 增值税 (餐饮业一般纳税人 6%)
        vat_rate = 0.06
        vat_output = int(revenue * vat_rate / (1 + vat_rate))  # 销项税
        vat_input = sum(item.get("amount", 0) for item in deductible_items if item.get("type") == "vat_input")
        vat_payable = max(0, vat_output - vat_input)

        # 企业所得税 (25%，小微企业可能更低)
        corp_tax_rate = 0.25
        total_deductions = sum(item.get("amount", 0) for item in deductible_items)
        adjusted_taxable = max(0, taxable_income - total_deductions)
        # 小微企业优惠：应纳税所得额 ≤ 300万按 5%
        if adjusted_taxable <= 300_0000_00:
            effective_corp_rate = 0.05
        else:
            effective_corp_rate = corp_tax_rate
        corp_tax = int(adjusted_taxable * effective_corp_rate)

        # 工资相关税费
        social_insurance_rate = 0.30  # 企业承担约 30%
        social_insurance = int(payroll_total * social_insurance_rate)

        # 房产税 (自用: 原值 * 70% * 1.2%)
        property_tax = int(property_value * 0.70 * 0.012)

        # 印花税 (购销合同 0.03%)
        stamp_tax = int(revenue * 0.0003)

        total_tax = vat_payable + corp_tax + social_insurance + property_tax + stamp_tax
        effective_tax_rate = _safe_ratio(total_tax, revenue)

        result = {
            "brand_id": brand_id,
            "period": period,
            "vat": {
                "rate": vat_rate,
                "output_tax": vat_output,
                "input_tax": vat_input,
                "payable": vat_payable,
            },
            "corporate_income_tax": {
                "statutory_rate": corp_tax_rate,
                "effective_rate": effective_corp_rate,
                "taxable_income": taxable_income,
                "deductions": total_deductions,
                "adjusted_taxable": adjusted_taxable,
                "tax_amount": corp_tax,
            },
            "payroll_taxes": {
                "payroll_total": payroll_total,
                "social_insurance_rate": social_insurance_rate,
                "social_insurance": social_insurance,
            },
            "property_tax": {
                "property_value": property_value,
                "tax_amount": property_tax,
            },
            "stamp_tax": stamp_tax,
            "total_tax": total_tax,
            "effective_tax_rate": effective_tax_rate,
            "deductible_items": deductible_items,
        }

        logger.info(
            "tax_summary_generated",
            brand_id=brand_id,
            period=period,
            total_tax=total_tax,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 4. Cost Analytics — 成本结构分析
    # ══════════════════════════════════════════════════════════════

    def get_cost_structure(
        self,
        brand_id: str,
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """成本结构分析。

        Args:
            brand_id: 品牌ID
            period: 期间
            data: 成本数据:
                revenue: int
                fixed_costs: {rent, depreciation, admin_salary, insurance}
                variable_costs: {food_cost, beverage_cost, hourly_labor,
                                 utilities, packaging, platform_commission}
                covers: int (客流量)
                store_count: int

        Returns:
            成本结构分析
        """
        if data is None:
            data = {}

        revenue = data.get("revenue", 0)
        fixed = data.get("fixed_costs", {})
        variable = data.get("variable_costs", {})
        covers = data.get("covers", 1)
        store_count = data.get("store_count", 1)

        # 固定成本
        rent = fixed.get("rent", 0)
        depreciation = fixed.get("depreciation", 0)
        admin_salary = fixed.get("admin_salary", 0)
        insurance = fixed.get("insurance", 0)
        total_fixed = rent + depreciation + admin_salary + insurance

        # 变动成本
        food_cost = variable.get("food_cost", 0)
        beverage_cost = variable.get("beverage_cost", 0)
        hourly_labor = variable.get("hourly_labor", 0)
        utilities = variable.get("utilities", 0)
        packaging = variable.get("packaging", 0)
        platform_commission = variable.get("platform_commission", 0)
        total_variable = food_cost + beverage_cost + hourly_labor + utilities + packaging + platform_commission

        total_cost = total_fixed + total_variable

        # 单位成本
        cost_per_cover = _safe_ratio(total_cost, covers)
        cost_per_store = _safe_ratio(total_cost, store_count)
        cost_per_revenue = _safe_ratio(total_cost, revenue)

        # 盈亏平衡点（收入）
        contribution_margin_ratio = _safe_ratio(revenue - total_variable, revenue)
        breakeven_revenue = int(total_fixed / contribution_margin_ratio) if contribution_margin_ratio > 0 else 0

        result = {
            "brand_id": brand_id,
            "period": period,
            "fixed_costs": {
                "rent": rent,
                "depreciation": depreciation,
                "admin_salary": admin_salary,
                "insurance": insurance,
                "total": total_fixed,
                "ratio": _safe_ratio(total_fixed, revenue),
            },
            "variable_costs": {
                "food_cost": food_cost,
                "beverage_cost": beverage_cost,
                "hourly_labor": hourly_labor,
                "utilities": utilities,
                "packaging": packaging,
                "platform_commission": platform_commission,
                "total": total_variable,
                "ratio": _safe_ratio(total_variable, revenue),
            },
            "total_cost": total_cost,
            "unit_costs": {
                "cost_per_cover": cost_per_cover,
                "cost_per_store": cost_per_store,
                "cost_per_revenue_unit": cost_per_revenue,
            },
            "breakeven": {
                "contribution_margin_ratio": contribution_margin_ratio,
                "breakeven_revenue": breakeven_revenue,
                "current_revenue": revenue,
                "safety_margin": _safe_ratio(revenue - breakeven_revenue, revenue),
            },
        }

        logger.info(
            "cost_structure_generated",
            brand_id=brand_id,
            period=period,
            total_cost=total_cost,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 5. Financial KPIs
    # ══════════════════════════════════════════════════════════════

    def get_financial_kpis(
        self,
        brand_id: str,
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """财务核心KPI。

        Args:
            brand_id: 品牌ID
            period: 期间
            data:
                revenue, cogs, opex, depreciation, amortization,
                interest_expense, tax_expense, net_profit,
                total_investment, opening_revenue (上期收入),
                same_store_revenue_current, same_store_revenue_prior,
                new_store_revenue,
                current_assets, current_liabilities,
                accounts_receivable, accounts_payable,
                daily_revenue (日均收入), daily_cogs (日均成本)

        Returns:
            Financial KPIs dictionary
        """
        if data is None:
            data = {}

        revenue = data.get("revenue", 0)
        cogs = data.get("cogs", 0)
        opex = data.get("opex", 0)
        depreciation = data.get("depreciation", 0)
        amortization = data.get("amortization", 0)
        interest = data.get("interest_expense", 0)
        tax = data.get("tax_expense", 0)
        net_profit = data.get("net_profit", 0)
        total_investment = data.get("total_investment", 1)

        # EBITDA
        operating_profit = revenue - cogs - opex
        ebitda = operating_profit + depreciation + amortization
        ebitda_margin = _safe_ratio(ebitda, revenue)

        # ROI & 回本周期
        annual_profit = net_profit  # 假设 period 为年，否则需年化
        roi = _safe_ratio(annual_profit, total_investment)
        payback_months = int(total_investment / (annual_profit / 12)) if annual_profit > 0 else 999

        # 同店增长
        ss_current = data.get("same_store_revenue_current", 0)
        ss_prior = data.get("same_store_revenue_prior", 0)
        same_store_growth = _safe_ratio(ss_current - ss_prior, ss_prior) if ss_prior else 0.0

        # 新店贡献
        new_store_rev = data.get("new_store_revenue", 0)
        new_store_contribution = _safe_ratio(new_store_rev, revenue)

        # 营运资金
        current_assets = data.get("current_assets", 0)
        current_liabilities = data.get("current_liabilities", 0)
        working_capital = current_assets - current_liabilities
        current_ratio = _safe_ratio(current_assets, current_liabilities)

        # 应收/应付天数
        ar = data.get("accounts_receivable", 0)
        ap = data.get("accounts_payable", 0)
        daily_revenue = data.get("daily_revenue", 0)
        daily_cogs = data.get("daily_cogs", 0)
        ar_days = int(ar / daily_revenue) if daily_revenue > 0 else 0
        ap_days = int(ap / daily_cogs) if daily_cogs > 0 else 0

        result = {
            "brand_id": brand_id,
            "period": period,
            "profitability": {
                "ebitda": ebitda,
                "ebitda_margin": ebitda_margin,
                "operating_profit": operating_profit,
                "operating_margin": _safe_ratio(operating_profit, revenue),
                "net_profit": net_profit,
                "net_margin": _safe_ratio(net_profit, revenue),
            },
            "returns": {
                "roi": roi,
                "total_investment": total_investment,
                "payback_months": payback_months,
            },
            "growth": {
                "same_store_growth": same_store_growth,
                "new_store_contribution": new_store_contribution,
                "new_store_revenue": new_store_rev,
            },
            "liquidity": {
                "working_capital": working_capital,
                "current_ratio": current_ratio,
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
            },
            "efficiency": {
                "accounts_receivable_days": ar_days,
                "accounts_payable_days": ap_days,
                "cash_conversion_cycle": ar_days - ap_days,
            },
        }

        logger.info(
            "financial_kpis_generated",
            brand_id=brand_id,
            ebitda=ebitda,
            roi=roi,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 6. Budget vs Actual — 预算对比
    # ══════════════════════════════════════════════════════════════

    def compare_budget(
        self,
        brand_id: str,
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """预算 vs 实际对比分析。

        Args:
            brand_id: 品牌ID
            period: 期间
            data:
                budget: {revenue, cogs, labor, rent, marketing, utilities, net_profit}
                actual: {revenue, cogs, labor, rent, marketing, utilities, net_profit}

        Returns:
            逐项差异分析
        """
        if data is None:
            data = {}

        budget = data.get("budget", {})
        actual = data.get("actual", {})

        line_items = [
            "revenue",
            "cogs",
            "labor",
            "rent",
            "marketing",
            "utilities",
            "net_profit",
        ]

        variances: list[dict[str, Any]] = []
        for item in line_items:
            b_val = budget.get(item, 0)
            a_val = actual.get(item, 0)
            diff = a_val - b_val
            pct = _safe_ratio(diff, b_val) if b_val else 0.0

            # 收入项：实际 > 预算为 favorable
            # 成本项：实际 < 预算为 favorable
            if item in ("revenue", "net_profit"):
                status = "favorable" if diff >= 0 else "unfavorable"
            else:
                status = "favorable" if diff <= 0 else "unfavorable"

            variances.append(
                {
                    "item": item,
                    "budget": b_val,
                    "actual": a_val,
                    "variance": diff,
                    "variance_pct": pct,
                    "status": status,
                }
            )

        # 总体评估
        rev_var = actual.get("revenue", 0) - budget.get("revenue", 0)
        np_var = actual.get("net_profit", 0) - budget.get("net_profit", 0)
        if rev_var >= 0 and np_var >= 0:
            overall = "超额完成"
        elif rev_var >= 0 and np_var < 0:
            overall = "增收不增利"
        elif rev_var < 0 and np_var >= 0:
            overall = "降本增效"
        else:
            overall = "未达预期"

        result = {
            "brand_id": brand_id,
            "period": period,
            "variances": variances,
            "overall_assessment": overall,
            "revenue_achievement": _safe_ratio(actual.get("revenue", 0), budget.get("revenue", 1)),
            "profit_achievement": _safe_ratio(actual.get("net_profit", 0), budget.get("net_profit", 1)),
        }

        logger.info(
            "budget_comparison_generated",
            brand_id=brand_id,
            overall=overall,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 7. Forecast — 财务预测
    # ══════════════════════════════════════════════════════════════

    def generate_forecast(
        self,
        brand_id: str,
        months_ahead: int = 3,
        historical_data: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """基于趋势生成财务预测。

        Args:
            brand_id: 品牌ID
            months_ahead: 预测月数
            historical_data: 历史月度数据列表:
                [{month, revenue, cogs, opex, net_profit}, ...]

        Returns:
            预测结果
        """
        if historical_data is None:
            historical_data = []

        if len(historical_data) < 2:
            return {
                "brand_id": brand_id,
                "months_ahead": months_ahead,
                "error": "需要至少2个月的历史数据",
                "forecasts": [],
            }

        # 计算增长趋势（简单线性回归 — 取最近数据的平均增长率）
        metrics = ["revenue", "cogs", "opex", "net_profit"]
        growth_rates: dict[str, float] = {}

        for metric in metrics:
            values = [d.get(metric, 0) for d in historical_data]
            if len(values) >= 2:
                rates = []
                for i in range(1, len(values)):
                    if values[i - 1] != 0:
                        rates.append((values[i] - values[i - 1]) / abs(values[i - 1]))
                growth_rates[metric] = sum(rates) / len(rates) if rates else 0.0
            else:
                growth_rates[metric] = 0.0

        # 生成预测
        last = historical_data[-1]
        last_month = last.get("month", "2026-03")
        forecasts: list[dict[str, Any]] = []

        for i in range(1, months_ahead + 1):
            # 简单月份递增
            year, month = last_month.split("-")
            new_month = int(month) + i
            new_year = int(year) + (new_month - 1) // 12
            new_month = ((new_month - 1) % 12) + 1
            forecast_month = f"{new_year}-{new_month:02d}"

            forecast_entry: dict[str, Any] = {"month": forecast_month}
            for metric in metrics:
                base_value = last.get(metric, 0)
                growth = growth_rates.get(metric, 0)
                projected = int(base_value * (1 + growth) ** i)
                forecast_entry[metric] = projected

            # 预测毛利率
            f_rev = forecast_entry.get("revenue", 0)
            f_cogs = forecast_entry.get("cogs", 0)
            forecast_entry["gross_margin"] = _safe_ratio(f_rev - f_cogs, f_rev)
            forecast_entry["net_margin"] = _safe_ratio(forecast_entry.get("net_profit", 0), f_rev)

            forecasts.append(forecast_entry)

        result = {
            "brand_id": brand_id,
            "months_ahead": months_ahead,
            "growth_rates": growth_rates,
            "base_month": last_month,
            "forecasts": forecasts,
            "method": "linear_trend",
            "confidence": "medium" if len(historical_data) >= 6 else "low",
        }

        logger.info(
            "forecast_generated",
            brand_id=brand_id,
            months_ahead=months_ahead,
        )
        return result

    # ══════════════════════════════════════════════════════════════
    # 8. Executive Summary — 高管摘要
    # ══════════════════════════════════════════════════════════════

    def generate_executive_summary(
        self,
        brand_ids: list[str],
        period: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """为董事会自动生成一页摘要。

        Args:
            brand_ids: 品牌ID列表
            period: 期间
            data: 汇总数据:
                consolidated_revenue, consolidated_net_profit,
                yoy_revenue_growth, yoy_profit_growth,
                store_count, new_stores, closed_stores,
                same_store_growth, top_brand, bottom_brand,
                cash_position, debt_total,
                alerts: list[str],
                achievements: list[str]

        Returns:
            结构化高管摘要
        """
        if data is None:
            data = {}

        revenue = data.get("consolidated_revenue", 0)
        net_profit = data.get("consolidated_net_profit", 0)
        yoy_rev = data.get("yoy_revenue_growth", 0)
        yoy_profit = data.get("yoy_profit_growth", 0)
        store_count = data.get("store_count", 0)
        new_stores = data.get("new_stores", 0)
        closed_stores = data.get("closed_stores", 0)
        ss_growth = data.get("same_store_growth", 0)
        top_brand = data.get("top_brand", {})
        bottom_brand = data.get("bottom_brand", {})
        cash = data.get("cash_position", 0)
        debt = data.get("debt_total", 0)
        alerts = data.get("alerts", [])
        achievements = data.get("achievements", [])

        # 生成自然语言摘要
        net_margin = _safe_ratio(net_profit, revenue)

        headline = self._generate_headline(revenue, yoy_rev, net_margin)

        # 关键指标卡片
        key_metrics = {
            "revenue": {
                "value": revenue,
                "display": _format_fen(revenue),
                "yoy_growth": yoy_rev,
                "trend": "up" if yoy_rev > 0 else "down" if yoy_rev < 0 else "flat",
            },
            "net_profit": {
                "value": net_profit,
                "display": _format_fen(net_profit),
                "yoy_growth": yoy_profit,
                "margin": net_margin,
            },
            "stores": {
                "total": store_count,
                "new": new_stores,
                "closed": closed_stores,
                "net_change": new_stores - closed_stores,
            },
            "same_store_growth": ss_growth,
            "cash_position": {
                "cash": cash,
                "debt": debt,
                "net_cash": cash - debt,
                "display": _format_fen(cash - debt),
            },
        }

        # 建议
        recommendations = self._generate_recommendations(net_margin, ss_growth, yoy_rev, alerts)

        result = {
            "period": period,
            "brand_count": len(brand_ids),
            "headline": headline,
            "key_metrics": key_metrics,
            "top_performer": top_brand,
            "needs_attention": bottom_brand,
            "alerts": alerts,
            "achievements": achievements,
            "recommendations": recommendations,
            "generated_by": "CFO Dashboard AI",
        }

        logger.info(
            "executive_summary_generated",
            period=period,
            brand_count=len(brand_ids),
        )
        return result

    def _generate_headline(self, revenue: int, yoy_growth: float, net_margin: float) -> str:
        """生成摘要标题。"""
        rev_str = _format_fen(revenue)

        if yoy_growth > 0.10:
            trend = f"强劲增长{int(yoy_growth * 100)}%"
        elif yoy_growth > 0:
            trend = f"稳步增长{int(yoy_growth * 100)}%"
        elif yoy_growth == 0:
            trend = "持平"
        elif yoy_growth > -0.10:
            trend = f"小幅下降{int(abs(yoy_growth) * 100)}%"
        else:
            trend = f"显著下降{int(abs(yoy_growth) * 100)}%"

        margin_str = f"净利率{net_margin:.1%}"

        return f"集团营收{rev_str}，同比{trend}，{margin_str}"

    def _generate_recommendations(
        self,
        net_margin: float,
        ss_growth: float,
        yoy_rev: float,
        alerts: list[str],
    ) -> list[str]:
        """生成经营建议。"""
        recs: list[str] = []

        if net_margin < 0.05:
            recs.append("净利率低于5%，建议审查高成本门店并优化食材采购策略")

        if net_margin < 0:
            recs.append("集团整体亏损，建议立即启动成本削减计划")

        if ss_growth < 0:
            recs.append("同店增长为负，建议加强菜单创新和会员运营")

        if ss_growth > 0.15:
            recs.append("同店增长强劲，可考虑加速开店计划")

        if yoy_rev < -0.05:
            recs.append("营收同比下降超5%，建议检查市场策略和竞争环境")

        if len(alerts) > 3:
            recs.append("多项指标异常，建议召开专题分析会")

        if not recs:
            recs.append("各项指标健康，建议保持当前经营策略")

        return recs
