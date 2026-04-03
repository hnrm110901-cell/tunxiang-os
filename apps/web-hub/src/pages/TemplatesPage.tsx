/**
 * 模板分配 — Pro/Standard/Lite（GET /api/v1/hub/templates + merchants）
 */
import { useEffect, useState } from 'react';
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

type HubTemplateRow = {
  id: string;
  name: string;
  price_yuan: number;
  domains: number;
  agents: number;
  max_stores: number;
  features_count: number;
};

type HubMerchant = {
  id: string;
  name: string;
  template: string;
  stores: number;
  status: string;
  expires: string;
};

const tierColor: Record<string, string> = {
  pro: '#FF6B2C',
  standard: '#3B82F6',
  lite: '#6B8A97',
};

function tierLabel(id: string): string {
  const x = id.toLowerCase();
  if (x === 'pro') return 'Pro';
  if (x === 'lite') return 'Lite';
  if (x === 'standard') return 'Standard';
  return id;
}

export function TemplatesPage() {
  const [templates, setTemplates] = useState<HubTemplateRow[]>([]);
  const [merchants, setMerchants] = useState<HubMerchant[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      hubGet<HubTemplateRow[]>('/templates'),
      hubGet<HubListResult<HubMerchant>>('/merchants?page=1&size=100'),
    ])
      .then(([t, m]) => {
        if (!cancelled) {
          setTemplates(Array.isArray(t) ? t : []);
          setMerchants(m.items || []);
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

  return (
    <div style={s.page}>
      <div style={s.title}>模板配置</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        {templates.map((t) => (
          <div key={t.id} style={s.card}>
            <div style={s.cardLabel}>{t.name}</div>
            <div style={{ ...s.cardValue, color: tierColor[t.id] || '#FF6B2C' }}>
              {merchants.filter((m) => m.template.toLowerCase() === t.id.toLowerCase()).length}
            </div>
            <div style={{ fontSize: 11, color: '#6B8A97', marginTop: 4 }}>
              ¥{t.price_yuan}/月 · {t.domains}域 · {t.agents} Agent
            </div>
          </div>
        ))}
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>模板分配记录（来自商户）</div>
        <button type="button" style={s.btn}>+ 新建模板</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>商户</th>
            <th style={s.th}>模板</th>
            <th style={s.th}>到期日</th>
            <th style={s.th}>覆盖门店</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {merchants.map((a) => (
            <tr key={a.id}>
              <td style={s.td}>{a.name}</td>
              <td style={s.td}>
                <span style={s.badge(tierColor[a.template.toLowerCase()] || '#6B8A97')}>
                  {tierLabel(a.template)}
                </span>
              </td>
              <td style={s.td}>{a.expires}</td>
              <td style={s.td}>{a.stores}</td>
              <td style={s.td}>
                <button type="button" style={s.btnSec}>升级</button>
                <button type="button" style={s.btnSec}>编辑</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
