/**
 * F. Platform 平台治理台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const PLATFORM_ROUTES: RouteNode[] = [
  // ── F1 门店与设备 ──
  { path: '/platform/stores',              name: '门店列表',   nameEn: 'PlatformStores',  moduleId: 'F1' },
  { path: '/platform/stores/:storeId',     name: '门店详情',   nameEn: 'PlatformStoreDetail', moduleId: 'F1', hideInNav: true },
  { path: '/platform/edge',               name: 'Edge节点',   nameEn: 'EdgeNodes',       moduleId: 'F1' },
  { path: '/platform/edge/:nodeId',        name: '节点详情',   nameEn: 'EdgeNodeDetail',  moduleId: 'F1', hideInNav: true },
  { path: '/platform/devices/pos',         name: 'POS设备',    nameEn: 'PosDevices',      moduleId: 'F1' },
  { path: '/platform/devices/kds',         name: 'KDS设备',    nameEn: 'KdsDevices',      moduleId: 'F1' },
  { path: '/platform/devices/printers',    name: '打印机',     nameEn: 'Printers',        moduleId: 'F1' },
  { path: '/platform/device-alerts',       name: '设备告警',   nameEn: 'DeviceAlerts',    moduleId: 'F1', aiEntry: ['alert_card'] },

  // ── F2 集成与接口 ──
  { path: '/platform/integrations/payments',      name: '支付通道',   nameEn: 'PaymentChannels',  moduleId: 'F2' },
  { path: '/platform/integrations/providers',     name: '第三方接口', nameEn: 'Providers',         moduleId: 'F2' },
  { path: '/platform/integrations/webhooks',      name: 'Webhook',    nameEn: 'Webhooks',          moduleId: 'F2' },
  { path: '/platform/integrations/api-keys',      name: 'API Key',    nameEn: 'ApiKeys',           moduleId: 'F2' },
  { path: '/platform/integrations/callback-logs', name: '回调日志',   nameEn: 'CallbackLogs',      moduleId: 'F2' },

  // ── F3 配置中心 ──
  { path: '/platform/config/menu',              name: '菜单配置',   nameEn: 'MenuConfig',         moduleId: 'F3' },
  { path: '/platform/config/pricing',           name: '价格配置',   nameEn: 'PricingConfig',      moduleId: 'F3' },
  { path: '/platform/config/business-calendar', name: '营业日历',   nameEn: 'BusinessCalendar',   moduleId: 'F3' },
  { path: '/platform/config/daypart-rules',     name: '时段规则',   nameEn: 'DaypartRules',       moduleId: 'F3' },
  { path: '/platform/config/env',               name: '环境配置',   nameEn: 'EnvConfig',          moduleId: 'F3' },

  // ── F4 风控与审计 ──
  { path: '/platform/risk/rules',    name: '风险规则',   nameEn: 'RiskRules',      moduleId: 'F4' },
  { path: '/platform/risk/events',   name: '异常事件',   nameEn: 'RiskEvents',     moduleId: 'F4', aiEntry: ['alert_card'] },
  { path: '/platform/audit',         name: '审计日志',   nameEn: 'PlatformAudit',  moduleId: 'F4' },
  { path: '/platform/operation-logs', name: '操作留痕',  nameEn: 'OperationLogs',  moduleId: 'F4' },

  // ── F5 权限中心 ──
  { path: '/platform/access/users',     name: '用户',       nameEn: 'Users',      moduleId: 'F5' },
  { path: '/platform/access/roles',     name: '角色',       nameEn: 'AccessRoles', moduleId: 'F5' },
  { path: '/platform/access/positions', name: '岗位',       nameEn: 'Positions',   moduleId: 'F5' },
  { path: '/platform/access/scopes',    name: '范围授权',   nameEn: 'Scopes',      moduleId: 'F5' },
];

export const PLATFORM_NAV: NavItem[] = [
  { key: 'devices', label: '门店与设备', icon: 'cluster', children: [
    { key: 'stores',   label: '门店列表', path: '/platform/stores' },
    { key: 'edge',     label: 'Edge节点', path: '/platform/edge' },
    { key: 'pos',      label: 'POS设备',  path: '/platform/devices/pos' },
    { key: 'kds',      label: 'KDS设备',  path: '/platform/devices/kds' },
    { key: 'printers', label: '打印机',   path: '/platform/devices/printers' },
    { key: 'alerts',   label: '设备告警', path: '/platform/device-alerts' },
  ]},
  { key: 'integrations', label: '集成接口', icon: 'api', children: [
    { key: 'payments',  label: '支付通道',   path: '/platform/integrations/payments' },
    { key: 'providers', label: '第三方接口', path: '/platform/integrations/providers' },
    { key: 'webhooks',  label: 'Webhook',    path: '/platform/integrations/webhooks' },
    { key: 'api-keys',  label: 'API Key',    path: '/platform/integrations/api-keys' },
    { key: 'callbacks', label: '回调日志',   path: '/platform/integrations/callback-logs' },
  ]},
  { key: 'config', label: '配置中心', icon: 'control', children: [
    { key: 'menu',     label: '菜单配置', path: '/platform/config/menu' },
    { key: 'pricing',  label: '价格配置', path: '/platform/config/pricing' },
    { key: 'calendar', label: '营业日历', path: '/platform/config/business-calendar' },
    { key: 'daypart',  label: '时段规则', path: '/platform/config/daypart-rules' },
    { key: 'env',      label: '环境配置', path: '/platform/config/env' },
  ]},
  { key: 'risk', label: '风控审计', icon: 'safety', children: [
    { key: 'rules',  label: '风险规则', path: '/platform/risk/rules' },
    { key: 'events', label: '异常事件', path: '/platform/risk/events' },
    { key: 'audit',  label: '审计日志', path: '/platform/audit' },
    { key: 'ops',    label: '操作留痕', path: '/platform/operation-logs' },
  ]},
  { key: 'access', label: '权限中心', icon: 'lock', children: [
    { key: 'users',     label: '用户',     path: '/platform/access/users' },
    { key: 'roles',     label: '角色',     path: '/platform/access/roles' },
    { key: 'positions', label: '岗位',     path: '/platform/access/positions' },
    { key: 'scopes',    label: '范围授权', path: '/platform/access/scopes' },
  ]},
];
