import React, { useState, useMemo, useCallback } from 'react';
import { Dropdown, Avatar, Space, Tag, Badge, Tooltip, Button } from 'antd';
import type { MenuProps } from 'antd';
import NotificationCenter from '../components/NotificationCenter';
import {
  DashboardOutlined,
  ScheduleOutlined,
  ShoppingCartOutlined,
  InboxOutlined,
  CustomerServiceOutlined,
  ReadOutlined,
  BarChartOutlined,
  CalendarOutlined,
  UserOutlined,
  LogoutOutlined,
  SettingOutlined,
  TeamOutlined,
  ApiOutlined,
  LineChartOutlined,
  MobileOutlined,
  ShopOutlined,
  ShoppingOutlined,
  MonitorOutlined,
  DatabaseOutlined,
  BellOutlined,
  DollarOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  HomeOutlined,
  BulbOutlined,
  BulbFilled,
  SearchOutlined,
  RiseOutlined,
  GlobalOutlined,
  SafetyOutlined,
  CheckCircleOutlined,
  RobotOutlined,
  CloudOutlined,
  ExperimentOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  TranslationOutlined,
  ExportOutlined,
  SyncOutlined,
  SoundOutlined,
  ToolOutlined,
  UploadOutlined,
  TrophyOutlined,
  HistoryOutlined,
  WarningOutlined,
  FireOutlined,
  PieChartOutlined,
  UnorderedListOutlined,
  FundOutlined,
  ControlOutlined,
  UsergroupAddOutlined,
  NodeIndexOutlined,
  RocketOutlined,
  HeartOutlined,
  WifiOutlined,
  DesktopOutlined,
  BankOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  EnvironmentOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { GlobalSearch } from '../components/GlobalSearch';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useBrandTheme } from '../hooks/useBrandTheme';
import styles from './MainLayout.module.css';

// ══════════════════════════════════════════════════════════════
// L1 Domain Tabs — 5 个功能域
// ══════════════════════════════════════════════════════════════

interface DomainTab {
  key: string;
  label: string;
  adminOnly?: boolean;
}

const DOMAIN_TABS: DomainTab[] = [
  { key: 'overview',    label: '经营总览' },
  { key: 'operations',  label: '运营中心' },
  { key: 'growth',      label: '增长引擎' },
  { key: 'supply',      label: '供应链' },
  { key: 'agents',      label: '智能体' },
  { key: 'platform',    label: '平台治理', adminOnly: true },
];

// ══════════════════════════════════════════════════════════════
// L2 Sidebar Items — 按 domain → group → items 组织
// ══════════════════════════════════════════════════════════════

interface SidebarItem {
  key: string;
  label: string;
  icon: React.ReactNode;
}

interface SidebarGroup {
  groupLabel: string;
  items: SidebarItem[];
}

type DomainSidebar = Record<string, SidebarGroup[]>;

const DOMAIN_SIDEBAR: DomainSidebar = {
  overview: [
    {
      groupLabel: '经营看板',
      items: [
        { key: '/',                     icon: <DashboardOutlined />,  label: '经营作战台' },
        { key: '/daily-hub',            icon: <RiseOutlined />,       label: '明日备战板' },
        { key: '/kpi-dashboard',        icon: <BarChartOutlined />,   label: 'KPI仪表盘' },
        { key: '/profit-dashboard',     icon: <LineChartOutlined />,  label: '利润分析' },
        { key: '/monthly-report',       icon: <FileTextOutlined />,   label: '月度报告' },
        { key: '/decision-stats',       icon: <PieChartOutlined />,   label: '决策统计' },
        { key: '/forecast',             icon: <LineChartOutlined />,  label: '需求预测' },
      ],
    },
    {
      groupLabel: '跨门店',
      items: [
        { key: '/cross-store-insights', icon: <GlobalOutlined />,     label: '跨店洞察' },
        { key: '/competitive-analysis', icon: <RiseOutlined />,       label: '竞争分析' },
        { key: '/hq-dashboard',         icon: <ShopOutlined />,       label: '总部看板' },
        { key: '/data-visualization',   icon: <MonitorOutlined />,    label: '数据大屏' },
      ],
    },
    {
      groupLabel: '财务',
      items: [
        { key: '/finance',              icon: <DollarOutlined />,     label: '财务管理' },
        { key: '/cfo-dashboard',        icon: <DollarOutlined />,     label: 'CFO 工作台' },
        { key: '/ceo-dashboard',        icon: <FundOutlined />,       label: 'CEO 驾驶舱' },
        { key: '/budget-management',    icon: <DollarOutlined />,     label: '预算管理' },
        { key: '/settlement-risk',      icon: <SafetyOutlined />,     label: '结算风控' },
        { key: '/financial-alerts',     icon: <BellOutlined />,       label: '财务预警' },
        { key: '/finance-health',       icon: <FundOutlined />,       label: '财务健康' },
        { key: '/financial-forecast',   icon: <LineChartOutlined />,  label: '财务预测' },
        { key: '/financial-anomaly',    icon: <WarningOutlined />,    label: '财务异常' },
        { key: '/performance-ranking',  icon: <TrophyOutlined />,     label: '对标排名' },
        { key: '/financial-recommendation', icon: <BulbOutlined />,   label: '智能建议' },
        { key: '/business-events',      icon: <NodeIndexOutlined />,  label: '事件中心' },
      ],
    },
    {
      groupLabel: '菜品分析',
      items: [
        { key: '/dish-profitability',   icon: <PieChartOutlined />,   label: '盈利分析' },
        { key: '/menu-optimization',    icon: <BulbOutlined />,       label: '菜单优化' },
        { key: '/dish-cost-alert',      icon: <WarningOutlined />,    label: '成本预警' },
        { key: '/dish-benchmark',       icon: <TrophyOutlined />,     label: '跨店对标' },
        { key: '/dish-pricing',         icon: <DollarOutlined />,     label: '智能定价' },
        { key: '/dish-lifecycle',       icon: <HistoryOutlined />,    label: '生命周期' },
        { key: '/dish-forecast',        icon: <LineChartOutlined />,  label: '销售预测' },
        { key: '/dish-health',          icon: <HeartOutlined />,      label: '健康评分' },
        { key: '/dish-attribution',     icon: <FundOutlined />,       label: '营收归因' },
        { key: '/menu-matrix',          icon: <PieChartOutlined />,   label: '组合矩阵' },
        { key: '/cost-compression',     icon: <DollarOutlined />,     label: '成本压缩' },
        { key: '/dish-monthly-summary', icon: <FileTextOutlined />,   label: '菜品月报' },
        { key: '/fct-advanced',         icon: <BankOutlined />,       label: 'FCT 高级' },
      ],
    },
  ],

  operations: [
    {
      groupLabel: '日常运营',
      items: [
        { key: '/ops-hub',             icon: <AppstoreOutlined />,        label: '运营中心' },
        { key: '/schedule',            icon: <ScheduleOutlined />,        label: '智能排班' },
        { key: '/employees',           icon: <TeamOutlined />,            label: '员工管理' },
        { key: '/my-schedule',         icon: <CalendarOutlined />,        label: '我的班表' },
        { key: '/employee-performance',icon: <TrophyOutlined />,          label: '员工绩效' },
        { key: '/workforce',           icon: <TeamOutlined />,            label: '人力管理' },
      ],
    },
    {
      groupLabel: '门店服务',
      items: [
        { key: '/queue',               icon: <TeamOutlined />,            label: '排队管理' },
        { key: '/meituan-queue',       icon: <SyncOutlined />,            label: '美团排队' },
        { key: '/reservation',         icon: <CalendarOutlined />,        label: '预订宴会' },
        { key: '/pos',                 icon: <ShoppingCartOutlined />,    label: 'POS系统' },
        { key: '/service',             icon: <CustomerServiceOutlined />, label: '服务质量' },
      ],
    },
    {
      groupLabel: '合规与任务',
      items: [
        { key: '/quality',             icon: <CheckCircleOutlined />,     label: '质量管理' },
        { key: '/compliance',          icon: <SafetyOutlined />,          label: '合规管理' },
        { key: '/human-in-the-loop',   icon: <CheckCircleOutlined />,     label: '人工审批' },
        { key: '/tasks',               icon: <FileTextOutlined />,        label: '任务管理' },
        { key: '/action-plans',        icon: <CheckCircleOutlined />,     label: 'L5 行动计划' },
        { key: '/ops-agent',           icon: <ToolOutlined />,            label: 'IT运维Agent' },
        { key: '/voice-devices',       icon: <SoundOutlined />,           label: '语音设备' },
      ],
    },
  ],

  growth: [
    {
      groupLabel: '会员',
      items: [
        { key: '/crm-hub',            icon: <AppstoreOutlined />,  label: '增长中心' },
        { key: '/members',            icon: <UserOutlined />,      label: '会员中心' },
        { key: '/customer360',        icon: <UserOutlined />,      label: '客户360' },
        { key: '/private-domain',     icon: <TeamOutlined />,      label: '私域运营' },
      ],
    },
    {
      groupLabel: '营销',
      items: [
        { key: '/marketing',          icon: <RocketOutlined />,    label: '营销智能体' },
        { key: '/recommendations',    icon: <BulbOutlined />,      label: '推荐引擎' },
        { key: '/wechat-triggers',    icon: <BellOutlined />,      label: '企微触发器' },
        { key: '/channel-profit',     icon: <ShopOutlined />,      label: '渠道毛利' },
      ],
    },
  ],

  supply: [
    {
      groupLabel: '商品管理',
      items: [
        { key: '/products-hub',       icon: <AppstoreOutlined />,     label: '供应链中心' },
        { key: '/dishes',             icon: <ShoppingOutlined />,     label: '菜品管理' },
        { key: '/bom-management',     icon: <ReadOutlined />,         label: 'BOM配方' },
        { key: '/dish-cost',          icon: <DollarOutlined />,       label: '菜品成本' },
        { key: '/dish-rd',            icon: <ExperimentOutlined />,   label: '菜品研发' },
        { key: '/dynamic-pricing',    icon: <DollarOutlined />,       label: '动态定价' },
      ],
    },
    {
      groupLabel: '库存与采购',
      items: [
        { key: '/inventory',          icon: <InboxOutlined />,        label: '库存管理' },
        { key: '/order',              icon: <ShoppingCartOutlined />, label: '订单协同' },
        { key: '/supply-chain',       icon: <ShoppingOutlined />,     label: '供应链管理' },
        { key: '/supplier-agent',     icon: <ShoppingOutlined />,     label: '供应商管理' },
        { key: '/reconciliation',     icon: <FileExcelOutlined />,    label: '对账管理' },
      ],
    },
    {
      groupLabel: '损耗管控',
      items: [
        { key: '/waste-reasoning',    icon: <FireOutlined />,         label: '损耗分析' },
        { key: '/waste-events',       icon: <WarningOutlined />,      label: '损耗事件' },
        { key: '/alert-thresholds',   icon: <BellOutlined />,         label: '告警阈值' },
      ],
    },
  ],

  agents: [
    {
      groupLabel: '总览',
      items: [
        { key: '/agent-hub',          icon: <AppstoreOutlined />,     label: 'Agent 总览' },
        { key: '/decision',           icon: <BarChartOutlined />,     label: '经营决策' },
        { key: '/training',           icon: <ReadOutlined />,         label: '培训管理' },
      ],
    },
    {
      groupLabel: 'Agent 工作台',
      items: [
        { key: '/business-intel',     icon: <RobotOutlined />,        label: '经营智能体' },
        { key: '/people-agent',       icon: <TeamOutlined />,         label: '人员智能体' },
        { key: '/ops-flow-agent',     icon: <ApiOutlined />,          label: '运营流程体' },
        { key: '/agent-okr',          icon: <BarChartOutlined />,     label: 'Agent OKR' },
        { key: '/agent-collab',       icon: <ApiOutlined />,          label: '协同总线' },
      ],
    },
    {
      groupLabel: '配置与治理',
      items: [
        { key: '/agent-collaboration',icon: <ApartmentOutlined />,    label: '协作编排' },
        { key: '/agent-memory',       icon: <DatabaseOutlined />,     label: 'Agent 记忆' },
        { key: '/knowledge-rules',    icon: <DatabaseOutlined />,     label: '知识规则库' },
        { key: '/governance',         icon: <SafetyOutlined />,       label: 'AI 治理' },
        { key: '/decision-validator', icon: <CheckCircleOutlined />,  label: '决策验证' },
        { key: '/ai-accuracy',       icon: <BarChartOutlined />,      label: 'AI 准确率' },
        { key: '/ai-evolution',      icon: <RobotOutlined />,         label: 'AI 进化' },
      ],
    },
    {
      groupLabel: '底层技术',
      items: [
        { key: '/edge-node',          icon: <CloudOutlined />,        label: '边缘节点' },
        { key: '/federated-learning', icon: <ExperimentOutlined />,   label: '联邦学习' },
        { key: '/neural',             icon: <ApartmentOutlined />,    label: '神经系统' },
        { key: '/embedding',          icon: <ExperimentOutlined />,   label: '嵌入模型' },
        { key: '/vector-index',       icon: <SearchOutlined />,       label: '向量知识库' },
        { key: '/event-sourcing',     icon: <FileTextOutlined />,     label: '事件溯源' },
        { key: '/voice-ws',           icon: <SoundOutlined />,        label: '语音 WS' },
      ],
    },
  ],

  platform: [
    {
      groupLabel: '组织与权限',
      items: [
        { key: '/platform-hub',       icon: <AppstoreOutlined />,     label: '治理中心' },
        { key: '/merchants',          icon: <BankOutlined />,         label: '商户管理' },
        { key: '/users',              icon: <TeamOutlined />,         label: '用户管理' },
        { key: '/stores',             icon: <ShopOutlined />,         label: '门店管理' },
        { key: '/multi-store',        icon: <ShopOutlined />,         label: '多门店管理' },
        { key: '/cross-store-config', icon: <ShopOutlined />,         label: '跨店协调' },
        { key: '/roles',              icon: <SafetyOutlined />,       label: '角色权限' },
      ],
    },
    {
      groupLabel: '审批与审计',
      items: [
        { key: '/approval',           icon: <CheckCircleOutlined />,  label: '审批管理' },
        { key: '/approval-list',      icon: <UnorderedListOutlined />,label: '审批列表' },
        { key: '/audit',              icon: <FileTextOutlined />,     label: '审计日志' },
        { key: '/data-security',      icon: <SafetyOutlined />,       label: '数据安全' },
      ],
    },
    {
      groupLabel: '集成与适配',
      items: [
        { key: '/integrations',       icon: <ApiOutlined />,          label: '外部集成' },
        { key: '/adapters',           icon: <ApiOutlined />,          label: '适配器管理' },
        { key: '/enterprise',         icon: <ApiOutlined />,          label: '企业集成' },
        { key: '/llm-config',         icon: <SettingOutlined />,      label: 'LLM配置' },
        { key: '/model-marketplace',  icon: <AppstoreOutlined />,     label: '模型市场' },
      ],
    },
    {
      groupLabel: '硬件与边缘',
      items: [
        { key: '/hardware',           icon: <CloudOutlined />,        label: '硬件管理' },
        { key: '/edge-hub',           icon: <WifiOutlined />,         label: 'Edge Hub' },
        { key: '/edge-hub/nodes',     icon: <DesktopOutlined />,      label: 'Edge 节点' },
        { key: '/edge-hub/alerts',    icon: <BellOutlined />,         label: 'Edge 告警' },
        { key: '/edge-hub/bindings',  icon: <ApiOutlined />,          label: '耳机绑定' },
      ],
    },
    {
      groupLabel: '系统监控',
      items: [
        { key: '/monitoring',         icon: <MonitorOutlined />,      label: '系统监控' },
        { key: '/system-health',      icon: <MonitorOutlined />,      label: '系统健康' },
        { key: '/scheduler',          icon: <CalendarOutlined />,     label: '调度管理' },
        { key: '/benchmark',          icon: <BarChartOutlined />,     label: '基准测试' },
      ],
    },
    {
      groupLabel: '数据与配置',
      items: [
        { key: '/backup',             icon: <DatabaseOutlined />,     label: '数据备份' },
        { key: '/export-jobs',        icon: <ExportOutlined />,       label: '导出任务' },
        { key: '/data-import-export', icon: <FileExcelOutlined />,    label: '导入导出' },
        { key: '/bulk-import',        icon: <UploadOutlined />,       label: '批量导入' },
        { key: '/report-templates',   icon: <FileTextOutlined />,     label: '报表模板' },
      ],
    },
    {
      groupLabel: '开放平台',
      items: [
        { key: '/open-platform',      icon: <AppstoreOutlined />,     label: '开放平台' },
        { key: '/developer-docs',     icon: <FileTextOutlined />,     label: '开发者文档' },
        { key: '/developer-console',  icon: <FundOutlined />,         label: '开发者控制台' },
        { key: '/isv-ecosystem',      icon: <RocketOutlined />,       label: 'ISV 生态' },
        { key: '/isv-management',     icon: <TeamOutlined />,         label: 'ISV 管理' },
        { key: '/plugin-marketplace', icon: <AppstoreOutlined />,     label: '插件市场' },
        { key: '/revenue-share',      icon: <DollarOutlined />,       label: '分成管理' },
        { key: '/isv-dashboard',      icon: <FundOutlined />,         label: 'ISV 看板' },
        { key: '/platform-analytics', icon: <RiseOutlined />,         label: '商业化总览' },
        { key: '/webhook-management', icon: <ApiOutlined />,          label: 'Webhook' },
        { key: '/api-billing',        icon: <DollarOutlined />,       label: 'API 计费' },
        { key: '/raas',               icon: <DollarOutlined />,       label: 'RaaS定价' },
        { key: '/industry-solutions', icon: <GlobalOutlined />,       label: '行业方案' },
        { key: '/i18n',               icon: <TranslationOutlined />,  label: '国际化' },
      ],
    },
  ],
};

// ══════════════════════════════════════════════════════════════
// 路由 → Domain 映射（自动构建）
// ══════════════════════════════════════════════════════════════

const ROUTE_TO_DOMAIN: Record<string, string> = {};
Object.entries(DOMAIN_SIDEBAR).forEach(([domain, groups]) => {
  groups.forEach(g => g.items.forEach(item => {
    ROUTE_TO_DOMAIN[item.key] = domain;
  }));
});
// 角色视图路由不映射到任何 domain
['/hq', '/sm', '/chef', '/floor', '/profile', '/notifications'].forEach(r => {
  ROUTE_TO_DOMAIN[r] = '';
});

// ══════════════════════════════════════════════════════════════
// 面包屑 label
// ══════════════════════════════════════════════════════════════

const BREADCRUMB_LABELS: Record<string, string> = {
  '/': '经营作战台',
  '/daily-hub': '明日备战板',
  '/kpi-dashboard': 'KPI仪表盘',
  '/profit-dashboard': '利润分析',
  '/monthly-report': '月度报告',
  '/forecast': '需求预测',
  '/cross-store-insights': '跨店洞察',
  '/hq-dashboard': '总部看板',
  '/data-visualization': '数据大屏',
  '/analytics': '高级分析',
  '/decision-stats': '决策统计',
  '/competitive-analysis': '竞争分析',
  '/report-templates': '报表模板',
  '/finance': '财务管理',
  '/products-hub': '供应链中心',
  '/schedule': '智能排班',
  '/employees': '员工管理',
  '/my-schedule': '我的班表',
  '/queue': '排队管理',
  '/meituan-queue': '美团排队',
  '/reservation': '预订宴会',
  '/pos': 'POS系统',
  '/service': '服务质量',
  '/quality': '质量管理',
  '/compliance': '合规管理',
  '/human-in-the-loop': '人工审批',
  '/tasks': '任务管理',
  '/ops-agent': 'IT运维Agent',
  '/voice-devices': '语音设备',
  '/employee-performance': '员工绩效',
  '/workforce': '人力管理',
  '/dishes': '菜品管理',
  '/bom-management': 'BOM配方',
  '/inventory': '库存管理',
  '/order': '订单协同',
  '/waste-reasoning': '损耗分析',
  '/waste-events': '损耗事件',
  '/supply-chain': '供应链管理',
  '/dish-cost': '菜品成本',
  '/alert-thresholds': '告警阈值',
  '/reconciliation': '对账管理',
  '/dish-rd': '菜品研发',
  '/supplier-agent': '供应商管理',
  '/business-intel': '经营智能体',
  '/people-agent': '人员智能体',
  '/ops-flow-agent': '运营流程体',
  '/agent-okr': 'Agent OKR',
  '/agent-collab': '协同总线',
  '/dynamic-pricing': '动态定价',
  '/members': '会员中心',
  '/crm-hub': '增长中心',
  '/marketing': '营销智能体',
  '/customer360': '客户360',
  '/private-domain': '私域运营',
  '/channel-profit': '渠道毛利',
  '/recommendations': '推荐引擎',
  '/wechat-triggers': '企微触发器',
  '/agent-hub': 'Agent 总览',
  '/decision': '决策支持',
  '/training': '培训管理',
  '/ai-evolution': 'AI 进化',
  '/ai-accuracy': 'AI 准确率',
  '/governance': 'AI 治理',
  '/agent-collaboration': '协作编排',
  '/agent-memory': 'Agent 记忆',
  '/knowledge-rules': '知识规则库',
  '/decision-validator': '决策验证',
  '/edge-node': '边缘节点',
  '/federated-learning': '联邦学习',
  '/neural': '神经系统',
  '/embedding': '嵌入模型',
  '/vector-index': '向量知识库',
  '/event-sourcing': '事件溯源',
  '/voice-ws': '语音 WebSocket',
  '/users': '用户管理',
  '/merchants': '商户管理',
  '/platform-hub': '治理中心',
  '/stores': '门店管理',
  '/multi-store': '多门店管理',
  '/cross-store-config': '跨店协调',
  '/approval': '审批管理',
  '/approval-list': '审批列表',
  '/action-plans': 'L5 行动计划',
  '/audit': '审计日志',
  '/data-security': '数据安全',
  '/integrations': '外部集成',
  '/adapters': '适配器管理',
  '/enterprise': '企业集成',
  '/llm-config': 'LLM配置',
  '/model-marketplace': '模型市场',
  '/hardware': '硬件管理',
  '/edge-hub': 'Edge Hub',
  '/edge-hub/nodes': 'Edge 节点',
  '/edge-hub/alerts': 'Edge 告警',
  '/edge-hub/bindings': '耳机绑定',
  '/monitoring': '系统监控',
  '/system-health': '系统健康',
  '/scheduler': '调度管理',
  '/backup': '数据备份',
  '/export-jobs': '导出任务',
  '/roles': '角色权限',
  '/data-import-export': '导入导出',
  '/bulk-import': '批量导入',
  '/open-platform': '开放平台',
  '/developer-docs': '开发者文档',
  '/isv-ecosystem': 'ISV 生态',
  '/isv-management': 'ISV 管理',
  '/plugin-marketplace': '插件市场',
  '/revenue-share': '分成管理',
  '/isv-dashboard': 'ISV 看板',
  '/platform-analytics': '商业化总览',
  '/webhook-management': 'Webhook',
  '/api-billing': 'API 计费',
  '/developer-console': '开发者控制台',
  '/business-events': '事件中心',
  '/cfo-dashboard': 'CFO 工作台',
  '/settlement-risk': '结算风控',
  '/ceo-dashboard': 'CEO 驾驶舱',
  '/budget-management': '预算管理',
  '/financial-alerts': '财务预警',
  '/finance-health': '财务健康',
  '/financial-forecast': '财务预测',
  '/financial-anomaly': '财务异常',
  '/performance-ranking': '对标排名',
  '/financial-recommendation': '智能建议',
  '/fct-advanced': 'FCT 高级',
  '/dish-profitability': '盈利分析',
  '/menu-optimization': '菜单优化',
  '/dish-cost-alert': '成本预警',
  '/dish-benchmark': '跨店对标',
  '/dish-pricing': '智能定价',
  '/dish-lifecycle': '生命周期',
  '/dish-forecast': '销售预测',
  '/dish-health': '健康评分',
  '/dish-attribution': '营收归因',
  '/menu-matrix': '组合矩阵',
  '/cost-compression': '成本压缩',
  '/dish-monthly-summary': '菜品月报',
  '/ops-hub': '运营中心',
  '/industry-solutions': '行业方案',
  '/i18n': '国际化',
  '/raas': 'RaaS定价',
  '/benchmark': '基准测试',
  '/hq': '总部大屏',
  '/sm': '店长移动端',
  '/chef': '厨师长看板',
  '/floor': '楼面经理看板',
  '/profile': '个人信息',
  '/notifications': '通知中心',
};

// ── RBAC 路由集 ─────────────────────────────────────────────

const PUBLIC_ROLE_ROUTES = new Set<string>([
  '/', '/daily-hub', '/schedule', '/reservation', '/notifications',
  '/my-schedule', '/ops-hub', '/products-hub', '/crm-hub',
  '/order-analytics', '/dashboard-preferences', '/notification-preferences',
  '/menu-recommendation',
]);

const STORE_MANAGER_EXTRA_ROUTES = new Set<string>([
  '/recommendations', '/dish-cost', '/channel-profit', '/employee-performance',
  '/waste-reasoning', '/bom-management', '/waste-events', '/banquet-lifecycle',
  '/marketing', '/fct', '/action-plans', '/workforce', '/alert-thresholds',
]);

// ══════════════════════════════════════════════════════════════
// Component
// ══════════════════════════════════════════════════════════════

const MainLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const { brandName } = useBrandTheme();

  const isAdmin = user?.role === 'admin';
  const userRole = user?.role || 'staff';

  // 当前路由对应的 domain
  const currentDomain = ROUTE_TO_DOMAIN[location.pathname] || 'overview';

  // 活跃 domain tab（用户可手动切换，也跟随路由）
  const [activeDomain, setActiveDomain] = useState(currentDomain || 'overview');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [searchVisible, setSearchVisible] = useState(false);

  // 路由变化时同步 domain
  const effectiveDomain = ROUTE_TO_DOMAIN[location.pathname] || activeDomain;
  if (effectiveDomain && effectiveDomain !== activeDomain) {
    setActiveDomain(effectiveDomain);
  }

  // ── RBAC ──
  const allowedRoutes = useMemo(() => {
    const routes = new Set<string>(PUBLIC_ROLE_ROUTES);
    if (userRole === 'store_manager') {
      STORE_MANAGER_EXTRA_ROUTES.forEach(r => routes.add(r));
    }
    return routes;
  }, [userRole]);

  const isRouteAllowed = useCallback((key: string) => {
    return isAdmin || allowedRoutes.has(key);
  }, [isAdmin, allowedRoutes]);

  // ── 快捷键 ──
  useKeyboardShortcuts([
    { key: 'k', ctrl: true, callback: () => setSearchVisible(true), description: '打开搜索' },
    { key: 't', ctrl: true, shift: true, callback: toggleTheme, description: '切换主题' },
    { key: 'h', ctrl: true, callback: () => navigate('/'), description: '返回首页' },
    { key: 'n', ctrl: true, callback: () => navigate('/notifications'), description: '打开通知' },
  ]);

  // ── 角色 ──
  const roleMap: Record<string, { text: string; color: string }> = {
    admin: { text: '管理员', color: 'red' },
    store_manager: { text: '店长', color: 'blue' },
    manager: { text: '经理', color: 'blue' },
    staff: { text: '员工', color: 'green' },
    waiter: { text: '服务员', color: 'green' },
  };

  // ── User Menu ──
  const userMenuItems: MenuProps['items'] = [
    { key: 'profile', icon: <UserOutlined />, label: '个人信息' },
    { key: 'settings', icon: <SettingOutlined />, label: '设置' },
    { type: 'divider' },
    // 角色视图
    { key: '/sm', icon: <MobileOutlined />, label: '店长首页' },
    { key: '/chef', icon: <TeamOutlined />, label: '厨师长看板' },
    { key: '/floor', icon: <HomeOutlined />, label: '楼面经理看板' },
    ...(isAdmin ? [{ key: '/hq', icon: <ShopOutlined />, label: '总部大屏' }] : []),
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ];

  const handleUserMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'logout') { logout(); navigate('/login'); }
    else if (key === 'profile') { navigate('/profile'); }
    else if (key.startsWith('/')) { navigate(key); }
  };

  // ── Domain Tab Click ──
  const handleDomainClick = (domain: string) => {
    setActiveDomain(domain);
    // 导航到该 domain 的第一个页面
    const groups = DOMAIN_SIDEBAR[domain];
    if (groups?.[0]?.items?.[0]) {
      navigate(groups[0].items[0].key);
    }
  };

  // ── Sidebar Group Toggle ──
  const toggleGroup = (groupLabel: string) => {
    setExpandedGroups(prev => ({
      ...prev,
      [groupLabel]: prev[groupLabel] === false ? true : prev[groupLabel] === undefined ? false : !prev[groupLabel],
    }));
  };

  const isGroupExpanded = (groupLabel: string) => {
    return expandedGroups[groupLabel] !== false; // default expanded
  };

  // ── Current sidebar groups ──
  const sidebarGroups = DOMAIN_SIDEBAR[activeDomain] || [];

  // ── Breadcrumb ──
  const domainLabel = DOMAIN_TABS.find(t => t.key === activeDomain)?.label || '';

  const breadcrumbItems = () => {
    const snippets = location.pathname.split('/').filter(Boolean);
    const parts: { key: string; label: string }[] = [];
    snippets.forEach((_, i) => {
      const url = `/${snippets.slice(0, i + 1).join('/')}`;
      parts.push({ key: url, label: BREADCRUMB_LABELS[url] ?? snippets[i] });
    });
    return parts;
  };

  return (
    <div className={styles.layout}>
      <GlobalSearch visible={searchVisible} onClose={() => setSearchVisible(false)} />

      {/* ════════════════ L1 · 顶部导航栏 ════════════════ */}
      <nav className={styles.topNav}>
        <div className={styles.topNavLeft}>
          {/* Logo */}
          <div className={styles.logo} onClick={() => navigate('/')}>
            <img src="/logo-mark-v3.svg" alt="屯象" style={{ width: 26, height: 32 }} />
            <span className={styles.logoText}>{brandName || '智链OS'}</span>
          </div>

          <div className={styles.divider} />

          {/* Domain Tabs */}
          <div className={styles.domainTabs}>
            {DOMAIN_TABS.map(tab => {
              if (tab.adminOnly && !isAdmin) return null;
              return (
                <button
                  key={tab.key}
                  className={`${styles.domainTab} ${activeDomain === tab.key ? styles.domainTabActive : ''}`}
                  onClick={() => handleDomainClick(tab.key)}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className={styles.topNavRight}>
          {/* Search Trigger */}
          <div className={styles.searchTrigger} onClick={() => setSearchVisible(true)}>
            <SearchOutlined />
            <span>搜索功能、数据...</span>
            <span className={styles.searchKbd}>⌘K</span>
          </div>

          {/* Theme Toggle */}
          <Tooltip title={isDark ? '切换亮色' : '切换暗色'}>
            <button className={styles.topNavIcon} onClick={toggleTheme}>
              {isDark ? <BulbFilled style={{ color: '#faad14' }} /> : <BulbOutlined />}
            </button>
          </Tooltip>

          {/* Notifications */}
          <NotificationCenter />

          {/* User Avatar + Dropdown */}
          <Dropdown
            menu={{ items: userMenuItems, onClick: handleUserMenuClick }}
            placement="bottomRight"
          >
            <Space style={{ cursor: 'pointer', padding: '0 2px' }}>
              <Avatar icon={<UserOutlined />} size={30} style={{ backgroundColor: 'var(--accent, #0A84FF)' }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>{user?.username}</span>
              <Tag color={roleMap[user?.role || 'staff']?.color || 'green'} style={{ margin: 0 }}>
                {roleMap[user?.role || 'staff']?.text || '员工'}
              </Tag>
            </Space>
          </Dropdown>
        </div>
      </nav>

      {/* ════════════════ Body: L2 + L3 ════════════════ */}
      <div className={styles.body}>

        {/* ════════════════ L2 · 侧边栏 ════════════════ */}
        <aside className={`${styles.sidebar} ${sidebarCollapsed ? styles.sidebarCollapsed : ''}`}>
          {sidebarGroups.map((group) => {
            const expanded = isGroupExpanded(group.groupLabel);
            // 过滤权限
            const visibleItems = group.items.filter(item => isRouteAllowed(item.key));
            if (visibleItems.length === 0) return null;

            return (
              <React.Fragment key={group.groupLabel}>
                {/* Group Header */}
                <div
                  className={`${styles.sidebarGroup} ${sidebarCollapsed ? styles.sidebarGroupCollapsed : ''}`}
                  onClick={() => toggleGroup(group.groupLabel)}
                >
                  {!sidebarCollapsed && (
                    <span className={`${styles.groupArrow} ${expanded ? styles.groupArrowOpen : ''}`}>
                      ▶
                    </span>
                  )}
                  {sidebarCollapsed ? '·' : group.groupLabel}
                </div>

                {/* Group Items */}
                {expanded && visibleItems.map((item) => (
                  <Tooltip key={item.key} title={sidebarCollapsed ? item.label : ''} placement="right">
                    <button
                      className={`${styles.sidebarItem} ${
                        location.pathname === item.key ? styles.sidebarItemActive : ''
                      } ${sidebarCollapsed ? styles.sidebarItemCollapsed : ''}`}
                      onClick={() => navigate(item.key)}
                    >
                      <span className={styles.sidebarItemIcon}>{item.icon}</span>
                      {!sidebarCollapsed && item.label}
                    </button>
                  </Tooltip>
                ))}
              </React.Fragment>
            );
          })}

          {/* Sidebar Toggle */}
          <div className={styles.sidebarToggle} onClick={() => setSidebarCollapsed(!sidebarCollapsed)}>
            {sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
        </aside>

        {/* ════════════════ L3 · 内容区 ════════════════ */}
        <main className={styles.content}>
          {/* Breadcrumb */}
          <div className={styles.breadcrumb}>
            <span className={styles.breadcrumbLink} onClick={() => navigate('/')}>
              <HomeOutlined /> 首页
            </span>
            {domainLabel && (
              <>
                <span>/</span>
                <span className={styles.breadcrumbLink} onClick={() => handleDomainClick(activeDomain)}>
                  {domainLabel}
                </span>
              </>
            )}
            {breadcrumbItems().map(item => (
              <React.Fragment key={item.key}>
                <span>/</span>
                <span
                  className={
                    item.key === location.pathname ? styles.breadcrumbCurrent : styles.breadcrumbLink
                  }
                  onClick={() => item.key !== location.pathname && navigate(item.key)}
                >
                  {item.label}
                </span>
              </React.Fragment>
            ))}
          </div>

          {/* Content */}
          <div className={styles.contentInner}>
            <Outlet />
          </div>

          {/* Footer */}
          <div className={styles.footer}>
            屯象OS ©{new Date().getFullYear()} — 餐饮人的好伙伴
          </div>
        </main>
      </div>
    </div>
  );
};

export default MainLayout;
