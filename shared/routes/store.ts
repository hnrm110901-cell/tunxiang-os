/**
 * C. Store 门店执行台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const STORE_ROUTES: RouteNode[] = [
  // ── C1 当班工作台 ──
  { path: '/store/workbench', name: '当班工作台', nameEn: 'StoreWorkbench', moduleId: 'C1', priority: true, aiEntry: ['task_input', 'alert_card'] },
  { path: '/store/briefing',  name: '班前简报',   nameEn: 'Briefing',       moduleId: 'C1', aiEntry: ['review'] },
  { path: '/store/tasks',     name: '今日任务',   nameEn: 'DailyTasks',     moduleId: 'C1', aiEntry: ['suggestion'] },
  { path: '/store/incidents', name: '异常中心',   nameEn: 'Incidents',      moduleId: 'C1', aiEntry: ['alert_card'] },

  // ── C2 点单与服务 ──
  { path: '/store/service/open-table',            name: '开台',       nameEn: 'OpenTable',     moduleId: 'C2' },
  { path: '/store/service/orders',                name: '点单列表',   nameEn: 'OrderList',     moduleId: 'C2' },
  { path: '/store/service/orders/:orderId',       name: '订单详情',   nameEn: 'OrderDetail',   moduleId: 'C2', hideInNav: true },
  { path: '/store/service/orders/:orderId/edit',  name: '加退菜',     nameEn: 'EditOrder',     moduleId: 'C2', hideInNav: true },
  { path: '/store/service/service-log',           name: '服务记录',   nameEn: 'ServiceLog',    moduleId: 'C2' },
  { path: '/store/service/fire-followup',         name: '催菜/起菜',  nameEn: 'FireFollowup',  moduleId: 'C2', aiEntry: ['suggestion'] },

  // ── C3 收银与结账 ──
  { path: '/store/cashier',                       name: '收银台',     nameEn: 'Cashier',        moduleId: 'C3', priority: true },
  { path: '/store/cashier/orders',                name: '待结订单',   nameEn: 'PendingOrders',  moduleId: 'C3' },
  { path: '/store/cashier/orders/:orderId',       name: '结账详情',   nameEn: 'CheckoutDetail', moduleId: 'C3', hideInNav: true },
  { path: '/store/cashier/merge-split',           name: '合单拆单',   nameEn: 'MergeSplit',     moduleId: 'C3' },
  { path: '/store/cashier/payments/:paymentId',   name: '支付详情',   nameEn: 'PaymentDetail',  moduleId: 'C3', hideInNav: true },
  { path: '/store/cashier/refunds/:refundId',     name: '退款',       nameEn: 'Refund',         moduleId: 'C3', hideInNav: true },
  { path: '/store/cashier/invoices',              name: '发票记录',   nameEn: 'Invoices',       moduleId: 'C3' },

  // ── C4 厨房协同 ──
  { path: '/store/kitchen',                       name: 'KDS总览',    nameEn: 'KDSOverview',    moduleId: 'C4' },
  { path: '/store/kitchen/stations',              name: '工位队列',   nameEn: 'StationQueue',   moduleId: 'C4', aiEntry: ['alert_card'] },
  { path: '/store/kitchen/stations/:stationId',   name: '工位详情',   nameEn: 'StationDetail',  moduleId: 'C4', hideInNav: true },
  { path: '/store/kitchen/orders/:ticketId',      name: '出品详情',   nameEn: 'TicketDetail',   moduleId: 'C4', hideInNav: true },
  { path: '/store/kitchen/exceptions',            name: '异常挂起',   nameEn: 'KitchenExcept',  moduleId: 'C4', aiEntry: ['alert_card'] },
  { path: '/store/kitchen/stockout',              name: '缺货/停售',  nameEn: 'Stockout',       moduleId: 'C4', aiEntry: ['alert_card'] },

  // ── C5 店长运营 ──
  { path: '/store/manager/lunch-review',   name: '午市复盘',   nameEn: 'LunchReview',    moduleId: 'C5', aiEntry: ['review'] },
  { path: '/store/manager/dinner-review',  name: '晚市复盘',   nameEn: 'DinnerReview',   moduleId: 'C5', aiEntry: ['review'] },
  { path: '/store/manager/day-close',      name: '日清日结',   nameEn: 'DayClose',       moduleId: 'C5', priority: true, aiEntry: ['suggestion', 'review'] },
  { path: '/store/manager/explanations',   name: '差异解释',   nameEn: 'Explanations',   moduleId: 'C5', aiEntry: ['task_input'] },
  { path: '/store/manager/rectifications', name: '整改任务',   nameEn: 'Rectifications', moduleId: 'C5', aiEntry: ['suggestion'] },

  // ── C6 门店消息中心 ──
  { path: '/store/messages',                    name: '消息中心',    nameEn: 'MessageCenter', moduleId: 'C6' },
  { path: '/store/messages/approvals',          name: '审批待办',    nameEn: 'Approvals',     moduleId: 'C6' },
  { path: '/store/messages/agent-suggestions',  name: 'Agent建议',   nameEn: 'AgentSuggestions', moduleId: 'C6', aiEntry: ['suggestion'] },
];

export const STORE_NAV: NavItem[] = [
  { key: 'shift', label: '当班', icon: 'clock-circle', children: [
    { key: 'workbench', label: '工作台',   path: '/store/workbench' },
    { key: 'briefing',  label: '班前简报', path: '/store/briefing' },
    { key: 'tasks',     label: '今日任务', path: '/store/tasks' },
    { key: 'incidents', label: '异常中心', path: '/store/incidents' },
  ]},
  { key: 'service', label: '服务', icon: 'coffee', children: [
    { key: 'open',    label: '开台',     path: '/store/service/open-table' },
    { key: 'orders',  label: '点单列表', path: '/store/service/orders' },
    { key: 'log',     label: '服务记录', path: '/store/service/service-log' },
    { key: 'fire',    label: '催菜/起菜', path: '/store/service/fire-followup' },
  ]},
  { key: 'cashier', label: '收银', icon: 'dollar', children: [
    { key: 'main',       label: '收银台',   path: '/store/cashier' },
    { key: 'pending',    label: '待结订单', path: '/store/cashier/orders' },
    { key: 'merge',      label: '合单拆单', path: '/store/cashier/merge-split' },
    { key: 'invoices',   label: '发票记录', path: '/store/cashier/invoices' },
  ]},
  { key: 'kitchen', label: '厨房', icon: 'fire', children: [
    { key: 'kds',       label: 'KDS总览',   path: '/store/kitchen' },
    { key: 'stations',  label: '工位队列',   path: '/store/kitchen/stations' },
    { key: 'except',    label: '异常挂起',   path: '/store/kitchen/exceptions' },
    { key: 'stockout',  label: '缺货/停售',  path: '/store/kitchen/stockout' },
  ]},
  { key: 'manager', label: '店长运营', icon: 'crown', children: [
    { key: 'lunch',  label: '午市复盘',   path: '/store/manager/lunch-review' },
    { key: 'dinner', label: '晚市复盘',   path: '/store/manager/dinner-review' },
    { key: 'close',  label: '日清日结',   path: '/store/manager/day-close' },
    { key: 'explain', label: '差异解释',  path: '/store/manager/explanations' },
    { key: 'rects',  label: '整改任务',   path: '/store/manager/rectifications' },
  ]},
  { key: 'messages', label: '消息', icon: 'bell', children: [
    { key: 'all',       label: '消息中心', path: '/store/messages' },
    { key: 'approvals', label: '审批待办', path: '/store/messages/approvals' },
    { key: 'agent',     label: 'Agent建议', path: '/store/messages/agent-suggestions' },
  ]},
];
