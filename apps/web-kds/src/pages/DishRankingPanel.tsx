/**
 * 实时三榜单面板 — 畅销 / 滞销 / 退菜
 *
 * 可嵌入 StatsPage 或作为独立 Tab 展示。
 * 三列横排：畅销榜 / 滞销榜 / 退菜榜
 * 每5分钟自动刷新，底部显示更新时间戳。
 *
 * 数据流：GET /api/v1/kds-analytics/rankings/{storeId}
 */
import { useEffect, useState, useCallback } from 'react';

// ── 类型定义 ─────────────────────────────────────────────────

interface DishRankItem {
  dish_id: string;
  dish_name: string;
  count: number;
  rate: number;   // 退菜率 0.0~1.0
  rank: number;
}

interface DishRankings {
  hot: DishRankItem[];
  cold: DishRankItem[];
  remake: DishRankItem[];
  as_of: string;
}

interface DishRankingPanelProps {
  storeId: string;
  tenantId: string;
  /** 可选：只显示前 N 条，默认 5 */
  topN?: number;
  /** 可选：自动刷新间隔毫秒，默认 300000（5分钟） */
  refreshMs?: number;
}

// ── 样式常量 ─────────────────────────────────────────────────

const S = {
  root: {
    background: '#0B1A20',
    color: '#E0E0E0',
    fontFamily: 'Noto Sans SC, sans-serif',
    padding: 16,
  } as React.CSSProperties,
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  } as React.CSSProperties,
  title: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#fff',
    margin: 0,
  } as React.CSSProperties,
  columns: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 12,
  } as React.CSSProperties,
  column: {
    background: '#112B36',
    borderRadius: 10,
    padding: 14,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  } as React.CSSProperties,
  columnTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    paddingBottom: 8,
    borderBottom: '2px solid',
    marginBottom: 4,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  } as React.CSSProperties,
  rankRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 0',
    borderBottom: '1px solid #1A3A48',
  } as React.CSSProperties,
  badge: {
    width: 22,
    height: 22,
    borderRadius: 11,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 12,
    fontWeight: 'bold',
    flexShrink: 0,
  } as React.CSSProperties,
  dishName: {
    flex: 1,
    fontSize: 15,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  countHot: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#52c41a',
    fontFamily: 'JetBrains Mono, monospace',
    flexShrink: 0,
  } as React.CSSProperties,
  countCold: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#8899A6',
    fontFamily: 'JetBrains Mono, monospace',
    flexShrink: 0,
  } as React.CSSProperties,
  countRemake: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#ff4d4f',
    fontFamily: 'JetBrains Mono, monospace',
    flexShrink: 0,
  } as React.CSSProperties,
  footer: {
    marginTop: 16,
    textAlign: 'center' as const,
    fontSize: 12,
    color: '#8899A6',
  } as React.CSSProperties,
  emptyRow: {
    textAlign: 'center' as const,
    color: '#8899A6',
    fontSize: 14,
    padding: '20px 0',
  } as React.CSSProperties,
  loadingRow: {
    textAlign: 'center' as const,
    color: '#8899A6',
    fontSize: 14,
    padding: '20px 0',
  } as React.CSSProperties,
  errorRow: {
    textAlign: 'center' as const,
    color: '#ff4d4f',
    fontSize: 13,
    padding: '12px 0',
  } as React.CSSProperties,
};

// 排名徽章颜色
const BADGE_COLORS = ['#E8A020', '#8899A6', '#CD7F32', '#556677', '#445566'];

function badgeStyle(rank: number): React.CSSProperties {
  return {
    ...S.badge,
    background: BADGE_COLORS[rank - 1] ?? '#223344',
    color: rank <= 3 ? '#fff' : '#aaa',
  };
}

// ── 子组件：单列榜单 ─────────────────────────────────────────

interface RankColumnProps {
  title: string;
  titleColor: string;
  items: DishRankItem[];
  topN: number;
  loading: boolean;
  renderCount: (item: DishRankItem) => React.ReactNode;
}

function RankColumn({ title, titleColor, items, topN, loading, renderCount }: RankColumnProps) {
  const visible = items.slice(0, topN);

  return (
    <div style={S.column}>
      <div style={{ ...S.columnTitle, borderColor: titleColor, color: titleColor }}>
        {title}
      </div>

      {loading && <div style={S.loadingRow}>加载中...</div>}

      {!loading && visible.length === 0 && (
        <div style={S.emptyRow}>暂无数据</div>
      )}

      {!loading && visible.map((item) => (
        <div key={item.dish_id || item.dish_name} style={S.rankRow}>
          <div style={badgeStyle(item.rank)}>{item.rank}</div>
          <span style={S.dishName} title={item.dish_name}>{item.dish_name}</span>
          {renderCount(item)}
        </div>
      ))}
    </div>
  );
}

// ── 主组件 ───────────────────────────────────────────────────

export function DishRankingPanel({
  storeId,
  tenantId,
  topN = 5,
  refreshMs = 300_000,
}: DishRankingPanelProps) {
  const [rankings, setRankings] = useState<DishRankings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchRankings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/kds-analytics/rankings/${storeId}`,
        { headers: { 'X-Tenant-ID': tenantId } }
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: DishRankings = await res.json();
      setRankings(data);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId, tenantId]);

  // 首次加载 + 定时刷新
  useEffect(() => {
    fetchRankings();
    const timer = setInterval(fetchRankings, refreshMs);
    return () => clearInterval(timer);
  }, [fetchRankings, refreshMs]);

  const hot = rankings?.hot ?? [];
  const cold = rankings?.cold ?? [];
  const remake = rankings?.remake ?? [];

  return (
    <div style={S.root}>
      {/* 标题行 */}
      <div style={S.header}>
        <h2 style={S.title}>菜品实时榜单</h2>
        <button
          onClick={fetchRankings}
          disabled={loading}
          style={{
            padding: '6px 14px',
            background: 'transparent',
            border: '1px solid #8899A6',
            borderRadius: 6,
            color: '#8899A6',
            fontSize: 13,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? '刷新中...' : '立即刷新'}
        </button>
      </div>

      {error && <div style={S.errorRow}>加载失败：{error}</div>}

      {/* 三列榜单 */}
      <div style={S.columns}>
        <RankColumn
          title="🔥 畅销榜"
          titleColor="#52c41a"
          items={hot}
          topN={topN}
          loading={loading}
          renderCount={(item) => (
            <span style={S.countHot}>今日 {item.count} 单</span>
          )}
        />

        <RankColumn
          title="🧊 滞销榜"
          titleColor="#8899A6"
          items={cold}
          topN={topN}
          loading={loading}
          renderCount={(item) => (
            <span style={S.countCold}>今日仅 {item.count} 单</span>
          )}
        />

        <RankColumn
          title="↩ 退菜榜"
          titleColor="#ff4d4f"
          items={remake}
          topN={topN}
          loading={loading}
          renderCount={(item) => (
            <span style={S.countRemake}>{(item.rate * 100).toFixed(1)}%</span>
          )}
        />
      </div>

      {/* 底部时间戳 */}
      <div style={S.footer}>
        {lastRefresh
          ? `数据更新时间：${lastRefresh.toLocaleTimeString('zh-CN')} · 每5分钟自动刷新`
          : '数据加载中...'}
      </div>
    </div>
  );
}
