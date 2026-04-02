# 屯象OS 6个P0关键页面 React 组件拆分清单 + Props 字段定义 V1

> 本文档定义每个 P0 页面的组件树结构、Props 接口和状态管理策略。
> 可直接用于前端开发分工和 Code Review 检查。

---

## 一、共享组件清单（跨页面复用）

### 布局组件

| 组件 | 路径 | Props | 说明 |
|------|------|-------|------|
| `ShellHQ` | shell/ShellHQ.tsx | `{ children, onLogout }` | 四栏主布局（已有） |
| `AgentDrawer` | components/agent/AgentDrawer.tsx | `{ suggestions, explanations, actions, logs, contextSummary, loading }` | V1 四Tab Agent抽屉 |

### 业务组件

| 组件 | 路径 | Props 关键字段 | 说明 |
|------|------|---------------|------|
| `KPIStatCard` | components/agent/ | `{ title, value, format, changeRate, target, isAnomaly, onClick }` | 指标卡片 |
| `AlertListTable` | components/agent/ | `{ request, onViewDetail, onAssign, onCreateTask, onIgnore }` | 预警ProTable |
| `TaskExecutionTimeline` | components/agent/ | `{ steps: ExecutionStep[], currentStep }` | Agent任务步骤流 |
| `ShiftSummaryPanel` | components/agent/ | `{ shiftName, summary, metrics, anomalies, improvements }` | 班次复盘面板 |
| `CloseDayStepper` | components/agent/ | `{ steps: CloseStep[], currentStep, onStepClick }` | 日结7步导航 |
| `ApprovalConfirmDialog` | components/agent/ | `{ open, title, riskLevel, agentName, impactItems, onApprove, onReject }` | 审批弹窗 |
| `StatusTag` | components/agent/ | `{ status, label? }` | 自动颜色状态标签 |
| `FilterBar` | components/agent/ | `{ fields: FilterField[], values, onChange, onReset }` | 声明式筛选栏 |
| `OfflineSyncBanner` | components/agent/ | `{ status: SyncStatus, lastSyncTime?, onRetry? }` | 离线横幅 |

---

## 二、页面组件拆分

### 1. 总控Agent工作台 (`OrchestratorPage`)

```
OrchestratorPage
├── PageHeader (标题 + 副标题)
├── Row[16:8]
│   ├── Col[16] — 中央任务区
│   │   ├── TaskInputCard
│   │   │   ├── TextArea (任务输入)
│   │   │   ├── TemplateButtonGroup (模板快捷按钮)
│   │   │   └── SubmitButton
│   │   └── TaskExecutionCard
│   │       ├── TaskExecutionTimeline (步骤流)
│   │       ├── ResultSummaryCard (一句话结论)
│   │       └── ResultItemList (重点门店列表)
│   └── Col[8] — 右侧执行区
│       ├── ContextCard (品牌/区域/日期/角色)
│       ├── QuickActionCard (生成任务/发消息/查历史)
│       └── ToolCallLogCard (调用记录)
└── ApprovalConfirmDialog (审批弹窗)
```

**状态管理** (Zustand store):
```ts
interface OrchestratorStore {
  taskInput: string;
  pageState: 'empty' | 'planning' | 'running' | 'done' | 'error';
  steps: OrchestratorStep[];
  currentStep: number;
  result: OrchestratorResult | null;
  toolCalls: ToolCallRecord[];
  submitTask: (input: OrchestratorTaskInput) => Promise<void>;
  approveStep: (stepId: string, remark: string) => Promise<void>;
}
```

### 2. 预警中心 (`AlertsCenterPage`)

```
AlertsCenterPage
├── Row[15:9] (detailOpen) 或 Row[24] (closed)
│   ├── Col — 主列表
│   │   ├── ProTable (AlertListTable columns)
│   │   │   ├── SearchForm (严重级/类型/状态/门店)
│   │   │   ├── BatchActionBar (指派/建任务/忽略)
│   │   │   └── ToolBar (Agent处置按钮)
│   │   └── Pagination
│   └── Col — 右侧详情 (条件渲染)
│       ├── AlertEventSummary
│       ├── AlertImpactScope
│       ├── AgentRootCauseList
│       ├── RecommendedActionList
│       ├── SimilarCaseList
│       └── ActionButtonGroup (Agent工作台/指派/建任务)
```

**状态管理**:
```ts
interface AlertsStore {
  selectedAlertId: string | null;
  detailOpen: boolean;
  alertDetail: AlertDetail | null;
  selectAlert: (id: string) => void;
  closeDetail: () => void;
}
```

### 3. 前厅工作台 (`FrontWorkbenchPage`)

```
FrontWorkbenchPage
├── KPIRow (4个 KPIStatCard / Statistic)
│   ├── 今日预订数
│   ├── 当前等位数
│   ├── 空闲桌位数
│   └── 超时桌数
├── Row[12:12]
│   ├── ReservationListCard
│   │   ├── CardTitle + 新建按钮
│   │   └── Table (时间/顾客/人数/状态/操作)
│   └── WaitlistCard
│       ├── CardTitle + 加入等位按钮
│       └── List (号牌/人数/等待时长/风险/操作)
├── TableThumbnailCard
│   ├── 图例 (空闲/预订/用餐/超时/清台)
│   └── TableGrid (色块桌卡)
└── [右侧 AgentDrawer — 由 ShellHQ 提供]
```

### 4. 预订台账 (`ReservationsPage`)

```
ReservationsPage
├── PageHeaderRow
│   ├── Title + ViewToggle (列表/日历)
│   ├── StatisticGroup (总计/待确认/已确认)
│   └── NewReservationModalForm
├── Row[15:9] (selectedId) 或 Row[24]
│   ├── Col — 列表
│   │   └── ProTable (预订列表)
│   │       ├── Columns (时间/顾客/VIP/人数/标签/状态/来源/操作)
│   │       └── SearchForm (日期/时段/状态/桌型/来源)
│   └── Col — 详情 (条件渲染)
│       ├── CustomerInfoDescriptions
│       ├── DietaryAlertBanner
│       ├── RecommendedTableList
│       ├── ConflictCheckAlert
│       ├── ContactRecordTimeline
│       └── ActionButtonGroup (确认/入座/改约/联系/取消)
```

### 5. 桌态总览 (`TableBoardPage`)

```
TableBoardPage
├── FilterToolbar
│   ├── ZoneSelect
│   ├── StatusSelect
│   ├── SearchInput
│   └── StatisticGroup (空闲/用餐/预订)
├── Row[16:8] (drawerOpen) 或 Row[24]
│   ├── Col — 画布
│   │   ├── TableCanvas
│   │   │   └── ZoneGroup[] (按桌区分组)
│   │   │       └── TableCard[] (色块 + 桌号 + 人数 + 时长 + VIP)
│   │   └── EventTimeline (底部事件栏)
│   └── Col — 详情抽屉 (条件渲染)
│       ├── TableInfoDescriptions
│       └── ActionButtonGroup (入座/改桌/并台/拆台/催菜)
```

**TableCard 状态映射**:
```
idle     → #0F6E56 (success绿)
reserved → #185FA5 (info蓝)
dining   → #FF6B35 (primary橙)
overtime → #A32D2D (danger红 + pulse动画)
cleaning → #B4B2A9 (灰)
```

### 6. 日清日结 (`DayClosePage`)

```
DayClosePage
├── ProgressHeader
│   ├── 营业日 / 进度条 / 待核对数 / 异常数
│   └── LockBadge (已锁账)
├── Row[5:12:7]
│   ├── Col[5] — 步骤区
│   │   └── CloseDayStepper (7步)
│   ├── Col[12] — 核对区 (根据 currentStep 切换)
│   │   ├── RevenueCheckPanel (step 0)
│   │   │   ├── ComparisonTable (系统值/人工值/差异)
│   │   │   ├── DifferenceAlert
│   │   │   └── RemarkTextArea
│   │   ├── PaymentCheckPanel (step 1)
│   │   ├── RefundCheckPanel (step 2)
│   │   │   ├── AnomalyAlert
│   │   │   └── RefundDetailTable
│   │   ├── InvoiceCheckPanel (step 3)
│   │   ├── InventoryCheckPanel (step 4)
│   │   ├── HandoverCheckPanel (step 5)
│   │   └── SignoffPanel (step 6)
│   │       └── SignoffResult (检查必填/差异/风险)
│   └── Col[7] — Agent解释区
│       ├── ShiftSummaryPanel
│       └── QuickActionCard (生成整改/推送/导出)
```

---

## 三、跨页面联动实现方式

| 联动 | 实现方式 |
|------|---------|
| 预警中心 → Agent工作台 | `navigate('/hub/agent/orchestrator', { state: AlertToOrchestratorParams })` |
| 前厅工作台 → 预订台账 | `navigate('/front/reservations?status=pending_confirm')` |
| 前厅工作台 → 桌态总览 | `navigate('/front/tables', { state: ToTableBoardParams })` |
| 预订台账 → 桌态总览 | `navigate('/front/tables', { state: { highlight_table_id, reservation_id } })` |
| 日清日结 → Agent工作台 | `navigate('/hub/agent/orchestrator', { state: DayCloseToOrchestratorParams })` |

联动参数类型定义在 `shared/api-types/p0-pages.ts` 中。

---

## 四、Zustand Store 拆分建议

| Store | 文件 | 服务页面 |
|-------|------|---------|
| `useOrchestratorStore` | stores/orchestratorStore.ts | Agent工作台 |
| `useAlertsStore` | stores/alertsStore.ts | 预警中心 |
| `useFrontStore` | stores/frontStore.ts | 前厅工作台 |
| `useReservationStore` | stores/reservationStore.ts | 预订台账 |
| `useTableStore` | stores/tableStore.ts | 桌态总览 |
| `useDayCloseStore` | stores/dayCloseStore.ts | 日清日结 |
| `useAgentDrawerStore` | stores/agentDrawerStore.ts | 所有页面共享 |
