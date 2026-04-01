/**
 * B. Front 前厅协同台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const FRONT_ROUTES: RouteNode[] = [
  // ── B1 迎宾工作台 ──
  { path: '/front/workbench', name: '前厅工作台', nameEn: 'FrontWorkbench', moduleId: 'B1', priority: true, aiEntry: ['task_input', 'alert_card'] },

  // ── B2 预订管理 ──
  { path: '/front/reservations',                       name: '预订台账',   nameEn: 'ReservationList',    moduleId: 'B2', priority: true, aiEntry: ['task_input', 'alert_card'] },
  { path: '/front/reservations/new',                   name: '新建预订',   nameEn: 'NewReservation',     moduleId: 'B2', hideInNav: true },
  { path: '/front/reservations/:reservationId',        name: '预订详情',   nameEn: 'ReservationDetail',  moduleId: 'B2', hideInNav: true },
  { path: '/front/reservations/:reservationId/edit',   name: '改约',       nameEn: 'EditReservation',    moduleId: 'B2', hideInNav: true },
  { path: '/front/reservations/private-room',          name: '包厢预订',   nameEn: 'PrivateRoom',        moduleId: 'B2' },
  { path: '/front/reservations/banquet',               name: '团餐/宴会',  nameEn: 'Banquet',            moduleId: 'B2' },

  // ── B3 等位管理 ──
  { path: '/front/waitlist',               name: '等位队列', nameEn: 'WaitlistQueue',   moduleId: 'B3', priority: true, aiEntry: ['alert_card'] },
  { path: '/front/waitlist/:queueId',      name: '等位详情', nameEn: 'WaitlistDetail',  moduleId: 'B3', hideInNav: true },
  { path: '/front/waitlist/call',          name: '叫号台',   nameEn: 'CallStation',     moduleId: 'B3' },
  { path: '/front/waitlist/recovery',      name: '过号处理', nameEn: 'WaitlistRecovery', moduleId: 'B3', hideInNav: true },

  // ── B4 桌台管理 ──
  { path: '/front/tables',                        name: '桌态总览',   nameEn: 'TableOverview',    moduleId: 'B4', priority: true, aiEntry: ['suggestion'] },
  { path: '/front/tables/zones/:zoneId',           name: '桌区详情',   nameEn: 'ZoneDetail',       moduleId: 'B4', hideInNav: true },
  { path: '/front/tables/:tableId',                name: '桌台详情',   nameEn: 'TableDetail',      moduleId: 'B4', hideInNav: true },
  { path: '/front/tables/:tableId/merge',          name: '并台',       nameEn: 'MergeTable',       moduleId: 'B4', hideInNav: true },
  { path: '/front/tables/:tableId/split',          name: '拆台',       nameEn: 'SplitTable',       moduleId: 'B4', hideInNav: true },
  { path: '/front/tables/turnover-forecast',       name: '翻台预测',   nameEn: 'TurnoverForecast', moduleId: 'B4', aiEntry: ['suggestion'] },

  // ── B5 前厅 Agent 协同 ──
  { path: '/front/agent/reservation',     name: '预订Agent',     nameEn: 'ReservationAgent',  moduleId: 'B5', aiEntry: ['task_input'] },
  { path: '/front/agent/waitlist',        name: '等位Agent',     nameEn: 'WaitlistAgent',     moduleId: 'B5', aiEntry: ['task_input'] },
  { path: '/front/agent/table-dispatch',  name: '桌台调度Agent', nameEn: 'TableDispatchAgent', moduleId: 'B5', aiEntry: ['suggestion'] },
  { path: '/front/agent/vip-recognition', name: '高价值客识别',  nameEn: 'VipRecognition',    moduleId: 'B5', aiEntry: ['alert_card'] },
];

export const FRONT_NAV: NavItem[] = [
  { key: 'workbench', label: '工作台', icon: 'appstore', path: '/front/workbench' },
  { key: 'reservation', label: '预订', icon: 'calendar', children: [
    { key: 'list',         label: '预订台账', path: '/front/reservations' },
    { key: 'private-room', label: '包厢预订', path: '/front/reservations/private-room' },
    { key: 'banquet',      label: '团餐/宴会', path: '/front/reservations/banquet' },
  ]},
  { key: 'waitlist', label: '等位', icon: 'team', children: [
    { key: 'queue', label: '等位队列', path: '/front/waitlist' },
    { key: 'call',  label: '叫号台',   path: '/front/waitlist/call' },
  ]},
  { key: 'tables', label: '桌台', icon: 'table', children: [
    { key: 'overview', label: '桌态总览', path: '/front/tables' },
    { key: 'forecast', label: '翻台预测', path: '/front/tables/turnover-forecast' },
  ]},
  { key: 'agent', label: 'Agent协同', icon: 'robot', children: [
    { key: 'res-agent',   label: '预订Agent',     path: '/front/agent/reservation' },
    { key: 'wait-agent',  label: '等位Agent',      path: '/front/agent/waitlist' },
    { key: 'table-agent', label: '桌台调度Agent',  path: '/front/agent/table-dispatch' },
    { key: 'vip',         label: '高价值客识别',    path: '/front/agent/vip-recognition' },
  ]},
];
