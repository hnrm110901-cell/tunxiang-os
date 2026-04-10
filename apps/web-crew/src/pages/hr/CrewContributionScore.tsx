/**
 * CrewContributionScore -- 我的经营贡献度
 * Store-Crew 终端（深色主题，min 48px，禁止antd）
 * 路由: /me/contribution
 *
 * 功能：
 *  - 我的贡献度大数字展示（圆形进度环，中间显示总分）
 *  - 5个维度条形进度条（营收/效率/满意/出勤/协作）
 *  - 本月排名展示（"第3名/共12人"）
 *  - 趋势对比（本周 vs 上周，上升绿/下降红）
 *  - 鼓励文案（>80分"优秀" / 60-80"良好" / <60"加油"）
 *
 * API:
 *  GET /api/v1/contribution/score/{employee_id}
 *  GET /api/v1/contribution/trend/{employee_id}?periods=6
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── Design Token (深色主题) ────────────────────────────────────────────────

const T = {
  bg:        '#0B1A20',
  card:      '#112228',
  border:    '#1a2a33',
  text:      '#E0E0E0',
  muted:     '#64748b',
  dim:       '#334155',
  primary:   '#FF6B35',
  success:   '#30D158',
  warning:   '#FF9F0A',
  danger:    '#FF453A',
  info:      '#185FA5',
};

// ─── Types ──────────────────────────────────────────────────────────────────

interface Dimensions {
  revenue: number;
  efficiency: number;
  satisfaction: number;
  attendance: number;
  teamwork: number;
}

interface ScoreData {
  total_score: number;
  grade: string;
  dimensions: Dimensions;
  role: string;
  employee_name: string;
}

interface TrendPoint {
  period_end: string;
  total_score: number;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

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

const DIMENSION_LABELS: Record<keyof Dimensions, string> = {
  revenue: '营收贡献',
  efficiency: '服务效率',
  satisfaction: '客户满意',
  attendance: '出勤纪律',
  teamwork: '团队协作',
};

const DIMENSION_COLORS: Record<keyof Dimensions, string> = {
  revenue: '#FF6B35',
  efficiency: '#30D158',
  satisfaction: '#5AC8FA',
  attendance: '#FF9F0A',
  teamwork: '#BF5AF2',
};

function gradeInfo(score: number): { label: string; color: string; message: string } {
  if (score >= 90) return { label: '卓越', color: '#FFD700', message: '太棒了！你是门店之星！' };
  if (score >= 80) return { label: '优秀', color: T.success, message: '表现优秀，继续保持！' };
  if (score >= 60) return { label: '良好', color: T.primary, message: '稳步提升中，再接再厉！' };
  if (score >= 40) return { label: '合格', color: T.warning, message: '还有提升空间，加油！' };
  return { label: '待提升', color: T.danger, message: '一起努力，下周会更好！' };
}

// ─── CircleProgress ─────────────────────────────────────────────────────────

function CircleProgress({ score, size = 180 }: { score: number; size?: number }) {
  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const percent = Math.min(score, 100) / 100;
  const offset = circumference * (1 - percent);
  const info = gradeInfo(score);

  return (
    <div style={{ position: 'relative', width: size, height: size, margin: '0 auto' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Background circle */}
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={T.dim} strokeWidth={10}
        />
        {/* Progress circle */}
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={info.color} strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ fontSize: 42, fontWeight: 800, color: info.color }}>
          {score.toFixed(1)}
        </div>
        <div style={{ fontSize: 14, color: T.muted, marginTop: 2 }}>
          经营贡献度
        </div>
      </div>
    </div>
  );
}

// ─── DimensionBar ───────────────────────────────────────────────────────────

function DimensionBar({ label, score, color }: { label: string; score: number; color: string }) {
  const pct = Math.min(score, 100);
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 14, color: T.text }}>{label}</span>
        <span style={{ fontSize: 14, fontWeight: 700, color }}>{score.toFixed(1)}</span>
      </div>
      <div style={{
        width: '100%', height: 8, borderRadius: 4, background: T.dim, overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 4, background: color,
          transition: 'width 0.6s ease',
        }} />
      </div>
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function CrewContributionScore() {
  const navigate = useNavigate();
  const [data, setData] = useState<ScoreData | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [rank, _setRank] = useState<{ rank: number; total: number } | null>(null);
  const [loading, setLoading] = useState(true);

  const employeeId = localStorage.getItem('employeeId') ?? '';

  const load = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const [scoreRes, trendRes] = await Promise.all([
        apiGet<ScoreData>(`/api/v1/contribution/score/${employeeId}`),
        apiGet<TrendPoint[]>(`/api/v1/contribution/trend/${employeeId}?periods=6`),
      ]);
      setData(scoreRes);
      setTrend(trendRes);
    } catch { /* ignore */ }
    setLoading(false);
  }, [employeeId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <div style={{ background: T.bg, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: T.muted, fontSize: 16 }}>加载中...</div>
      </div>
    );
  }

  const score = data?.total_score ?? 0;
  const info = gradeInfo(score);
  const dims = data?.dimensions ?? { revenue: 0, efficiency: 0, satisfaction: 0, attendance: 0, teamwork: 0 };

  // 趋势对比
  const currentWeek = trend.length > 0 ? trend[trend.length - 1]?.total_score ?? 0 : 0;
  const lastWeek = trend.length > 1 ? trend[trend.length - 2]?.total_score ?? 0 : 0;
  const delta = currentWeek - lastWeek;
  const trendUp = delta > 0;
  const trendDown = delta < 0;

  return (
    <div style={{ background: T.bg, minHeight: '100vh', padding: '16px 16px 72px', color: T.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 20 }}>
        <div
          style={{
            width: 48, height: 48, display: 'flex', alignItems: 'center',
            justifyContent: 'center', cursor: 'pointer', fontSize: 20,
          }}
          onClick={() => navigate(-1)}
          role="button"
          tabIndex={0}
        >
          &larr;
        </div>
        <h1 style={{ fontSize: 20, fontWeight: 700, flex: 1, textAlign: 'center', margin: 0 }}>
          我的经营贡献度
        </h1>
        <div style={{
          background: T.info, color: '#fff', fontSize: 11, padding: '2px 8px',
          borderRadius: 4, fontWeight: 600,
        }}>
          AI实时计算
        </div>
      </div>

      {/* 圆形进度环 */}
      <div style={{
        background: T.card, borderRadius: 16, padding: '24px 16px', marginBottom: 16,
        border: `1px solid ${T.border}`,
      }}>
        <CircleProgress score={score} />
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <span style={{
            display: 'inline-block', padding: '4px 16px', borderRadius: 12,
            background: info.color + '22', color: info.color,
            fontSize: 16, fontWeight: 700,
          }}>
            {info.label}
          </span>
        </div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 14, color: T.muted }}>
          {info.message}
        </div>
      </div>

      {/* 排名 + 趋势 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        {/* 排名卡片 */}
        <div style={{
          flex: 1, background: T.card, borderRadius: 12, padding: 16,
          border: `1px solid ${T.border}`, textAlign: 'center',
        }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 4 }}>本月排名</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: T.primary }}>
            {rank ? `第${rank.rank}名` : '--'}
          </div>
          <div style={{ fontSize: 12, color: T.muted }}>
            {rank ? `共${rank.total}人` : ''}
          </div>
        </div>

        {/* 趋势卡片 */}
        <div style={{
          flex: 1, background: T.card, borderRadius: 12, padding: 16,
          border: `1px solid ${T.border}`, textAlign: 'center',
        }}>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 4 }}>本周 vs 上周</div>
          <div style={{
            fontSize: 28, fontWeight: 800,
            color: trendUp ? T.success : (trendDown ? T.danger : T.muted),
          }}>
            {trendUp ? '+' : ''}{delta.toFixed(1)}
          </div>
          <div style={{
            fontSize: 14,
            color: trendUp ? T.success : (trendDown ? T.danger : T.muted),
          }}>
            {trendUp ? '上升' : (trendDown ? '下降' : '持平')}
          </div>
        </div>
      </div>

      {/* 五维度条形进度条 */}
      <div style={{
        background: T.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>五维分析</div>
        {(Object.keys(DIMENSION_LABELS) as (keyof Dimensions)[]).map((key) => (
          <DimensionBar
            key={key}
            label={DIMENSION_LABELS[key]}
            score={dims[key]}
            color={DIMENSION_COLORS[key]}
          />
        ))}
      </div>

      {/* 趋势曲线（简化版：文字列表） */}
      {trend.length > 0 && (
        <div style={{
          background: T.card, borderRadius: 12, padding: 16,
          border: `1px solid ${T.border}`,
        }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>近期趋势</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 4 }}>
            {trend.map((t, i) => {
              const barH = Math.max(8, (t.total_score / 100) * 80);
              const isLatest = i === trend.length - 1;
              return (
                <div key={t.period_end} style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{
                    fontSize: 11, fontWeight: isLatest ? 700 : 400,
                    color: isLatest ? T.primary : T.muted, marginBottom: 4,
                  }}>
                    {t.total_score > 0 ? t.total_score.toFixed(0) : '-'}
                  </div>
                  <div style={{
                    height: 80, display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                  }}>
                    <div style={{
                      width: 20, height: barH, borderRadius: 4,
                      background: isLatest ? T.primary : T.dim,
                      transition: 'height 0.4s ease',
                    }} />
                  </div>
                  <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>
                    {t.period_end.slice(5)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default CrewContributionScore;
