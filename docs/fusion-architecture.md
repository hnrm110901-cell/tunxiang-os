# 屯象OS 融合架构规范 — Toast × Palantir × R365

> 前端借鉴 Toast POS，后端借鉴 Wendy's × Palantir Foundry 和 Restaurant365
> 三者精华融合为屯象OS统一架构

---

## 一、融合映射总览

```
┌─────────────────────────────────────────────────────────────┐
│                     屯象OS 融合架构                          │
├─────────────┬──────────────────┬────────────────────────────┤
│  Toast POS  │  Palantir AIP    │  Restaurant365              │
│  (前端体验)  │  (决策智能骨架)   │  (后台运营引擎)             │
├─────────────┼──────────────────┼────────────────────────────┤
│ Open View   │ Ontology Objects │ GL Accounting Backbone     │
│ Color-coded │ Actions          │ Inventory ↔ Accounting     │
│  Menu Grid  │ Functions        │  Auto Journal Entries      │
│ Quick Edit  │ Agent Studio     │ AI Scheduling              │
│ KDS Grid    │ Workflow Lineage │ Multi-Location Control     │
│ Bump Bar    │ AIP Logic        │ POS Data Auto-Pull         │
│ Modifier    │ Digital Twin     │ Vendor/Contract Pricing    │
│  Panel      │ Observability    │ Mobile Inventory Count     │
└─────────────┴──────────────────┴────────────────────────────┘
```

---

## 二、前端层 — 借鉴 Toast POS

### 2.1 POS 点餐界面（Toast Open View 融合）

Toast 的核心创新是 **Open View**：将菜单扁平展开为色块网格，所有修改器（做法/口味/加料）
同时可见，服务员可以按对话自然顺序录入，而非强制按菜单层级导航。

**屯象OS 融合方案：**

```
┌─────────────────────────────────────────────────────────────┐
│ [Agent预警条 — Palantir决策推送]                              │
├──────┬────────────────────────────────┬─────────────────────┤
│      │  Toast-style Color Grid        │                     │
│ 分类  │  ┌─────┐ ┌─────┐ ┌─────┐     │    购物车 + 修改器   │
│ 导航  │  │ 🔴  │ │ 🟠  │ │ 🟡  │     │    ┌─────────────┐ │
│      │  │剁椒鱼│ │小炒肉│ │土鸡汤│     │    │ 订单明细     │ │
│ 招牌● │  │ ¥128│ │ ¥68 │ │ ¥88 │     │    │ 1×剁椒鱼头  │ │
│ 湘菜● │  └─────┘ └─────┘ └─────┘     │    │  口味: 微辣  │ │
│ 凉菜● │  ┌─────┐ ┌─────┐ ┌─────┐     │    │  做法: 清蒸  │ │
│ 汤品● │  │ 🟢  │ │ 🔵  │ │ ⚫  │     │    ├─────────────┤ │
│ 主食● │  │口味虾│ │凉拌瓜│ │米饭 │     │    │[修改器面板]  │ │
│ 饮品● │  │¥128 │ │ ¥18 │ │ ¥3  │     │    │ 辣度 口味   │ │
│      │  └─────┘ └─────┘ └─────┘     │    │ 做法 加料   │ │
├──────┤                               │    ├─────────────┤ │
│搜索🔍│  [快捷操作栏]                   │    │合计 ¥128    │ │
│语音🎤│  [常点] [套餐] [时令]           │    │[结算] [挂单]│ │
└──────┴────────────────────────────────┴─────────────────────┘
```

**关键设计决策：**

| Toast 特性 | 屯象OS 实现 | 为什么 |
|-----------|------------|--------|
| Open View 扁平展开 | 色块网格 + 分类侧栏 | 中餐菜品多(100+)，需要分类辅助 |
| Color-coded 按钮 | 按分类自动着色 | 一眼区分招牌菜/凉菜/饮品 |
| Modifier 同屏显示 | 右侧面板实时展开 | 中餐做法复杂（辣度/口味/加料） |
| Quick Edit 长按编辑 | 长按菜品弹出做法面板 | 触控场景快速定制 |
| Favorites 快捷区 | 顶部"常点/套餐/时令"标签 | 高频菜品一键到达 |
| Guest-facing display | iPad可选升级双屏 | 高端店顾客确认 |

### 2.2 KDS 出餐屏（Toast KDS 融合）

Toast KDS 的核心：**Grid View + Expediter 双层工作流 + Bump Bar**

```
┌─────────────────────────────────────────────────────────────┐
│ [Agent预警: 出餐调度Agent — A3桌VIP即将超时]                  │
├────────────────────┬────────────────────────────────────────┤
│ 📊 统计栏           │                                        │
│ 待出: 12 | 超时: 2  │  Toast-style Grid View                │
│ 均时: 18min        │  ┌────────┐ ┌────────┐ ┌────────┐    │
│                    │  │🔴 A3 VIP│ │🟡 B5   │ │🟢 C2   │    │
│ 档口筛选            │  │ 15:22  │ │ 08:45  │ │ 03:11  │    │
│ ● 全部             │  │■鱼头 ×1│ │■虾 ×2  │ │■鱼 ×1  │    │
│ ○ 热菜档           │  │■清蒸鱼×1│ │■青菜×1 │ │■汤 ×1  │    │
│ ○ 凉菜档           │  │■汤 ×2  │ │        │ │        │    │
│ ○ 面点档           │  │[超时!]  │ │[即将]  │ │[正常]  │    │
│                    │  │←滑动完成│ │←滑动   │ │←滑动   │    │
│ 已完成 ✅           │  └────────┘ └────────┘ └────────┘    │
│ 查看最近完成 →      │                                        │
│                    │  ┌────────┐ ┌────────┐ ┌────────┐    │
│                    │  │🟢 D1   │ │🟢 E3   │ │🟢 F2   │    │
│                    │  │ 01:30  │ │ 02:15  │ │ 00:45  │    │
│                    │  │■凉菜×3 │ │■小炒×1 │ │■饮品×2 │    │
│                    │  └────────┘ └────────┘ └────────┘    │
└────────────────────┴────────────────────────────────────────┘

颜色编码（借鉴Toast ticket aging）:
  🟢 绿色 = 正常（剩余时间 > 50%）
  🟡 黄色 = 注意（剩余时间 ≤ 50%）
  🔴 红色 = 超时（已超过时限）+ 脉冲动画
  ⭐ 金色边框 = VIP 桌
```

**Toast KDS → 屯象OS 融合要点：**
- Grid View + 动态调整卡片尺寸（Toast "Change ticket size"）
- Bump Bar 支持（通过安卓 USB HID 设备桥接）
- Expediter 工作流：档口完成 → 传菜台汇总 → 出餐
- 最近完成的工单可回看（Toast "Show recently fulfilled"）
- 声音提醒：新单/超时/催菜（Toast auditory settings）

---

## 三、后端层 — 借鉴 Palantir Foundry

### 3.1 Ontology 驱动架构

Palantir 的核心是 **Ontology**：将现实世界映射为 Objects → Properties → Links → Actions。
屯象OS 的 L1 Ontology 层完全对标这个思路。

```
Palantir 概念          →  屯象OS 实现
─────────────────────────────────────────────
Object Types           →  六大实体类 (Customer/Dish/Store/Order/Ingredient/Employee)
Properties             →  实体字段 (priceFen, marginRate, isAvailable...)
Links                  →  实体关联 (Order.items → Dish, Store.employees → Employee)
Actions                →  业务操作 (createOrder, applyDiscount, transferStock...)
Functions              →  业务逻辑 (calcMarginRate, predictDemand, checkFoodSafety...)
Agent Studio           →  tx-agent 9大Skill Agent + Master Agent
Workflow Lineage       →  Agent决策留痕 (AgentDecisionLog)
Digital Twin           →  Mac mini 本地PG副本 = 门店数字孪生
AIP Observability      →  Agent监控面板 (AgentMonitorPage)
```

### 3.2 Ontology 核心实现

```python
# Palantir-style: 每个 Object Type 有明确的 Properties + Links + Actions
class OntologyObjectType:
    name: str              # "Dish"
    properties: dict       # {name: str, priceFen: int, marginRate: float...}
    links: dict            # {category: "DishCategory", orders: "Order[]"...}
    actions: list          # ["updatePrice", "toggleAvailability", "markSoldOut"]
    functions: list        # ["calcMarginRate", "predictDemand"]
    constraints: list      # 三条硬约束

# 关键创新：Actions 不只是 CRUD，而是包含 Agent 可执行的决策动作
class OntologyAction:
    name: str              # "applyDiscount"
    input_schema: dict     # {orderId, discountRate, reason}
    constraints_check: list  # [毛利底线检查, 授权级别检查]
    side_effects: list     # [写入决策日志, 通知折扣守护Agent]
    rollback: str          # 回滚操作名
```

### 3.3 Agent 分层（对标 Palantir Agent Tier Framework）

```
Tier 0 — 只读查询Agent
  例: "今天A3桌花了多少钱？" → 查Ontology，返回结果
  实现: Claude API + Ontology读取

Tier 1 — 建议型Agent
  例: 折扣守护检测到异常 → 推送预警到POS，人工决定
  实现: Core ML边缘推理 + WebSocket推送

Tier 2 — 半自动Agent
  例: 库存Agent检测到食材即将过期 → 自动生成处理建议 + 等审批
  实现: Agent生成Action → 等Store/Admin确认 → 执行

Tier 3 — 全自动Agent（需授权）
  例: 出餐调度Agent自动调整档口优先级
  实现: Agent直接执行Action → 写决策日志 → 人可回滚
```

---

## 四、运营后台层 — 借鉴 Restaurant365

### 4.1 R365 核心模式：会计骨架 + 运营模块融合

R365 的革命性设计：**库存变动自动生成会计分录**。
传统餐饮：库存系统和财务系统分离，月底对账。
R365 模式：每次进货/盘点/报损，实时生成 Journal Entry。

**屯象OS 融合实现：**

```
┌──────────────────────────────────────────────────────┐
│                R365-style 运营后台                     │
├──────────────┬───────────────────────────────────────┤
│              │                                       │
│  会计骨架     │  业务模块（自动写入GL）                │
│  (tx-finance) │                                       │
│              │  ┌─────────┐  ┌──────────┐            │
│  总账 GL     │  │ 库存管理 │──│自动分录   │            │
│  科目表 COA  │  │tx-supply │  │进货→借:库存│           │
│  日记账 JE   │  │         │  │    贷:应付 │           │
│  应收 AR     │  └─────────┘  └──────────┘            │
│  应付 AP     │                                       │
│  银行对账    │  ┌─────────┐  ┌──────────┐            │
│  损益表 P&L  │  │ 销售数据 │──│自动分录   │            │
│              │  │ POS拉取  │  │收入→借:现金│           │
│              │  │tx-trade  │  │    贷:营收 │           │
│              │  └─────────┘  └──────────┘            │
│              │                                       │
│              │  ┌─────────┐  ┌──────────┐            │
│              │  │ 人力排班 │──│自动分录   │            │
│              │  │ tx-org   │  │工资→借:人工│           │
│              │  │AI排班    │  │    贷:应付 │           │
│              │  └─────────┘  └──────────┘            │
└──────────────┴───────────────────────────────────────┘
```

### 4.2 库存 ↔ 会计集成

```
R365特性                    →  屯象OS tx-supply + tx-finance 实现
───────────────────────────────────────────────────────────────
Invoice auto-import        →  供应商发票OCR识别 → 自动创建AP凭证
Food costing tied to GL    →  菜品BOM成本实时计算 → 毛利率更新
Mobile inventory count     →  员工手机PWA盘点 → 差异自动生成调整分录
Contract pricing alerts    →  合同价/目标价偏差 → Agent预警
Waste tracking             →  报损录入 → 自动借:损耗 贷:库存
Transfer between stores    →  门店调拨 → 双方库存+会计同步
```

### 4.3 AI 排班（R365 AI Scheduling 融合）

R365 的 AI 排班基于销售模式和季节调整。屯象OS 融合边缘 AI：

```
数据输入:
  - 历史销售数据（按时段/星期/节假日）
  - 天气预报（Core ML 边缘获取）
  - 预订数据（ReservationPage）
  - 员工技能标签（Employee Ontology）

AI排班输出:
  - 各档口各时段人员配置
  - 预估人力成本 vs 预估营收 → 人效比
  - 加班预警 + 合规检查

执行方式:
  - 边缘: Core ML 快速预测客流
  - 云端: Claude API 生成最优排班方案
  - 人工: 店长在 Crew PWA 确认/微调
```

---

## 五、三源融合的独特优势

```
单独用 Toast:     只有好用的POS前端，后端管理弱
单独用 Palantir:  太通用，不懂餐饮业务语义
单独用 R365:      后端强但前端弱，无AI能力

屯象OS 融合后:
  Toast前端体验 × Palantir决策智能 × R365运营深度
  = 中餐连锁的全栈智能操作系统
```

| 维度 | Toast | Palantir | R365 | 屯象OS融合 |
|------|-------|----------|------|-----------|
| POS点餐 | ★★★★★ | — | — | ★★★★★ Toast Open View |
| KDS出餐 | ★★★★ | — | — | ★★★★★ + Agent调度 |
| AI决策 | ★★ | ★★★★★ | ★★ | ★★★★★ Ontology+Agent |
| 库存管理 | ★★ | ★★★ | ★★★★★ | ★★★★★ R365模式 |
| 会计集成 | — | — | ★★★★★ | ★★★★ 自动分录 |
| 供应链 | — | ★★★★ | ★★★★ | ★★★★★ Palantir数字孪生 |
| 边缘AI | — | — | — | ★★★★★ Mac mini独创 |
| 多品牌隔离 | ★★★ | ★★★★★ | ★★★ | ★★★★★ RLS+Ontology |
