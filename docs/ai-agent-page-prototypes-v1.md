# 屯象OS 原生 AI Agent 关键页面原型结构图 + 页面交互说明 V1

> 本文档定义 10 个关键页面的骨架布局、区域组件、状态流转和联动关系。
> 可直接用于 Figma 低保真 / 前端页面骨架 / PRD 交互说明。

---

## 一、V1 页面设计总原则

每个关键页面同时满足：
1. **看业务现状** — 主内容区
2. **看 AI 建议** — Agent 抽屉区
3. **做关键动作** — 动作区
4. **看动作结果** — 反馈层

## 二、统一 5 区布局

1. **顶部 App Shell** — 全局搜索 + 品牌/门店切换 + 日期 + 消息 + Agent 入口 + 用户
2. **左侧导航区** — 应用域导航 + 子导航
3. **主内容区** — 业务核心
4. **右侧 Agent 抽屉** — 上下文 + 建议 + 动作 + 记录（4 Tab）
5. **底部反馈层** — Toast + 审批结果 + 同步状态

## 三、10 个关键页面

### 总部侧
1. `/hub/dashboard/group` 集团经营驾驶舱
2. `/hub/alerts` 预警中心
3. `/hub/agent/orchestrator` 总控 Agent 工作台
4. `/hub/reports/weekly` 周经营复盘

### 前厅侧
5. `/front/workbench` 前厅工作台
6. `/front/reservations` 预订台账
7. `/front/waitlist` 等位队列
8. `/front/tables` 桌态总览

### 门店侧
9. `/store/workbench` 店长当班工作台
10. `/store/manager/day-close` 日清日结

## 四、12 个关键组件

1. KPIStatCard — 指标卡片
2. AlertListTable — 预警列表
3. AgentSuggestionPanel — Agent 建议面板
4. TaskExecutionTimeline — 任务执行时间线
5. StoreHeatmapBoard — 门店热力图
6. ReservationCalendarList — 预订日历/列表
7. WaitlistQueuePanel — 等位队列面板
8. TableCanvasBoard — 桌态画布
9. ShiftSummaryPanel — 班次总结
10. CloseDayStepper — 日结步骤器
11. ExceptionReasonDrawer — 异常原因抽屉
12. ApprovalConfirmDialog — 审批确认弹窗

## 五、统一交互机制

### Agent 抽屉 4 Tab
- 建议 — 当前上下文推荐动作
- 解释 — 为什么给出建议
- 动作 — 可触发按钮（生成任务/发消息/发券/标记风险）
- 记录 — Agent 调用工具和结果日志

### 页面状态
- Loading / Empty / Error / Partial Success / Permission Denied / Offline
