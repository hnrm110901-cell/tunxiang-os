/**
 * TankStatusView — 鱼缸可视化组件
 *
 * 横向滚动卡片列表，每张卡片展示一个鱼缸区域的实时库存与价格。
 * 可嵌入 OrderPage / LiveSeafoodOrderPage 等页面。
 *
 * 设计规范：
 *   - 深色主题，bg=#0B1A20, card=#112228, accent=#FF6B35
 *   - 卡片宽140px，固定高度
 *   - 库存紧张：橙色 border + badge
 *   - 无库存：灰色遮罩
 *   - 多品种鱼缸支持展开子列表
 */
import { useState, useEffect, useCallback } from 'react';
import {
  fetchTankList,
  fetchTankDishes,
  isTankEmpty,
  isTankLowStock,
  tankStockLabel,
  type TankZone,
  type LiveSeafoodDish,
} from '../api/liveSeafoodApi';

// ─── Design Tokens ────────────────────────────────────────────────────────────

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  yellow: '#facc15',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#ef4444',
  orange: '#f97316',
};

// ─── Props ────────────────────────────────────────────────────────────────────

export interface TankStatusViewProps {
  storeId: string;
  /** 选中某鱼缸的一个菜品时回调 */
  onSelectDish: (dish: LiveSeafoodDish, tankZone: string) => void;
  /** 可选：高亮展开某鱼缸（如扫码后自动定位） */
  defaultZoneCode?: string | null;
}

// ─── 辅助：鱼缸图标 emoji（按品种名模糊匹配） ────────────────────────────────

function tankEmoji(tank: TankZone): string {
  const name = tank.zone_name + tank.featured_dish;
  if (/虾/.test(name)) return '\uD83E\uDD90'; // 🦐
  if (/龙虾/.test(name)) return '\uD83E\uDD9E'; // 🦞
  if (/蟹|螃蟹/.test(name)) return '\uD83E\uDD80'; // 🦀
  if (/贝|蛤|蚝|生蚝/.test(name)) return '\uD83E\uDDAA'; // 🦪
  if (/章鱼|墨鱼|鱿鱼/.test(name)) return '\uD83D\uDC19'; // 🐙
  return '\uD83D\uDC1F'; // 🐟 default
}

// ─── 子组件：单个鱼缸卡片 ────────────────────────────────────────────────────

interface TankCardProps {
  tank: TankZone;
  isExpanded: boolean;
  onToggle: () => void;
  onSelectDish: (dish: LiveSeafoodDish, zoneCode: string) => void;
  storeId: string;
}

function TankCard({ tank, isExpanded, onToggle, onSelectDish, storeId }: TankCardProps) {
  const [dishes, setDishes] = useState<LiveSeafoodDish[]>([]);
  const [loadingDishes, setLoadingDishes] = useState(false);

  const empty = isTankEmpty(tank);
  const low = isTankLowStock(tank);
  const stockLabel = tankStockLabel(tank);

  // 展开时加载菜品列表
  useEffect(() => {
    if (!isExpanded) return;
    setLoadingDishes(true);
    fetchTankDishes(tank.zone_code, storeId)
      .then(res => setDishes(res.dishes))
      .catch(() => setDishes([]))
      .finally(() => setLoadingDishes(false));
  }, [isExpanded, tank.zone_code, storeId]);

  const borderColor = empty ? C.border : low ? C.orange : C.border;
  const cardOpacity = empty ? 0.55 : 1;

  return (
    <div
      style={{
        flexShrink: 0,
        width: 140,
        display: 'flex',
        flexDirection: 'column',
        opacity: cardOpacity,
      }}
    >
      {/* ── 主卡片 ── */}
      <div
        style={{
          background: C.card,
          border: `1.5px solid ${borderColor}`,
          borderRadius: 12,
          padding: 12,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          position: 'relative',
          boxShadow: low ? `0 0 0 1px ${C.orange}44` : undefined,
        }}
      >
        {/* 库存紧张 badge */}
        {low && !empty && (
          <span
            style={{
              position: 'absolute',
              top: 6,
              right: 6,
              fontSize: 11,
              padding: '1px 5px',
              borderRadius: 4,
              background: C.orange,
              color: C.white,
              fontWeight: 700,
            }}
          >
            库存紧张
          </span>
        )}

        {/* emoji */}
        <span style={{ fontSize: 32, lineHeight: 1 }}>{tankEmoji(tank)}</span>

        {/* 名称 */}
        <div
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: C.white,
            lineHeight: 1.2,
            wordBreak: 'break-all',
          }}
        >
          {tank.zone_name}
        </div>

        {/* 编码 */}
        <div style={{ fontSize: 14, color: C.muted }}>{tank.zone_code}</div>

        {/* 库存 */}
        <div
          style={{
            fontSize: 14,
            color: empty ? C.muted : low ? C.orange : C.text,
            fontWeight: 500,
          }}
        >
          {stockLabel}
        </div>

        {/* 价格 */}
        <div
          style={{
            fontSize: 16,
            fontWeight: 700,
            color: empty ? C.muted : C.accent,
          }}
        >
          {tank.price_display}
        </div>

        {/* 无库存遮罩文字 */}
        {empty && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 12,
              background: 'rgba(11,26,32,0.55)',
              pointerEvents: 'none',
            }}
          >
            <span
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: C.muted,
                background: C.card,
                padding: '4px 8px',
                borderRadius: 6,
              }}
            >
              暂无
            </span>
          </div>
        )}

        {/* 选择按钮 */}
        {!empty && (
          <button
            onClick={onToggle}
            style={{
              minHeight: 48,
              borderRadius: 8,
              border: `1px solid ${C.accent}`,
              background: isExpanded ? C.accent : 'transparent',
              color: isExpanded ? C.white : C.accent,
              fontSize: 16,
              fontWeight: 700,
              cursor: 'pointer',
              marginTop: 4,
            }}
          >
            {isExpanded ? '收起' : '选择'}
          </button>
        )}
      </div>

      {/* ── 展开：菜品子列表 ── */}
      {isExpanded && (
        <div
          style={{
            marginTop: 8,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          {loadingDishes && (
            <div
              style={{
                textAlign: 'center',
                fontSize: 14,
                color: C.muted,
                padding: '8px 0',
              }}
            >
              加载中...
            </div>
          )}
          {!loadingDishes &&
            dishes.map(dish => (
              <button
                key={dish.dish_id}
                onClick={() => onSelectDish(dish, tank.zone_code)}
                disabled={dish.live_stock_count === 0 && dish.live_stock_weight_g === 0}
                style={{
                  width: '100%',
                  minHeight: 64,
                  padding: '8px 10px',
                  borderRadius: 8,
                  background: C.bg,
                  border: `1px solid ${C.border}`,
                  textAlign: 'left',
                  cursor:
                    dish.live_stock_count === 0 && dish.live_stock_weight_g === 0
                      ? 'not-allowed'
                      : 'pointer',
                  opacity:
                    dish.live_stock_count === 0 && dish.live_stock_weight_g === 0 ? 0.45 : 1,
                }}
              >
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: 600,
                    color: C.white,
                    marginBottom: 2,
                  }}
                >
                  {dish.dish_name}
                </div>
                <div style={{ fontSize: 14, color: C.accent, fontWeight: 700 }}>
                  {dish.price_display}
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function TankStatusView({
  storeId,
  onSelectDish,
  defaultZoneCode,
}: TankStatusViewProps) {
  const [tanks, setTanks] = useState<TankZone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedZone, setExpandedZone] = useState<string | null>(defaultZoneCode ?? null);

  const loadTanks = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchTankList(storeId)
      .then(res => {
        setTanks(res.tanks);
        // 如果有默认展开区域，确保它在列表中存在
        if (defaultZoneCode) {
          const found = res.tanks.find(t => t.zone_code === defaultZoneCode);
          if (found && !isTankEmpty(found)) {
            setExpandedZone(defaultZoneCode);
          }
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '加载鱼缸数据失败';
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [storeId, defaultZoneCode]);

  useEffect(() => {
    loadTanks();
  }, [loadTanks]);

  const handleToggle = (zoneCode: string) => {
    setExpandedZone(prev => (prev === zoneCode ? null : zoneCode));
  };

  // ── 加载状态 ──
  if (loading) {
    return (
      <div
        style={{
          padding: '20px 16px',
          display: 'flex',
          gap: 12,
          overflowX: 'auto',
        }}
      >
        {[1, 2, 3].map(i => (
          <div
            key={i}
            style={{
              flexShrink: 0,
              width: 140,
              height: 200,
              borderRadius: 12,
              background: C.card,
              border: `1px solid ${C.border}`,
              opacity: 0.4 + i * 0.15,
            }}
          />
        ))}
      </div>
    );
  }

  // ── 错误状态 ──
  if (error) {
    return (
      <div
        style={{
          padding: '16px',
          textAlign: 'center',
          color: C.muted,
          fontSize: 16,
        }}
      >
        <div style={{ marginBottom: 8 }}>{error}</div>
        <button
          onClick={loadTanks}
          style={{
            minHeight: 48,
            padding: '0 20px',
            borderRadius: 8,
            background: C.accent,
            border: 'none',
            color: C.white,
            fontSize: 16,
            cursor: 'pointer',
          }}
        >
          重试
        </button>
      </div>
    );
  }

  // ── 无数据 ──
  if (tanks.length === 0) {
    return (
      <div
        style={{
          padding: '24px 16px',
          textAlign: 'center',
          color: C.muted,
          fontSize: 16,
        }}
      >
        该门店暂无鱼缸区域配置
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {/* 标题行 */}
      <div
        style={{
          padding: '12px 16px 8px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>
          活鲜选品
        </span>
        <span style={{ fontSize: 14, color: C.muted }}>
          {tanks.filter(t => !isTankEmpty(t)).length}/{tanks.length} 个缸有货
        </span>
      </div>

      {/* 横向滚动卡片列表 */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          overflowX: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '0 16px 16px',
          alignItems: 'flex-start',
        } as React.CSSProperties}
      >
        {tanks.map(tank => (
          <TankCard
            key={tank.zone_code}
            tank={tank}
            isExpanded={expandedZone === tank.zone_code}
            onToggle={() => handleToggle(tank.zone_code)}
            onSelectDish={onSelectDish}
            storeId={storeId}
          />
        ))}
      </div>
    </div>
  );
}
