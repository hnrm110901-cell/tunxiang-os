/**
 * 计费账单 — HaaS+SaaS+AI（GET /api/v1/hub/billing）
 */
import { useEffect, useMemo, useState } from 'react';
import { hubGet } from '../api/hubApi';

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
  row: { display: 'flex', gap: 24, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  section: {
    flex: '1 1 320px', background: '#0D2129', borderRadius: 10, padding: 20,
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  sectionTitle: { fontSize: 14, fontWeight: 600, color: '#FFFFFF', marginBottom: 16 } as React.CSSProperties,
  pieRow: { display: 'flex', justifyContent: 'space-around', alignItems: 'center' } as React.CSSProperties,
  pieItem: { textAlign: 'center' as const } as React.CSSProperties,
  pieDot: (color: string) => ({
    display: 'inline-block', width: 12, height: 12, borderRadius: '50%', background: color, marginRight: 6,
  }) as React.CSSProperties,
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
  err: { color: '#EF4444', fontSize: 13, marginBottom: 12 } as React.CSSProperties,
};

type HubBilling = {
  month: string;
  total_revenue_yuan: number;
  breakdown: Record<string, { label: string; yuan: number; pct: number }>;
  merchants: number;
  active_stores: number;
  arr_yuan: number;
};

export function BillingPage() {
  const [data, setData] = useState<HubBilling | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hubGet<HubBilling>('/billing')
      .then((d) => {
        if (!cancelled) {
          setData(d);
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

  const { haas, saas, ai, total, pcts } = useMemo(() => {
    if (!data) {
      return {
        haas: 0, saas: 0, ai: 0, total: 0,
        pcts: { haas: 0, saas: 0, ai: 0 },
      };
    }
    const h = data.breakdown?.haas?.yuan ?? 0;
    const sa = data.breakdown?.saas?.yuan ?? 0;
    const a = data.breakdown?.ai?.yuan ?? 0;
    const t = h + sa + a || data.total_revenue_yuan;
    return {
      haas: h,
      saas: sa,
      ai: a,
      total: t,
      pcts: {
        haas: t ? Math.round((h / t) * 100) : 0,
        saas: t ? Math.round((sa / t) * 100) : 0,
        ai: t ? Math.round((a / t) * 100) : 0,
      },
    };
  }, [data]);

  return (
    <div style={s.page}>
      <div style={s.title}>计费账单</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>本月总收入</div><div style={s.cardValue}>{(total / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>HaaS收入</div><div style={{ ...s.cardValue, color: '#3B82F6' }}>{(haas / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>SaaS收入</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{(saas / 10000).toFixed(1)}万</div></div>
        <div style={s.card}><div style={s.cardLabel}>AI收入</div><div style={{ ...s.cardValue, color: '#A855F7' }}>{(ai / 10000).toFixed(1)}万</div></div>
      </div>

      <div style={s.row}>
        <div style={s.section}>
          <div style={s.sectionTitle}>三层收入占比</div>
          <div style={s.pieRow}>
            <div style={s.pieItem}>
              <div style={{
                width: 120,
                height: 120,
                borderRadius: '50%',
                background: `conic-gradient(#3B82F6 0% ${pcts.haas}%, #22C55E ${pcts.haas}% ${pcts.haas + pcts.saas}%, #A855F7 ${pcts.haas + pcts.saas}% 100%)`,
                margin: '0 auto 12px',
              }}
              />
            </div>
            <div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#3B82F6')} />HaaS {pcts.haas}%</div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#22C55E')} />SaaS {pcts.saas}%</div>
              <div style={{ marginBottom: 8, fontSize: 13 }}><span style={s.pieDot('#A855F7')} />AI {pcts.ai}%</div>
            </div>
          </div>
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>平台汇总（Hub）</div>
          <div style={{ fontSize: 13, color: '#8BA5B2', lineHeight: 1.8 }}>
            <p>账期：{data?.month ?? '—'}</p>
            <p>计费商户数：{data?.merchants ?? '—'}；在营门店：{data?.active_stores ?? '—'}</p>
            <p>ARR 约：{data ? `${(data.arr_yuan / 10000).toFixed(0)}万` : '—'} 元/年（演示数据）</p>
          </div>
        </div>
      </div>

      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>账单明细（网关暂未提供商户级明细时仅展示汇总）</div>
        <button type="button" style={s.btn}>+ 新建账单</button>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>项目</th>
            <th style={s.th}>金额（元）</th>
            <th style={s.th}>占比</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {data && (
            <>
              <tr>
                <td style={s.td}>{data.breakdown.haas?.label ?? 'HaaS'}</td>
                <td style={s.td}>{data.breakdown.haas?.yuan?.toLocaleString() ?? '—'}</td>
                <td style={s.td}>{data.breakdown.haas?.pct ?? '—'}%</td>
                <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
              </tr>
              <tr>
                <td style={s.td}>{data.breakdown.saas?.label ?? 'SaaS'}</td>
                <td style={s.td}>{data.breakdown.saas?.yuan?.toLocaleString() ?? '—'}</td>
                <td style={s.td}>{data.breakdown.saas?.pct ?? '—'}%</td>
                <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
              </tr>
              <tr>
                <td style={s.td}>{data.breakdown.ai?.label ?? 'AI'}</td>
                <td style={s.td}>{data.breakdown.ai?.yuan?.toLocaleString() ?? '—'}</td>
                <td style={s.td}>{data.breakdown.ai?.pct ?? '—'}%</td>
                <td style={s.td}><button type="button" style={s.btnSec}>查看详情</button></td>
              </tr>
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}
