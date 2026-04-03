/**
 * 部署管理 — Mac mini 舰队（GET /api/v1/hub/deployment/mac-minis）
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
  dot: (ok: boolean) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: ok ? '#22C55E' : '#EF4444', marginRight: 6,
  }) as React.CSSProperties,
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color,
  }) as React.CSSProperties,
  err: { color: '#EF4444', fontSize: 13, marginBottom: 12 } as React.CSSProperties,
};

type HubMini = {
  store: string;
  ip: string;
  tailscale: string;
  version: string;
  last_heartbeat: string;
  cpu_pct: number;
  mem_pct: number;
};

const TARGET_VER = '3.3.0';

export function DeploymentPage() {
  const [minis, setMinis] = useState<HubMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hubGet<HubMini[]>('/deployment/mac-minis')
      .then((d) => {
        if (!cancelled) {
          setMinis(Array.isArray(d) ? d : []);
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

  const { online, outdated } = useMemo(() => {
    let on = 0;
    let od = 0;
    for (const m of minis) {
      if (m.tailscale === 'online') on += 1;
      if (m.version !== TARGET_VER) od += 1;
    }
    return { online: on, outdated: od };
  }, [minis]);

  return (
    <div style={s.page}>
      <div style={s.title}>部署管理</div>
      {err && <div style={s.err}>{err}</div>}
      {loading && <div style={{ color: '#6B8A97', marginBottom: 16 }}>加载中…</div>}
      <div style={s.cards}>
        <div style={s.card}><div style={s.cardLabel}>Mac mini总数</div><div style={s.cardValue}>{minis.length}</div></div>
        <div style={s.card}><div style={s.cardLabel}>Tailscale在线</div><div style={{ ...s.cardValue, color: '#22C55E' }}>{online}</div></div>
        <div style={s.card}><div style={s.cardLabel}>离线设备</div><div style={{ ...s.cardValue, color: '#EF4444' }}>{minis.length - online}</div></div>
        <div style={s.card}><div style={s.cardLabel}>待更新</div><div style={{ ...s.cardValue, color: '#F59E0B' }}>{outdated}</div></div>
      </div>
      <div style={s.toolbar}>
        <div style={{ fontSize: 14, color: '#8BA5B2' }}>Mac mini 舰队</div>
        <div>
          <button type="button" style={s.btn}>推送更新</button>
        </div>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>门店</th>
            <th style={s.th}>IP</th>
            <th style={s.th}>Tailscale状态</th>
            <th style={s.th}>软件版本</th>
            <th style={s.th}>最后心跳</th>
            <th style={s.th}>CPU</th>
            <th style={s.th}>内存</th>
            <th style={s.th}>操作</th>
          </tr>
        </thead>
        <tbody>
          {minis.map((m) => {
            const tsOk = m.tailscale === 'online';
            const verOk = m.version === TARGET_VER;
            return (
              <tr key={m.store}>
                <td style={s.td}>{m.store}</td>
                <td style={s.td}><code style={{ color: '#8BA5B2' }}>{m.ip}</code></td>
                <td style={s.td}><span style={s.dot(tsOk)} />{tsOk ? '已连接' : '断开'}</td>
                <td style={s.td}>
                  {verOk
                    ? <span style={s.badge('#22C55E')}>{m.version}</span>
                    : <span style={s.badge('#F59E0B')}>{m.version}</span>}
                </td>
                <td style={s.td}>{m.last_heartbeat}</td>
                <td style={s.td}>{m.cpu_pct}%</td>
                <td style={s.td}>{m.mem_pct}%</td>
                <td style={s.td}>
                  <button type="button" style={s.btnSec}>SSH</button>
                  <button type="button" style={s.btnSec}>更新</button>
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
