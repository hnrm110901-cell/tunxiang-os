/**
 * PrepRecommendationPanel — 预制量智能推荐面板
 *
 * 天财商龙特色功能：基于历史销量+节假日+预订的备料建议，
 * 直接展示在各档口KDS屏幕上，厨师开班即可按此备料。
 *
 * 布局：
 *   按推荐数量倒序排列菜品卡片
 *   每卡片：菜名 + 推荐份数（大字）+ 基线 + 修正系数说明
 *   颜色：推荐数高 → 橙色，低 → 灰色
 */
import { useCallback, useEffect, useState } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface PrepItem {
  dish_id: string;
  dish_name: string;
  dept_id: string;
  dept_name: string;
  recommended_qty: number;
  baseline_qty: number;
  boost_factor: number;
  reason: string;
}

// ─── Constants ───

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';
const STORE_ID = (window as any).__STORE_ID__ || '';
const DEPT_ID = (window as any).__KDS_DEPT_ID__ || '';

const MOCK_DATA: PrepItem[] = [
  { dish_id: 'd1', dish_name: '剁椒鱼头', dept_id: 'dp1', dept_name: '热菜档', recommended_qty: 15, baseline_qty: 11.2, boost_factor: 1.3, reason: '节假日+30%、安全系数+10%' },
  { dish_id: 'd2', dish_name: '口味虾', dept_id: 'dp1', dept_name: '热菜档', recommended_qty: 22, baseline_qty: 18.5, boost_factor: 1.3, reason: '节假日+30%、安全系数+10%' },
  { dish_id: 'd3', dish_name: '清蒸鲈鱼', dept_id: 'dp1', dept_name: '热菜档', recommended_qty: 10, baseline_qty: 8.9, boost_factor: 1.1, reason: '安全系数+10%' },
  { dish_id: 'd4', dish_name: '烤乳猪', dept_id: 'dp2', dept_name: '烤制档', recommended_qty: 6, baseline_qty: 4.2, boost_factor: 1.43, reason: '预订加成+20%、节假日+20%、安全系数+10%' },
  { dish_id: 'd5', dish_name: '白灼基围虾', dept_id: 'dp1', dept_name: '热菜档', recommended_qty: 12, baseline_qty: 10.8, boost_factor: 1.1, reason: '安全系数+10%' },
];

// ─── Sub-components ───

function PrepCard({ item, rank }: { item: PrepItem; rank: number }) {
  const isHigh = item.recommended_qty >= 15;
  const isMid = item.recommended_qty >= 8 && item.recommended_qty < 15;

  const qtyColor = isHigh ? '#FF6B35' : isMid ? '#FF9F0A' : '#8E8E93';
  const boostPct = Math.round((item.boost_factor - 1) * 100);

  return (
    <div
      style={{
        background: '#1A1A1A',
        border: `1px solid ${isHigh ? '#FF6B35' : '#2A2A2A'}`,
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        minHeight: 80,
      }}
    >
      {/* 序号 */}
      <div
        style={{
          width: 28,
          textAlign: 'center',
          fontSize: 14,
          color: '#444',
          flexShrink: 0,
        }}
      >
        {rank}
      </div>

      {/* 菜名 + 档口 */}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 4 }}>
          {item.dish_name}
        </div>
        <div style={{ fontSize: 13, color: '#555' }}>
          {item.dept_name}
          {item.reason && (
            <span style={{ color: '#664422', marginLeft: 8 }}>· {item.reason}</span>
          )}
        </div>
      </div>

      {/* 推荐份数（主数字） */}
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div
          style={{
            fontSize: 44,
            fontWeight: 700,
            color: qtyColor,
            lineHeight: 1,
            fontFamily: 'monospace',
          }}
        >
          {item.recommended_qty}
        </div>
        <div style={{ fontSize: 12, color: '#444' }}>
          份 · 基线 {item.baseline_qty}
          {boostPct > 0 && (
            <span style={{ color: '#FF9F0A', marginLeft: 4 }}>+{boostPct}%</span>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main ───

export function PrepRecommendationPanel() {
  const [items, setItems] = useState<PrepItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [targetDate] = useState(() => new Date().toLocaleDateString('zh-CN'));

  const fetchRec = useCallback(async () => {
    setLoading(true);
    if (!STORE_ID) {
      setItems(MOCK_DATA);
      setLoading(false);
      return;
    }
    try {
      const params = new URLSearchParams({ store_id: STORE_ID });
      if (DEPT_ID) params.set('dept_id', DEPT_ID);
      const res = await txFetch(
        `${API_BASE}/api/v1/kds/prep/recommendations?${params.toString()}`,
        undefined,
        TENANT_ID,
      );
      if (res.ok) {
        setItems(res.data.items as PrepItem[]);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRec();
  }, [fetchRec]);

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
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>
            今日备料推荐
          </div>
          <div style={{ fontSize: 13, color: '#555', marginTop: 2 }}>
            基于历史4周销量 · {targetDate}
          </div>
        </div>
        <button
          onClick={fetchRec}
          style={{
            minHeight: 48,
            padding: '0 20px',
            background: '#1A1A1A',
            color: '#888',
            border: '1px solid #2A2A2A',
            borderRadius: 8,
            fontSize: 15,
            cursor: 'pointer',
          }}
        >
          刷新
        </button>
      </header>

      {/* 说明提示 */}
      <div
        style={{
          background: '#0A1520',
          border: '1px solid #1A3050',
          margin: 16,
          borderRadius: 8,
          padding: '10px 16px',
          fontSize: 13,
          color: '#6699CC',
        }}
      >
        推荐数量 = 历史平均 × 节假日系数 × 预订加成 × 1.1安全系数。仅供参考，实际备料以总厨判断为准。
      </div>

      {/* 列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0 16px 16px',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {error && (
          <div style={{ color: '#FF3B30', marginBottom: 12, fontSize: 14 }}>{error}</div>
        )}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#555' }}>计算推荐数量中…</div>
        ) : items.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#333', fontSize: 18 }}>
            暂无历史数据，无法生成推荐
          </div>
        ) : (
          items.map((item, idx) => (
            <div key={item.dish_id} style={{ marginBottom: 8 }}>
              <PrepCard item={item} rank={idx + 1} />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
