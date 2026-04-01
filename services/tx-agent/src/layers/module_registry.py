"""Agent 模块注册表 — 一级/二级模块清单 + 终端/页面映射

每个模块定义：
- 所属 Agent
- 适配模式 (A/B/C)
- 关联的终端和页面路由
- AI 入口类型
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AiEntryType(str, Enum):
    """AI 入口类型"""
    TASK_INPUT = "task_input"       # 任务输入入口（自然语言）
    ALERT_CARD = "alert_card"       # 异常卡片入口（系统主动推送）
    SUGGESTION = "suggestion"       # 建议执行入口（一键执行）
    REVIEW = "review"               # 复盘入口（班次/日结复盘）


class Terminal(str, Enum):
    """终端类型"""
    RECEPTION = "web-reception"     # 迎宾台 iPad
    POS = "web-pos"                 # 收银 POS
    KDS = "web-kds"                 # 厨房 KDS
    CREW = "web-crew"               # 服务员 PWA
    ADMIN = "web-admin"             # 总部后台
    MINIAPP = "miniapp-customer"    # 顾客小程序


@dataclass
class PageRoute:
    """页面路由定义"""
    path: str
    page_name: str
    terminal: Terminal
    ai_entry_types: list[AiEntryType] = field(default_factory=list)
    is_new: bool = False            # 是否为新增页面
    description: str = ""


@dataclass
class AgentModule:
    """Agent 二级模块定义"""
    module_id: str
    name: str
    name_en: str
    agent_id: str                   # 所属专业 Agent
    adaptation_mode: str            # A/B/C
    description: str
    pages: list[PageRoute] = field(default_factory=list)
    priority: str = "P1"


# ── 模块定义 ──────────────────────────────────────────────────────────────────

AGENT_MODULES: list[AgentModule] = [
    # ── Agent 1: 迎宾预订 (reception) ──
    AgentModule(
        module_id="M1.1", name="预订管理", name_en="Reservation Management",
        agent_id="reception", adaptation_mode="B", priority="P0",
        description="创建/修改/取消预订，时段容量校验",
        pages=[
            PageRoute("/reservations", "预订看板", Terminal.RECEPTION,
                       [AiEntryType.TASK_INPUT, AiEntryType.ALERT_CARD]),
            PageRoute("/ai-host", "AI迎宾助手", Terminal.RECEPTION,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="迎宾场景的统一AI助手入口"),
        ],
    ),
    AgentModule(
        module_id="M1.2", name="VIP识别", name_en="VIP Recognition",
        agent_id="reception", adaptation_mode="B", priority="P0",
        description="会员识别、偏好加载、服务策略",
        pages=[
            PageRoute("/vip", "VIP到店提醒", Terminal.RECEPTION,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),
    AgentModule(
        module_id="M1.3", name="桌位推荐", name_en="Table Recommendation",
        agent_id="reception", adaptation_mode="A", priority="P0",
        description="根据人数/偏好/时段推荐最佳桌位",
        pages=[
            PageRoute("/seats", "桌位分配", Terminal.RECEPTION,
                       [AiEntryType.SUGGESTION]),
        ],
    ),
    AgentModule(
        module_id="M1.4", name="到店确认", name_en="Arrival Confirmation",
        agent_id="reception", adaptation_mode="B", priority="P1",
        description="到店提醒、确认短信/微信、迎接准备",
        pages=[
            PageRoute("/checkin", "入住确认", Terminal.RECEPTION,
                       [AiEntryType.SUGGESTION]),
        ],
    ),

    # ── Agent 2: 等位桌台 (waitlist_table) ──
    AgentModule(
        module_id="M2.1", name="等位队列", name_en="Waitlist Queue",
        agent_id="waitlist_table", adaptation_mode="B", priority="P0",
        description="排队管理、叫号、候位安抚",
        pages=[
            PageRoute("/queue", "等位队列", Terminal.RECEPTION,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),
    AgentModule(
        module_id="M2.2", name="桌台调度", name_en="Table Dispatch",
        agent_id="waitlist_table", adaptation_mode="C", priority="P1",
        description="开台/并台/拆台/换台、桌态状态机",
        pages=[
            PageRoute("/tables", "桌台地图", Terminal.POS,
                       [AiEntryType.SUGGESTION]),
            PageRoute("/tables", "桌台视图", Terminal.CREW),
        ],
    ),
    AgentModule(
        module_id="M2.3", name="翻台预估", name_en="Turnover Prediction",
        agent_id="waitlist_table", adaptation_mode="A", priority="P1",
        description="基于历史+实时预估翻台时间",
        pages=[
            PageRoute("/wait-estimate", "等位预估", Terminal.RECEPTION,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="显示各桌型预估等待时间"),
        ],
    ),
    AgentModule(
        module_id="M2.4", name="流失预警", name_en="Churn Alert",
        agent_id="waitlist_table", adaptation_mode="A", priority="P1",
        description="识别等位流失风险客户，建议安抚策略",
        pages=[
            PageRoute("/churn-alert", "流失预警", Terminal.RECEPTION,
                       [AiEntryType.ALERT_CARD], is_new=True,
                       description="等位客户流失风险识别和安抚建议"),
        ],
    ),

    # ── Agent 3: 点单服务 (ordering) ──
    AgentModule(
        module_id="M3.1", name="菜品推荐", name_en="Dish Recommendation",
        agent_id="ordering", adaptation_mode="A", priority="P1",
        description="基于画像+库存+毛利的个性化推荐",
        pages=[
            PageRoute("/ai-order", "AI点单助手", Terminal.CREW,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="服务员AI点单辅助"),
            PageRoute("/dish-suggest", "菜品推荐卡", Terminal.CREW,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="基于客户画像的菜品推荐"),
        ],
    ),
    AgentModule(
        module_id="M3.2", name="套餐搭配", name_en="Combo Matching",
        agent_id="ordering", adaptation_mode="A", priority="P2",
        description="智能套餐组合建议",
        pages=[
            PageRoute("/order-full", "完整点单", Terminal.CREW),
        ],
    ),
    AgentModule(
        module_id="M3.3", name="忌口管理", name_en="Dietary Restriction",
        agent_id="ordering", adaptation_mode="C", priority="P1",
        description="过敏原/忌口提醒、菜品标注",
        pages=[
            PageRoute("/allergy-alert", "忌口提醒", Terminal.CREW,
                       [AiEntryType.ALERT_CARD], is_new=True,
                       description="点单时自动忌口/过敏原提醒"),
        ],
    ),
    AgentModule(
        module_id="M3.4", name="加菜建议", name_en="Upsell Suggestion",
        agent_id="ordering", adaptation_mode="A", priority="P2",
        description="用餐中段加菜upsell策略",
        pages=[],  # 集成到点单页面，不需要独立路由
    ),

    # ── Agent 4: 厨房协同 (kitchen) ──
    AgentModule(
        module_id="M4.1", name="出品监控", name_en="Production Monitor",
        agent_id="kitchen", adaptation_mode="C", priority="P1",
        description="全厨房出品状态实时看板",
        pages=[
            PageRoute("/board", "厨房主板", Terminal.KDS),
            PageRoute("/swimlane", "泳道视图", Terminal.KDS),
            PageRoute("/stats-panel", "统计面板", Terminal.KDS),
        ],
    ),
    AgentModule(
        module_id="M4.2", name="工位拥塞", name_en="Station Bottleneck",
        agent_id="kitchen", adaptation_mode="A", priority="P1",
        description="识别瓶颈工位，建议调度",
        pages=[
            PageRoute("/bottleneck", "工位拥塞看板", Terminal.KDS,
                       [AiEntryType.ALERT_CARD], is_new=True,
                       description="实时工位拥塞检测和调度建议"),
            PageRoute("/timeout", "超时预警", Terminal.KDS,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),
    AgentModule(
        module_id="M4.3", name="催菜管理", name_en="Rush Order",
        agent_id="kitchen", adaptation_mode="B", priority="P1",
        description="催菜优先级判断、影响评估",
        pages=[
            PageRoute("/rush", "催菜", Terminal.CREW,
                       [AiEntryType.SUGGESTION]),
            PageRoute("/pace-suggest", "出菜节奏建议", Terminal.KDS,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="基于实时状态的出菜节奏建议"),
            PageRoute("/ai-kitchen", "AI厨房助手", Terminal.KDS,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="厨房场景的统一AI助手入口"),
        ],
    ),
    AgentModule(
        module_id="M4.4", name="估清管理", name_en="Availability Management",
        agent_id="kitchen", adaptation_mode="B", priority="P1",
        description="缺货/估清联动停售/恢复",
        pages=[
            PageRoute("/shortage", "缺货报告", Terminal.KDS,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),

    # ── Agent 5: 会员增长 (member_growth) ──
    AgentModule(
        module_id="M5.1", name="会员画像", name_en="Member Profile",
        agent_id="member_growth", adaptation_mode="C", priority="P1",
        description="全渠道画像、RFM、偏好、消费轨迹",
        pages=[
            PageRoute("/member", "会员查询", Terminal.CREW),
            PageRoute("/hq/analytics/member", "会员分析", Terminal.ADMIN),
        ],
    ),
    AgentModule(
        module_id="M5.2", name="分群管理", name_en="Segment Management",
        agent_id="member_growth", adaptation_mode="B", priority="P1",
        description="人群标签、细分、分层策略",
        pages=[
            PageRoute("/hq/growth/segments", "分群中心", Terminal.ADMIN),
        ],
    ),
    AgentModule(
        module_id="M5.3", name="营销触达", name_en="Campaign Outreach",
        agent_id="member_growth", adaptation_mode="A", priority="P1",
        description="活动编排、文案生成、渠道分发",
        pages=[
            PageRoute("/hq/ai-campaign", "AI营销编排", Terminal.ADMIN,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="AI驱动的会员营销触达编排"),
            PageRoute("/hq/growth/journeys", "旅程列表", Terminal.ADMIN),
        ],
    ),
    AgentModule(
        module_id="M5.4", name="沉睡唤醒", name_en="Dormant Recall",
        agent_id="member_growth", adaptation_mode="A", priority="P1",
        description="流失预测、召回策略、效果追踪",
        pages=[],  # 集成到营销编排页面
    ),

    # ── Agent 6: 结账风控 (checkout_risk) ──
    AgentModule(
        module_id="M6.1", name="结账监控", name_en="Checkout Monitor",
        agent_id="checkout_risk", adaptation_mode="C", priority="P1",
        description="实时结账状态、异常检测",
        pages=[
            PageRoute("/cashier/:tableNo", "收银台", Terminal.POS),
            PageRoute("/ai-checkout", "AI结账助手", Terminal.POS,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="结账场景的异常检测和风控助手"),
        ],
    ),
    AgentModule(
        module_id="M6.2", name="折扣审计", name_en="Discount Audit",
        agent_id="checkout_risk", adaptation_mode="B", priority="P1",
        description="大额折扣解释、合规校验",
        pages=[
            PageRoute("/discount-audit", "折扣审计", Terminal.POS,
                       [AiEntryType.ALERT_CARD]),
            PageRoute("/hq/ops/approvals", "审批中心", Terminal.ADMIN),
        ],
    ),
    AgentModule(
        module_id="M6.3", name="退款风控", name_en="Refund Risk",
        agent_id="checkout_risk", adaptation_mode="B", priority="P1",
        description="退款风险评估、审批建议",
        pages=[
            PageRoute("/exceptions", "异常处理", Terminal.POS,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),
    AgentModule(
        module_id="M6.4", name="客诉补偿", name_en="Complaint Compensation",
        agent_id="checkout_risk", adaptation_mode="A", priority="P1",
        description="客诉场景补偿方案建议",
        pages=[
            PageRoute("/complaint", "客诉", Terminal.CREW,
                       [AiEntryType.SUGGESTION]),
        ],
    ),

    # ── Agent 7: 店长经营 (store_ops) ──
    AgentModule(
        module_id="M7.1", name="经营播报", name_en="Business Broadcast",
        agent_id="store_ops", adaptation_mode="A", priority="P0",
        description="实时经营数据播报、指标趋势",
        pages=[
            PageRoute("/biz-broadcast", "经营播报面板", Terminal.POS,
                       [AiEntryType.REVIEW], is_new=True,
                       description="店长实时经营数据播报和趋势"),
            PageRoute("/dashboard", "经营仪表盘", Terminal.ADMIN,
                       [AiEntryType.REVIEW]),
        ],
    ),
    AgentModule(
        module_id="M7.2", name="班次复盘", name_en="Shift Review",
        agent_id="store_ops", adaptation_mode="A", priority="P0",
        description="午市/晚市复盘、异常归因",
        pages=[
            PageRoute("/reports", "班次报表", Terminal.POS,
                       [AiEntryType.REVIEW]),
            PageRoute("/shift-summary", "班次总结", Terminal.CREW,
                       [AiEntryType.REVIEW]),
        ],
    ),
    AgentModule(
        module_id="M7.3", name="日清日结", name_en="Daily Settlement",
        agent_id="store_ops", adaptation_mode="B", priority="P0",
        description="日结检查、交班签核、对账",
        pages=[
            PageRoute("/daily-check", "日清检查", Terminal.POS,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="AI辅助日清检查和交班提醒"),
            PageRoute("/handover", "交班", Terminal.POS,
                       [AiEntryType.REVIEW]),
        ],
    ),
    AgentModule(
        module_id="M7.4", name="整改任务", name_en="Improvement Tasks",
        agent_id="store_ops", adaptation_mode="A", priority="P0",
        description="基于异常生成整改工单、跟踪闭环",
        pages=[
            PageRoute("/hq/ai-tasks", "整改任务中心", Terminal.ADMIN,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="AI生成的整改任务管理和跟踪"),
            PageRoute("/cruise", "巡台", Terminal.CREW,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),

    # ── Agent 8: 总部分析 (hq_analytics) ──
    AgentModule(
        module_id="M8.1", name="多店对比", name_en="Multi-Store Compare",
        agent_id="hq_analytics", adaptation_mode="A", priority="P0",
        description="门店间经营指标对比排名",
        pages=[
            PageRoute("/hq/analytics/multi-store", "多店对比", Terminal.ADMIN,
                       [AiEntryType.TASK_INPUT]),
        ],
    ),
    AgentModule(
        module_id="M8.2", name="经营洞察", name_en="Business Insight",
        agent_id="hq_analytics", adaptation_mode="A", priority="P0",
        description="自然语言问答式经营分析",
        pages=[
            PageRoute("/hq/ai-insight", "AI经营问答", Terminal.ADMIN,
                       [AiEntryType.TASK_INPUT], is_new=True,
                       description="总部自然语言经营问答入口"),
        ],
    ),
    AgentModule(
        module_id="M8.3", name="预警中心", name_en="Alert Center",
        agent_id="hq_analytics", adaptation_mode="A", priority="P0",
        description="异常门店聚合、优先级排序",
        pages=[
            PageRoute("/hq/ai-alerts", "AI门店预警", Terminal.ADMIN,
                       [AiEntryType.ALERT_CARD], is_new=True,
                       description="AI驱动的异常门店预警和对策"),
            PageRoute("/hq/ops/alerts", "预警中心", Terminal.ADMIN,
                       [AiEntryType.ALERT_CARD]),
        ],
    ),
    AgentModule(
        module_id="M8.4", name="报告生成", name_en="Report Generation",
        agent_id="hq_analytics", adaptation_mode="A", priority="P0",
        description="周报/月报/季报草拟",
        pages=[
            PageRoute("/hq/ai-report", "AI报告生成", Terminal.ADMIN,
                       [AiEntryType.SUGGESTION], is_new=True,
                       description="AI草拟经营报告（周报/月报）"),
        ],
    ),
]


# ── 索引和查询 ────────────────────────────────────────────────────────────────

MODULE_INDEX: dict[str, AgentModule] = {m.module_id: m for m in AGENT_MODULES}


def get_modules_by_agent(agent_id: str) -> list[AgentModule]:
    """获取某 Agent 的所有二级模块"""
    return [m for m in AGENT_MODULES if m.agent_id == agent_id]


def get_modules_by_terminal(terminal: Terminal) -> list[AgentModule]:
    """获取某终端涉及的所有模块"""
    return [
        m for m in AGENT_MODULES
        if any(p.terminal == terminal for p in m.pages)
    ]


def get_new_pages() -> list[PageRoute]:
    """获取所有需要新增的页面"""
    pages = []
    for m in AGENT_MODULES:
        for p in m.pages:
            if p.is_new:
                pages.append(p)
    return pages


def get_new_pages_by_terminal(terminal: Terminal) -> list[PageRoute]:
    """获取某终端需要新增的页面"""
    return [p for p in get_new_pages() if p.terminal == terminal]


def get_pages_by_ai_entry(entry_type: AiEntryType) -> list[tuple[AgentModule, PageRoute]]:
    """获取某AI入口类型的所有页面"""
    results = []
    for m in AGENT_MODULES:
        for p in m.pages:
            if entry_type in p.ai_entry_types:
                results.append((m, p))
    return results


def get_module_summary() -> dict:
    """获取模块总览统计"""
    agents: dict[str, list[str]] = {}
    for m in AGENT_MODULES:
        if m.agent_id not in agents:
            agents[m.agent_id] = []
        agents[m.agent_id].append(m.module_id)

    total_pages = sum(len(m.pages) for m in AGENT_MODULES)
    new_pages = len(get_new_pages())
    by_mode = {"A": 0, "B": 0, "C": 0}
    for m in AGENT_MODULES:
        by_mode[m.adaptation_mode] = by_mode.get(m.adaptation_mode, 0) + 1

    return {
        "total_modules": len(AGENT_MODULES),
        "total_agents": len(agents),
        "total_pages": total_pages,
        "new_pages": new_pages,
        "existing_pages": total_pages - new_pages,
        "by_adaptation_mode": by_mode,
        "by_agent": {k: len(v) for k, v in agents.items()},
    }
