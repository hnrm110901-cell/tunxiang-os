"""库存预警Agent — 基于BOM用量和当前库存，预测缺货风险

工作流程：
1. 计算各食材7日平均日消耗速率
2. 根据当前库存量预测剩余天数
3. 食安合规硬约束：效期≤3天的食材强制标红
4. 调用Claude Haiku生成采购建议和预算估算
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date

import anthropic
import structlog

logger = structlog.get_logger()
client = anthropic.AsyncAnthropic()  # 从环境变量 ANTHROPIC_API_KEY 读取

# 风险等级阈值（天）
HIGH_RISK_DAYS = 2
MEDIUM_RISK_DAYS = 5
EXPIRY_WARNING_DAYS = 3
REORDER_DAYS = 7  # 补货目标天数


class InventorySentinelAgent:
    """库存预警Agent：预测缺货风险，生成采购建议

    三条不可违反的硬约束：
    1. 食安合规：临期食材（效期≤3天）必须标红预警，不可继续正常使用
    2. 毛利底线：采购建议需考虑成本控制，优先推荐高性价比供应商
    3. 客户体验：缺货风险高的菜品必须提前预警，避免客户点餐后无货
    """

    SYSTEM_PROMPT = """你是屯象OS的库存预警智能体。分析食材库存和消耗速率，生成采购建议。

三条不可违反约束：
- 食安合规：临期食材（效期≤3天）必须在recommendations里明确标红预警，建议今日处理
- 毛利底线：采购建议需考虑成本控制，给出合理的采购量而非过量备货
- 客户体验：高风险食材（剩余天数<2天）必须建议立即采购或临时下架相关菜品

输入：风险食材列表（含当前库存、消耗速率、效期信息）

返回JSON（仅JSON，不含其他文字）：
{
  "risk_items": [
    {
      "ingredient_name": "xxx",
      "current_stock": 10,
      "unit": "kg",
      "daily_consumption": 3.5,
      "days_remaining": 2.9,
      "risk_level": "high|medium|low",
      "expiry_warning": true,
      "suggested_order_qty": 20,
      "suggested_supplier": "建议供应商或渠道",
      "action_note": "今日必须采购/建议明日采购/保持关注"
    }
  ],
  "summary": "3种食材需要今日采购，其中活鱼库存告急",
  "total_purchase_budget_estimate_fen": 150000
}"""

    async def analyze(
        self,
        store_id: str,
        tenant_id: str,
        inventory: list[dict],
        sales_history: list[dict],
    ) -> dict:
        """分析库存风险，生成采购建议。

        Args:
            store_id: 门店ID
            tenant_id: 租户ID
            inventory: 当前库存列表，每条包含：
                - ingredient_name: 食材名称
                - current_qty: 当前库存量
                - unit: 单位（kg/个/升等）
                - min_qty: 安全库存量
                - expiry_date: 效期（ISO格式，可选）
                - unit_cost_fen: 单价（分，可选）
            sales_history: 近7天每日消耗量，每条包含：
                - date: 日期（ISO格式）
                - ingredient_name: 食材名称
                - consumed_qty: 消耗量

        Returns:
            包含 risk_items/summary/total_purchase_budget_estimate_fen 的字典
        """
        consumption_rates = self._calc_rates(sales_history)
        risk_items = self._identify_risks(inventory, consumption_rates)

        if not risk_items:
            logger.info(
                "inventory_sentinel_no_risk",
                store_id=store_id,
                tenant_id=tenant_id,
                total_ingredients=len(inventory),
            )
            return {
                "risk_items": [],
                "summary": "库存充足，无需紧急采购",
                "total_purchase_budget_estimate_fen": 0,
            }

        # 调用 Claude Haiku 生成采购建议
        context = self._build_context(store_id, risk_items)

        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )

        response_text = message.content[0].text
        result = self._parse_response(response_text, risk_items)

        high_count = sum(1 for r in risk_items if r["risk_level"] == "high")
        expiry_count = sum(1 for r in risk_items if r.get("expiry_warning"))

        logger.info(
            "inventory_sentinel_analyzed",
            store_id=store_id,
            tenant_id=tenant_id,
            total_risk_items=len(risk_items),
            high_risk_count=high_count,
            expiry_warning_count=expiry_count,
            total_budget_fen=result.get("total_purchase_budget_estimate_fen", 0),
        )

        return result

    def _calc_rates(self, sales_history: list[dict]) -> dict[str, float]:
        """计算各食材7日平均日消耗量。"""
        totals: dict[str, float] = defaultdict(float)
        dates: dict[str, set] = defaultdict(set)

        for record in sales_history:
            name = record.get("ingredient_name", "")
            if not name:
                continue
            totals[name] += record.get("consumed_qty", 0)
            dates[name].add(record.get("date", ""))

        return {
            name: totals[name] / max(len(dates[name]), 1)
            for name in totals
        }

    def _identify_risks(
        self, inventory: list[dict], consumption_rates: dict[str, float]
    ) -> list[dict]:
        """识别风险食材列表（high/medium级别）。"""
        risk_items: list[dict] = []
        today = date.today()

        for item in inventory:
            name = item.get("ingredient_name", "")
            if not name:
                continue

            rate = consumption_rates.get(name, 0.0)
            current_qty = item.get("current_qty", 0)

            # 计算剩余天数
            days_remaining = current_qty / rate if rate > 0 else 999.0

            # 食安合规硬约束：效期检查
            expiry_warning = False
            expiry_date_str = item.get("expiry_date")
            if expiry_date_str:
                try:
                    days_to_expiry = (date.fromisoformat(expiry_date_str) - today).days
                    expiry_warning = days_to_expiry <= EXPIRY_WARNING_DAYS
                except ValueError:
                    logger.warning(
                        "inventory_sentinel_invalid_expiry_date",
                        ingredient_name=name,
                        expiry_date=expiry_date_str,
                    )

            # 综合判断风险等级
            risk_level: str
            if days_remaining < HIGH_RISK_DAYS or expiry_warning:
                risk_level = "high"
            elif days_remaining < MEDIUM_RISK_DAYS:
                risk_level = "medium"
            else:
                risk_level = "low"

            if risk_level in ("high", "medium"):
                suggested_qty = round(rate * REORDER_DAYS, 1) if rate > 0 else 0
                unit_cost_fen = item.get("unit_cost_fen", 0)

                risk_items.append({
                    "ingredient_name": name,
                    "current_stock": current_qty,
                    "unit": item.get("unit", ""),
                    "daily_consumption": round(rate, 2),
                    "days_remaining": round(days_remaining, 1),
                    "risk_level": risk_level,
                    "expiry_warning": expiry_warning,
                    "suggested_order_qty": suggested_qty,
                    "unit_cost_fen": unit_cost_fen,
                })

        # 按风险等级排序：high优先
        risk_items.sort(key=lambda x: (0 if x["risk_level"] == "high" else 1, x["days_remaining"]))
        return risk_items

    def _build_context(self, store_id: str, risk_items: list[dict]) -> str:
        high_items = [r for r in risk_items if r["risk_level"] == "high"]
        medium_items = [r for r in risk_items if r["risk_level"] == "medium"]
        expiry_items = [r for r in risk_items if r.get("expiry_warning")]

        # 计算预估采购金额
        rough_budget_fen = sum(
            r.get("suggested_order_qty", 0) * r.get("unit_cost_fen", 0)
            for r in risk_items
        )

        items_lines = []
        for r in risk_items:
            expiry_tag = "【临期】" if r.get("expiry_warning") else ""
            items_lines.append(
                f"  [{r['risk_level'].upper()}]{expiry_tag} {r['ingredient_name']}: "
                f"当前{r['current_stock']}{r['unit']}，"
                f"日均消耗{r['daily_consumption']}{r['unit']}，"
                f"预计还剩{r['days_remaining']}天，"
                f"建议补货{r['suggested_order_qty']}{r['unit']}"
            )

        return f"""门店 {store_id} 库存预警分析：

风险概览：
- 高风险食材（需立即处理）：{len(high_items)}种
- 中风险食材（3-5天内需采购）：{len(medium_items)}种
- 临期食材（效期≤3天）：{len(expiry_items)}种

风险食材明细：
{chr(10).join(items_lines)}

预估总采购金额：约{rough_budget_fen/100:.0f}元

请根据以上数据生成采购建议，重点关注高风险和临期食材。"""

    def _parse_response(self, response_text: str, risk_items: list[dict]) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回基础兜底结果。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "inventory_sentinel_parse_failed",
            response_preview=response_text[:200],
        )

        # 兜底：返回自动计算的结果，不含Claude建议
        high_count = sum(1 for r in risk_items if r["risk_level"] == "high")
        expiry_count = sum(1 for r in risk_items if r.get("expiry_warning"))
        rough_budget = sum(
            r.get("suggested_order_qty", 0) * r.get("unit_cost_fen", 0)
            for r in risk_items
        )

        summary_parts = []
        if high_count:
            summary_parts.append(f"{high_count}种高风险食材需立即采购")
        if expiry_count:
            summary_parts.append(f"{expiry_count}种临期食材需紧急处理")
        medium_count = len(risk_items) - high_count
        if medium_count > 0:
            summary_parts.append(f"{medium_count}种食材需近期跟进")

        return {
            "risk_items": risk_items,
            "summary": "，".join(summary_parts) if summary_parts else "存在库存风险，建议人工检查",
            "total_purchase_budget_estimate_fen": int(rough_budget),
        }


    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """从 mv_inventory_bom 快速读取 BOM 损耗数据，<5ms，无 Claude 调用。

        数据来源：因果链③投影视图（InventoryBomProjector）
        返回高损耗率食材列表（loss_rate > 10%）。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
        from shared.ontology.src.database import get_db

        try:
            async for db in get_db():
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
                params: dict = {"tenant_id": tenant_id}
                store_clause = ""
                if store_id:
                    store_clause = "AND store_id = :store_id"
                    params["store_id"] = store_id

                result = await db.execute(
                    text(f"""
                        SELECT
                            ingredient_id,
                            ingredient_name,
                            theoretical_usage_g,
                            actual_usage_g,
                            waste_g,
                            unexplained_loss_g,
                            loss_rate,
                            stat_date
                        FROM mv_inventory_bom
                        WHERE tenant_id = :tenant_id
                        {store_clause}
                        AND stat_date = (
                            SELECT MAX(stat_date) FROM mv_inventory_bom
                            WHERE tenant_id = :tenant_id {store_clause}
                        )
                        ORDER BY loss_rate DESC
                        LIMIT 20
                    """),
                    params,
                )
                rows = result.mappings().all()
                items = []
                for r in rows:
                    item = dict(r._mapping)
                    if item.get("loss_rate") is not None:
                        item["loss_rate"] = float(item["loss_rate"])
                    for g_field in ("theoretical_usage_g", "actual_usage_g", "waste_g", "unexplained_loss_g"):
                        if item.get(g_field) is not None:
                            item[g_field] = float(item[g_field])
                    items.append(item)

                high_loss_items = [i for i in items if i.get("loss_rate", 0) > 0.10]
                return {
                    "inference_layer": "mv_fast_path",
                    "data": {
                        "total_ingredients": len(items),
                        "high_loss_count": len(high_loss_items),
                        "high_loss_items": high_loss_items[:5],
                        "all_items": items,
                    },
                    "agent": self.__class__.__name__,
                    "risk_signal": "high" if len(high_loss_items) > 3 else ("medium" if high_loss_items else "normal"),
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "inventory_sentinel_mv_db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return {
                "inference_layer": "mv_fast_path_error",
                "data": {},
                "agent": self.__class__.__name__,
                "error": "数据库查询失败，请使用实时分析",
            }


inventory_sentinel = InventorySentinelAgent()
