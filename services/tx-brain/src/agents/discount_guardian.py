"""折扣守护Agent — 实时检测异常折扣，保护毛利底线

工作流程：
1. 接收折扣事件（折扣类型/折扣率/菜品/桌号/操作员）
2. 查询历史折扣数据（同操作员/同时段/同菜品）
3. 调用Claude分析是否异常
4. 记录决策日志（AgentDecisionLog）
5. 返回：允许/警告/拒绝 + 理由
"""
from __future__ import annotations

import json
import re

import structlog

from ..services.model_router import chat as model_chat

logger = structlog.get_logger()


class DiscountGuardianAgent:
    """折扣守护Agent：实时检测异常折扣，保护毛利底线

    三条硬约束校验：
    - 毛利底线：折扣不可使单笔毛利低于设定阈值（默认25%）
    - 权限校验：折扣率不超过操作员授权范围
    - 行为模式：无短时间内异常批量折扣
    """

    SYSTEM_PROMPT = """你是屯象OS的折扣守护智能体。你的职责是分析餐厅收银操作中的折扣是否合规。

三条不可突破的硬约束：
1. 毛利底线：任何折扣不可使单笔毛利低于设定阈值（默认25%）
2. 食安合规：不分析此类问题
3. 客户体验：不分析此类问题

你接收折扣事件，需要判断：
- 折扣率是否超过授权范围（普通员工最高9折，店长最高8折，总经理不限）
- 是否存在异常模式（短时间内大量折扣/特定菜品频繁打折）
- 折扣后毛利率是否仍在阈值以上

返回JSON格式：
{
  "decision": "allow|warn|reject",
  "confidence": 0.0-1.0,
  "reason": "决策理由（中文，30字以内）",
  "risk_factors": ["风险因素列表"],
  "constraints_check": {
    "margin_ok": true/false,
    "authority_ok": true/false,
    "pattern_ok": true/false
  }
}"""

    async def analyze(self, event: dict, history: list[dict]) -> dict:
        """分析折扣事件是否合规。

        Args:
            event: 折扣事件，包含以下字段：
                - operator_id: 操作员ID
                - operator_role: 操作员角色（employee/manager/gm）
                - dish_id: 菜品ID
                - dish_name: 菜品名称
                - original_price_fen: 原价（分）
                - discount_type: 折扣类型
                - discount_rate: 折扣率（0.0-1.0，例如0.9表示九折）
                - table_no: 桌号
                - order_id: 订单ID
                - store_id: 门店ID
                - margin_rate: 菜品毛利率（可选）
            history: 近30条同操作员的折扣记录

        Returns:
            包含 decision/confidence/reason/risk_factors/constraints_check 的字典
        """
        context = self._build_context(event, history)

        message = await model_chat(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
            agent_id="discount_guardian",
            tenant_id=event.get("tenant_id", "unknown"),
        )

        response_text = message.content[0].text
        result = self._parse_response(response_text)

        logger.info(
            "discount_guardian_decision",
            operator_id=event.get("operator_id"),
            order_id=event.get("order_id"),
            store_id=event.get("store_id"),
            decision=result.get("decision"),
            confidence=result.get("confidence"),
            dish_name=event.get("dish_name"),
            discount_rate=event.get("discount_rate"),
        )

        return result

    def _build_context(self, event: dict, history: list[dict]) -> str:
        original_price_fen = event.get("original_price_fen", 0)
        discount_rate = event.get("discount_rate", 1.0)
        discounted_price = original_price_fen * discount_rate / 100

        return f"""折扣事件：
- 操作员：{event.get('operator_id')} ({event.get('operator_role')})
- 菜品：{event.get('dish_name')} 原价 {original_price_fen / 100:.2f}元
- 折扣类型：{event.get('discount_type')} 折扣率：{discount_rate}
- 折后价：{discounted_price:.2f}元
- 桌号：{event.get('table_no')} 订单：{event.get('order_id')}

近期折扣历史（最近{len(history)}条）：
{self._format_history(history)}

菜品毛利率（从dish BOM）：{event.get('margin_rate', '未知')}
"""

    def _format_history(self, history: list[dict]) -> str:
        if not history:
            return "无历史记录"
        lines = []
        for h in history[-10:]:  # 最近10条
            lines.append(
                f"  - {h.get('created_at', '')} "
                f"{h.get('dish_name', '')} "
                f"{h.get('discount_type', '')} "
                f"{h.get('discount_rate', '')} "
                f"{h.get('decision', '')}"
            )
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回安全兜底值。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "discount_guardian_parse_failed",
            response_preview=response_text[:200],
        )
        return {
            "decision": "warn",
            "confidence": 0.5,
            "reason": "AI解析失败，需人工审核",
            "risk_factors": ["响应解析异常"],
            "constraints_check": {
                "margin_ok": None,
                "authority_ok": None,
                "pattern_ok": None,
            },
        }


    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """从 mv_discount_health 快速读取最近折扣健康数据，<5ms，无 Claude 调用。

        数据来源：因果链①投影视图（DiscountHealthProjector）
        无数据时返回空 data + note（调用方按需处理）。
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
                            store_id,
                            stat_date,
                            total_orders,
                            discounted_orders,
                            discount_rate,
                            total_discount_fen,
                            unauthorized_count,
                            leak_types,
                            top_operators,
                            threshold_breaches
                        FROM mv_discount_health
                        WHERE tenant_id = :tenant_id
                        {store_clause}
                        ORDER BY stat_date DESC
                        LIMIT 1
                    """),
                    params,
                )
                row = result.mappings().one_or_none()
                if not row:
                    return {
                        "inference_layer": "mv_fast_path",
                        "data": {},
                        "agent": self.__class__.__name__,
                        "note": "暂无折扣健康数据",
                    }
                data = dict(row._mapping)
                # 转换 Decimal 类型到 float
                if data.get("discount_rate") is not None:
                    data["discount_rate"] = float(data["discount_rate"])
                return {
                    "inference_layer": "mv_fast_path",
                    "data": data,
                    "agent": self.__class__.__name__,
                    "risk_signal": "high" if data.get("unauthorized_count", 0) > 0 or data.get("threshold_breaches", 0) > 0 else "normal",
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "discount_guardian_mv_db_error",
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


discount_guardian = DiscountGuardianAgent()
