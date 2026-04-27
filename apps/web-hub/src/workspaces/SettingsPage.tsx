/**
 * Settings 平台底座页面 — 6个子模块
 * Flags / Releases / Billing / Security / Knowledge / Tenancy
 */
import { useState } from 'react';

const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

/* ═══════════════════════════════════════════════════════════════
   类型定义
   ═══════════════════════════════════════════════════════════════ */

type SettingsTab = 'flags' | 'releases' | 'billing' | 'security' | 'knowledge' | 'tenancy';

interface FeatureFlag {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  env: ('dev' | 'staging' | 'prod')[];
  rollout: number;
  group: string;
  updatedAt: string;
  updatedBy: string;
}

interface FlagChangeLog {
  time: string;
  flag: string;
  action: string;
  operator: string;
}

type DeployStatus = 'deployed' | 'deploying' | 'pending' | 'rollback';
type ReleaseEnv = 'dev' | 'test' | 'uat' | 'pilot' | 'prod';

interface AppRelease {
  name: string;
  type: 'frontend' | 'backend';
  currentVersion: string;
  targetVersion: string;
  status: DeployStatus;
  lastDeploy: string;
}

interface BillingCustomer {
  id: string;
  name: string;
  plan: string;
  monthlyFee: number;
  tokenUsage: number;
  aiCost: number;
  expiresAt: string;
}

interface Invoice {
  id: string;
  customer: string;
  amount: number;
  status: 'paid' | 'pending' | 'issued';
}

interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  lastLogin: string;
  status: 'active' | 'inactive' | 'locked';
}

interface Role {
  name: string;
  permissions: number;
  users: number;
}

interface AuditLog {
  time: string;
  operator: string;
  action: string;
  target: string;
  result: 'success' | 'failed';
}

type DocCategory = 'SOP' | 'Postmortem' | '产品文档' | 'FAQ';

interface KnowledgeDoc {
  id: string;
  title: string;
  category: DocCategory;
  updatedAt: string;
  author: string;
  tags: string[];
  summary: string;
  relevance: number;
}

interface Tenant {
  id: string;
  name: string;
  plan: string;
  stores: number;
  status: 'active' | 'inactive' | 'trial';
  region: string;
  createdAt: string;
}

/* ═══════════════════════════════════════════════════════════════
   Tab 定义
   ═══════════════════════════════════════════════════════════════ */

const TABS: { key: SettingsTab; label: string; icon: string }[] = [
  { key: 'flags',     label: 'Flags',     icon: '🚩' },
  { key: 'releases',  label: 'Releases',  icon: '🚀' },
  { key: 'billing',   label: 'Billing',   icon: '💰' },
  { key: 'security',  label: 'Security',  icon: '🔒' },
  { key: 'knowledge', label: 'Knowledge', icon: '📚' },
  { key: 'tenancy',   label: 'Tenancy',   icon: '🏢' },
];

/* ═══════════════════════════════════════════════════════════════
   Mock 数据
   ═══════════════════════════════════════════════════════════════ */

const MOCK_FLAGS: FeatureFlag[] = [
  { id: 'f1', name: 'discount_guardian.enabled', description: '折扣守护Agent全局开关', enabled: true, env: ['dev', 'staging', 'prod'], rollout: 100, group: 'agents', updatedAt: '2026-04-25 14:30', updatedBy: '未了已' },
  { id: 'f2', name: 'smart_menu.ai_recommend', description: 'AI智能菜品推荐', enabled: true, env: ['dev', 'staging'], rollout: 60, group: 'agents', updatedAt: '2026-04-24 10:00', updatedBy: '未了已' },
  { id: 'f3', name: 'trade.multi_currency', description: '多币种支付支持', enabled: false, env: ['dev'], rollout: 0, group: 'trade', updatedAt: '2026-04-20 16:45', updatedBy: '未了已' },
  { id: 'f4', name: 'member.cdp_v2', description: '会员CDP 2.0引擎', enabled: true, env: ['dev', 'staging', 'prod'], rollout: 100, group: 'member', updatedAt: '2026-04-18 09:30', updatedBy: '未了已' },
  { id: 'f5', name: 'org.smart_scheduling', description: '智能排班算法', enabled: true, env: ['dev', 'staging'], rollout: 40, group: 'org', updatedAt: '2026-04-15 11:20', updatedBy: '未了已' },
  { id: 'f6', name: 'growth.referral_program', description: '转介绍裂变活动', enabled: false, env: ['dev'], rollout: 0, group: 'growth', updatedAt: '2026-04-12 15:00', updatedBy: '未了已' },
  { id: 'f7', name: 'edge.offline_ai', description: '边缘离线AI推理', enabled: true, env: ['dev', 'staging', 'prod'], rollout: 80, group: 'edge', updatedAt: '2026-04-10 08:45', updatedBy: '未了已' },
  { id: 'f8', name: 'trade.banquet_v2', description: '宴席管理2.0流程', enabled: true, env: ['dev'], rollout: 20, group: 'trade', updatedAt: '2026-04-08 13:10', updatedBy: '未了已' },
  { id: 'f9', name: 'member.loyalty_points_v3', description: '积分体系3.0', enabled: false, env: ['dev'], rollout: 0, group: 'member', updatedAt: '2026-04-05 17:30', updatedBy: '未了已' },
  { id: 'f10', name: 'agents.inventory_predict', description: '库存预测Agent', enabled: true, env: ['dev', 'staging'], rollout: 50, group: 'agents', updatedAt: '2026-04-03 10:15', updatedBy: '未了已' },
  { id: 'f11', name: 'edge.coreml_whisper', description: 'CoreML语音指令识别', enabled: true, env: ['dev'], rollout: 10, group: 'edge', updatedAt: '2026-04-01 14:00', updatedBy: '未了已' },
  { id: 'f12', name: 'org.performance_review', description: '绩效考核自动化', enabled: false, env: [], rollout: 0, group: 'org', updatedAt: '2026-03-28 09:00', updatedBy: '未了已' },
];

const MOCK_FLAG_CHANGELOG: FlagChangeLog[] = [
  { time: '2026-04-25 14:30', flag: 'discount_guardian.enabled', action: 'rollout 80% -> 100%', operator: '未了已' },
  { time: '2026-04-24 10:00', flag: 'smart_menu.ai_recommend', action: 'rollout 40% -> 60%', operator: '未了已' },
  { time: '2026-04-20 16:45', flag: 'trade.multi_currency', action: '关闭', operator: '未了已' },
  { time: '2026-04-18 09:30', flag: 'member.cdp_v2', action: '推至 prod', operator: '未了已' },
  { time: '2026-04-15 11:20', flag: 'org.smart_scheduling', action: 'rollout 20% -> 40%', operator: '未了已' },
];

const MOCK_RELEASES: AppRelease[] = [
  { name: 'web-pos', type: 'frontend', currentVersion: 'v2.8.1', targetVersion: 'v2.9.0', status: 'pending', lastDeploy: '2026-04-20' },
  { name: 'web-admin', type: 'frontend', currentVersion: 'v2.5.3', targetVersion: 'v2.5.3', status: 'deployed', lastDeploy: '2026-04-22' },
  { name: 'web-kds', type: 'frontend', currentVersion: 'v1.4.0', targetVersion: 'v1.4.0', status: 'deployed', lastDeploy: '2026-04-18' },
  { name: 'web-crew', type: 'frontend', currentVersion: 'v1.2.1', targetVersion: 'v1.3.0', status: 'deploying', lastDeploy: '2026-04-26' },
  { name: 'web-hub', type: 'frontend', currentVersion: 'v2.0.0', targetVersion: 'v2.1.0', status: 'pending', lastDeploy: '2026-04-25' },
  { name: 'web-forge', type: 'frontend', currentVersion: 'v1.0.0', targetVersion: 'v1.0.0', status: 'deployed', lastDeploy: '2026-04-15' },
  { name: 'web-reception', type: 'frontend', currentVersion: 'v1.1.0', targetVersion: 'v1.1.0', status: 'deployed', lastDeploy: '2026-04-10' },
  { name: 'web-tv-menu', type: 'frontend', currentVersion: 'v1.0.2', targetVersion: 'v1.0.2', status: 'deployed', lastDeploy: '2026-04-08' },
  { name: 'h5-self-order', type: 'frontend', currentVersion: 'v1.3.0', targetVersion: 'v1.3.0', status: 'deployed', lastDeploy: '2026-04-12' },
  { name: 'miniapp-customer', type: 'frontend', currentVersion: 'v2.1.0', targetVersion: 'v2.2.0', status: 'pending', lastDeploy: '2026-04-19' },
  { name: 'web-wecom-sidebar', type: 'frontend', currentVersion: 'v1.0.1', targetVersion: 'v1.0.1', status: 'deployed', lastDeploy: '2026-04-05' },
  { name: 'android-pos', type: 'frontend', currentVersion: 'v1.5.0', targetVersion: 'v1.5.0', status: 'deployed', lastDeploy: '2026-04-14' },
  { name: 'ios-shell', type: 'frontend', currentVersion: 'v1.2.0', targetVersion: 'v1.2.0', status: 'deployed', lastDeploy: '2026-04-11' },
  { name: 'windows-pos-shell', type: 'frontend', currentVersion: 'v1.0.0', targetVersion: 'v1.0.0', status: 'deployed', lastDeploy: '2026-03-28' },
  { name: 'android-shell', type: 'frontend', currentVersion: 'v1.1.0', targetVersion: 'v1.2.0', status: 'pending', lastDeploy: '2026-04-16' },
  { name: 'miniapp-customer-v2', type: 'frontend', currentVersion: 'v0.9.0', targetVersion: 'v1.0.0', status: 'deploying', lastDeploy: '2026-04-26' },
  { name: 'gateway', type: 'backend', currentVersion: 'v3.2.1', targetVersion: 'v3.3.0', status: 'pending', lastDeploy: '2026-04-24' },
  { name: 'tx-trade', type: 'backend', currentVersion: 'v4.1.0', targetVersion: 'v4.1.0', status: 'deployed', lastDeploy: '2026-04-25' },
  { name: 'tx-menu', type: 'backend', currentVersion: 'v2.3.0', targetVersion: 'v2.3.0', status: 'deployed', lastDeploy: '2026-04-22' },
  { name: 'tx-member', type: 'backend', currentVersion: 'v3.0.1', targetVersion: 'v3.1.0', status: 'pending', lastDeploy: '2026-04-20' },
  { name: 'tx-growth', type: 'backend', currentVersion: 'v1.5.0', targetVersion: 'v1.5.0', status: 'deployed', lastDeploy: '2026-04-18' },
  { name: 'tx-ops', type: 'backend', currentVersion: 'v2.1.0', targetVersion: 'v2.1.0', status: 'deployed', lastDeploy: '2026-04-16' },
  { name: 'tx-supply', type: 'backend', currentVersion: 'v2.8.0', targetVersion: 'v2.8.0', status: 'deployed', lastDeploy: '2026-04-15' },
  { name: 'tx-finance', type: 'backend', currentVersion: 'v1.9.0', targetVersion: 'v2.0.0', status: 'deploying', lastDeploy: '2026-04-26' },
  { name: 'tx-agent', type: 'backend', currentVersion: 'v2.5.0', targetVersion: 'v2.6.0', status: 'pending', lastDeploy: '2026-04-23' },
  { name: 'tx-analytics', type: 'backend', currentVersion: 'v1.7.0', targetVersion: 'v1.7.0', status: 'deployed', lastDeploy: '2026-04-19' },
  { name: 'tx-brain', type: 'backend', currentVersion: 'v1.3.0', targetVersion: 'v1.3.0', status: 'deployed', lastDeploy: '2026-04-17' },
  { name: 'tx-intel', type: 'backend', currentVersion: 'v1.1.0', targetVersion: 'v1.1.0', status: 'deployed', lastDeploy: '2026-04-14' },
  { name: 'tx-org', type: 'backend', currentVersion: 'v2.2.0', targetVersion: 'v2.2.0', status: 'deployed', lastDeploy: '2026-04-12' },
  { name: 'tx-civic', type: 'backend', currentVersion: 'v1.0.0', targetVersion: 'v1.0.0', status: 'deployed', lastDeploy: '2026-04-10' },
  { name: 'mcp-server', type: 'backend', currentVersion: 'v1.4.0', targetVersion: 'v1.5.0', status: 'rollback', lastDeploy: '2026-04-26' },
  { name: 'mac-station', type: 'backend', currentVersion: 'v1.6.0', targetVersion: 'v1.6.0', status: 'deployed', lastDeploy: '2026-04-21' },
  { name: 'sync-engine', type: 'backend', currentVersion: 'v1.3.0', targetVersion: 'v1.3.0', status: 'deployed', lastDeploy: '2026-04-13' },
];

const MOCK_BILLING_CUSTOMERS: BillingCustomer[] = [
  { id: 'bc1', name: '尚宫厨', plan: 'Pro', monthlyFee: 12800, tokenUsage: 85200, aiCost: 2340, expiresAt: '2027-03-15' },
  { id: 'bc2', name: '最黔线', plan: 'Pro', monthlyFee: 9800, tokenUsage: 62100, aiCost: 1680, expiresAt: '2027-01-20' },
  { id: 'bc3', name: '味蜀吾', plan: 'Standard', monthlyFee: 6800, tokenUsage: 43500, aiCost: 980, expiresAt: '2026-12-10' },
  { id: 'bc4', name: '渝是乎', plan: 'Standard', monthlyFee: 6800, tokenUsage: 38900, aiCost: 860, expiresAt: '2026-11-28' },
  { id: 'bc5', name: '蜀大侠', plan: 'Enterprise', monthlyFee: 28800, tokenUsage: 156000, aiCost: 5200, expiresAt: '2027-06-01' },
  { id: 'bc6', name: '大龙燚', plan: 'Pro', monthlyFee: 12800, tokenUsage: 78300, aiCost: 2100, expiresAt: '2027-02-15' },
  { id: 'bc7', name: '小龙坎', plan: 'Enterprise', monthlyFee: 38800, tokenUsage: 210000, aiCost: 7800, expiresAt: '2027-08-20' },
  { id: 'bc8', name: '谭鸭血', plan: 'Standard', monthlyFee: 6800, tokenUsage: 35200, aiCost: 780, expiresAt: '2026-10-30' },
  { id: 'bc9', name: '楠火锅', plan: 'Pro', monthlyFee: 9800, tokenUsage: 55800, aiCost: 1420, expiresAt: '2027-04-10' },
  { id: 'bc10', name: '巴奴', plan: 'Enterprise', monthlyFee: 48800, tokenUsage: 280000, aiCost: 9600, expiresAt: '2027-12-01' },
];

const MOCK_INVOICES: Invoice[] = [
  { id: 'INV-2026-0401', customer: '尚宫厨', amount: 15140, status: 'paid' },
  { id: 'INV-2026-0402', customer: '最黔线', amount: 11480, status: 'paid' },
  { id: 'INV-2026-0403', customer: '味蜀吾', amount: 7780, status: 'issued' },
  { id: 'INV-2026-0404', customer: '蜀大侠', amount: 34000, status: 'pending' },
  { id: 'INV-2026-0405', customer: '小龙坎', amount: 46600, status: 'pending' },
  { id: 'INV-2026-0406', customer: '巴奴', amount: 58400, status: 'issued' },
];

const MOCK_USERS: User[] = [
  { id: 'u1', name: '未了已', email: 'admin@tunxiang.tech', role: 'platform-admin', lastLogin: '2026-04-26 08:30', status: 'active' },
  { id: 'u2', name: '张三', email: 'zhangsan@tunxiang.tech', role: 'csm', lastLogin: '2026-04-25 17:45', status: 'active' },
  { id: 'u3', name: '李四', email: 'lisi@tunxiang.tech', role: 'sre', lastLogin: '2026-04-26 07:00', status: 'active' },
  { id: 'u4', name: '王五', email: 'wangwu@tunxiang.tech', role: 'engineer', lastLogin: '2026-04-24 16:20', status: 'active' },
  { id: 'u5', name: '赵六', email: 'zhaoliu@tunxiang.tech', role: 'engineer', lastLogin: '2026-04-23 14:10', status: 'active' },
  { id: 'u6', name: '孙七', email: 'sunqi@tunxiang.tech', role: 'viewer', lastLogin: '2026-04-20 09:30', status: 'inactive' },
  { id: 'u7', name: '周八', email: 'zhouba@tunxiang.tech', role: 'csm', lastLogin: '2026-04-22 11:00', status: 'active' },
  { id: 'u8', name: '吴九', email: 'wujiu@tunxiang.tech', role: 'viewer', lastLogin: '2026-03-15 10:00', status: 'locked' },
];

const MOCK_ROLES: Role[] = [
  { name: 'platform-admin', permissions: 128, users: 1 },
  { name: 'csm', permissions: 64, users: 2 },
  { name: 'sre', permissions: 96, users: 1 },
  { name: 'engineer', permissions: 72, users: 2 },
  { name: 'viewer', permissions: 12, users: 2 },
];

const MOCK_AUDIT_LOGS: AuditLog[] = Array.from({ length: 20 }, (_, i) => {
  const actions = ['登录系统', '修改Feature Flag', '部署服务', '创建用户', '修改角色权限', '查看审计日志', '修改租户配置', '导出账单', '更新知识库', '重置密码'];
  const operators = ['未了已', '张三', '李四', '王五', '赵六'];
  const targets = ['discount_guardian', 'tx-trade v4.1.0', '用户赵六', 'csm角色', '尚宫厨租户', '系统配置', '账单模块', 'SOP文档', '网关配置', 'IP白名单'];
  const h = 8 + Math.floor(i * 0.5);
  const m = (i * 7) % 60;
  return {
    time: `2026-04-${String(26 - Math.floor(i / 4)).padStart(2, '0')} ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`,
    operator: operators[i % operators.length],
    action: actions[i % actions.length],
    target: targets[i % targets.length],
    result: (i === 5 || i === 13) ? 'failed' as const : 'success' as const,
  };
});

const MOCK_KNOWLEDGE: KnowledgeDoc[] = [
  { id: 'k1', title: '新客户Onboarding标准流程', category: 'SOP', updatedAt: '2026-04-20', author: '未了已', tags: ['客户成功', '流程'], summary: '从合同签署到首月回访的全流程标准化操作规范，包含每个节点的时间要求和回退方案。', relevance: 98 },
  { id: 'k2', title: '数据迁移五段式操作手册', category: 'SOP', updatedAt: '2026-04-18', author: '未了已', tags: ['迁移', '数据'], summary: '映射-历史回放-增量追平-双跑对账-切流五个阶段的详细操作指南。', relevance: 95 },
  { id: 'k3', title: '2026-04-15 mcp-server OOM事件', category: 'Postmortem', updatedAt: '2026-04-16', author: '李四', tags: ['SRE', '事件'], summary: 'mcp-server因内存泄漏导致OOM，影响3个租户15分钟。根因为未关闭的数据库连接。', relevance: 90 },
  { id: 'k4', title: '2026-03-28 TX-MAC-007离线事件', category: 'Postmortem', updatedAt: '2026-03-29', author: '李四', tags: ['边缘', '事件'], summary: '尚宫厨门店Mac mini因UPS电池耗尽导致非正常关机，本地PG数据完整性校验通过。', relevance: 88 },
  { id: 'k5', title: '屯象OS产品架构总览', category: '产品文档', updatedAt: '2026-04-25', author: '未了已', tags: ['架构', '产品'], summary: '五层架构、六大实体、九大Agent的产品体系说明文档。', relevance: 92 },
  { id: 'k6', title: 'Agent决策留痕规范', category: '产品文档', updatedAt: '2026-04-22', author: '未了已', tags: ['Agent', '规范'], summary: '所有Agent决策必须记录输入上下文、推理过程、三条硬约束校验结果。', relevance: 85 },
  { id: 'k7', title: 'RLS多租户隔离实施指南', category: 'SOP', updatedAt: '2026-04-10', author: '王五', tags: ['安全', '数据库'], summary: '所有表必须包含tenant_id，RLS策略使用app.tenant_id，禁止NULL绕过。', relevance: 96 },
  { id: 'k8', title: '常见POS收银问题FAQ', category: 'FAQ', updatedAt: '2026-04-23', author: '张三', tags: ['POS', '收银'], summary: '收银员日常操作中常见的30个问题及解决方案汇总。', relevance: 82 },
  { id: 'k9', title: '门店网络故障排查指南', category: 'FAQ', updatedAt: '2026-04-15', author: '李四', tags: ['网络', '运维'], summary: 'Mac mini与安卓POS之间的WiFi连接问题诊断和修复步骤。', relevance: 80 },
  { id: 'k10', title: '2026-03-10 tx-trade支付超时事件', category: 'Postmortem', updatedAt: '2026-03-11', author: '李四', tags: ['支付', '事件'], summary: '高峰期tx-trade数据库连接池耗尽导致支付接口超时，影响5家门店。', relevance: 87 },
  { id: 'k11', title: '供应链库存盘点SOP', category: 'SOP', updatedAt: '2026-04-08', author: '张三', tags: ['供应链', '库存'], summary: '月度库存盘点的标准流程，包含差异处理和审批机制。', relevance: 78 },
  { id: 'k12', title: '会员CDP数据模型说明', category: '产品文档', updatedAt: '2026-04-12', author: '未了已', tags: ['会员', 'CDP'], summary: 'Golden ID体系、RFM分层、全渠道画像的数据模型设计。', relevance: 83 },
  { id: 'k13', title: '微信支付V3对接指南', category: 'SOP', updatedAt: '2026-04-05', author: '王五', tags: ['支付', '微信'], summary: 'JSAPI支付、小程序支付、退款对账的完整对接流程。', relevance: 86 },
  { id: 'k14', title: '如何添加新的Feature Flag', category: 'FAQ', updatedAt: '2026-04-01', author: '赵六', tags: ['开发', '配置'], summary: '在flags/目录下添加新特性开关的步骤和命名规范。', relevance: 75 },
  { id: 'k15', title: '边缘CoreML模型更新流程', category: '产品文档', updatedAt: '2026-03-28', author: '未了已', tags: ['AI', '边缘'], summary: '从模型训练到部署至Mac mini的CoreML模型更新全流程。', relevance: 81 },
];

const MOCK_TENANTS: Tenant[] = [
  { id: 'T-001', name: '尚宫厨', plan: 'Pro', stores: 8, status: 'active', region: '湖南', createdAt: '2025-08-15' },
  { id: 'T-002', name: '最黔线', plan: 'Pro', stores: 5, status: 'active', region: '贵州', createdAt: '2025-09-20' },
  { id: 'T-003', name: '味蜀吾', plan: 'Standard', stores: 12, status: 'active', region: '四川', createdAt: '2025-10-10' },
  { id: 'T-004', name: '渝是乎', plan: 'Standard', stores: 6, status: 'active', region: '湖南', createdAt: '2025-11-05' },
  { id: 'T-005', name: '蜀大侠', plan: 'Enterprise', stores: 45, status: 'active', region: '四川', createdAt: '2025-06-01' },
  { id: 'T-006', name: '大龙燚', plan: 'Pro', stores: 18, status: 'active', region: '四川', createdAt: '2025-07-20' },
  { id: 'T-007', name: '小龙坎', plan: 'Enterprise', stores: 120, status: 'active', region: '重庆', createdAt: '2025-05-15' },
  { id: 'T-008', name: '谭鸭血', plan: 'Standard', stores: 15, status: 'active', region: '四川', createdAt: '2025-12-01' },
  { id: 'T-009', name: '楠火锅', plan: 'Pro', stores: 10, status: 'active', region: '湖南', createdAt: '2026-01-10' },
  { id: 'T-010', name: '巴奴', plan: 'Enterprise', stores: 85, status: 'active', region: '河南', createdAt: '2025-04-01' },
];

/* ═══════════════════════════════════════════════════════════════
   公共小组件
   ═══════════════════════════════════════════════════════════════ */

const STATUS_DEPLOY_STYLE: Record<DeployStatus, { bg: string; color: string; label: string }> = {
  deployed:  { bg: C.green + '22', color: C.green,  label: '已部署' },
  deploying: { bg: C.yellow + '22', color: C.yellow, label: '部署中' },
  pending:   { bg: C.text3 + '22', color: C.text3,  label: '待部署' },
  rollback:  { bg: C.red + '22', color: C.red,    label: '回滚' },
};

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: color + '22', color,
    }}>
      {text}
    </span>
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div
      onClick={() => onChange(!value)}
      style={{
        width: 36, height: 20, borderRadius: 10, cursor: 'pointer',
        background: value ? C.green : C.surface3,
        border: `1px solid ${value ? C.green : C.border2}`,
        position: 'relative', transition: 'all 0.2s', flexShrink: 0,
      }}
    >
      <div style={{
        width: 14, height: 14, borderRadius: '50%',
        background: '#fff', position: 'absolute', top: 2,
        left: value ? 19 : 2, transition: 'left 0.2s',
      }} />
    </div>
  );
}

function Slider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
      <input
        type="range" min={0} max={100} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ flex: 1, accentColor: C.orange, height: 4, cursor: 'pointer' }}
      />
      <span style={{ fontSize: 11, color: C.text2, minWidth: 32, textAlign: 'right' }}>{value}%</span>
    </div>
  );
}

function SectionTitle({ children, extra }: { children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 16 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: C.text, display: 'flex', alignItems: 'baseline', gap: 10 }}>
        {children}
      </div>
      {extra}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 1: Flags
   ═══════════════════════════════════════════════════════════════ */

function FlagsPanel() {
  const [flags, setFlags] = useState<FeatureFlag[]>(MOCK_FLAGS);

  const groups = Array.from(new Set(flags.map(f => f.group)));

  const toggleFlag = (id: string) => {
    setFlags(prev => prev.map(f => f.id === id ? { ...f, enabled: !f.enabled } : f));
  };

  const updateRollout = (id: string, rollout: number) => {
    setFlags(prev => prev.map(f => f.id === id ? { ...f, rollout } : f));
  };

  const envBadge = (env: string) => {
    const colors: Record<string, string> = { dev: C.blue, staging: C.yellow, prod: C.green };
    return <Badge key={env} text={env} color={colors[env] || C.text3} />;
  };

  return (
    <div>
      <SectionTitle extra={<span style={{ fontSize: 13, color: C.text3 }}>{flags.length} flags</span>}>
        Feature Flags
      </SectionTitle>

      {groups.map(group => (
        <div key={group} style={{ marginBottom: 24 }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: C.orange, textTransform: 'uppercase',
            marginBottom: 8, letterSpacing: 1,
          }}>
            {group}
          </div>
          <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
            {flags.filter(f => f.group === group).map((flag, i, arr) => (
              <div key={flag.id} style={{
                padding: '12px 16px',
                borderBottom: i < arr.length - 1 ? `1px solid ${C.border}` : 'none',
                display: 'grid',
                gridTemplateColumns: '1fr auto auto auto auto',
                alignItems: 'center',
                gap: 16,
                background: C.surface,
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: 'monospace' }}>
                    {flag.name}
                  </div>
                  <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>{flag.description}</div>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {flag.env.length > 0 ? flag.env.map(envBadge) : <span style={{ fontSize: 11, color: C.text3 }}>--</span>}
                </div>
                <Slider value={flag.rollout} onChange={v => updateRollout(flag.id, v)} />
                <Toggle value={flag.enabled} onChange={() => toggleFlag(flag.id)} />
                <div style={{ fontSize: 10, color: C.text3, whiteSpace: 'nowrap', textAlign: 'right', minWidth: 80 }}>
                  <div>{flag.updatedAt}</div>
                  <div>{flag.updatedBy}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* 变更日志 */}
      <div style={{ marginTop: 32 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>灰度变更日志</div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '140px 1fr 1fr 100px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
          }}>
            <span>时间</span><span>Flag</span><span>操作</span><span>操作人</span>
          </div>
          {MOCK_FLAG_CHANGELOG.map((log, i) => (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '140px 1fr 1fr 100px',
              padding: '8px 14px', fontSize: 12, color: C.text2,
              borderTop: `1px solid ${C.border}`,
            }}>
              <span style={{ color: C.text3 }}>{log.time}</span>
              <span style={{ fontFamily: 'monospace', color: C.text }}>{log.flag}</span>
              <span>{log.action}</span>
              <span>{log.operator}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 2: Releases
   ═══════════════════════════════════════════════════════════════ */

function ReleasesPanel() {
  const [env, setEnv] = useState<ReleaseEnv>('prod');
  const envs: ReleaseEnv[] = ['dev', 'test', 'uat', 'pilot', 'prod'];

  const frontendApps = MOCK_RELEASES.filter(r => r.type === 'frontend');
  const backendApps = MOCK_RELEASES.filter(r => r.type === 'backend');

  const renderRow = (app: AppRelease, i: number, arr: AppRelease[]) => {
    const st = STATUS_DEPLOY_STYLE[app.status];
    return (
      <div key={app.name} style={{
        display: 'grid', gridTemplateColumns: '180px 100px 100px 90px 110px',
        padding: '10px 14px', fontSize: 12, color: C.text2,
        borderBottom: i < arr.length - 1 ? `1px solid ${C.border}` : 'none',
        alignItems: 'center',
      }}>
        <span style={{ fontWeight: 600, color: C.text, fontFamily: 'monospace' }}>{app.name}</span>
        <span>{app.currentVersion}</span>
        <span style={{ color: app.currentVersion !== app.targetVersion ? C.orange : C.text3 }}>
          {app.targetVersion}
        </span>
        <span style={{
          padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
          background: st.bg, color: st.color, display: 'inline-block', textAlign: 'center',
          animation: app.status === 'deploying' ? 'pulse 1.5s infinite' : 'none',
        }}>
          {st.label}
        </span>
        <span style={{ color: C.text3 }}>{app.lastDeploy}</span>
      </div>
    );
  };

  const tableHeader = (
    <div style={{
      display: 'grid', gridTemplateColumns: '180px 100px 100px 90px 110px',
      padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
    }}>
      <span>应用</span><span>当前版本</span><span>目标版本</span><span>状态</span><span>最近部署</span>
    </div>
  );

  return (
    <div>
      <SectionTitle extra={<span style={{ fontSize: 13, color: C.text3 }}>GitOps 5 环境</span>}>
        Releases
      </SectionTitle>

      {/* 环境 chips */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {envs.map(e => (
          <button key={e} onClick={() => setEnv(e)} style={{
            padding: '6px 16px', borderRadius: 6, fontSize: 13,
            fontWeight: env === e ? 600 : 400,
            color: env === e ? C.orange : C.text2,
            background: env === e ? 'rgba(255,107,44,0.12)' : C.surface2,
            border: `1px solid ${env === e ? C.orange + '44' : C.border}`,
            cursor: 'pointer', textTransform: 'uppercase',
          }}>
            {e}
          </button>
        ))}
      </div>

      {/* Frontend */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text2, marginBottom: 8 }}>
          Frontend ({frontendApps.length})
        </div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {tableHeader}
          {frontendApps.map((a, i, arr) => renderRow(a, i, arr))}
        </div>
      </div>

      {/* Backend */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text2, marginBottom: 8 }}>
          Backend ({backendApps.length})
        </div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          {tableHeader}
          {backendApps.map((a, i, arr) => renderRow(a, i, arr))}
        </div>
      </div>

      {/* pulse animation */}
      <style>{`@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.5 } }`}</style>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 3: Billing
   ═══════════════════════════════════════════════════════════════ */

function BillingPanel() {
  const totalRevenue = MOCK_BILLING_CUSTOMERS.reduce((s, c) => s + c.monthlyFee, 0);
  const totalAI = MOCK_BILLING_CUSTOMERS.reduce((s, c) => s + c.aiCost, 0);
  const haasRevenue = 18000; // mock HaaS
  const saasRevenue = totalRevenue - totalAI - haasRevenue;

  const barData = [
    { label: 'HaaS', value: haasRevenue, color: C.blue },
    { label: 'SaaS', value: saasRevenue, color: C.green },
    { label: 'AI增值', value: totalAI, color: C.purple },
  ];
  const maxBar = Math.max(...barData.map(b => b.value));

  const invoiceStatusStyle: Record<string, { color: string; label: string }> = {
    paid: { color: C.green, label: '已付' },
    issued: { color: C.yellow, label: '已开' },
    pending: { color: C.text3, label: '待开' },
  };

  return (
    <div>
      <SectionTitle>Billing</SectionTitle>

      {/* 月度概览 */}
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 20, marginBottom: 32,
      }}>
        <div style={{
          background: C.surface, borderRadius: 10, padding: 20,
          border: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column',
          justifyContent: 'center',
        }}>
          <div style={{ fontSize: 12, color: C.text3, marginBottom: 4 }}>月度总收入</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: C.orange }}>
            {'\u00A5'}{(totalRevenue / 100).toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: C.text3, marginTop: 4 }}>2026年4月</div>
        </div>
        <div style={{
          background: C.surface, borderRadius: 10, padding: 20,
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontSize: 12, color: C.text3, marginBottom: 12 }}>收入拆解</div>
          {barData.map(b => (
            <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span style={{ fontSize: 12, color: C.text2, width: 50 }}>{b.label}</span>
              <div style={{ flex: 1, height: 18, background: C.surface3, borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: `${(b.value / maxBar) * 100}%`, height: '100%',
                  background: b.color, borderRadius: 4, transition: 'width 0.3s',
                }} />
              </div>
              <span style={{ fontSize: 12, color: C.text, fontWeight: 600, minWidth: 70, textAlign: 'right' }}>
                {'\u00A5'}{(b.value / 100).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 客户账单表 */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>客户账单</div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '100px 80px 90px 90px 80px 100px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
          }}>
            <span>客户</span><span>套餐</span><span>月费</span><span>Token用量</span><span>AI费用</span><span>到期日</span>
          </div>
          {MOCK_BILLING_CUSTOMERS.map((c, i) => (
            <div key={c.id} style={{
              display: 'grid', gridTemplateColumns: '100px 80px 90px 90px 80px 100px',
              padding: '10px 14px', fontSize: 12, color: C.text2,
              borderTop: `1px solid ${C.border}`,
            }}>
              <span style={{ fontWeight: 600, color: C.text }}>{c.name}</span>
              <Badge text={c.plan} color={c.plan === 'Enterprise' ? C.purple : c.plan === 'Pro' ? C.blue : C.text3} />
              <span>{'\u00A5'}{(c.monthlyFee / 100).toLocaleString()}</span>
              <span>{(c.tokenUsage / 1000).toFixed(1)}K</span>
              <span>{'\u00A5'}{(c.aiCost / 100).toFixed(0)}</span>
              <span style={{ color: C.text3 }}>{c.expiresAt}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 发票列表 */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>发票列表</div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '150px 100px 100px 80px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
          }}>
            <span>编号</span><span>客户</span><span>金额</span><span>状态</span>
          </div>
          {MOCK_INVOICES.map((inv, i) => {
            const st = invoiceStatusStyle[inv.status];
            return (
              <div key={inv.id} style={{
                display: 'grid', gridTemplateColumns: '150px 100px 100px 80px',
                padding: '10px 14px', fontSize: 12, color: C.text2,
                borderTop: `1px solid ${C.border}`,
              }}>
                <span style={{ fontFamily: 'monospace', color: C.text }}>{inv.id}</span>
                <span>{inv.customer}</span>
                <span>{'\u00A5'}{(inv.amount / 100).toLocaleString()}</span>
                <Badge text={st.label} color={st.color} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 4: Security
   ═══════════════════════════════════════════════════════════════ */

function SecurityPanel() {
  const userStatusStyle: Record<string, { color: string; label: string }> = {
    active: { color: C.green, label: '活跃' },
    inactive: { color: C.text3, label: '未活跃' },
    locked: { color: C.red, label: '已锁定' },
  };

  return (
    <div>
      <SectionTitle>Security</SectionTitle>

      {/* 组织管理 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>组织管理</div>
        <div style={{
          background: C.surface, borderRadius: 10, padding: 16,
          border: `1px solid ${C.border}`, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16,
        }}>
          <div>
            <div style={{ fontSize: 11, color: C.text3 }}>组织名称</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginTop: 4 }}>屯象科技</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.text3 }}>管理员</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginTop: 4 }}>未了已</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: C.text3 }}>创建时间</div>
            <div style={{ fontSize: 14, color: C.text2, marginTop: 4 }}>2025-04-01</div>
          </div>
        </div>
      </div>

      {/* 用户列表 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>
          用户列表 ({MOCK_USERS.length})
        </div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '80px 180px 110px 140px 70px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
          }}>
            <span>姓名</span><span>邮箱</span><span>角色</span><span>最后登录</span><span>状态</span>
          </div>
          {MOCK_USERS.map(u => {
            const st = userStatusStyle[u.status];
            return (
              <div key={u.id} style={{
                display: 'grid', gridTemplateColumns: '80px 180px 110px 140px 70px',
                padding: '10px 14px', fontSize: 12, color: C.text2,
                borderTop: `1px solid ${C.border}`,
              }}>
                <span style={{ fontWeight: 600, color: C.text }}>{u.name}</span>
                <span style={{ fontFamily: 'monospace' }}>{u.email}</span>
                <Badge text={u.role} color={u.role === 'platform-admin' ? C.orange : u.role === 'sre' ? C.red : C.blue} />
                <span style={{ color: C.text3 }}>{u.lastLogin}</span>
                <Badge text={st.label} color={st.color} />
              </div>
            );
          })}
        </div>
      </div>

      {/* 角色管理 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>角色管理</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {MOCK_ROLES.map(role => (
            <div key={role.name} style={{
              background: C.surface, borderRadius: 8, padding: 14,
              border: `1px solid ${C.border}`, textAlign: 'center',
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 6 }}>{role.name}</div>
              <div style={{ fontSize: 11, color: C.text3 }}>{role.permissions} 权限</div>
              <div style={{ fontSize: 11, color: C.text3 }}>{role.users} 用户</div>
            </div>
          ))}
        </div>
      </div>

      {/* 审计日志 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>审计日志（最近20条）</div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden', maxHeight: 400, overflowY: 'auto' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '140px 70px 120px 120px 60px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
            position: 'sticky', top: 0,
          }}>
            <span>时间</span><span>操作人</span><span>操作</span><span>对象</span><span>结果</span>
          </div>
          {MOCK_AUDIT_LOGS.map((log, i) => (
            <div key={i} style={{
              display: 'grid', gridTemplateColumns: '140px 70px 120px 120px 60px',
              padding: '8px 14px', fontSize: 12, color: C.text2,
              borderTop: `1px solid ${C.border}`,
            }}>
              <span style={{ color: C.text3 }}>{log.time}</span>
              <span style={{ color: C.text }}>{log.operator}</span>
              <span>{log.action}</span>
              <span>{log.target}</span>
              <Badge text={log.result === 'success' ? '成功' : '失败'} color={log.result === 'success' ? C.green : C.red} />
            </div>
          ))}
        </div>
      </div>

      {/* IP 白名单 */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>IP 白名单</div>
        <div style={{
          background: C.surface, borderRadius: 8, padding: 16,
          border: `1px solid ${C.border}`,
        }}>
          {['10.0.0.0/8', '172.16.0.0/12', '192.168.1.0/24', '114.251.43.88/32'].map(ip => (
            <div key={ip} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '6px 0', borderBottom: `1px solid ${C.border}`,
            }}>
              <span style={{ fontFamily: 'monospace', fontSize: 13, color: C.text }}>{ip}</span>
              <span style={{ fontSize: 11, color: C.text3 }}>允许</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 5: Knowledge
   ═══════════════════════════════════════════════════════════════ */

function KnowledgePanel() {
  const [docFilter, setDocFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const categories: { key: string; label: string }[] = [
    { key: 'all', label: '全部' },
    { key: 'SOP', label: 'SOP' },
    { key: 'Postmortem', label: 'Postmortem' },
    { key: '产品文档', label: '产品文档' },
    { key: 'FAQ', label: 'FAQ' },
  ];

  const catColors: Record<string, string> = {
    SOP: C.blue, Postmortem: C.red, '产品文档': C.purple, FAQ: C.green,
  };

  let docs = MOCK_KNOWLEDGE;
  if (docFilter !== 'all') docs = docs.filter(d => d.category === docFilter);
  if (search) {
    const q = search.toLowerCase();
    docs = docs.filter(d =>
      d.title.toLowerCase().includes(q) ||
      d.summary.toLowerCase().includes(q) ||
      d.tags.some(t => t.toLowerCase().includes(q))
    );
  }

  return (
    <div>
      <SectionTitle extra={<span style={{ fontSize: 13, color: C.text3 }}>RAG-powered</span>}>
        Knowledge Base
      </SectionTitle>

      {/* 搜索框 */}
      <div style={{ marginBottom: 16 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索文档（模拟RAG搜索）..."
          style={{
            width: '100%', padding: '10px 14px', borderRadius: 8,
            background: C.surface, border: `1px solid ${C.border}`,
            color: C.text, fontSize: 13, outline: 'none',
            boxSizing: 'border-box',
          }}
          onFocus={e => { e.currentTarget.style.borderColor = C.orange; }}
          onBlur={e => { e.currentTarget.style.borderColor = C.border; }}
        />
      </div>

      {/* 分类 tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {categories.map(cat => (
          <button key={cat.key} onClick={() => setDocFilter(cat.key)} style={{
            padding: '6px 14px', borderRadius: 6, fontSize: 13,
            fontWeight: docFilter === cat.key ? 600 : 400,
            color: docFilter === cat.key ? C.orange : C.text2,
            background: docFilter === cat.key ? 'rgba(255,107,44,0.12)' : C.surface2,
            border: `1px solid ${docFilter === cat.key ? C.orange + '44' : C.border}`,
            cursor: 'pointer',
          }}>
            {cat.label}
          </button>
        ))}
      </div>

      {/* 文档列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {docs.map(doc => (
          <div key={doc.id} style={{
            background: C.surface, borderRadius: 10, padding: 16,
            border: `1px solid ${C.border}`, cursor: 'pointer',
            transition: 'border-color 0.15s',
          }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = C.border2; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = C.border; }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: C.text }}>{doc.title}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
                <Badge text={doc.category} color={catColors[doc.category] || C.text3} />
                <span style={{
                  fontSize: 11, fontWeight: 700, color: C.orange,
                  padding: '2px 6px', borderRadius: 4, background: C.orange + '18',
                }}>
                  {doc.relevance}%
                </span>
              </div>
            </div>
            <div style={{ fontSize: 12, color: C.text2, lineHeight: 1.5, marginBottom: 8 }}>{doc.summary}</div>
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: C.text3 }}>
              <span>{doc.author}</span>
              <span>{doc.updatedAt}</span>
              <span style={{ display: 'flex', gap: 4 }}>
                {doc.tags.map(t => (
                  <span key={t} style={{ padding: '1px 6px', borderRadius: 3, background: C.surface3, fontSize: 10 }}>
                    {t}
                  </span>
                ))}
              </span>
            </div>
          </div>
        ))}
        {docs.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: C.text3, fontSize: 13 }}>
            未找到匹配的文档
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   子模块 6: Tenancy
   ═══════════════════════════════════════════════════════════════ */

function TenancyPanel() {
  const totalTenants = MOCK_TENANTS.length;
  const activeTenants = MOCK_TENANTS.filter(t => t.status === 'active').length;
  const totalStores = MOCK_TENANTS.reduce((s, t) => s + t.stores, 0);
  const activeStoresApprox = Math.round(totalStores * 0.82);

  const statusStyle: Record<string, { color: string; label: string }> = {
    active: { color: C.green, label: '活跃' },
    inactive: { color: C.text3, label: '停用' },
    trial: { color: C.yellow, label: '试用' },
  };

  // 区域分布
  const regionMap: Record<string, number> = {};
  MOCK_TENANTS.forEach(t => { regionMap[t.region] = (regionMap[t.region] || 0) + t.stores; });
  const regionData = Object.entries(regionMap).sort((a, b) => b[1] - a[1]);
  const maxRegion = Math.max(...regionData.map(r => r[1]));

  const metricCards = [
    { label: '租户总数', value: totalTenants, color: C.blue },
    { label: '活跃租户', value: activeTenants, color: C.green },
    { label: '门店总数', value: totalStores, color: C.orange },
    { label: '今日活跃门店', value: activeStoresApprox, color: C.yellow },
  ];

  return (
    <div>
      <SectionTitle>Tenancy</SectionTitle>

      {/* 概览指标 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 28 }}>
        {metricCards.map(m => (
          <div key={m.label} style={{
            background: C.surface, borderRadius: 10, padding: 16,
            border: `1px solid ${C.border}`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 11, color: C.text3, marginBottom: 6 }}>{m.label}</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: m.color }}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* 租户列表 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>租户列表</div>
        <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '70px 80px 90px 70px 60px 60px 100px',
            padding: '8px 14px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
          }}>
            <span>ID</span><span>名称</span><span>套餐</span><span>门店数</span><span>状态</span><span>区域</span><span>创建时间</span>
          </div>
          {MOCK_TENANTS.map(t => {
            const st = statusStyle[t.status];
            return (
              <div key={t.id} style={{
                display: 'grid', gridTemplateColumns: '70px 80px 90px 70px 60px 60px 100px',
                padding: '10px 14px', fontSize: 12, color: C.text2,
                borderTop: `1px solid ${C.border}`,
              }}>
                <span style={{ fontFamily: 'monospace', color: C.text3 }}>{t.id}</span>
                <span style={{ fontWeight: 600, color: C.text }}>{t.name}</span>
                <Badge text={t.plan} color={t.plan === 'Enterprise' ? C.purple : t.plan === 'Pro' ? C.blue : C.text3} />
                <span style={{ fontWeight: 600 }}>{t.stores}</span>
                <Badge text={st.label} color={st.color} />
                <span>{t.region}</span>
                <span style={{ color: C.text3 }}>{t.createdAt}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 区域分布 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>区域门店分布</div>
        <div style={{
          background: C.surface, borderRadius: 10, padding: 20,
          border: `1px solid ${C.border}`,
        }}>
          {regionData.map(([region, count]) => (
            <div key={region} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 12, color: C.text2, width: 40 }}>{region}</span>
              <div style={{ flex: 1, height: 22, background: C.surface3, borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  width: `${(count / maxRegion) * 100}%`, height: '100%',
                  background: C.orange, borderRadius: 4, transition: 'width 0.3s',
                  display: 'flex', alignItems: 'center', justifyContent: 'flex-end', paddingRight: 8,
                }}>
                  <span style={{ fontSize: 11, color: '#fff', fontWeight: 600 }}>{count}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 数据字典 */}
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>数据字典管理</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { key: '业态', items: ['大店Pro', '小店Lite', '宴席', '外卖'] },
            { key: '区域', items: ['湖南', '四川', '重庆', '贵州', '河南'] },
            { key: '品牌', items: MOCK_TENANTS.map(t => t.name).slice(0, 5) },
            { key: '套餐', items: ['Standard', 'Pro', 'Enterprise'] },
          ].map(dict => (
            <div key={dict.key} style={{
              background: C.surface, borderRadius: 8, padding: 14,
              border: `1px solid ${C.border}`,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 8 }}>{dict.key}</div>
              {dict.items.map(item => (
                <div key={item} style={{
                  fontSize: 12, color: C.text2, padding: '3px 0',
                  borderBottom: `1px solid ${C.border}`,
                }}>
                  {item}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   主页面
   ═══════════════════════════════════════════════════════════════ */

const PANEL_MAP: Record<SettingsTab, () => JSX.Element> = {
  flags: FlagsPanel,
  releases: ReleasesPanel,
  billing: BillingPanel,
  security: SecurityPanel,
  knowledge: KnowledgePanel,
  tenancy: TenancyPanel,
};

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => {
    // 从 URL hash 解析初始 tab
    const hash = window.location.hash.replace('#', '') as SettingsTab;
    return PANEL_MAP[hash] ? hash : 'flags';
  });

  const PanelComponent = PANEL_MAP[activeTab];

  return (
    <div style={{
      display: 'flex', height: '100%', color: C.text,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      {/* 左侧导航 */}
      <div style={{
        width: 180, minWidth: 180, background: C.surface,
        borderRight: `1px solid ${C.border}`,
        padding: '20px 0', display: 'flex', flexDirection: 'column', gap: 2,
      }}>
        <div style={{
          fontSize: 14, fontWeight: 700, color: C.text, padding: '0 16px 12px',
          borderBottom: `1px solid ${C.border}`, marginBottom: 8,
        }}>
          Settings
        </div>
        {TABS.map(tab => {
          const active = activeTab === tab.key;
          return (
            <div
              key={tab.key}
              onClick={() => {
                setActiveTab(tab.key);
                window.location.hash = tab.key;
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '10px 16px', cursor: 'pointer',
                borderLeft: `3px solid ${active ? C.orange : 'transparent'}`,
                background: active ? 'rgba(255,107,44,0.08)' : 'transparent',
                color: active ? C.text : C.text2,
                fontWeight: active ? 600 : 400,
                fontSize: 13, transition: 'all 0.15s',
              }}
              onMouseEnter={e => {
                if (!active) e.currentTarget.style.background = C.surface2;
              }}
              onMouseLeave={e => {
                if (!active) e.currentTarget.style.background = 'transparent';
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </div>
          );
        })}
      </div>

      {/* 右侧内容区 */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        <PanelComponent />
      </div>
    </div>
  );
}
