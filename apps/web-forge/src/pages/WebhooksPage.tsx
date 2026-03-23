import React, { useState } from 'react';

const BRAND = '#FF6B2C';

interface EventType {
  event: string;
  description: string;
  domain: string;
  payload: string;
}

const EVENT_TYPES: EventType[] = [
  { event: 'order.created', description: '新订单创建', domain: 'trade', payload: '{ order_id, store_id, type, items[], total, created_at }' },
  { event: 'order.status_changed', description: '订单状态变更', domain: 'trade', payload: '{ order_id, from_status, to_status, changed_at }' },
  { event: 'order.refunded', description: '订单退款完成', domain: 'trade', payload: '{ order_id, refund_id, amount, reason }' },
  { event: 'payment.completed', description: '支付完成', domain: 'finance', payload: '{ payment_id, order_id, amount, method, paid_at }' },
  { event: 'member.registered', description: '新会员注册', domain: 'member', payload: '{ user_id, phone, source, registered_at }' },
  { event: 'member.points_changed', description: '会员积分变动', domain: 'member', payload: '{ user_id, delta, balance, reason }' },
  { event: 'inventory.low_stock', description: '库存低于安全水位', domain: 'supply', payload: '{ item_id, item_name, current_qty, threshold }' },
  { event: 'menu.dish_updated', description: '菜品信息更新', domain: 'menu', payload: '{ dish_id, fields_changed[], updated_by }' },
  { event: 'agent.action_executed', description: 'Agent 执行动作', domain: 'agent', payload: '{ session_id, action_id, action_name, result }' },
  { event: 'ops.alert_triggered', description: '告警触发', domain: 'ops', payload: '{ alert_id, rule_id, severity, message }' },
];

const DOMAIN_COLORS: Record<string, string> = {
  trade: '#3b82f6', finance: '#22c55e', member: '#a855f7',
  supply: '#f59e0b', menu: '#ec4899', agent: '#06b6d4', ops: '#ef4444',
};

export default function WebhooksPage() {
  const [url, setUrl] = useState('https://your-server.com/webhook');
  const [secret, setSecret] = useState('whsec_xxxxxxxxxxxxxxxx');
  const [selectedEvents, setSelectedEvents] = useState<string[]>(['order.created', 'payment.completed']);
  const [saved, setSaved] = useState(false);

  const toggleEvent = (event: string) => {
    setSelectedEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event]
    );
    setSaved(false);
  };

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 8 }}>Webhook 管理</h1>
      <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 40 }}>
        配置 Webhook 端点，实时接收业务事件通知
      </p>

      {/* Config Form */}
      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 28, marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: '#111', marginBottom: 20 }}>端点配置</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6 }}>Webhook URL</label>
            <input
              value={url}
              onChange={(e) => { setUrl(e.target.value); setSaved(false); }}
              style={{
                width: '100%', padding: '10px 14px', border: '1px solid #d1d5db', borderRadius: 8,
                fontSize: 14, fontFamily: 'monospace', outline: 'none',
              }}
            />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6 }}>Signing Secret</label>
            <input
              value={secret}
              onChange={(e) => { setSecret(e.target.value); setSaved(false); }}
              style={{
                width: '100%', padding: '10px 14px', border: '1px solid #d1d5db', borderRadius: 8,
                fontSize: 14, fontFamily: 'monospace', outline: 'none',
              }}
            />
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => setSaved(true)}
            style={{
              padding: '10px 24px', background: BRAND, color: '#fff', border: 'none',
              borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer',
            }}
          >
            保存配置
          </button>
          {saved && <span style={{ fontSize: 13, color: '#22c55e', fontWeight: 600 }}>已保存</span>}
        </div>
      </div>

      {/* Event Types */}
      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#111' }}>事件类型</h2>
          <span style={{ fontSize: 13, color: '#6b7280' }}>
            已订阅 {selectedEvents.length} / {EVENT_TYPES.length} 个事件
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {EVENT_TYPES.map((et) => {
            const isSelected = selectedEvents.includes(et.event);
            return (
              <div
                key={et.event}
                onClick={() => toggleEvent(et.event)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
                  borderRadius: 8, cursor: 'pointer',
                  border: isSelected ? `1px solid ${BRAND}` : '1px solid #e5e7eb',
                  background: isSelected ? '#FFF9F5' : '#fff',
                }}
              >
                <input type="checkbox" checked={isSelected} readOnly style={{ accentColor: BRAND, width: 16, height: 16 }} />
                <span style={{
                  padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                  color: '#fff', background: DOMAIN_COLORS[et.domain] || '#6b7280',
                }}>{et.domain}</span>
                <code style={{ fontSize: 13, fontWeight: 600, color: '#1f2937', fontFamily: 'monospace', minWidth: 200 }}>
                  {et.event}
                </code>
                <span style={{ fontSize: 13, color: '#6b7280', flex: 1 }}>{et.description}</span>
                <code style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {et.payload}
                </code>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
