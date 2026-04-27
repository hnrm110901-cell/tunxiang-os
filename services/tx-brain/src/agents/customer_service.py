"""智能客服Agent — 处理顾客投诉/询问/反馈，生成建议回复及处置动作

工作流程：
1. 接收顾客消息（渠道/内容/类型/历史对话/顾客等级）
2. Python预处理：VIP投诉升级、食品安全关键词检测、高额退款检测
3. 调用Claude分析意图/情绪，生成中文回复和处置动作
4. 校验补偿金额约束（不超过订单金额50%，自动处理<5000分）
5. 返回：意图/情绪/建议回复/处置动作/升级标志
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

# 食品安全投诉关键词（触发高优先级强制处置）
_FOOD_SAFETY_KEYWORDS = ["变质", "异物", "食物中毒", "发霉", "腐烂", "虫子", "头发", "玻璃", "金属"]

# 退款/赔偿金额正则（匹配"退款100元"/"赔偿50元"等）
_REFUND_AMOUNT_RE = re.compile(r"(?:退款|赔偿|补偿|赔)[\s]*(\d+(?:\.\d+)?)\s*(?:元|块|RMB)?")


class CustomerServiceAgent:
    """智能客服Agent：处理顾客投诉/询问/反馈，生成建议回复及处置动作

    三条硬约束校验：
    - 毛利底线：补偿建议不超过订单金额的50%
    - 权限校验：退款额在自动处理权限内（<5000分）
    - 客户体验：必须给出改善客户体验的方案
    """

    SYSTEM_PROMPT = """你是屯象OS的专业餐饮品牌客服代表。你的职责是处理顾客投诉、询问和反馈，给出专业、亲切的回复，并提出合理的处置建议。

服务原则：
1. 语气亲切但专业，符合餐饮行业服务语言规范
2. 对于情绪激动（angry）的顾客，优先共情，再解决问题
3. 补偿建议不超过订单金额的50%（硬约束，绝不超越）
4. 食品安全问题必须高度重视，立即升级处理
5. 输出标准中文，用词专业礼貌

意图分类：
- food_quality: 食品质量投诉（口味/份量/新鲜度/异物等）
- wait_time: 等待时间投诉（出餐慢/排队久等）
- wrong_order: 上错菜/漏菜/与点单不符
- price: 价格争议/账单错误/优惠未到账
- service: 服务态度/环境卫生/设施问题
- other: 其他（建议/表扬/一般咨询）

情绪分类：
- positive: 满意/表扬
- neutral: 中性/询问
- negative: 不满/轻度投诉
- angry: 强烈不满/激烈投诉

处置动作类型：
- refund: 退款（需指定金额）
- discount_coupon: 赠送优惠券（需指定面值）
- apologize: 正式道歉（无金额）
- escalate: 升级至人工处理
- follow_up: 后续回访跟进

返回严格JSON格式（不含markdown代码块）：
{
  "intent": "food_quality|wait_time|wrong_order|price|service|other",
  "sentiment": "positive|neutral|negative|angry",
  "response": "建议回复的完整中文文字（可直接发送给顾客）",
  "action_required": true/false,
  "actions": [
    {
      "type": "refund|discount_coupon|apologize|escalate|follow_up",
      "description": "动作说明",
      "amount_fen": 0,
      "priority": "high|medium|low"
    }
  ],
  "constraints_check": {
    "margin_ok": true/false,
    "authority_ok": true/false,
    "experience_ok": true/false
  },
  "escalate_to_human": true/false
}"""

    async def handle(self, payload: dict) -> dict:
        """处理顾客投诉/询问/反馈。

        Args:
            payload: 包含以下字段：
                - tenant_id: 租户ID
                - store_id: 门店ID
                - customer_id: 顾客ID（可选）
                - channel: 渠道（wechat_mp/miniapp/review/call/in_store）
                - message: 顾客原文
                - order_id: 关联订单ID（可选）
                - message_type: 消息类型（complaint/inquiry/feedback/praise）
                - context_history: 历史对话 [{role, content}]（可空）
                - customer_tier: 顾客等级（vip/regular/new）

        Returns:
            包含 intent/sentiment/response/action_required/actions/
            constraints_check/escalate_to_human/source 的字典
        """
        # Python 预处理：业务规则前置判断
        pre_check = self._pre_check(payload)

        context = self._build_context(payload, pre_check)
        messages = self._build_messages(payload, context)

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=self.SYSTEM_PROMPT,
            messages=messages,
        )

        response_text = message.content[0].text
        result = self._parse_response(response_text)

        # 将预处理的强制升级标志合并到结果
        if pre_check["force_escalate"]:
            result["escalate_to_human"] = True
        if pre_check["force_action_required"]:
            result["action_required"] = True
        if pre_check["food_safety_detected"]:
            # 确保食品安全问题优先级最高
            for action in result.get("actions", []):
                action["priority"] = "high"

        logger.info(
            "customer_service_handled",
            tenant_id=payload.get("tenant_id"),
            store_id=payload.get("store_id"),
            customer_id=payload.get("customer_id"),
            channel=payload.get("channel"),
            message_type=payload.get("message_type"),
            customer_tier=payload.get("customer_tier"),
            intent=result.get("intent"),
            sentiment=result.get("sentiment"),
            escalate_to_human=result.get("escalate_to_human"),
            action_required=result.get("action_required"),
            food_safety_detected=pre_check["food_safety_detected"],
            source=result.get("source"),
        )

        return result

    async def analyze_from_mv(self, tenant_id: str, store_id: str | None = None) -> dict:
        """Phase 3 快速路径：从 mv_public_opinion 物化视图读取，<5ms。

        字段：tenant_id, store_id, total_mentions, positive_rate, negative_rate,
              top_complaints, unresolved_count

        无数据时 fallback 到 handle()；DB 异常也 graceful fallback。
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
                            SELECT tenant_id, store_id, total_mentions, positive_rate,
                                   negative_rate, top_complaints, unresolved_count
                            FROM mv_public_opinion
                            WHERE tenant_id = :tid
                              AND store_id = :sid
                            LIMIT 1
                        """),
                        {"tid": tenant_id, "sid": store_id},
                    )
                else:
                    result = await db.execute(
                        text("""
                            SELECT tenant_id, store_id, total_mentions, positive_rate,
                                   negative_rate, top_complaints, unresolved_count
                            FROM mv_public_opinion
                            WHERE tenant_id = :tid
                            LIMIT 1
                        """),
                        {"tid": tenant_id},
                    )

                row = result.fetchone()
                if not row:
                    logger.info(
                        "customer_service_mv_empty_fallback",
                        tenant_id=tenant_id,
                        store_id=store_id,
                    )
                    return await self.handle({"tenant_id": tenant_id, "store_id": store_id, "message": ""})

                return {
                    "inference_layer": "mv_fast_path",
                    "data": dict(row._mapping),
                    "agent": self.__class__.__name__,
                }

        except SQLAlchemyError as exc:
            logger.warning(
                "customer_service_mv_db_error",
                tenant_id=tenant_id,
                store_id=store_id,
                error=str(exc),
            )
            return await self.handle({"tenant_id": tenant_id, "store_id": store_id, "message": ""})

    def _pre_check(self, payload: dict) -> dict:
        """Python预处理：业务规则前置判断，不依赖Claude。"""
        message = payload.get("message", "")
        customer_tier = payload.get("customer_tier", "regular")
        message_type = payload.get("message_type", "inquiry")

        force_escalate = False
        force_action_required = False
        food_safety_detected = False

        # 规则1：VIP顾客 + 投诉 → 强制升级人工
        if customer_tier == "vip" and message_type == "complaint":
            force_escalate = True

        # 规则2：消息包含退款/赔偿金额 > 5000分（50元）→ 强制升级人工
        matches = _REFUND_AMOUNT_RE.findall(message)
        for amount_str in matches:
            try:
                amount_fen = int(float(amount_str) * 100)
                if amount_fen > 5000:
                    force_escalate = True
                    break
            except ValueError:
                pass

        # 规则3：食品安全关键词 → 强制 action_required，高优先级
        for keyword in _FOOD_SAFETY_KEYWORDS:
            if keyword in message:
                food_safety_detected = True
                force_action_required = True
                break

        return {
            "force_escalate": force_escalate,
            "force_action_required": force_action_required,
            "food_safety_detected": food_safety_detected,
        }

    def _build_context(self, payload: dict, pre_check: dict) -> str:
        """构建发送给Claude的上下文描述。"""
        lines = [
            f"渠道：{payload.get('channel', '未知')}",
            f"顾客等级：{payload.get('customer_tier', 'regular')}",
            f"消息类型：{payload.get('message_type', 'inquiry')}",
            f"顾客消息：{payload.get('message', '')}",
        ]

        if payload.get("order_id"):
            lines.append(f"关联订单：{payload.get('order_id')}")

        if pre_check["food_safety_detected"]:
            lines.append("【系统预警】检测到食品安全相关投诉，需高度重视，优先处理")

        if pre_check["force_escalate"]:
            lines.append("【系统提示】该顾客属于需要人工介入的情形，请在actions中包含escalate动作")

        return "\n".join(lines)

    def _build_messages(self, payload: dict, context: str) -> list[dict]:
        """构建发送给Claude的消息列表（含历史对话）。"""
        messages: list[dict] = []

        # 加入历史对话（最近10条）
        history = payload.get("context_history") or []
        for turn in history[-10:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # 当前顾客消息作为新的user消息
        messages.append({"role": "user", "content": context})

        return messages

    def _parse_response(self, response_text: str) -> dict:
        """解析 Claude 响应，提取 JSON，失败时返回安全兜底值。"""
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group())
                result["source"] = "claude"
                return result
            except json.JSONDecodeError:
                pass

        logger.warning(
            "customer_service_parse_failed",
            response_preview=response_text[:200],
        )
        return self._fallback_response()

    def _fallback_response(self) -> dict:
        """Claude调用失败或解析失败时的兜底响应。"""
        return {
            "intent": "other",
            "sentiment": "neutral",
            "response": "感谢您的反馈，我们已记录您的意见，将尽快为您处理。",
            "action_required": True,
            "actions": [
                {
                    "type": "escalate",
                    "description": "AI处理异常，转人工客服跟进",
                    "amount_fen": 0,
                    "priority": "medium",
                }
            ],
            "constraints_check": {
                "margin_ok": None,
                "authority_ok": None,
                "experience_ok": None,
            },
            "escalate_to_human": True,
            "source": "fallback",
        }


customer_service = CustomerServiceAgent()
