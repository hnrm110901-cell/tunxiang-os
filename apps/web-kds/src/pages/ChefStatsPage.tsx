/**
 * ChefStatsPage — 厨师绩效计件看板
 *
 * 天财商龙特色功能：KDS即绩效系统，多劳多得。
 *
 * 功能：
 *   - 今日/本周/本月绩效排行榜
 *   - 展示出品数量、金额、平均制作时长
 *   - 返工次数（负向指标，红色标注）
 *   - 可按档口过滤
 */
import { useCallback, useEffect, useState } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface ChefStat {
  operator_id: string;
  operator_name?: string;
  total_dishes: number;
  total_amount: number;
  avg_cook_sec: number;
  rush_handled: number;
  remake_count: number;
}

type Period = 'today' | 'week' | 'month';

// ─── Constants ───

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const STORE_ID = (window as any).__STORE_ID__ || '';

const PERIOD_LABELS: Record<Period, string> = {
  today: '今日',
  week: '本周',
  month: '本月',
};

// ─── Helpers ───

function fmtSec(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}'${String(s).padStart(2, '0')}"`;
}

function RankBadge({ rank }: { rank: number }) {
  const bg = rank === 1 ? '#FFD60A' : rank === 2 ? '#C0C0C0' : rank === 3 ? '#CD7F32' : '#2A2A2A';
  const color = rank <= 3 ? '#000' : '#555';
  return (
    <div
      style={{
        width: 32,
        height: 32,
        borderRadius: 8,
        background: bg,
        color,
        fontSize: 16,
        fontWeight: 700,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      {rank}
    </div>
  );
}

// ─── Main ───

export function ChefStatsPage() {
  const [period, setPeriod] = useState<Period>('today');
  const [stats, setStats] = useState<ChefStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async (p: Period) => {
    if (!STORE_ID) {
      setLoading(false);
      setError('未配置门店信息（STORE_ID）');
      return;
    }
    setLoading(true);
    try {
      const res = await txFetch<{ items: ChefStat[] }>(
        `${API_BASE}/api/v1/kds/chef-stats/leaderboard?store_id=${STORE_ID}&period=${p}`,
      );
      setStats(res.items);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats(period);
  }, [fetchStats, period]);

  const maxDishes = Math.max(...stats.map((s) => s.total_dishes), 1);

  return (
    <div
      style={{
        background: '#0B0B0B',
        minHeight: '100vh',
        fontFamily: 'Noto Sans SC, sans-serif',
        color: '#E0E0E0',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 标题栏 */}
      <header
        style={{
          background: '#111',
          padding: '16px 20px',
          borderBottom: '1px solid #1A1A1A',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>
            厨师绩效排行
          </span>
          {/* 周期切换 */}
          <div style={{ display: 'flex', gap: 4 }}>
            {(['today', 'week', 'month'] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                style={{
                  padding: '8px 16px',
                  minHeight: 48,
                  background: period === p ? '#FF6B35' : '#1A1A1A',
                  color: period === p ? '#fff' : '#888',
                  border: 'none',
                  borderRadius: 8,
                  fontSize: 15,
                  fontWeight: period === p ? 700 : 400,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* 排行榜主体 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 16,
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {error && (
          <div style={{ color: '#FF3B30', padding: 16, fontSize: 14 }}>{error}</div>
        )}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#555' }}>加载中…</div>
        ) : stats.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#333', fontSize: 18 }}>
            {PERIOD_LABELS[period]}暂无绩效数据
          </div>
        ) : (
          stats.map((stat, idx) => {
            const barWidth = (stat.total_dishes / maxDishes) * 100;
            return (
              <div
                key={stat.operator_id}
                style={{
                  background: '#1A1A1A',
                  border: `1px solid ${idx === 0 ? '#FFD60A' : '#2A2A2A'}`,
                  borderRadius: 12,
                  padding: 16,
                  marginBottom: 10,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                  <RankBadge rank={idx + 1} />
                  <span style={{ fontSize: 20, fontWeight: 700, color: '#fff', flex: 1 }}>
                    {stat.operator_name || `厨师 ${stat.operator_id.slice(-6)}`}
                  </span>
                  {/* 出品总数 */}
                  <div style={{ textAlign: 'right' }}>
                    <span
                      style={{
                        fontSize: 36,
                        fontWeight: 700,
                        color: '#FF6B35',
                        fontFamily: 'monospace',
                        lineHeight: 1,
                      }}
                    >
                      {stat.total_dishes}
                    </span>
                    <span style={{ fontSize: 13, color: '#666', marginLeft: 4 }}>道</span>
                  </div>
                </div>

                {/* 出品数量进度条 */}
                <div
                  style={{
                    height: 8,
                    borderRadius: 4,
                    background: '#2A2A2A',
                    overflow: 'hidden',
                    marginBottom: 12,
                  }}
                >
                  <div
                    style={{
                      width: `${barWidth}%`,
                      height: '100%',
                      background: idx === 0 ? '#FFD60A' : '#FF6B35',
                      transition: 'width 0.5s',
                    }}
                  />
                </div>

                {/* 详细指标 */}
                <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                  <div>
                    <div style={{ fontSize: 13, color: '#555' }}>出品金额</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#30D158' }}>
                      ¥{stat.total_amount.toFixed(0)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, color: '#555' }}>平均制作</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#64D2FF' }}>
                      {fmtSec(stat.avg_cook_sec)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, color: '#555' }}>处理催菜</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#FF9F0A' }}>
                      {stat.rush_handled}次
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, color: '#555' }}>返工</div>
                    <div
                      style={{
                        fontSize: 18,
                        fontWeight: 700,
                        color: stat.remake_count > 0 ? '#FF3B30' : '#30D158',
                      }}
                    >
                      {stat.remake_count}次
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
