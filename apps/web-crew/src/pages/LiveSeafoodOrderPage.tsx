/**
 * LiveSeafoodOrderPage — 活鲜点单三步流程页面
 *
 * URL: /live-seafood?order_id=xxx&table=xxx[&tank_zone=A1]
 *
 * Step 1 — 鱼缸选品（TankStatusView）
 * Step 2 — 称重确认（WeighDishSheet 底部弹层）
 * Step 3 — 提交活鲜订单
 *
 * 扫码入口：?tank_zone=A1 直接定位到指定鱼缸区域
 */
import { useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { addItemsToOrder } from '../api/index';
import type { OrderItem } from '../api/index';
import { toWeighDishInfo, type LiveSeafoodDish } from '../api/liveSeafoodApi';
import { TankStatusView } from './TankStatusView';
import { WeighDishSheet } from './WeighDishSheet';
import { printLiveSeafoodReceipt } from '../utils/printUtils';

// ─── Design Tokens ────────────────────────────────────────────────────────────

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#ef4444',
};

// ─── 已选活鲜条目 ─────────────────────────────────────────────────────────────

interface SelectedSeafoodItem {
  /** 唯一 key（同一菜可多次称重，各自独立） */
  key: string;
  dish: LiveSeafoodDish;
  tankZone: string;
  weightKg: number;
  totalFen: number;
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function LiveSeafoodOrderPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const orderId = params.get('order_id') || '';
  const tableNo = params.get('table') || '';
  const tankZoneParam = params.get('tank_zone') ?? null;

  const storeId =
    (window as unknown as Record<string, string>).__STORE_ID__ || 'store_001';

  // 已选活鲜列表
  const [selected, setSelected] = useState<SelectedSeafoodItem[]>([]);

  // 称重弹层
  const [weighingDish, setWeighingDish] = useState<LiveSeafoodDish | null>(null);
  const [weighingTankZone, setWeighingTankZone] = useState<string>('');

  // 底部已选列表展开
  const [showSelected, setShowSelected] = useState(false);

  // 提交状态
  const [submitting, setSubmitting] = useState(false);

  // Toast
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(null);
  const showToast = useCallback((text: string, ok: boolean) => {
    setToast({ text, ok });
    setTimeout(() => setToast(null), 2500);
  }, []);

  // ── 选择菜品 → 弹出称重面板 ──

  const handleSelectDish = useCallback(
    (dish: LiveSeafoodDish, tankZone: string) => {
      setWeighingDish(dish);
      setWeighingTankZone(tankZone);
    },
    [],
  );

  // ── 称重确认 → 加入已选列表 ──

  const handleWeighConfirm = useCallback(
    (weightKg: number, totalFen: number) => {
      if (!weighingDish) return;
      const item: SelectedSeafoodItem = {
        key: `${weighingDish.dish_id}_${Date.now()}`,
        dish: weighingDish,
        tankZone: weighingTankZone,
        weightKg,
        totalFen,
      };
      setSelected(prev => [...prev, item]);
      setWeighingDish(null);
      setWeighingTankZone('');
      showToast(`已添加 ${weighingDish.dish_name}`, true);
    },
    [weighingDish, weighingTankZone, showToast],
  );

  // ── 移除已选条目 ──

  const handleRemoveItem = (key: string) => {
    setSelected(prev => prev.filter(i => i.key !== key));
  };

  // ── 提交订单 ──

  const totalFen = selected.reduce((sum, i) => sum + i.totalFen, 0);
  const totalYuan = (totalFen / 100).toFixed(2);

  const handleSubmit = () => {
    if (selected.length === 0 || submitting) return;
    setSubmitting(true);

    const items: OrderItem[] = selected.map(i => ({
      dish_id: i.dish.dish_id,
      dish_name: `${i.dish.dish_name}（${(i.weightKg * 2).toFixed(3)}斤）`,
      quantity: 1,
      unit_price_fen: i.totalFen, // 直接用称重后总价作为单位价
      special_notes: `称重${(i.weightKg * 2).toFixed(3)}斤·鱼缸${i.tankZone}`,
    }));

    addItemsToOrder(orderId, items)
      .then(() => {
        showToast('活鲜已加入订单', true);

        // 安卓POS环境下自动打印活鲜称重单
        if (window.TXBridge) {
          const storeName =
            (window as unknown as Record<string, string>).__STORE_NAME__ || '门店';
          const operatorName =
            (window as unknown as Record<string, string>).__EMPLOYEE_NAME__ || '服务员';
          const printData = {
            store_name: storeName,
            table_no: tableNo,
            printed_at: new Date().toLocaleString('zh-CN', {
              year: 'numeric',
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
              hour12: false,
            }),
            operator: operatorName,
            items: selected.map(item => ({
              dish_name: item.dish.dish_name,
              tank_zone: item.tankZone,
              weight_kg: item.weightKg,
              weight_jin: item.weightKg * 2,
              price_per_jin_fen: item.dish.price_per_unit_fen,
              total_fen: item.totalFen,
              note: '',
            })),
            total_fen: totalFen,
          };
          // 异步打印，不阻塞页面跳转
          printLiveSeafoodReceipt(printData).catch((printErr: unknown) => {
            console.error('[打印失败]', printErr);
          });
        }

        setTimeout(() => navigate(-1), 800);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '提交失败';
        showToast(msg, false);
        setSubmitting(false);
      });
  };

  // ── 渲染 ──

  return (
    <div
      style={{
        background: C.bg,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* ── 顶部导航 ── */}
      <div
        style={{
          padding: '12px 16px',
          background: C.card,
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48,
            minHeight: 48,
            borderRadius: 12,
            background: 'transparent',
            border: `1px solid ${C.border}`,
            color: C.muted,
            fontSize: 20,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          aria-label="返回"
        >
          {'<'}
        </button>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white }}>
            活鲜点单{tableNo ? ` · ${tableNo}台` : ''}
          </div>
          {tankZoneParam && (
            <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
              已定位到 {tankZoneParam} 区域
            </div>
          )}
        </div>
      </div>

      {/* ── 主内容：鱼缸选品 ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          paddingBottom: selected.length > 0 ? 140 : 80,
        } as React.CSSProperties}
      >
        <TankStatusView
          storeId={storeId}
          onSelectDish={handleSelectDish}
          defaultZoneCode={tankZoneParam}
        />
      </div>

      {/* ── 称重弹层（Step 2）── */}
      {weighingDish && (
        <WeighDishSheet
          dish={toWeighDishInfo(weighingDish)}
          onConfirm={handleWeighConfirm}
          onClose={() => setWeighingDish(null)}
        />
      )}

      {/* ── 底部：已选清单 + 提交按钮（Step 3）── */}
      {selected.length > 0 && (
        <div
          style={{
            position: 'fixed',
            bottom: 0,
            left: 0,
            right: 0,
            background: C.card,
            borderTop: `1px solid ${C.border}`,
            zIndex: 100,
          }}
        >
          {/* 已选折叠列表 */}
          {showSelected && (
            <div
              style={{
                maxHeight: '40vh',
                overflowY: 'auto',
                padding: '12px 16px 0',
              }}
            >
              <div
                style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: C.text,
                  marginBottom: 10,
                }}
              >
                已选活鲜（{selected.length}项）
              </div>
              {selected.map(item => (
                <div
                  key={item.key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '10px 0',
                    borderBottom: `1px solid ${C.border}`,
                    gap: 10,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, color: C.white, fontWeight: 600 }}>
                      {item.dish.dish_name}
                    </div>
                    <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
                      {(item.weightKg * 2).toFixed(3)}斤 · {item.tankZone}区
                    </div>
                  </div>
                  <div
                    style={{
                      fontSize: 18,
                      fontWeight: 700,
                      color: C.accent,
                      minWidth: 60,
                      textAlign: 'right',
                    }}
                  >
                    ¥{(item.totalFen / 100).toFixed(2)}
                  </div>
                  <button
                    onClick={() => handleRemoveItem(item.key)}
                    style={{
                      minWidth: 36,
                      minHeight: 36,
                      borderRadius: 8,
                      background: 'transparent',
                      border: `1px solid ${C.border}`,
                      color: C.muted,
                      fontSize: 16,
                      cursor: 'pointer',
                    }}
                    aria-label="移除"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 汇总行 + 提交按钮 */}
          <div
            style={{
              padding: '12px 16px',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            {/* 已选摘要（点击展开） */}
            <button
              onClick={() => setShowSelected(s => !s)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                padding: 0,
              }}
            >
              <span
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 22,
                  background: C.accent,
                  color: C.white,
                  fontSize: 18,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {selected.length}
              </span>
              <div style={{ textAlign: 'left' }}>
                <div style={{ fontSize: 16, color: C.text, fontWeight: 600 }}>
                  ¥{totalYuan}
                </div>
                <div style={{ fontSize: 13, color: C.muted }}>
                  {showSelected ? '收起清单' : '查看清单'}
                </div>
              </div>
            </button>

            {/* 加入订单按钮 */}
            <button
              onClick={handleSubmit}
              disabled={submitting}
              style={{
                flex: 1,
                minHeight: 52,
                borderRadius: 12,
                background: submitting ? C.muted : C.accent,
                border: 'none',
                color: C.white,
                fontSize: 18,
                fontWeight: 700,
                cursor: submitting ? 'not-allowed' : 'pointer',
                transition: 'background 0.2s',
              }}
            >
              {submitting
                ? '提交中...'
                : `加入订单（共${selected.length}项，¥${totalYuan}）`}
            </button>
          </div>

          {/* iOS 安全区域 */}
          <div style={{ height: 'env(safe-area-inset-bottom, 8px)' }} />
        </div>
      )}

      {/* ── Toast ── */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: selected.length > 0 ? 140 : 40,
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '10px 20px',
            borderRadius: 10,
            background: toast.ok ? C.green : C.danger,
            color: C.white,
            fontSize: 16,
            fontWeight: 600,
            zIndex: 200,
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
          }}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}
