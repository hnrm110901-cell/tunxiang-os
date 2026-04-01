/**
 * E. Agent Studio / Ops 智能体中台 — 路由清单 + 导航配置
 */
import type { RouteNode, NavItem } from './types';

export const AGENT_ROUTES: RouteNode[] = [
  // ── E1 Agent 目录 ──
  { path: '/agent/catalog',                      name: 'Agent列表',   nameEn: 'AgentCatalog',   moduleId: 'E1', priority: true },
  { path: '/agent/catalog/:agentId',             name: 'Agent详情',   nameEn: 'AgentDetail',    moduleId: 'E1', hideInNav: true },
  { path: '/agent/catalog/:agentId/versions',    name: 'Agent版本',   nameEn: 'AgentVersions',  moduleId: 'E1', hideInNav: true },
  { path: '/agent/releases',                     name: '发布记录',    nameEn: 'Releases',       moduleId: 'E1' },

  // ── E2 Prompt / Policy ──
  { path: '/agent/prompts',             name: 'Prompt列表',  nameEn: 'PromptList',    moduleId: 'E2' },
  { path: '/agent/prompts/:promptId',   name: 'Prompt编辑',  nameEn: 'PromptEditor',  moduleId: 'E2', hideInNav: true },
  { path: '/agent/policies',            name: '策略规则',     nameEn: 'Policies',      moduleId: 'E2' },
  { path: '/agent/templates',           name: '输出模版',     nameEn: 'Templates',     moduleId: 'E2' },

  // ── E3 Tool / MCP ──
  { path: '/agent/tools',                       name: '工具列表',     nameEn: 'ToolList',         moduleId: 'E3' },
  { path: '/agent/tools/:toolId',               name: '工具详情',     nameEn: 'ToolDetail',       moduleId: 'E3', hideInNav: true },
  { path: '/agent/tools/:toolId/test',          name: '工具测试',     nameEn: 'ToolTest',         moduleId: 'E3', hideInNav: true },
  { path: '/agent/tools/:toolId/permissions',   name: '权限绑定',     nameEn: 'ToolPermissions',  moduleId: 'E3', hideInNav: true },

  // ── E4 Workflow 编排 ──
  { path: '/agent/workflows',                              name: '工作流列表',   nameEn: 'WorkflowList',     moduleId: 'E4', priority: true },
  { path: '/agent/workflows/new',                          name: '新建工作流',   nameEn: 'NewWorkflow',      moduleId: 'E4', hideInNav: true },
  { path: '/agent/workflows/:workflowId',                  name: '工作流详情',   nameEn: 'WorkflowDetail',   moduleId: 'E4', hideInNav: true },
  { path: '/agent/workflows/:workflowId/debug',            name: '节点调试',     nameEn: 'WorkflowDebug',    moduleId: 'E4', hideInNav: true },
  { path: '/agent/workflows/:workflowId/approval-chain',   name: '审批链配置',   nameEn: 'ApprovalChain',    moduleId: 'E4', hideInNav: true },

  // ── E5 Knowledge / Memory ──
  { path: '/agent/knowledge',              name: '知识库列表', nameEn: 'KnowledgeList',   moduleId: 'E5' },
  { path: '/agent/knowledge/:kbId',        name: '文档详情',   nameEn: 'KnowledgeDetail', moduleId: 'E5', hideInNav: true },
  { path: '/agent/memory',                 name: '记忆策略',   nameEn: 'MemoryPolicy',    moduleId: 'E5' },
  { path: '/agent/sessions/:sessionId',    name: '会话回放',   nameEn: 'SessionReplay',   moduleId: 'E5', hideInNav: true },

  // ── E6 监控与评测 ──
  { path: '/agent/observability/conversations', name: '对话日志',   nameEn: 'ConversationLog', moduleId: 'E6', priority: true },
  { path: '/agent/observability/tools',         name: '工具调用',   nameEn: 'ToolCallLog',     moduleId: 'E6' },
  { path: '/agent/observability/success-rate',  name: '成功率分析', nameEn: 'SuccessRate',     moduleId: 'E6' },
  { path: '/agent/observability/cost',          name: '成本分析',   nameEn: 'CostAnalysis',    moduleId: 'E6' },
  { path: '/agent/observability/error-cases',   name: '错例库',     nameEn: 'ErrorCases',      moduleId: 'E6' },
];

export const AGENT_NAV: NavItem[] = [
  { key: 'catalog', label: 'Agent', icon: 'robot', children: [
    { key: 'list',     label: 'Agent列表', path: '/agent/catalog' },
    { key: 'releases', label: '发布记录',  path: '/agent/releases' },
  ]},
  { key: 'prompts', label: 'Prompt/Policy', icon: 'file-text', children: [
    { key: 'prompts',   label: 'Prompt列表', path: '/agent/prompts' },
    { key: 'policies',  label: '策略规则',   path: '/agent/policies' },
    { key: 'templates', label: '输出模版',   path: '/agent/templates' },
  ]},
  { key: 'tools', label: 'Tools', icon: 'tool', children: [
    { key: 'list', label: '工具列表', path: '/agent/tools' },
  ]},
  { key: 'workflows', label: 'Workflow', icon: 'branch', children: [
    { key: 'list', label: '工作流列表', path: '/agent/workflows' },
  ]},
  { key: 'knowledge', label: 'Knowledge/Memory', icon: 'book', children: [
    { key: 'kb',     label: '知识库', path: '/agent/knowledge' },
    { key: 'memory', label: '记忆策略', path: '/agent/memory' },
  ]},
  { key: 'observability', label: '监控评测', icon: 'monitor', children: [
    { key: 'conversations', label: '对话日志',   path: '/agent/observability/conversations' },
    { key: 'tools',         label: '工具调用',   path: '/agent/observability/tools' },
    { key: 'success',       label: '成功率',     path: '/agent/observability/success-rate' },
    { key: 'cost',          label: '成本分析',   path: '/agent/observability/cost' },
    { key: 'errors',        label: '错例库',     path: '/agent/observability/error-cases' },
  ]},
];
