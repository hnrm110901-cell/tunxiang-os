import React, { useState } from 'react';

const BRAND = '#FF6B2C';

interface ApiKey {
  id: string;
  name: string;
  key: string;
  created: string;
  lastUsed: string;
  status: 'active' | 'revoked';
}

interface WebhookLog {
  id: string;
  event: string;
  status: number;
  timestamp: string;
  duration: string;
}

const INITIAL_KEYS: ApiKey[] = [
  { id: '1', name: '生产环境', key: 'txos_live_a1b2c3d4e5f6g7h8i9j0', created: '2026-01-15', lastUsed: '2026-03-23', status: 'active' },
  { id: '2', name: '测试环境', key: 'txos_test_k1l2m3n4o5p6q7r8s9t0', created: '2026-02-20', lastUsed: '2026-03-22', status: 'active' },
  { id: '3', name: '旧版密钥', key: 'txos_live_z9y8x7w6v5u4t3s2r1q0', created: '2025-08-10', lastUsed: '2025-12-01', status: 'revoked' },
];

const WEBHOOK_LOGS: WebhookLog[] = [
  { id: '1', event: 'order.created', status: 200, timestamp: '2026-03-23 14:32:01', duration: '120ms' },
  { id: '2', event: 'payment.completed', status: 200, timestamp: '2026-03-23 14:31:58', duration: '89ms' },
  { id: '3', event: 'order.status_changed', status: 200, timestamp: '2026-03-23 14:30:45', duration: '105ms' },
  { id: '4', event: 'member.points_changed', status: 500, timestamp: '2026-03-23 14:28:12', duration: '3012ms' },
  { id: '5', event: 'inventory.low_stock', status: 200, timestamp: '2026-03-23 14:25:30', duration: '78ms' },
  { id: '6', event: 'order.created', status: 200, timestamp: '2026-03-23 14:22:15', duration: '132ms' },
  { id: '7', event: 'menu.dish_updated', status: 200, timestamp: '2026-03-23 14:18:44', duration: '95ms' },
  { id: '8', event: 'order.refunded', status: 408, timestamp: '2026-03-23 14:15:20', duration: '5000ms' },
];

const stats = [
  { label: '今日调用量', value: '12,847', change: '+18.3%', up: true },
  { label: '本月调用量', value: '384,210', change: '+12.5%', up: true },
  { label: '今日错误率', value: '0.32%', change: '-0.05%', up: false },
  { label: '平均响应时间', value: '86ms', change: '-12ms', up: false },
];

export default function ConsolePage() {
  const [keys, setKeys] = useState<ApiKey[]>(INITIAL_KEYS);

  const generateKey = () => {
    const rand = Math.random().toString(36).substring(2, 22);
    const newKey: ApiKey = {
      id: String(Date.now()),
      name: `新密钥-${keys.filter(k => k.status === 'active').length + 1}`,
      key: `txos_live_${rand}`,
      created: '2026-03-23',
      lastUsed: '-',
      status: 'active',
    };
    setKeys([newKey, ...keys]);
  };

  const revokeKey = (id: string) => {
    setKeys(keys.map((k) => (k.id === id ? { ...k, status: 'revoked' as const } : k)));
  };

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 8 }}>开发者控制台</h1>
      <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 32 }}>管理应用密钥、监控调用量、查看事件日志</p>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
        {stats.map((s) => (
          <div key={s.label} style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: '20px 24px' }}>
            <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 8 }}>{s.label}</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: '#111', marginBottom: 4 }}>{s.value}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: s.up ? '#22c55e' : '#3b82f6' }}>
              {s.change} vs 昨日
            </div>
          </div>
        ))}
      </div>

      {/* API Keys */}
      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 28, marginBottom: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#111' }}>API Key 管理</h2>
          <button
            onClick={generateKey}
            style={{
              padding: '8px 20px', background: BRAND, color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            + 生成新密钥
          </button>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
              {['名称', '密钥', '创建时间', '最近使用', '状态', '操作'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#9ca3af' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '12px', fontSize: 14, fontWeight: 600, color: '#111' }}>{k.name}</td>
                <td style={{ padding: '12px' }}>
                  <code style={{ fontSize: 12, color: '#6b7280', fontFamily: 'monospace', background: '#f3f4f6', padding: '2px 8px', borderRadius: 4 }}>
                    {k.key.slice(0, 16)}{'...'}
                  </code>
                </td>
                <td style={{ padding: '12px', fontSize: 13, color: '#6b7280' }}>{k.created}</td>
                <td style={{ padding: '12px', fontSize: 13, color: '#6b7280' }}>{k.lastUsed}</td>
                <td style={{ padding: '12px' }}>
                  <span style={{
                    padding: '3px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600,
                    background: k.status === 'active' ? '#dcfce7' : '#fee2e2',
                    color: k.status === 'active' ? '#16a34a' : '#dc2626',
                  }}>
                    {k.status === 'active' ? '活跃' : '已吊销'}
                  </span>
                </td>
                <td style={{ padding: '12px' }}>
                  {k.status === 'active' && (
                    <button
                      onClick={() => revokeKey(k.id)}
                      style={{
                        padding: '4px 12px', background: '#fee2e2', color: '#dc2626', border: 'none',
                        borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                      }}
                    >
                      吊销
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Webhook Event Logs */}
      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 28 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#111', marginBottom: 20 }}>Webhook 事件日志</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
              {['事件', '状态码', '时间', '耗时'].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#9ca3af' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {WEBHOOK_LOGS.map((log) => (
              <tr key={log.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '10px 12px' }}>
                  <code style={{ fontSize: 13, fontFamily: 'monospace', color: '#1f2937' }}>{log.event}</code>
                </td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{
                    padding: '2px 10px', borderRadius: 10, fontSize: 12, fontWeight: 700,
                    background: log.status === 200 ? '#dcfce7' : '#fee2e2',
                    color: log.status === 200 ? '#16a34a' : '#dc2626',
                  }}>{log.status}</span>
                </td>
                <td style={{ padding: '10px 12px', fontSize: 13, color: '#6b7280', fontFamily: 'monospace' }}>{log.timestamp}</td>
                <td style={{ padding: '10px 12px', fontSize: 13, color: '#6b7280' }}>{log.duration}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
