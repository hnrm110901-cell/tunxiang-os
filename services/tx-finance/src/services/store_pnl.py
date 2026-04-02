"""门店 P&L 自动生成 — 每日/每周/每月利润表

基于长沙连锁餐饮行业真实数据结构设计。
所有金额单位：分（fen）。

P&L 结构：
  Revenue（营收）
  - COGS（食材成本）
  = Gross Profit（毛利）
  - Operating Expenses（运营费用）
  = Operating Profit（营业利润）
  - Other（其他：折旧、管理分摊）
  = Net Profit（净利润）

KPI:
  毛利率、营业利润率、净利率、人力成本占比、食材成本占比、RevPASH
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()

# ── 异常检测阈值 ──────────────────────────────────────────────
ANOMALY_THRESHOLDS = {
    "food_cost_ratio_max": 0.35,        # 食材成本占比 > 35% 告警
    "labor_cost_ratio_max": 0.30,        # 人力成本占比 > 30% 告警
    "net_margin_min": 0.05,              # 净利率 < 5% 告警
    "waste_ratio_max": 0.03,             # 损耗率 > 3% 告警
    "utility_ratio_max": 0.05,           # 水电气占比 > 5% 告警
}


def _safe_ratio(numerator: int, denominator: int) -> float:
    """安全计算比率，避免除零"""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


class StorePnLService:
    """门店 P&L 自动生成服务"""

    def generate_daily_pnl(self, store_id: str, biz_date: str, data: dict) -> dict:
        """生成每日利润表

        Args:
            store_id: 门店 ID
            biz_date: 营业日期 (YYYY-MM-DD)
            data: 原始数据，包含营收、成本、费用各项
                revenue: {dine_in, takeaway, delivery, banquet, other}
                cogs: {food_cost, beverage_cost, waste_spoilage}
                opex: {labor, rent, utilities, marketing, platform_commission,
                       payment_processing, supplies}
                other: {depreciation, admin_allocation}
                meta: {seats, operating_hours}  (用于 RevPASH)

        Returns:
            完整 P&L 报表
        """
        rev = data.get("revenue", {})
        cogs_data = data.get("cogs", {})
        opex = data.get("opex", {})
        other = data.get("other", {})
        meta = data.get("meta", {})

        # ── Revenue ──────────────────────────────────────────
        dine_in = rev.get("dine_in", 0)
        takeaway = rev.get("takeaway", 0)
        delivery = rev.get("delivery", 0)
        banquet = rev.get("banquet", 0)
        other_rev = rev.get("other", 0)
        total_revenue = dine_in + takeaway + delivery + banquet + other_rev

        # ── COGS ─────────────────────────────────────────────
        food_cost = cogs_data.get("food_cost", 0)
        beverage_cost = cogs_data.get("beverage_cost", 0)
        waste_spoilage = cogs_data.get("waste_spoilage", 0)
        total_cogs = food_cost + beverage_cost + waste_spoilage

        # ── Gross Profit ─────────────────────────────────────
        gross_profit = total_revenue - total_cogs

        # ── Operating Expenses ───────────────────────────────
        labor_cost = opex.get("labor", 0)
        rent = opex.get("rent", 0)
        utilities = opex.get("utilities", 0)
        marketing = opex.get("marketing", 0)
        platform_commission = opex.get("platform_commission", 0)
        payment_processing = opex.get("payment_processing", 0)
        supplies = opex.get("supplies", 0)
        total_opex = (
            labor_cost + rent + utilities + marketing
            + platform_commission + payment_processing + supplies
        )

        # ── Operating Profit ─────────────────────────────────
        operating_profit = gross_profit - total_opex

        # ── Other ────────────────────────────────────────────
        depreciation = other.get("depreciation", 0)
        admin_allocation = other.get("admin_allocation", 0)
        total_other = depreciation + admin_allocation

        # ── Net Profit ───────────────────────────────────────
        net_profit = operating_profit - total_other

        # ── KPIs ─────────────────────────────────────────────
        gross_margin = _safe_ratio(gross_profit, total_revenue)
        operating_margin = _safe_ratio(operating_profit, total_revenue)
        net_margin = _safe_ratio(net_profit, total_revenue)
        labor_cost_ratio = _safe_ratio(labor_cost, total_revenue)
        food_cost_ratio = _safe_ratio(food_cost + beverage_cost, total_revenue)
        waste_ratio = _safe_ratio(waste_spoilage, total_revenue)

        # RevPASH: Revenue per Available Seat Hour
        seats = meta.get("seats", 0)
        operating_hours = meta.get("operating_hours", 0)
        available_seat_hours = seats * operating_hours
        revpash = _safe_ratio(total_revenue, available_seat_hours) if available_seat_hours > 0 else 0

        pnl = {
            "store_id": store_id,
            "biz_date": biz_date,
            "period_type": "daily",
            "revenue": {
                "dine_in": dine_in,
                "takeaway": takeaway,
                "delivery": delivery,
                "banquet": banquet,
                "other": other_rev,
                "total": total_revenue,
            },
            "cogs": {
                "food_cost": food_cost,
                "beverage_cost": beverage_cost,
                "waste_spoilage": waste_spoilage,
                "total": total_cogs,
            },
            "gross_profit": gross_profit,
            "opex": {
                "labor": labor_cost,
                "rent": rent,
                "utilities": utilities,
                "marketing": marketing,
                "platform_commission": platform_commission,
                "payment_processing": payment_processing,
                "supplies": supplies,
                "total": total_opex,
            },
            "operating_profit": operating_profit,
            "other_expenses": {
                "depreciation": depreciation,
                "admin_allocation": admin_allocation,
                "total": total_other,
            },
            "net_profit": net_profit,
            "kpi": {
                "gross_margin": gross_margin,
                "operating_margin": operating_margin,
                "net_margin": net_margin,
                "labor_cost_ratio": labor_cost_ratio,
                "food_cost_ratio": food_cost_ratio,
                "waste_ratio": waste_ratio,
                "revpash": revpash,
            },
        }

        logger.info(
            "daily_pnl_generated",
            store_id=store_id,
            biz_date=biz_date,
            revenue=total_revenue,
            net_profit=net_profit,
            net_margin=net_margin,
        )

        return pnl

    def generate_weekly_pnl(
        self,
        store_id: str,
        week_start: str,
        daily_pnls: list[dict],
    ) -> dict:
        """合并每日 P&L 生成周报表

        Args:
            store_id: 门店 ID
            week_start: 周一日期 (YYYY-MM-DD)
            daily_pnls: 该周每日 P&L 列表（由 generate_daily_pnl 生成）

        Returns:
            周 P&L 报表
        """
        return self._aggregate_pnls(
            store_id=store_id,
            period_label=week_start,
            period_type="weekly",
            pnls=daily_pnls,
        )

    def generate_monthly_pnl(
        self,
        store_id: str,
        month: str,
        daily_pnls: list[dict],
    ) -> dict:
        """合并每日 P&L 生成月报表

        Args:
            store_id: 门店 ID
            month: 月份 (YYYY-MM)
            daily_pnls: 该月每日 P&L 列表

        Returns:
            月 P&L 报表
        """
        return self._aggregate_pnls(
            store_id=store_id,
            period_label=month,
            period_type="monthly",
            pnls=daily_pnls,
        )

    def compare_pnl(
        self,
        store_id: str,
        period_a: dict,
        period_b: dict,
    ) -> dict:
        """期间对比分析

        Args:
            store_id: 门店 ID
            period_a: A 期 P&L
            period_b: B 期 P&L

        Returns:
            差异分析
        """
        def _variance(key_path: str) -> dict:
            """按路径提取两期值并计算差异"""
            parts = key_path.split(".")
            val_a = period_a
            val_b = period_b
            for p in parts:
                val_a = val_a.get(p, 0) if isinstance(val_a, dict) else 0
                val_b = val_b.get(p, 0) if isinstance(val_b, dict) else 0
            change = val_b - val_a
            pct = round(change / val_a * 100, 1) if val_a else 0.0
            return {"period_a": val_a, "period_b": val_b, "change": change, "pct": pct}

        return {
            "store_id": store_id,
            "variance": {
                "total_revenue": _variance("revenue.total"),
                "total_cogs": _variance("cogs.total"),
                "gross_profit": _variance("gross_profit"),
                "total_opex": _variance("opex.total"),
                "operating_profit": _variance("operating_profit"),
                "net_profit": _variance("net_profit"),
                "food_cost_ratio": _variance("kpi.food_cost_ratio"),
                "labor_cost_ratio": _variance("kpi.labor_cost_ratio"),
                "net_margin": _variance("kpi.net_margin"),
            },
        }

    def get_multi_store_pnl(
        self,
        store_pnls: list[dict],
    ) -> dict:
        """多门店合并报表

        Args:
            store_pnls: 各门店 P&L 列表

        Returns:
            {consolidated: 合并P&L, per_store: 各门店明细}
        """
        if not store_pnls:
            return {"consolidated": {}, "per_store": []}

        consolidated = self._aggregate_pnls(
            store_id="ALL",
            period_label="consolidated",
            period_type="multi_store",
            pnls=store_pnls,
        )

        return {
            "consolidated": consolidated,
            "per_store": store_pnls,
            "store_count": len(store_pnls),
        }

    def detect_pnl_anomalies(self, pnl: dict) -> list[dict]:
        """检测 P&L 异常指标

        Args:
            pnl: 单期 P&L 报表

        Returns:
            异常列表 [{metric, value, threshold, severity, message}]
        """
        kpi = pnl.get("kpi", {})
        anomalies: list[dict] = []

        food_cost_ratio = kpi.get("food_cost_ratio", 0)
        if food_cost_ratio > ANOMALY_THRESHOLDS["food_cost_ratio_max"]:
            anomalies.append({
                "metric": "food_cost_ratio",
                "value": food_cost_ratio,
                "threshold": ANOMALY_THRESHOLDS["food_cost_ratio_max"],
                "severity": "high",
                "message": f"食材成本占比 {food_cost_ratio:.1%} 超过阈值 {ANOMALY_THRESHOLDS['food_cost_ratio_max']:.0%}",
            })

        labor_cost_ratio = kpi.get("labor_cost_ratio", 0)
        if labor_cost_ratio > ANOMALY_THRESHOLDS["labor_cost_ratio_max"]:
            anomalies.append({
                "metric": "labor_cost_ratio",
                "value": labor_cost_ratio,
                "threshold": ANOMALY_THRESHOLDS["labor_cost_ratio_max"],
                "severity": "high",
                "message": f"人力成本占比 {labor_cost_ratio:.1%} 超过阈值 {ANOMALY_THRESHOLDS['labor_cost_ratio_max']:.0%}",
            })

        net_margin = kpi.get("net_margin", 0)
        if net_margin < ANOMALY_THRESHOLDS["net_margin_min"]:
            anomalies.append({
                "metric": "net_margin",
                "value": net_margin,
                "threshold": ANOMALY_THRESHOLDS["net_margin_min"],
                "severity": "critical",
                "message": f"净利率 {net_margin:.1%} 低于阈值 {ANOMALY_THRESHOLDS['net_margin_min']:.0%}",
            })

        waste_ratio = kpi.get("waste_ratio", 0)
        if waste_ratio > ANOMALY_THRESHOLDS["waste_ratio_max"]:
            anomalies.append({
                "metric": "waste_ratio",
                "value": waste_ratio,
                "threshold": ANOMALY_THRESHOLDS["waste_ratio_max"],
                "severity": "medium",
                "message": f"损耗率 {waste_ratio:.1%} 超过阈值 {ANOMALY_THRESHOLDS['waste_ratio_max']:.0%}",
            })

        return anomalies

    def get_pnl_trend(self, monthly_pnls: list[dict]) -> list[dict]:
        """获取 P&L 趋势数据

        Args:
            monthly_pnls: 按月排列的 P&L 列表

        Returns:
            趋势数据 [{month, revenue, net_profit, net_margin, ...}]
        """
        trend = []
        for pnl in monthly_pnls:
            kpi = pnl.get("kpi", {})
            trend.append({
                "period": pnl.get("biz_date") or pnl.get("period_label", ""),
                "total_revenue": pnl.get("revenue", {}).get("total", 0),
                "gross_profit": pnl.get("gross_profit", 0),
                "operating_profit": pnl.get("operating_profit", 0),
                "net_profit": pnl.get("net_profit", 0),
                "gross_margin": kpi.get("gross_margin", 0),
                "operating_margin": kpi.get("operating_margin", 0),
                "net_margin": kpi.get("net_margin", 0),
                "food_cost_ratio": kpi.get("food_cost_ratio", 0),
                "labor_cost_ratio": kpi.get("labor_cost_ratio", 0),
            })
        return trend

    # ─── 内部辅助 ─────────────────────────────────────────────

    def _aggregate_pnls(
        self,
        store_id: str,
        period_label: str,
        period_type: str,
        pnls: list[dict],
    ) -> dict:
        """聚合多期 P&L"""
        if not pnls:
            return {}

        def _sum_nested(key_path: str) -> int:
            parts = key_path.split(".")
            total = 0
            for pnl in pnls:
                val = pnl
                for p in parts:
                    val = val.get(p, 0) if isinstance(val, dict) else 0
                total += val if isinstance(val, (int, float)) else 0
            return total

        total_revenue = _sum_nested("revenue.total")
        total_cogs = _sum_nested("cogs.total")
        gross_profit = total_revenue - total_cogs
        total_opex = _sum_nested("opex.total")
        operating_profit = gross_profit - total_opex
        total_other = _sum_nested("other_expenses.total")
        net_profit = operating_profit - total_other

        food_cost = _sum_nested("cogs.food_cost") + _sum_nested("cogs.beverage_cost")
        labor_cost = _sum_nested("opex.labor")
        waste = _sum_nested("cogs.waste_spoilage")

        return {
            "store_id": store_id,
            "period_label": period_label,
            "period_type": period_type,
            "days_count": len(pnls),
            "revenue": {
                "dine_in": _sum_nested("revenue.dine_in"),
                "takeaway": _sum_nested("revenue.takeaway"),
                "delivery": _sum_nested("revenue.delivery"),
                "banquet": _sum_nested("revenue.banquet"),
                "other": _sum_nested("revenue.other"),
                "total": total_revenue,
            },
            "cogs": {
                "food_cost": _sum_nested("cogs.food_cost"),
                "beverage_cost": _sum_nested("cogs.beverage_cost"),
                "waste_spoilage": waste,
                "total": total_cogs,
            },
            "gross_profit": gross_profit,
            "opex": {
                "labor": labor_cost,
                "rent": _sum_nested("opex.rent"),
                "utilities": _sum_nested("opex.utilities"),
                "marketing": _sum_nested("opex.marketing"),
                "platform_commission": _sum_nested("opex.platform_commission"),
                "payment_processing": _sum_nested("opex.payment_processing"),
                "supplies": _sum_nested("opex.supplies"),
                "total": total_opex,
            },
            "operating_profit": operating_profit,
            "other_expenses": {
                "depreciation": _sum_nested("other_expenses.depreciation"),
                "admin_allocation": _sum_nested("other_expenses.admin_allocation"),
                "total": total_other,
            },
            "net_profit": net_profit,
            "kpi": {
                "gross_margin": _safe_ratio(gross_profit, total_revenue),
                "operating_margin": _safe_ratio(operating_profit, total_revenue),
                "net_margin": _safe_ratio(net_profit, total_revenue),
                "labor_cost_ratio": _safe_ratio(labor_cost, total_revenue),
                "food_cost_ratio": _safe_ratio(food_cost, total_revenue),
                "waste_ratio": _safe_ratio(waste, total_revenue),
            },
        }
