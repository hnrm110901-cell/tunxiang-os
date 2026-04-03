/**
 * 商户管理 — 开户/续费/停用/升级（数据：GET /api/v1/hub/merchants）
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
  cardValueGreen: { fontSize: 28, fontWeight: 700, color: '#22C55E' } as React.CSSProperties,
  cardValueRed: { fontSize: 28, fontWeight: 700, color: '#EF4444' } as React.CSSProperties,
  cardValueBlue: { fontSize: 28, fontWeight: 700, color: '#3B82F6' } as React.CSSProperties,
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

type HubMerchant = {
  id: string;
  name: string;
  template: string;
  stores: number;
  status: string;
  expires: string;
};

function templateLabel(t: string): string {
  const x = t.toLowerCase();
  if (x === 'pro') return 'Pro';
  if (x === 'lite') return 'Lite';
  if (x === 'standard') return 'Standard';
  return t;
}

function statusLabel(status: string, expires: string): { text: string; color: string } {
  const st = status.toLowerCase();
  if (st === 'active') {
    const exp = new Date(expires);
    const days = (exp.getTime() - Date.now()) / (86400 * 1000);
    if (!Number.isNaN(exp.getTime()) && days >= 0 && days <= 30) {
      return { text: '即将到期', color: '#F59E0B' };
    }
    return { text: '正常', color: '#22C55E' };
  }
  if (st === 'trial') return { text: '试用', color: '#3B82F6' };
  if (st === 'inactive' || st === 'suspended') return { text: '已停用', color: '#EF4444' };
  return { text: status, color: '#6B8A97' };
}

export function MerchantsPage() {
  const [items, setItems] = useState<HubMerchant[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hubGet<HubListResult<HubMerchant>>('/merchants?page=1&size=100')
      .then((d) => {
        if (!cancelled) {
          setItems(d.items || []);
          setTotal(d.total ?? (d.items?.length ?? 0));
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

  const stats = useMemo(() => {
    let normal = 0;
    let soon = 0;
    let stopped = 0;
    for (const m of items) {
      const { text } = statusLabel(m.status, m.expires);
      if (text === '正常') normal += 1;
      else if (text === '即将到期') soon += 1;
      else if (text === '已停用') stopped += 1;
    }
    return { normal, soon, stopped };
  }, [items]);

  return (
    <div style={s.page}>
      <div style={s.title}>商户管理</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>商户总数</div><div style={s.cardValue}>{total}</div></div>
        <div style={s.card}><div style={s.cardLabel}>正常运营</div><div style={s.cardValueGreen}>{stats.normal}</div></div>
        <div style={s.card}><div style={s.cardLabel}>即将到期</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{stats.soon}</div></div>
        <div style={s.card}><div style={s.cardLabel}>已停用</div><div style={s.cardValueRed}>{stats.stopped}</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>全部商户</div>
        <button type="button" style={s.btn}>+ 新建商户</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户名称</th>
            <th style={s.th}>套餐</th>
            <th style={s.th}>门店数</th>
            <th style={s.th}>到期日</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => {
            const st = statusLabel(m.status, m.expires);
            return (
              <tr key={m.id}>
                <td style={s.td}>{m.name}</td>
                <td style={s.td}><span style={s.badge('#3B82F6')}>{templateLabel(m.template)}</span></td>
                <td style={s.td}>{m.stores}</td>
                <td style={s.td}>{m.expires}</td>
                <td style={s.td}><span style={s.badge(st.color)}>{st.text}</span></td>
                <td style={s.td}>
                  <button type="button" style={s.btnSec}>编辑</button>
                  <button type="button" style={s.btnSec}>续费</button>
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
