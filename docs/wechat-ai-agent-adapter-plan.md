# 微信 AI 智能体适配设计方案

> 版本：V1.0 | 日期：2026-05-03 | 状态：草稿  
> 关联：`docs/wechat-ecosystem-dev-plan-v1.md` (WA-1)  
> 负责人：架构组

---

## 一、背景

微信计划 2026 年 Q3 全量上线 AI 智能体（对话式入口调用小程序）。用户可通过微信对话直接点餐、查询订单、预订桌位，无需手动打开小程序。

屯象 OS 需提前将小程序核心功能暴露为 OpenAI Function Calling 格式，使微信 AI 智能体能够理解并调用屯象服务。

### 时间线

| 里程碑 | 时间 | 动作 |
|--------|------|------|
| WA-1 适配准备 | 2026-05 (当前) | Function Schema 定义 + SDK + 语义参数 API |
| 微信内测对接 | 2026-06~07 | 与微信团队联调 Function Calling 协议 |
| WA-2 正式上线 | 2026 Q4 | 全量开放对话式点餐 |

---

## 二、架构概览

```
用户微信对话
    │ "帮我点上次的水煮鱼"
    ▼
微信 AI 智能体
    │ POST /function-calling (OpenAI 格式)
    ▼
屯象 Gateway (external_sdk.py)
    │ ┌─ WechatAIAgentSDK ──────────────────────┐
    │ │  1. query_menu(store_id, dish_name, cat) │
    │ │  2. create_order(store_id, dishes, pref) │
    │ │  3. query_order(order_id)                │
    │ │  4. query_member(openid)                 │
    │ │  5. query_coupons(openid, store_id)      │
    │ │  6. book_table(store_id, time, guests)   │
    │ └──────────────────────────────────────────┘
    │
    ├─→ tx-trade   (订单/桌位)
    ├─→ tx-menu    (菜品)
    ├─→ tx-member  (会员/优惠券)
    └─→ tx-growth  (营销)
```

### 核心原则

1. **Gateway 是唯一入口** — 所有 Function Calling 请求经过 Gateway，不直连业务服务
2. **语义层在 Gateway** — 自然语言→参数的映射在 WechatAIAgentSDK 中完成
3. **下游不动** — 业务服务（tx-trade/tx-menu/tx-member）不感知 AI 智能体存在
4. **Mock 模式** — 无微信配置时，SDK 返回模拟数据，不阻塞开发

---

## 三、Function Calling 定义

所有函数遵循 OpenAI Function Calling Schema 格式。6 个核心函数：

### 3.1 query_menu

```json
{
  "name": "query_menu",
  "description": "查询门店菜单和菜品信息。支持按菜品名称搜索或按分类浏览。",
  "parameters": {
    "type": "object",
    "properties": {
      "store_id": {
        "type": "string",
        "description": "门店 ID（如未知则填 'current'）"
      },
      "dish_name": {
        "type": "string",
        "description": "菜品名称关键词（可选，用于搜索特定菜品）"
      },
      "category": {
        "type": "string",
        "enum": ["全部", "招牌", "热菜", "凉菜", "汤品", "主食", "酒水", "套餐"],
        "description": "菜品分类（可选，过滤菜单）"
      }
    },
    "required": ["store_id"]
  }
}
```

### 3.2 create_order

```json
{
  "name": "create_order",
  "description": "提交订单。用户说出想点的菜品后，调用此函数创建订单。",
  "parameters": {
    "type": "object",
    "properties": {
      "store_id": {
        "type": "string",
        "description": "门店 ID"
      },
      "dishes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "dish_name": {"type": "string", "description": "菜品名称"},
            "quantity": {"type": "integer", "description": "数量", "default": 1},
            "spec": {"type": "string", "description": "规格（如: 大份/小份/微辣/中辣/特辣）"}
          },
          "required": ["dish_name"]
        },
        "description": "菜品列表"
      },
      "preference": {
        "type": "string",
        "description": "偏好说明（如: 少油、少盐、加急）"
      }
    },
    "required": ["store_id", "dishes"]
  }
}
```

### 3.3 query_order

```json
{
  "name": "query_order",
  "description": "查询订单状态。包括订单当前状态、预计出餐时间等。",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": {
        "type": "string",
        "description": "订单 ID（用户可在对话中提供订单号或手机号）"
      }
    },
    "required": ["order_id"]
  }
}
```

### 3.4 query_member

```json
{
  "name": "query_member",
  "description": "查询会员信息。包括等级、积分余额、储值余额。",
  "parameters": {
    "type": "object",
    "properties": {
      "openid": {
        "type": "string",
        "description": "微信 OpenID（由微信智能体自动传递）"
      }
    },
    "required": ["openid"]
  }
}
```

### 3.5 query_coupons

```json
{
  "name": "query_coupons",
  "description": "查询用户可用的优惠券列表。包括折扣券、满减券、赠品券等。",
  "parameters": {
    "type": "object",
    "properties": {
      "openid": {
        "type": "string",
        "description": "微信 OpenID"
      },
      "store_id": {
        "type": "string",
        "description": "门店 ID（可选，只查询该门店可用券）"
      }
    },
    "required": ["openid"]
  }
}
```

### 3.6 book_table

```json
{
  "name": "book_table",
  "description": "预订桌位。用户说明人数和时间后，查询可用桌位并预订。",
  "parameters": {
    "type": "object",
    "properties": {
      "store_id": {
        "type": "string",
        "description": "门店 ID"
      },
      "time": {
        "type": "string",
        "description": "到店时间（ISO 8601 格式，如 '2026-06-01T18:30:00+08:00'）"
      },
      "guests": {
        "type": "integer",
        "description": "用餐人数"
      },
      "note": {
        "type": "string",
        "description": "备注（如: 靠窗、包厢、婴儿椅）"
      }
    },
    "required": ["store_id", "time", "guests"]
  }
}
```

---

## 四、自然语言参数映射策略

微信 AI 智能体传递的参数可能是不精确的自然语言描述。SDK 需要智能映射：

### 4.1 菜品名称模糊匹配

```
用户输入: "上次的水煮鱼"  → 查询历史订单 → 匹配最近订单中的 dish_name
用户输入: "那个辣的鱼"    → 模糊匹配菜品名含"辣"和"鱼"的菜品
用户输入: "招牌菜"       → 按销量或推荐排序，返回 top 3
```

### 4.2 时间解析

```
用户输入: "今晚6点半"    → 解析为当前日期的 18:30
用户输入: "明天中午"     → 解析为明日 12:00
用户输入: "周六晚上"     → 解析为最近周六的 19:00
```

### 4.3 数量推断

```
用户输入: "来两份"       → quantity=2
用户输入: "再来一个"     → quantity=1（追加）
用户输入: "三碗米饭"     → quantity=3
```

### 4.4 规格解析

```
用户输入: "大份酸菜鱼"   → dish_name="酸菜鱼", spec="大份"
用户输入: "微辣的"       → 解析辣度等级（微辣/中辣/特辣）
```

---

## 五、SDK 接口设计

```python
class WechatAIAgentSDK:
    """微信 AI 智能体 SDK

    职责：
    1. 提供 6 个 Function Calling 函数的实现
    2. 每个函数附带 OpenAPI Schema 定义
    3. 处理自然语言参数映射
    4. Mock 模式（无配置时返回示例数据）
    """

    # ── 函数定义（OpenAI Function Calling Schema）──
    FUNCTIONS: list[dict] = [...]

    # ── 函数实现 ──
    async def query_menu(self, store_id, dish_name=None, category=None) -> dict: ...
    async def create_order(self, store_id, dishes, preference=None) -> dict: ...
    async def query_order(self, order_id) -> dict: ...
    async def query_member(self, openid) -> dict: ...
    async def query_coupons(self, openid, store_id=None) -> dict: ...
    async def book_table(self, store_id, time, guests, note=None) -> dict: ...
```

---

## 六、小程序侧适配

在 `miniapp-customer-v2` 中新增 `src/api/ai-agent.ts`，提供语义参数 API：

- 对现有 API（trade.ts/menu.ts/member.ts/growth.ts）进行包装
- 支持自然语言参数→精确参数的映射
- 不修改现有 API 的调用方式

### 包装关系

| AI Agent 函数 | 底层调用 |
|---------------|---------|
| `query_menu` | `menu.getDishes()` + `menu.searchDishes()` |
| `create_order` | `trade.createOrder()` |
| `query_order` | `trade.getOrder()` |
| `query_member` | `member.getMemberProfile()` |
| `query_coupons` | `growth.listCoupons()` |
| `book_table` | `trade request`（通过 Gateway 转发到 tx-trade） |

---

## 七、对接流程

### 微信 AI 智能体调用时序

```
微信客户端                         屯象 Gateway
    │                                    │
    │  1. 用户对话 "帮我点餐"              │
    │─────────────────────────────────→   │
    │  2. GET /v1/agent/functions         │  ← 获取 Function 列表
    │←─────────────────────────────────   │
    │  3. POST /v1/agent/execute          │
    │     {function: "query_menu", args}  │
    │─────────────────────────────────→   │
    │  4. SDK 路由到对应服务               │
    │     (无需等待，流式返回)              │
    │←─────────────────────────────────   │
    │  5. 结果返回给用户对话               │
```

### 对接注意事项

1. **认证**：微信 AI 智能体通过 `X-Wechat-Agent-Token` header 鉴权
2. **流式响应**：查询类同步返回，订单类通过 Webhook 异步通知
3. **错误处理**：Function 返回统一错误结构 `{ok: false, error: {code, message}}`
4. **限流**：每用户每分钟 30 次 Function Calling（微信侧限制）

---

## 八、验收标准

| 检查点 | 标准 | 验证方式 |
|--------|------|---------|
| 全部 6 个 Function 定义 | 符合 OpenAI Function Calling Schema | Schema 校验通过 |
| 语义参数映射 | 自然语言→准确参数映射准确率 > 85% | 测试用例覆盖 |
| 菜名模糊匹配 | "上次的水煮鱼" 能匹配到近期订单 | 集成测试 |
| Mock 模式 | 无配置时返回合理示例数据 | 单元测试 |
| 新 API 文件 | miniapp `ai-agent.ts` 包含 6 个函数定义 | 代码审查 |
| 文档 | 设计文档 + 6 个 Function 的 OpenAPI 描述 | 文档审查 |

---

## 九、与 WA-2 的边界

| WA-1（当前） | WA-2（Phase 3） |
|-------------|-----------------|
| Function Schema 定义 | Function Calling 正式对接 |
| SDK 实现（Gateway 侧） | 微信 AI 智能体完整回调路由 |
| 语义参数 API（小程序侧） | 对话式点餐全流程 |
| 自然语言映射策略 | 历史订单上下文理解 |
| Mock 模式开发 | 真实微信 API 对接 |
