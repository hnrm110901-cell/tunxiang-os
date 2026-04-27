import {
  LayoutDashboard,
  Boxes,
  GitBranch,
  Workflow,
  Package,
  TestTube2,
  Rocket,
  Sliders,
  Settings2,
  Activity,
  Server,
  Database,
  PlugZap,
  ShieldCheck,
  Cog,
} from 'lucide-react'
import { createElement } from 'react'
import type { MenuItem } from '@/types/menu'

/**
 * 15 项一级菜单 · single source of truth
 * 任何变更只改这里，Sidebar / Router / 面包屑 自动同步
 */
export const MENU: MenuItem[] = [
  {
    key: 'dashboard',
    no: '01',
    label: '工作台',
    icon: createElement(LayoutDashboard, { size: 18 }),
    path: '/dashboard',
    children: [
      { key: 'todo', label: '我的待办', path: '#todo' },
      { key: 'kpi', label: '研发 KPI', path: '#kpi' },
      { key: 'feed', label: '动态信息流', path: '#feed' },
    ],
  },
  {
    key: 'apps',
    no: '02',
    label: '应用中心',
    icon: createElement(Boxes, { size: 18 }),
    path: '/apps',
    children: [
      { key: 'all', label: '全部应用', path: '#all' },
      { key: 'mine', label: '我负责的', path: '#mine' },
      { key: 'topology', label: '拓扑视图', path: '#topology' },
    ],
  },
  {
    key: 'source',
    no: '03',
    label: '代码协作',
    icon: createElement(GitBranch, { size: 18 }),
    path: '/source',
    children: [
      { key: 'repos', label: '仓库列表', path: '#repos' },
      { key: 'mr', label: 'Merge Request', path: '#mr' },
      { key: 'review', label: '代码评审', path: '#review' },
    ],
  },
  {
    key: 'pipeline',
    no: '04',
    label: '流水线',
    icon: createElement(Workflow, { size: 18 }),
    path: '/pipeline',
    children: [
      { key: 'list', label: '流水线列表', path: '#list' },
      { key: 'runs', label: '运行历史', path: '#runs' },
      { key: 'templates', label: '模板库', path: '#templates' },
    ],
  },
  {
    key: 'artifact',
    no: '05',
    label: '制品库',
    icon: createElement(Package, { size: 18 }),
    path: '/artifact',
    children: [
      { key: 'images', label: '镜像仓库', path: '#images' },
      { key: 'packages', label: 'Package', path: '#packages' },
      { key: 'sbom', label: 'SBOM', path: '#sbom' },
    ],
  },
  {
    key: 'test',
    no: '06',
    label: '测试中心',
    icon: createElement(TestTube2, { size: 18 }),
    path: '/test',
    children: [
      { key: 'cases', label: '用例库', path: '#cases' },
      { key: 'reports', label: '测试报告', path: '#reports' },
      { key: 'coverage', label: '覆盖率', path: '#coverage' },
    ],
  },
  {
    key: 'deploy',
    no: '07',
    label: '部署中心',
    icon: createElement(Rocket, { size: 18 }),
    path: '/deploy',
    children: [
      { key: 'envs', label: '环境管理', path: '#envs' },
      { key: 'history', label: '部署历史', path: '#history' },
      { key: 'rollback', label: '回滚', path: '#rollback' },
    ],
  },
  {
    key: 'release',
    no: '08',
    label: '灰度发布',
    icon: createElement(Sliders, { size: 18 }),
    path: '/release',
    children: [
      { key: 'plans', label: '发布计划', path: '#plans' },
      { key: 'canary', label: '灰度策略', path: '#canary' },
      { key: 'flags', label: '特性开关', path: '#flags' },
    ],
  },
  {
    key: 'config',
    no: '09',
    label: '配置中心',
    icon: createElement(Settings2, { size: 18 }),
    path: '/config',
    children: [
      { key: 'items', label: '配置项', path: '#items' },
      { key: 'templates', label: '模板', path: '#templates' },
      { key: 'audit', label: '变更审计', path: '#audit' },
    ],
  },
  {
    key: 'observe',
    no: '10',
    label: '可观测',
    icon: createElement(Activity, { size: 18 }),
    path: '/observe',
    children: [
      { key: 'metrics', label: '指标', path: '#metrics' },
      { key: 'logs', label: '日志', path: '#logs' },
      { key: 'traces', label: '链路', path: '#traces' },
      { key: 'alerts', label: '告警', path: '#alerts' },
    ],
  },
  {
    key: 'edge',
    no: '11',
    label: '边缘门店',
    icon: createElement(Server, { size: 18 }),
    path: '/edge',
    children: [
      { key: 'stations', label: 'Mac mini 节点', path: '#stations' },
      { key: 'sync', label: '同步状态', path: '#sync' },
      { key: 'remote', label: '远程运维', path: '#remote' },
    ],
  },
  {
    key: 'data',
    no: '12',
    label: '数据治理',
    icon: createElement(Database, { size: 18 }),
    path: '/data',
    children: [
      { key: 'lineage', label: '数据血缘', path: '#lineage' },
      { key: 'quality', label: '质量监控', path: '#quality' },
      { key: 'catalog', label: '资产目录', path: '#catalog' },
    ],
  },
  {
    key: 'integration',
    no: '13',
    label: '集成中心',
    icon: createElement(PlugZap, { size: 18 }),
    path: '/integration',
    children: [
      { key: 'webhook', label: 'Webhook', path: '#webhook' },
      { key: 'mcp', label: 'MCP Server', path: '#mcp' },
      { key: 'apis', label: 'OpenAPI', path: '#apis' },
    ],
  },
  {
    key: 'security',
    no: '14',
    label: '安全审计',
    icon: createElement(ShieldCheck, { size: 18 }),
    path: '/security',
    children: [
      { key: 'cve', label: 'CVE 跟踪', path: '#cve' },
      { key: 'access', label: '访问审计', path: '#access' },
      { key: 'secrets', label: '密钥扫描', path: '#secrets' },
    ],
  },
  {
    key: 'system',
    no: '15',
    label: '系统设置',
    icon: createElement(Cog, { size: 18 }),
    path: '/system',
    children: [
      { key: 'users', label: '用户管理', path: '#users' },
      { key: 'roles', label: '角色权限', path: '#roles' },
      { key: 'tenants', label: '租户', path: '#tenants' },
    ],
  },
]
