import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';
import type { SeafoodItem, SeafoodBoard } from '../api/menuWallApi';
import { getSeafoodBoard } from '../api/menuWallApi';

/** 自动滚动间隔 */
const SCROLL_INTERVAL = 15_000;
const REFRESH_INTERVAL = 30_000;
const VISIBLE_ROWS = 10;

/** Mock数据 */
function getMockSeafood(): SeafoodItem[] {
  const items = [
    { name: '波士顿龙虾', price: 268, prev: 258, status: 'alive' as const },
    { name: '帝王蟹', price: 588, prev: 598, status: 'alive' as const },
    { name: '澳洲龙虾', price: 888, prev: 888, status: 'alive' as const },
    { name: '东星斑', price: 368, prev: 348, status: 'alive' as const },
    { name: '多宝鱼', price: 128, prev: 138, status: 'alive' as const },
    { name: '基围虾', price: 88, prev: 88, status: 'alive' as const },
    { name: '皮皮虾', price: 98, prev: 108, status: 'weak' as const },
    { name: '花甲', price: 38, prev: 38, status: 'alive' as const },
    { name: '生蚝(打)', price: 68, prev: 58, status: 'alive' as const },
    { name: '扇贝', price: 48, prev: 48, status: 'alive' as const },
    { name: '鲍鱼(只)', price: 38, prev: 42, status: 'alive' as const },
    { name: '大闸蟹', price: 168, prev: 168, status: 'sold_out' as const },
    { name: '象拔蚌', price: 328, prev: 298, status: 'alive' as const },
    { name: '竹节虾', price: 158, prev: 148, status: 'weak' as const },
    { name: '面包蟹', price: 198, prev: 198, status: 'alive' as const },
  ];
  return items.map((item, i) => ({
    id: `sf-${i}`,
    name: item.name,
    price: item.price,
    previousPrice: item.prev,
    unit: '元/斤',
    status: item.status,
    updatedAt: new Date().toISOString(),
  }));
}

export default function SeafoodPriceBoard() {
  const [items, setItems] = useState<SeafoodItem[]>([]);
  const [scrollOffset, setScrollOffset] = useState(0);
  const [updatedAt, setUpdatedAt] = useState('');
  const [isTransitioning, setIsTransitioning] = useState(false);
  const scrollTimerRef = useRef<ReturnType<typeof setInterval>>();

  const loadData = useCallback(async () => {
    try {
      const data: SeafoodBoard = await getSeafoodBoard();
      setItems(data.items);
      setUpdatedAt(new Date(data.updatedAt).toLocaleTimeString('zh-CN'));
    } catch {
      setItems(getMockSeafood());
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN'));
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [loadData]);

  /** 自动滚动 */
  useEffect(() => {
    if (items.length <= VISIBLE_ROWS) return;

    scrollTimerRef.current = setInterval(() => {
      setIsTransitioning(true);
      setTimeout(() => {
        setScrollOffset((prev) => {
          const maxOffset = items.length - VISIBLE_ROWS;
          return prev >= maxOffset ? 0 : prev + VISIBLE_ROWS;
        });
        setIsTransitioning(false);
      }, 400);
    }, SCROLL_INTERVAL);

    return () => {
      if (scrollTimerRef.current) clearInterval(scrollTimerRef.current);
    };
  }, [items.length]);

  const visibleItems = items.slice(scrollOffset, scrollOffset + VISIBLE_ROWS);

  const getPriceChange = (item: SeafoodItem) => {
    const diff = item.price - item.previousPrice;
    if (diff > 0) return { symbol: '↑', color: 'var(--tx-seafood-up)', diff: `+${diff}` };
    if (diff < 0) return { symbol: '↓', color: 'var(--tx-seafood-down)', diff: `${diff}` };
    return { symbol: '—', color: 'var(--tx-seafood-flat)', diff: '0' };
  };

  const getStatusText = (status: SeafoodItem['status']) => {
    switch (status) {
      case 'alive': return { text: '鲜活', color: '#00CC66' };
      case 'weak': return { text: '偏弱', color: '#FFAA00' };
      case 'sold_out': return { text: '售罄', color: '#FF4444' };
    }
  };

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: '#0A0A0A',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: 'var(--tx-font)',
    overflow: 'hidden',
  };

  const headerStyle: CSSProperties = {
    padding: '24px 40px',
    borderBottom: '2px solid #1A1A1A',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  };

  const tableHeaderStyle: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: '2fr 1.2fr 1fr 0.8fr',
    padding: '12px 40px',
    background: '#111111',
    borderBottom: '1px solid #222',
    fontSize: 18,
    fontWeight: 600,
    color: '#888888',
    flexShrink: 0,
  };

  const rowStyle = (index: number): CSSProperties => ({
    display: 'grid',
    gridTemplateColumns: '2fr 1.2fr 1fr 0.8fr',
    padding: '16px 40px',
    borderBottom: '1px solid #1A1A1A',
    background: index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
    alignItems: 'center',
    transition: 'opacity 0.4s ease, transform 0.4s ease',
    opacity: isTransitioning ? 0 : 1,
    transform: isTransitioning ? 'translateY(-10px)' : 'translateY(0)',
    animation: `tx-fade-in 0.3s ease-out ${index * 50}ms both`,
  });

  return (
    <div style={containerStyle}>
      {/* 顶部 */}
      <div style={headerStyle}>
        <div>
          <div style={{ fontSize: 36, fontWeight: 700, color: '#FFFFFF', letterSpacing: 4 }}>
            今日海鲜时价
          </div>
          <div style={{ fontSize: 16, color: '#666', marginTop: 4 }}>
            LIVE SEAFOOD MARKET PRICE
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 16, color: '#888' }}>最近更新</div>
          <div style={{ fontSize: 24, color: '#FFD700', fontWeight: 600 }}>{updatedAt}</div>
          <div style={{ fontSize: 14, color: '#444', marginTop: 4 }}>
            共 {items.length} 种 · 第 {Math.floor(scrollOffset / VISIBLE_ROWS) + 1}/{Math.ceil(items.length / VISIBLE_ROWS)} 页
          </div>
        </div>
      </div>

      {/* 表头 */}
      <div style={tableHeaderStyle}>
        <span>品名</span>
        <span style={{ textAlign: 'right' }}>单价</span>
        <span style={{ textAlign: 'center' }}>涨跌</span>
        <span style={{ textAlign: 'center' }}>状态</span>
      </div>

      {/* 数据行 */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {visibleItems.map((item, i) => {
          const change = getPriceChange(item);
          const status = getStatusText(item.status);
          const isSoldOut = item.status === 'sold_out';

          return (
            <div key={`${item.id}-${scrollOffset}`} style={rowStyle(i)}>
              <span style={{
                fontSize: 26,
                fontWeight: 600,
                color: isSoldOut ? '#444' : '#FFFFFF',
                textDecoration: isSoldOut ? 'line-through' : 'none',
              }}>
                {item.name}
              </span>
              <span style={{
                textAlign: 'right',
                fontSize: 30,
                fontWeight: 700,
                fontVariantNumeric: 'tabular-nums',
                color: isSoldOut ? '#444' : change.color,
              }}>
                ¥{item.price}
                <span style={{ fontSize: 16, fontWeight: 400, color: '#666', marginLeft: 4 }}>
                  /{item.unit.replace('元/', '')}
                </span>
              </span>
              <span style={{
                textAlign: 'center',
                fontSize: 24,
                fontWeight: 700,
                color: isSoldOut ? '#333' : change.color,
                fontVariantNumeric: 'tabular-nums',
              }}>
                {change.symbol} {change.diff}
              </span>
              <span style={{
                textAlign: 'center',
                fontSize: 20,
                fontWeight: 600,
                color: status.color,
              }}>
                {status.text}
              </span>
            </div>
          );
        })}
      </div>

      {/* 底部装饰线 */}
      <div style={{
        height: 4,
        background: 'linear-gradient(90deg, transparent, var(--tx-primary), transparent)',
        flexShrink: 0,
      }} />
    </div>
  );
}
