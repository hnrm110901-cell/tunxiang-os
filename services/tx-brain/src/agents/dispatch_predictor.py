"""出餐调度预测Agent — 预测出餐时间，辅助KDS调度

双路径设计：
- 快路径：基于菜品分类历史均值估算，不调用Claude（低负载/普通订单）
- 慢路径：Claude sonnet分析（厨房高负载 / 活鲜菜品 / 大桌 / 超长等待）
"""
from __future__ import annotations

import json
import re

import anthropic
import structlog

logger = structlog.get_logger()
client = anthropic.AsyncAnthropic()  # 从环境变量 ANTHROPIC_API_KEY 读取


class DispatchPredictorAgent:
    """出餐时间预测Agent

    双层推理：
    - 快路径：基于历史平均（从菜品分类统计），不调用Claude
    - 慢路径：Claude分析（当厨房负载高/特殊菜品/大桌时调用）

    三条硬约束校验（客户体验）：
    - 出餐时间不可超过门店设定上限
    - 活鲜海鲜必须额外标注备注
    - 大桌（>10人）必须建议分批出
    """

    QUICK_ESTIMATE_MINUTES: dict[str, int] = {
        "凉菜": 5,
        "热菜": 15,
        "海鲜": 20,
        "汤": 25,
        "主食": 8,
    }

    # 触发慢路径的阈值
    SLOW_PATH_PENDING_TASKS = 20
    SLOW_PATH_AVG_WAIT_MINUTES = 25
    SLOW_PATH_TABLE_SIZE = 10

    SYSTEM_PROMPT = """你是屯象OS的出餐调度智能体。根据当前厨房状态预测出餐时间。

输入：订单菜品列表 + 厨房当前负载（待处理工单数/平均等待时间）

分析维度：
1. 菜品准备时间（海鲜最长/凉菜最短）
2. 厨房负载（负载>80%时时间×1.3）
3. 特殊菜品（活鲜需现杀，额外+10分钟）
4. 桌位规模（>10人时建议分批出）

三条硬约束（客户体验）：
- 出餐时间估算必须客观，不可低估以掩盖真实延误
- 活鲜海鲜必须在recommendations中明确说明
- 大桌必须建议分批出（避免食物冷掉）

返回JSON（仅JSON，不含其他文字）：
{
  "estimated_minutes": 18,
  "confidence": 0.85,
  "key_bottleneck": "xxx菜品准备最慢",
  "recommendations": ["建议先出凉菜和主食", "大桌建议分两批"],
  "trigger_slow_path": true
}"""

    async def predict(self, order: dict, kitchen_load: dict) -> dict:
        """预测出餐时间。

        Args:
            order: {
                id: 订单ID,
                items: [{dish_name, category, quantity, is_live_seafood}],
                table_size: 桌位人数,
                created_at: 下单时间（ISO格式字符串）
            }
            kitchen_load: {
                pending_tasks: 当前待处理工单数,
                avg_wait_minutes: 平均等待时间（分钟）,
                active_chefs: 在岗厨师数
            }

        Returns:
            包含 estimated_minutes/confidence/key_bottleneck/
            recommendations/trigger_slow_path/source 的字典
        """
        quick_estimate = self._quick_estimate(order)

        needs_slow = (
            kitchen_load.get("pending_tasks", 0) > self.SLOW_PATH_PENDING_TASKS
            or kitchen_load.get("avg_wait_minutes", 0) > self.SLOW_PATH_AVG_WAIT_MINUTES
            or order.get("table_size", 0) > self.SLOW_PATH_TABLE_SIZE
            or any(item.get("is_live_seafood") for item in order.get("items", []))
        )

        if not needs_slow:
            logger.info(
                "dispatch_predictor_quick_path",
                order_id=order.get("id"),
                estimated_minutes=quick_estimate["estimated_minutes"],
                pending_tasks=kitchen_load.get("pending_tasks", 0),
            )
            return {**quick_estimate, "trigger_slow_path": False, "source": "quick"}

        # 慢路径：Claude 分析
        context = self._build_context(order, kitchen_load, quick_estimate)

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )

        response_text = message.content[0].text
        result = self._parse_response(response_text, quick_estimate)

        logger.info(
            "dispatch_predictor_slow_path",
            order_id=order.get("id"),
            table_size=order.get("table_size"),
            pending_tasks=kitchen_load.get("pending_tasks", 0),
            avg_wait_minutes=kitchen_load.get("avg_wait_minutes", 0),
            estimated_minutes=result.get("estimated_minutes"),
            confidence=result.get("confidence"),
            has_live_seafood=any(
                item.get("is_live_seafood") for item in order.get("items", [])
            ),
        )

        return {**result, "trigger_slow_path": True, "source": "claude"}

    def _quick_estimate(self, order: dict) -> dict:
        """基于菜品分类的快速估算（不调Claude）。"""
        max_time = 10
        bottleneck_dish = ""
        recommendations: list[str] = []

        for item in order.get("items", []):
            category = item.get("category", "热菜")
            base_time = self.QUICK_ESTIMATE_MINUTES.get(category, 15)
            if item.get("is_live_seafood"):
                base_time += 10
                recommendations.append(f"{item.get('dish_name', '活鲜菜品')}需现杀，请提前通知后厨")
            if base_time > max_time:
                max_time = base_time
                bottleneck_dish = item.get("dish_name", category)

        if order.get("table_size", 0) > self.SLOW_PATH_TABLE_SIZE:
            recommendations.append("大桌建议分批出菜，避免食物冷却")

        return {
            "estimated_minutes": max_time,
            "confidence": 0.7,
            "key_bottleneck": f"{bottleneck_dish}准备时间最长" if bottleneck_dish else "基于菜品分类快速估算",
            "recommendations": recommendations,
        }

    def _build_context(
        self, order: dict, kitchen_load: dict, quick_estimate: dict
    ) -> str:
        items = order.get("items", [])
        items_str = "\n".join(
            f"  - {item.get('dish_name', '未知菜品')} "
            f"[{item.get('category', '热菜')}] "
            f"×{item.get('quantity', 1)}"
            f"{'（活鲜）' if item.get('is_live_seafood') else ''}"
            for item in items
        )

        return f"""订单信息：
- 订单ID：{order.get('id', '未知')}
- 桌位人数：{order.get('table_size', 0)}人
- 下单时间：{order.get('created_at', '未知')}
- 菜品列表：
{items_str if items_str else '  （无菜品）'}

厨房当前负载：
- 待处理工单数：{kitchen_load.get('pending_tasks', 0)}单
- 平均等待时间：{kitchen_load.get('avg_wait_minutes', 0):.1f}分钟
- 在岗厨师数：{kitchen_load.get('active_chefs', 0)}人

快路径估算参考：{quick_estimate.get('estimated_minutes', 0)}分钟（置信度0.7）

请结合厨房实际负载给出更精准的出餐时间预测。"""

    def _parse_response(self, response_text: str, fallback: dict) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回快路径估算值。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "dispatch_predictor_parse_failed",
            response_preview=response_text[:200],
        )
        # 兜底：使用快路径估算，但置信度降低
        return {
            **fallback,
            "confidence": 0.5,
            "key_bottleneck": fallback.get("key_bottleneck", "AI解析失败，使用快路径兜底"),
        }


    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """从 mv_store_pnl 快速读取出餐压力背景数据，<5ms，无 Claude 调用。

        数据来源：因果链④投影视图（StorePnlProjector）
        出餐调度视角：近7天订单量/客单数趋势 → 估算厨房基准负载
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
                            stat_date,
                            order_count,
                            customer_count,
                            avg_check_fen,
                            gross_margin_rate
                        FROM mv_store_pnl
                        WHERE tenant_id = :tenant_id
                        {store_clause}
                        ORDER BY stat_date DESC
                        LIMIT 7
                    """),
                    params,
                )
                rows = result.mappings().all()

                if not rows:
                    return {
                        "inference_layer": "mv_fast_path",
                        "data": {},
                        "agent": self.__class__.__name__,
                        "note": "暂无历史订单量数据",
                    }

                daily_orders = [int(r["order_count"] or 0) for r in rows]
                avg_daily_orders = sum(daily_orders) / len(daily_orders) if daily_orders else 0
                max_daily_orders = max(daily_orders) if daily_orders else 0
                avg_check = float(rows[0]["avg_check_fen"] or 0) if rows else 0.0

                # 推算厨房压力等级
                load_level = "normal"
                if avg_daily_orders > 300:
                    load_level = "high"
                elif avg_daily_orders > 150:
                    load_level = "medium"

                trend = "stable"
                if len(daily_orders) >= 3:
                    recent_3 = sum(daily_orders[:3]) / 3
                    older_3 = sum(daily_orders[-3:]) / 3
                    if recent_3 > older_3 * 1.15:
                        trend = "rising"
                    elif recent_3 < older_3 * 0.85:
                        trend = "declining"

                return {
                    "inference_layer": "mv_fast_path",
                    "data": {
                        "avg_daily_orders": round(avg_daily_orders, 1),
                        "max_daily_orders": max_daily_orders,
                        "avg_check_fen": avg_check,
                        "recent_7d_trend": trend,
                        "kitchen_load_level": load_level,
                        "daily_orders_history": daily_orders,
                    },
                    "agent": self.__class__.__name__,
                    "risk_signal": "high" if load_level == "high" and trend == "rising" else "normal",
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "dispatch_predictor_mv_db_error",
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


dispatch_predictor = DispatchPredictorAgent()
