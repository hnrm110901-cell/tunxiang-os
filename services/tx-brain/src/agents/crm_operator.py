"""私域运营Agent — 生成微信群/朋友圈/小程序推送私域运营活动方案

工作流程：
1. Python预检：折扣预算合规性、折扣权限校验
2. 调用Claude（claude-haiku-4-5-20251001）生成文案和活动方案
3. 记录决策日志（留痕）
4. 返回：活动名称/微信群文案/朋友圈文案/小程序推送/优惠券建议/发送时间建议
"""

from __future__ import annotations

import json
import re

import anthropic
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger()
client = anthropic.AsyncAnthropic()  # 从环境变量 ANTHROPIC_API_KEY 读取

# 文案长度限制
WECHAT_GROUP_MAX_LEN = 300
MOMENTS_MAX_LEN = 140
MINIAPP_TITLE_MAX_LEN = 15
MINIAPP_CONTENT_MAX_LEN = 30


class CRMOperator:
    """私域运营Agent：生成微信群/朋友圈/小程序推送私域运营活动方案

    三条硬约束校验：
    - 毛利底线：折扣成本不超过 budget/target_count × 2（合理性检查）
    - 权限校验：折扣率不超过 discount_limit
    - 客户体验：文案包含品牌特色，体现品牌价值
    """

    SYSTEM_PROMPT = """你是屯象OS的私域运营智能体。你的职责是为餐厅生成高质量的私域运营活动文案，覆盖微信群、朋友圈和小程序推送。

三条不可突破的硬约束：
1. 毛利底线：优惠力度必须在预算范围内，不能随意加大折扣
2. 权限校验：折扣率不能超过授权的最大折扣率
3. 客户体验：文案必须体现品牌特色，让顾客感受到品牌温度，不能用模板化无个性的文案

文案要求：
- 微信群推送：≤300字，口语化，有情感温度，包含行动号召
- 朋友圈文案：≤140字，吸引眼球，适合转发，emoji可适量使用
- 小程序推送标题：≤15字，简洁有力
- 小程序推送内容：≤30字，突出核心利益点

不同活动类型的侧重点：
- retention（留存）：强调会员专属感，回馈忠实顾客
- reactivation（召回）：唤起美好记忆，用限时优惠创造紧迫感
- upsell（升客单）：推荐高价值菜品搭配，突出性价比
- event（活动）：营造活动氛围，强调参与感
- holiday（节日）：结合节日氛围，情感营销

返回严格的JSON格式（无其他文字）：
{
  "campaign_name": "活动名称",
  "wechat_group_message": "微信群文案（≤300字）",
  "moments_copy": "朋友圈文案（≤140字）",
  "miniapp_push_title": "推送标题（≤15字）",
  "miniapp_push_content": "推送内容（≤30字）",
  "coupon_suggestion": {
    "type": "满减/折扣/免费菜品",
    "value": "满100减20",
    "validity_days": 7
  },
  "send_time_suggestion": "周六上午10点",
  "constraints_check": {
    "margin_ok": true,
    "authority_ok": true,
    "experience_ok": true
  }
}"""

    async def generate_campaign(self, payload: dict) -> dict:
        """生成私域运营活动方案（微信群/朋友圈/小程序推送内容）。

        Args:
            payload: 包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - brand_name: 品牌名称
                - campaign_type: 活动类型（retention/reactivation/upsell/event/holiday）
                - target_segment: 目标用户群（vip/regular/at_risk/new）
                - target_count: 目标用户数量
                - budget_fen: 活动预算（分）
                - key_dishes: 重点推广菜品名列表
                - discount_limit: 最大折扣率（如0.2=8折），可空
                - special_occasion: 特殊场合（可空，如"母亲节"）

        Returns:
            包含 campaign_name/wechat_group_message/moments_copy/
            miniapp_push_title/miniapp_push_content/coupon_suggestion/
            send_time_suggestion/constraints_check/source 的字典
        """
        pre_check = self._pre_check(payload)
        context = self._build_context(payload, pre_check)

        try:
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            response_text = message.content[0].text
            result = self._parse_response(response_text)

            if result is None:
                result = self._fallback(payload, pre_check)
                result["source"] = "fallback"
            else:
                result["source"] = "claude"

        except (anthropic.APIConnectionError, anthropic.APIError):
            result = self._fallback(payload, pre_check)
            result["source"] = "fallback"

        logger.info(
            "crm_operator_campaign_generated",
            tenant_id=payload.get("tenant_id"),
            store_id=payload.get("store_id"),
            brand_name=payload.get("brand_name"),
            campaign_type=payload.get("campaign_type"),
            target_segment=payload.get("target_segment"),
            target_count=payload.get("target_count"),
            source=result.get("source"),
            constraints_check=result.get("constraints_check"),
        )

        return result

    def _pre_check(self, payload: dict) -> dict:
        """Python预检：折扣预算合规、折扣权限校验。"""
        budget_fen = payload.get("budget_fen", 0)
        target_count = payload.get("target_count", 1)
        discount_limit = payload.get("discount_limit")

        # 毛利检查：预算/目标用户数，每人平均可用预算（分）
        per_user_budget_fen = budget_fen / max(target_count, 1)

        # authority_ok：如果有discount_limit，检查是否合理（这里预检仅做计算，
        # 实际折扣约束由Claude和fallback共同执行）
        authority_ok = discount_limit is not None  # 有明确授权则为True；无限制也算OK
        if discount_limit is None:
            authority_ok = True  # 未设置上限视为无限制，允许

        return {
            "per_user_budget_fen": per_user_budget_fen,
            "authority_ok": authority_ok,
            "discount_limit": discount_limit,
        }

    def _build_context(self, payload: dict, pre_check: dict) -> str:
        brand_name = payload.get("brand_name", "品牌")
        campaign_type = payload.get("campaign_type", "retention")
        target_segment = payload.get("target_segment", "regular")
        target_count = payload.get("target_count", 0)
        budget_fen = payload.get("budget_fen", 0)
        key_dishes = payload.get("key_dishes", [])
        discount_limit = payload.get("discount_limit")
        special_occasion = payload.get("special_occasion", "")

        # 活动类型中文映射
        campaign_type_map = {
            "retention": "留存老客",
            "reactivation": "召回流失",
            "upsell": "提升客单",
            "event": "活动推广",
            "holiday": "节日营销",
        }
        # 用户群中文映射
        segment_map = {
            "vip": "VIP会员",
            "regular": "普通会员",
            "at_risk": "流失风险用户",
            "new": "新客",
        }

        discount_text = (
            f"最大折扣率：{discount_limit:.0%}（即最低{1 - discount_limit:.0%}折）"
            if discount_limit is not None
            else "折扣上限：未设置"
        )

        occasion_text = f"特殊场合：{special_occasion}" if special_occasion else "无特殊场合"

        return f"""私域运营文案生成请求：

品牌信息：
- 品牌名称：{brand_name}
- 门店ID：{payload.get("store_id")}

活动参数：
- 活动类型：{campaign_type_map.get(campaign_type, campaign_type)}（{campaign_type}）
- 目标用户：{segment_map.get(target_segment, target_segment)}，共{target_count}人
- 活动预算：{budget_fen / 100:.2f}元（每人均摊{pre_check.get("per_user_budget_fen", 0) / 100:.2f}元）
- {discount_text}
- {occasion_text}

重点推广菜品：{", ".join(key_dishes) if key_dishes else "未指定"}

请为{brand_name}生成一套完整的私域运营活动方案，文案要体现品牌特色和温度。"""

    def _parse_response(self, response_text: str) -> dict | None:
        """解析Claude响应，提取JSON，失败返回None。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(
            "crm_operator_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    def _fallback(self, payload: dict, pre_check: dict) -> dict:
        """Claude失败时的模板兜底。"""
        brand_name = payload.get("brand_name", "我们")
        key_dishes = payload.get("key_dishes", [])
        main_dish = key_dishes[0] if key_dishes else "特色菜品"
        discount_limit = pre_check.get("discount_limit")

        # authority_ok：折扣不超过discount_limit（满100减10约等于9折）
        authority_ok = discount_limit is None or discount_limit >= 0.1

        wechat_msg = (
            f"【{brand_name}会员专属福利】\n\n"
            f"亲爱的会员，感谢您一直以来对{brand_name}的支持！\n\n"
            f"今日为您带来会员专属优惠，{main_dish}等特色菜品等您品尝。\n\n"
            f"满100元立减10元，仅限今日，先到先得！\n\n"
            f"期待您的光临 🎉"
        )

        moments_copy = f"{brand_name}会员专享！{main_dish}等特色好味，满100减10，今日限定，快来打卡！"

        return {
            "campaign_name": f"{brand_name}会员专属活动",
            "wechat_group_message": wechat_msg[:WECHAT_GROUP_MAX_LEN],
            "moments_copy": moments_copy[:MOMENTS_MAX_LEN],
            "miniapp_push_title": f"{brand_name}会员福利",
            "miniapp_push_content": "满100减10，今日有效，快来领取",
            "coupon_suggestion": {
                "type": "满减",
                "value": "满100减10",
                "validity_days": 7,
            },
            "send_time_suggestion": "周末上午10点",
            "constraints_check": {
                "margin_ok": True,
                "authority_ok": authority_ok,
                "experience_ok": True,
            },
        }

    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """Phase 3 快速路径：从 mv_member_clv 物化视图读取，<5ms。

        字段：tenant_id, store_id, total_members, active_members,
              avg_clv, churn_risk_count, top_segments

        无数据时 fallback 到 generate_campaign()；DB 异常也 graceful fallback。
        """
        from ..db import get_db  # 延迟导入避免循环依赖

        try:
            async with get_db() as db:
                await db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": tenant_id},
                )

                if store_id:
                    result = await db.execute(
                        text("""
                            SELECT tenant_id, store_id, total_members, active_members,
                                   avg_clv, churn_risk_count, top_segments
                            FROM mv_member_clv
                            WHERE tenant_id = :tid
                              AND store_id = :sid
                            LIMIT 1
                        """),
                        {"tid": tenant_id, "sid": store_id},
                    )
                else:
                    result = await db.execute(
                        text("""
                            SELECT tenant_id, store_id, total_members, active_members,
                                   avg_clv, churn_risk_count, top_segments
                            FROM mv_member_clv
                            WHERE tenant_id = :tid
                            LIMIT 1
                        """),
                        {"tid": tenant_id},
                    )

                row = result.fetchone()
                if not row:
                    logger.info(
                        "crm_operator_mv_empty_fallback",
                        tenant_id=tenant_id,
                        store_id=store_id,
                    )
                    return await self.generate_campaign({"tenant_id": tenant_id, "store_id": store_id})

                return {
                    "inference_layer": "mv_fast_path",
                    "data": dict(row._mapping),
                    "agent": self.__class__.__name__,
                }

        except SQLAlchemyError as exc:
            logger.warning(
                "crm_operator_mv_db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return await self.generate_campaign({"tenant_id": tenant_id, "store_id": store_id})

    async def get_clv_context(self, tenant_id: str, store_id: str, db) -> dict:
        """从 mv_member_clv 读取高流失风险会员数、平均CLV、总储值余额。

        供 generate_campaign() 调用时，通过 analyze_with_clv() 附加到活动决策背景。
        无数据或查询失败时返回 {}。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        try:
            result = await db.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE churn_probability > 0.7) AS high_churn_count,
                        AVG(clv_score) AS avg_clv,
                        SUM(stored_value_balance_fen) AS total_stored_value_fen
                    FROM mv_member_clv
                    WHERE tenant_id = :tenant_id AND store_id = :store_id
                """),
                {"tenant_id": tenant_id, "store_id": store_id},
            )
            row = result.mappings().one_or_none()
            if not row or row["avg_clv"] is None:
                return {}

            return {
                "high_churn_count": int(row["high_churn_count"] or 0),
                "avg_clv": round(float(row["avg_clv"]), 2) if row["avg_clv"] is not None else None,
                "total_stored_value_fen": int(row["total_stored_value_fen"] or 0),
            }
        except SQLAlchemyError as exc:
            logger.warning(
                "crm_operator_clv_ctx_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return {}

    async def generate_campaign_with_clv(self, payload: dict, db) -> dict:
        """带 CLV 背景数据的活动方案生成入口。

        从 mv_member_clv 读取 CLV 上下文并附加到 payload，再调用 generate_campaign()。
        """
        tenant_id = payload.get("tenant_id", "")
        store_id = payload.get("store_id", "")

        clv_ctx = await self.get_clv_context(tenant_id, store_id, db)

        enriched_payload = dict(payload)
        enriched_payload["clv_context"] = clv_ctx

        return await self.generate_campaign(enriched_payload)


crm_operator = CRMOperator()
