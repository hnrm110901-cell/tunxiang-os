# 屯象OS 战略升级 — Claude Code 开发执行方案

> 将战略升级方案 U1-U3 拆解为可由 Claude Code + 超级智能体团队执行的具体开发任务
> 优先执行 U1（经营智能体进化），这是用户感知最强、技术可行性最高的阶段

---

## 总览：3 个 Sprint，6 周

| Sprint | 周期 | 主题 | 核心交付 |
|--------|------|------|--------|
| **SU1** | W1-2 | Agent 自主规划引擎 | 每日06:00自动经营计划 + 推送审批 |
| **SU2** | W3-4 | 决策反馈闭环 + Event Bus | 建议→执行→效果追踪→学习 |
| **SU3** | W5-6 | MCP Server + 多模态基础 | 73 action 开放 + 语音/视觉预留 |

---

## Sprint SU1：Agent 自主规划引擎（W1-2）

> 目标：Agent 从"被动响应"升级为"主动规划"，每天自动生成经营计划

### SU1-1：日计划 Agent（DailyPlannerAgent）

**新建文件**：`services/tx-agent/src/agents/planner.py`

```python
class DailyPlannerAgent:
    """每日经营计划 Agent — 06:00 自动执行"""

    async def generate_daily_plan(self, store_id, date) -> DailyPlan:
        """
        1. 拉取今日预订数据 → ReservationData
        2. 检查库存状态 → InventoryStatus（调用 inventory_alert Agent）
        3. 获取天气+客流预测 → TrafficForecast（调用 serve_dispatch Agent）
        4. 分析历史同期 → HistoricalComparison（调用 finance_audit Agent）
        5. 综合生成：
           - menu_suggestions: 今日排菜建议（主推/减推/新品试点）
           - procurement_list: 紧急采购清单
           - staffing_adjustments: 排班微调
           - marketing_triggers: 营销触发（给谁发什么券）
           - risk_alerts: 风险预警（库存不足/天气异常/设备故障）
        6. 包装为 DailyPlan → 推送审批
        """

    async def get_plan_status(self, store_id, date) -> dict:
        """查询计划执行状态（待审批/部分批准/全部执行）"""

    async def approve_plan(self, store_id, date, approved_items, rejected_items) -> dict:
        """店长审批计划（一键全批/逐条调整）"""
```

**数据模型**：`services/tx-agent/src/models/daily_plan.py`

```python
class DailyPlan(TenantBase):
    __tablename__ = "daily_plans"
    store_id: UUID
    plan_date: Date
    status: str  # draft/pending_approval/approved/executing/completed

    # 5大计划项
    menu_suggestions: JSON      # [{dish_id, action(push/reduce/try), reason, confidence}]
    procurement_list: JSON      # [{ingredient_id, quantity, urgency, supplier}]
    staffing_adjustments: JSON  # [{employee_id, action(add/remove/swap), shift, reason}]
    marketing_triggers: JSON    # [{target_segment, action(coupon/sms/wechat), content}]
    risk_alerts: JSON           # [{type, severity, detail, suggested_action}]

    # 审批
    approved_by: str
    approved_at: DateTime
    approval_notes: JSON        # 逐条审批结果

    # 执行追踪
    execution_status: JSON      # 每条建议的执行状态
    outcome_summary: JSON       # 48小时后的效果汇总
```

**API 端点**：`services/tx-agent/src/api/planner.py`

```
POST /api/v1/agent/plans/generate        — 手动触发生成（或定时06:00）
GET  /api/v1/agent/plans/{store_id}      — 查询今日计划
POST /api/v1/agent/plans/{plan_id}/approve — 审批计划
GET  /api/v1/agent/plans/{plan_id}/status  — 执行状态
GET  /api/v1/agent/plans/history          — 历史计划列表
```

**前端页面**：`apps/web-admin/src/pages/DailyPlanPage.tsx`（OS商家端）

```
布局：
┌─────────────────────────────────────────────┐
│ 今日经营计划 · 2026-03-25 · 芙蓉路店         │
│ 状态：待审批 ⏳                               │
├─────────────────────────────────────────────┤
│ 📋 排菜建议 (3条)                    [全部批准] │
│  ✅ 主推剁椒鱼头（鲈鱼库存充足+40%）  [批准][调整] │
│  ✅ 减推外婆鸡（鸡肉库存偏低）        [批准][调整] │
│  ⚠️ 试点酸菜鱼套餐（新品试点第3天）   [批准][跳过] │
├─────────────────────────────────────────────┤
│ 📦 紧急采购 (2条)                    [全部批准] │
│  🔴 虾仁 +30% 备量（今日预订含3桌虾菜） [批准]   │
│  🟡 青菜 常规补货                     [批准]    │
├─────────────────────────────────────────────┤
│ 👥 排班微调 (1条)                             │
│  增加1名服务员（天气晴+周末，预测客流+15%）      │
├─────────────────────────────────────────────┤
│ 📣 营销触发 (2条)                             │
│  给S2会员发午餐优惠券（周三未到店群体）          │
│  给生日客户发祝福+赠菜券                       │
├─────────────────────────────────────────────┤
│          [一键全部批准]  [逐条审批]             │
└─────────────────────────────────────────────┘
```

**测试**：≥15个
- 计划生成（正常/无预订/库存全充足）
- 多Agent协同调用验证
- 审批流程（全批/部分批/全拒）
- 计划状态流转

### SU1-2：定时任务调度

**新建文件**：`services/tx-agent/src/scheduler.py`

```python
# Celery Beat 定时任务
SCHEDULE = {
    "daily_plan_06:00": {
        "task": "generate_daily_plans",
        "schedule": crontab(hour=6, minute=0),
        "description": "为所有活跃门店生成今日经营计划",
    },
    "plan_reminder_08:00": {
        "task": "remind_unapproved_plans",
        "schedule": crontab(hour=8, minute=0),
        "description": "提醒未审批的计划（企微推送店长）",
    },
    "plan_auto_execute_09:00": {
        "task": "auto_execute_approved_plans",
        "schedule": crontab(hour=9, minute=0),
        "description": "自动执行已审批的计划项",
    },
    "plan_outcome_check": {
        "task": "check_plan_outcomes",
        "schedule": crontab(hour=22, minute=0),
        "description": "当日计划效果回收（为明天计划提供反馈）",
    },
}
```

### SU1-3：企微推送集成（计划审批通知）

**扩展文件**：`services/gateway/src/external_sdk.py` 中的 WecomSDK

```python
async def send_daily_plan_card(self, user_id, store_name, plan_summary, approve_url):
    """发送每日经营计划卡片 — 06:30 推送到店长企微"""
    title = f"【每日计划】{store_name} · {today}"
    description = f"""📋 排菜建议 {plan_summary['menu_count']} 条
📦 采购建议 {plan_summary['procurement_count']} 条
👥 排班调整 {plan_summary['staffing_count']} 条
📣 营销触发 {plan_summary['marketing_count']} 条
⚠️ 风险预警 {plan_summary['risk_count']} 条

预期今日节省：¥{plan_summary['expected_saving']}"""
```

---

## Sprint SU2：决策反馈闭环 + Event Bus（W3-4）

> 目标：Agent 建议→执行→效果追踪→学习优化

### SU2-1：决策反馈服务

**新建文件**：`services/tx-agent/src/services/decision_feedback.py`

```python
class DecisionFeedbackService:
    """决策效果追踪 — 闭环学习"""

    async def record_execution(self, decision_id, executed_by, execution_data):
        """记录决策执行"""

    async def collect_outcome(self, decision_id, hours_after=48):
        """收集决策效果（48小时后自动触发）
        对比建议前后的关键指标变化：
        - 排菜建议 → 对比推荐菜品销量变化
        - 采购建议 → 对比是否避免了缺货
        - 排班建议 → 对比人效变化
        - 营销建议 → 对比触达/转化率
        """

    async def compute_effectiveness_score(self, decision_id) -> float:
        """计算决策效果分（0-100）"""

    async def get_agent_learning_context(self, agent_id, store_id, limit=20):
        """获取Agent学习上下文 — 注入prompt提升下次决策质量
        返回最近20条决策的效果摘要：
        [{"decision": "主推剁椒鱼头", "outcome": "销量+40%", "score": 92},
         {"decision": "减推外婆鸡", "outcome": "销量-20%但库存消化慢", "score": 65}]
        """

    async def get_store_decision_stats(self, store_id, period="month"):
        """门店决策统计：采纳率/执行率/效果分均值"""
```

**数据模型扩展**：AgentDecisionLog 增加字段

```python
# 执行追踪
executed: bool = False
executed_at: DateTime
executed_by: str
execution_data: JSON

# 效果评估
outcome_collected: bool = False
outcome_data: JSON          # 执行后的实际业务指标
effectiveness_score: float  # 0-100 效果分
outcome_summary: str        # 一句话效果描述
```

### SU2-2：Event Bus（Redis Streams 实现）

**新建文件**：`services/tx-agent/src/agents/event_bus.py`

```python
class EventBus:
    """事件总线 — Redis Streams 实现，替代内存 Memory Bus"""

    async def publish(self, event: AgentEvent):
        """发布事件到 Redis Stream"""

    async def subscribe(self, event_types: list[str], handler: Callable):
        """订阅事件类型"""

    async def get_event_chain(self, correlation_id: str) -> list[AgentEvent]:
        """获取事件链路（追踪一个事件触发了哪些后续事件）"""

class AgentEvent:
    event_id: str
    event_type: str           # inventory_alert / menu_change / price_update / ...
    source_agent: str
    store_id: str
    data: dict
    correlation_id: str       # 事件链路追踪ID
    timestamp: datetime

# 事件类型注册表
EVENT_HANDLERS = {
    "inventory_surplus": [
        ("smart_menu", "adjust_recommendations"),    # 库存充足→调整推荐
        ("private_ops", "trigger_promotion"),         # 库存充足→触发促销
    ],
    "inventory_shortage": [
        ("smart_menu", "reduce_recommendations"),    # 库存不足→减少推荐
        ("serve_dispatch", "alert_kitchen"),          # 库存不足→通知厨房
    ],
    "discount_violation": [
        ("discount_guard", "block_transaction"),     # 折扣违规→拦截交易
        ("private_ops", "notify_manager"),            # 折扣违规→通知店长
    ],
    "vip_arrival": [
        ("member_insight", "load_preferences"),      # VIP到店→加载偏好
        ("serve_dispatch", "assign_best_waiter"),    # VIP到店→分配最佳服务员
        ("smart_menu", "prepare_recommendations"),   # VIP到店→准备推荐
    ],
}
```

### SU2-3：Agent 可观测性面板

**新建页面**：`apps/web-hub/src/pages/AgentObservabilityPage.tsx`

```
布局：
┌──────────────────────────────────────────────────┐
│ Agent 可观测性 · 全局视图                          │
├──────────────────────────────────────────────────┤
│ [实时事件流]  [决策追踪]  [效果分析]  [学习日志]     │
├──────────────────────────────────────────────────┤
│                                                  │
│ 实时事件流（最近100条）                            │
│ ┌────────────────────────────────────────────┐  │
│ │ 08:15 inventory_alert → smart_menu          │  │
│ │   "鲈鱼到货+50%" → "调整推荐：主推鲈鱼系列"    │  │
│ │ 08:15 smart_menu → private_ops               │  │
│ │   "推荐变更" → "给海鲜爱好者发推荐通知"         │  │
│ │ 08:16 discount_guard → (blocked)             │  │
│ │   "A05桌折扣62%" → "拦截！毛利底线违规"        │  │
│ └────────────────────────────────────────────┘  │
│                                                  │
│ 决策效果排行（本月）                               │
│ ┌────────────────────────────────────────────┐  │
│ │ Agent          │ 建议数 │ 采纳率 │ 效果分    │  │
│ │ 库存预警        │  156  │  92%  │  87.3    │  │
│ │ 智能排菜        │  89   │  85%  │  82.1    │  │
│ │ 折扣守护        │  234  │  98%  │  95.0    │  │
│ └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

---

## Sprint SU3：MCP Server + 多模态基础（W5-6）

> 目标：将 73 个 Agent action 开放为 MCP 协议，任何 AI 可调用

### SU3-1：MCP Server 实现

**新建目录**：`services/mcp-server/`

```python
# services/mcp-server/src/main.py
"""屯象OS MCP Server — 将餐饮 Agent 能力开放为标准协议"""

from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("tunxiang-restaurant")

# 注册所有 73 个 Agent action 为 MCP Tool
@server.tool("analyze_store_health")
async def analyze_store_health(store_id: str, date: str = "today"):
    """分析门店经营健康度（5维加权评分）"""
    # 调用 store_health_service

@server.tool("predict_inventory")
async def predict_inventory(store_id: str, ingredient_id: str, days: int = 7):
    """预测食材消耗量（4种算法自动选优）"""

@server.tool("generate_menu_ranking")
async def generate_menu_ranking(store_id: str, time_slot: str = "lunch"):
    """生成菜品排名（5因子加权：趋势+毛利+库存+时段+退单）"""

@server.tool("detect_discount_anomaly")
async def detect_discount_anomaly(order_data: dict):
    """检测折扣异常（边缘实时+风险评分）"""

@server.tool("compose_business_brief")
async def compose_business_brief(store_id: str):
    """生成经营简报（≤200字，含异常+建议）"""

@server.tool("generate_daily_plan")
async def generate_daily_plan(store_id: str):
    """生成每日经营计划（5大维度）"""

# ... 注册全部 73 个 action
```

**配置文件**：`services/mcp-server/mcp.json`

```json
{
  "name": "tunxiang-restaurant",
  "version": "1.0.0",
  "description": "连锁餐饮行业 AI Agent 能力集 — 屯象OS",
  "tools": 73,
  "categories": [
    "restaurant_operations",
    "inventory_management",
    "menu_optimization",
    "customer_analytics",
    "financial_audit",
    "workforce_management"
  ]
}
```

### SU3-2：语音交互基础

**新建文件**：`edge/mac-station/src/voice_service.py`

```python
class VoiceService:
    """语音交互服务 — Mac mini Core ML Whisper"""

    async def transcribe(self, audio_data: bytes) -> str:
        """语音转文字（调用 coreml-bridge /transcribe）"""

    async def parse_intent(self, text: str) -> dict:
        """解析语音意图
        "今天营收多少" → {intent: "query_revenue", params: {date: "today"}}
        "鲈鱼还有多少" → {intent: "query_inventory", params: {ingredient: "鲈鱼"}}
        "帮我报一个缺料" → {intent: "report_shortage", params: {}}
        """

    async def execute_voice_command(self, intent: dict) -> str:
        """执行语音命令并返回语音回复文本"""
```

**WebSocket 端点**：`/ws/voice/{store_id}`
- 厨师通过骨传导耳机发出语音指令
- Mac mini 本地 Whisper 转文字
- 解析意图 → 调用对应 Agent → 语音回复

### SU3-3：视觉质检基础

**新建文件**：`edge/mac-station/src/vision_service.py`

```python
class VisionService:
    """视觉质检服务 — Mac mini Core ML Vision"""

    async def inspect_dish(self, image_data: bytes, dish_name: str) -> dict:
        """菜品出品质量检测
        Returns: {score: 85, issues: ["摆盘不规范"], passed: True}
        """

    async def inspect_hygiene(self, image_data: bytes, area: str) -> dict:
        """后厨卫生巡检
        Returns: {score: 92, issues: [], compliant: True}
        """

    async def count_customers(self, image_data: bytes) -> int:
        """客流计数（入口摄像头）"""
```

---

## 智能体分工

| Sprint | Agent 1 | Agent 2 | Agent 3 | 主线程 |
|--------|---------|---------|---------|--------|
| **SU1** | DailyPlannerAgent + 模型 + API | 前端DailyPlanPage + 审批流 | 定时任务 + 企微推送 | 测试 + 集成 |
| **SU2** | DecisionFeedback 服务 + 模型扩展 | Event Bus(Redis Streams) + 事件注册 | AgentObservabilityPage(Hub) | 测试 + 集成 |
| **SU3** | MCP Server(73 tools注册) | 语音服务 + 意图解析 | 视觉服务 + 质检 | 测试 + 文档 |

---

## 验收标准

### SU1 验收
- [ ] Agent 06:00 自动生成经营计划（5大维度）
- [ ] 企微推送计划卡片到店长
- [ ] 店长在 OS 端一键审批/逐条调整
- [ ] 计划执行状态可追踪
- [ ] ≥15 个测试通过

### SU2 验收
- [ ] 决策48小时后自动收集效果数据
- [ ] 效果分注入下次 Agent prompt
- [ ] Event Bus 事件链路可追踪
- [ ] Hub 可观测性面板实时展示事件流
- [ ] ≥12 个测试通过

### SU3 验收
- [ ] MCP Server 可被 Claude Desktop 调用
- [ ] 语音 "今天营收多少" → 返回数据
- [ ] 视觉质检 → 返回评分
- [ ] ≥10 个测试通过

---

## 预期成果

| 指标 | V3.4(当前) | U1完成后 |
|------|---------|---------|
| Tests | 549 | **≥590** |
| Agent actions | 73 | **73 + 日计划引擎** |
| API endpoints | ~200 | **~220** |
| 前端页面 | 57 | **59**（+日计划+可观测性） |
| MCP Tools | 0 | **73** |
| 事件类型 | 0 | **10+** |

**核心价值**：从"老板问 Agent 才回答"变为"Agent 每天主动告诉老板该做什么"。这是从工具到经营伙伴的质变。
