"""会员洞察Agent — 分析会员消费行为，生成个性化洞察

使用 Claude Haiku 节省成本，适合高频的会员分析场景。
"""
from __future__ import annotations

import json
import re

import structlog

from ..services.model_router import chat as model_chat

logger = structlog.get_logger()


class MemberInsightAgent:
    """会员洞察Agent：分析消费行为，生成个性化洞察

    输出帮助门店员工：
    1. 了解VIP会员的偏好（常点菜品/用餐时间/消费水平）
    2. 识别流失风险会员（长期未消费）
    3. 推荐适合的菜品和活动
    """

    SYSTEM_PROMPT = """你是屯象OS的会员洞察智能体。分析餐厅会员的消费行为，生成实用的经营洞察。

你的输出应该帮助门店员工：
1. 了解VIP会员的偏好（常点菜品/用餐时间/消费水平）
2. 识别流失风险会员（长期未消费）
3. 推荐适合的菜品和活动

返回JSON格式：
{
  "member_segment": "vip|regular|at_risk|new",
  "key_insights": ["洞察1", "洞察2"],
  "recommended_dishes": ["菜品1", "菜品2"],
  "recommended_actions": ["行动1"],
  "next_visit_prediction": "预计N天内会来"
}

注意：
- key_insights 最多3条，每条20字以内
- recommended_dishes 2-3个推荐菜品
- recommended_actions 1-2个员工行动建议
- next_visit_prediction 简短预测，流失风险高时说明"""

    async def analyze(self, member: dict, orders: list[dict]) -> dict:
        """分析会员消费行为，返回洞察结果。

        Args:
            member: 会员信息，包含以下字段：
                - id: 会员ID
                - name: 姓名（可为脱敏）
                - phone_masked: 脱敏手机号
                - level: 会员等级
                - total_spend_fen: 累计消费（分）
                - visit_count: 消费次数
                - last_visit_date: 上次消费日期（ISO格式字符串）
                - points: 积分余额
            orders: 近12个月订单列表（含菜品明细，每条含 items 列表）

        Returns:
            包含 member_segment/key_insights/recommended_dishes/
            recommended_actions/next_visit_prediction 的字典
        """
        context = self._build_context(member, orders)

        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )

        response_text = message.content[0].text
        result = self._parse_response(response_text)

        logger.info(
            "member_insight_generated",
            member_id=member.get("id"),
            member_level=member.get("level"),
            member_segment=result.get("member_segment"),
            order_count=len(orders),
        )

        return result

    def _build_context(self, member: dict, orders: list[dict]) -> str:
        # 统计常点菜品
        dish_counts: dict[str, int] = {}
        for order in orders:
            for item in order.get("items", []):
                name = item.get("dish_name", "")
                if name:
                    dish_counts[name] = dish_counts.get(name, 0) + 1

        top_dishes = sorted(dish_counts.items(), key=lambda x: -x[1])[:5]
        top_dishes_str = (
            ", ".join([f"{d[0]}({d[1]}次)" for d in top_dishes])
            if top_dishes
            else "暂无记录"
        )

        total_spend_fen = member.get("total_spend_fen", 0)
        visit_count = max(len(orders), 1)
        avg_spend_per_visit = total_spend_fen / 100 / visit_count

        return f"""会员信息：
- 等级：{member.get('level', '普通会员')}
- 累计消费：{total_spend_fen / 100:.0f}元
- 消费次数：{member.get('visit_count', 0)}次
- 上次消费：{member.get('last_visit_date', '未知')}
- 积分余额：{member.get('points', 0)}分

近12个月消费记录：{len(orders)}笔订单
常点菜品：{top_dishes_str}
月均消费：{avg_spend_per_visit:.0f}元/次

请分析该会员的特征和推荐策略。"""

    def _parse_response(self, response_text: str) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回安全兜底值。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "member_insight_parse_failed",
            response_preview=response_text[:200],
        )
        return {
            "member_segment": "regular",
            "key_insights": [],
            "recommended_dishes": [],
            "recommended_actions": [],
            "next_visit_prediction": "数据不足，无法预测",
        }


    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """从 mv_member_clv 快速读取会员 CLV 聚合数据，<5ms，无 Claude 调用。

        数据来源：因果链⑤投影视图（MemberClvProjector）
        返回：高流失风险会员数 + 平均CLV + 分层分布 + 储值余额合计
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

                result = await db.execute(
                    text("""
                        SELECT
                            COUNT(*) AS total_members,
                            COUNT(*) FILTER (WHERE churn_probability > 0.7) AS high_churn_count,
                            COUNT(*) FILTER (WHERE churn_probability BETWEEN 0.4 AND 0.7) AS medium_churn_count,
                            AVG(clv_fen) AS avg_clv_fen,
                            SUM(stored_value_balance_fen) AS total_stored_value_fen,
                            COUNT(*) FILTER (WHERE rfm_segment = 'champions') AS champions_count,
                            COUNT(*) FILTER (WHERE rfm_segment = 'at_risk') AS at_risk_count,
                            AVG(visit_count) AS avg_visit_count
                        FROM mv_member_clv
                        WHERE tenant_id = :tenant_id
                    """),
                    params,
                )
                row = result.mappings().one_or_none()

                if not row or row["total_members"] == 0:
                    return {
                        "inference_layer": "mv_fast_path",
                        "data": {},
                        "agent": self.__class__.__name__,
                        "note": "暂无会员 CLV 数据",
                    }

                data = {
                    "total_members": int(row["total_members"] or 0),
                    "high_churn_count": int(row["high_churn_count"] or 0),
                    "medium_churn_count": int(row["medium_churn_count"] or 0),
                    "avg_clv_fen": round(float(row["avg_clv_fen"]), 2) if row["avg_clv_fen"] else 0.0,
                    "total_stored_value_fen": int(row["total_stored_value_fen"] or 0),
                    "champions_count": int(row["champions_count"] or 0),
                    "at_risk_count": int(row["at_risk_count"] or 0),
                    "avg_visit_count": round(float(row["avg_visit_count"]), 1) if row["avg_visit_count"] else 0.0,
                }

                # 流失风险高于20%触发预警
                churn_rate = data["high_churn_count"] / max(data["total_members"], 1)
                risk_signal = "high" if churn_rate > 0.20 else ("medium" if churn_rate > 0.10 else "normal")

                return {
                    "inference_layer": "mv_fast_path",
                    "data": data,
                    "agent": self.__class__.__name__,
                    "risk_signal": risk_signal,
                    "churn_rate": round(churn_rate, 4),
                }
        except SQLAlchemyError as exc:
            logger.warning(
                "member_insight_mv_db_error",
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


member_insight = MemberInsightAgent()
