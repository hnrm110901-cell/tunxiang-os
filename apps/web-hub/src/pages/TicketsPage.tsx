/**
 * 工单系统（GET /api/v1/hub/tickets）
 */
import { useEffect, useMemo, useState } from 'react';
import { hubGet, type HubListResult } from '../api/hubApi';

const s = {
  page: { color: '#E0E0E0' } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: '#FFFFFF', marginBottom: 20 } as React.CSSProperties,
  cards: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  card: {
    flex: '1 1 200px', background: '#0D2129', borderRadius: 10, padding: '18px 20px',
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  cardLabel: { fontSize: 12, color: '#6B8A97', marginBottom: 6 } as React.CSSProperties,
  cardValue: { fontSize: 28, fontWeight: 700, color: '#FF6B2C' } as React.CSSProperties,
  toolbar: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 } as React.CSSProperties,
  btn: {
    background: '#FF6B2C', color: '#FFF', border: 'none', borderRadius: 6,
    padding: '8px 18px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
  } as React.CSSProperties,
  btnSec: {
    background: 'transparent', color: '#FF6B2C', border: '1px solid #FF6B2C', borderRadius: 6,
    padding: '6px 14px', fontSize: 12, cursor: 'pointer', marginLeft: 6,
  } as React.CSSProperties,
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 } as React.CSSProperties,
  th: {
    textAlign: 'left' as const, padding: '10px 12px', borderBottom: '1px solid #1A3540',
    color: '#6B8A97', fontWeight: 600, fontSize: 12,
  } as React.CSSProperties,
  td: { padding: '10px 12px', borderBottom: '1px solid #112A33' } as React.CSSProperties,
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color,
  }) as React.CSSProperties,
  err: { color: '#EF4444', fontSize: 13, marginBottom: 12 } as React.CSSProperties,
};

type HubTicket = {
  id: string;
  merchant: string;
  title: string;
  priority: string;
  status: string;
  created: string;
  assignee: string;
};

const priorityLabel = (p: string): string => {
  const x = p.toLowerCase();
  if (x === 'high') return 'P1';
  if (x === 'medium') return 'P2';
  if (x === 'low') return 'P3';
  if (x === 'p0') return 'P0';
  if (x === 'p1') return 'P1';
  if (x === 'p2') return 'P2';
  return p.toUpperCase();
};

const priorityColor: Record<string, string> = {
  P0: '#EF4444', P1: '#F59E0B', P2: '#3B82F6', P3: '#6B8A97',
};

const statusZh = (st: string): string => {
  const x = st.toLowerCase();
  if (x === 'open') return '待分配';
  if (x === 'in_progress') return '处理中';
  if (x === 'closed' || x === 'done') return '已完成';
  return st;
};

const statusColor: Record<string, string> = {
  处理中: '#F59E0B',
  待分配: '#3B82F6',
  已完成: '#22C55E',
};

export function TicketsPage() {
  const [items, setItems] = useState<HubTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hubGet<HubListResult<HubTicket>>('/tickets')
      .then((d) => {
        if (!cancelled) {
          setItems(d.items || []);
          setErr(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setErr(e.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const open = useMemo(
    () => items.filter((t) => statusZh(t.status) !== '已完成').length,
    [items],
  );

  const p0 = useMemo(
    () => items.filter((t) => priorityLabel(t.priority) === 'P0').length,
    [items],
  );

  return (
    <div style={s.page}>
      <div style={s.title}>工单中心</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>工单总数</div><div style={s.cardValue}>{items.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>未完成</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{open}</div></div>
        <div style={s.card}><div style={s.cardLabel}>P0工单</div><div style={{ ...s.cardValue, color: '#EF4444' }}>{p0}</div></div>
        <div style={s.card}><div style={s.cardLabel}>SLA达标率</div><div style={{ ...s.cardValue, color: '#22C55E' }}>—</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>所有工单</div>
        <button type="button" style={s.btn}>+ 新建工单</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>工单号</th>
            <th style={s.th}>商户</th>
            <th style={s.th}>门店</th>
            <th style={s.th}>标题</th>
            <th style={s.th}>优先级</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>负责人</th>
            <th style={s.th}>创建时间</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => {
            const pl = priorityLabel(t.priority);
            const sz = statusZh(t.status);
            return (
              <tr key={t.id}>
                <td style={s.td}>{t.id}</td>
                <td style={s.td}>{t.merchant}</td>
                <td style={s.td}>—</td>
                <td style={s.td}>{t.title}</td>
                <td style={s.td}><span style={s.badge(priorityColor[pl] || '#6B8A97')}>{pl}</span></td>
                <td style={s.td}><span style={{ color: statusColor[sz] || '#6B8A97', fontWeight: 600 }}>{sz}</span></td>
                <td style={s.td}>{t.assignee}</td>
                <td style={s.td}>{t.created}</td>
                <td style={s.td}>
                  <button type="button" style={s.btnSec}>处理</button>
                  <button type="button" style={s.btnSec}>查看详情</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
