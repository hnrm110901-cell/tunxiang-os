/**
 * 门店健康度总览页
 *
 * - 顶部 3 张汇总卡片（在线门店 / 平均健康分 / 今日总营收）
 * - 门店健康列表：分数 + 等级 + 营收进度条 + 成本率 + 日清完成率 + 预警标签
 * - 30 秒自动刷新
 * - 单门店数据失败时显示灰色降级状态，不崩溃
 */

import { useEffect, useState, useCallback } from 'react';
import {
  fetchStoreHealthOverview,
  StoreHealthItem,
  StoreHealthSummary,
} from '../api/storeHealthApi';

// ─── 颜色映射 ──────────────────────────────────────────────────────────────────

const SCORE_COLOR: Record<string, string> = {
  A: '#0F6E56',  // ≥80 绿色（优秀）
  B: '#4FC3F7',  // ≥60 蓝色（良好）
  C: '#BA7517',  // ≥40 橙色（警告）
  D: '#FF4D4D',  // <40 红色（危险）
};

const GRADE_LABEL: Record<string, string> = {
  A: '优秀', B: '良好', C: '警告', D: '危险', '-': '加载中',
};

function scoreColor(grade: string): string {
  return SCORE_COLOR[grade] ?? '#555';
}

function costRateColor(rate: number): string {
  if (rate > 0.50) return '#FF4D4D';
  if (rate > 0.38) return '#BA7517';
  return '#4CAF50';
}

function fmtYuan(fen: number): string {
  return `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

// ─── 汇总卡片 ──────────────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div style={{
      background: '#112228',
      borderRadius: 8,
      padding: '20px 24px',
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color: valueColor ?? '#E0E0E0', lineHeight: 1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

// ─── 健康分圆圈 ────────────────────────────────────────────────────────────────

function ScoreBadge({ score, grade }: { score: number; grade: string }) {
  const color = scoreColor(grade);
  if (score < 0) {
    return (
      <div style={{
        width: 56, height: 56, borderRadius: '50%',
        border: '3px solid #444',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, color: '#555', flexShrink: 0,
      }}>—</div>
    );
  }
  return (
    <div style={{
      width: 56, height: 56, borderRadius: '50%',
      border: `3px solid ${color}`,
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 18, fontWeight: 700, color, lineHeight: 1 }}>{score}</span>
      <span style={{ fontSize: 10, color, lineHeight: 1.2 }}>{grade}</span>
    </div>
  );
}

// ─── 进度条 ────────────────────────────────────────────────────────────────────

function ProgressBar({
  value,
  color,
  max = 1,
}: {
  value: number;
  color: string;
  max?: number;
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div style={{ flex: 1, height: 6, background: '#1a2a33', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.4s' }} />
    </div>
  );
}

// ─── 预警标签 ──────────────────────────────────────────────────────────────────

function AlertTag({ text }: { text: string }) {
  return (
    <span style={{
      background: 'rgba(255,77,77,0.15)',
      color: '#FF4D4D',
      fontSize: 11,
      padding: '2px 8px',
      borderRadius: 10,
      whiteSpace: 'nowrap',
    }}>
      {text}
    </span>
  );
}

// ─── 门店行 ────────────────────────────────────────────────────────────────────

function StoreRow({ store }: { store: StoreHealthItem }) {
  const grade = store.health_grade;
  const color = scoreColor(grade);
  const isDegraded = store.health_score < 0;
  const isOffline = store.status === 'offline';

  return (
    <div style={{
      background: isDegraded ? '#0d1c22' : '#112228',
      borderRadius: 8,
      padding: '16px 20px',
      opacity: isDegraded ? 0.65 : 1,
    }}>
      {/* 头部：门店名 + 状态 + 分数圆圈 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14 }}>
        <ScoreBadge score={store.health_score} grade={grade} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#E0E0E0' }}>
              {store.store_name}
            </span>
            <span style={{
              fontSize: 11,
              padding: '1px 8px',
              borderRadius: 10,
              background: isOffline ? 'rgba(255,77,77,0.15)' : 'rgba(79,195,247,0.12)',
              color: isOffline ? '#FF4D4D' : '#4FC3F7',
            }}>
              {isOffline ? '离线' : store.status === 'online' ? '在线' : store.status}
            </span>
            {!isDegraded && (
              <span style={{ fontSize: 12, color: color }}>
                {GRADE_LABEL[grade] ?? grade}
              </span>
            )}
          </div>
          <div style={{ fontSize: 13, color: '#999', marginTop: 4 }}>
            今日营收 <span style={{ color: '#E0E0E0', fontWeight: 600 }}>
              {fmtYuan(store.today_revenue_fen)}
            </span>
          </div>
        </div>
      </div>

      {/* 指标行 */}
      {!isDegraded && (
        <div style={{ display: 'grid', gap: 8 }}>

          {/* 营收达成率 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 72, fontSize: 12, color: '#999', textAlign: 'right', flexShrink: 0 }}>营收达成</span>
            <ProgressBar value={store.revenue_rate} color={color} />
            <span style={{ width: 44, fontSize: 12, color: '#ccc', textAlign: 'right', flexShrink: 0 }}>
              {fmtPct(store.revenue_rate)}
            </span>
          </div>

          {/* 成本率 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 72, fontSize: 12, color: '#999', textAlign: 'right', flexShrink: 0 }}>成本率</span>
            <ProgressBar value={store.cost_rate} color={costRateColor(store.cost_rate)} max={0.6} />
            <span style={{
              width: 44, fontSize: 12, textAlign: 'right', flexShrink: 0,
              color: costRateColor(store.cost_rate), fontWeight: store.cost_rate > 0.38 ? 600 : 400,
            }}>
              {fmtPct(store.cost_rate)}
            </span>
          </div>

          {/* 日清完成率 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 72, fontSize: 12, color: '#999', textAlign: 'right', flexShrink: 0 }}>日清</span>
            <ProgressBar value={store.daily_review_completion} color="#4FC3F7" />
            <span style={{ width: 44, fontSize: 12, color: '#ccc', textAlign: 'right', flexShrink: 0 }}>
              {fmtPct(store.daily_review_completion)}
            </span>
          </div>
        </div>
      )}

      {/* 预警标签 */}
      {store.alerts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
          {store.alerts.map((a, i) => <AlertTag key={i} text={a} />)}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function StoreHealthPage() {
  const [stores, setStores] = useState<StoreHealthItem[]>([]);
  const [summary, setSummary] = useState<StoreHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchStoreHealthOverview();
      setStores(data.stores);
      setSummary(data.summary);
      setLastUpdated(new Date());
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => { load(); }, [load]);

  // 30 秒自动刷新
  useEffect(() => {
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  // ─── 平均分颜色 ───
  const avgGrade =
    !summary ? '-'
    : summary.avg_health_score >= 80 ? 'A'
    : summary.avg_health_score >= 60 ? 'B'
    : summary.avg_health_score >= 40 ? 'C'
    : 'D';

  return (
    <div style={{ padding: 24 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>门店健康度</h2>
        <div style={{ fontSize: 12, color: '#555' }}>
          {loading && !summary
            ? '加载中…'
            : lastUpdated
              ? `更新于 ${lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
              : null}
        </div>
      </div>

      {/* 顶部汇总卡片 */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        <SummaryCard
          label="在线门店"
          value={summary ? `${summary.online_stores} / ${summary.total_stores}` : '—'}
          sub="门店在线数 / 总门店数"
        />
        <SummaryCard
          label="平均健康分"
          value={summary ? `${summary.avg_health_score}` : '—'}
          sub={summary ? GRADE_LABEL[avgGrade] : undefined}
          valueColor={scoreColor(avgGrade)}
        />
        <SummaryCard
          label="今日总营收"
          value={summary ? fmtYuan(summary.total_revenue_fen) : '—'}
          sub="所有门店合计"
        />
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: 'rgba(255,77,77,0.1)',
          border: '1px solid rgba(255,77,77,0.3)',
          borderRadius: 8,
          padding: '12px 16px',
          marginBottom: 20,
          color: '#FF4D4D',
          fontSize: 14,
        }}>
          数据加载失败：{error}
        </div>
      )}

      {/* 门店健康列表 */}
      {loading && !summary ? (
        <div style={{ color: '#555', textAlign: 'center', padding: 48, fontSize: 14 }}>
          正在加载门店健康数据…
        </div>
      ) : stores.length === 0 ? (
        <div style={{ color: '#555', textAlign: 'center', padding: 48, fontSize: 14 }}>
          暂无门店数据
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {stores.map(store => (
            <StoreRow key={store.store_id} store={store} />
          ))}
        </div>
      )}
    </div>
  );
}
