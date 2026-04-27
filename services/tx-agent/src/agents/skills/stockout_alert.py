"""#28 沽清预警 Agent — P1 | 边缘+云端

守门员Agent：基于当前库存 + 今日销量趋势，预测菜品即将沽清。
提前预警距离沽清还有约N份，建议替代菜品、通知前台停售。

触发条件：库存变动事件 or 每15分钟定时扫描。
"""

from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger()

# 默认阈值
DEFAULT_WARNING_PORTIONS = 5  # 剩余份数 <= 此值时预警
DEFAULT_CRITICAL_PORTIONS = 2  # 剩余份数 <= 此值时紧急预警
DEFAULT_FORECAST_HOURS = 3  # 预测未来N小时的消耗


class StockoutAlertAgent(SkillAgent):
    agent_id = "stockout_alert"
    agent_name = "沽清预警"
    description = "预测菜品即将沽清，提前预警并推荐替代菜品"
    priority = "P1"
    run_location = "edge+cloud"

    # Sprint D1 / PR G 批次 1：沽清预警核心是食材（临期/不足），兼顾替代菜品的毛利
    # 与出餐时长无关（这里判断是否该上某道菜，非出餐调度）
    constraint_scope = {"margin", "safety"}

    def get_supported_actions(self) -> list[str]:
        return [
            "predict_stockout",
            "get_alternatives",
            "batch_scan",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "predict_stockout": self._predict_stockout,
            "get_alternatives": self._get_alternatives,
            "batch_scan": self._batch_scan,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ─── 单菜品沽清预测 ───

    async def _predict_stockout(self, params: dict) -> AgentResult:
        """预测单个菜品沽清时间"""
        dish_name = params.get("dish_name", "未知菜品")
        current_portions = params.get("current_portions", 0)
        hourly_sales = params.get("hourly_sales", [])
        alternatives = params.get("alternatives", [])
        warning_threshold = params.get("warning_portions", DEFAULT_WARNING_PORTIONS)

        # 计算销售速率
        if hourly_sales:
            avg_hourly = sum(hourly_sales) / len(hourly_sales)
            # 加权最近时段（最近的权重更高）
            if len(hourly_sales) >= 3:
                recent_weight = sum(hourly_sales[-3:]) / 3
                avg_hourly = avg_hourly * 0.4 + recent_weight * 0.6
        else:
            avg_hourly = 0

        # 预测沽清时间
        if avg_hourly > 0:
            hours_until_stockout = current_portions / avg_hourly
            est_stockout_time = f"约 {hours_until_stockout:.1f} 小时后"
        else:
            hours_until_stockout = float("inf")
            est_stockout_time = "销量低，暂无沽清风险"

        # 风险等级
        if current_portions <= DEFAULT_CRITICAL_PORTIONS:
            risk_level = "critical"
            action_suggestion = "建议立即通知前台停售"
        elif current_portions <= warning_threshold:
            risk_level = "warning"
            action_suggestion = "建议提前准备替代菜品"
        elif hours_until_stockout <= DEFAULT_FORECAST_HOURS:
            risk_level = "warning"
            action_suggestion = f"预计 {hours_until_stockout:.1f} 小时内沽清"
        else:
            risk_level = "normal"
            action_suggestion = "库存充足"

        dish_result = {
            "dish": dish_name,
            "remaining_portions": current_portions,
            "est_stockout_time": est_stockout_time,
            "hours_until_stockout": round(hours_until_stockout, 1) if hours_until_stockout != float("inf") else None,
            "avg_hourly_sales": round(avg_hourly, 1),
            "alternatives": alternatives[:3],
            "risk_level": risk_level,
            "action": action_suggestion,
        }

        return AgentResult(
            success=True,
            action="predict_stockout",
            data={
                "at_risk_dishes": [dish_result] if risk_level != "normal" else [],
                "all_dishes": [dish_result],
            },
            reasoning=f"{dish_name} 剩余 {current_portions} 份，"
            f"时速 {avg_hourly:.1f} 份/h，{est_stockout_time}，{risk_level}",
            confidence=0.85 if len(hourly_sales) >= 3 else 0.65,
        )

    # ─── 替代菜品推荐 ───

    async def _get_alternatives(self, params: dict) -> AgentResult:
        """为即将沽清的菜品推荐替代品"""
        dish_name = params.get("dish_name", "")
        category = params.get("category", "")
        available_dishes = params.get("available_dishes", [])
        price_range_fen = params.get("price_range_fen", {})

        min_price = price_range_fen.get("min", 0)
        max_price = price_range_fen.get("max", float("inf"))

        # 筛选同类目、价格接近、库存充足的菜品
        candidates = []
        for dish in available_dishes:
            dish_category = dish.get("category", "")
            dish_price = dish.get("price_fen", 0)
            dish_portions = dish.get("remaining_portions", 0)

            if dish.get("name") == dish_name:
                continue
            if category and dish_category != category:
                continue
            if dish_portions < DEFAULT_WARNING_PORTIONS:
                continue
            if min_price <= dish_price <= max_price:
                candidates.append(
                    {
                        "name": dish.get("name", ""),
                        "price_fen": dish_price,
                        "remaining_portions": dish_portions,
                        "category": dish_category,
                        "match_score": self._calc_match_score(dish, price_range_fen),
                    }
                )

        # 按匹配度排序
        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        top_alternatives = candidates[:5]

        return AgentResult(
            success=True,
            action="get_alternatives",
            data={
                "dish_name": dish_name,
                "alternatives": top_alternatives,
                "total_candidates": len(candidates),
            },
            reasoning=f"为 {dish_name} 找到 {len(candidates)} 个替代菜品",
            confidence=0.80 if candidates else 0.50,
        )

    # ─── 批量扫描 ───

    async def _batch_scan(self, params: dict) -> AgentResult:
        """批量扫描所有菜品库存，返回沽清风险列表"""
        dishes = params.get("dishes", [])
        if not dishes:
            return AgentResult(
                success=False,
                action="batch_scan",
                error="无菜品数据",
                reasoning="批量扫描需要提供菜品列表",
                confidence=1.0,
            )

        at_risk: list[dict] = []
        for dish in dishes:
            result = await self._predict_stockout(
                {
                    "dish_name": dish.get("name", ""),
                    "current_portions": dish.get("remaining_portions", 0),
                    "hourly_sales": dish.get("hourly_sales", []),
                    "alternatives": dish.get("alternatives", []),
                }
            )
            at_risk_items = result.data.get("at_risk_dishes", [])
            at_risk.extend(at_risk_items)

        # 按风险等级排序：critical > warning
        priority_map = {"critical": 0, "warning": 1, "normal": 2}
        at_risk.sort(key=lambda x: priority_map.get(x.get("risk_level", "normal"), 2))

        critical_count = sum(1 for d in at_risk if d["risk_level"] == "critical")

        return AgentResult(
            success=True,
            action="batch_scan",
            data={
                "at_risk_dishes": at_risk,
                "total_scanned": len(dishes),
                "at_risk_count": len(at_risk),
                "critical_count": critical_count,
            },
            reasoning=f"扫描 {len(dishes)} 道菜品，{len(at_risk)} 道有沽清风险（{critical_count} 道紧急）",
            confidence=0.82,
        )

    @staticmethod
    def _calc_match_score(dish: dict, price_range: dict) -> float:
        """计算替代菜品匹配度"""
        score = 0.5  # 基础分
        portions = dish.get("remaining_portions", 0)
        if portions > 20:
            score += 0.3
        elif portions > 10:
            score += 0.2
        # 价格越接近中位数越好
        mid_price = (price_range.get("min", 0) + price_range.get("max", 10000)) / 2
        dish_price = dish.get("price_fen", 0)
        if mid_price > 0:
            price_diff_ratio = abs(dish_price - mid_price) / mid_price
            score += max(0, 0.2 - price_diff_ratio * 0.2)
        return round(score, 2)
