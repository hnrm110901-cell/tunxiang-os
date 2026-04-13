/**
 * QuickOrderPanel — 快速下单面板（移动银台Pro 模块2.2）
 *
 * 常用菜品前10名（按点单频率），大按钮一键加入当前桌台订单。
 * 减少多级菜单导航，对标天财移动银台Pro。
 *
 * 数据来源（优先级）：
 *   1. localStorage 缓存（key: tx_quick_dishes_{storeId}）
 *   2. API GET /api/v1/menu/dishes/popular?store_id=&limit=10
 */
import { useEffect, useState, useCallback } from 'react';

// ─── 类型 ───

interface QuickDish {
  dish_id: string;
  dish_name: string;
  price_fen: number;
  category?: string;
  order_count?: number;  // 点单次数（排序用）
}

interface QuickOrderPanelProps {
  storeId: string;
  tableNo: string;
  orderId: string;
  tenantId?: string;
  onAdded?: (dish: QuickDish, newQty: number) => void;
  onClose?: () => void;
}

// ─── 工具函数 ───

const CACHE_KEY = (storeId: string) => `tx_quick_dishes_${storeId}`;
const CACHE_TTL = 10 * 60 * 1000; // 10 分钟

function loadCache(storeId: string): QuickDish[] | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY(storeId));
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw) as { data: QuickDish[]; ts: number };
    if (Date.now() - ts > CACHE_TTL) return null;
    return data;
  } catch {
    return null;
  }
}

function saveCache(storeId: string, data: QuickDish[]) {
  try {
    localStorage.setItem(CACHE_KEY(storeId), JSON.stringify({ data, ts: Date.now() }));
  } catch {
    // ignore storage quota errors
  }
}

function fmtPrice(fen: number): string {
  const yuan = fen / 100;
  return `¥${yuan % 1 === 0 ? yuan.toFixed(0) : yuan.toFixed(1)}`;
}

const TENANT_ID = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TENANT_ID__) || '';

const API_BASE = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TX_API_BASE__) || '';

// ─── 主组件 ───

export function QuickOrderPanel({
  storeId,
  tableNo,
  orderId,
  onAdded,
  onClose,
}: QuickOrderPanelProps) {
  const [dishes, setDishes] = useState<QuickDish[]>([]);
  const [loading, setLoading] = useState(true);
  const [addingId, setAddingId] = useState<string | null>(null);
  const [qtyMap, setQtyMap] = useState<Record<string, number>>({});
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 1800);
  }, []);

  // ── 加载常用菜品 ──
  useEffect(() => {
    const cached = loadCache(storeId);
    if (cached) {
      setDishes(cached);
      setLoading(false);
      return;
    }

    const tenantId = TENANT_ID();
    const apiBase = API_BASE();

    fetch(`${apiBase}/api/v1/menu/dishes/popular?store_id=${encodeURIComponent(storeId)}&limit=10`, {
      headers: {
        'X-Tenant-ID': tenantId,
        'Content-Type': 'application/json',
      },
    })
      .then((r) => r.json())
      .then((res) => {
        const items: QuickDish[] = res.ok
          ? (res.data?.items ?? res.data ?? [])
          : [];
        saveCache(storeId, items);
        setDishes(items);
      })
      .catch(() => {
        // 网络失败：使用 mock 数据（开发模式）
        const mock: QuickDish[] = [
          { dish_id: 'd001', dish_name: '米饭', price_fen: 200, category: '主食', order_count: 1200 },
          { dish_id: 'd002', dish_name: '茶水', price_fen: 100, category: '饮品', order_count: 1100 },
          { dish_id: 'd003', dish_name: '小炒黄牛吊龙', price_fen: 5500, category: '热菜', order_count: 980 },
          { dish_id: 'd004', dish_name: '蒸鱼', price_fen: 8800, category: '海鲜', order_count: 870 },
          { dish_id: 'd005', dish_name: '白灼虾', price_fen: 6800, category: '海鲜', order_count: 760 },
          { dish_id: 'd006', dish_name: '炒青菜', price_fen: 2800, category: '素菜', order_count: 720 },
          { dish_id: 'd007', dish_name: '蒜蓉粉丝虾', price_fen: 7200, category: '海鲜', order_count: 680 },
          { dish_id: 'd008', dish_name: '例汤', price_fen: 1500, category: '汤', order_count: 650 },
          { dish_id: 'd009', dish_name: '玉米排骨汤', price_fen: 4800, category: '汤', order_count: 610 },
          { dish_id: 'd010', dish_name: '酸辣土豆丝', price_fen: 2200, category: '素菜', order_count: 580 },
        ];
        setDishes(mock);
      })
      .finally(() => setLoading(false));
  }, [storeId]);

  // ── 加入订单 ──
  const handleAdd = useCallback(async (dish: QuickDish) => {
    if (addingId) return;
    setAddingId(dish.dish_id);

    const tenantId = TENANT_ID();
    const apiBase = API_BASE();

    try {
      const body = {
        order_id: orderId,
        table_no: tableNo,
        items: [
          {
            dish_id: dish.dish_id,
            dish_name: dish.dish_name,
            quantity: 1,
            unit_price_fen: dish.price_fen,
          },
        ],
      };

      const res = await fetch(`${apiBase}/api/v1/trade/orders/${encodeURIComponent(orderId)}/items`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': tenantId,
        },
        body: JSON.stringify(body),
      });

      const json = await res.json();
      if (!res.ok || json.ok === false) {
        throw new Error(json.error?.message || `HTTP ${res.status}`);
      }

      const newQty = (qtyMap[dish.dish_id] ?? 0) + 1;
      setQtyMap((prev) => ({ ...prev, [dish.dish_id]: newQty }));
      onAdded?.(dish, newQty);
      showToast(`已加：${dish.dish_name}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加单失败';
      showToast(`失败：${msg}`);
    } finally {
      setAddingId(null);
    }
  }, [addingId, orderId, tableNo, qtyMap, onAdded, showToast]);

  // ─── 渲染 ───

  return (
    <div
      style={{
        background: '#0B1A20',
        borderRadius: '16px 16px 0 0',
        display: 'flex',
        flexDirection: 'column',
        maxHeight: '70vh',
        overflow: 'hidden',
      }}
    >
      {/* 顶部栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 16px 10px',
          borderBottom: '1px solid #1e3a45',
          flexShrink: 0,
        }}
      >
        <div>
          <span style={{ fontSize: 17, fontWeight: 700, color: '#fff' }}>
            ⚡ 快速下单
          </span>
          <span style={{ fontSize: 13, color: '#888', marginLeft: 8 }}>
            {tableNo} · 常用菜品TOP10
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#aaa',
              fontSize: 22,
              cursor: 'pointer',
              minHeight: 48,
              minWidth: 48,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ×
          </button>
        )}
      </div>

      {/* 菜品列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '8px 0 16px',
        }}
      >
        {loading ? (
          // Skeleton
          Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '12px 16px',
                gap: 12,
                borderBottom: '1px solid #1e3a45',
              }}
            >
              <div style={{ flex: 1, height: 20, background: '#1e3a45', borderRadius: 4 }} />
              <div style={{ width: 60, height: 20, background: '#1e3a45', borderRadius: 4 }} />
              <div style={{ width: 48, height: 40, background: '#1e3a45', borderRadius: 8 }} />
            </div>
          ))
        ) : dishes.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#888', padding: '32px 16px', fontSize: 15 }}>
            暂无常用菜品数据
          </div>
        ) : (
          dishes.map((dish, idx) => {
            const qty = qtyMap[dish.dish_id] ?? 0;
            const isAdding = addingId === dish.dish_id;

            return (
              <div
                key={dish.dish_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '12px 16px',
                  gap: 12,
                  borderBottom: '1px solid #1a2a33',
                  background: qty > 0 ? 'rgba(255,107,35,0.06)' : 'transparent',
                  transition: 'background 0.2s',
                }}
              >
                {/* 排名标 */}
                <span
                  style={{
                    fontSize: 13,
                    color: idx < 3 ? '#FF6B35' : '#666',
                    minWidth: 20,
                    textAlign: 'center',
                    fontWeight: idx < 3 ? 700 : 400,
                  }}
                >
                  {idx + 1}
                </span>

                {/* 菜名 + 品类 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 16,
                      color: '#fff',
                      fontWeight: 500,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {dish.dish_name}
                  </div>
                  {dish.category && (
                    <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
                      {dish.category}
                      {dish.order_count != null && (
                        <span style={{ marginLeft: 6 }}>点单{dish.order_count}次</span>
                      )}
                    </div>
                  )}
                </div>

                {/* 价格 */}
                <span style={{ fontSize: 15, color: '#FF6B35', fontWeight: 600, minWidth: 52, textAlign: 'right' }}>
                  {fmtPrice(dish.price_fen)}
                </span>

                {/* 已加数量标记 */}
                {qty > 0 && (
                  <span
                    style={{
                      fontSize: 13,
                      color: '#fff',
                      background: '#FF6B35',
                      borderRadius: 10,
                      padding: '2px 7px',
                      fontWeight: 700,
                      minWidth: 24,
                      textAlign: 'center',
                    }}
                  >
                    +{qty}
                  </span>
                )}

                {/* 加入按钮 */}
                <button
                  onClick={() => handleAdd(dish)}
                  disabled={isAdding}
                  style={{
                    minHeight: 48,
                    minWidth: 64,
                    background: isAdding ? '#3a4a55' : '#FF6B35',
                    border: 'none',
                    borderRadius: 10,
                    color: '#fff',
                    fontSize: 22,
                    fontWeight: 700,
                    cursor: isAdding ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'background 0.15s',
                    WebkitTapHighlightColor: 'transparent',
                    flexShrink: 0,
                  }}
                >
                  {isAdding ? '…' : '+'}
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div
          style={{
            position: 'absolute',
            bottom: 80,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.8)',
            color: '#fff',
            borderRadius: 20,
            padding: '8px 18px',
            fontSize: 14,
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            zIndex: 10,
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
