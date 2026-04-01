/**
 * D. Growth 会员增长台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const GROWTH_ROUTES: RouteNode[] = [
  // ── D1 会员资产 ──
  { path: '/growth/overview',              name: '会员总览',   nameEn: 'MemberOverview', moduleId: 'D1', aiEntry: ['review'] },
  { path: '/growth/members',               name: '会员列表',   nameEn: 'MemberList',     moduleId: 'D1' },
  { path: '/growth/members/:memberId',     name: '会员详情',   nameEn: 'MemberDetail',   moduleId: 'D1', hideInNav: true },
  { path: '/growth/tags',                  name: '标签管理',   nameEn: 'TagManagement',  moduleId: 'D1' },
  { path: '/growth/levels',                name: '等级体系',   nameEn: 'LevelSystem',    moduleId: 'D1' },

  // ── D2 人群与分层 ──
  { path: '/growth/segments',              name: '人群列表',   nameEn: 'SegmentList',    moduleId: 'D2', aiEntry: ['task_input'] },
  { path: '/growth/segments/new',          name: '人群圈选',   nameEn: 'NewSegment',     moduleId: 'D2', hideInNav: true },
  { path: '/growth/segments/:segmentId',   name: '人群详情',   nameEn: 'SegmentDetail',  moduleId: 'D2', hideInNav: true },

  // ── D3 活动与券 ──
  { path: '/growth/campaigns',                    name: '活动列表',   nameEn: 'CampaignList',    moduleId: 'D3' },
  { path: '/growth/campaigns/new',                name: '新建活动',   nameEn: 'NewCampaign',     moduleId: 'D3', hideInNav: true },
  { path: '/growth/campaigns/:campaignId',        name: '活动详情',   nameEn: 'CampaignDetail',  moduleId: 'D3', hideInNav: true },
  { path: '/growth/coupons',                      name: '券模板',     nameEn: 'CouponTemplates', moduleId: 'D3' },
  { path: '/growth/coupon-templates',             name: '发券任务',   nameEn: 'CouponTasks',     moduleId: 'D3' },
  { path: '/growth/redemptions',                  name: '核销分析',   nameEn: 'Redemptions',     moduleId: 'D3', aiEntry: ['review'] },

  // ── D4 触达编排 ──
  { path: '/growth/reach/assistant',    name: 'AI触达助手',  nameEn: 'ReachAssistant',  moduleId: 'D4', aiEntry: ['task_input'] },
  { path: '/growth/reach/tasks',        name: '触达任务',    nameEn: 'ReachTasks',      moduleId: 'D4' },
  { path: '/growth/reach/copy',         name: '文案生成',    nameEn: 'CopyGeneration',  moduleId: 'D4', aiEntry: ['suggestion'] },
  { path: '/growth/reach/logs',         name: '发送记录',    nameEn: 'SendLogs',        moduleId: 'D4' },
  { path: '/growth/reach/attribution',  name: '归因分析',    nameEn: 'Attribution',     moduleId: 'D4', aiEntry: ['review'] },

  // ── D5 会员 Agent 中心 ──
  { path: '/growth/agent/growth',       name: '会员增长Agent', nameEn: 'GrowthAgent',       moduleId: 'D5', aiEntry: ['task_input'] },
  { path: '/growth/agent/reactivation', name: '沉睡召回Agent', nameEn: 'ReactivationAgent', moduleId: 'D5', aiEntry: ['task_input'] },
  { path: '/growth/agent/repurchase',   name: '复购Agent',     nameEn: 'RepurchaseAgent',   moduleId: 'D5', aiEntry: ['suggestion'] },
];

export const GROWTH_NAV: NavItem[] = [
  { key: 'assets', label: '会员资产', icon: 'user', children: [
    { key: 'overview', label: '会员总览', path: '/growth/overview' },
    { key: 'list',     label: '会员列表', path: '/growth/members' },
    { key: 'tags',     label: '标签管理', path: '/growth/tags' },
    { key: 'levels',   label: '等级体系', path: '/growth/levels' },
  ]},
  { key: 'segments', label: '人群', icon: 'partition', children: [
    { key: 'list', label: '人群列表', path: '/growth/segments' },
  ]},
  { key: 'campaigns', label: '活动与券', icon: 'gift', children: [
    { key: 'list',     label: '活动列表', path: '/growth/campaigns' },
    { key: 'coupons',  label: '券模板',   path: '/growth/coupons' },
    { key: 'tasks',    label: '发券任务', path: '/growth/coupon-templates' },
    { key: 'redeem',   label: '核销分析', path: '/growth/redemptions' },
  ]},
  { key: 'reach', label: '触达', icon: 'send', children: [
    { key: 'assistant',   label: 'AI触达助手', path: '/growth/reach/assistant' },
    { key: 'tasks',       label: '触达任务',   path: '/growth/reach/tasks' },
    { key: 'copy',        label: '文案生成',   path: '/growth/reach/copy' },
    { key: 'logs',        label: '发送记录',   path: '/growth/reach/logs' },
    { key: 'attribution', label: '归因分析',   path: '/growth/reach/attribution' },
  ]},
  { key: 'agent', label: 'Agent', icon: 'robot', children: [
    { key: 'growth',       label: '会员增长Agent', path: '/growth/agent/growth' },
    { key: 'reactivation', label: '沉睡召回Agent', path: '/growth/agent/reactivation' },
    { key: 'repurchase',   label: '复购Agent',     path: '/growth/agent/repurchase' },
  ]},
];
