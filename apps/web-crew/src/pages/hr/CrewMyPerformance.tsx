/**
 * 我的绩效 — 员工端 PWA
 * 路由: /me/performance
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

const T = {
  bg:       '#0B1A20',
  card:     '#112228',
  border:   '#1a2a33',
  text:     '#E0E0E0',
  muted:    '#64748b',
  dim:      '#334155',
  primary:  '#FF6B35',
  success:  '#30D158',
  warning:  '#FF9F0A',
};

interface PerformanceData {
  score: number;
  grade: string;
  rank: number;
  total_employees: number;
  dimensions: { name: string; score: number; max: number }[];
  history: { month: string; score: number }[];
}

function buildHeaders(): HeadersInit {
  const tenantId = localStorage.getItem('tenantId') ?? '';
  return {
    'Content-Type': 'application/json',
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };
}

async function apiGet<R>(url: string): Promise<R> {
  const res = await fetch(url, { headers: buildHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json() as { ok: boolean; data: R };
  if (!json.ok) throw new Error('API error');
  return json.data;
}

function gradeColor(grade: string): string {
  if (grade === 'S' || grade === 'A') return T.success;
  if (grade === 'B') return T.primary;
  if (grade === 'C') return T.warning;
  return '#FF453A';
}

export function CrewMyPerformance() {
  const navigate = useNavigate();

  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet<PerformanceData>('/api/v1/performance/me');
      setData(d);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <div
          style={{ width: 48, height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 20 }}
          onClick={() => navigate(-1)}
        >←</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center' }}>我的绩效</h1>
        <div style={{ width: 48 }} />
      </div>

      {loading && <div style={{ textAlign: 'center', color: T.muted, padding: 32 }}>加载中...</div>}

      {data && (
        <>
          {/* 总评分卡 */}
          <div style={{
            background: T.card, borderRadius: 12, padding: 20, marginBottom: 16,
            border: `1px solid ${T.border}`, textAlign: 'center',
          }}>
            <div style={{ fontSize: 48, fontWeight: 800, color: gradeColor(data.grade) }}>{data.score}</div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 8 }}>
              <span style={{
                fontSize: 14, padding: '4px 12px', borderRadius: 6,
                background: gradeColor(data.grade) + '22', color: gradeColor(data.grade),
              }}>等级 {data.grade}</span>
              <span style={{ fontSize: 14, color: T.muted }}>
                排名 {data.rank}/{data.total_employees}
              </span>
            </div>
          </div>

          {/* 各维度进度条 */}
          <div style={{
            background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>评分维度</div>
            {data.dimensions.map(dim => {
              const pct = dim.max > 0 ? (dim.score / dim.max) * 100 : 0;
              return (
                <div key={dim.name} style={{ marginBottom: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 6 }}>
                    <span>{dim.name}</span>
                    <span style={{ color: T.muted }}>{dim.score}/{dim.max}</span>
                  </div>
                  <div style={{ height: 8, background: T.dim, borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', borderRadius: 4,
                      background: pct >= 80 ? T.success : pct >= 60 ? T.primary : T.warning,
                      width: `${pct}%`, transition: 'width 0.5s',
                    }} />
                  </div>
                </div>
              );
            })}
          </div>

          {/* 历史趋势 */}
          <div style={{
            background: T.card, borderRadius: 12, padding: 16,
            border: `1px solid ${T.border}`,
          }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>历史趋势</div>
            {data.history.length > 0 ? (
              <div style={{ position: 'relative', height: 120 }}>
                {/* 简单折线用 SVG */}
                <svg width="100%" height="120" viewBox={`0 0 ${data.history.length * 60} 120`} preserveAspectRatio="none">
                  {(() => {
                    const maxS = Math.max(...data.history.map(h => h.score), 100);
                    const minS = Math.min(...data.history.map(h => h.score), 0);
                    const range = maxS - minS || 1;
                    const points = data.history.map((h, i) => {
                      const x = i * 60 + 30;
                      const y = 110 - ((h.score - minS) / range) * 90;
                      return `${x},${y}`;
                    }).join(' ');
                    return (
                      <>
                        <polyline points={points} fill="none" stroke={T.primary} strokeWidth="2" />
                        {data.history.map((h, i) => {
                          const x = i * 60 + 30;
                          const y = 110 - ((h.score - minS) / range) * 90;
                          return (
                            <g key={i}>
                              <circle cx={x} cy={y} r="4" fill={T.primary} />
                              <text x={x} y={y - 10} textAnchor="middle" fill={T.text} fontSize="11">{h.score}</text>
                            </g>
                          );
                        })}
                      </>
                    );
                  })()}
                </svg>
                <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: 4 }}>
                  {data.history.map(h => (
                    <span key={h.month} style={{ fontSize: 11, color: T.muted }}>{h.month}</span>
                  ))}
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', color: T.muted, padding: 20, fontSize: 16 }}>暂无历史数据</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default CrewMyPerformance;
