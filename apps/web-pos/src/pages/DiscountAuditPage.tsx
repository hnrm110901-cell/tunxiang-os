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

const MOCK_ITEMS: AuditItem[] = [
  {
    id: '1', order_id: 'ORD-001', operator_id: 'op1', operator_name: '张收银',
    approver_name: '李经理', action_type: 'discount_pct',
    original_amount: '288.00', final_amount: '180.00', discount_amount: '108.00',
    discount_pct: 37.5, reason: 'VIP客户', created_at: new Date().toISOString(),
  },
  {
    id: '2', order_id: 'ORD-002', operator_id: 'op2', operator_name: '王服务员',
    approver_name: null, action_type: 'return_item',
    original_amount: '68.00', final_amount: '0.00', discount_amount: '68.00',
    discount_pct: 100, reason: '菜品质量问题', created_at: new Date().toISOString(),
  },
  {
    id: '3', order_id: 'ORD-003', operator_id: 'op1', operator_name: '张收银',
    approver_name: null, action_type: 'discount_amt',
    original_amount: '156.00', final_amount: '136.00', discount_amount: '20.00',
    discount_pct: 12.8, reason: null, created_at: new Date().toISOString(),
  },
];

const MOCK_SUMMARY: SummaryData = {
  period: 'today', total_count: 12, total_discount_amount: 486.5, high_risk_count: 3,
  by_operator: [
    { operator_id: 'op1', operator_name: '张收银', high_risk_count: 2, total_discount_amount: '320.00', avg_discount_pct: 38.2, last_action_at: new Date().toISOString() },
    { operator_id: 'op2', operator_name: '王服务员', high_risk_count: 1, total_discount_amount: '166.50', avg_discount_pct: 22.5, last_action_at: new Date().toISOString() },
  ],
};

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function formatAmount(val: string): string {
  return `¥${parseFloat(val).toFixed(2)}`;
}

const STORE_ID = (window as unknown as Record<string, unknown>).STORE_ID as string | undefined;

export function DiscountAuditPage() {
  const [period, setPeriod] = useState<Period>('today');
  const [selectedOperator, setSelectedOperator] = useState('');
  const [selectedAction, setSelectedAction] = useState<ActionType>('');
  const [items, setItems] = useState<AuditItem[]>([]);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(false);
  const [operatorOptions, setOperatorOptions] = useState<OperatorStat[]>([]);

  const isMock = !STORE_ID;

  useEffect(() => {
    if (isMock) {
      setItems(MOCK_ITEMS);
      setSummary(MOCK_SUMMARY);
      setOperatorOptions(MOCK_SUMMARY.by_operator);
      return;
    }
    fetchData();
  }, [period, selectedOperator, selectedAction]);

  async function fetchData() {
    setLoading(true);
    try {
      const tenantId = (window as unknown as Record<string, unknown>).TENANT_ID as string ?? '';
      const headers = { 'X-Tenant-ID': tenantId };

      const params = new URLSearchParams({ period, store_id: STORE_ID ?? '' });
      if (selectedOperator) params.set('operator_id', selectedOperator);
      if (selectedAction) params.set('action_type', selectedAction);

      const [logRes, summaryRes] = await Promise.all([
        fetch(`/api/v1/discount/audit-log?${params}`, { headers }),
        fetch(`/api/v1/discount/audit-log/summary?${params}`, { headers }),
      ]);

      if (logRes.ok) {
        const logJson = await logRes.json();
        setItems(logJson.data?.items ?? []);
      }
      if (summaryRes.ok) {
        const summaryJson = await summaryRes.json();
        setSummary(summaryJson.data);
        setOperatorOptions(summaryJson.data?.by_operator ?? []);
      }
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
          {!loading && filteredItems.length === 0 && (
            <div style={{ color: C.muted, textAlign: 'center', padding: 32, fontSize: 14 }}>
              暂无记录
            </div>
          )}
          {!loading && filteredItems.map(item => (
            <AuditRow key={item.id} item={item} />
          ))}
        </div>

        {/* Mock badge */}
        {isMock && (
          <div style={{ textAlign: 'center', color: C.muted, fontSize: 12, paddingTop: 8 }}>
            演示数据 — 连接门店后显示真实记录
          </div>
        )}
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
