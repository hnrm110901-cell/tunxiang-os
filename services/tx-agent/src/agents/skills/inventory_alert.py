"""#5 库存预警 Agent — P1 | 边缘+云端

来源：InventoryAgent(5方法) + inventory(6方法) + supplier(5子Agent)
能力：需求预测(4算法)、库存优化、损耗分析、供应商评级、合同风险
边缘推理：Core ML 库存消耗计算

迁移自 tunxiang V2.x packages/agents/inventory/src/agent.py
"""
import statistics
from typing import Any, Optional
import structlog
from ..base import SkillAgent, AgentResult

logger = structlog.get_logger(__name__)


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

    # ─── 消耗预测（DB查询 + 历史算法） ───

    async def _predict_consumption(self, params: dict) -> AgentResult:
        """消耗预测 — 优先查DB历史数据，降级使用params传入的历史"""
        ingredient_id = params.get("ingredient_id")
        days_ahead = params.get("days_ahead", 7)
        store_id = params.get("store_id") or self.store_id

        if self._db and ingredient_id:
            from sqlalchemy import text
            # 查询过去30天的消耗记录（从库存变动日志或order_items中推算）
            rows = await self._db.execute(text("""
                SELECT DATE(oi.created_at) as date,
                       SUM(oi.quantity * COALESCE(bi.quantity_per_dish, 1)) as daily_consumption
                FROM order_items oi
                JOIN bom_recipe_items bi ON bi.ingredient_id = :ingredient_id
                JOIN orders o ON oi.order_id = o.id
                WHERE o.tenant_id = :tenant_id
                  AND (:store_id::UUID IS NULL OR o.store_id = :store_id::UUID)
                  AND o.created_at >= NOW() - INTERVAL '30 days'
                  AND o.status = 'completed'
                GROUP BY DATE(oi.created_at)
                ORDER BY date DESC
            """), {"ingredient_id": ingredient_id, "tenant_id": self.tenant_id,
                   "store_id": store_id})

            daily_data = [dict(r) for r in rows.mappings()]

            if daily_data:
                consumptions = [float(d["daily_consumption"] or 0) for d in daily_data]
                avg_daily = statistics.mean(consumptions)
                predicted_total = avg_daily * days_ahead

                return AgentResult(
                    success=True, action="predict_consumption",
                    data={
                        "ingredient_id": ingredient_id,
                        "days_ahead": days_ahead,
                        "avg_daily_consumption": round(avg_daily, 2),
                        "predicted_total": round(predicted_total, 2),
                        "data_points": len(daily_data),
                        "algorithm": "moving_average",
                    },
                    reasoning=f"基于{len(daily_data)}天历史数据，日均消耗{avg_daily:.2f}，预测{days_ahead}天消耗{predicted_total:.2f}",
                    confidence=min(0.95, 0.6 + len(daily_data) * 0.01),
                    inference_layer="edge",
                )

        # 降级：使用params中传入的历史数据（兼容原有4算法逻辑）
        history = params.get("history") or params.get("daily_usage", [])
        if not history:
            return AgentResult(success=False, action="predict_consumption",
                               error="缺少历史消耗数据，且无法查询DB")

        avg = statistics.mean(history)
        predicted = avg * days_ahead
        return AgentResult(
            success=True, action="predict_consumption",
            data={"predicted_total": round(predicted, 2), "avg_daily": round(avg, 2),
                  "days_ahead": days_ahead, "algorithm": "simple_average"},
            reasoning=f"日均消耗{avg:.2f}，预测{days_ahead}天消耗{predicted:.2f}",
            confidence=0.8,
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

    # ─── 补货告警（查DB + Claude采购建议） ───

    async def _generate_alerts(self, params: dict) -> AgentResult:
        """生成补货告警：优先查DB，有缺货数据时调用Claude生成采购建议"""
        store_id = params.get("store_id") or self.store_id

        alerts = []
        db_data = ""

        if self._db and store_id:
            from sqlalchemy import text
            rows = await self._db.execute(text("""
                SELECT i.id, i.name, i.unit,
                       COALESCE(il.quantity, 0) as current_qty,
                       COALESCE(i.safety_stock_qty, 0) as safety_stock,
                       i.last_purchase_price_fen
                FROM ingredients i
                LEFT JOIN inventory_levels il
                       ON i.id = il.ingredient_id AND il.store_id = :store_id
                WHERE i.tenant_id = :tenant_id
                  AND i.is_deleted = false
                  AND COALESCE(il.quantity, 0) < COALESCE(i.safety_stock_qty, 1)
                ORDER BY (COALESCE(i.safety_stock_qty, 1) - COALESCE(il.quantity, 0)) DESC
                LIMIT 15
            """), {"tenant_id": self.tenant_id, "store_id": store_id})

            for row in rows.mappings():
                d = dict(row)
                gap = d["safety_stock"] - d["current_qty"]
                alerts.append({
                    "ingredient_id": str(d["id"]),
                    "name": d["name"],
                    "current_qty": d["current_qty"],
                    "safety_stock": d["safety_stock"],
                    "gap": gap,
                    "unit": d.get("unit", ""),
                    "estimated_cost_fen": gap * (d.get("last_purchase_price_fen") or 0),
                })

            if alerts:
                db_data = "\n".join([
                    f"- {a['name']}: 现有{a['current_qty']}{a['unit']}，安全库存{a['safety_stock']}{a['unit']}，缺口{a['gap']}{a['unit']}"
                    for a in alerts[:8]
                ])
        else:
            alerts = params.get("low_stock_items", [])

        # 若有 Claude + 有缺货数据，生成采购建议
        suggestion = ""
        if self._router and alerts:
            try:
                suggestion = await self._router.complete(
                    tenant_id=self.tenant_id,
                    task_type="standard_analysis",
                    system="你是餐饮供应链专家，根据缺货清单生成今日采购建议，用简洁中文表述，控制在150字内。",
                    messages=[{"role": "user", "content":
                        f"以下食材库存不足，请给出采购优先级和注意事项：\n{db_data or str(alerts[:5])}"}],
                    max_tokens=300,
                    db=self._db,
                )
            except Exception as exc:  # noqa: BLE001 — Claude不可用时降级为规则结果
                logger.warning("inventory_alert_llm_fallback", error=str(exc))

        total_est = sum(a.get("estimated_cost_fen", 0) for a in alerts)

        return AgentResult(
            success=True, action="generate_restock_alerts",
            data={
                "alerts": alerts,
                "alert_count": len(alerts),
                "total_estimated_cost_fen": total_est,
                "suggestion": suggestion,
                "store_id": store_id,
            },
            reasoning=f"{len(alerts)}种食材需补货，预计采购成本{total_est/100:.0f}元。{suggestion[:40] if suggestion else ''}",
            confidence=0.95 if suggestion else 0.85,
            inference_layer="cloud" if suggestion else "edge",
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
        """实时库存监控 — 优先查DB获取真实库存，降级使用params数据"""
        store_id = params.get("store_id") or self.store_id

        if self._db and store_id:
            from sqlalchemy import text
            # 查询库存不足和临期食材
            rows = await self._db.execute(text("""
                SELECT i.id, i.name, i.unit,
                       COALESCE(il.quantity, 0) as current_qty,
                       i.safety_stock_qty,
                       i.expiry_date
                FROM ingredients i
                LEFT JOIN inventory_levels il
                       ON i.id = il.ingredient_id AND il.store_id = :store_id
                WHERE i.tenant_id = :tenant_id
                  AND i.is_deleted = false
                ORDER BY current_qty ASC
                LIMIT 50
            """), {"tenant_id": self.tenant_id, "store_id": store_id})

            items = []
            low_stock = []
            expiring_soon = []

            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)

            for row in rows.mappings():
                item = dict(row)
                items.append(item)

                # 库存不足
                safety = item.get("safety_stock_qty") or 0
                current = item.get("current_qty", 0)
                if safety > 0 and current < safety:
                    low_stock.append({
                        "name": item["name"],
                        "current": current,
                        "safety": safety,
                        "unit": item.get("unit", ""),
                        "gap": safety - current,
                    })

                # 临期（3天内）
                expiry = item.get("expiry_date")
                if expiry:
                    days_remaining = (expiry - now.date()).days if hasattr(expiry, 'year') else 999
                    if 0 <= days_remaining <= 3:
                        expiring_soon.append({
                            "name": item["name"],
                            "expiry_date": str(expiry),
                            "days_remaining": days_remaining,
                        })

            return AgentResult(
                success=True, action="monitor_inventory",
                data={
                    "low_stock": low_stock,
                    "expiring_soon": expiring_soon,
                    "total_items": len(items),
                    "alert_count": len(low_stock) + len(expiring_soon),
                    "store_id": store_id,
                },
                reasoning=f"扫描{len(items)}种食材：{len(low_stock)}种库存不足，{len(expiring_soon)}种临期",
                confidence=1.0,
                inference_layer="edge",
            )

        # 降级：使用params中的数据（向下兼容）
        items = params.get("items", [])
        low_stock = [i for i in items if i.get("current_qty", 0) < i.get("safety_stock", 1)]
        return AgentResult(
            success=True, action="monitor_inventory",
            data={"low_stock": low_stock, "total_items": len(items), "alert_count": len(low_stock)},
            reasoning=f"{len(low_stock)}/{len(items)} 库存不足",
            confidence=0.9,
        )

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
