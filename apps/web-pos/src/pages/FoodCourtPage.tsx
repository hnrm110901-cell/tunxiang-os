/**
 * FoodCourtPage — 美食广场档口收银
 * TC-P2-12 智慧商街/档口管理
 *
 * TXTouch 风格：深色 header #1E2A3A，浅色内容 #F8F7F5，触控友好 ≥48px
 * 布局：档口选择器 → 3列（品项 | 订单明细 | 结算面板）→ 底部Tab
 */
import { useState, useCallback } from 'react';

// ─── Design Token（CSS 变量）────────────────────────────────────────────────
const TOKEN = {
  primary: '#FF6B35',
  primaryActive: '#E55A28',
  navy: '#1E2A3A',
  navyLight: '#2C3E50',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  textPrimary: '#2C2C2A',
  textSecondary: '#5F5E5A',
  bgPrimary: '#FFFFFF',
  bgSecondary: '#F8F7F5',
  border: '#E8E6E1',
} as const;

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

interface Outlet {
  id: string;
  name: string;
  outlet_code: string;
  location: string;
  status: string;
  today_revenue_fen: number;
  today_order_count: number;
}

interface MenuItem {
  id: string;
  name: string;
  price_fen: number;
  category: string;
}

interface CartItem {
  id: string;
  name: string;
  price_fen: number;
  qty: number;
  outlet_id: string;
  outlet_name: string;
}

interface OutletOrder {
  outlet_id: string;
  outlet_name: string;
  outlet_code: string;
  items: CartItem[];
  subtotal_fen: number;
}

const MOCK_OUTLETS: Outlet[] = [
  { id: 'out-001', name: '张记烤鱼', outlet_code: 'A01', location: 'A区1号', status: 'active', today_revenue_fen: 285600, today_order_count: 23 },
  { id: 'out-002', name: '李家粉面', outlet_code: 'A02', location: 'A区2号', status: 'active', today_revenue_fen: 156800, today_order_count: 41 },
  { id: 'out-003', name: '老王串串', outlet_code: 'B01', location: 'B区1号', status: 'active', today_revenue_fen: 198400, today_order_count: 31 },
];

const MOCK_MENU: Record<string, MenuItem[]> = {
  'out-001': [
    { id: 'dish-001', name: '招牌烤鱼', price_fen: 6800, category: '烤鱼' },
    { id: 'dish-002', name: '香辣烤鱼', price_fen: 7200, category: '烤鱼' },
    { id: 'dish-003', name: '豆腐', price_fen: 800, category: '配菜' },
    { id: 'dish-004', name: '粉丝', price_fen: 600, category: '配菜' },
    { id: 'dish-013', name: '宽粉', price_fen: 700, category: '配菜' },
    { id: 'dish-014', name: '藕片', price_fen: 600, category: '配菜' },
  ],
  'out-002': [
    { id: 'dish-005', name: '牛肉粉', price_fen: 1800, category: '粉面' },
    { id: 'dish-006', name: '猪脚粉', price_fen: 1600, category: '粉面' },
    { id: 'dish-007', name: '肥肠面', price_fen: 1400, category: '粉面' },
    { id: 'dish-008', name: '卤蛋', price_fen: 200, category: '小料' },
    { id: 'dish-015', name: '鸡爪', price_fen: 500, category: '小料' },
    { id: 'dish-016', name: '排骨粉', price_fen: 2000, category: '粉面' },
  ],
  'out-003': [
    { id: 'dish-009', name: '牛肉串', price_fen: 600, category: '荤串' },
    { id: 'dish-010', name: '羊肉串', price_fen: 500, category: '荤串' },
    { id: 'dish-011', name: '脑花', price_fen: 1200, category: '特色' },
    { id: 'dish-012', name: '青笋', price_fen: 300, category: '素串' },
    { id: 'dish-017', name: '土豆', price_fen: 200, category: '素串' },
    { id: 'dish-018', name: '鸭肠', price_fen: 800, category: '荤串' },
  ],
};

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);

// ─── 子组件 ───────────────────────────────────────────────────────────────────

/** 档口选择器卡片 */
function OutletSelectorCard({
  outlet,
  selected,
  onSelect,
}: {
  outlet: Outlet;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(outlet.id)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        padding: '12px 16px',
        minHeight: 72,
        minWidth: 140,
        borderRadius: 12,
        border: selected ? `2px solid ${TOKEN.primary}` : `1px solid ${TOKEN.border}`,
        background: selected ? '#FFF3ED' : TOKEN.bgPrimary,
        cursor: 'pointer',
        transition: 'all 200ms ease',
        transform: selected ? 'scale(1)' : 'scale(1)',
        flexShrink: 0,
        boxShadow: selected ? `0 0 0 2px ${TOKEN.primary}33` : '0 1px 2px rgba(0,0,0,0.05)',
      }}
      onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
      onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{
          fontSize: 16,
          fontWeight: 700,
          color: selected ? TOKEN.primary : TOKEN.textPrimary,
        }}>
          {outlet.name}
        </span>
        <span style={{
          fontSize: 12,
          padding: '1px 6px',
          borderRadius: 4,
          background: selected ? TOKEN.primary : TOKEN.bgSecondary,
          color: selected ? '#fff' : TOKEN.textSecondary,
          fontWeight: 600,
        }}>
          {outlet.outlet_code}
        </span>
      </div>
      <span style={{ fontSize: 13, color: TOKEN.textSecondary }}>{outlet.location}</span>
      <span style={{ fontSize: 13, color: TOKEN.textSecondary, marginTop: 2 }}>
        今日 ¥{fenToYuan(outlet.today_revenue_fen)} · {outlet.today_order_count}单
      </span>
    </button>
  );
}

/** 菜品按钮（触控优化） */
function DishButton({
  dish,
  count,
  onAdd,
}: {
  dish: MenuItem;
  count: number;
  onAdd: (dish: MenuItem) => void;
}) {
  return (
    <button
      onClick={() => onAdd(dish)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: 12,
        minHeight: 80,
        borderRadius: 12,
        border: count > 0 ? `2px solid ${TOKEN.primary}` : `1px solid ${TOKEN.border}`,
        background: count > 0 ? '#FFF3ED' : TOKEN.bgPrimary,
        cursor: 'pointer',
        transition: 'all 200ms ease',
        position: 'relative',
        textAlign: 'left',
      }}
      onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
      onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
    >
      {count > 0 && (
        <span style={{
          position: 'absolute',
          top: -6,
          right: -6,
          background: TOKEN.primary,
          color: '#fff',
          borderRadius: '50%',
          width: 20,
          height: 20,
          fontSize: 12,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1,
        }}>
          {count}
        </span>
      )}
      <span style={{ fontSize: 16, fontWeight: 600, color: TOKEN.textPrimary, lineHeight: 1.3 }}>
        {dish.name}
      </span>
      <span style={{ fontSize: 18, fontWeight: 700, color: TOKEN.primary }}>
        ¥{fenToYuan(dish.price_fen)}
      </span>
    </button>
  );
}

/** 档口订单分组 */
function OutletOrderGroup({ group }: { group: OutletOrder }) {
  return (
    <div style={{
      marginBottom: 12,
      borderRadius: 10,
      border: `1px solid ${TOKEN.border}`,
      overflow: 'hidden',
    }}>
      {/* 档口标题 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        background: TOKEN.navy,
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>
          {group.outlet_name}
        </span>
        <span style={{
          fontSize: 12,
          padding: '2px 8px',
          borderRadius: 4,
          background: '#ffffff22',
          color: '#ffffffcc',
        }}>
          {group.outlet_code}
        </span>
      </div>
      {/* 品项列表 */}
      <div style={{ padding: '8px 12px', background: TOKEN.bgPrimary }}>
        {group.items.map((item) => (
          <div key={item.id} style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '6px 0',
            borderBottom: `1px solid ${TOKEN.border}`,
            minHeight: 40,
          }}>
            <span style={{ fontSize: 15, color: TOKEN.textPrimary }}>{item.name}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 14, color: TOKEN.textSecondary }}>×{item.qty}</span>
              <span style={{ fontSize: 15, fontWeight: 600, color: TOKEN.primary }}>
                ¥{fenToYuan(item.price_fen * item.qty)}
              </span>
            </div>
          </div>
        ))}
        {/* 档口小计 */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center',
          paddingTop: 6,
          gap: 4,
        }}>
          <span style={{ fontSize: 13, color: TOKEN.textSecondary }}>小计：</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: TOKEN.textPrimary }}>
            ¥{fenToYuan(group.subtotal_fen)}
          </span>
        </div>
      </div>
    </div>
  );
}

/** 结算面板 */
function CheckoutPanel({
  outletGroups,
  totalFen,
  onCheckout,
  onClear,
}: {
  outletGroups: OutletOrder[];
  totalFen: number;
  onCheckout: (method: string, tendered?: number) => void;
  onClear: () => void;
}) {
  const [cashInput, setCashInput] = useState('');
  const [cashMode, setCashMode] = useState(false);

  const cashTenderedFen = cashInput ? Math.round(parseFloat(cashInput) * 100) : 0;
  const changeFen = cashTenderedFen > totalFen ? cashTenderedFen - totalFen : 0;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: TOKEN.bgSecondary,
      borderRadius: 12,
      overflow: 'hidden',
    }}>
      {/* 合计 */}
      <div style={{
        padding: '16px 20px',
        background: TOKEN.navy,
        flexShrink: 0,
      }}>
        <div style={{ fontSize: 14, color: '#ffffff88', marginBottom: 4 }}>合计</div>
        <div style={{ fontSize: 36, fontWeight: 800, color: '#fff' }}>
          ¥{fenToYuan(totalFen)}
        </div>
        <div style={{ fontSize: 13, color: '#ffffff66', marginTop: 4 }}>
          {outletGroups.length} 个档口 · {outletGroups.reduce((s, g) => s + g.items.reduce((ss, i) => ss + i.qty, 0), 0)} 件商品
        </div>
      </div>

      {/* 档口分账摘要 */}
      {outletGroups.length > 0 && (
        <div style={{ padding: '12px 16px', background: TOKEN.bgPrimary, flexShrink: 0 }}>
          {outletGroups.map((group) => (
            <div key={group.outlet_id} style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '4px 0',
              fontSize: 14,
              color: TOKEN.textSecondary,
            }}>
              <span>{group.outlet_name}</span>
              <span style={{ fontWeight: 600, color: TOKEN.textPrimary }}>
                ¥{fenToYuan(group.subtotal_fen)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
        {/* 现金模式：输入实收金额 */}
        {cashMode && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 14, color: TOKEN.textSecondary, marginBottom: 6 }}>实收金额（元）</div>
            <input
              type="number"
              value={cashInput}
              onChange={(e) => setCashInput(e.target.value)}
              placeholder="请输入实收金额"
              style={{
                width: '100%',
                height: 56,
                borderRadius: 10,
                border: `1px solid ${TOKEN.border}`,
                padding: '0 16px',
                fontSize: 24,
                fontWeight: 700,
                color: TOKEN.textPrimary,
                boxSizing: 'border-box',
                outline: 'none',
              }}
            />
            {cashTenderedFen > totalFen && (
              <div style={{
                marginTop: 8,
                padding: '8px 12px',
                borderRadius: 8,
                background: '#0F6E5610',
                color: TOKEN.success,
                fontSize: 16,
                fontWeight: 600,
              }}>
                找零：¥{fenToYuan(changeFen)}
              </div>
            )}
            {cashTenderedFen > 0 && cashTenderedFen < totalFen && (
              <div style={{
                marginTop: 8,
                padding: '8px 12px',
                borderRadius: 8,
                background: '#A32D2D10',
                color: TOKEN.danger,
                fontSize: 14,
              }}>
                金额不足，请再输入 ¥{fenToYuan(totalFen - cashTenderedFen)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 支付按钮区 */}
      <div style={{ padding: '12px 16px', flexShrink: 0, background: TOKEN.bgPrimary }}>
        {/* 扫码支付 */}
        <button
          onClick={() => onCheckout('wechat')}
          disabled={totalFen === 0}
          style={{
            width: '100%',
            height: 64,
            borderRadius: 12,
            border: 'none',
            background: totalFen > 0 ? TOKEN.primary : TOKEN.border,
            color: '#fff',
            fontSize: 18,
            fontWeight: 700,
            cursor: totalFen > 0 ? 'pointer' : 'not-allowed',
            marginBottom: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            transition: 'all 200ms ease',
          }}
          onMouseDown={(e) => { if (totalFen > 0) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
        >
          📱 扫码收款
        </button>

        <div style={{ display: 'flex', gap: 10 }}>
          {/* 现金 */}
          <button
            onClick={() => {
              if (!cashMode) { setCashMode(true); return; }
              if (cashTenderedFen >= totalFen) {
                onCheckout('cash', cashTenderedFen);
                setCashMode(false);
                setCashInput('');
              }
            }}
            disabled={totalFen === 0}
            style={{
              flex: 1,
              height: 56,
              borderRadius: 10,
              border: `1px solid ${TOKEN.border}`,
              background: cashMode ? TOKEN.success : TOKEN.bgSecondary,
              color: cashMode ? '#fff' : TOKEN.textPrimary,
              fontSize: 16,
              fontWeight: 600,
              cursor: totalFen > 0 ? 'pointer' : 'not-allowed',
              transition: 'all 200ms ease',
            }}
            onMouseDown={(e) => { if (totalFen > 0) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            💵 {cashMode ? '确认找零' : '现金'}
          </button>

          {/* 清单 */}
          <button
            onClick={onClear}
            style={{
              flex: 1,
              height: 56,
              borderRadius: 10,
              border: `1px solid ${TOKEN.danger}`,
              background: 'transparent',
              color: TOKEN.danger,
              fontSize: 16,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 200ms ease',
            }}
            onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            🗑 清单
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Tab 类型 ─────────────────────────────────────────────────────────────────
type TabKey = 'cashier' | 'orders' | 'reports';

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function FoodCourtPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('cashier');
  const [selectedOutletId, setSelectedOutletId] = useState<string>(MOCK_OUTLETS[0].id);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [paidOrders, setPaidOrders] = useState<{ orderId: string; total: number; method: string; time: string }[]>([]);
  const [notification, setNotification] = useState<string | null>(null);

  const selectedOutlet = MOCK_OUTLETS.find((o) => o.id === selectedOutletId)!;
  const menu = MOCK_MENU[selectedOutletId] || [];

  // 按类别分组菜品
  const categories = Array.from(new Set(menu.map((d) => d.category)));

  // 购物车中各品项数量
  const getItemCount = (dishId: string) =>
    cart.filter((c) => c.id === dishId).reduce((s, c) => s + c.qty, 0);

  // 按档口分组购物车
  const outletGroups: OutletOrder[] = MOCK_OUTLETS.map((outlet) => {
    const items = cart.filter((c) => c.outlet_id === outlet.id);
    if (!items.length) return null;
    return {
      outlet_id: outlet.id,
      outlet_name: outlet.name,
      outlet_code: outlet.outlet_code,
      items,
      subtotal_fen: items.reduce((s, i) => s + i.price_fen * i.qty, 0),
    };
  }).filter(Boolean) as OutletOrder[];

  const totalFen = cart.reduce((s, i) => s + i.price_fen * i.qty, 0);

  const handleAddDish = useCallback((dish: MenuItem) => {
    setCart((prev) => {
      const existing = prev.find((c) => c.id === dish.id && c.outlet_id === selectedOutletId);
      if (existing) {
        return prev.map((c) =>
          c.id === dish.id && c.outlet_id === selectedOutletId
            ? { ...c, qty: c.qty + 1 }
            : c
        );
      }
      return [...prev, {
        id: dish.id,
        name: dish.name,
        price_fen: dish.price_fen,
        qty: 1,
        outlet_id: selectedOutletId,
        outlet_name: selectedOutlet.name,
      }];
    });
  }, [selectedOutletId, selectedOutlet]);

  const handleCheckout = useCallback((method: string, tendered?: number) => {
    if (totalFen === 0) return;
    const orderId = `FC-${Date.now().toString().slice(-6)}`;
    setPaidOrders((prev) => [{
      orderId,
      total: totalFen,
      method,
      time: new Date().toLocaleTimeString(),
    }, ...prev]);
    setCart([]);
    setNotification(`订单 ${orderId} 结算成功！¥${fenToYuan(totalFen)}`);
    setTimeout(() => setNotification(null), 3000);
  }, [totalFen]);

  const handleClear = useCallback(() => {
    if (window.confirm('确定清空当前购物车？')) {
      setCart([]);
    }
  }, []);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      background: TOKEN.bgSecondary,
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
      overflow: 'hidden',
    }}>
      {/* ── Header ── */}
      <div style={{
        background: TOKEN.navy,
        padding: '0 20px',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 60,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 20, fontWeight: 800, color: TOKEN.primary }}>屯象</span>
          <span style={{ fontSize: 16, color: '#ffffff88' }}>|</span>
          <span style={{ fontSize: 16, fontWeight: 600, color: '#fff' }}>美食广场收银</span>
        </div>
        <div style={{ fontSize: 14, color: '#ffffff66' }}>
          {new Date().toLocaleDateString('zh-CN')}
        </div>
      </div>

      {/* ── 结算成功通知 ── */}
      {notification && (
        <div style={{
          padding: '10px 20px',
          background: TOKEN.success,
          color: '#fff',
          fontSize: 15,
          fontWeight: 600,
          flexShrink: 0,
          animation: 'fadeIn 200ms ease',
        }}>
          ✓ {notification}
        </div>
      )}

      {/* ── Tab 内容 ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'cashier' && (
          <>
            {/* 档口选择器 */}
            <div style={{
              padding: '12px 16px',
              background: TOKEN.bgPrimary,
              flexShrink: 0,
              borderBottom: `1px solid ${TOKEN.border}`,
            }}>
              <div style={{ fontSize: 13, color: TOKEN.textSecondary, marginBottom: 8 }}>
                选择档口
              </div>
              <div style={{
                display: 'flex',
                gap: 10,
                overflowX: 'auto',
                WebkitOverflowScrolling: 'touch',
                paddingBottom: 4,
              }}>
                {MOCK_OUTLETS.map((outlet) => (
                  <OutletSelectorCard
                    key={outlet.id}
                    outlet={outlet}
                    selected={outlet.id === selectedOutletId}
                    onSelect={setSelectedOutletId}
                  />
                ))}
              </div>
            </div>

            {/* 主体：3列布局 */}
            <div style={{
              flex: 1,
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 340px',
              gap: 12,
              padding: 12,
              overflow: 'hidden',
              minWidth: 0,
            }}>
              {/* 左列：档口品项 */}
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                background: TOKEN.bgPrimary,
                borderRadius: 12,
                overflow: 'hidden',
              }}>
                <div style={{
                  padding: '12px 16px',
                  background: TOKEN.navy,
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>
                    {selectedOutlet.name}
                  </span>
                  <span style={{
                    fontSize: 12,
                    padding: '2px 8px',
                    borderRadius: 4,
                    background: TOKEN.primary,
                    color: '#fff',
                  }}>
                    {selectedOutlet.outlet_code}
                  </span>
                </div>
                <div style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: 12,
                  WebkitOverflowScrolling: 'touch',
                }}>
                  {categories.map((cat) => (
                    <div key={cat} style={{ marginBottom: 16 }}>
                      <div style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: TOKEN.textSecondary,
                        marginBottom: 8,
                        paddingLeft: 4,
                      }}>
                        {cat}
                      </div>
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
                        gap: 8,
                      }}>
                        {menu.filter((d) => d.category === cat).map((dish) => (
                          <DishButton
                            key={dish.id}
                            dish={dish}
                            count={getItemCount(dish.id)}
                            onAdd={handleAddDish}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 中列：订单明细（按档口分组） */}
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                background: TOKEN.bgPrimary,
                borderRadius: 12,
                overflow: 'hidden',
              }}>
                <div style={{
                  padding: '12px 16px',
                  background: TOKEN.navyLight,
                  flexShrink: 0,
                }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>
                    当前订单
                  </span>
                  {cart.length > 0 && (
                    <span style={{
                      marginLeft: 8,
                      fontSize: 13,
                      color: '#ffffff88',
                    }}>
                      {outletGroups.length}个档口 · {cart.reduce((s, i) => s + i.qty, 0)}件
                    </span>
                  )}
                </div>

                <div style={{
                  flex: 1,
                  overflowY: 'auto',
                  padding: 12,
                  WebkitOverflowScrolling: 'touch',
                }}>
                  {outletGroups.length === 0 ? (
                    <div style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      height: '100%',
                      color: TOKEN.textSecondary,
                      gap: 8,
                    }}>
                      <span style={{ fontSize: 40 }}>🛒</span>
                      <span style={{ fontSize: 15 }}>选择档口并添加品项</span>
                    </div>
                  ) : (
                    outletGroups.map((group) => (
                      <OutletOrderGroup key={group.outlet_id} group={group} />
                    ))
                  )}
                </div>
              </div>

              {/* 右列：结算面板 */}
              <CheckoutPanel
                outletGroups={outletGroups}
                totalFen={totalFen}
                onCheckout={handleCheckout}
                onClear={handleClear}
              />
            </div>
          </>
        )}

        {activeTab === 'orders' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: 16, WebkitOverflowScrolling: 'touch' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: TOKEN.textPrimary, marginBottom: 16 }}>
              今日订单记录
            </div>
            {paidOrders.length === 0 ? (
              <div style={{
                textAlign: 'center',
                padding: 40,
                color: TOKEN.textSecondary,
                fontSize: 16,
              }}>
                暂无订单记录
              </div>
            ) : (
              paidOrders.map((order) => (
                <div key={order.orderId} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '14px 16px',
                  background: TOKEN.bgPrimary,
                  borderRadius: 10,
                  marginBottom: 10,
                  border: `1px solid ${TOKEN.border}`,
                  minHeight: 56,
                }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: TOKEN.textPrimary }}>
                      {order.orderId}
                    </div>
                    <div style={{ fontSize: 13, color: TOKEN.textSecondary }}>
                      {order.time} · {order.method === 'wechat' ? '扫码支付' : '现金'}
                    </div>
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: TOKEN.primary }}>
                    ¥{fenToYuan(order.total)}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'reports' && (
          <div style={{ flex: 1, overflowY: 'auto', padding: 16, WebkitOverflowScrolling: 'touch' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: TOKEN.textPrimary, marginBottom: 16 }}>
              档口今日报表
            </div>
            {MOCK_OUTLETS.map((outlet) => (
              <div key={outlet.id} style={{
                background: TOKEN.bgPrimary,
                borderRadius: 12,
                padding: 16,
                marginBottom: 12,
                border: `1px solid ${TOKEN.border}`,
              }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 12,
                }}>
                  <span style={{ fontSize: 17, fontWeight: 700, color: TOKEN.textPrimary }}>
                    {outlet.name}
                  </span>
                  <span style={{
                    fontSize: 12,
                    padding: '2px 8px',
                    borderRadius: 4,
                    background: TOKEN.bgSecondary,
                    color: TOKEN.textSecondary,
                    fontWeight: 600,
                  }}>
                    {outlet.outlet_code}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div style={{
                    padding: '12px',
                    background: TOKEN.bgSecondary,
                    borderRadius: 8,
                  }}>
                    <div style={{ fontSize: 13, color: TOKEN.textSecondary }}>营业额</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: TOKEN.primary }}>
                      ¥{fenToYuan(outlet.today_revenue_fen)}
                    </div>
                  </div>
                  <div style={{
                    padding: '12px',
                    background: TOKEN.bgSecondary,
                    borderRadius: 8,
                  }}>
                    <div style={{ fontSize: 13, color: TOKEN.textSecondary }}>订单数</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: TOKEN.textPrimary }}>
                      {outlet.today_order_count}单
                    </div>
                  </div>
                </div>
                {/* 简单条形图 */}
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, color: TOKEN.textSecondary, marginBottom: 4 }}>
                    占广场总额比例
                  </div>
                  <div style={{
                    height: 8,
                    background: TOKEN.bgSecondary,
                    borderRadius: 4,
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      height: '100%',
                      width: `${Math.round(outlet.today_revenue_fen / 640800 * 100)}%`,
                      background: TOKEN.primary,
                      borderRadius: 4,
                      transition: 'width 600ms ease',
                    }} />
                  </div>
                  <div style={{ fontSize: 12, color: TOKEN.textSecondary, marginTop: 2 }}>
                    {Math.round(outlet.today_revenue_fen / 640800 * 100)}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── 底部 Tab ── */}
      <div style={{
        display: 'flex',
        background: TOKEN.bgPrimary,
        borderTop: `1px solid ${TOKEN.border}`,
        flexShrink: 0,
        height: 64,
      }}>
        {([
          { key: 'cashier', label: '收银', icon: '💰' },
          { key: 'orders', label: '订单', icon: '📋' },
          { key: 'reports', label: '报表', icon: '📊' },
        ] as { key: TabKey; label: string; icon: string }[]).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              flex: 1,
              height: 64,
              border: 'none',
              background: 'transparent',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 2,
              cursor: 'pointer',
              borderTop: activeTab === tab.key ? `3px solid ${TOKEN.primary}` : '3px solid transparent',
              transition: 'all 200ms ease',
            }}
          >
            <span style={{ fontSize: 22 }}>{tab.icon}</span>
            <span style={{
              fontSize: 13,
              fontWeight: 600,
              color: activeTab === tab.key ? TOKEN.primary : TOKEN.textSecondary,
            }}>
              {tab.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
