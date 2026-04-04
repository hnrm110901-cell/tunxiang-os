import { useEffect, useState } from 'react';

const C = {
  bg: '#0B0B0B', card: '#111', border: '#1A1A1A',
  text: '#E0E0E0', muted: '#555', primary: '#FF6B35',
  danger: '#FF3B30', warning: '#FF9F0A', success: '#30D158',
};

type Period = 'today' | 'week' | 'month';

type ActionType =
  | 'discount_pct' | 'discount_amt' | 'gift_item'
  | 'return_item' | 'free_order' | 'price_override' | 'coupon' | '';

interface AuditItem {
  id: string;
  order_id: string;
  operator_id: string;
  operator_name: string;
  approver_name: string | null;
  action_type: string;
  original_amount: string;
  final_amount: string;
  discount_amount: string;
  discount_pct: number;
  reason: string | null;
  created_at: string | null;
}

interface SummaryData {
  period: Period;
  total_count: number;
  total_discount_amount: number;
  high_risk_count: number;
  by_operator: OperatorStat[];
}

interface OperatorStat {
  operator_id: string;
  operator_name: string;
  high_risk_count: number;
  total_discount_amount: string;
  avg_discount_pct: number;
  last_action_at: string | null;
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  discount_pct: '折扣%',
  discount_amt: '折扣额',
  gift_item: '赠品',
  return_item: '退菜',
  free_order: '整单免单',
  price_override: '改价',
  coupon: '优惠券',
};

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function formatAmount(val: string): string {
  return `¥${parseFloat(val).toFixed(2)}`;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '';

export function DiscountAuditPage() {
  const [period, setPeriod] = useState<Period>('today');
  const [selectedOperator, setSelectedOperator] = useState('');
  const [selectedAction, setSelectedAction] = useState<ActionType>('');
  const [items, setItems] = useState<AuditItem[]>([]);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [operatorOptions, setOperatorOptions] = useState<OperatorStat[]>([]);

  useEffect(() => {
    fetchData();
  }, [period, selectedOperator, selectedAction]);

  async function fetchData() {
    setLoading(true);
    setError(null);
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      };

      const params = new URLSearchParams({ period, store_id: STORE_ID });
      if (selectedOperator) params.set('operator_id', selectedOperator);
      if (selectedAction) params.set('action_type', selectedAction);

      const [logRes, summaryRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/discount/audit-log?${params}`, { headers }),
        fetch(`${API_BASE}/api/v1/discount/audit-log/summary?${params}`, { headers }),
      ]);

      if (!logRes.ok) throw new Error(`审计记录加载失败 (${logRes.status})`);
      if (!summaryRes.ok) throw new Error(`汇总数据加载失败 (${summaryRes.status})`);

      const logJson = await logRes.json();
      if (!logJson.ok) throw new Error(logJson.error?.message || '审计记录接口异常');
      setItems(logJson.data?.items ?? []);

      const summaryJson = await summaryRes.json();
      if (!summaryJson.ok) throw new Error(summaryJson.error?.message || '汇总接口异常');
      setSummary(summaryJson.data);
      setOperatorOptions(summaryJson.data?.by_operator ?? []);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '加载折扣审计数据失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  const filteredItems = items.filter(item => {
    if (selectedOperator && item.operator_id !== selectedOperator) return false;
    if (selectedAction && item.action_type !== selectedAction) return false;
    return true;
  });

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, fontFamily: 'system-ui, sans-serif' }}>
      {/* Header */}
      <div style={{
        background: C.card, borderBottom: `1px solid ${C.border}`,
        padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 18, fontWeight: 600 }}>折扣审计</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['today', 'week', 'month'] as Period[]).map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                minWidth: 64, minHeight: 36, padding: '6px 14px',
                borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 14,
                background: period === p ? C.primary : '#222',
                color: period === p ? '#fff' : C.text,
              }}
            >
              {p === 'today' ? '今日' : p === 'week' ? '本周' : '本月'}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Summary cards */}
        {summary && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <SummaryCard label="总折扣次数" value={String(summary.total_count)} />
            <SummaryCard label="总折扣金额" value={`¥${summary.total_discount_amount.toFixed(2)}`} />
            <SummaryCard label="高风险次数" value={String(summary.high_risk_count)} danger />
          </div>
        )}

        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <select
            value={selectedOperator}
            onChange={e => setSelectedOperator(e.target.value)}
            style={selectStyle}
          >
            <option value="">全部员工</option>
            {operatorOptions.map(op => (
              <option key={op.operator_id} value={op.operator_id}>{op.operator_name}</option>
            ))}
          </select>
          <select
            value={selectedAction}
            onChange={e => setSelectedAction(e.target.value as ActionType)}
            style={selectStyle}
          >
            <option value="">全部类型</option>
            {Object.entries(ACTION_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>

        {/* Records list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {loading && (
            <div style={{ color: C.muted, textAlign: 'center', padding: 32, fontSize: 14 }}>
              加载中...
            </div>
          )}
          {error && !loading && (
            <div style={{ textAlign: 'center', padding: 32 }}>
              <div style={{ color: C.danger, fontSize: 14 }}>{error}</div>
              <button
                onClick={() => fetchData()}
                style={{
                  marginTop: 12, padding: '6px 16px', background: C.primary, color: '#fff',
                  border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13,
                }}
              >
                重试
              </button>
            </div>
          )}
          {!loading && !error && filteredItems.length === 0 && (
            <div style={{ color: C.muted, textAlign: 'center', padding: 32, fontSize: 14 }}>
              暂无记录
            </div>
          )}
          {!loading && !error && filteredItems.map(item => (
            <AuditRow key={item.id} item={item} />
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
      padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      <span style={{ fontSize: 12, color: C.muted }}>{label}</span>
      <span style={{ fontSize: 22, fontWeight: 700, color: danger ? C.danger : C.text }}>
        {value}
      </span>
    </div>
  );
}

function AuditRow({ item }: { item: AuditItem }) {
  const isHighRisk = item.discount_pct >= 30;

  return (
    <div style={{
      background: isHighRisk ? '#1A0E00' : C.card,
      border: `1px solid ${isHighRisk ? C.warning : C.border}`,
      borderRadius: 10, padding: '12px 16px',
      display: 'grid',
      gridTemplateColumns: '60px 1fr 80px 100px 80px 80px 80px',
      alignItems: 'center', gap: 8,
      minHeight: 52,
    }}>
      <span style={{ fontSize: 13, color: C.muted }}>{formatTime(item.created_at)}</span>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{item.operator_name}</div>
        <div style={{ fontSize: 12, color: C.muted }}>
          {item.order_id.slice(-8)}
          {item.reason ? ` · ${item.reason}` : ''}
        </div>
      </div>
      <span style={{
        fontSize: 12, padding: '2px 8px', borderRadius: 6,
        background: '#222', color: C.primary, textAlign: 'center',
      }}>
        {ACTION_TYPE_LABELS[item.action_type] ?? item.action_type}
      </span>
      <span style={{ fontSize: 13, color: C.muted, textAlign: 'center' }}>
        {formatAmount(item.original_amount)} → {formatAmount(item.final_amount)}
      </span>
      <span style={{ fontSize: 14, fontWeight: 600, color: C.danger, textAlign: 'right' }}>
        -{formatAmount(item.discount_amount)}
      </span>
      <span style={{
        fontSize: 13,
        color: isHighRisk ? C.warning : C.muted,
        textAlign: 'center',
      }}>
        {item.discount_pct}%
      </span>
      <span style={{ fontSize: 12, color: C.muted, textAlign: 'right' }}>
        {item.approver_name ?? '—'}
      </span>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  background: '#1A1A1A', border: `1px solid ${C.border}`, borderRadius: 8,
  color: C.text, fontSize: 14, padding: '10px 14px',
  minHeight: 44, cursor: 'pointer', outline: 'none',
};
