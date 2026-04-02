# 屯象OS 原生 AI Agent 6个P0关键页面低保真线框说明 + 字段明细 V1

> 6 个 P0 页面覆盖完整闭环：总部发现问题 → Agent 分析编排 → 前厅执行协同 → 门店闭店复盘
> 详见 `shared/api-types/p0-pages.ts` 中的完整 TypeScript 字段定义

## P0 页面清单

| # | 页面 | 路由 | 职责 |
|---|------|------|------|
| 1 | 总控Agent工作台 | /hub/agent/orchestrator | 任务编排与执行中枢 |
| 2 | 预警中心 | /hub/alerts | 总部发现问题主入口 |
| 3 | 前厅工作台 | /front/workbench | 迎宾/楼面经理主作战页 |
| 4 | 预订台账 | /front/reservations | 预订全生命周期管理 |
| 5 | 桌态总览 | /front/tables | 现场调度核心 |
| 6 | 日清日结 | /store/manager/day-close | 门店闭环页 |

## 页面联动

1. 预警中心 → 总控Agent（带入alert上下文）
2. 前厅工作台 → 预订台账（筛选待确认）
3. 前厅工作台 → 桌态总览（带入等位顾客）
4. 预订台账 → 桌态总览（高亮推荐桌位）
5. 日清日结 → 总控Agent（带入异常项生成整改）

## 统一复用组件

PageHeader, FilterBar, KpiStatCard, AgentSuggestionPanel, ExecutionTimeline,
RightDrawerDetailPanel, StatusTag, ActionBar, RiskConfirmDialog, OfflineSyncBanner

## 开发顺序

第一组（看见+理解）：预警中心 → 总控Agent
第二组（前厅执行）：前厅工作台 → 预订台账 → 桌态总览
第三组（闭环）：日清日结
