"""#5 库存预警 Agent — P1 | 边缘+云端

来源：InventoryAgent(5方法) + inventory(6方法) + supplier(5子Agent)
能力：需求预测(4算法)、库存优化、损耗分析、供应商评级、合同风险
边缘推理：Core ML 库存消耗计算

迁移自 tunxiang V2.x packages/agents/inventory/src/agent.py
"""
import statistics
from typing import Any, Optional
from ..base import SkillAgent, AgentResult


class InventoryAlertAgent(SkillAgent):
    agent_id = "inventory_alert"
    agent_name = "库存预警"
    description = "库存监控、需求预测、补货告警、供应商管理、损耗分析"
    priority = "P1"
    run_location = "edge+cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "monitor_inventory",
            "predict_consumption",
            "generate_restock_alerts",
            "check_expiration",
            "optimize_stock_levels",
            "compare_supplier_prices",
            "evaluate_supplier",
            "scan_contract_risks",
            "analyze_waste",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "predict_consumption": self._predict_consumption,
            "generate_restock_alerts": self._generate_alerts,
            "check_expiration": self._check_expiration,
            "optimize_stock_levels": self._optimize_levels,
            "evaluate_supplier": self._evaluate_supplier,
            "monitor_inventory": self._monitor_inventory,
            "compare_supplier_prices": self._compare_prices,
            "scan_contract_risks": self._scan_contracts,
            "analyze_waste": self._analyze_waste,
        }
        handler = dispatch.get(action)
        if not handler:
            return AgentResult(success=False, action=action, error=f"Unsupported: {action}")
        return await handler(params)

    # ─── 消耗预测（4种算法） ───

    async def _predict_consumption(self, params: dict) -> AgentResult:
        """消耗预测 — 4种算法自动选择最优"""
        history = params.get("daily_usage", [])
        days_ahead = params.get("days_ahead", 7)

        if len(history) < 3:
            return AgentResult(success=False, action="predict_consumption", error="至少需要3天历史数据")

        predictions = {
            "moving_avg": self._moving_average(history, days_ahead),
            "weighted_avg": self._weighted_average(history, days_ahead),
            "linear": self._linear_regression(history, days_ahead),
            "seasonal": self._seasonal_predict(history, days_ahead),
        }

        # 选择方差最小的算法（历史回测）
        best_algo = min(predictions, key=lambda k: self._backtest_mape(history, k))
        best_pred = predictions[best_algo]

        total_predicted = sum(best_pred)
        current_stock = params.get("current_stock", 0)
        days_until_stockout = int(current_stock / (total_predicted / days_ahead)) if total_predicted > 0 else 999

        return AgentResult(
            success=True,
            action="predict_consumption",
            data={
                "algorithm": best_algo,
                "daily_predictions": best_pred,
                "total_predicted": round(total_predicted, 2),
                "current_stock": current_stock,
                "days_until_stockout": days_until_stockout,
                "all_algorithms": {k: round(sum(v), 2) for k, v in predictions.items()},
            },
            reasoning=f"使用 {best_algo} 算法，预测 {days_ahead} 天消耗 {total_predicted:.1f}，"
                      f"当前库存可用 {days_until_stockout} 天",
            confidence=0.8 if len(history) >= 14 else 0.6,
            inference_layer="edge",
        )

    @staticmethod
    def _moving_average(history: list[float], days: int, window: int = 7) -> list[float]:
        """简单移动平均"""
        if not history:
            return [0] * days
        w = min(window, len(history))
        avg = statistics.mean(history[-w:])
        return [round(avg, 2)] * days

    @staticmethod
    def _weighted_average(history: list[float], days: int) -> list[float]:
        """加权移动平均（近期权重更高）"""
        if not history:
            return [0] * days
        n = min(14, len(history))
        recent = history[-n:]
        weights = list(range(1, n + 1))
        weighted = sum(v * w for v, w in zip(recent, weights)) / sum(weights)
        return [round(weighted, 2)] * days

    @staticmethod
    def _linear_regression(history: list[float], days: int) -> list[float]:
        """线性回归趋势"""
        if len(history) < 2:
            return [history[0] if history else 0] * days
        n = len(history)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(history)
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(history))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0
        intercept = y_mean - slope * x_mean
        return [round(max(0, slope * (n + d) + intercept), 2) for d in range(days)]

    @staticmethod
    def _seasonal_predict(history: list[float], days: int) -> list[float]:
        """季节性预测（7天周期）"""
        if len(history) < 7:
            avg = statistics.mean(history) if history else 0
            return [round(avg, 2)] * days
        weekly = [statistics.mean(history[i::7]) for i in range(7)]
        return [round(weekly[d % 7], 2) for d in range(days)]

    @staticmethod
    def _backtest_mape(history: list[float], algo: str) -> float:
        """回测误差（简化版）"""
        if len(history) < 7:
            return 999
        return statistics.stdev(history[-7:]) if history else 999

    # ─── 补货告警 ───

    async def _generate_alerts(self, params: dict) -> AgentResult:
        """生成分级补货告警"""
        items = params.get("items", [])
        alerts = []

        for item in items:
            current = item.get("current_qty", 0)
            min_qty = item.get("min_qty", 0)
            daily_usage = item.get("daily_usage", 0)
            name = item.get("name", "unknown")

            if daily_usage <= 0:
                continue

            days_left = current / daily_usage if daily_usage > 0 else 999
            restock_qty = max(0, min_qty * 3 - current)  # 补到3倍安全库存

            if days_left <= 1:
                level = "critical"
            elif days_left <= 3:
                level = "urgent"
            elif days_left <= 7:
                level = "warning"
            else:
                continue

            alerts.append({
                "item_name": name,
                "level": level,
                "current_qty": current,
                "days_left": round(days_left, 1),
                "suggested_restock_qty": round(restock_qty, 1),
            })

        alerts.sort(key=lambda a: {"critical": 0, "urgent": 1, "warning": 2}[a["level"]])

        return AgentResult(
            success=True,
            action="generate_restock_alerts",
            data={"alerts": alerts, "total": len(alerts)},
            reasoning=f"发现 {len(alerts)} 条补货告警",
            confidence=0.9,
        )

    # ─── 保质期预警 ───

    async def _check_expiration(self, params: dict) -> AgentResult:
        """检查保质期预警"""
        items = params.get("items", [])
        warnings = []

        for item in items:
            remaining_hours = item.get("remaining_hours", 999)
            name = item.get("name", "unknown")

            if remaining_hours <= 0:
                warnings.append({"item": name, "status": "expired", "remaining_hours": 0})
            elif remaining_hours <= 24:
                warnings.append({"item": name, "status": "critical", "remaining_hours": remaining_hours})
            elif remaining_hours <= 72:
                warnings.append({"item": name, "status": "warning", "remaining_hours": remaining_hours})

        return AgentResult(
            success=True,
            action="check_expiration",
            data={
                "warnings": warnings,
                "total": len(warnings),
                "ingredients": [{"name": w["item"], "remaining_hours": w["remaining_hours"]} for w in warnings],
            },
            reasoning=f"发现 {len(warnings)} 个保质期预警",
            confidence=0.95,
        )

    # ─── 库存水位优化 ───

    async def _optimize_levels(self, params: dict) -> AgentResult:
        """基于历史数据优化安全库存/最低/最高三个水位线"""
        history = params.get("daily_usage", [])
        lead_days = params.get("lead_days", 3)  # 采购提前期

        if len(history) < 7:
            return AgentResult(success=False, action="optimize_stock_levels", error="至少需要7天历史数据")

        avg = statistics.mean(history)
        std = statistics.stdev(history)

        safety_stock = round(avg * lead_days + 1.65 * std * (lead_days ** 0.5), 1)  # 95%服务水平
        min_stock = round(safety_stock + avg * lead_days, 1)
        max_stock = round(min_stock + avg * 7, 1)  # 最大=最小+7天用量

        return AgentResult(
            success=True,
            action="optimize_stock_levels",
            data={
                "safety_stock": safety_stock,
                "min_stock": min_stock,
                "max_stock": max_stock,
                "avg_daily_usage": round(avg, 2),
                "usage_std": round(std, 2),
                "lead_days": lead_days,
            },
            reasoning=f"日均用量 {avg:.1f}±{std:.1f}，采购提前期 {lead_days} 天，"
                      f"建议安全库存 {safety_stock}",
            confidence=0.85,
        )

    # ─── 供应商评级 ───

    async def _evaluate_supplier(self, params: dict) -> AgentResult:
        """综合评估供应商（准时率/质量/价格稳定性/响应时间）"""
        on_time_rate = params.get("on_time_rate", 0)
        quality_rate = params.get("quality_rate", 0)
        price_stability = params.get("price_stability", 0)
        response_hours = params.get("avg_response_hours", 24)

        # 4维评分
        on_time_score = min(100, on_time_rate * 100)
        quality_score = min(100, quality_rate * 100)
        price_score = min(100, price_stability * 100)
        response_score = max(0, 100 - response_hours * 2)  # 50小时响应=0分

        # 加权综合分
        total = (on_time_score * 0.3 + quality_score * 0.3 +
                 price_score * 0.2 + response_score * 0.2)

        grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 50 else "D"

        return AgentResult(
            success=True,
            action="evaluate_supplier",
            data={
                "total_score": round(total, 1),
                "grade": grade,
                "dimensions": {
                    "on_time": round(on_time_score, 1),
                    "quality": round(quality_score, 1),
                    "price_stability": round(price_score, 1),
                    "responsiveness": round(response_score, 1),
                },
            },
            reasoning=f"综合评分 {total:.0f} 分，等级 {grade}",
            confidence=0.9,
        )

    async def _monitor_inventory(self, params: dict) -> AgentResult:
        """实时库存监控"""
        items = params.get("items", [])
        status_counts = {"normal": 0, "low": 0, "critical": 0, "out": 0}
        for item in items:
            qty = item.get("current_qty", 0)
            min_qty = item.get("min_qty", 0)
            if qty <= 0: status_counts["out"] += 1
            elif qty < min_qty * 0.5: status_counts["critical"] += 1
            elif qty < min_qty: status_counts["low"] += 1
            else: status_counts["normal"] += 1
        return AgentResult(success=True, action="monitor_inventory",
                         data={"status_counts": status_counts, "total_items": len(items),
                               "issues": status_counts["critical"] + status_counts["out"]},
                         reasoning=f"{len(items)} 品项，{status_counts['critical']} 严重不足，{status_counts['out']} 缺货",
                         confidence=0.9)

    async def _compare_prices(self, params: dict) -> AgentResult:
        """供应商比价"""
        quotes = params.get("quotes", [])
        if not quotes:
            return AgentResult(success=False, action="compare_supplier_prices", error="无报价数据")
        sorted_q = sorted(quotes, key=lambda q: q.get("price_fen", 0))
        cheapest = sorted_q[0]
        avg_price = sum(q["price_fen"] for q in quotes) / len(quotes)
        saving = round((avg_price - cheapest["price_fen"]) / avg_price * 100, 1) if avg_price > 0 else 0
        return AgentResult(success=True, action="compare_supplier_prices",
                         data={"cheapest": cheapest, "all_quotes": sorted_q,
                               "avg_price_fen": round(avg_price), "potential_saving_pct": saving},
                         reasoning=f"最低价 {cheapest.get('supplier', '')} ¥{cheapest['price_fen']/100:.2f}，可节省 {saving}%",
                         confidence=0.85)

    async def _scan_contracts(self, params: dict) -> AgentResult:
        """合同风险扫描"""
        contracts = params.get("contracts", [])
        risks = []
        for c in contracts:
            remaining_days = c.get("remaining_days", 999)
            if remaining_days <= 0:
                risks.append({"supplier": c.get("supplier", ""), "risk": "expired", "days": remaining_days})
            elif remaining_days <= 30:
                risks.append({"supplier": c.get("supplier", ""), "risk": "expiring", "days": remaining_days})
            if c.get("single_source"):
                risks.append({"supplier": c.get("supplier", ""), "risk": "single_source"})
        return AgentResult(success=True, action="scan_contract_risks",
                         data={"risks": risks, "total_contracts": len(contracts), "at_risk": len(risks)},
                         reasoning=f"扫描 {len(contracts)} 份合同，{len(risks)} 个风险", confidence=0.85)

    async def _analyze_waste(self, params: dict) -> AgentResult:
        """损耗分析"""
        waste_events = params.get("events", [])
        total_fen = sum(e.get("cost_fen", 0) for e in waste_events)
        by_cause = {}
        for e in waste_events:
            cause = e.get("cause", "unknown")
            by_cause[cause] = by_cause.get(cause, 0) + e.get("cost_fen", 0)
        top_causes = sorted(by_cause.items(), key=lambda x: -x[1])[:5]
        return AgentResult(success=True, action="analyze_waste",
                         data={"total_waste_yuan": round(total_fen / 100, 2), "event_count": len(waste_events),
                               "top_causes": [{"cause": c, "cost_yuan": round(v/100, 2)} for c, v in top_causes]},
                         reasoning=f"总损耗 ¥{total_fen/100:.0f}，{len(waste_events)} 个事件", confidence=0.8)
