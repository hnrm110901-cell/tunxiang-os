"""L1 场景会话层 — 意图识别 + 角色识别 + 上下文注入 + 多轮任务拆解

职责：
1. 用户意图识别（查询 / 建议 / 触发动作）
2. 角色识别（收银员 / 迎宾 / 服务员 / 厨师 / 店长 / 总部）
3. 门店/品牌/班次上下文注入
4. 会话状态保持
5. 多轮任务拆解
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


# ── 意图类型 ──────────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    """用户意图类型"""
    QUERY = "query"              # 查询：看板数据、状态查询
    SUGGESTION = "suggestion"    # 建议请求：推荐、分析、解释
    ACTION = "action"            # 触发动作：预订、发券、生成任务
    REVIEW = "review"            # 复盘：经营总结、异常归因
    ALERT_RESPONSE = "alert_response"  # 响应异常卡片


class UserRole(str, Enum):
    """用户角色"""
    CASHIER = "cashier"          # 收银员
    HOST = "host"                # 迎宾
    WAITER = "waiter"            # 服务员
    CHEF = "chef"                # 厨师/厨师长
    STORE_MANAGER = "store_manager"  # 店长
    AREA_MANAGER = "area_manager"    # 区域经理
    HQ_ANALYST = "hq_analyst"        # 总部分析师
    HQ_EXECUTIVE = "hq_executive"    # 总部高管
    CUSTOMER = "customer"            # 顾客（小程序端）


class ShiftPeriod(str, Enum):
    """班次"""
    MORNING = "morning"      # 早班 06:00-14:00
    LUNCH = "lunch"          # 午市 10:30-14:00
    AFTERNOON = "afternoon"  # 下午班 14:00-17:00
    DINNER = "dinner"        # 晚市 17:00-21:00
    NIGHT = "night"          # 晚班 21:00-02:00
    ALL_DAY = "all_day"      # 全天


# ── 意图识别结果 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedIntent:
    """解析后的意图"""
    intent_type: IntentType
    target_agent: str           # 路由目标 Agent ID
    action: str                 # 具体动作
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_input: str = ""
    requires_confirmation: bool = False


# ── 会话上下文 ────────────────────────────────────────────────────────────────

@dataclass
class SessionContext:
    """场景会话上下文 — 贯穿单次会话的完整上下文"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    store_id: Optional[str] = None
    brand_id: Optional[str] = None
    user_role: UserRole = UserRole.STORE_MANAGER
    user_id: Optional[str] = None
    shift_period: ShiftPeriod = ShiftPeriod.ALL_DAY
    device_type: str = "browser"     # android_pos / ipad / browser / miniapp / mobile
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 多轮对话历史（最近 N 轮）
    conversation_history: list[dict] = field(default_factory=list)
    max_history: int = 20

    # 当前任务链（多轮任务拆解）
    task_chain: list[dict] = field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        """添加一轮对话"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]

    def to_prompt_context(self) -> dict:
        """生成用于注入 LLM prompt 的上下文"""
        return {
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "brand_id": self.brand_id,
            "user_role": self.user_role.value,
            "shift_period": self.shift_period.value,
            "device_type": self.device_type,
            "conversation_turns": len(self.conversation_history),
            "active_tasks": len(self.task_chain),
        }


# ── 意图识别引擎 ──────────────────────────────────────────────────────────────

# 关键词 → (target_agent, action, intent_type) 的规则映射
_INTENT_RULES: list[tuple[list[str], str, str, IntentType]] = [
    # 迎宾预订
    (["预订", "预约", "包厢", "订位", "预定"], "reception", "handle_reservation", IntentType.ACTION),
    (["改约", "改期", "换桌", "取消预订"], "reception", "modify_reservation", IntentType.ACTION),
    (["今晚预订", "预订情况", "预订排布"], "reception", "query_reservations", IntentType.QUERY),
    # 等位桌台
    (["等位", "排队", "候位", "叫号"], "waitlist_table", "manage_waitlist", IntentType.ACTION),
    (["开台", "并台", "拆台", "换台"], "waitlist_table", "manage_table", IntentType.ACTION),
    (["翻台", "桌位", "桌态"], "waitlist_table", "query_tables", IntentType.QUERY),
    # 点单服务
    (["推荐菜", "搭配", "套餐推荐", "加菜"], "ordering", "recommend_dishes", IntentType.SUGGESTION),
    (["忌口", "过敏", "不吃"], "ordering", "check_dietary", IntentType.QUERY),
    # 厨房协同
    (["催菜", "出菜", "超时", "拥塞", "堵单"], "kitchen", "kitchen_status", IntentType.QUERY),
    (["停售", "缺货", "估清"], "kitchen", "manage_availability", IntentType.ACTION),
    # 会员增长
    (["会员", "积分", "券", "优惠", "储值"], "member_growth", "member_service", IntentType.QUERY),
    (["召回", "唤醒", "沉睡", "复购", "发券"], "member_growth", "member_campaign", IntentType.ACTION),
    # 结账风控
    (["买单", "结账", "退款", "折扣异常", "发票"], "checkout_risk", "checkout_query", IntentType.QUERY),
    (["大额折扣", "免单", "挂账"], "checkout_risk", "risk_check", IntentType.SUGGESTION),
    # 店长经营
    (["午市", "晚市", "复盘", "经营播报", "当班"], "store_ops", "shift_review", IntentType.REVIEW),
    (["人效", "翻台率", "客单价", "营业额"], "store_ops", "kpi_query", IntentType.QUERY),
    (["日清", "日结", "交班", "闭店"], "store_ops", "daily_close", IntentType.ACTION),
    (["整改", "改善", "提升"], "store_ops", "generate_improvement", IntentType.ACTION),
    # 总部分析
    (["多门店", "对比", "排名", "全国"], "hq_analytics", "multi_store_compare", IntentType.QUERY),
    (["周报", "月报", "季报", "报告"], "hq_analytics", "generate_report", IntentType.ACTION),
    (["预警", "异常门店", "风险门店"], "hq_analytics", "store_alerts", IntentType.QUERY),
    (["洞察", "趋势", "归因", "为什么"], "hq_analytics", "insight_analysis", IntentType.SUGGESTION),
]


class SceneSessionManager:
    """L1 场景会话管理器

    负责：
    1. 创建和管理会话上下文
    2. 基于规则的意图识别（快速路由）
    3. 基于 LLM 的意图识别（复杂意图，需要 ModelRouter）
    4. 上下文注入到 Agent 编排层
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}

    def create_session(
        self,
        tenant_id: str,
        user_role: UserRole,
        store_id: Optional[str] = None,
        brand_id: Optional[str] = None,
        user_id: Optional[str] = None,
        device_type: str = "browser",
    ) -> SessionContext:
        """创建新会话"""
        ctx = SessionContext(
            tenant_id=tenant_id,
            store_id=store_id,
            brand_id=brand_id,
            user_role=user_role,
            user_id=user_id,
            device_type=device_type,
            shift_period=self._detect_shift_period(),
        )
        self._sessions[ctx.session_id] = ctx
        logger.info(
            "session_created",
            session_id=ctx.session_id,
            tenant_id=tenant_id,
            role=user_role.value,
            store_id=store_id,
        )
        return ctx

    def get_session(self, session_id: str) -> Optional[SessionContext]:
        return self._sessions.get(session_id)

    def parse_intent(self, text: str, context: SessionContext) -> ParsedIntent:
        """基于规则的快速意图识别

        先尝试关键词匹配，匹配失败则返回默认路由。
        复杂意图需要调用 parse_intent_with_llm()。
        """
        text_lower = text.strip()

        for keywords, agent_id, action, intent_type in _INTENT_RULES:
            for kw in keywords:
                if kw in text_lower:
                    parsed = ParsedIntent(
                        intent_type=intent_type,
                        target_agent=agent_id,
                        action=action,
                        confidence=0.8,
                        raw_input=text,
                    )
                    # 动作类意图可能需要确认
                    if intent_type == IntentType.ACTION:
                        parsed.requires_confirmation = True
                    logger.info(
                        "intent_parsed_rule",
                        agent=agent_id,
                        action=action,
                        keyword=kw,
                        confidence=0.8,
                    )
                    return parsed

        # 角色默认路由：无法识别时根据用户角色选择 Agent
        default_agent = self._role_default_agent(context.user_role)
        return ParsedIntent(
            intent_type=IntentType.QUERY,
            target_agent=default_agent,
            action="general_query",
            confidence=0.3,
            raw_input=text,
        )

    async def parse_intent_with_llm(
        self,
        text: str,
        context: SessionContext,
        model_router: Any,
    ) -> ParsedIntent:
        """基于 LLM 的复杂意图识别

        当规则匹配置信度低于阈值时使用。
        """
        system_prompt = (
            "你是屯象OS的意图识别引擎。根据用户输入，返回JSON格式的意图分析。\n"
            f"用户角色: {context.user_role.value}\n"
            f"当前班次: {context.shift_period.value}\n"
            f"设备类型: {context.device_type}\n\n"
            "可用的 Agent: reception(迎宾预订), waitlist_table(等位桌台), "
            "ordering(点单服务), kitchen(厨房协同), member_growth(会员增长), "
            "checkout_risk(结账风控), store_ops(店长经营), hq_analytics(总部分析)\n\n"
            "返回格式: {\"agent\": \"agent_id\", \"action\": \"action_name\", "
            "\"intent_type\": \"query|suggestion|action|review\", \"confidence\": 0.9}"
        )

        try:
            response = await model_router.complete(
                tenant_id=context.tenant_id,
                task_type="quick_classification",
                messages=[{"role": "user", "content": text}],
                system=system_prompt,
                urgency="fast",
                max_tokens=200,
            )

            import json
            # 尝试从响应中提取 JSON
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                result = json.loads(json_match.group())
                return ParsedIntent(
                    intent_type=IntentType(result.get("intent_type", "query")),
                    target_agent=result.get("agent", "store_ops"),
                    action=result.get("action", "general_query"),
                    confidence=float(result.get("confidence", 0.7)),
                    raw_input=text,
                    requires_confirmation=result.get("intent_type") == "action",
                )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("llm_intent_parse_failed", error=str(exc))

        # LLM 解析失败，回退到规则
        return self.parse_intent(text, context)

    def _role_default_agent(self, role: UserRole) -> str:
        """角色默认 Agent 映射"""
        mapping = {
            UserRole.CASHIER: "checkout_risk",
            UserRole.HOST: "reception",
            UserRole.WAITER: "ordering",
            UserRole.CHEF: "kitchen",
            UserRole.STORE_MANAGER: "store_ops",
            UserRole.AREA_MANAGER: "hq_analytics",
            UserRole.HQ_ANALYST: "hq_analytics",
            UserRole.HQ_EXECUTIVE: "hq_analytics",
            UserRole.CUSTOMER: "ordering",
        }
        return mapping.get(role, "store_ops")

    def _detect_shift_period(self) -> ShiftPeriod:
        """根据当前时间自动检测班次"""
        hour = datetime.now().hour
        if 6 <= hour < 10:
            return ShiftPeriod.MORNING
        elif 10 <= hour < 14:
            return ShiftPeriod.LUNCH
        elif 14 <= hour < 17:
            return ShiftPeriod.AFTERNOON
        elif 17 <= hour < 21:
            return ShiftPeriod.DINNER
        else:
            return ShiftPeriod.NIGHT

    def cleanup_expired(self, max_age_seconds: int = 7200) -> int:
        """清理过期会话"""
        now = datetime.now(timezone.utc)
        expired = [
            sid for sid, ctx in self._sessions.items()
            if (now - ctx.created_at).total_seconds() > max_age_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)
