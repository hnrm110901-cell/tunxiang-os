/**
 * StationProfitPage — 档口毛利核算
 *
 * 天财商龙特色功能：每条生产动线的营收/毛利独立核算，档口即利润中心。
 *
 * 颜色语义（与 Design Token 一致）：
 *   毛利率 ≥60% → success 绿色（#0F6E56）
 *   40~60%      → warning 黄色（#BA7517）
 *   <40%        → danger  红色（#A32D2D）
 */
import { useCallback, useEffect, useState } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface StationProfit {
  dept_id: string;
  dept_name: string;
  dish_count: number;
  revenue: number;
  cost: number;
  profit: number;
  profit_margin_pct: number;
  status: 'healthy' | 'warning' | 'danger';
}

interface ProfitSummary {
  total_revenue: number;
  total_profit: number;
  avg_margin_pct: number;
  depts: StationProfit[];
}

type Period = 'today' | 'week' | 'month';

// ─── Constants ───

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';
const STORE_ID = (window as any).__STORE_ID__ || '';

const STATUS_COLORS = {
  healthy: { bg: '#0A1A10', border: '#0F6E56', text: '#30D158' },
  warning: { bg: '#1A1500', border: '#BA7517', text: '#FF9F0A' },
  danger:  { bg: '#1A0A0A', border: '#A32D2D', text: '#FF3B30' },
};

const MOCK_SUMMARY: ProfitSummary = {
  total_revenue: 28450,
  total_profit: 17120,
  avg_margin_pct: 60.2,
  depts: [
    { dept_id: 'd1', dept_name: '热菜档', dish_count: 142, revenue: 12800, cost: 4480, profit: 8320, profit_margin_pct: 65.0, status: 'healthy' },
    { dept_id: 'd2', dept_name: '海鲜档', dish_count: 38, revenue: 8600, cost: 3870, profit: 4730, profit_margin_pct: 55.0, status: 'warning' },
    { dept_id: 'd3', dept_name: '凉菜档', dish_count: 65, revenue: 4200, cost: 1260, profit: 2940, profit_margin_pct: 70.0, status: 'healthy' },
    { dept_id: 'd4', dept_name: '主食档', dish_count: 82, revenue: 2850, cost: 1710, profit: 1140, profit_margin_pct: 40.0, status: 'warning' },
  ],
};

// ─── Sub-components ───

function ProfitCard({ dept }: { dept: StationProfit }) {
  const c = STATUS_COLORS[dept.status];
  return (
    <div
      style={{
        background: c.bg,
        border: `2px solid ${c.border}`,
        borderRadius: 12,
        padding: 18,
      }}
    >
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>
          {dept.dept_name}
        </span>
        <div
          style={{
            fontSize: 32,
            fontWeight: 700,
            color: c.text,
            fontFamily: 'monospace',
          }}
        >
          {dept.profit_margin_pct.toFixed(1)}%
        </div>
      </div>

      {/* 进度条 */}
      <div
        style={{
          height: 8,
          borderRadius: 4,
          background: '#2A2A2A',
          overflow: 'hidden',
          marginBottom: 14,
        }}
      >
        <div
          style={{
            width: `${Math.min(dept.profit_margin_pct, 100)}%`,
            height: '100%',
            background: c.text,
            transition: 'width 0.5s',
          }}
        />
      </div>

      {/* 数字明细 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <div>
          <div style={{ fontSize: 12, color: '#555' }}>营收</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
            ¥{dept.revenue.toFixed(0)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: '#555' }}>成本</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#888' }}>
            ¥{dept.cost.toFixed(0)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: '#555' }}>毛利</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: c.text }}>
            ¥{dept.profit.toFixed(0)}
          </div>
        </div>
      </div>

      {/* 出品量 */}
      <div style={{ fontSize: 12, color: '#444', marginTop: 10 }}>
        出品 {dept.dish_count} 道
      </div>
    </div>
  );
}

// ─── Main ───

export function StationProfitPage() {
  const [period, setPeriod] = useState<Period>('today');
  const [summary, setSummary] = useState<ProfitSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (p: Period) => {
    setLoading(true);
    if (!STORE_ID) {
      setSummary(MOCK_SUMMARY);
      setLoading(false);
      return;
    }
    try {
      const res = await txFetch(
        `${API_BASE}/api/v1/kds/station-profit?store_id=${STORE_ID}&period=${p}`,
        undefined,
        TENANT_ID,
      );
      if (res.ok) {
        setSummary(res.data as ProfitSummary);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(period);
  }, [fetchData, period]);

  const PERIOD_LABELS: Record<Period, string> = { today: '今日', week: '本周', month: '本月' };

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
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>档口毛利核算</span>
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
              }}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </header>

      {/* 全店汇总 */}
      {summary && (
        <div
          style={{
            background: '#111',
            borderBottom: '1px solid #1A1A1A',
            padding: '14px 20px',
            display: 'flex',
            gap: 40,
            flexShrink: 0,
          }}
        >
          <div>
            <div style={{ fontSize: 13, color: '#555' }}>全店营收</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#fff', fontFamily: 'monospace' }}>
              ¥{summary.total_revenue.toFixed(0)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 13, color: '#555' }}>全店毛利</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#30D158', fontFamily: 'monospace' }}>
              ¥{summary.total_profit.toFixed(0)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 13, color: '#555' }}>平均毛利率</div>
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                fontFamily: 'monospace',
                color:
                  summary.avg_margin_pct >= 60
                    ? '#30D158'
                    : summary.avg_margin_pct >= 40
                    ? '#FF9F0A'
                    : '#FF3B30',
              }}
            >
              {summary.avg_margin_pct.toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {/* 档口列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: 16,
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {error && (
          <div style={{ color: '#FF3B30', marginBottom: 12, fontSize: 14 }}>{error}</div>
        )}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#555' }}>计算中…</div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 12,
            }}
          >
            {(summary?.depts ?? []).map((dept) => (
              <ProfitCard key={dept.dept_id} dept={dept} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
