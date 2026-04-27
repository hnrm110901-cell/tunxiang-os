/**
 * ListPanel — 通用左侧列表面板
 * Workspace 双栏布局的左栏：标题 + 筛选 chips + 可搜索列表
 */
import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import type { ListItem } from '../types/hub';

/* ─── 状态颜色映射 ─── */
const STATUS_COLOR: Record<ListItem['status'], string> = {
  online:  '#22C55E',
  offline: '#647985',
  warning: '#F59E0B',
  error:   '#EF4444',
  pending: '#3B82F6',
  unknown: '#647985',
};

/* ─── Props ─── */
interface ListPanelProps {
  title: string;
  items: ListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading?: boolean;
  filterChips?: { key: string; label: string }[];
}

/* ─── 样式 ─── */
const sty = {
  panel: {
    width: 300,
    minWidth: 300,
    height: '100%',
    background: '#0E1E24',
    borderRight: '1px solid #1A3540',
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  } as React.CSSProperties,

  header: {
    padding: '14px 16px 10px',
    borderBottom: '1px solid #1A3540',
  } as React.CSSProperties,

  title: {
    fontSize: 14,
    fontWeight: 700,
    color: '#E6EDF1',
    marginBottom: 10,
  } as React.CSSProperties,

  searchInput: {
    width: '100%',
    boxSizing: 'border-box' as const,
    background: '#132932',
    border: '1px solid #1A3540',
    borderRadius: 6,
    padding: '7px 10px',
    fontSize: 13,
    color: '#E6EDF1',
    outline: 'none',
  } as React.CSSProperties,

  chips: {
    display: 'flex',
    gap: 6,
    padding: '8px 16px 4px',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,

  chip: (active: boolean): React.CSSProperties => ({
    padding: '3px 10px',
    borderRadius: 12,
    fontSize: 12,
    cursor: 'pointer',
    border: '1px solid',
    borderColor: active ? '#FF6B2C' : '#1A3540',
    background: active ? 'rgba(255,107,44,0.15)' : 'transparent',
    color: active ? '#FF6B2C' : '#94A8B3',
    transition: 'all 0.15s',
  }),

  list: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '4px 0',
  } as React.CSSProperties,

  row: (selected: boolean): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 16px',
    cursor: 'pointer',
    borderLeft: `3px solid ${selected ? '#FF6B2C' : 'transparent'}`,
    background: selected ? 'rgba(255,107,44,0.08)' : 'transparent',
    transition: 'all 0.15s',
  }),

  dot: (color: string): React.CSSProperties => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: color,
    flexShrink: 0,
  }),

  rowName: {
    fontSize: 13,
    fontWeight: 600,
    color: '#E6EDF1',
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,

  rowMeta: {
    fontSize: 11,
    color: '#647985',
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,

  empty: {
    padding: 24,
    textAlign: 'center' as const,
    color: '#647985',
    fontSize: 13,
  } as React.CSSProperties,

  loading: {
    padding: 24,
    textAlign: 'center' as const,
    color: '#94A8B3',
    fontSize: 13,
  } as React.CSSProperties,
};

/* ─── 虚拟滚动 Hook（简易版，行高固定 52px） ─── */
const ROW_HEIGHT = 52;

function useVirtualScroll(totalItems: number, containerRef: React.RefObject<HTMLDivElement | null>) {
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(600);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height);
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [containerRef]);

  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - 2);
  const visibleCount = Math.ceil(containerHeight / ROW_HEIGHT) + 4;
  const endIdx = Math.min(totalItems, startIdx + visibleCount);

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  return { startIdx, endIdx, onScroll, totalHeight: totalItems * ROW_HEIGHT };
}

/* ─── Component ─── */
export function ListPanel({ title, items, selectedId, onSelect, loading, filterChips }: ListPanelProps) {
  const [search, setSearch] = useState('');
  const [activeChip, setActiveChip] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    let result = items;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (it) =>
          it.name.toLowerCase().includes(q) ||
          (it.subtitle && it.subtitle.toLowerCase().includes(q)),
      );
    }
    if (activeChip) {
      result = result.filter((it) => it.status === activeChip);
    }
    return result;
  }, [items, search, activeChip]);

  const { startIdx, endIdx, onScroll, totalHeight } = useVirtualScroll(filtered.length, listRef);

  if (loading) {
    return (
      <div style={sty.panel}>
        <div style={sty.header}>
          <div style={sty.title}>{title}</div>
        </div>
        <div style={sty.loading}>加载中...</div>
      </div>
    );
  }

  return (
    <div style={sty.panel}>
      {/* Header */}
      <div style={sty.header}>
        <div style={sty.title}>{title} ({filtered.length})</div>
        <input
          style={sty.searchInput}
          placeholder="搜索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Filter chips */}
      {filterChips && filterChips.length > 0 && (
        <div style={sty.chips}>
          <span
            style={sty.chip(activeChip === null)}
            onClick={() => setActiveChip(null)}
          >
            全部
          </span>
          {filterChips.map((c) => (
            <span
              key={c.key}
              style={sty.chip(activeChip === c.key)}
              onClick={() => setActiveChip(activeChip === c.key ? null : c.key)}
            >
              {c.label}
            </span>
          ))}
        </div>
      )}

      {/* List with virtual scroll */}
      <div ref={listRef} style={sty.list} onScroll={onScroll}>
        {filtered.length === 0 ? (
          <div style={sty.empty}>无匹配项</div>
        ) : (
          <div style={{ height: totalHeight, position: 'relative' }}>
            {filtered.slice(startIdx, endIdx).map((item, i) => (
              <div
                key={item.id}
                style={{
                  ...sty.row(item.id === selectedId),
                  position: 'absolute',
                  top: (startIdx + i) * ROW_HEIGHT,
                  left: 0,
                  right: 0,
                  height: ROW_HEIGHT,
                }}
                onClick={() => onSelect(item.id)}
              >
                <div style={sty.dot(STATUS_COLOR[item.status] || '#647985')} />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <div style={sty.rowName}>{item.name}</div>
                  {item.subtitle && <div style={sty.rowMeta}>{item.subtitle}</div>}
                </div>
                {item.meta && (
                  <div style={{ fontSize: 11, color: '#94A8B3', flexShrink: 0 }}>{item.meta}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
