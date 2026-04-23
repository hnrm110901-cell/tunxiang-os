"""What-If 场景模拟器 — Phase 2B

纯函数引擎，零新增数据模型。消费现有 BOM/定价/销售数据进行利润模拟。

支持场景：
  1. ingredient_price_change  — 原料涨跌价对菜品成本和利润的影响
  2. dish_price_change        — 菜品调价 + 销量弹性 = 利润变化
  3. close_period             — 关闭某时段后的新保本点
  4. staff_change             — 增减员工对人效和利润的影响

金额单位：分（fen, int）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# 关闭时段模拟时的默认边际贡献率假设（食材30% + 其他变动10%）
_DEFAULT_CM_RATE: float = 0.60


# ─── 枚举 ──────────────────────────────────────────────────────────────────────


class ScenarioType(str, Enum):
    INGREDIENT_PRICE_CHANGE = "ingredient_price_change"
    DISH_PRICE_CHANGE = "dish_price_change"
    CLOSE_PERIOD = "close_period"
    STAFF_CHANGE = "staff_change"


# ─── 数据类 ────────────────────────────────────────────────────────────────────


@dataclass
class ImpactItem:
    """单项影响明细"""

    name: str  # 菜品名 / 原料名 / 时段名
    baseline_fen: int  # 基准值（成本/利润/营业额）
    simulated_fen: int  # 模拟值
    delta_fen: int  # 差值（正=增加, 负=减少）
    delta_pct: float  # 差值百分比


@dataclass
class ScenarioResult:
    """场景模拟结果"""

    scenario_type: str
    description: str
    affected_items: list[ImpactItem] = field(default_factory=list)
    baseline_profit_fen: int = 0
    simulated_profit_fen: int = 0
    delta_fen: int = 0
    delta_pct: float = 0.0
    top_impacts: list[dict] = field(default_factory=list)  # Top5影响项
    break_even_change: dict = field(default_factory=dict)  # 保本点变化（如适用）
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type,
            "description": self.description,
            "baseline_profit_fen": self.baseline_profit_fen,
            "simulated_profit_fen": self.simulated_profit_fen,
            "delta_fen": self.delta_fen,
            "delta_pct": round(self.delta_pct, 4),
            "top_impacts": self.top_impacts,
            "break_even_change": self.break_even_change,
            "recommendation": self.recommendation,
            "affected_count": len(self.affected_items),
        }


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _safe_pct(delta: int, base: int) -> float:
    return round(delta / base, 4) if base != 0 else 0.0


def _top_n_impacts(items: list[ImpactItem], n: int = 5) -> list[dict]:
    sorted_items = sorted(items, key=lambda x: abs(x.delta_fen), reverse=True)
    return [
        {
            "name": it.name,
            "delta_fen": it.delta_fen,
            "delta_pct": round(it.delta_pct, 4),
            "baseline_fen": it.baseline_fen,
            "simulated_fen": it.simulated_fen,
        }
        for it in sorted_items[:n]
    ]


# ─── 核心引擎 ──────────────────────────────────────────────────────────────────


class ScenarioSimulator:
    """What-If 场景模拟器（无状态，纯函数风格）

    context 结构（由调用方从各服务聚合提供）:
    {
        "dishes": [
            {
                "dish_id": str,
                "dish_name": str,
                "selling_price_fen": int,
                "monthly_quantity": int,
                "bom_items": [
                    {"ingredient_id": str, "ingredient_name": str,
                     "quantity": float, "unit_cost_fen": int}
                ],
            }
        ],
        "store": {
            "monthly_revenue_fen": int,
            "monthly_fixed_cost_fen": int,   # 房租+折旧+管理层工资
            "monthly_labor_fen": int,         # 员工人工成本
            "avg_check_fen": int,             # 平均客单价
            "total_headcount": int,
        },
        "periods": [  # 时段营收分布（可选）
            {"name": "午市", "weight": 0.4, "revenue_fen": N},
            {"name": "晚市", "weight": 0.5, "revenue_fen": N},
            {"name": "宵夜", "weight": 0.1, "revenue_fen": N},
        ],
    }
    """

    def simulate(
        self,
        scenario_type: ScenarioType | str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> ScenarioResult:
        """统一模拟入口"""
        stype = ScenarioType(scenario_type) if isinstance(scenario_type, str) else scenario_type

        dispatch = {
            ScenarioType.INGREDIENT_PRICE_CHANGE: self._sim_ingredient_price,
            ScenarioType.DISH_PRICE_CHANGE: self._sim_dish_price,
            ScenarioType.CLOSE_PERIOD: self._sim_close_period,
            ScenarioType.STAFF_CHANGE: self._sim_staff_change,
        }

        handler = dispatch.get(stype)
        if not handler:
            log.error("scenario_simulator.unknown_type", scenario_type=stype)
            return ScenarioResult(
                scenario_type=str(stype),
                description="未知场景类型",
                recommendation="请指定有效的场景类型",
            )

        result = handler(params, context)
        log.info(
            "scenario_simulated",
            scenario_type=result.scenario_type,
            delta_fen=result.delta_fen,
            delta_pct=result.delta_pct,
        )
        return result

    # ─── 场景1：原料涨跌价 ────────────────────────────────────────────────────

    def _sim_ingredient_price(self, params: dict, context: dict) -> ScenarioResult:
        """原料涨跌价模拟

        params:
            ingredient_id: str      (可选，不传则按名称模糊匹配)
            ingredient_name: str    (可选)
            price_change_pct: float (如 0.1 = 涨10%, -0.05 = 降5%)
        """
        ingredient_id = params.get("ingredient_id", "")
        ingredient_name = params.get("ingredient_name", "")
        change_pct: float = float(params.get("price_change_pct", 0.0))

        dishes = context.get("dishes", [])
        impacts: list[ImpactItem] = []
        total_baseline_cost = 0
        total_sim_cost = 0

        for dish in dishes:
            dish_name = dish.get("dish_name", "")
            qty = int(dish.get("monthly_quantity", 0))
            price_fen = int(dish.get("selling_price_fen", 0))

            bom_items = dish.get("bom_items", [])
            baseline_bom_cost = sum(int(b.get("quantity", 0) * b.get("unit_cost_fen", 0)) for b in bom_items)
            # 找到受影响的原料
            affected_cost_delta = 0
            for b in bom_items:
                match = (ingredient_id and b.get("ingredient_id") == ingredient_id) or (
                    ingredient_name and ingredient_name in b.get("ingredient_name", "")
                )
                if match:
                    item_cost = int(b.get("quantity", 0) * b.get("unit_cost_fen", 0))
                    affected_cost_delta += int(item_cost * change_pct)

            if affected_cost_delta == 0:
                continue

            baseline_profit = (price_fen - baseline_bom_cost) * qty
            sim_bom_cost = baseline_bom_cost + affected_cost_delta
            sim_profit = (price_fen - sim_bom_cost) * qty

            total_baseline_cost += baseline_bom_cost * qty
            total_sim_cost += sim_bom_cost * qty

            impacts.append(
                ImpactItem(
                    name=dish_name,
                    baseline_fen=baseline_profit,
                    simulated_fen=sim_profit,
                    delta_fen=sim_profit - baseline_profit,
                    delta_pct=_safe_pct(sim_profit - baseline_profit, baseline_profit),
                )
            )

        total_delta = sum(it.delta_fen for it in impacts)
        # 估算月度基准利润（若context有store信息则用真实值）
        store = context.get("store", {})
        baseline_profit_total = (
            int(store.get("monthly_revenue_fen", 0))
            - int(store.get("monthly_fixed_cost_fen", 0))
            - int(store.get("monthly_labor_fen", 0))
            - total_baseline_cost
        )

        direction = "涨价" if change_pct > 0 else "降价"
        ing_display = ingredient_name or ingredient_id or "指定原料"
        abs_pct = abs(change_pct * 100)

        recommendation = (
            f"{ing_display} {direction} {abs_pct:.1f}%，"
            f"预计月度利润变化 {total_delta / 100:+.0f} 元，"
            f"影响 {len(impacts)} 道菜品。"
        )
        if change_pct > 0.05 and impacts:
            recommendation += " 建议：对比至少3家供应商报价，或考虑调整受影响菜品定价。"
        elif change_pct < -0.05 and impacts:
            recommendation += " 建议：与供应商签订锁价合同，锁定低价周期。"

        return ScenarioResult(
            scenario_type=ScenarioType.INGREDIENT_PRICE_CHANGE,
            description=f"{ing_display} {direction} {abs_pct:.1f}%",
            affected_items=impacts,
            baseline_profit_fen=baseline_profit_total,
            simulated_profit_fen=baseline_profit_total + total_delta,
            delta_fen=total_delta,
            delta_pct=_safe_pct(total_delta, baseline_profit_total),
            top_impacts=_top_n_impacts(impacts),
            recommendation=recommendation,
        )

    # ─── 场景2：菜品调价 ──────────────────────────────────────────────────────

    def _sim_dish_price(self, params: dict, context: dict) -> ScenarioResult:
        """菜品调价 + 价格弹性模拟

        params:
            dish_id: str
            dish_name: str       (模糊匹配)
            price_change_pct: float   (如 0.08 = 提价8%)
            volume_change_pct: float  (如 -0.12 = 销量下降12%)
        """
        dish_id = params.get("dish_id", "")
        dish_name_kw = params.get("dish_name", "")
        price_chg: float = float(params.get("price_change_pct", 0.0))
        volume_chg: float = float(params.get("volume_change_pct", 0.0))

        dishes = context.get("dishes", [])
        impacts: list[ImpactItem] = []
        total_delta = 0

        for dish in dishes:
            match = (dish_id and dish.get("dish_id") == dish_id) or (
                dish_name_kw and dish_name_kw in dish.get("dish_name", "")
            )
            if not match:
                continue

            price = int(dish.get("selling_price_fen", 0))
            qty = int(dish.get("monthly_quantity", 0))
            bom_cost = sum(int(b.get("quantity", 0) * b.get("unit_cost_fen", 0)) for b in dish.get("bom_items", []))

            new_price = int(price * (1 + price_chg))
            new_qty = max(0, int(qty * (1 + volume_chg)))

            baseline_profit = (price - bom_cost) * qty
            sim_profit = (new_price - bom_cost) * new_qty
            delta = sim_profit - baseline_profit

            impacts.append(
                ImpactItem(
                    name=dish.get("dish_name", ""),
                    baseline_fen=baseline_profit,
                    simulated_fen=sim_profit,
                    delta_fen=delta,
                    delta_pct=_safe_pct(delta, baseline_profit),
                )
            )
            total_delta += delta

        store = context.get("store", {})
        baseline_profit_total = store.get("monthly_revenue_fen", 0)

        direction = "提价" if price_chg > 0 else "降价"
        vol_direction = "下降" if volume_chg < 0 else "上升"

        recommendation = (
            f"调价 {price_chg * 100:+.1f}% + 销量{vol_direction} {abs(volume_chg) * 100:.1f}%，"
            f"综合利润变化 {total_delta / 100:+.0f} 元。"
        )
        if total_delta > 0:
            recommendation += " 调价后仍净收益，建议执行。"
        else:
            recommendation += " 调价后净亏损，建议重新评估提价幅度或寻找降本路径。"

        return ScenarioResult(
            scenario_type=ScenarioType.DISH_PRICE_CHANGE,
            description=f"菜品{direction} {abs(price_chg) * 100:.1f}%，销量{vol_direction} {abs(volume_chg) * 100:.1f}%",
            affected_items=impacts,
            baseline_profit_fen=baseline_profit_total,
            simulated_profit_fen=baseline_profit_total + total_delta,
            delta_fen=total_delta,
            delta_pct=_safe_pct(total_delta, baseline_profit_total),
            top_impacts=_top_n_impacts(impacts),
            recommendation=recommendation,
        )

    # ─── 场景3：关闭时段 ──────────────────────────────────────────────────────

    def _sim_close_period(self, params: dict, context: dict) -> ScenarioResult:
        """关闭某营业时段的保本点变化模拟

        params:
            period_name: str   (如 "午市")
        """
        period_name: str = params.get("period_name", "")
        periods = context.get("periods", [])
        store = context.get("store", {})
        fixed_cost = int(store.get("monthly_fixed_cost_fen", 0))
        labor_cost = int(store.get("monthly_labor_fen", 0))
        total_revenue = int(store.get("monthly_revenue_fen", 0))
        avg_check = int(store.get("avg_check_fen", 10000))

        # 找到要关闭的时段
        target = next((p for p in periods if p.get("name") == period_name), None)
        if not target:
            return ScenarioResult(
                scenario_type=ScenarioType.CLOSE_PERIOD,
                description=f"关闭 {period_name}",
                recommendation=f"未找到时段 {period_name}，请检查输入。",
            )

        period_revenue = int(target.get("revenue_fen", 0))
        # 关闭时段后的营收
        sim_revenue = total_revenue - period_revenue
        # 保本点：固定成本/(边际贡献率)，假设边际贡献率约60%（食材30%+其他变动10%）
        assumed_cm_rate = float(params.get("cm_rate", _DEFAULT_CM_RATE))
        baseline_break_even = math.ceil(fixed_cost / assumed_cm_rate) if assumed_cm_rate > 0 else 0
        sim_break_even = baseline_break_even  # 固定成本不变

        # 关闭时段后是否仍能保本
        sim_profit = int(sim_revenue * assumed_cm_rate) - fixed_cost - labor_cost
        baseline_profit = int(total_revenue * assumed_cm_rate) - fixed_cost - labor_cost

        recommendation = (
            f"关闭【{period_name}】后月度营收减少 {period_revenue / 100:.0f} 元，"
            f"利润变化 {(sim_profit - baseline_profit) / 100:+.0f} 元。"
        )
        if sim_revenue >= baseline_break_even:
            recommendation += f" 仍高于保本点（{baseline_break_even / 100:.0f} 元），可执行。"
        else:
            recommendation += f" 低于保本点（{baseline_break_even / 100:.0f} 元），慎重决策。"

        return ScenarioResult(
            scenario_type=ScenarioType.CLOSE_PERIOD,
            description=f"关闭 {period_name}（月收减 {period_revenue / 100:.0f} 元）",
            baseline_profit_fen=baseline_profit,
            simulated_profit_fen=sim_profit,
            delta_fen=sim_profit - baseline_profit,
            delta_pct=_safe_pct(sim_profit - baseline_profit, baseline_profit),
            break_even_change={
                "baseline_break_even_fen": baseline_break_even,
                "simulated_break_even_fen": sim_break_even,
                "simulated_revenue_fen": sim_revenue,
                "above_break_even": sim_revenue >= sim_break_even,
            },
            recommendation=recommendation,
        )

    # ─── 场景4：人力增减 ──────────────────────────────────────────────────────

    def _sim_staff_change(self, params: dict, context: dict) -> ScenarioResult:
        """增减员工对人效和利润的影响

        params:
            delta_headcount: int    (正=增加, 负=减少)
            monthly_salary_fen: int (新增/减少员工的月薪)
            role: str               (可选，如 "厨师")
        """
        delta_hc: int = int(params.get("delta_headcount", 0))
        salary: int = int(params.get("monthly_salary_fen", 0))
        role: str = params.get("role", "员工")

        store = context.get("store", {})
        total_revenue = int(store.get("monthly_revenue_fen", 0))
        labor_cost = int(store.get("monthly_labor_fen", 0))
        fixed_cost = int(store.get("monthly_fixed_cost_fen", 0))
        headcount = int(store.get("total_headcount", 1))

        labor_delta = delta_hc * salary
        sim_labor = labor_cost + labor_delta

        baseline_profit = total_revenue - fixed_cost - labor_cost
        sim_profit = total_revenue - fixed_cost - sim_labor

        # 人效：营收 / 人头数
        baseline_efficiency = total_revenue // headcount if headcount > 0 else 0
        sim_headcount = max(1, headcount + delta_hc)
        sim_efficiency = total_revenue // sim_headcount

        direction = "增加" if delta_hc > 0 else "减少"

        recommendation = (
            f"{direction} {abs(delta_hc)} 名{role}（月薪 {salary / 100:.0f} 元），"
            f"月人工成本{'+' if delta_hc > 0 else ''}{labor_delta / 100:.0f} 元，"
            f"人均月产出 {sim_efficiency / 100:.0f} 元（变化 {(sim_efficiency - baseline_efficiency) / 100:+.0f} 元）。"
        )
        if delta_hc > 0 and sim_efficiency < baseline_efficiency * 0.85:
            recommendation += " 人效下降超过15%，建议重新评估用工计划。"

        return ScenarioResult(
            scenario_type=ScenarioType.STAFF_CHANGE,
            description=f"{direction} {abs(delta_hc)} 名{role}，月薪 {salary / 100:.0f} 元",
            baseline_profit_fen=baseline_profit,
            simulated_profit_fen=sim_profit,
            delta_fen=sim_profit - baseline_profit,
            delta_pct=_safe_pct(sim_profit - baseline_profit, baseline_profit),
            top_impacts=[
                {
                    "name": "人工成本",
                    "delta_fen": labor_delta,
                    "delta_pct": _safe_pct(labor_delta, labor_cost),
                    "baseline_fen": labor_cost,
                    "simulated_fen": sim_labor,
                },
                {
                    "name": "人均产出",
                    "delta_fen": sim_efficiency - baseline_efficiency,
                    "delta_pct": _safe_pct(sim_efficiency - baseline_efficiency, baseline_efficiency),
                    "baseline_fen": baseline_efficiency,
                    "simulated_fen": sim_efficiency,
                },
            ],
            recommendation=recommendation,
        )
