/**
 * A. Hub 总部经营台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const HUB_ROUTES: RouteNode[] = [
  // ── A1 经营驾驶舱 ──
  { path: '/hub/dashboard/group',  name: '集团经营总览', nameEn: 'GroupDashboard',  moduleId: 'A1', priority: true, aiEntry: ['review'] },
  { path: '/hub/dashboard/brand',  name: '品牌经营总览', nameEn: 'BrandDashboard',  moduleId: 'A1', aiEntry: ['review'] },
  { path: '/hub/dashboard/region', name: '区域经营总览', nameEn: 'RegionDashboard', moduleId: 'A1', aiEntry: ['review'] },
  { path: '/hub/dashboard/stores', name: '门店经营对比', nameEn: 'StoreCompare',    moduleId: 'A1', aiEntry: ['task_input'] },
  { path: '/hub/alerts',           name: '预警中心',     nameEn: 'AlertCenter',      moduleId: 'A1', priority: true, aiEntry: ['alert_card'] },
  { path: '/hub/qa',               name: 'AI经营问答',   nameEn: 'AiQA',             moduleId: 'A1', aiEntry: ['task_input'] },

  // ── A2 总部 Agent 决策中心 ──
  { path: '/hub/agent/orchestrator', name: '总控Agent工作台', nameEn: 'AgentOrchestrator', moduleId: 'A2', priority: true, aiEntry: ['task_input'] },
  { path: '/hub/agent/analysis',     name: '经营分析Agent',   nameEn: 'AnalysisAgent',     moduleId: 'A2', aiEntry: ['task_input'] },
  { path: '/hub/agent/alerts',       name: '预警处置Agent',   nameEn: 'AlertAgent',        moduleId: 'A2', aiEntry: ['alert_card'] },
  { path: '/hub/tasks',              name: '总部任务中心',    nameEn: 'TaskCenter',        moduleId: 'A2', aiEntry: ['suggestion'] },
  { path: '/hub/approvals',          name: '审批确认',        nameEn: 'Approvals',         moduleId: 'A2' },

  // ── A3 门店治理 ──
  { path: '/hub/stores',                   name: '门店列表',     nameEn: 'StoreList',       moduleId: 'A3' },
  { path: '/hub/stores/:storeId',          name: '门店详情',     nameEn: 'StoreDetail',     moduleId: 'A3', hideInNav: true },
  { path: '/hub/stores/:storeId/status',   name: '营业状态',     nameEn: 'StoreStatus',     moduleId: 'A3', hideInNav: true, aiEntry: ['alert_card'] },
  { path: '/hub/inspections',              name: '巡店任务',     nameEn: 'Inspections',     moduleId: 'A3', aiEntry: ['suggestion'] },
  { path: '/hub/inspections/:taskId',      name: '巡店详情',     nameEn: 'InspectionDetail', moduleId: 'A3', hideInNav: true },
  { path: '/hub/rectifications',           name: '整改闭环',     nameEn: 'Rectifications',  moduleId: 'A3', aiEntry: ['suggestion'] },
  { path: '/hub/rectifications/:id',       name: '整改详情',     nameEn: 'RectDetail',      moduleId: 'A3', hideInNav: true },
  { path: '/hub/closing-summary',          name: '日清日结汇总', nameEn: 'ClosingSummary',  moduleId: 'A3', aiEntry: ['review'] },

  // ── A4 商品与菜单治理 ──
  { path: '/hub/menu',              name: '菜单列表', nameEn: 'MenuList',     moduleId: 'A4' },
  { path: '/hub/menu/:menuId',      name: '菜单详情', nameEn: 'MenuDetail',   moduleId: 'A4', hideInNav: true },
  { path: '/hub/items',             name: '品项列表', nameEn: 'ItemList',     moduleId: 'A4' },
  { path: '/hub/items/:itemId',     name: '品项详情', nameEn: 'ItemDetail',   moduleId: 'A4', hideInNav: true },
  { path: '/hub/bundles',           name: '套餐规则', nameEn: 'Bundles',      moduleId: 'A4' },
  { path: '/hub/daypart-menus',     name: '时段菜单', nameEn: 'DaypartMenus', moduleId: 'A4' },

  // ── A5 会员与增长总控 ──
  { path: '/hub/members/overview', name: '会员资产总览', nameEn: 'MemberOverview', moduleId: 'A5', aiEntry: ['review'] },
  { path: '/hub/members/segments', name: '人群分层',     nameEn: 'Segments',       moduleId: 'A5', aiEntry: ['task_input'] },
  { path: '/hub/campaigns',       name: '活动中心',     nameEn: 'Campaigns',      moduleId: 'A5' },
  { path: '/hub/coupons',         name: '券中心',       nameEn: 'Coupons',        moduleId: 'A5' },
  { path: '/hub/reach-analysis',  name: '触达分析',     nameEn: 'ReachAnalysis',  moduleId: 'A5', aiEntry: ['review'] },

  // ── A6 数据与报表中心 ──
  { path: '/hub/reports/daily',      name: '经营日报',   nameEn: 'DailyReport',   moduleId: 'A6', aiEntry: ['review'] },
  { path: '/hub/reports/weekly',     name: '周复盘',     nameEn: 'WeeklyReview',  moduleId: 'A6', priority: true, aiEntry: ['review'] },
  { path: '/hub/reports/monthly',    name: '月报',       nameEn: 'MonthlyReport', moduleId: 'A6', aiEntry: ['review'] },
  { path: '/hub/reports/category',   name: '品类分析',   nameEn: 'CategoryReport', moduleId: 'A6' },
  { path: '/hub/reports/dishes',     name: '菜品分析',   nameEn: 'DishReport',    moduleId: 'A6' },
  { path: '/hub/reports/table-turn', name: '翻台分析',   nameEn: 'TurnReport',    moduleId: 'A6' },
  { path: '/hub/reports/labor',      name: '人效分析',   nameEn: 'LaborReport',   moduleId: 'A6' },

  // ── A7 组织与权限 ──
  { path: '/hub/org',           name: '组织架构', nameEn: 'OrgChart',       moduleId: 'A7' },
  { path: '/hub/roles',         name: '角色权限', nameEn: 'Roles',          moduleId: 'A7' },
  { path: '/hub/data-scope',    name: '数据权限', nameEn: 'DataScope',      moduleId: 'A7' },
  { path: '/hub/audit',         name: '审计日志', nameEn: 'AuditLog',       moduleId: 'A7' },
  { path: '/hub/subscriptions', name: '消息订阅', nameEn: 'Subscriptions',  moduleId: 'A7' },
];

export const HUB_NAV: NavItem[] = [
  { key: 'dashboard', label: '驾驶舱', icon: 'dashboard', children: [
    { key: 'group',  label: '集团总览', path: '/hub/dashboard/group' },
    { key: 'brand',  label: '品牌概览', path: '/hub/dashboard/brand' },
    { key: 'region', label: '区域概览', path: '/hub/dashboard/region' },
    { key: 'stores', label: '门店对比', path: '/hub/dashboard/stores' },
    { key: 'alerts', label: '预警中心', path: '/hub/alerts' },
    { key: 'qa',     label: 'AI问答',  path: '/hub/qa' },
  ]},
  { key: 'agent', label: 'Agent决策', icon: 'robot', children: [
    { key: 'orchestrator', label: '总控工作台',   path: '/hub/agent/orchestrator' },
    { key: 'analysis',     label: '经营分析Agent', path: '/hub/agent/analysis' },
    { key: 'alert-agent',  label: '预警处置Agent', path: '/hub/agent/alerts' },
    { key: 'tasks',        label: '任务中心',      path: '/hub/tasks' },
    { key: 'approvals',    label: '审批确认',      path: '/hub/approvals' },
  ]},
  { key: 'store-gov', label: '门店治理', icon: 'shop', children: [
    { key: 'store-list',   label: '门店列表',     path: '/hub/stores' },
    { key: 'inspections',  label: '巡店管理',     path: '/hub/inspections' },
    { key: 'rects',        label: '整改闭环',     path: '/hub/rectifications' },
    { key: 'closing',      label: '日清汇总',     path: '/hub/closing-summary' },
  ]},
  { key: 'catalog', label: '商品治理', icon: 'menu', children: [
    { key: 'menu-list', label: '菜单中心', path: '/hub/menu' },
    { key: 'items',     label: '品项中心', path: '/hub/items' },
    { key: 'bundles',   label: '套餐规则', path: '/hub/bundles' },
    { key: 'daypart',   label: '时段菜单', path: '/hub/daypart-menus' },
  ]},
  { key: 'members', label: '会员增长', icon: 'team', children: [
    { key: 'overview',  label: '会员总览', path: '/hub/members/overview' },
    { key: 'segments',  label: '人群分层', path: '/hub/members/segments' },
    { key: 'campaigns', label: '活动中心', path: '/hub/campaigns' },
    { key: 'coupons',   label: '券中心',   path: '/hub/coupons' },
    { key: 'reach',     label: '触达分析', path: '/hub/reach-analysis' },
  ]},
  { key: 'reports', label: '报表中心', icon: 'bar-chart', children: [
    { key: 'daily',   label: '日报',     path: '/hub/reports/daily' },
    { key: 'weekly',  label: '周复盘',   path: '/hub/reports/weekly' },
    { key: 'monthly', label: '月报',     path: '/hub/reports/monthly' },
    { key: 'cat',     label: '品类分析', path: '/hub/reports/category' },
    { key: 'dish',    label: '菜品分析', path: '/hub/reports/dishes' },
    { key: 'turn',    label: '翻台分析', path: '/hub/reports/table-turn' },
    { key: 'labor',   label: '人效分析', path: '/hub/reports/labor' },
  ]},
  { key: 'org', label: '组织权限', icon: 'setting', children: [
    { key: 'org-chart', label: '组织架构', path: '/hub/org' },
    { key: 'roles',     label: '角色权限', path: '/hub/roles' },
    { key: 'scope',     label: '数据权限', path: '/hub/data-scope' },
    { key: 'audit',     label: '审计日志', path: '/hub/audit' },
    { key: 'subs',      label: '消息订阅', path: '/hub/subscriptions' },
  ]},
];
