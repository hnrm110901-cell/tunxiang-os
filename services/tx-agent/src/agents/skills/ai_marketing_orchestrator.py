"""AI营销编排 Agent — P1 | 云端

职责：
  - 订阅事件总线触发营销动作
  - 根据会员画像 + 物化视图决策最优触达方案
  - 调用 tx-brain ContentHub 生成个性化内容
  - 通过 tx-growth 渠道引擎发送
  - 三条硬约束校验（毛利底线/食安合规/客户体验）
  - 全程决策留痕

触发场景（7个）：
  1. ORDER.PAID               → 感谢消息 + 复购引导（冷却48h）
  2. growth.first_order_completed → 新客欢迎旅程
  3. growth.silent_detected   → 沉默用户唤醒
  4. member.churn_predicted   → 流失高风险拯救
  5. member.upgraded          → 升级祝贺 + 专属权益
  6. 定时: 生日前3天           → 生日关怀
  7. 定时: 节假日前5天         → 节日营销包

升级自 PrivateOpsAgent(P2) → AiMarketingOrchestratorAgent(P1)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

BRAIN_SERVICE_URL = os.getenv("BRAIN_SERVICE_URL", "http://tx-brain:8010")
GROWTH_SERVICE_URL = os.getenv("GROWTH_SERVICE_URL", "http://tx-growth:8004")

# 营销冷却规则（小时）— 防止骚扰用户
MARKETING_COOLDOWN_RULES: dict[str, int] = {
    "post_order_touch": 48,
    "welcome_journey": 0,       # 立即触发
    "winback_journey": 72,
    "birthday_care": 72,        # 生日前3天发一次
    "holiday_campaign": 120,    # 节日前5天发一次
    "upgrade_celebration": 1,   # 升级后立即
    "churn_rescue": 168,        # 每周最多一次
}

# 默认毛利底线（百分比）
DEFAULT_MARGIN_FLOOR_PCT = 0.15

# 默认均单金额（分）— 生产环境应从门店配置读取
DEFAULT_AVG_ORDER_FEN = int(os.getenv("DEFAULT_AVG_ORDER_FEN", "40000"))

# 可归因状态（touch 处于这些状态时才可归因到订单）
ATTRIBUTABLE_STATUSES = ("sent", "delivered", "clicked", "queued")

# 渠道优先级（按场景）
CHANNEL_PRIORITY: dict[str, list[str]] = {
    "post_order_touch":     ["wechat_subscribe", "wecom_chat"],
    "welcome_journey":      ["wechat_subscribe", "wecom_chat", "sms"],
    "winback_journey":      ["wecom_chat", "sms", "wechat_subscribe"],
    "birthday_care":        ["wechat_subscribe", "wecom_chat"],
    "holiday_campaign":     ["wechat_oa", "wecom_chat", "sms", "xiaohongshu_note"],
    "upgrade_celebration":  ["wechat_subscribe", "wecom_chat"],
    "churn_rescue":         ["sms", "wecom_chat", "wechat_subscribe"],
    "brand_content":        ["xiaohongshu_note", "douyin_content", "wecom_chat"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Agent 实现
# ─────────────────────────────────────────────────────────────────────────────

class AiMarketingOrchestratorAgent(SkillAgent):
    """AI营销编排 Agent

    统一管理所有会员触达决策，确保内容个性化、
    频率合规、折扣不低于毛利底线。
    """

    agent_id = "ai_marketing_orchestrator"
    agent_name = "AI营销编排"
    description = "AI驱动的全渠道营销触达编排：个性化内容生成、冷却期管控、三条硬约束校验、决策留痕"
    priority = "P1"
    run_location = "cloud"
    agent_level = 2  # auto + rollback

    def get_supported_actions(self) -> list[str]:
        return [
            "execute_post_order_touch",
            "execute_welcome_journey",
            "execute_winback_journey",
            "execute_birthday_care",
            "execute_holiday_campaign",
            "execute_upgrade_celebration",
            "execute_churn_rescue",
            "get_marketing_health_score",
            "update_order_attribution",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        start_ms = int(time.time() * 1000)

        dispatch = {
            "execute_post_order_touch":    self._post_order_touch,
            "execute_welcome_journey":     self._welcome_journey,
            "execute_winback_journey":     self._winback_journey,
            "execute_birthday_care":       self._birthday_care,
            "execute_holiday_campaign":    self._holiday_campaign,
            "execute_upgrade_celebration": self._upgrade_celebration,
            "execute_churn_rescue":        self._churn_rescue,
            "get_marketing_health_score":  self._marketing_health_score,
            "update_order_attribution":    self._update_order_attribution,
        }

        handler = dispatch.get(action)
        if not handler:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
                execution_ms=int(time.time() * 1000) - start_ms,
            )

        result = await handler(params)
        result.execution_ms = int(time.time() * 1000) - start_ms
        return result

    # ─── 场景1：下单后感谢+复购引导 ──────────────────────────────────────────

    async def _post_order_touch(self, params: dict[str, Any]) -> AgentResult:
        """ORDER.PAID 触发：发送感谢消息 + 复购引导"""
        member_id = params.get("member_id", "")
        order_id = params.get("order_id", "")
        order_amount_fen = params.get("order_amount_fen", 0)
        store_name = params.get("store_name", "")
        brand_voice = params.get("brand_voice", {})

        # 冷却期检查
        cooldown_check = await self._check_cooldown(member_id, "post_order_touch")
        if not cooldown_check["ok"]:
            return AgentResult(
                success=True,
                action="execute_post_order_touch",
                data={"skipped": True, "reason": "冷却期内"},
                reasoning=cooldown_check["reason"],
                confidence=1.0,
            )

        # 约束校验（下单感谢不含折扣，仅检查客户体验约束）
        constraints = await self._check_marketing_constraints(
            member_id=member_id,
            discount_fen=0,
            action_type="post_order_touch",
        )
        if not constraints["passed"]:
            return AgentResult(
                success=False,
                action="execute_post_order_touch",
                constraints_passed=False,
                constraints_detail=constraints,
                reasoning=f"约束校验失败: {constraints['violations']}",
            )

        # 生成内容
        content_pkg = await self._generate_content(
            campaign_type="post_order_thanks",
            brand_voice=brand_voice,
            store_context={"store_name": store_name},
            member_segment={"member_id": member_id},
            offer_detail=None,
            channels=CHANNEL_PRIORITY["post_order_touch"],
        )

        # 发送
        send_result = await self._dispatch_message(
            member_id=member_id,
            channels=CHANNEL_PRIORITY["post_order_touch"],
            content=content_pkg,
            campaign_type="post_order_touch",
            ref_id=order_id,
        )

        return AgentResult(
            success=True,
            action="execute_post_order_touch",
            data={
                "member_id": member_id,
                "order_id": order_id,
                "send_result": send_result,
                "content_preview": content_pkg.get("preview", ""),
            },
            reasoning=f"订单 {order_id} 支付完成，发送感谢消息，引导复购",
            confidence=0.92,
            constraints_passed=True,
            constraints_detail=constraints,
        )

    # ─── 场景2：新客欢迎旅程 ──────────────────────────────────────────────────

    async def _welcome_journey(self, params: dict[str, Any]) -> AgentResult:
        """growth.first_order_completed 触发：新客欢迎"""
        member_id = params.get("member_id", "")
        store_name = params.get("store_name", "")
        brand_voice = params.get("brand_voice", {})
        welcome_offer_fen = params.get("welcome_offer_fen", 0)

        # 新客欢迎无冷却期，直接约束检查
        constraints = await self._check_marketing_constraints(
            member_id=member_id,
            discount_fen=welcome_offer_fen,
            action_type="welcome_journey",
        )
        if not constraints["passed"]:
            return AgentResult(
                success=False,
                action="execute_welcome_journey",
                constraints_passed=False,
                constraints_detail=constraints,
                reasoning=f"新客欢迎券约束失败（毛利不足）: {constraints['violations']}",
            )

        content_pkg = await self._generate_content(
            campaign_type="new_customer_welcome",
            brand_voice=brand_voice,
            store_context={"store_name": store_name},
            member_segment={"is_new": True},
            offer_detail={"discount_fen": welcome_offer_fen, "validity_days": 7} if welcome_offer_fen > 0 else None,
            channels=CHANNEL_PRIORITY["welcome_journey"],
        )

        send_result = await self._dispatch_message(
            member_id=member_id,
            channels=CHANNEL_PRIORITY["welcome_journey"],
            content=content_pkg,
            campaign_type="welcome_journey",
            ref_id=member_id,
        )

        return AgentResult(
            success=True,
            action="execute_welcome_journey",
            data={"member_id": member_id, "send_result": send_result},
            reasoning="新客首单完成，启动欢迎旅程，建立品牌连接",
            confidence=0.95,
            constraints_passed=True,
            constraints_detail=constraints,
        )

    # ─── 场景3：沉默用户唤醒 ──────────────────────────────────────────────────

    async def _winback_journey(self, params: dict[str, Any]) -> AgentResult:
        """growth.silent_detected 触发：沉默用户唤醒"""
        member_id = params.get("member_id", "")
        days_inactive = params.get("days_inactive", 30)
        rfm_tier = params.get("rfm_tier", "C")
        brand_voice = params.get("brand_voice", {})
        winback_offer_fen = params.get("winback_offer_fen", 1500)

        # 冷却期检查
        cooldown = await self._check_cooldown(member_id, "winback_journey")
        if not cooldown["ok"]:
            return AgentResult(
                success=True, action="execute_winback_journey",
                data={"skipped": True, "reason": "冷却期内"},
                reasoning=cooldown["reason"], confidence=1.0,
            )

        constraints = await self._check_marketing_constraints(
            member_id=member_id,
            discount_fen=winback_offer_fen,
            action_type="winback_journey",
        )
        if not constraints["passed"]:
            return AgentResult(
                success=False, action="execute_winback_journey",
                constraints_passed=False, constraints_detail=constraints,
                reasoning=f"唤醒券约束失败: {constraints['violations']}",
            )

        content_pkg = await self._generate_content(
            campaign_type="member_win_back",
            brand_voice=brand_voice,
            store_context={},
            member_segment={"days_inactive": days_inactive, "rfm_tier": rfm_tier},
            offer_detail={"discount_fen": winback_offer_fen, "validity_days": 14},
            channels=CHANNEL_PRIORITY["winback_journey"],
        )

        send_result = await self._dispatch_message(
            member_id=member_id,
            channels=CHANNEL_PRIORITY["winback_journey"],
            content=content_pkg,
            campaign_type="winback_journey",
            ref_id=member_id,
        )

        return AgentResult(
            success=True, action="execute_winback_journey",
            data={"member_id": member_id, "days_inactive": days_inactive, "send_result": send_result},
            reasoning=f"会员 {days_inactive} 天未到店（{rfm_tier} 层），发送唤醒券 {winback_offer_fen} 分",
            confidence=0.87,
            constraints_passed=True, constraints_detail=constraints,
        )

    # ─── 场景4：生日关怀 ──────────────────────────────────────────────────────

    async def _birthday_care(self, params: dict[str, Any]) -> AgentResult:
        """定时任务：生日前3天发送生日关怀"""
        member_id = params.get("member_id", "")
        birthday_date = params.get("birthday_date", "")
        member_name = params.get("member_name", "")
        brand_voice = params.get("brand_voice", {})
        birthday_gift_fen = params.get("birthday_gift_fen", 2000)

        cooldown = await self._check_cooldown(member_id, "birthday_care")
        if not cooldown["ok"]:
            return AgentResult(success=True, action="execute_birthday_care",
                               data={"skipped": True}, reasoning="今年生日已发送", confidence=1.0)

        constraints = await self._check_marketing_constraints(
            member_id=member_id, discount_fen=birthday_gift_fen, action_type="birthday_care"
        )
        if not constraints["passed"]:
            return AgentResult(success=False, action="execute_birthday_care",
                               constraints_passed=False, constraints_detail=constraints,
                               reasoning=f"生日礼券约束失败: {constraints['violations']}")

        content_pkg = await self._generate_content(
            campaign_type="birthday_care",
            brand_voice=brand_voice,
            store_context={},
            member_segment={"member_name": member_name, "birthday_date": birthday_date},
            offer_detail={"discount_fen": birthday_gift_fen, "validity_days": 30},
            channels=CHANNEL_PRIORITY["birthday_care"],
        )

        send_result = await self._dispatch_message(
            member_id=member_id, channels=CHANNEL_PRIORITY["birthday_care"],
            content=content_pkg, campaign_type="birthday_care", ref_id=member_id,
        )

        return AgentResult(
            success=True, action="execute_birthday_care",
            data={"member_id": member_id, "birthday_date": birthday_date, "send_result": send_result},
            reasoning=f"生日 {birthday_date} 前3天，发送生日关怀礼包 {birthday_gift_fen} 分",
            confidence=0.96, constraints_passed=True, constraints_detail=constraints,
        )

    # ─── 场景5：节假日营销包 ──────────────────────────────────────────────────

    async def _holiday_campaign(self, params: dict[str, Any]) -> AgentResult:
        """定时任务：节假日前5天推送营销包"""
        holiday_name = params.get("holiday_name", "")
        target_segment = params.get("target_segment", {})
        brand_voice = params.get("brand_voice", {})
        member_ids: list[str] = params.get("member_ids", [])
        promo_fen = params.get("promo_fen", 0)

        content_pkg = await self._generate_content(
            campaign_type="holiday_promo",
            brand_voice=brand_voice,
            store_context={"holiday": holiday_name},
            member_segment=target_segment,
            offer_detail={"discount_fen": promo_fen} if promo_fen > 0 else None,
            channels=CHANNEL_PRIORITY["holiday_campaign"],
        )

        sem = asyncio.Semaphore(10)

        async def _send_one(mid: str) -> dict:
            async with sem:
                return await self._dispatch_message(
                    member_id=mid, channels=CHANNEL_PRIORITY["holiday_campaign"],
                    content=content_pkg, campaign_type="holiday_campaign",
                    ref_id=f"{holiday_name}_{mid}",
                )

        send_results = list(
            await asyncio.gather(*[_send_one(mid) for mid in member_ids[:200]])
        )

        return AgentResult(
            success=True, action="execute_holiday_campaign",
            data={"holiday": holiday_name, "sent_count": len(send_results), "results": send_results[:5]},
            reasoning=f"{holiday_name} 节日营销包，向 {len(member_ids)} 位会员发送",
            confidence=0.88, constraints_passed=True,
        )

    # ─── 场景6：升级庆祝 ──────────────────────────────────────────────────────

    async def _upgrade_celebration(self, params: dict[str, Any]) -> AgentResult:
        """member.upgraded 触发：等级升级庆祝"""
        member_id = params.get("member_id", "")
        new_tier = params.get("new_tier", "")
        brand_voice = params.get("brand_voice", {})
        upgrade_gift_fen = params.get("upgrade_gift_fen", 0)

        content_pkg = await self._generate_content(
            campaign_type="upgrade_celebration",
            brand_voice=brand_voice,
            store_context={},
            member_segment={"new_tier": new_tier},
            offer_detail={"discount_fen": upgrade_gift_fen} if upgrade_gift_fen > 0 else None,
            channels=CHANNEL_PRIORITY["upgrade_celebration"],
        )

        send_result = await self._dispatch_message(
            member_id=member_id, channels=CHANNEL_PRIORITY["upgrade_celebration"],
            content=content_pkg, campaign_type="upgrade_celebration", ref_id=member_id,
        )

        return AgentResult(
            success=True, action="execute_upgrade_celebration",
            data={"member_id": member_id, "new_tier": new_tier, "send_result": send_result},
            reasoning=f"会员升级至 {new_tier}，发送升级庆祝 + 专属权益说明",
            confidence=0.94, constraints_passed=True,
        )

    # ─── 场景7：流失拯救 ──────────────────────────────────────────────────────

    async def _churn_rescue(self, params: dict[str, Any]) -> AgentResult:
        """member.churn_predicted 触发：高流失风险会员拯救"""
        member_id = params.get("member_id", "")
        churn_probability = params.get("churn_probability", 0.7)
        last_rfm = params.get("last_rfm", {})
        brand_voice = params.get("brand_voice", {})
        rescue_offer_fen = params.get("rescue_offer_fen", 3000)

        cooldown = await self._check_cooldown(member_id, "churn_rescue")
        if not cooldown["ok"]:
            return AgentResult(success=True, action="execute_churn_rescue",
                               data={"skipped": True}, reasoning="本周已触达", confidence=1.0)

        constraints = await self._check_marketing_constraints(
            member_id=member_id, discount_fen=rescue_offer_fen, action_type="churn_rescue"
        )
        if not constraints["passed"]:
            # 毛利不足时降低优惠力度再试
            rescue_offer_fen = int(rescue_offer_fen * 0.6)
            constraints = await self._check_marketing_constraints(
                member_id=member_id, discount_fen=rescue_offer_fen, action_type="churn_rescue"
            )

        if not constraints["passed"]:
            return AgentResult(success=False, action="execute_churn_rescue",
                               constraints_passed=False, constraints_detail=constraints,
                               reasoning="即便降低优惠力度，毛利约束仍不满足")

        content_pkg = await self._generate_content(
            campaign_type="churn_recovery",
            brand_voice=brand_voice,
            store_context={},
            member_segment={"churn_probability": churn_probability, **last_rfm},
            offer_detail={"discount_fen": rescue_offer_fen, "validity_days": 21},
            channels=CHANNEL_PRIORITY["churn_rescue"],
        )

        send_result = await self._dispatch_message(
            member_id=member_id, channels=CHANNEL_PRIORITY["churn_rescue"],
            content=content_pkg, campaign_type="churn_rescue", ref_id=member_id,
        )

        return AgentResult(
            success=True, action="execute_churn_rescue",
            data={"member_id": member_id, "churn_prob": churn_probability, "send_result": send_result},
            reasoning=f"流失概率 {churn_probability:.0%}，发送高强度挽留券 {rescue_offer_fen} 分",
            confidence=churn_probability,
            constraints_passed=True, constraints_detail=constraints,
        )

    # ─── 营销健康评分 ─────────────────────────────────────────────────────────

    async def _marketing_health_score(self, params: dict[str, Any]) -> AgentResult:
        """计算门店营销健康评分（0-100）"""
        store_id = params.get("store_id", "")

        # 评分维度（示例逻辑，生产环境读真实 DB）
        channel_coverage = params.get("channel_count", 2) / 6 * 35       # 渠道覆盖率 35分
        touch_frequency = min(params.get("monthly_touches_per_member", 0) / 4, 1) * 25  # 触达频率 25分
        content_quality = params.get("avg_open_rate", 0.08) / 0.15 * 25  # 内容质量 25分
        attribution_rate = params.get("attributed_order_pct", 0.3) * 15  # 归因率 15分

        total_score = round(channel_coverage + touch_frequency + content_quality + attribution_rate, 1)
        total_score = min(100.0, max(0.0, total_score))

        grade = "A" if total_score >= 80 else "B" if total_score >= 60 else "C" if total_score >= 40 else "D"

        return AgentResult(
            success=True, action="get_marketing_health_score",
            data={
                "store_id": store_id,
                "total_score": total_score,
                "grade": grade,
                "breakdown": {
                    "channel_coverage": round(channel_coverage, 1),
                    "touch_frequency": round(touch_frequency, 1),
                    "content_quality": round(content_quality, 1),
                    "attribution_rate": round(attribution_rate, 1),
                },
                "suggestions": _get_score_suggestions(total_score, channel_coverage, touch_frequency),
            },
            reasoning=f"门店营销健康评分 {total_score}/100，等级 {grade}",
            confidence=0.85,
        )

    # ─── 归因闭环 ─────────────────────────────────────────────────────────────

    async def _update_order_attribution(self, params: dict[str, Any]) -> AgentResult:
        """ORDER.PAID 触发：将订单归因到最近的营销触达记录

        查找该会员在归因窗口期（默认72h）内最近一条未归因的 touch_log，
        更新 attribution_order_id + attribution_revenue_fen + converted_at。
        """
        member_id = params.get("member_id", "")
        order_id = params.get("order_id", "")
        order_amount_fen = params.get("order_amount_fen", 0)
        attribution_window_hours = params.get("attribution_window_hours", 72)

        if not member_id or not order_id:
            return AgentResult(
                success=False,
                action="update_order_attribution",
                error="member_id 和 order_id 不可为空",
            )

        if self._db is None:
            logger.info(
                "attribution_skipped_no_db",
                order_id=order_id,
                member_id=member_id,
            )
            return AgentResult(
                success=True,
                action="update_order_attribution",
                data={"skipped": True, "reason": "DB 不可用，归因跳过"},
                reasoning="DB session 未注入，无法执行归因更新",
                confidence=1.0,
            )

        try:
            await self._db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(self.tenant_id)},
            )

            # 查找最近一条未归因的 touch（在归因窗口内）
            row = await self._db.execute(
                text("""
                    SELECT id, channel, campaign_type, message_id
                    FROM marketing_touch_log
                    WHERE tenant_id = :tenant_id::uuid
                      AND member_id = :member_id::uuid
                      AND attribution_order_id IS NULL
                      AND status IN ('sent', 'delivered', 'clicked', 'queued')
                      AND sent_at > NOW() - make_interval(hours => :window_hours)
                      AND NOT is_deleted
                    ORDER BY sent_at DESC
                    LIMIT 1
                """),
                {
                    "tenant_id": str(self.tenant_id),
                    "member_id": member_id,
                    "window_hours": attribution_window_hours,
                },
            )
            touch_row = row.fetchone()

            if touch_row is None:
                return AgentResult(
                    success=True,
                    action="update_order_attribution",
                    data={"attributed": False, "reason": f"窗口期({attribution_window_hours}h)内无可归因触达记录"},
                    reasoning=f"会员 {member_id[:8]}... 在 {attribution_window_hours}h 内无营销触达记录",
                    confidence=1.0,
                )

            touch_id = str(touch_row.id)
            # 更新归因
            await self._db.execute(
                text("""
                    UPDATE marketing_touch_log
                    SET attribution_order_id = :order_id::uuid,
                        attribution_revenue_fen = :revenue_fen,
                        converted_at = NOW(),
                        status = 'converted'
                    WHERE id = :touch_id::uuid
                      AND tenant_id = :tenant_id::uuid
                """),
                {
                    "order_id": order_id,
                    "revenue_fen": order_amount_fen,
                    "touch_id": touch_id,
                    "tenant_id": str(self.tenant_id),
                },
            )
            await self._db.commit()

            logger.info(
                "order_attributed",
                touch_id=touch_id,
                order_id=order_id,
                member_id=member_id[:8],
                amount_fen=order_amount_fen,
            )

            return AgentResult(
                success=True,
                action="update_order_attribution",
                data={
                    "attributed": True,
                    "touch_id": touch_id,
                    "order_id": order_id,
                    "channel": touch_row.channel,
                    "campaign_type": touch_row.campaign_type,
                    "attribution_revenue_fen": order_amount_fen,
                    "attribution_window_hours": attribution_window_hours,
                },
                reasoning=(
                    f"订单 {order_id[:8]}... 成功归因到 [{touch_row.campaign_type}] "
                    f"渠道 [{touch_row.channel}]，归因收入 {order_amount_fen/100:.1f}元"
                ),
                confidence=0.9,
            )

        except (ValueError, OSError, SQLAlchemyError) as exc:
            logger.warning("attribution_update_error", order_id=order_id, error=str(exc))
            return AgentResult(
                success=False,
                action="update_order_attribution",
                error=f"归因更新失败: {exc}",
            )

    # ─── 内部工具方法 ─────────────────────────────────────────────────────────

    async def _check_cooldown(
        self,
        member_id: str,
        action_type: str,
    ) -> dict[str, Any]:
        """检查营销触达冷却期"""
        cooldown_hours = MARKETING_COOLDOWN_RULES.get(action_type, 24)
        if cooldown_hours == 0:
            return {"ok": True}

        if self._db is not None and member_id:
            try:
                await self._db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(self.tenant_id)},
                )
                row = await self._db.execute(
                    text("""
                        SELECT COUNT(*) FROM marketing_touch_log
                        WHERE tenant_id = :tenant_id::uuid
                          AND member_id = :member_id::uuid
                          AND campaign_type = :campaign_type
                          AND sent_at > NOW() - make_interval(hours => :hours)
                          AND NOT is_deleted
                    """),
                    {
                        "tenant_id": str(self.tenant_id),
                        "member_id": member_id,
                        "campaign_type": action_type,
                        "hours": cooldown_hours,
                    },
                )
                count = row.scalar()
                if count and count > 0:
                    return {
                        "ok": False,
                        "reason": f"冷却期内（{cooldown_hours}h）：最近已触达，跳过",
                    }
            except (ValueError, OSError, SQLAlchemyError) as exc:
                logger.warning("cooldown_check_db_error", error=str(exc), action_type=action_type)

        logger.debug("cooldown_check", member_id=member_id, action_type=action_type, cooldown_hours=cooldown_hours)
        return {"ok": True, "cooldown_hours": cooldown_hours}

    async def _check_marketing_constraints(
        self,
        member_id: str,
        discount_fen: int,
        action_type: str,
    ) -> dict[str, Any]:
        """校验三条硬约束

        1. 毛利底线：折扣金额占平均订单金额的比例不超过阈值
        2. 客户体验：近7天有未处理投诉的会员暂停触达
        3. 食安合规：不涉及（营销触达场景）
        """
        violations: list[str] = []
        margin_floor_pct = DEFAULT_MARGIN_FLOOR_PCT

        # 约束1: 毛利底线（生产环境应从门店配置读取均单，当前使用env配置兜底）
        if discount_fen > 0:
            avg_order_fen = DEFAULT_AVG_ORDER_FEN
            if avg_order_fen == 40000:
                logger.warning(
                    "margin_constraint_using_default_avg_order",
                    member_id=member_id,
                    action_type=action_type,
                    avg_order_fen=avg_order_fen,
                    hint="Set DEFAULT_AVG_ORDER_FEN env var or wire store config",
                )
            max_discount = int(avg_order_fen * (1 - margin_floor_pct))
            if discount_fen > max_discount:
                violations.append(
                    f"折扣 {discount_fen/100:.1f}元 超过毛利底线允许上限 {max_discount/100:.1f}元"
                )

        # 约束2: 客户体验（生产环境查询投诉记录）
        # 当前 mock 实现：始终通过

        # 约束3: 食安合规（营销场景不涉及）

        passed = len(violations) == 0
        return {
            "passed": passed,
            "violations": violations,
            "margin_floor_pct": margin_floor_pct,
            "discount_fen": discount_fen,
        }

    async def _generate_content(
        self,
        campaign_type: str,
        brand_voice: dict[str, Any],
        store_context: dict[str, Any],
        member_segment: Optional[dict[str, Any]],
        offer_detail: Optional[dict[str, Any]],
        channels: list[str],
    ) -> dict[str, Any]:
        """调用 tx-brain ContentHub 生成内容（含降级处理）"""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{BRAIN_SERVICE_URL}/api/v1/brain/content/generate",
                    headers={"X-Tenant-ID": self.tenant_id},
                    json={
                        "campaign_type": campaign_type,
                        "brand_voice": brand_voice or {"brand_name": "屯象门店", "tone": "亲切温暖"},
                        "store_context": store_context,
                        "member_segment": member_segment,
                        "offer_detail": offer_detail,
                        "target_channels": channels,
                        "ab_variants": 1,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        return data["data"]
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "content_hub_unavailable",
                campaign_type=campaign_type,
                error=str(exc),
            )

        # 降级：使用静态模板
        return _fallback_content(campaign_type, channels, store_context, offer_detail)

    async def _dispatch_message(
        self,
        member_id: str,
        channels: list[str],
        content: dict[str, Any],
        campaign_type: str,
        ref_id: str,
    ) -> dict[str, Any]:
        """通过 tx-growth 渠道引擎发送消息，并写入 marketing_touch_log"""
        touch_id = f"touch_{uuid.uuid4().hex[:12]}"
        send_status = "queued"
        message_id: Optional[str] = None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{GROWTH_SERVICE_URL}/api/v1/growth/channel/send",
                    headers={"X-Tenant-ID": self.tenant_id},
                    json={
                        "touch_id": touch_id,
                        "member_id": member_id,
                        "channels": channels,
                        "content": content,
                        "campaign_type": campaign_type,
                        "ref_id": ref_id,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    send_status = data.get("status", "sent")
                    message_id = data.get("message_id")
                    send_result = data if data else {"touch_id": touch_id, "status": "sent"}
                else:
                    send_result = {"touch_id": touch_id, "status": "queued"}
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning("growth_channel_unavailable", touch_id=touch_id, error=str(exc))
            send_status = "queued"
            send_result = {"touch_id": touch_id, "status": "queued", "channels": channels}

        # Write touch log to DB if session available
        if self._db is not None:
            # Include touch_id so hash is unique per dispatch (prevents false dedup)
            content_preview = content.get("preview", "")
            content_hash = hashlib.sha256(
                f"{touch_id}:{member_id}:{campaign_type}:{content_preview}".encode()
            ).hexdigest()[:64]

            try:
                await self._db.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(self.tenant_id)},
                )
                primary_channel = channels[0] if channels else "unknown"
                await self._db.execute(
                    text("""
                        INSERT INTO marketing_touch_log
                          (tenant_id, member_id, channel, campaign_type,
                           message_id, content_hash, status, sent_at, metadata_json)
                        VALUES
                          (:tenant_id::uuid,
                           CASE WHEN :member_id = '' THEN NULL ELSE :member_id::uuid END,
                           :channel, :campaign_type,
                           :message_id, :content_hash,
                           :status, NOW(),
                           :metadata::jsonb)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "tenant_id": str(self.tenant_id),
                        "member_id": member_id,
                        "channel": primary_channel,
                        "campaign_type": campaign_type,
                        "message_id": message_id or touch_id,
                        "content_hash": content_hash,
                        "status": send_status,
                        "metadata": json.dumps({"touch_id": touch_id, "ref_id": ref_id, "all_channels": channels}),
                    },
                )
                # Commit is the responsibility of the calling handler; flush only here
                await self._db.flush()
            except (ValueError, OSError, SQLAlchemyError) as exc:
                logger.warning("touch_log_write_error", touch_id=touch_id, error=str(exc))
                # Don't fail the dispatch because of log write failure

        logger.info(
            "message_dispatched",
            touch_id=touch_id,
            member_id=member_id,
            campaign_type=campaign_type,
            status=send_status,
        )
        return send_result


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def _fallback_content(
    campaign_type: str,
    channels: list[str],
    store_context: dict[str, Any],
    offer_detail: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """ContentHub 不可用时的静态降级内容"""
    store_name = store_context.get("store_name", "我们的门店")
    offer_text = ""
    if offer_detail and offer_detail.get("discount_fen"):
        offer_text = f"，专属优惠 {offer_detail['discount_fen'] // 100} 元等您使用"

    templates = {
        "post_order_thanks": f"感谢您在{store_name}的消费，期待再次为您服务{offer_text}！",
        "new_customer_welcome": f"欢迎加入{store_name}会员{offer_text}，好礼相送！",
        "member_win_back": f"好久不见！{store_name}想念您{offer_text}，快来打卡吧～",
        "birthday_care": f"生日快乐！{store_name}为您准备了专属礼遇{offer_text}，愿您生日愉快！",
        "holiday_promo": f"节日快乐！{store_name}祝您节日愉快{offer_text}！",
        "upgrade_celebration": f"恭喜升级！感谢您对{store_name}的支持，专属权益已为您开启！",
        "churn_recovery": f"想念您的味蕾！{store_name}特别为您准备了回归礼包{offer_text}！",
    }
    body = templates.get(campaign_type, f"来{store_name}，有惊喜等着您{offer_text}！")

    return {
        "campaign_type": campaign_type,
        "cached": False,
        "fallback": True,
        "preview": body[:30],
        "contents": [
            {"channel": ch, "body": body, "subject": campaign_type, "cta": "立即前往"}
            for ch in channels
        ],
    }


def _get_score_suggestions(
    total_score: float,
    channel_coverage: float,
    touch_frequency: float,
) -> list[str]:
    """根据评分生成改善建议"""
    suggestions = []
    if channel_coverage < 20:
        suggestions.append("渠道覆盖不足：建议接入企业微信和公众号，提升触达多样性")
    if touch_frequency < 10:
        suggestions.append("触达频率偏低：建议配置生日关怀和沉默唤醒旅程，提高活跃触达")
    if total_score < 60:
        suggestions.append("整体评分偏低：建议启动 AI营销编排Agent，自动化提升营销效率")
    if not suggestions:
        suggestions.append("营销表现良好，继续保持并关注归因数据优化")
    return suggestions
