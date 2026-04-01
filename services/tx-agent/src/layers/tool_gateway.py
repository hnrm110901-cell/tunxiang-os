"""L3 Tool/MCP 网关层 — Agent 受控工具调用

核心原则：Agent 不能直接碰数据库，只能通过受控工具完成动作。

每个 Tool 定义：
- name: 工具名称
- description: 描述（供 LLM 理解）
- parameters: 参数 schema
- requires_confirmation: 是否需要人工确认
- allowed_roles: 允许调用的角色
- execute: 执行函数（实际调用域服务）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import structlog

from .scene_session import UserRole

logger = structlog.get_logger()


class ToolCategory(str, Enum):
    """工具分类"""
    RESERVATION = "reservation"     # 预订
    WAITLIST = "waitlist"           # 等位
    TABLE = "table"                 # 桌台
    MENU = "menu"                   # 菜单
    ORDER = "order"                 # 订单
    KITCHEN = "kitchen"             # 厨房
    MEMBER = "member"               # 会员
    PAYMENT = "payment"             # 支付
    REPORT = "report"               # 报表
    NOTIFICATION = "notification"   # 消息通知
    TASK = "task"                   # 审批/工单


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    category: ToolCategory
    parameters: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    allowed_roles: list[UserRole] = field(default_factory=list)
    is_read_only: bool = False


@dataclass
class ToolCallResult:
    """工具调用结果"""
    tool_name: str
    success: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


# ── 工具注册表 ────────────────────────────────────────────────────────────────

# 所有 Agent 可用的工具定义
TOOL_DEFINITIONS: list[ToolDefinition] = [
    # ── 预订工具 ──
    ToolDefinition(
        name="query_reservations",
        description="查询预订列表，支持按日期、时段、状态筛选",
        category=ToolCategory.RESERVATION,
        parameters={"date": "str", "time_slot": "str?", "status": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER, UserRole.HQ_EXECUTIVE],
    ),
    ToolDefinition(
        name="create_reservation",
        description="创建新预订，包含顾客信息、桌位、时间",
        category=ToolCategory.RESERVATION,
        parameters={"customer_phone": "str", "party_size": "int", "date": "str", "time": "str", "table_id": "str?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER],
    ),
    ToolDefinition(
        name="modify_reservation",
        description="修改预订（改时间、改桌位、改人数）",
        category=ToolCategory.RESERVATION,
        parameters={"reservation_id": "str", "changes": "dict"},
        requires_confirmation=True,
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER],
    ),
    ToolDefinition(
        name="cancel_reservation",
        description="取消预订",
        category=ToolCategory.RESERVATION,
        parameters={"reservation_id": "str", "reason": "str?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER],
    ),

    # ── 等位工具 ──
    ToolDefinition(
        name="query_waitlist",
        description="查询当前等位队列",
        category=ToolCategory.WAITLIST,
        parameters={"store_id": "str"},
        is_read_only=True,
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER],
    ),
    ToolDefinition(
        name="add_to_waitlist",
        description="加入等位队列",
        category=ToolCategory.WAITLIST,
        parameters={"customer_phone": "str?", "party_size": "int", "preference": "str?"},
        allowed_roles=[UserRole.HOST],
    ),
    ToolDefinition(
        name="call_next_waitlist",
        description="叫号（通知下一位等位顾客）",
        category=ToolCategory.WAITLIST,
        parameters={"waitlist_id": "str", "table_id": "str"},
        allowed_roles=[UserRole.HOST, UserRole.STORE_MANAGER],
    ),

    # ── 桌台工具 ──
    ToolDefinition(
        name="query_table_status",
        description="查询桌台状态（全部或指定桌号）",
        category=ToolCategory.TABLE,
        parameters={"store_id": "str", "table_id": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.HOST, UserRole.WAITER, UserRole.STORE_MANAGER],
    ),
    ToolDefinition(
        name="open_table",
        description="开台（将桌台状态设为占用）",
        category=ToolCategory.TABLE,
        parameters={"table_id": "str", "party_size": "int", "customer_id": "str?"},
        allowed_roles=[UserRole.HOST, UserRole.WAITER, UserRole.CASHIER],
    ),
    ToolDefinition(
        name="merge_tables",
        description="并台操作",
        category=ToolCategory.TABLE,
        parameters={"table_ids": "list[str]"},
        requires_confirmation=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.WAITER],
    ),

    # ── 菜单工具 ──
    ToolDefinition(
        name="query_menu",
        description="查询菜单（支持分类、价格范围、口味筛选）",
        category=ToolCategory.MENU,
        parameters={"category": "str?", "price_range": "str?", "tags": "list[str]?"},
        is_read_only=True,
        allowed_roles=list(UserRole),
    ),
    ToolDefinition(
        name="recommend_dishes",
        description="根据顾客画像和当前库存推荐菜品",
        category=ToolCategory.MENU,
        parameters={"customer_id": "str?", "party_size": "int?", "preferences": "list[str]?"},
        is_read_only=True,
        allowed_roles=[UserRole.WAITER, UserRole.CUSTOMER],
    ),
    ToolDefinition(
        name="set_dish_availability",
        description="设置菜品可售状态（估清/停售/恢复）",
        category=ToolCategory.MENU,
        parameters={"dish_id": "str", "available": "bool", "reason": "str?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.CHEF, UserRole.STORE_MANAGER],
    ),

    # ── 订单工具 ──
    ToolDefinition(
        name="query_orders",
        description="查询订单列表",
        category=ToolCategory.ORDER,
        parameters={"store_id": "str", "status": "str?", "table_id": "str?", "date": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.WAITER, UserRole.CASHIER, UserRole.STORE_MANAGER],
    ),
    ToolDefinition(
        name="create_order",
        description="创建订单（点菜）",
        category=ToolCategory.ORDER,
        parameters={"table_id": "str", "items": "list[dict]", "customer_id": "str?"},
        allowed_roles=[UserRole.WAITER, UserRole.CASHIER, UserRole.CUSTOMER],
    ),
    ToolDefinition(
        name="add_order_items",
        description="加菜",
        category=ToolCategory.ORDER,
        parameters={"order_id": "str", "items": "list[dict]"},
        allowed_roles=[UserRole.WAITER, UserRole.CUSTOMER],
    ),

    # ── 厨房工具 ──
    ToolDefinition(
        name="query_kitchen_status",
        description="查询厨房出品状态（各工位排队数、超时菜品）",
        category=ToolCategory.KITCHEN,
        parameters={"store_id": "str"},
        is_read_only=True,
        allowed_roles=[UserRole.CHEF, UserRole.STORE_MANAGER, UserRole.WAITER],
    ),
    ToolDefinition(
        name="expedite_dish",
        description="催菜（提高出品优先级）",
        category=ToolCategory.KITCHEN,
        parameters={"order_item_id": "str", "reason": "str?"},
        allowed_roles=[UserRole.WAITER, UserRole.STORE_MANAGER],
    ),

    # ── 会员工具 ──
    ToolDefinition(
        name="query_member_profile",
        description="查询会员画像（RFM、偏好、消费记录）",
        category=ToolCategory.MEMBER,
        parameters={"customer_id": "str?", "phone": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.WAITER, UserRole.CASHIER, UserRole.STORE_MANAGER, UserRole.HOST],
    ),
    ToolDefinition(
        name="issue_coupon",
        description="发放优惠券",
        category=ToolCategory.MEMBER,
        parameters={"customer_id": "str", "coupon_template_id": "str", "reason": "str?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.HQ_ANALYST],
    ),
    ToolDefinition(
        name="query_member_segments",
        description="查询会员分群和标签统计",
        category=ToolCategory.MEMBER,
        parameters={"segment_type": "str?", "store_id": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.HQ_ANALYST, UserRole.HQ_EXECUTIVE],
    ),

    # ── 支付查询工具 ──
    ToolDefinition(
        name="query_payment_status",
        description="查询支付状态",
        category=ToolCategory.PAYMENT,
        parameters={"order_id": "str"},
        is_read_only=True,
        allowed_roles=[UserRole.CASHIER, UserRole.STORE_MANAGER],
    ),

    # ── 报表工具 ──
    ToolDefinition(
        name="query_sales_summary",
        description="查询销售汇总（按日/周/月）",
        category=ToolCategory.REPORT,
        parameters={"store_id": "str?", "period": "str", "start_date": "str", "end_date": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.AREA_MANAGER, UserRole.HQ_ANALYST, UserRole.HQ_EXECUTIVE],
    ),
    ToolDefinition(
        name="query_kpi_dashboard",
        description="查询KPI仪表盘（翻台率、客单价、人效等）",
        category=ToolCategory.REPORT,
        parameters={"store_id": "str?", "date": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.AREA_MANAGER, UserRole.HQ_ANALYST, UserRole.HQ_EXECUTIVE],
    ),
    ToolDefinition(
        name="compare_stores",
        description="多门店经营指标对比",
        category=ToolCategory.REPORT,
        parameters={"store_ids": "list[str]", "metrics": "list[str]", "period": "str"},
        is_read_only=True,
        allowed_roles=[UserRole.AREA_MANAGER, UserRole.HQ_ANALYST, UserRole.HQ_EXECUTIVE],
    ),

    # ── 消息通知工具 ──
    ToolDefinition(
        name="send_notification",
        description="发送通知（短信/微信/企业微信）",
        category=ToolCategory.NOTIFICATION,
        parameters={"target_type": "str", "target_id": "str", "template": "str", "params": "dict?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.HQ_ANALYST],
    ),

    # ── 工单工具 ──
    ToolDefinition(
        name="create_task",
        description="创建整改/跟进任务",
        category=ToolCategory.TASK,
        parameters={"title": "str", "description": "str", "assignee_id": "str", "priority": "str", "due_date": "str?"},
        requires_confirmation=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.AREA_MANAGER, UserRole.HQ_ANALYST],
    ),
    ToolDefinition(
        name="query_tasks",
        description="查询任务列表",
        category=ToolCategory.TASK,
        parameters={"store_id": "str?", "status": "str?", "assignee_id": "str?"},
        is_read_only=True,
        allowed_roles=[UserRole.STORE_MANAGER, UserRole.AREA_MANAGER, UserRole.HQ_ANALYST, UserRole.HQ_EXECUTIVE],
    ),
]


# ── Tool 名称索引 ─────────────────────────────────────────────────────────────

TOOL_INDEX: dict[str, ToolDefinition] = {t.name: t for t in TOOL_DEFINITIONS}


# ── Tool 网关 ─────────────────────────────────────────────────────────────────

class ToolGateway:
    """L3 Tool/MCP 网关

    Agent 通过 ToolGateway 调用工具。网关负责：
    1. 权限校验（角色 + 工具级别）
    2. 参数校验
    3. 确认拦截（需人工确认的动作）
    4. 调用域服务
    5. 审计日志
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """注册工具的实际执行函数"""
        if tool_name not in TOOL_INDEX:
            raise ValueError(f"Unknown tool: {tool_name}")
        self._handlers[tool_name] = handler

    def get_tools_for_agent(self, agent_id: str) -> list[dict]:
        """获取某 Agent 可用的工具列表（供 LLM function calling）

        返回格式兼容 Claude API tool_use。
        """
        agent_tool_mapping = _AGENT_TOOL_MAPPING.get(agent_id, [])
        tools = []
        for tool_name in agent_tool_mapping:
            defn = TOOL_INDEX.get(tool_name)
            if defn:
                tools.append({
                    "name": defn.name,
                    "description": defn.description,
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            k: {"type": "string", "description": k}
                            for k in defn.parameters
                        },
                    },
                })
        return tools

    async def call_tool(
        self,
        tool_name: str,
        params: dict,
        caller_role: UserRole,
        caller_agent: str,
        tenant_id: str,
    ) -> ToolCallResult:
        """调用工具（带权限校验和审计）"""
        defn = TOOL_INDEX.get(tool_name)
        if not defn:
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        # 权限校验
        if defn.allowed_roles and caller_role not in defn.allowed_roles:
            logger.warning(
                "tool_access_denied",
                tool=tool_name,
                role=caller_role.value,
                agent=caller_agent,
            )
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=f"角色 {caller_role.value} 无权使用工具 {tool_name}",
            )

        # 需确认拦截
        if defn.requires_confirmation:
            return ToolCallResult(
                tool_name=tool_name,
                success=True,
                data={"action": "pending_confirmation", "params": params},
                requires_confirmation=True,
                confirmation_message=f"操作 [{defn.description}] 需要确认，是否执行？",
            )

        # 执行
        handler = self._handlers.get(tool_name)
        if not handler:
            # 无 handler 时返回模拟结果（开发阶段）
            logger.info("tool_stub_called", tool=tool_name, params=params)
            return ToolCallResult(
                tool_name=tool_name,
                success=True,
                data={"stub": True, "tool": tool_name, "params": params},
            )

        try:
            result = await handler(params, tenant_id=tenant_id)
            logger.info(
                "tool_executed",
                tool=tool_name,
                agent=caller_agent,
                role=caller_role.value,
                success=True,
            )
            return ToolCallResult(tool_name=tool_name, success=True, data=result)
        except Exception as exc:
            logger.error(
                "tool_execution_failed",
                tool=tool_name,
                agent=caller_agent,
                error=str(exc),
                exc_info=True,
            )
            return ToolCallResult(
                tool_name=tool_name,
                success=False,
                error=str(exc),
            )

    async def execute_confirmed_tool(
        self,
        tool_name: str,
        params: dict,
        tenant_id: str,
    ) -> ToolCallResult:
        """执行已确认的工具（跳过确认拦截）"""
        handler = self._handlers.get(tool_name)
        if not handler:
            return ToolCallResult(
                tool_name=tool_name,
                success=True,
                data={"stub": True, "tool": tool_name, "params": params},
            )

        try:
            result = await handler(params, tenant_id=tenant_id)
            return ToolCallResult(tool_name=tool_name, success=True, data=result)
        except Exception as exc:
            return ToolCallResult(tool_name=tool_name, success=False, error=str(exc))


# ── Agent → Tool 映射 ────────────────────────────────────────────────────────

_AGENT_TOOL_MAPPING: dict[str, list[str]] = {
    "reception": [
        "query_reservations", "create_reservation", "modify_reservation",
        "cancel_reservation", "query_table_status", "query_member_profile",
        "send_notification",
    ],
    "waitlist_table": [
        "query_waitlist", "add_to_waitlist", "call_next_waitlist",
        "query_table_status", "open_table", "merge_tables",
    ],
    "ordering": [
        "query_menu", "recommend_dishes", "query_orders",
        "create_order", "add_order_items", "query_member_profile",
    ],
    "kitchen": [
        "query_kitchen_status", "expedite_dish", "set_dish_availability",
        "query_orders",
    ],
    "member_growth": [
        "query_member_profile", "query_member_segments", "issue_coupon",
        "send_notification",
    ],
    "checkout_risk": [
        "query_orders", "query_payment_status", "query_member_profile",
    ],
    "store_ops": [
        "query_sales_summary", "query_kpi_dashboard", "query_orders",
        "query_kitchen_status", "query_table_status", "create_task",
        "query_tasks", "send_notification",
    ],
    "hq_analytics": [
        "query_sales_summary", "query_kpi_dashboard", "compare_stores",
        "query_member_segments", "create_task", "query_tasks",
    ],
}
