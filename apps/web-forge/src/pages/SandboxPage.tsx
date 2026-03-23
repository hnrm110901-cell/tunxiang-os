import React, { useState } from 'react';

const BRAND = '#FF6B2C';

interface EndpointDef {
  method: string;
  path: string;
  description: string;
  params: { name: string; type: string; required: boolean; example: string }[];
  sampleResponse: string;
}

const API_MAP: Record<string, EndpointDef[]> = {
  gateway: [
    {
      method: 'GET', path: '/gateway/health', description: '健康检查', params: [],
      sampleResponse: JSON.stringify({ status: 'healthy', version: '1.0.0', uptime: '72h 15m', services: { trade: 'up', menu: 'up', member: 'up', supply: 'up', finance: 'up' } }, null, 2),
    },
    {
      method: 'POST', path: '/gateway/auth/token', description: '获取 Access Token',
      params: [
        { name: 'client_id', type: 'string', required: true, example: 'app-001' },
        { name: 'client_secret', type: 'string', required: true, example: 'secret-xxx' },
        { name: 'grant_type', type: 'string', required: true, example: 'client_credentials' },
      ],
      sampleResponse: JSON.stringify({ access_token: 'eyJhbGciOiJSUzI1NiIs...', token_type: 'Bearer', expires_in: 3600 }, null, 2),
    },
  ],
  trade: [
    {
      method: 'POST', path: '/trade/v1/orders', description: '创建订单',
      params: [
        { name: 'store_id', type: 'string', required: true, example: 'store-001' },
        { name: 'type', type: 'string', required: true, example: 'dine_in' },
        { name: 'items', type: 'json', required: true, example: '[{"dish_id":"dish-001","quantity":2}]' },
      ],
      sampleResponse: JSON.stringify({ id: 'order-20260323-001', store_id: 'store-001', type: 'dine_in', status: 'pending', items: [{ dish_id: 'dish-001', name: '宫保鸡丁', quantity: 2, price: 38.0 }], total: 76.0, created_at: '2026-03-23T14:30:00Z' }, null, 2),
    },
    {
      method: 'GET', path: '/trade/v1/orders/:id', description: '查询订单详情',
      params: [
        { name: 'id', type: 'string', required: true, example: 'order-20260323-001' },
      ],
      sampleResponse: JSON.stringify({ id: 'order-20260323-001', store_id: 'store-001', type: 'dine_in', status: 'completed', items: [{ dish_id: 'dish-001', name: '宫保鸡丁', quantity: 2, price: 38.0 }], total: 76.0, paid_at: '2026-03-23T14:35:00Z' }, null, 2),
    },
  ],
  menu: [
    {
      method: 'GET', path: '/menu/v1/dishes', description: '获取菜品列表',
      params: [
        { name: 'store_id', type: 'string', required: true, example: 'store-001' },
        { name: 'category_id', type: 'string', required: false, example: 'cat-hot' },
        { name: 'page', type: 'number', required: false, example: '1' },
        { name: 'page_size', type: 'number', required: false, example: '20' },
      ],
      sampleResponse: JSON.stringify({ items: [{ id: 'dish-001', name: '宫保鸡丁', price: 38.0, category: '热菜', available: true }, { id: 'dish-002', name: '麻婆豆腐', price: 28.0, category: '热菜', available: true }, { id: 'dish-003', name: '拍黄瓜', price: 12.0, category: '凉菜', available: true }], total: 56, page: 1, page_size: 20 }, null, 2),
    },
    {
      method: 'POST', path: '/menu/v1/dishes', description: '新增菜品',
      params: [
        { name: 'name', type: 'string', required: true, example: '酸菜鱼' },
        { name: 'price', type: 'number', required: true, example: '58' },
        { name: 'category_id', type: 'string', required: true, example: 'cat-hot' },
        { name: 'description', type: 'string', required: false, example: '鲜嫩鱼片配酸菜' },
      ],
      sampleResponse: JSON.stringify({ id: 'dish-new-001', name: '酸菜鱼', price: 58.0, category_id: 'cat-hot', description: '鲜嫩鱼片配酸菜', available: true, created_at: '2026-03-23T14:30:00Z' }, null, 2),
    },
  ],
  member: [
    {
      method: 'GET', path: '/member/v1/users/:id', description: '查询会员详情',
      params: [
        { name: 'id', type: 'string', required: true, example: 'user-001' },
      ],
      sampleResponse: JSON.stringify({ id: 'user-001', name: '张三', phone: '138****1234', level: 'gold', points: 2580, total_orders: 47, registered_at: '2025-06-15' }, null, 2),
    },
    {
      method: 'POST', path: '/member/v1/points/adjust', description: '积分调整',
      params: [
        { name: 'user_id', type: 'string', required: true, example: 'user-001' },
        { name: 'delta', type: 'number', required: true, example: '100' },
        { name: 'reason', type: 'string', required: true, example: '消费奖励' },
      ],
      sampleResponse: JSON.stringify({ user_id: 'user-001', delta: 100, balance: 2680, reason: '消费奖励', adjusted_at: '2026-03-23T14:30:00Z' }, null, 2),
    },
  ],
  supply: [
    {
      method: 'GET', path: '/supply/v1/inventory', description: '查询库存',
      params: [
        { name: 'store_id', type: 'string', required: true, example: 'store-001' },
        { name: 'item_name', type: 'string', required: false, example: '鸡胸肉' },
      ],
      sampleResponse: JSON.stringify({ items: [{ id: 'inv-001', name: '鸡胸肉', quantity: 25.5, unit: 'kg', threshold: 10 }, { id: 'inv-002', name: '大米', quantity: 100, unit: 'kg', threshold: 30 }], total: 2 }, null, 2),
    },
  ],
  finance: [
    {
      method: 'GET', path: '/finance/v1/reports/revenue', description: '营收报表',
      params: [
        { name: 'store_id', type: 'string', required: true, example: 'store-001' },
        { name: 'period', type: 'string', required: true, example: 'daily' },
        { name: 'date', type: 'string', required: false, example: '2026-03-23' },
      ],
      sampleResponse: JSON.stringify({ store_id: 'store-001', period: 'daily', date: '2026-03-23', revenue: 12847.5, orders: 156, avg_order_value: 82.36, top_dish: { name: '宫保鸡丁', sales: 42 } }, null, 2),
    },
  ],
  agent: [
    {
      method: 'POST', path: '/agent/v1/chat', description: 'AI 对话交互',
      params: [
        { name: 'session_id', type: 'string', required: false, example: 'sess-001' },
        { name: 'message', type: 'string', required: true, example: '今天营业额怎么样？' },
      ],
      sampleResponse: JSON.stringify({ session_id: 'sess-001', reply: '今日截至目前，门店总营业额为 12,847.50 元，共 156 笔订单，客单价 82.36 元。相比昨日同期增长 18.3%。销量最高的菜品是宫保鸡丁（42份）。', actions_executed: ['analytics.get_dashboard'], confidence: 0.95 }, null, 2),
    },
  ],
};

const DOMAIN_LIST = Object.keys(API_MAP);

const METHOD_COLORS: Record<string, string> = {
  GET: '#22c55e', POST: '#3b82f6', PUT: '#f59e0b', PATCH: '#a855f7', DELETE: '#ef4444',
};

export default function SandboxPage() {
  const [domain, setDomain] = useState('gateway');
  const [endpointIdx, setEndpointIdx] = useState(0);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [response, setResponse] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [latency, setLatency] = useState<number | null>(null);

  const endpoints = API_MAP[domain] || [];
  const currentEndpoint = endpoints[endpointIdx];

  const handleDomainChange = (d: string) => {
    setDomain(d);
    setEndpointIdx(0);
    setParamValues({});
    setResponse(null);
    setStatusCode(null);
    setLatency(null);
  };

  const handleEndpointChange = (idx: number) => {
    setEndpointIdx(idx);
    setParamValues({});
    setResponse(null);
    setStatusCode(null);
    setLatency(null);
  };

  const handleSend = () => {
    setLoading(true);
    setResponse(null);
    const ms = 80 + Math.floor(Math.random() * 150);
    setTimeout(() => {
      setResponse(currentEndpoint.sampleResponse);
      setStatusCode(200);
      setLatency(ms);
      setLoading(false);
    }, 400 + Math.random() * 400);
  };

  const fillExamples = () => {
    const vals: Record<string, string> = {};
    currentEndpoint.params.forEach((p) => {
      vals[p.name] = p.example;
    });
    setParamValues(vals);
  };

  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - 56px)' }}>
      {/* Left: Domain + Endpoint Picker */}
      <aside style={{ width: 260, background: '#fff', borderRight: '1px solid #e5e7eb', padding: '24px 0', flexShrink: 0, overflowY: 'auto' }}>
        <div style={{ padding: '0 20px', marginBottom: 16 }}>
          <h3 style={{ fontSize: 13, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: 1 }}>
            API 调试器
          </h3>
        </div>
        {DOMAIN_LIST.map((d) => (
          <div key={d}>
            <button
              onClick={() => handleDomainChange(d)}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '8px 20px', border: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: domain === d ? 700 : 500,
                color: domain === d ? BRAND : '#374151',
                background: domain === d ? '#FFF5F0' : 'transparent',
              }}
            >
              {d}
            </button>
            {domain === d && (
              <div style={{ padding: '4px 0 8px' }}>
                {endpoints.map((ep, i) => (
                  <button
                    key={i}
                    onClick={() => handleEndpointChange(i)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                      padding: '6px 20px 6px 32px', border: 'none', cursor: 'pointer',
                      fontSize: 12, background: endpointIdx === i ? '#f3f4f6' : 'transparent',
                      color: '#4b5563',
                    }}
                  >
                    <span style={{
                      fontSize: 10, fontWeight: 700, color: METHOD_COLORS[ep.method],
                      fontFamily: 'monospace', minWidth: 32,
                    }}>{ep.method}</span>
                    <span style={{ fontFamily: 'monospace', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ep.path.split('/').slice(-1)[0]}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </aside>

      {/* Right: Request/Response */}
      <div style={{ flex: 1, padding: '28px 36px', overflowY: 'auto' }}>
        {currentEndpoint ? (
          <>
            {/* Endpoint Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              <span style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 13, fontWeight: 700,
                color: '#fff', background: METHOD_COLORS[currentEndpoint.method],
                fontFamily: 'monospace',
              }}>{currentEndpoint.method}</span>
              <code style={{ fontSize: 16, fontWeight: 600, color: '#1f2937', fontFamily: '"Fira Code", monospace' }}>
                {currentEndpoint.path}
              </code>
            </div>
            <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 24 }}>{currentEndpoint.description}</p>

            {/* Parameters */}
            {currentEndpoint.params.length > 0 && (
              <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 24, marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <h3 style={{ fontSize: 15, fontWeight: 700, color: '#111' }}>请求参数</h3>
                  <button
                    onClick={fillExamples}
                    style={{
                      padding: '4px 12px', background: '#f3f4f6', color: '#4b5563', border: 'none',
                      borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 500,
                    }}
                  >
                    填充示例值
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {currentEndpoint.params.map((p) => (
                    <div key={p.name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ width: 140 }}>
                        <code style={{ fontSize: 13, fontWeight: 600, color: '#1f2937', fontFamily: 'monospace' }}>
                          {p.name}
                        </code>
                        {p.required && <span style={{ color: '#ef4444', marginLeft: 2 }}>*</span>}
                        <div style={{ fontSize: 11, color: '#9ca3af' }}>{p.type}</div>
                      </div>
                      <input
                        value={paramValues[p.name] || ''}
                        onChange={(e) => setParamValues({ ...paramValues, [p.name]: e.target.value })}
                        placeholder={p.example}
                        style={{
                          flex: 1, padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8,
                          fontSize: 13, fontFamily: 'monospace', outline: 'none',
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Send Button */}
            <button
              onClick={handleSend}
              disabled={loading}
              style={{
                padding: '10px 32px', background: loading ? '#9ca3af' : BRAND, color: '#fff', border: 'none',
                borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
                marginBottom: 24,
              }}
            >
              {loading ? '发送中...' : '发送请求'}
            </button>

            {/* Response */}
            {response && (
              <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, overflow: 'hidden' }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px',
                  borderBottom: '1px solid #e5e7eb', background: '#f9fafb',
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#111' }}>响应</span>
                  <span style={{
                    padding: '2px 10px', borderRadius: 10, fontSize: 12, fontWeight: 700,
                    background: statusCode === 200 ? '#dcfce7' : '#fee2e2',
                    color: statusCode === 200 ? '#16a34a' : '#dc2626',
                  }}>{statusCode}</span>
                  <span style={{ fontSize: 12, color: '#9ca3af' }}>{latency}ms</span>
                </div>
                <div style={{ padding: '16px 20px', background: '#1e293b', overflowX: 'auto' }}>
                  <pre style={{
                    color: '#e2e8f0', fontSize: 13, lineHeight: 1.6,
                    fontFamily: '"Fira Code", "SF Mono", Consolas, monospace', margin: 0,
                  }}>
                    {response}
                  </pre>
                </div>
              </div>
            )}
          </>
        ) : (
          <div style={{ color: '#9ca3af', fontSize: 15, paddingTop: 60, textAlign: 'center' }}>
            请从左侧选择一个 API 端点
          </div>
        )}
      </div>
    </div>
  );
}
