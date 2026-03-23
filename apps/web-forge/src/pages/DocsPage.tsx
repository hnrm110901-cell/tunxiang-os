import React, { useState } from 'react';

const BRAND = '#FF6B2C';

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  path: string;
  description: string;
}

interface Domain {
  key: string;
  label: string;
  description: string;
  endpoints: Endpoint[];
}

const DOMAINS: Domain[] = [
  {
    key: 'gateway', label: 'Gateway 网关', description: '统一入口、认证鉴权、限流路由',
    endpoints: [
      { method: 'GET', path: '/gateway/health', description: '健康检查，返回各域服务状态' },
      { method: 'POST', path: '/gateway/auth/token', description: '获取 Access Token（OAuth2 Client Credentials）' },
      { method: 'POST', path: '/gateway/auth/refresh', description: '刷新 Access Token' },
      { method: 'GET', path: '/gateway/rate-limit/status', description: '查询当前租户的限流配额与用量' },
    ],
  },
  {
    key: 'trade', label: 'Trade 交易', description: '订单全生命周期管理',
    endpoints: [
      { method: 'POST', path: '/trade/v1/orders', description: '创建订单（堂食/外卖/自提）' },
      { method: 'GET', path: '/trade/v1/orders/:id', description: '查询订单详情' },
      { method: 'PATCH', path: '/trade/v1/orders/:id/status', description: '更新订单状态' },
      { method: 'POST', path: '/trade/v1/orders/:id/refund', description: '发起退款' },
      { method: 'GET', path: '/trade/v1/orders', description: '订单列表查询（支持分页与过滤）' },
    ],
  },
  {
    key: 'menu', label: 'Menu 菜单', description: '菜品、分类、规格与定价',
    endpoints: [
      { method: 'GET', path: '/menu/v1/dishes', description: '获取菜品列表' },
      { method: 'POST', path: '/menu/v1/dishes', description: '新增菜品' },
      { method: 'PUT', path: '/menu/v1/dishes/:id', description: '更新菜品信息（名称/价格/规格）' },
      { method: 'GET', path: '/menu/v1/categories', description: '获取菜品分类树' },
      { method: 'PATCH', path: '/menu/v1/dishes/:id/availability', description: '上下架菜品' },
    ],
  },
  {
    key: 'member', label: 'Member 会员', description: '会员体系与营销',
    endpoints: [
      { method: 'POST', path: '/member/v1/users', description: '注册会员' },
      { method: 'GET', path: '/member/v1/users/:id', description: '查询会员详情与积分' },
      { method: 'POST', path: '/member/v1/points/adjust', description: '积分调整（增加/扣减）' },
      { method: 'GET', path: '/member/v1/coupons', description: '可领取优惠券列表' },
      { method: 'POST', path: '/member/v1/coupons/claim', description: '领取优惠券' },
    ],
  },
  {
    key: 'supply', label: 'Supply 供应链', description: '采购、库存与供应商',
    endpoints: [
      { method: 'POST', path: '/supply/v1/purchase-orders', description: '创建采购单' },
      { method: 'GET', path: '/supply/v1/inventory', description: '查询库存（支持按门店/仓库）' },
      { method: 'POST', path: '/supply/v1/inventory/adjust', description: '库存盘点调整' },
      { method: 'GET', path: '/supply/v1/suppliers', description: '供应商列表' },
    ],
  },
  {
    key: 'finance', label: 'Finance 财务', description: '支付、对账与财务报表',
    endpoints: [
      { method: 'POST', path: '/finance/v1/payments', description: '发起支付（微信/支付宝/现金）' },
      { method: 'GET', path: '/finance/v1/payments/:id', description: '查询支付结果' },
      { method: 'GET', path: '/finance/v1/reconciliation/daily', description: '获取日对账单' },
      { method: 'GET', path: '/finance/v1/reports/revenue', description: '营收报表（按日/周/月）' },
    ],
  },
  {
    key: 'org', label: 'Org 组织', description: '门店、员工与权限',
    endpoints: [
      { method: 'GET', path: '/org/v1/stores', description: '门店列表' },
      { method: 'POST', path: '/org/v1/stores', description: '创建门店' },
      { method: 'GET', path: '/org/v1/employees', description: '员工列表' },
      { method: 'POST', path: '/org/v1/roles', description: '创建角色与权限' },
    ],
  },
  {
    key: 'analytics', label: 'Analytics 分析', description: '经营数据与BI',
    endpoints: [
      { method: 'GET', path: '/analytics/v1/dashboard', description: '经营看板数据' },
      { method: 'GET', path: '/analytics/v1/sales/trends', description: '销售趋势（按时间维度）' },
      { method: 'GET', path: '/analytics/v1/dishes/ranking', description: '菜品销量排行' },
      { method: 'POST', path: '/analytics/v1/reports/export', description: '导出自定义报表' },
    ],
  },
  {
    key: 'agent', label: 'Agent 智能体', description: 'AI Agent 接口与动作',
    endpoints: [
      { method: 'POST', path: '/agent/v1/chat', description: '对话式 AI 交互（自然语言 -> 操作）' },
      { method: 'GET', path: '/agent/v1/actions', description: '获取可用 Action 列表（73个）' },
      { method: 'POST', path: '/agent/v1/actions/:id/execute', description: '执行指定 Action' },
      { method: 'GET', path: '/agent/v1/sessions/:id', description: '查询对话会话历史' },
    ],
  },
  {
    key: 'ops', label: 'Ops 运维', description: '系统运维与监控',
    endpoints: [
      { method: 'GET', path: '/ops/v1/logs', description: '查询操作日志' },
      { method: 'GET', path: '/ops/v1/metrics', description: '系统指标（CPU/内存/QPS）' },
      { method: 'POST', path: '/ops/v1/alerts/rules', description: '创建告警规则' },
      { method: 'GET', path: '/ops/v1/deployments', description: '部署记录列表' },
    ],
  },
];

const METHOD_COLORS: Record<string, string> = {
  GET: '#22c55e',
  POST: '#3b82f6',
  PUT: '#f59e0b',
  PATCH: '#a855f7',
  DELETE: '#ef4444',
};

export default function DocsPage() {
  const [activeDomain, setActiveDomain] = useState('gateway');
  const domain = DOMAINS.find((d) => d.key === activeDomain)!;

  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - 56px)' }}>
      {/* Sidebar */}
      <aside
        style={{
          width: 240, background: '#fff', borderRight: '1px solid #e5e7eb',
          padding: '24px 0', flexShrink: 0, overflowY: 'auto',
        }}
      >
        <div style={{ padding: '0 20px', marginBottom: 16 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: 1 }}>
            域服务
          </h3>
        </div>
        {DOMAINS.map((d) => (
          <button
            key={d.key}
            onClick={() => setActiveDomain(d.key)}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '10px 20px', border: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: activeDomain === d.key ? 600 : 400,
              color: activeDomain === d.key ? BRAND : '#4b5563',
              background: activeDomain === d.key ? '#FFF5F0' : 'transparent',
              borderRight: activeDomain === d.key ? `3px solid ${BRAND}` : '3px solid transparent',
            }}
          >
            {d.label}
          </button>
        ))}
      </aside>

      {/* Content */}
      <div style={{ flex: 1, padding: '32px 40px', maxWidth: 900 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 8 }}>{domain.label}</h1>
        <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 32 }}>{domain.description}</p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {domain.endpoints.map((ep, i) => (
            <div
              key={i}
              style={{
                display: 'flex', alignItems: 'center', gap: 14,
                background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10,
                padding: '14px 20px',
              }}
            >
              <span
                style={{
                  display: 'inline-block', width: 60, textAlign: 'center',
                  padding: '3px 0', borderRadius: 4, fontSize: 11, fontWeight: 700,
                  color: '#fff', background: METHOD_COLORS[ep.method] || '#6b7280',
                  fontFamily: 'monospace',
                }}
              >
                {ep.method}
              </span>
              <code style={{ fontSize: 13, color: '#1f2937', fontFamily: '"Fira Code", "SF Mono", Consolas, monospace', minWidth: 280 }}>
                {ep.path}
              </code>
              <span style={{ fontSize: 13, color: '#6b7280' }}>{ep.description}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
