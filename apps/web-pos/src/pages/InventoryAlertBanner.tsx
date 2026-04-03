/**
 * InventoryAlertBanner — 库存预警横幅
 *
 * 在 web-pos 顶部显示库存预警信息。
 * 每 60 秒轮询 /api/v1/inventory/soldout-watch。
 * 无预警时隐藏（height: 0），有预警时显示最紧急一条 + 总数。
 * 点击"处理"跳转到 /live-menu 菜单实时编辑页。
 *
 * 对标：Lightspeed 和 Odoo 的库存预警横幅设计。
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── 类型 ───

interface WatchItem {
  dish_id: string;
  dish_name: string;
  ingredient_name: string;
  ingredient_id: string;
  estimated_servings: number;
  is_auto_soldout: boolean;
  is_low_stock: boolean;
  current_stock: number;
  unit: string;
}

interface SoldoutWatchResponse {
  ok: boolean;
  data: {
    items: WatchItem[];
    total: number;
    store_id: string;
  };
}

// ─── Props ───

interface InventoryAlertBannerProps {
  storeId: string;
}

// ─── 常量 ───

const API_BASE: string =
  (window as Record<string, unknown>).__STORE_API_BASE__ as string || '';
const TENANT_ID: string =
  (window as Record<string, unknown>).__TENANT_ID__ as string || '';

const POLL_INTERVAL_MS = 60_000;

// ─── 工具函数 ───

function buildAlertText(item: WatchItem): string {
  if (item.is_auto_soldout) {
    return `${item.dish_name} 已自动下架（${item.ingredient_name}库存耗尽）`;
  }
  const servings = item.estimated_servings;
  return `${item.ingredient_name} 还剩约 ${servings} 份可出品（影响: ${item.dish_name}）`;
}

// ─── 主组件 ───

export function InventoryAlertBanner({ storeId }: InventoryAlertBannerProps) {
  const navigate = useNavigate();
  const [items, setItems] = useState<WatchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAlerts = useCallback(async () => {
    if (!API_BASE || !storeId) {
      // 无 API 配置时不显示任何预警（避免误导）
      return;
    }

    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;

      const resp = await fetch(
        `${API_BASE}/api/v1/inventory/soldout-watch?store_id=${encodeURIComponent(storeId)}`,
        { headers }
      );

      if (!resp.ok) return;

      const json = (await resp.json()) as SoldoutWatchResponse;
      if (json.ok && json.data?.items) {
        setItems(json.data.items);
      }
    } catch {
      // 网络错误静默忽略，不影响正常 POS 流程
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  // 初始加载 + 定时轮询
  useEffect(() => {
    fetchAlerts();

    timerRef.current = setInterval(fetchAlerts, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchAlerts]);

  // 无预警时不渲染（height: 0 方案保留动画空间）
  if (items.length === 0) {
    return null;
  }

  const topItem = items[0];
  const extraCount = items.length - 1;
  const hasSoldout = items.some(i => i.is_auto_soldout);

  // 颜色策略：已下架 → 深橙红；仅低库存 → 橙色
  const bgColor = hasSoldout ? '#92400E' : '#78350F';
  const borderColor = hasSoldout ? '#F97316' : '#FF6B35';
  const textColor = '#FEF3C7';
  const iconColor = hasSoldout ? '#FCA5A5' : '#FDE68A';

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: bgColor,
        borderBottom: `2px solid ${borderColor}`,
        padding: '10px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        minHeight: 48,
      }}
    >
      {/* 警告图标 */}
      <span
        style={{
          fontSize: 18,
          flexShrink: 0,
          color: iconColor,
          lineHeight: 1,
        }}
        aria-hidden="true"
      >
        ⚠
      </span>

      {/* 预警文字 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            color: textColor,
            fontSize: 14,
            fontWeight: 600,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: 'block',
          }}
        >
          {loading ? '库存预警: 刷新中...' : buildAlertText(topItem)}
          {extraCount > 0 && (
            <span
              style={{
                marginLeft: 8,
                color: '#FCD34D',
                fontWeight: 400,
                fontSize: 13,
              }}
            >
              共 {items.length} 条预警
            </span>
          )}
        </span>
      </div>

      {/* 处理按钮 */}
      <button
        onClick={() => navigate('/live-menu')}
        style={{
          height: 36,
          padding: '0 16px',
          background: '#FF6B35',
          color: '#fff',
          border: 'none',
          borderRadius: 8,
          cursor: 'pointer',
          fontSize: 14,
          fontWeight: 700,
          flexShrink: 0,
          whiteSpace: 'nowrap',
        }}
      >
        处理
      </button>

      {/* 关闭（临时忽略，下次轮询仍会显示） */}
      <button
        onClick={() => setItems([])}
        aria-label="暂时关闭预警横幅"
        style={{
          background: 'none',
          border: 'none',
          color: textColor,
          cursor: 'pointer',
          fontSize: 18,
          padding: '4px 6px',
          flexShrink: 0,
          opacity: 0.7,
          minWidth: 32,
          minHeight: 32,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        ✕
      </button>
    </div>
  );
}
