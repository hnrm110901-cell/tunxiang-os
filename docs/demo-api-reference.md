# 演示环境 API 端点清单

> 演示客户：尝在一起（tenant_id: 10000000-0000-0000-0000-000000000001）
> Gateway 地址：http://localhost:8000（demo 环境）
> 所有请求需携带 Header：`X-Tenant-ID: 10000000-0000-0000-0000-000000000001`
> 响应格式：`{ "ok": true, "data": {}, "error": null }`

---

## 一、经营驾驶舱（tx-analytics :8009）

### 1.1 Boss BI — 今日 KPI 汇总
```
GET /api/v1/boss-bi/kpi/today?tenant_id={tenant_id}
```
响应示例：
```json
{
  "revenue_fen": 4856000,
  "order_count": 86,
  "avg_ticket_fen": 14800,
  "gross_profit_rate": 0.64,
  "customer_count": 210,
  "vs_yesterday_pct": 8.3
}
```

### 1.2 Boss BI — 品牌门店排名
```
GET /api/v1/boss-bi/brands/ranking?tenant_id={tenant_id}&date={YYYY-MM-DD}
```

### 1.3 Boss BI — 经营预警
```
GET /api/v1/boss-bi/alerts?tenant_id={tenant_id}&store_id={store_id}
```

### 1.4 Boss BI — 晨报（每日简报）
```
GET /api/v1/boss-bi/daily-brief?tenant_id={tenant_id}
```

### 1.5 Boss BI — 门店营收趋势
```
GET /api/v1/boss-bi/store/{store_id}/trend?tenant_id={tenant_id}&days=30
```

### 1.6 Dashboard — 门店今日数据
```
GET /api/v1/dashboard/today/{store_id}?tenant_id={tenant_id}
```
响应示例：
```json
{
  "store_id": "...",
  "revenue_fen": 1620000,
  "order_count": 32,
  "avg_ticket_fen": 16800,
  "table_turnover": 3.2
}
```

### 1.7 Dashboard — 多店概览
```
GET /api/v1/dashboard/stores?tenant_id={tenant_id}
```

### 1.8 Dashboard — 门店排名
```
GET /api/v1/dashboard/ranking?tenant_id={tenant_id}&date={YYYY-MM-DD}
```

### 1.9 Dashboard — 预警统计
```
GET /api/v1/dashboard/alerts/stats?tenant_id={tenant_id}
GET /api/v1/dashboard/alerts/{store_id}?tenant_id={tenant_id}
```

### 1.10 门店详细分析
```
GET /api/v1/analysis/store/{store_id}/revenue?tenant_id={tenant_id}&start_date=&end_date=
GET /api/v1/analysis/store/{store_id}/turnover?tenant_id={tenant_id}
GET /api/v1/analysis/store/{store_id}/ticket?tenant_id={tenant_id}
GET /api/v1/analysis/store/{store_id}/peak-hours?tenant_id={tenant_id}
POST /api/v1/analysis/store/comparison  body: {tenant_id, store_ids: [...], date_range}
```

### 1.11 每日简报
```
GET /api/v1/analytics/daily-brief/{store_id}?tenant_id={tenant_id}
GET /api/v1/analytics/daily-brief/history?tenant_id={tenant_id}&store_id=&days=7
GET /api/v1/analytics/daily-brief/group?tenant_id={tenant_id}
```

### 1.12 异常检测
```
GET /api/v1/analytics/anomaly?tenant_id={tenant_id}&store_id=&date=
```

---

## 二、AI 经营合伙人（tx-agent :8008）

### 2.1 AI 对话问答（Chief Agent Chat）
```
POST /api/v1/agent/chat
Body: {
  "session_id": "sess_czyz_demo_001",
  "message": "本周营收趋势怎么样？",
  "tenant_id": "10000000-0000-0000-0000-000000000001",
  "store_id": "optional"
}
```
响应示例：
```json
{
  "answer": "本周三店合计营收156万，环比上周增长8.3%，文化城店表现最好...",
  "confidence": 0.87,
  "data_sources": ["operation_snapshots", "boss-bi"],
  "actions": []
}
```

### 2.2 Agent 执行（触发 Skill Agent）
```
POST /api/v1/agent/execute
Body: {
  "action": "discount_check",
  "tenant_id": "...",
  "store_id": "...",
  "params": {}
}
```

### 2.3 Agent 任务状态查询
```
GET /api/v1/agent/tasks/{task_id}?tenant_id={tenant_id}
```

### 2.4 Agent Hub — 状态总览
```
GET /api/v1/agent-hub/status?tenant_id={tenant_id}&store_id={store_id}
```
响应示例：
```json
{
  "active_agents": 4,
  "pending_actions": 3,
  "last_decision_at": "2026-04-11T09:23:00+08:00"
}
```

### 2.5 Agent Hub — 待确认动作列表
```
GET /api/v1/agent-hub/actions?tenant_id={tenant_id}&store_id={store_id}&status=pending
```
响应示例：
```json
[{
  "action_id": "act_001",
  "agent": "discount_guard",
  "description": "建议停止88折促销，当前毛利率已降至28%",
  "risk_level": "high",
  "created_at": "..."
}]
```

### 2.6 Agent Hub — 确认/驳回动作
```
POST /api/v1/agent-hub/actions/{action_id}/confirm
POST /api/v1/agent-hub/actions/{action_id}/dismiss
Body: { "tenant_id": "...", "reason": "optional" }
```

### 2.7 Agent Hub — 决策日志
```
GET /api/v1/agent-hub/log?tenant_id={tenant_id}&store_id={store_id}&page=1&size=20
```
响应示例：
```json
{
  "items": [{
    "decision_type": "discount_risk",
    "reasoning": "客单价连续3日低于目标值",
    "confidence": 0.91,
    "created_at": "..."
  }],
  "total": 48
}
```

### 2.8 Agent 监控 — 运行状态
```
GET /api/v1/agent-monitor/status?tenant_id={tenant_id}
```

### 2.9 Agent 监控 — 决策记录
```
GET /api/v1/agent-monitor/decisions?tenant_id={tenant_id}&store_id=&page=1&size=20
```

### 2.10 门店工作台 — 健康度概览
```
GET /api/v1/store-health/overview?tenant_id={tenant_id}
GET /api/v1/store-health/{store_id}?tenant_id={tenant_id}
```

### 2.11 每日晨检（Today's Checklist）
```
GET /api/v1/daily-review/today?tenant_id={tenant_id}&store_id={store_id}
```
响应示例：
```json
{
  "date": "2026-04-11",
  "store_id": "...",
  "nodes": [
    {"code": "E1", "name": "早班清点", "status": "done", "completed_at": "..."},
    {"code": "E2", "name": "食安自查", "status": "pending"},
    {"code": "E3", "name": "营业准备", "status": "pending"}
  ],
  "completion_rate": 0.33
}
```

### 2.12 多店晨检汇总
```
GET /api/v1/daily-review/multi-store?tenant_id={tenant_id}
```

---

## 三、KDS 出餐系统（tx-trade :8001）

### 3.1 KDS 工单列表
```
GET /api/v1/kds/tasks?store_id={store_id}&tenant_id={tenant_id}&status=pending
```
响应示例：
```json
[{
  "task_id": "kds_task_001",
  "order_id": "order_abc",
  "table_no": "A12",
  "dept_name": "热菜档口",
  "items": [
    {"name": "剁椒鱼头", "qty": 1, "spec": "大份"},
    {"name": "口水鸡", "qty": 2, "spec": "正常"}
  ],
  "status": "pending",
  "elapsed_seconds": 320,
  "limit_seconds": 480,
  "is_rush": false
}]
```

### 3.2 KDS 工单 — 按档口队列
```
GET /api/v1/kds/queue/{dept_id}?store_id={store_id}&tenant_id={tenant_id}
```

### 3.3 KDS 工单 — 门店出餐概览
```
GET /api/v1/kds/overview/{store_id}?tenant_id={tenant_id}
```
响应示例：
```json
{
  "pending_count": 5,
  "avg_wait_seconds": 340,
  "timeout_count": 1,
  "rush_count": 0
}
```

### 3.4 KDS 工单 — 开始制作
```
POST /api/v1/kds/task/{task_id}/start
Body: { "tenant_id": "...", "store_id": "..." }
```

### 3.5 KDS 工单 — 完成出餐
```
POST /api/v1/kds/task/{task_id}/finish
Body: { "tenant_id": "...", "store_id": "..." }
```

### 3.6 KDS 工单 — 催单
```
POST /api/v1/kds/task/{task_id}/rush
Body: { "tenant_id": "...", "store_id": "...", "reason": "optional" }
```

### 3.7 KDS 工单 — 派单
```
POST /api/v1/kds/dispatch/{order_id}
Body: { "tenant_id": "...", "store_id": "..." }
```

### 3.8 KDS 超时工单列表
```
GET /api/v1/kds/timeouts/{store_id}?tenant_id={tenant_id}
```

---

## 四、菜品菜单（tx-menu :8002）

### 4.1 菜品列表
```
GET /api/v1/menu/dishes?tenant_id={tenant_id}&store_id={store_id}&status=active
```
响应示例：
```json
[{
  "id": "...",
  "dish_name": "剁椒鱼头",
  "category": "招牌湘菜",
  "sale_price_fen": 6800,
  "cost_price_fen": 1800,
  "status": "active"
}]
```

### 4.2 菜品分类列表
```
GET /api/v1/menu/categories?tenant_id={tenant_id}
```
响应示例：
```json
[
  {"id": "cat_001", "name": "招牌湘菜", "sort_order": 1},
  {"id": "cat_002", "name": "时令小炒", "sort_order": 2}
]
```

### 4.3 菜品详情
```
GET /api/v1/menu/dishes/{dish_id}?tenant_id={tenant_id}
```

### 4.4 门店当前可用菜单
```
GET /api/v1/menu/stores/{store_id}/menu?tenant_id={tenant_id}
```

### 4.5 菜品销售排名
```
GET /api/v1/menu/ranking?tenant_id={tenant_id}&store_id=&period=week
```

### 4.6 菜品四象限分析
```
GET /api/v1/menu/dishes/{dish_id}/quadrant?tenant_id={tenant_id}
```

---

## 五、门店工作台待办（tx-ops :8005）

### 5.1 今日日清节点（今日待办）
```
GET /api/v1/ops/daily/{store_id}?tenant_id={tenant_id}
```
响应示例：
```json
{
  "date": "2026-04-11",
  "store_id": "...",
  "nodes": [
    {"node_code": "E1", "name": "开店准备", "status": "done", "completed_at": "08:32"},
    {"node_code": "E2", "name": "食安晨检", "status": "in_progress"},
    {"node_code": "E3", "name": "备货盘点", "status": "pending"},
    {"node_code": "E4", "name": "晚班交接", "status": "pending"}
  ]
}
```

### 5.2 完成节点
```
POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/complete
Body: { "tenant_id": "...", "operator_id": "..." }
```

### 5.3 跳过节点
```
POST /api/v1/ops/daily/{store_id}/nodes/{node_code}/skip
Body: { "tenant_id": "...", "reason": "..." }
```

### 5.4 今日运营时间线
```
GET /api/v1/ops/daily/{store_id}/timeline?tenant_id={tenant_id}
```

---

## 六、认证（gateway :8000）

### 6.1 登录
```
POST /api/v1/auth/login
Body: { "username": "czyz_admin", "password": "demo2026" }
```
响应示例：
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "tenant_id": "10000000-0000-0000-0000-000000000001",
  "role": "brand_admin"
}
```

### 演示账号（密码统一：demo2026）
| 账号 | 角色 | 适用门店 |
|------|------|----------|
| czyz_admin | brand_admin | 全品牌（三店总览） |
| czyz_wh | store_manager | 文化城店 |
| czyz_lxx | store_manager | 浏小鲜 |
| czyz_ya | store_manager | 永安店 |

---

## 七、尝在一起门店参数

| 门店 | 品智ID | 屯象UUID |
|------|--------|----------|
| 文化城店 | 2461 | 由 uuid5(DNS, "czyz:pinzhi:2461") 生成 |
| 浏小鲜 | 7269 | 由 uuid5(DNS, "czyz:pinzhi:7269") 生成 |
| 永安店 | 19189 | 由 uuid5(DNS, "czyz:pinzhi:19189") 生成 |

---

## 八、Gateway 路由规则

Gateway（:8000）使用通配路由 `/api/v1/{domain}/{path}` 按第一段 domain 转发：

| domain 前缀 | 目标服务 | 端口 |
|------------|---------|------|
| `trade` | tx-trade | 8001 |
| `kds` | tx-trade（别名） | 8001 |
| `menu` | tx-menu | 8002 |
| `member` | tx-member | 8003 |
| `ops` | tx-ops | 8005 |
| `agent` | tx-agent | 8008 |
| `agent-hub` | tx-agent | 8008 |
| `agent-monitor` | tx-agent | 8008 |
| `daily-review` | tx-agent | 8008 |
| `store-health` | tx-agent | 8008 |
| `analytics` | tx-analytics | 8009 |
| `dashboard` | tx-analytics | 8009 |
| `boss-bi` | tx-analytics | 8009 |
| `store-analysis` | tx-analytics | 8009 |
| `analysis` | tx-analytics | 8009 |
| `brain` | tx-brain | 8010 |

> 注意：`dashboard` 和 `store-analysis`、`analysis`、`boss-bi` 等子域未在 DOMAIN_ROUTES 中单独注册，
> 前端需直接使用 `analytics` 作为 domain 前缀，或通过服务端口直连。
> 实际路由：`GET /api/v1/analytics/boss-bi/kpi/today` → gateway → tx-analytics

---

## 九、健康检查端点

| 服务 | 端点 |
|------|------|
| tx-analytics | GET http://localhost:8009/health |
| tx-agent | GET http://localhost:8008/api/v1/agent/health |
| tx-trade | GET http://localhost:8001/health |
| tx-menu | GET http://localhost:8002/health |
| tx-ops | GET http://localhost:8005/health |

---

*生成时间：2026-04-11 | 对应版本：v215+*
