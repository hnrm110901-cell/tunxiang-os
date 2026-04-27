"""成本核算 Agent — 重构版 V2

覆盖缺口（来源：餐饮成本核算体系完整性评估文档）：
  GAP-2  盘点闭环：理论→实际→差异归因
  GAP-7  保本点与边际贡献分析
  Phase2B What-If 场景模拟
  Phase2C 采购价趋势预警

10个Action：
  diagnose           — Top10高偏差菜品（增强版）
  root_cause         — 原料级根因分析（增强：区分5类因素）
  suggest_fix        — 改进建议（关联预期节省金额）
  dish_margin        — 菜品毛利四象限分析
  stocktake_gap      — 盘点闭环：实际消耗vs理论消耗差异
  contribution_margin — 边际贡献率计算
  break_even         — 保本点分析（营业额/客单数）
  scenario_simulate  — What-If场景模拟
  price_trend_alert  — 采购价趋势预警（价格漂移检测）
  channel_cost_compare — 渠道成本对比（堂食vs外卖毛利差异）

运行位置：云端（Claude API, ModelRouter MODERATE）
优先级：P1
"""

from __future__ import annotations

from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router as _global_router
except ImportError:
    _global_router = None

try:
    from services.tx_supply.src.services.dish_margin import batch_dish_margin as _batch_dish_margin  # noqa: F401

    _DISH_MARGIN_AVAILABLE = True
except ImportError:
    _DISH_MARGIN_AVAILABLE = False

try:
    from services.tx_finance.src.services.contribution_margin_engine import (
        ContributionMarginEngine as _CMEngine,  # noqa: F401
    )

    _CM_ENGINE_AVAILABLE = True
except ImportError:
    _CM_ENGINE_AVAILABLE = False

try:
    from services.tx_finance.src.services.scenario_simulator import ScenarioSimulator as _ScenarioSimulator

    _SCENARIO_SIM_AVAILABLE = True
except ImportError:
    _ScenarioSimulator = None  # type: ignore[assignment,misc]
    _SCENARIO_SIM_AVAILABLE = False

log = structlog.get_logger(__name__)

# ─── 成本偏差阈值 ───────────────────────────────────────────────────────────────
VARIANCE_THRESHOLDS = {
    "minor": 0.05,
    "moderate": 0.10,
    "severe": 0.20,
}

# ─── 根因类别（对齐文档5因素） ────────────────────────────────────────────────────
ROOT_CAUSE_TYPES = {
    "over_portioning": "份量超标",
    "yield_deviation": "出成率偏差",
    "waste_excess": "报废损耗",
    "unknown_loss": "盗损/未记录",
    "bom_inaccurate": "BOM配方不准",
    "price_fluctuation": "采购价波动",
    "supplier_change": "供应商变更",
}

# ─── 渠道默认佣金率 ──────────────────────────────────────────────────────────────
CHANNEL_COMMISSION = {
    "dine_in": 0.0,
    "takeaway": 0.22,
    "meituan": 0.20,
    "douyin": 0.18,
    "self_order": 0.0,
}


def _safe_ratio(num: int | float, den: int | float, precision: int = 4) -> float:
    return round(num / den, precision) if den != 0 else 0.0


def _classify_severity(variance_rate: float) -> str:
    abs_rate = abs(variance_rate)
    if abs_rate >= VARIANCE_THRESHOLDS["severe"]:
        return "severe"
    if abs_rate >= VARIANCE_THRESHOLDS["moderate"]:
        return "moderate"
    if abs_rate >= VARIANCE_THRESHOLDS["minor"]:
        return "minor"
    return "normal"


class CostDiagnosisAgent(SkillAgent):
    """成本核算Agent — 全维度成本诊断、分析、预测"""

    agent_id = "cost_diagnosis"
    agent_name = "成本核算"
    description = (
        "全维度成本核算：菜品偏差诊断、BOM根因分析、盘点闭环差异、"
        "边际贡献保本点、场景模拟、采购价趋势预警、渠道毛利对比"
    )
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "diagnose",
            "root_cause",
            "suggest_fix",
            "dish_margin",
            "stocktake_gap",
            "contribution_margin",
            "break_even",
            "scenario_simulate",
            "price_trend_alert",
            "channel_cost_compare",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "diagnose": self._diagnose,
            "root_cause": self._root_cause,
            "suggest_fix": self._suggest_fix,
            "dish_margin": self._dish_margin,
            "stocktake_gap": self._stocktake_gap,
            "contribution_margin": self._contribution_margin,
            "break_even": self._break_even,
            "scenario_simulate": self._scenario_simulate,
            "price_trend_alert": self._price_trend_alert,
            "channel_cost_compare": self._channel_cost_compare,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(
                success=False,
                action=action,
                error=f"Unsupported action: {action}. Supported: {list(dispatch.keys())}",
            )
        return await handler(params)

    # ══════════════════════════════════════════════════════════════════════════
    # Action 1: diagnose — Top10高偏差菜品
    # ══════════════════════════════════════════════════════════════════════════

    async def _diagnose(self, params: dict) -> AgentResult:
        """找出成本偏差最大的菜品 Top10

        params:
            store_id: str
            date: str
            dishes: list[{name, expected_cost_fen, actual_cost_fen, quantity_sold}]
        """
        store_id = params.get("store_id", "")
        date_str = params.get("date", "")
        dishes = params.get("dishes", [])

        if not dishes:
            return AgentResult(
                success=False,
                action="diagnose",
                error="无菜品成本数据，请提供 dishes 列表",
            )

        variances = []
        total_expected = total_actual = 0

        for d in dishes:
            name = d.get("name", d.get("dish_name", ""))
            expected = int(d.get("expected_cost_fen", d.get("theoretical_cost_fen", 0)))
            actual = int(d.get("actual_cost_fen", 0))
            qty = int(d.get("quantity_sold", 0))

            if expected <= 0 or qty <= 0:
                continue

            variance_rate = _safe_ratio(actual - expected, expected)
            variance_amount = (actual - expected) * qty
            total_expected += expected * qty
            total_actual += actual * qty
            severity = _classify_severity(variance_rate)

            if severity != "normal":
                variances.append(
                    {
                        "dish_name": name,
                        "expected_cost_fen": expected,
                        "actual_cost_fen": actual,
                        "variance_rate": variance_rate,
                        "variance_amount_fen": variance_amount,
                        "quantity_sold": qty,
                        "severity": severity,
                    }
                )

        variances.sort(key=lambda x: abs(x["variance_amount_fen"]), reverse=True)
        overall_variance = _safe_ratio(total_actual - total_expected, total_expected)

        # Count severities in one pass instead of 4× list comprehensions
        severity_counts: dict[str, int] = {"severe": 0, "moderate": 0, "minor": 0}
        for v in variances:
            severity_counts[v["severity"]] = severity_counts.get(v["severity"], 0) + 1

        _log_model_call()

        return AgentResult(
            success=True,
            action="diagnose",
            data={
                "store_id": store_id,
                "date": date_str,
                "overall_variance_rate": overall_variance,
                "total_expected_fen": total_expected,
                "total_actual_fen": total_actual,
                "total_variance_fen": total_actual - total_expected,
                "top_variances": variances[:10],
                "variance_count": len(variances),
                "dishes_analyzed": len(dishes),
                "severity_breakdown": severity_counts,
            },
            reasoning=(
                f"门店 {store_id} 在 {date_str} 整体成本偏差 {overall_variance:+.1%}，"
                f"发现 {len(variances)} 道菜品存在显著偏差，"
                f"严重 {severity_counts['severe']} 道，"
                f"总超支 {(total_actual - total_expected) / 100:+.0f} 元"
            ),
            confidence=0.85,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 2: root_cause — 原料级根因分析（5因素）
    # ══════════════════════════════════════════════════════════════════════════

    async def _root_cause(self, params: dict) -> AgentResult:
        """原料级根因分析：5因素归因

        params:
            dish_id: str
            dish_name: str
            bom_items: list[{ingredient_id, ingredient_name, standard_quantity,
                             standard_price_fen, yield_rate}]
            actual_usage: list[{ingredient_id, actual_quantity, actual_price_fen,
                                waste_rate}]
            stocktake_variance_fen: int  (可选，盘点差异金额，用于unknown_loss归因)
        """
        dish_id = params.get("dish_id", "")
        dish_name = params.get("dish_name", "")
        bom_items = params.get("bom_items", [])
        actual_usage = params.get("actual_usage", [])
        stocktake_var = int(params.get("stocktake_variance_fen", 0))

        if not bom_items:
            return AgentResult(
                success=False,
                action="root_cause",
                error="无BOM数据，无法进行根因分析",
            )

        usage_map = {u.get("ingredient_id"): u for u in actual_usage}
        causes = []
        total_known_impact = 0

        for item in bom_items:
            ing_id = item.get("ingredient_id", "")
            ing_name = item.get("ingredient_name", "")
            std_qty = float(item.get("standard_quantity", 0))
            std_price = int(item.get("standard_price_fen", 0))
            std_yield = float(item.get("yield_rate", 1.0))

            actual = usage_map.get(ing_id, {})
            actual_qty = float(actual.get("actual_quantity", std_qty))
            actual_price = int(actual.get("actual_price_fen", std_price))
            actual_waste = float(actual.get("waste_rate", 0.0))

            # 1. 采购价波动
            if std_price > 0 and abs(actual_price - std_price) / std_price > 0.05:
                impact = int((actual_price - std_price) * std_qty)
                causes.append(
                    _make_cause("price_fluctuation", ing_name, (actual_price - std_price) / std_price, impact)
                )
                total_known_impact += abs(impact)

            # 2. 份量超标（实际用量 > BOM标准量）
            if std_qty > 0 and (actual_qty - std_qty) / std_qty > 0.08:
                impact = int((actual_qty - std_qty) * std_price)
                causes.append(_make_cause("over_portioning", ing_name, (actual_qty - std_qty) / std_qty, impact))
                total_known_impact += abs(impact)

            # 3. 出成率偏差（实际出成率 < BOM标准出成率）
            actual_yield = 1.0 - actual_waste
            if std_yield > 0 and (std_yield - actual_yield) / std_yield > 0.05:
                yield_cost_extra = int(std_qty * std_price * ((1 / actual_yield) - (1 / std_yield)))
                causes.append(
                    _make_cause("yield_deviation", ing_name, (std_yield - actual_yield) / std_yield, yield_cost_extra)
                )
                total_known_impact += yield_cost_extra

            # 4. 报废损耗（实际废弃率 > 阈值）
            if actual_waste > 0.08:
                waste_cost = int(actual_waste * std_qty * std_price)
                causes.append(_make_cause("waste_excess", ing_name, actual_waste, waste_cost))
                total_known_impact += waste_cost

        # 5. 盗损/未记录（盘点差异减去已知因素）
        if stocktake_var > 0:
            unknown = max(0, stocktake_var - total_known_impact)
            if unknown > 0:
                causes.append(_make_cause("unknown_loss", "综合", 0, unknown))

        # 若无任何具体原因，归因为BOM不准
        if not causes:
            causes.append(_make_cause("bom_inaccurate", "整体", 0, 0))

        causes.sort(key=lambda x: abs(x.get("impact_fen", 0)), reverse=True)
        primary_cause = causes[0]["cause_type_label"]

        return AgentResult(
            success=True,
            action="root_cause",
            data={
                "dish_id": dish_id,
                "dish_name": dish_name,
                "primary_cause": primary_cause,
                "all_causes": causes,
                "cause_count": len(causes),
                "bom_items_analyzed": len(bom_items),
                "total_known_impact_fen": total_known_impact,
            },
            reasoning=f"菜品【{dish_name}】成本偏差主因：{primary_cause}，共识别 {len(causes)} 个因素，已知影响金额 {total_known_impact / 100:.0f} 元",
            confidence=0.82,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 3: suggest_fix — 改进建议（含预期节省金额）
    # ══════════════════════════════════════════════════════════════════════════

    async def _suggest_fix(self, params: dict) -> AgentResult:
        """生成改进建议，含预期节省金额

        params:
            causes: list[{cause_type, ingredient, variance_rate, impact_fen}]
            dish_name: str
            monthly_quantity: int  (月销量，用于计算月度节省)
        """
        causes = params.get("causes", params.get("diagnosis", {}).get("all_causes", []))
        dish_name = params.get("dish_name", "")
        monthly_qty = int(params.get("monthly_quantity", 0))

        ACTION_MAP = {
            "price_fluctuation": {
                "action": "寻找替代供应商或谈判锁价合同",
                "category": "采购",
                "saving_pct": 0.05,
                "detail": "对比至少3家供应商报价，选择性价比最优；或与现有供应商签订季度锁价协议",
            },
            "over_portioning": {
                "action": "配备定量工具 + 厨师培训",
                "category": "出品",
                "saving_pct": 0.08,
                "detail": "为高成本食材配备电子秤或标准量杯；录制标准出品视频，每周抽查",
            },
            "yield_deviation": {
                "action": "优化加工SOP，提升出成率",
                "category": "出品",
                "saving_pct": 0.05,
                "detail": "核查刀工/初加工步骤；考虑统一半成品加工批次，降低单次损耗",
            },
            "waste_excess": {
                "action": "优化备料计划 + 改善储存条件",
                "category": "运营",
                "saving_pct": 0.04,
                "detail": "根据历史销量减少提前备料量；检查冷库温度和食材存放方式",
            },
            "unknown_loss": {
                "action": "加强盘点管控，排查内部流失",
                "category": "管控",
                "saving_pct": 0.03,
                "detail": "实施双人盘点制度；对高价值食材启用RFID/条码管理",
            },
            "bom_inaccurate": {
                "action": "重新核定BOM配方",
                "category": "研发",
                "saving_pct": 0.10,
                "detail": "研发部门现场实测标准用量，更新BOM版本；建议每季度复审一次",
            },
            "supplier_change": {
                "action": "评估新供应商性价比",
                "category": "采购",
                "saving_pct": 0.03,
                "detail": "建立供应商比价台账，每月对比；审核新供应商的食品安全资质",
            },
        }

        actions = []
        total_saving_estimate_fen = 0
        seen = set()

        for c in causes:
            ct = c.get("cause_type", "")
            if ct in seen:
                continue
            seen.add(ct)

            template = ACTION_MAP.get(ct, {})
            if not template:
                continue

            impact = int(c.get("impact_fen", 0))
            monthly_saving = int(impact * template["saving_pct"] * (monthly_qty if monthly_qty > 0 else 1))
            total_saving_estimate_fen += monthly_saving

            actions.append(
                {
                    "action": template["action"],
                    "priority": "high"
                    if ct in ("bom_inaccurate", "price_fluctuation", "over_portioning")
                    else "medium",
                    "category": template["category"],
                    "cause_type": ct,
                    "cause_label": ROOT_CAUSE_TYPES.get(ct, ct),
                    "detail": template["detail"].replace("{ingredient}", c.get("ingredient", "")),
                    "estimated_monthly_saving_fen": monthly_saving,
                    "saving_pct": template["saving_pct"],
                }
            )

        actions.sort(key=lambda x: x["estimated_monthly_saving_fen"], reverse=True)

        return AgentResult(
            success=True,
            action="suggest_fix",
            data={
                "dish_name": dish_name,
                "actions": actions,
                "action_count": len(actions),
                "estimated_monthly_saving_fen": total_saving_estimate_fen,
                "estimated_annual_saving_fen": total_saving_estimate_fen * 12,
            },
            reasoning=(
                f"针对【{dish_name}】生成 {len(actions)} 条改进建议，"
                f"预计月节省 {total_saving_estimate_fen / 100:.0f} 元，"
                f"年节省 {total_saving_estimate_fen * 12 / 100:.0f} 元"
            ),
            confidence=0.78,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 4: dish_margin — 菜品毛利四象限分析
    # ══════════════════════════════════════════════════════════════════════════

    async def _dish_margin(self, params: dict) -> AgentResult:
        """菜品毛利四象限分析

        params:
            dishes: list[{dish_name, selling_price_fen, bom_cost_fen,
                          monthly_quantity, channel?}]
        """
        dishes = params.get("dishes", [])
        if not dishes:
            return AgentResult(
                success=False,
                action="dish_margin",
                error="无菜品数据，请提供 dishes 列表",
            )

        results = []
        for d in dishes:
            price = int(d.get("selling_price_fen", 0))
            cost = int(d.get("bom_cost_fen", d.get("theoretical_cost_fen", 0)))
            qty = int(d.get("monthly_quantity", 0))
            channel = d.get("channel", "dine_in")
            commission = CHANNEL_COMMISSION.get(channel, 0.0)

            effective_price = int(price * (1 - commission))
            gross_profit = effective_price - cost
            margin_rate = _safe_ratio(gross_profit, effective_price)

            results.append(
                {
                    "dish_name": d.get("dish_name", ""),
                    "selling_price_fen": price,
                    "effective_price_fen": effective_price,
                    "bom_cost_fen": cost,
                    "gross_profit_fen": gross_profit,
                    "margin_rate": margin_rate,
                    "monthly_quantity": qty,
                    "total_gross_profit_fen": gross_profit * qty,
                    "channel": channel,
                }
            )

        if not results:
            return AgentResult(success=False, action="dish_margin", error="菜品数据无效")

        # 四象限分类（以平均毛利率为分界）
        avg_margin = sum(r["margin_rate"] for r in results) / len(results)
        avg_qty = sum(r["monthly_quantity"] for r in results) / max(len(results), 1)

        for r in results:
            high_margin = r["margin_rate"] >= avg_margin
            high_volume = r["monthly_quantity"] >= avg_qty
            if high_margin and high_volume:
                r["quadrant"] = "star"
                r["quadrant_label"] = "明星菜品（高毛利高销量）"
            elif not high_margin and high_volume:
                r["quadrant"] = "plow_horse"
                r["quadrant_label"] = "耕马菜品（低毛利高销量）"
            elif high_margin and not high_volume:
                r["quadrant"] = "puzzle"
                r["quadrant_label"] = "谜题菜品（高毛利低销量）"
            else:
                r["quadrant"] = "dog"
                r["quadrant_label"] = "狗骨菜品（低毛利低销量）"

        results.sort(key=lambda x: x["total_gross_profit_fen"], reverse=True)

        # 汇总
        quadrant_summary = {}
        for q in ("star", "plow_horse", "puzzle", "dog"):
            items = [r for r in results if r["quadrant"] == q]
            quadrant_summary[q] = {
                "count": len(items),
                "total_gross_profit_fen": sum(r["total_gross_profit_fen"] for r in items),
            }

        return AgentResult(
            success=True,
            action="dish_margin",
            data={
                "dishes": results,
                "dish_count": len(results),
                "avg_margin_rate": round(avg_margin, 4),
                "total_gross_profit_fen": sum(r["total_gross_profit_fen"] for r in results),
                "quadrant_summary": quadrant_summary,
            },
            reasoning=(
                f"分析 {len(results)} 道菜品毛利，平均毛利率 {avg_margin:.1%}，"
                f"明星 {quadrant_summary['star']['count']} 道，"
                f"耕马 {quadrant_summary['plow_horse']['count']} 道，"
                f"谜题 {quadrant_summary['puzzle']['count']} 道，"
                f"狗骨 {quadrant_summary['dog']['count']} 道"
            ),
            confidence=0.9,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 5: stocktake_gap — 盘点闭环差异分析（GAP-2）
    # ══════════════════════════════════════════════════════════════════════════

    async def _stocktake_gap(self, params: dict) -> AgentResult:
        """盘点闭环：实际消耗 vs 理论消耗 → 差异归因

        核算逻辑：
          期初库存 + 本期采购 - 本期盘点库存 = 实际消耗
          实际消耗 - 理论消耗(BOM × 销量) = 差异量
          差异量 × 单价 = 差异金额

        params:
            store_id: str
            period: str  (如 "2026-04")
            ingredients: list[{
                ingredient_id, ingredient_name, unit_price_fen,
                opening_qty, purchase_qty, closing_qty,
                theoretical_usage_qty,  # BOM × 销量计算的理论消耗
                recorded_waste_qty,     # waste_events 中已记录的报废量
            }]
        """
        store_id = params.get("store_id", "")
        period = params.get("period", "")
        ingredients = params.get("ingredients", [])

        if not ingredients:
            return AgentResult(
                success=False,
                action="stocktake_gap",
                error="无盘点数据，请提供 ingredients 盘点信息",
            )

        CAUSE_LABELS = {
            "over_portioning": "份量偏差",
            "waste_excess": "报废损耗",
            "unknown_loss": "盗损/未记录",
            "bom_inaccurate": "BOM配方误差",
        }

        items = []
        total_variance_fen = 0
        total_unknown_fen = 0

        for ing in ingredients:
            name = ing.get("ingredient_name", "")
            unit_price = int(ing.get("unit_price_fen", 0))
            opening = float(ing.get("opening_qty", 0))
            purchase = float(ing.get("purchase_qty", 0))
            closing = float(ing.get("closing_qty", 0))
            theoretical = float(ing.get("theoretical_usage_qty", 0))
            recorded_waste = float(ing.get("recorded_waste_qty", 0))

            # 实际消耗量
            actual_usage = opening + purchase - closing
            # 与理论消耗差异
            variance_qty = actual_usage - theoretical
            variance_fen = int(variance_qty * unit_price)
            total_variance_fen += variance_fen

            # 差异归因
            unexplained_qty = max(0.0, variance_qty - recorded_waste)
            unexplained_fen = int(unexplained_qty * unit_price)
            total_unknown_fen += unexplained_fen

            # 归因分类
            primary_cause: str
            if abs(variance_qty) < 0.01:
                primary_cause = "normal"
            elif recorded_waste >= variance_qty * 0.8:
                primary_cause = "waste_excess"
            elif unexplained_fen > 0:
                primary_cause = "unknown_loss"
            else:
                primary_cause = "bom_inaccurate"

            items.append(
                {
                    "ingredient_name": name,
                    "unit_price_fen": unit_price,
                    "actual_usage_qty": round(actual_usage, 3),
                    "theoretical_usage_qty": round(theoretical, 3),
                    "variance_qty": round(variance_qty, 3),
                    "variance_fen": variance_fen,
                    "recorded_waste_qty": round(recorded_waste, 3),
                    "unexplained_qty": round(unexplained_qty, 3),
                    "unexplained_fen": unexplained_fen,
                    "primary_cause": primary_cause,
                    "primary_cause_label": CAUSE_LABELS.get(primary_cause, primary_cause),
                }
            )

        items.sort(key=lambda x: abs(x["variance_fen"]), reverse=True)

        return AgentResult(
            success=True,
            action="stocktake_gap",
            data={
                "store_id": store_id,
                "period": period,
                "items": items,
                "ingredient_count": len(items),
                "total_variance_fen": total_variance_fen,
                "total_unknown_loss_fen": total_unknown_fen,
                "top10_variances": items[:10],
                "summary": {
                    "over_threshold": sum(1 for i in items if abs(i["variance_fen"]) > 10000),  # 超过100元
                    "has_unknown_loss": total_unknown_fen > 0,
                },
            },
            reasoning=(
                f"门店 {store_id} {period} 期盘点差异总计 {total_variance_fen / 100:+.0f} 元，"
                f"不明损耗 {total_unknown_fen / 100:.0f} 元，"
                f"涉及 {sum(1 for i in items if abs(i['variance_fen']) > 10000)} 种食材超过阈值"
            ),
            confidence=0.88,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 6: contribution_margin — 边际贡献率分析（GAP-7/Phase2A）
    # ══════════════════════════════════════════════════════════════════════════

    async def _contribution_margin(self, params: dict) -> AgentResult:
        """菜品边际贡献率 + 门店加权平均边际贡献率

        params:
            dishes: list[{dish_name, selling_price_fen, variable_cost_fen,
                          monthly_quantity}]
            fixed_cost_fen: int  (门店月度固定成本：房租+折旧+管理工资)
        """
        dishes = params.get("dishes", [])
        fixed_cost = int(params.get("fixed_cost_fen", 0))

        if not dishes:
            return AgentResult(
                success=False,
                action="contribution_margin",
                error="无菜品数据",
            )

        dish_results = []
        total_revenue = total_variable = 0

        for d in dishes:
            price = int(d.get("selling_price_fen", 0))
            var_cost = int(d.get("variable_cost_fen", d.get("bom_cost_fen", 0)))
            qty = int(d.get("monthly_quantity", 0))

            cm = price - var_cost
            cm_rate = _safe_ratio(cm, price)
            monthly_cm = cm * qty

            total_revenue += price * qty
            total_variable += var_cost * qty

            dish_results.append(
                {
                    "dish_name": d.get("dish_name", ""),
                    "selling_price_fen": price,
                    "variable_cost_fen": var_cost,
                    "contribution_margin_fen": cm,
                    "cm_rate": cm_rate,
                    "monthly_quantity": qty,
                    "monthly_cm_fen": monthly_cm,
                }
            )

        dish_results.sort(key=lambda x: x["monthly_cm_fen"], reverse=True)

        # 加权平均边际贡献率
        weighted_cm_rate = _safe_ratio(total_revenue - total_variable, total_revenue)
        total_cm_fen = total_revenue - total_variable
        # 毛利（边际贡献 - 固定成本）
        operating_profit = total_cm_fen - fixed_cost

        return AgentResult(
            success=True,
            action="contribution_margin",
            data={
                "dishes": dish_results,
                "weighted_avg_cm_rate": weighted_cm_rate,
                "total_contribution_margin_fen": total_cm_fen,
                "total_revenue_fen": total_revenue,
                "fixed_cost_fen": fixed_cost,
                "operating_profit_fen": operating_profit,
                "dishes_by_cm_rate": sorted(dish_results, key=lambda x: x["cm_rate"], reverse=True),
            },
            reasoning=(
                f"加权平均边际贡献率 {weighted_cm_rate:.1%}，"
                f"月度边际贡献 {total_cm_fen / 100:.0f} 元，"
                f"扣除固定成本 {fixed_cost / 100:.0f} 元后，营业利润 {operating_profit / 100:+.0f} 元"
            ),
            confidence=0.9,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 7: break_even — 保本点分析（GAP-7/Phase2A）
    # ══════════════════════════════════════════════════════════════════════════

    async def _break_even(self, params: dict) -> AgentResult:
        """保本点分析：营业额保本点 + 客单数保本点

        params:
            fixed_cost_fen: int             门店月度固定成本
            weighted_cm_rate: float         加权平均边际贡献率（0-1）
            avg_check_fen: int              平均客单价
            current_monthly_revenue_fen: int 当前月营业额（计算安全边际）
        """
        import math

        fixed_cost = int(params.get("fixed_cost_fen", 0))
        cm_rate = float(params.get("weighted_cm_rate", 0.6))
        avg_check = int(params.get("avg_check_fen", 10000))
        current_revenue = int(params.get("current_monthly_revenue_fen", 0))

        if cm_rate <= 0:
            return AgentResult(
                success=False,
                action="break_even",
                error="边际贡献率必须大于0",
            )
        if fixed_cost <= 0:
            return AgentResult(
                success=False,
                action="break_even",
                error="固定成本必须大于0",
            )

        # 保本营业额（向上取整到分）
        break_even_revenue = math.ceil(fixed_cost / cm_rate)
        # 保本客单数
        break_even_covers = math.ceil(break_even_revenue / avg_check) if avg_check > 0 else 0

        # 安全边际
        safety_margin_fen = current_revenue - break_even_revenue
        safety_margin_rate = _safe_ratio(safety_margin_fen, current_revenue) if current_revenue > 0 else 0.0

        # 每日保本（按30天）
        daily_break_even = math.ceil(break_even_revenue / 30)
        daily_covers = math.ceil(break_even_covers / 30)

        status = "above" if safety_margin_fen >= 0 else "below"

        return AgentResult(
            success=True,
            action="break_even",
            data={
                "fixed_cost_fen": fixed_cost,
                "weighted_cm_rate": cm_rate,
                "avg_check_fen": avg_check,
                "break_even_revenue_fen": break_even_revenue,
                "break_even_covers_monthly": break_even_covers,
                "daily_break_even_fen": daily_break_even,
                "daily_break_even_covers": daily_covers,
                "current_monthly_revenue_fen": current_revenue,
                "safety_margin_fen": safety_margin_fen,
                "safety_margin_rate": safety_margin_rate,
                "status": status,
            },
            reasoning=(
                f"月度保本营业额 {break_even_revenue / 100:.0f} 元（约 {break_even_covers} 桌次），"
                f"日均需达到 {daily_break_even / 100:.0f} 元。"
                + (
                    f"当前安全边际 {safety_margin_fen / 100:+.0f} 元（{safety_margin_rate:.1%}）。"
                    if current_revenue > 0
                    else ""
                )
            ),
            confidence=0.95,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 8: scenario_simulate — What-If 场景模拟（Phase2B）
    # ══════════════════════════════════════════════════════════════════════════

    async def _scenario_simulate(self, params: dict) -> AgentResult:
        """What-If 场景模拟

        params:
            scenario_type: str  (ingredient_price_change / dish_price_change /
                                  close_period / staff_change)
            scenario_params: dict  (具体场景参数)
            context: dict          (门店/菜品上下文数据)
        """
        scenario_type = params.get("scenario_type", "")
        scenario_params = params.get("scenario_params", {})
        context = params.get("context", {})

        if not scenario_type:
            return AgentResult(
                success=False,
                action="scenario_simulate",
                error="请指定 scenario_type：ingredient_price_change / dish_price_change / close_period / staff_change",
            )

        if _SCENARIO_SIM_AVAILABLE:
            sim_result = _ScenarioSimulator().simulate(scenario_type, scenario_params, context)
            return AgentResult(
                success=True,
                action="scenario_simulate",
                data=sim_result.to_dict(),
                reasoning=sim_result.recommendation,
                confidence=0.80,
            )

        return AgentResult(
            success=True,
            action="scenario_simulate",
            data={"scenario_type": scenario_type, "note": "简化模拟（完整引擎未加载）"},
            reasoning=f"已收到 {scenario_type} 场景模拟请求，请确保 tx-finance/scenario_simulator.py 可访问",
            confidence=0.5,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 9: price_trend_alert — 采购价趋势预警（Phase2C）
    # ══════════════════════════════════════════════════════════════════════════

    async def _price_trend_alert(self, params: dict) -> AgentResult:
        """采购价趋势预警：检测连续涨价、供应商价格漂移

        params:
            price_history: list[{ingredient_name, ingredient_id, prices: list[int]}]
                           prices 列表按时间升序排列（分为单位）
            alert_threshold: float  (连续涨幅阈值，默认0.05=5%)
        """
        price_history = params.get("price_history", [])
        threshold = float(params.get("alert_threshold", 0.05))
        consecutive_required = int(params.get("consecutive_required", 3))

        if not price_history:
            return AgentResult(
                success=False,
                action="price_trend_alert",
                error="无价格历史数据",
            )

        alerts = []
        stable = []

        for item in price_history:
            name = item.get("ingredient_name", "")
            ing_id = item.get("ingredient_id", "")
            prices = [int(p) for p in item.get("prices", []) if p > 0]

            if len(prices) < 2:
                continue

            # 检测连续上涨
            consecutive_rises = 0
            for i in range(1, len(prices)):
                if prices[i] > prices[i - 1] * (1 + threshold):
                    consecutive_rises += 1
                else:
                    consecutive_rises = 0

            total_drift = _safe_ratio(prices[-1] - prices[0], prices[0])
            recent_change = _safe_ratio(prices[-1] - prices[-2], prices[-2])

            if consecutive_rises >= consecutive_required:
                alerts.append(
                    {
                        "ingredient_name": name,
                        "ingredient_id": ing_id,
                        "alert_level": "critical" if consecutive_rises >= 5 else "warning",
                        "consecutive_rises": consecutive_rises,
                        "total_drift_pct": total_drift,
                        "recent_change_pct": recent_change,
                        "latest_price_fen": prices[-1],
                        "baseline_price_fen": prices[0],
                        "recommendation": (
                            f"已连续 {consecutive_rises} 次涨价，累计涨幅 {total_drift:.1%}。"
                            "建议立即比价并联系替代供应商。"
                        ),
                    }
                )
            else:
                stable.append(
                    {
                        "ingredient_name": name,
                        "ingredient_id": ing_id,
                        "total_drift_pct": total_drift,
                        "latest_price_fen": prices[-1],
                    }
                )

        alerts.sort(key=lambda x: x["consecutive_rises"], reverse=True)

        return AgentResult(
            success=True,
            action="price_trend_alert",
            data={
                "alerts": alerts,
                "stable_count": len(stable),
                "alert_count": len(alerts),
                "critical_count": sum(1 for a in alerts if a["alert_level"] == "critical"),
            },
            reasoning=(
                f"检测 {len(price_history)} 种食材价格趋势，"
                f"发现 {len(alerts)} 种存在价格漂移预警，"
                f"其中严重 {sum(1 for a in alerts if a['alert_level'] == 'critical')} 种"
            ),
            confidence=0.85,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Action 10: channel_cost_compare — 渠道成本对比
    # ══════════════════════════════════════════════════════════════════════════

    async def _channel_cost_compare(self, params: dict) -> AgentResult:
        """渠道毛利对比：堂食 vs 外卖（含平台佣金）

        params:
            dishes: list[{dish_name, selling_price_fen, bom_cost_fen,
                          dine_in_qty, takeaway_qty, platform?}]
        """
        dishes = params.get("dishes", [])
        if not dishes:
            return AgentResult(
                success=False,
                action="channel_cost_compare",
                error="无菜品数据",
            )

        channel_totals: dict[str, dict] = {
            "dine_in": {"revenue_fen": 0, "cost_fen": 0, "qty": 0},
            "takeaway": {"revenue_fen": 0, "cost_fen": 0, "qty": 0},
        }

        dish_compare = []
        for d in dishes:
            price = int(d.get("selling_price_fen", 0))
            cost = int(d.get("bom_cost_fen", d.get("theoretical_cost_fen", 0)))
            dine_qty = int(d.get("dine_in_qty", 0))
            take_qty = int(d.get("takeaway_qty", 0))
            platform = d.get("platform", "takeaway")
            commission = CHANNEL_COMMISSION.get(platform, 0.22)

            # 堂食毛利
            dine_gp = (price - cost) * dine_qty
            dine_gp_rate = _safe_ratio(price - cost, price)

            # 外卖毛利（扣佣金）
            take_effective = int(price * (1 - commission))
            take_gp = (take_effective - cost) * take_qty
            take_gp_rate = _safe_ratio(take_effective - cost, take_effective)

            channel_totals["dine_in"]["revenue_fen"] += price * dine_qty
            channel_totals["dine_in"]["cost_fen"] += cost * dine_qty
            channel_totals["dine_in"]["qty"] += dine_qty

            channel_totals["takeaway"]["revenue_fen"] += take_effective * take_qty
            channel_totals["takeaway"]["cost_fen"] += cost * take_qty
            channel_totals["takeaway"]["qty"] += take_qty

            dish_compare.append(
                {
                    "dish_name": d.get("dish_name", ""),
                    "dine_in_margin_rate": dine_gp_rate,
                    "takeaway_margin_rate": take_gp_rate,
                    "margin_gap": round(dine_gp_rate - take_gp_rate, 4),
                    "dine_in_gp_fen": dine_gp,
                    "takeaway_gp_fen": take_gp,
                    "commission_rate": commission,
                    "commission_fen_per_dish": int(price * commission),
                }
            )

        # 渠道汇总毛利率
        channel_summary = {}
        for ch, data in channel_totals.items():
            rev = data["revenue_fen"]
            cost = data["cost_fen"]
            gp = rev - cost
            channel_summary[ch] = {
                "revenue_fen": rev,
                "gross_profit_fen": gp,
                "margin_rate": _safe_ratio(gp, rev),
                "qty": data["qty"],
            }

        dish_compare.sort(key=lambda x: abs(x["margin_gap"]), reverse=True)

        return AgentResult(
            success=True,
            action="channel_cost_compare",
            data={
                "dishes": dish_compare,
                "channel_summary": channel_summary,
                "margin_gap_avg": round(sum(d["margin_gap"] for d in dish_compare) / max(len(dish_compare), 1), 4),
                "high_commission_dishes": [d for d in dish_compare if d["commission_fen_per_dish"] > 500],
            },
            reasoning=(
                f"堂食综合毛利率 {channel_summary['dine_in']['margin_rate']:.1%}，"
                f"外卖综合毛利率 {channel_summary['takeaway']['margin_rate']:.1%}，"
                f"平均差距 {sum(d['margin_gap'] for d in dish_compare) / max(len(dish_compare), 1):.1%}"
            ),
            confidence=0.88,
        )


# ─── 内部工具 ──────────────────────────────────────────────────────────────────


def _make_cause(cause_type: str, ingredient: str, variance_rate: float, impact_fen: int) -> dict:
    return {
        "cause_type": cause_type,
        "cause_type_label": ROOT_CAUSE_TYPES.get(cause_type, cause_type),
        "ingredient": ingredient,
        "variance_rate": round(variance_rate, 4),
        "impact_fen": impact_fen,
    }


def _log_model_call() -> None:
    """记录 ModelRouter 调用（anomaly_detection = MODERATE 级别）"""
    router = _global_router
    if router:
        try:
            model = router.get_model("anomaly_detection")
            router.log_call(
                task_type="anomaly_detection",
                model=model,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                success=True,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("model_router.log_call_failed", error=str(exc))
