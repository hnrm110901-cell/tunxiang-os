"""业务流适配矩阵 — 定义每条业务流的 Agent 介入模式

适配模式：
  A: 原生 Agent 主导 — Agent 驱动决策和执行
  B: Agent + 状态机协同 — Agent 提供建议，状态机守住底线
  C: 代码/状态机主导 — 系统确定性执行，Agent 仅辅助
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AdaptationMode(str, Enum):
    """适配模式"""
    AGENT_LED = "A"            # 原生 Agent 主导
    AGENT_SYSTEM_COOP = "B"    # Agent + 状态机协同
    SYSTEM_LED = "C"           # 系统主导，Agent 辅助


@dataclass
class BusinessFlow:
    """业务流定义"""
    flow_id: str
    name: str
    name_en: str
    mode: AdaptationMode
    agent_value: str                      # Agent 在此流中的价值描述
    system_control: str                   # 必须由系统/状态机控制的部分
    primary_agents: list[str]             # 主要负责的 Agent ID
    recommended_terminals: list[str]      # 推荐终端
    priority: str = "P1"                  # P0/P1/P2

    @property
    def is_agent_led(self) -> bool:
        return self.mode == AdaptationMode.AGENT_LED

    @property
    def agent_can_execute(self) -> bool:
        """Agent 是否可以直接执行（A模式可以，B/C需要系统配合）"""
        return self.mode == AdaptationMode.AGENT_LED


# ── 业务流适配矩阵定义 ────────────────────────────────────────────────────────

BUSINESS_FLOWS: list[BusinessFlow] = [
    BusinessFlow(
        flow_id="reservation",
        name="预订",
        name_en="Reservation",
        mode=AdaptationMode.AGENT_SYSTEM_COOP,
        agent_value="识别意图、推荐桌位、生成确认话术",
        system_control="预订锁台、时段容量、超时释放",
        primary_agents=["reception"],
        recommended_terminals=["迎宾台", "店长端", "小程序"],
        priority="P0",
    ),
    BusinessFlow(
        flow_id="waitlist",
        name="等位",
        name_en="Waitlist",
        mode=AdaptationMode.AGENT_SYSTEM_COOP,
        agent_value="预估等待时长、优先级建议、流失预警",
        system_control="队列顺序、叫号规则、到号超时",
        primary_agents=["waitlist_table"],
        recommended_terminals=["迎宾台", "顾客端"],
        priority="P0",
    ),
    BusinessFlow(
        flow_id="table_management",
        name="桌台管理",
        name_en="Table Management",
        mode=AdaptationMode.SYSTEM_LED,
        agent_value="翻台预测、桌位调度建议",
        system_control="桌态状态机、占用释放、冲突校验",
        primary_agents=["waitlist_table"],
        recommended_terminals=["POS", "迎宾台", "服务员手持"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="ordering",
        name="点单",
        name_en="Ordering",
        mode=AdaptationMode.SYSTEM_LED,
        agent_value="推荐搭配、忌口提示、upsell建议",
        system_control="下单、改单、权限、价格、赠送规则",
        primary_agents=["ordering"],
        recommended_terminals=["服务员手持", "POS", "扫码端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="kitchen_production",
        name="厨房出品",
        name_en="Kitchen Production",
        mode=AdaptationMode.SYSTEM_LED,
        agent_value="拥塞识别、优先级建议、超时解释",
        system_control="分单路由、工位状态、出菜确认",
        primary_agents=["kitchen"],
        recommended_terminals=["KDS", "传菜端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="member_recognition",
        name="会员识别",
        name_en="Member Recognition",
        mode=AdaptationMode.AGENT_SYSTEM_COOP,
        agent_value="自动识别会员、推荐权益、成长路径建议",
        system_control="会员主档、积分、券核销、等级规则",
        primary_agents=["member_growth"],
        recommended_terminals=["POS", "扫码端", "店长端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="checkout_payment",
        name="结账支付",
        name_en="Checkout & Payment",
        mode=AdaptationMode.SYSTEM_LED,
        agent_value="风险提醒、异常解释、补偿建议",
        system_control="支付、退款、冲正、发票、审计",
        primary_agents=["checkout_risk"],
        recommended_terminals=["POS", "手持", "扫码端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="marketing_outreach",
        name="营销触达",
        name_en="Marketing Outreach",
        mode=AdaptationMode.AGENT_LED,
        agent_value="人群细分、文案生成、活动建议、触达编排",
        system_control="活动规则、发券额度、预算上限",
        primary_agents=["member_growth"],
        recommended_terminals=["总部端", "会员运营端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="report_analysis",
        name="报表分析",
        name_en="Report & Analysis",
        mode=AdaptationMode.AGENT_LED,
        agent_value="自动总结、经营问答、异常解释、动作建议",
        system_control="指标口径、数据权限、口径审计",
        primary_agents=["store_ops", "hq_analytics"],
        recommended_terminals=["总部端", "店长端"],
        priority="P0",
    ),
    BusinessFlow(
        flow_id="daily_settlement",
        name="日清日结",
        name_en="Daily Settlement",
        mode=AdaptationMode.AGENT_SYSTEM_COOP,
        agent_value="自动复盘、生成整改项、提醒漏项",
        system_control="班结、交班签核、对账、锁账",
        primary_agents=["store_ops"],
        recommended_terminals=["店长端", "POS", "总部端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="store_inspection",
        name="巡店整改",
        name_en="Store Inspection",
        mode=AdaptationMode.AGENT_LED,
        agent_value="生成任务、跟踪执行、催办升级",
        system_control="审批流、责任归属、完成确认",
        primary_agents=["hq_analytics"],
        recommended_terminals=["店长端", "总部端"],
        priority="P1",
    ),
    BusinessFlow(
        flow_id="hq_alerts",
        name="总部经营预警",
        name_en="HQ Operations Alerts",
        mode=AdaptationMode.AGENT_LED,
        agent_value="自动识别异常、生成对策、优先级排序",
        system_control="指标计算、权限、任务归档",
        primary_agents=["hq_analytics"],
        recommended_terminals=["总部端"],
        priority="P0",
    ),
]

# ── 索引 ──────────────────────────────────────────────────────────────────────

FLOW_INDEX: dict[str, BusinessFlow] = {f.flow_id: f for f in BUSINESS_FLOWS}


def get_agent_flows(agent_id: str) -> list[BusinessFlow]:
    """获取某 Agent 负责的所有业务流"""
    return [f for f in BUSINESS_FLOWS if agent_id in f.primary_agents]


def get_flows_by_mode(mode: AdaptationMode) -> list[BusinessFlow]:
    """按适配模式筛选业务流"""
    return [f for f in BUSINESS_FLOWS if f.mode == mode]


def get_agent_led_flows() -> list[BusinessFlow]:
    """获取所有 Agent 主导的业务流（优先开发）"""
    return get_flows_by_mode(AdaptationMode.AGENT_LED)
