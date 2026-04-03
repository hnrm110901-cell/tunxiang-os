"""成本偏差诊断 Agent — 优化型 | 云端

能力：成本偏差诊断、根因分析、改进建议
通过 ModelRouter (MODERATE) 调用 LLM 进行复杂根因推理。
"""
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

try:
    from services.tunxiang_api.src.shared.core.model_router import model_router
except ImportError:
    model_router = None  # 独立测试时无跨服务依赖

logger = structlog.get_logger()

# 成本偏差阈值
VARIANCE_THRESHOLDS = {
    "minor": 0.05,     # 5% 以内为轻微偏差
    "moderate": 0.10,   # 10% 以内为中等偏差
    "severe": 0.20,     # 20% 以上为严重偏差
}

# 根因类别
ROOT_CAUSE_TYPES = [
    "采购价上涨",
    "BOM配方不准",
    "加工损耗过高",
    "份量超标",
    "供应商变更",
    "季节性波动",
]


class CostDiagnosisAgent(SkillAgent):
    agent_id = "cost_diagnosis"
    agent_name = "成本偏差诊断"
    description = "找出成本偏差最大的菜品/原料，分析根因，建议改进动作"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return ["diagnose", "root_cause", "suggest_fix"]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "diagnose": self._diagnose,
            "root_cause": self._root_cause,
            "suggest_fix": self._suggest_fix,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    async def _diagnose(self, params: dict) -> AgentResult:
        """诊断成本偏差 -- 找出偏差最大的菜品/原料"""
        store_id = params.get("store_id", "")
        date = params.get("date", "")
        dishes = params.get("dishes", [])

        if not dishes:
            return AgentResult(
                success=False, action="diagnose",
                error="无菜品成本数据",
            )

        # 使用 ModelRouter (MODERATE)
        model = model_router.get_model("anomaly_detection") if model_router else "claude-sonnet-4-6"

        variances = []
        total_expected = 0
        total_actual = 0

        for d in dishes:
            name = d.get("name", "")
            expected_cost = d.get("expected_cost_fen", 0)
            actual_cost = d.get("actual_cost_fen", 0)
            quantity_sold = d.get("quantity_sold", 0)

            if expected_cost <= 0:
                continue

            variance_rate = (actual_cost - expected_cost) / expected_cost
            variance_amount = (actual_cost - expected_cost) * quantity_sold
            total_expected += expected_cost * quantity_sold
            total_actual += actual_cost * quantity_sold

            # 分级
            if abs(variance_rate) >= VARIANCE_THRESHOLDS["severe"]:
                severity = "severe"
            elif abs(variance_rate) >= VARIANCE_THRESHOLDS["moderate"]:
                severity = "moderate"
            elif abs(variance_rate) >= VARIANCE_THRESHOLDS["minor"]:
                severity = "minor"
            else:
                severity = "normal"

            if severity != "normal":
                variances.append({
                    "dish_name": name,
                    "expected_cost_fen": expected_cost,
                    "actual_cost_fen": actual_cost,
                    "variance_rate": round(variance_rate, 4),
                    "variance_amount_fen": round(variance_amount),
                    "quantity_sold": quantity_sold,
                    "severity": severity,
                })

        variances.sort(key=lambda x: abs(x["variance_amount_fen"]), reverse=True)

        overall_variance = (total_actual - total_expected) / total_expected if total_expected > 0 else 0

        if model_router:
            model_router.log_call(
                task_type="anomaly_detection", model=model,
                input_tokens=0, output_tokens=0, latency_ms=0, success=True,
            )

        return AgentResult(
            success=True, action="diagnose",
            data={
                "store_id": store_id,
                "date": date,
                "overall_variance_rate": round(overall_variance, 4),
                "total_expected_fen": total_expected,
                "total_actual_fen": total_actual,
                "top_variances": variances[:10],
                "variance_count": len(variances),
                "dishes_analyzed": len(dishes),
            },
            reasoning=f"门店 {store_id} 在 {date} 整体成本偏差 {overall_variance:+.1%}，"
                      f"发现 {len(variances)} 道菜品有显著偏差",
            confidence=0.85,
        )

    async def _root_cause(self, params: dict) -> AgentResult:
        """根因分析 -- 采购价上涨/BOM不准/损耗过高/份量超标"""
        dish_id = params.get("dish_id", "")
        dish_name = params.get("dish_name", "")
        bom_items = params.get("bom_items", [])
        actual_usage = params.get("actual_usage", [])

        if not bom_items:
            return AgentResult(
                success=False, action="root_cause",
                error="无BOM数据，无法分析根因",
            )

        # 构建原料偏差映射
        usage_map = {u.get("ingredient_id"): u for u in actual_usage}
        causes = []

        for item in bom_items:
            ing_id = item.get("ingredient_id", "")
            ing_name = item.get("ingredient_name", "")
            std_quantity = item.get("standard_quantity", 0)
            std_price_fen = item.get("standard_price_fen", 0)

            actual = usage_map.get(ing_id, {})
            actual_qty = actual.get("actual_quantity", std_quantity)
            actual_price = actual.get("actual_price_fen", std_price_fen)
            waste_rate = actual.get("waste_rate", 0)

            # 采购价偏差
            if std_price_fen > 0:
                price_variance = (actual_price - std_price_fen) / std_price_fen
                if abs(price_variance) > 0.05:
                    causes.append({
                        "ingredient": ing_name,
                        "cause_type": "采购价上涨" if price_variance > 0 else "采购价下降",
                        "variance_rate": round(price_variance, 4),
                        "impact_fen": round((actual_price - std_price_fen) * std_quantity),
                    })

            # 用量偏差(份量超标)
            if std_quantity > 0:
                qty_variance = (actual_qty - std_quantity) / std_quantity
                if qty_variance > 0.1:
                    causes.append({
                        "ingredient": ing_name,
                        "cause_type": "份量超标",
                        "variance_rate": round(qty_variance, 4),
                        "impact_fen": round((actual_qty - std_quantity) * std_price_fen),
                    })

            # 损耗过高
            if waste_rate > 0.08:
                causes.append({
                    "ingredient": ing_name,
                    "cause_type": "加工损耗过高",
                    "variance_rate": round(waste_rate, 4),
                    "impact_fen": round(waste_rate * std_quantity * std_price_fen),
                })

        # 如果无具体原料偏差但整体偏差存在，归因 BOM 不准
        if not causes and bom_items:
            causes.append({
                "ingredient": "整体",
                "cause_type": "BOM配方不准",
                "variance_rate": 0,
                "impact_fen": 0,
            })

        causes.sort(key=lambda x: abs(x.get("impact_fen", 0)), reverse=True)

        primary_cause = causes[0]["cause_type"] if causes else "未知"

        return AgentResult(
            success=True, action="root_cause",
            data={
                "dish_id": dish_id,
                "dish_name": dish_name,
                "primary_cause": primary_cause,
                "all_causes": causes,
                "cause_count": len(causes),
                "bom_items_analyzed": len(bom_items),
            },
            reasoning=f"菜品 {dish_name} 成本偏差主因: {primary_cause}，共 {len(causes)} 个因素",
            confidence=0.8,
        )

    async def _suggest_fix(self, params: dict) -> AgentResult:
        """建议改进动作 -- 调整BOM/更换供应商/培训厨师"""
        diagnosis = params.get("diagnosis", {})
        causes = diagnosis.get("all_causes", params.get("causes", []))
        dish_name = diagnosis.get("dish_name", params.get("dish_name", ""))

        # 使用 ModelRouter
        from services.tunxiang_api.src.shared.core.model_router import model_router
        model = model_router.get_model("anomaly_detection")  # MODERATE

        actions = []
        cause_types_seen = set()

        for c in causes:
            ct = c.get("cause_type", "")
            if ct in cause_types_seen:
                continue
            cause_types_seen.add(ct)

            if ct == "采购价上涨":
                actions.append({
                    "action": "更换供应商或协商价格",
                    "priority": "high",
                    "category": "采购",
                    "detail": f"原料 {c.get('ingredient', '')} 采购价偏差 {c.get('variance_rate', 0):.1%}，"
                              f"建议对比3家供应商报价",
                    "expected_saving_pct": 5,
                })
            elif ct == "份量超标":
                actions.append({
                    "action": "培训厨师 + 量化工具",
                    "priority": "high",
                    "category": "出品",
                    "detail": f"原料 {c.get('ingredient', '')} 超标 {c.get('variance_rate', 0):.1%}，"
                              f"建议使用量勺/电子秤标准化",
                    "expected_saving_pct": 8,
                })
            elif ct == "加工损耗过高":
                actions.append({
                    "action": "优化加工SOP + 培训",
                    "priority": "medium",
                    "category": "出品",
                    "detail": f"原料 {c.get('ingredient', '')} 损耗率 {c.get('variance_rate', 0):.1%}，"
                              f"建议录制标准操作视频培训",
                    "expected_saving_pct": 5,
                })
            elif ct == "BOM配方不准":
                actions.append({
                    "action": "重新核定BOM配方",
                    "priority": "high",
                    "category": "研发",
                    "detail": "标准配方与实际用料不符，建议研发部门重新核定并更新系统",
                    "expected_saving_pct": 10,
                })
            elif ct == "采购价下降":
                actions.append({
                    "action": "锁定当前低价供应商",
                    "priority": "low",
                    "category": "采购",
                    "detail": f"原料 {c.get('ingredient', '')} 价格下降，建议签订长期合同锁价",
                    "expected_saving_pct": 0,
                })

        if model_router:
            model_router.log_call(
                task_type="anomaly_detection", model=model,
                input_tokens=0, output_tokens=0, latency_ms=0, success=True,
            )

        return AgentResult(
            success=True, action="suggest_fix",
            data={
                "dish_name": dish_name,
                "actions": actions,
                "action_count": len(actions),
                "total_expected_saving_pct": sum(a.get("expected_saving_pct", 0) for a in actions),
            },
            reasoning=f"针对 {dish_name} 生成 {len(actions)} 条改进建议，"
                      f"预计可降低成本 {sum(a.get('expected_saving_pct', 0) for a in actions)}%",
            confidence=0.8,
        )
