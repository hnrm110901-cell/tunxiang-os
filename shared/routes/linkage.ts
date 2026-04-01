/**
 * 页面联动规则 — 跨应用域导航和 Agent 抽屉联动
 *
 * 这些规则定义了"像原生 AI 操作系统"的关键交互：
 * 从一个页面点击某个元素，自动跳转到关联页面并执行附加动作。
 */
import type { LinkageRule } from './types';

export const LINKAGE_RULES: LinkageRule[] = [
  // ── 1. 预警卡片联动 ──
  {
    id: 'alert-to-store-status',
    description: '预警中心点击某门店异常，跳转到门店营业状态页并打开Agent分析抽屉',
    from: '/hub/alerts',
    to: '/hub/stores/:storeId/status',
    action: 'navigate',
    params: ['storeId'],
  },
  {
    id: 'alert-to-store-explanation',
    description: '预警中心点击"查看原因"，跳转到差异解释页',
    from: '/hub/alerts',
    to: '/store/manager/explanations',
    action: 'navigate',
    params: ['storeId', 'alertId'],
  },
  {
    id: 'alert-open-agent-drawer',
    description: '进入门店状态页时自动打开Agent分析抽屉',
    from: '/hub/stores/:storeId/status',
    to: '/hub/stores/:storeId/status',
    action: 'open_drawer',
    params: ['storeId'],
  },

  // ── 2. 预订到桌台联动 ──
  {
    id: 'reservation-to-tables',
    description: '预订详情点击"分配桌位"，跳转到桌态总览并高亮推荐桌位',
    from: '/front/reservations/:reservationId',
    to: '/front/tables',
    action: 'highlight',
    params: ['reservationId', 'suggestedTableId', 'partySize'],
  },
  {
    id: 'reservation-agent-card',
    description: '预订页打开"预订Agent建议卡"',
    from: '/front/reservations/:reservationId',
    to: '/front/agent/reservation',
    action: 'open_drawer',
    params: ['reservationId'],
  },

  // ── 3. 等位到入座联动 ──
  {
    id: 'waitlist-to-seat',
    description: '叫号后跳转到桌台页，自动带入队列用户信息，一键入座开台',
    from: '/front/waitlist/:queueId',
    to: '/front/tables/:tableId',
    action: 'prefill',
    params: ['queueId', 'tableId', 'customerPhone', 'partySize'],
  },

  // ── 4. 报表到整改联动 ──
  {
    id: 'weekly-to-rectification',
    description: '周复盘点击异常门店，跳转到整改详情并自动生成整改任务草稿',
    from: '/hub/reports/weekly',
    to: '/hub/rectifications/:id',
    action: 'prefill',
    params: ['storeId', 'weekNumber', 'anomalyType'],
  },
  {
    id: 'report-generate-task',
    description: '报表页一键生成整改任务',
    from: '/hub/reports/weekly',
    to: '/hub/tasks',
    action: 'prefill',
    params: ['storeId', 'anomalyDescription'],
  },

  // ── 5. Agent到审批联动 ──
  {
    id: 'workflow-to-hub-approval',
    description: 'Agent工作流触发高风险动作时，跳转到总部审批页',
    from: '/agent/workflows/:workflowId/debug',
    to: '/hub/approvals',
    action: 'navigate',
    params: ['workflowId', 'actionType', 'riskLevel'],
  },
  {
    id: 'workflow-to-store-approval',
    description: 'Agent工作流触发门店级审批时，跳转到门店审批待办',
    from: '/agent/workflows/:workflowId/debug',
    to: '/store/messages/approvals',
    action: 'navigate',
    params: ['workflowId', 'storeId'],
  },

  // ── 6. 会员到触达联动 ──
  {
    id: 'segment-to-reach',
    description: '人群详情页点击"触达"，跳转到触达编排并预填人群',
    from: '/growth/segments/:segmentId',
    to: '/growth/reach/assistant',
    action: 'prefill',
    params: ['segmentId', 'segmentName', 'memberCount'],
  },

  // ── 7. 厨房到催菜联动 ──
  {
    id: 'kitchen-timeout-to-fire',
    description: '厨房超时预警点击催菜，跳转到催菜/起菜页',
    from: '/store/kitchen/exceptions',
    to: '/store/service/fire-followup',
    action: 'navigate',
    params: ['ticketId', 'orderId', 'tableId'],
  },

  // ── 8. 日结到交班联动 ──
  {
    id: 'dayclose-to-rectification',
    description: '日清日结发现差异后一键生成整改任务',
    from: '/store/manager/day-close',
    to: '/store/manager/rectifications',
    action: 'prefill',
    params: ['storeId', 'date', 'anomalyItems'],
  },
];
