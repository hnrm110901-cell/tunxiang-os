/**
 * TableDetailPage — 桌台操作中心
 *
 * 对标天财商龙移动收银截图，核心页面设计：
 *
 * ┌─────────────────────────────────┐
 * │ < A1(4人)            显示详情   │  ← 顶部栏
 * ├────────────────┬────────────────┤
 * │ 下单明细 ▲    │  核对数量       │  ← 双Tab
 * ├─────────────────────────────────┤
 * │ 1. 米饭+茶水   x4      ¥4      │
 * │ 2. 小炒黄牛吊龙 x1    ¥55      │  ← 订单明细/核对数量视图
 * │ 3. ...                         │
 * │                      编辑排序   │
 * ├─────────────────────────────────┤
 * │ [加单] [结算] [埋单] [起菜] [上菜] │
 * │ [停菜] [变价] [称重] [赠单] [退单] │  ← 5列操作宫格
 * │ [催单] [改台] [单转] [换台] [关台] │
 * │ [核对] [打印] [会员] [通知] [转账] │
 * │ [并账]                          │
 * └─────────────────────────────────┘
 *
 * 遵循 Store终端触控规范：
 *   - 最小热区 48×48px
 *   - 最小字体 16px
 *   - 白色主背景（与天财商龙对齐）
 *   - 图标+标签，清晰易辨
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  preBill,
  fireToKitchen,
  markItemServed,
  overrideItemPrice,
  transferSingleItem,
  printOrderReceipt,
  sendKitchenMessage,
  transferPayment,
  updateTableInfo,
  getOrderKdsStatus,
} from '../api/mobileOpsApi';
import { ConstraintStatusBar } from './ConstraintStatusBar';
import { ServiceSuggestionCard } from './ServiceSuggestionCard';
import type { ServiceSuggestion } from './ServiceSuggestionCard';

// ─── 类型 ───

interface OrderItem {
  item_id: string;
  dish_id: string;
  dish_name: string;
  qty: number;
  price_fen: number;
  spec?: string;
  note?: string;
  is_served: boolean;   // 是否已上桌（核对数量用）
  served_qty: number;   // 已上桌数量
  is_gift: boolean;     // 是否赠单
}

interface OrderDetail {
  order_id: string;
  table_no: string;
  guest_count: number;
  total_fen: number;
  items: OrderItem[];
  waiter_name?: string;
  created_at: string;
}

type ActiveTab = 'detail' | 'verify';
type ActiveModal =
  | 'none'
  | 'gift'           // 赠单
  | 'price-change'   // 菜品变价
  | 'weight'         // 称重
  | 'item-transfer'  // 单品转台
  | 'kitchen-msg'    // 后厨通知
  | 'close-table'    // 关台确认
  | 'edit-table'     // 修改开台
  | 'pay-transfer'   // 转账
  | 'print-confirm'; // 打印客单确认

// ─── Mock 数据 ───

const MOCK_ORDER: OrderDetail = {
  order_id: 'o-mock-001',
  table_no: 'A1',
  guest_count: 4,
  total_fen: 24800,
  waiter_name: '张服务员',
  created_at: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
  items: [
    { item_id: 'i1', dish_id: 'd10', dish_name: '米饭+茶水', qty: 4, price_fen: 100, is_served: true, served_qty: 4, is_gift: false },
    { item_id: 'i2', dish_id: 'd2', dish_name: '小炒黄牛吊龙', qty: 1, price_fen: 5500, is_served: true, served_qty: 1, is_gift: false },
    { item_id: 'i3', dish_id: 'd7', dish_name: '十五生腌傍', qty: 1, price_fen: 3500, is_served: false, served_qty: 0, is_gift: false },
    { item_id: 'i4', dish_id: 'd1', dish_name: '剁椒鱼头（黄剁椒）', qty: 1, price_fen: 8800, is_served: false, served_qty: 0, is_gift: false },
    { item_id: 'i5', dish_id: 'd9', dish_name: '老鸭汤', qty: 1, price_fen: 4800, is_served: false, served_qty: 0, is_gift: false },
    { item_id: 'i6', dish_id: 'd11', dish_name: '酸梅汤', qty: 2, price_fen: 800, is_served: true, served_qty: 2, is_gift: false },
  ],
};

// ─── Design Token（Store终端白色模式，对标天财商龙） ───

const T = {
  bg: '#F5F5F5',           // 页面背景
  white: '#FFFFFF',         // 卡片背景
  primary: '#FF6B35',       // 主色
  text1: '#1A1A1A',         // 主文字
  text2: '#666666',         // 次要文字
  text3: '#AAAAAA',         // 辅助文字
  border: '#E8E8E8',        // 分割线
  success: '#0F6E56',       // 已上桌绿
  warning: '#BA7517',       // 部分上桌黄
  danger: '#A32D2D',        // 未上桌/退单红
  gift: '#6B3FA0',          // 赠单紫
  tabActive: '#1A9BE8',     // Tab选中色（天财商龙蓝）
};

// ─── 辅助函数 ───

function fmtMoney(fen: number): string {
  return `¥${(fen / 100).toFixed(0)}`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${m}`;
}

// ─── 子组件：操作宫格图标 ───

const OPS_GRID = [
  // Row 1
  { key: 'add-order',  label: '加单',     icon: '➕',  action: 'add-order'    },
  { key: 'checkout',   label: '结算',     icon: '💳',  action: 'checkout'     },
  { key: 'pre-bill',   label: '埋单',     icon: '📋',  action: 'pre-bill'     },
  { key: 'fire',       label: '起菜',     icon: '🔥',  action: 'fire'         },
  { key: 'mark-served',label: '上菜(划菜)',icon: '✅',  action: 'mark-served'  },
  // Row 2
  { key: 'stop-dish',  label: '停菜',     icon: '⛔',  action: 'stop-dish'    },
  { key: 'price',      label: '菜品变价', icon: '💰',  action: 'price-change' },
  { key: 'weight',     label: '称重',     icon: '⚖️',  action: 'weight'       },
  { key: 'gift',       label: '赠单',     icon: '🎁',  action: 'gift'         },
  { key: 'return',     label: '退单',     icon: '❌',  action: 'return'       },
  // Row 3
  { key: 'rush',       label: '催单',     icon: '⚡',  action: 'rush'         },
  { key: 'edit-table', label: '修改开台', icon: '👥',  action: 'edit-table'   },
  { key: 'item-trans', label: '单品转台', icon: '↗️',  action: 'item-transfer'},
  { key: 'change-tab', label: '换台',     icon: '🔄',  action: 'change-table' },
  { key: 'close-tab',  label: '关台',     icon: '🚪',  action: 'close-table'  },
  // Row 4
  { key: 'verify-rec', label: '核对单据', icon: '📄',  action: 'verify-receipt'},
  { key: 'print',      label: '打印客单', icon: '🖨️',  action: 'print'        },
  { key: 'member',     label: '验证会员', icon: '👤',  action: 'member'       },
  { key: 'kitchen-msg',label: '后厨通知', icon: '📢',  action: 'kitchen-msg'  },
  { key: 'pay-trans',  label: '转账',     icon: '💸',  action: 'pay-transfer' },
  // Row 5（最后一行单独一个）
  { key: 'merge',      label: '并账',     icon: '🔗',  action: 'merge'        },
];

interface OpButtonProps {
  label: string;
  icon: string;
  onPress: () => void;
  danger?: boolean;
  primary?: boolean;
  gift?: boolean;
}

function OpButton({ label, icon, onPress, danger, primary, gift }: OpButtonProps) {
  const [pressed, setPressed] = useState(false);
  const color = danger ? T.danger : gift ? T.gift : primary ? T.primary : T.text1;

  return (
    <button
      onTouchStart={() => setPressed(true)}
      onTouchEnd={() => { setPressed(false); onPress(); }}
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => { setPressed(false); onPress(); }}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        minHeight: 72,
        minWidth: 60,
        background: pressed ? `${T.border}` : T.white,
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        cursor: 'pointer',
        transform: pressed ? 'scale(0.95)' : 'scale(1)',
        transition: 'transform 0.15s, background 0.1s',
        padding: '8px 4px',
      }}
    >
      <span style={{ fontSize: 24, lineHeight: 1 }}>{icon}</span>
      <span
        style={{
          fontSize: 13,
          color,
          fontWeight: primary || danger || gift ? 600 : 400,
          lineHeight: 1.2,
          textAlign: 'center',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
    </button>
  );
}

// ─── 子组件：下单明细 Tab ───

function OrderDetailTab({
  items,
  editMode,
  onToggleEdit,
  onGift,
}: {
  items: OrderItem[];
  editMode: boolean;
  onToggleEdit: () => void;
  onGift: (itemId: string) => void;
}) {
  const totalFen = items.reduce((s, i) => s + i.price_fen * i.qty, 0);

  return (
    <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as any }}>
      {/* 编辑排序按钮 */}
      <div
        style={{
          textAlign: 'right',
          padding: '6px 16px',
          borderBottom: `1px solid ${T.border}`,
        }}
      >
        <button
          onClick={onToggleEdit}
          style={{
            fontSize: 14,
            color: editMode ? T.primary : T.text3,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: '4px 8px',
            minHeight: 36,
          }}
        >
          {editMode ? '完成' : '编辑排序'}
        </button>
      </div>

      {/* 菜品列表 */}
      {items.map((item, idx) => (
        <div
          key={item.item_id}
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '14px 16px',
            borderBottom: `1px solid ${T.border}`,
            background: item.is_gift ? '#F9F0FF' : T.white,
            gap: 10,
          }}
        >
          {/* 拖拽手柄（编辑模式） */}
          {editMode && (
            <span style={{ color: T.text3, fontSize: 20, flexShrink: 0 }}>☰</span>
          )}

          {/* 序号 */}
          <span
            style={{
              fontSize: 16,
              color: T.text3,
              minWidth: 24,
              flexShrink: 0,
            }}
          >
            {idx + 1}.
          </span>

          {/* 菜名 + 规格 */}
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 17,
                color: T.text1,
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {item.dish_name}
              {item.is_gift && (
                <span
                  style={{
                    fontSize: 12,
                    color: T.gift,
                    background: '#EDE0FF',
                    borderRadius: 4,
                    padding: '1px 6px',
                    fontWeight: 600,
                  }}
                >
                  赠
                </span>
              )}
            </div>
            {item.spec && (
              <div style={{ fontSize: 14, color: T.text3, marginTop: 2 }}>
                {item.spec}
              </div>
            )}
          </div>

          {/* 数量 */}
          <span style={{ fontSize: 16, color: T.text2, minWidth: 32, textAlign: 'center' }}>
            x{item.qty}
          </span>

          {/* 金额 */}
          <span
            style={{
              fontSize: 17,
              color: item.is_gift ? T.gift : '#E53E3E',
              fontWeight: 600,
              minWidth: 52,
              textAlign: 'right',
            }}
          >
            {item.is_gift ? '赠' : fmtMoney(item.price_fen * item.qty)}
          </span>
        </div>
      ))}

      {/* 合计 */}
      <div
        style={{
          padding: '14px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderTop: `2px solid ${T.border}`,
          background: T.white,
        }}
      >
        <span style={{ fontSize: 16, color: T.text2 }}>
          合计 {items.length} 道菜
        </span>
        <span style={{ fontSize: 22, fontWeight: 700, color: '#E53E3E' }}>
          {fmtMoney(totalFen)}
        </span>
      </div>
    </div>
  );
}

// ─── 子组件：核对数量 Tab ───

function VerifyTab({ items }: { items: OrderItem[] }) {
  const allServed = items.every((i) => i.served_qty >= i.qty);
  const someServed = items.some((i) => i.served_qty > 0);

  return (
    <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as any }}>
      {/* 整体状态横幅 */}
      <div
        style={{
          padding: '12px 16px',
          background: allServed ? '#EFF9F5' : someServed ? '#FFF8E6' : '#FFF0F0',
          borderBottom: `1px solid ${T.border}`,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <span style={{ fontSize: 20 }}>
          {allServed ? '✅' : someServed ? '⏳' : '⚠️'}
        </span>
        <div>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: allServed ? T.success : someServed ? T.warning : T.danger,
            }}
          >
            {allServed ? '全部已上桌' : someServed ? '部分已上桌' : '菜品尚未上桌'}
          </div>
          <div style={{ fontSize: 13, color: T.text3, marginTop: 2 }}>
            已上 {items.filter((i) => i.served_qty >= i.qty).length} /{' '}
            {items.length} 道
          </div>
        </div>
      </div>

      {/* 按状态分组显示 */}
      {[
        {
          label: '未上桌',
          items: items.filter((i) => i.served_qty === 0),
          color: T.danger,
          bg: '#FFF0F0',
        },
        {
          label: '部分上桌',
          items: items.filter((i) => i.served_qty > 0 && i.served_qty < i.qty),
          color: T.warning,
          bg: '#FFF8E6',
        },
        {
          label: '已全部上桌',
          items: items.filter((i) => i.served_qty >= i.qty),
          color: T.success,
          bg: '#EFF9F5',
        },
      ]
        .filter((g) => g.items.length > 0)
        .map((group) => (
          <div key={group.label}>
            <div
              style={{
                padding: '8px 16px',
                background: T.bg,
                fontSize: 14,
                color: T.text3,
                fontWeight: 600,
              }}
            >
              {group.label}（{group.items.length}）
            </div>
            {group.items.map((item) => (
              <div
                key={item.item_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '14px 16px',
                  borderBottom: `1px solid ${T.border}`,
                  background: group.bg,
                  gap: 10,
                }}
              >
                {/* 状态点 */}
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 5,
                    background: group.color,
                    flexShrink: 0,
                  }}
                />

                {/* 菜名 */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 17, color: T.text1 }}>{item.dish_name}</div>
                  {item.spec && (
                    <div style={{ fontSize: 13, color: T.text3, marginTop: 2 }}>
                      {item.spec}
                    </div>
                  )}
                </div>

                {/* 已上/总计 */}
                <div style={{ textAlign: 'right' }}>
                  <span
                    style={{
                      fontSize: 22,
                      fontWeight: 700,
                      color: group.color,
                    }}
                  >
                    {item.served_qty}
                  </span>
                  <span style={{ fontSize: 16, color: T.text3 }}>/{item.qty}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}

// ─── 子组件：简单输入弹窗 ───

function InputModal({
  title,
  placeholder,
  onConfirm,
  onCancel,
  inputType,
}: {
  title: string;
  placeholder: string;
  onConfirm: (value: string) => void;
  onCancel: () => void;
  inputType?: string;
}) {
  const [val, setVal] = useState('');
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'flex-end',
        zIndex: 100,
      }}
      onClick={onCancel}
    >
      <div
        style={{
          width: '100%',
          background: T.white,
          borderRadius: '16px 16px 0 0',
          padding: '20px 20px 40px',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ fontSize: 18, fontWeight: 700, color: T.text1, marginBottom: 16 }}>
          {title}
        </div>
        <input
          type={inputType || 'text'}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder={placeholder}
          autoFocus
          style={{
            width: '100%',
            fontSize: 18,
            padding: '14px 16px',
            border: `2px solid ${T.primary}`,
            borderRadius: 10,
            outline: 'none',
            boxSizing: 'border-box',
            marginBottom: 16,
          }}
        />
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1,
              minHeight: 56,
              background: T.bg,
              color: T.text2,
              border: 'none',
              borderRadius: 10,
              fontSize: 17,
              cursor: 'pointer',
            }}
          >
            取消
          </button>
          <button
            onClick={() => val && onConfirm(val)}
            disabled={!val}
            style={{
              flex: 2,
              minHeight: 56,
              background: val ? T.primary : T.text3,
              color: '#fff',
              border: 'none',
              borderRadius: 10,
              fontSize: 17,
              fontWeight: 700,
              cursor: val ? 'pointer' : 'not-allowed',
            }}
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：赠单弹窗 ───

function GiftModal({
  items,
  onConfirm,
  onCancel,
}: {
  items: OrderItem[];
  onConfirm: (itemIds: string[], reason: string) => void;
  onCancel: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState('');
  const REASONS = ['招待贵宾', '菜品质量问题', '服务补偿', '老板赠送', '其他'];

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex',
        alignItems: 'flex-end',
        zIndex: 100,
      }}
      onClick={onCancel}
    >
      <div
        style={{
          width: '100%',
          background: T.white,
          borderRadius: '16px 16px 0 0',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          padding: '20px 0 0',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: T.text1,
            padding: '0 20px 16px',
            borderBottom: `1px solid ${T.border}`,
          }}
        >
          🎁 赠单 — 选择赠送菜品
        </div>

        {/* 菜品多选 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {items.map((item) => (
            <div
              key={item.item_id}
              onClick={() => toggle(item.item_id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '14px 20px',
                borderBottom: `1px solid ${T.border}`,
                background: selected.has(item.item_id) ? '#F9F0FF' : T.white,
                gap: 14,
                cursor: 'pointer',
              }}
            >
              <div
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: 6,
                  border: `2px solid ${selected.has(item.item_id) ? T.gift : T.border}`,
                  background: selected.has(item.item_id) ? T.gift : T.white,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                {selected.has(item.item_id) && (
                  <span style={{ color: '#fff', fontSize: 14, fontWeight: 700 }}>✓</span>
                )}
              </div>
              <span style={{ flex: 1, fontSize: 17, color: T.text1 }}>
                {item.dish_name}
              </span>
              <span style={{ fontSize: 16, color: T.text2 }}>
                x{item.qty} {fmtMoney(item.price_fen * item.qty)}
              </span>
            </div>
          ))}
        </div>

        {/* 赠单原因 */}
        <div style={{ padding: '12px 20px', borderTop: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 15, color: T.text2, marginBottom: 10 }}>赠单原因</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' as any, marginBottom: 12 }}>
            {REASONS.map((r) => (
              <button
                key={r}
                onClick={() => setReason(r)}
                style={{
                  padding: '8px 14px',
                  minHeight: 40,
                  background: reason === r ? T.gift : T.bg,
                  color: reason === r ? '#fff' : T.text2,
                  border: `1px solid ${reason === r ? T.gift : T.border}`,
                  borderRadius: 20,
                  fontSize: 15,
                  cursor: 'pointer',
                }}
              >
                {r}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={onCancel}
              style={{
                flex: 1, minHeight: 56, background: T.bg, color: T.text2,
                border: 'none', borderRadius: 10, fontSize: 17, cursor: 'pointer',
              }}
            >
              取消
            </button>
            <button
              onClick={() => selected.size > 0 && reason && onConfirm([...selected], reason)}
              disabled={selected.size === 0 || !reason}
              style={{
                flex: 2, minHeight: 56,
                background: selected.size > 0 && reason ? T.gift : T.text3,
                color: '#fff', border: 'none', borderRadius: 10,
                fontSize: 17, fontWeight: 700, cursor: selected.size > 0 && reason ? 'pointer' : 'not-allowed',
              }}
            >
              确认赠单（{selected.size}道）
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 主组件 ───

export function TableDetailPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tableNo = params.get('table') || 'A1';
  const orderId = params.get('order_id') || '';

  const [order, setOrder] = useState<OrderDetail>(MOCK_ORDER);
  const [activeTab, setActiveTab] = useState<ActiveTab>('detail');
  const [editMode, setEditMode] = useState(false);
  const [modal, setModal] = useState<ActiveModal>('none');
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }, []);

  const closeModal = useCallback(() => setModal('none'), []);

  // ── 操作处理 ──

  const handleAction = useCallback(async (action: string) => {
    switch (action) {
      case 'add-order':
        navigate(`/order-full?table=${tableNo}&order_id=${orderId}&mode=add`);
        break;
      case 'checkout':
        navigate(`/order-full?table=${tableNo}&order_id=${orderId}&mode=checkout`);
        break;
      case 'pre-bill':
        setLoading(true);
        try {
          await preBill(orderId || order.order_id);
          showToast('埋单成功，账单已打印');
        } finally {
          setLoading(false);
        }
        break;
      case 'fire':
        setLoading(true);
        try {
          await fireToKitchen(orderId || order.order_id);
          showToast('已通知后厨起菜');
        } finally {
          setLoading(false);
        }
        break;
      case 'mark-served':
        showToast('请在出餐追踪页面选择已上菜品');
        navigate(`/order-status?order_id=${orderId || order.order_id}`);
        break;
      case 'stop-dish':
        navigate(`/shortage?table=${tableNo}`);
        break;
      case 'price-change':
        setModal('price-change');
        break;
      case 'weight':
        setModal('weight');
        break;
      case 'gift':
        setModal('gift');
        break;
      case 'return':
        navigate(`/order-full?table=${tableNo}&order_id=${orderId}&mode=return`);
        break;
      case 'rush':
        navigate(`/rush?table=${tableNo}&order_id=${orderId || order.order_id}`);
        break;
      case 'edit-table':
        setModal('edit-table');
        break;
      case 'item-transfer':
        setModal('item-transfer');
        break;
      case 'change-table':
        navigate(`/table-ops?action=transfer&source=${tableNo}`);
        break;
      case 'close-table':
        setModal('close-table');
        break;
      case 'verify-receipt':
        setActiveTab('verify');
        break;
      case 'print':
        setLoading(true);
        try {
          await printOrderReceipt(orderId || order.order_id);
          showToast('客单已打印');
        } finally {
          setLoading(false);
        }
        break;
      case 'member':
        navigate(`/member?order_id=${orderId || order.order_id}`);
        break;
      case 'kitchen-msg':
        setModal('kitchen-msg');
        break;
      case 'pay-transfer':
        setModal('pay-transfer');
        break;
      case 'merge':
        navigate(`/table-ops?action=merge&source=${tableNo}`);
        break;
      default:
        showToast(`${action} 功能开发中`);
    }
  }, [navigate, order.order_id, orderId, tableNo, showToast]);

  const handleGift = useCallback((itemIds: string[], reason: string) => {
    setOrder((prev) => ({
      ...prev,
      items: prev.items.map((item) =>
        itemIds.includes(item.item_id) ? { ...item, is_gift: true } : item
      ),
    }));
    showToast(`已标记赠单，原因：${reason}`);
    closeModal();
  }, [closeModal, showToast]);

  // 危险操作：关台二次确认
  const handleCloseTable = useCallback(async () => {
    setLoading(true);
    try {
      showToast('已关台');
      navigate('/tables');
    } finally {
      setLoading(false);
      closeModal();
    }
  }, [navigate, showToast, closeModal]);

  const displayNo = `${order.table_no}(${order.guest_count}人)`;

  return (
    <div
      style={{
        background: T.bg,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        fontSize: 16,
        color: T.text1,
        maxWidth: 480,
        margin: '0 auto',
      }}
    >
      {/* ── 顶部导航栏 ── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          height: 52,
          background: T.tabActive,
          flexShrink: 0,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            background: 'none',
            border: 'none',
            color: '#fff',
            fontSize: 17,
            cursor: 'pointer',
            padding: '8px 8px 8px 0',
            minHeight: 48,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          ‹ {displayNo}
        </button>
        <button
          onClick={() => navigate(`/order-status?order_id=${orderId || order.order_id}`)}
          style={{
            background: 'none',
            border: 'none',
            color: '#fff',
            fontSize: 16,
            cursor: 'pointer',
            minHeight: 48,
            padding: '8px 0 8px 8px',
          }}
        >
          显示详情
        </button>
      </header>

      {/* ── 三约束实时看板（Phase 3-B） ── */}
      <ConstraintStatusBar
        orderId={orderId || order.order_id}
        storeId={(window as any).__STORE_ID__ || 'store-mock-001'}
      />

      {/* ── Tab 切换 ── */}
      <div
        style={{
          display: 'flex',
          background: T.white,
          borderBottom: `1px solid ${T.border}`,
          flexShrink: 0,
        }}
      >
        {[
          { key: 'detail', label: '下单明细' },
          { key: 'verify', label: '核对数量' },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as ActiveTab)}
            style={{
              flex: 1,
              padding: '14px 0',
              background: 'none',
              border: 'none',
              fontSize: 17,
              fontWeight: activeTab === tab.key ? 700 : 400,
              color: activeTab === tab.key ? T.tabActive : T.text2,
              cursor: 'pointer',
              borderBottom: activeTab === tab.key ? `3px solid ${T.tabActive}` : '3px solid transparent',
              minHeight: 52,
            }}
          >
            {tab.label}
            {tab.key === 'detail' && activeTab === tab.key && (
              <span style={{ marginLeft: 4, fontSize: 12 }}>▲</span>
            )}
          </button>
        ))}
      </div>

      {/* ── 订单视图区域 ── */}
      <div
        style={{
          flex: '0 0 auto',
          maxHeight: '35vh',
          display: 'flex',
          flexDirection: 'column',
          background: T.white,
          overflow: 'hidden',
        }}
      >
        {activeTab === 'detail' ? (
          <OrderDetailTab
            items={order.items}
            editMode={editMode}
            onToggleEdit={() => setEditMode((v) => !v)}
            onGift={(id) => {
              setOrder((prev) => ({
                ...prev,
                items: prev.items.map((i) =>
                  i.item_id === id ? { ...i, is_gift: !i.is_gift } : i
                ),
              }));
            }}
          />
        ) : (
          <VerifyTab items={order.items} />
        )}
      </div>

      {/* ── 主动服务建议（Phase 3-B） ── */}
      <ServiceSuggestionCard
        orderId={orderId || order.order_id}
        onAction={(suggestion: ServiceSuggestion) => {
          if (suggestion.type === 'upsell' || suggestion.type === 'refill' || suggestion.type === 'dessert') {
            navigate(`/order-full?table=${tableNo}&order_id=${orderId || order.order_id}&mode=add`);
          } else if (suggestion.type === 'checkout_hint') {
            navigate(`/order-full?table=${tableNo}&order_id=${orderId || order.order_id}&mode=checkout`);
          }
        }}
      />

      {/* ── 操作宫格 ── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          background: T.bg,
          padding: '12px 12px 24px',
          WebkitOverflowScrolling: 'touch' as any,
        }}
      >
        {/* 网格 5列布局 */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(5, 1fr)',
            gap: 8,
          }}
        >
          {OPS_GRID.slice(0, 20).map((op) => (
            <OpButton
              key={op.key}
              label={op.label}
              icon={op.icon}
              onPress={() => handleAction(op.action)}
              danger={['return', 'close-tab', 'stop-dish'].includes(op.key)}
              primary={['checkout', 'pre-bill', 'fire'].includes(op.key)}
              gift={op.key === 'gift'}
            />
          ))}
        </div>

        {/* 并账：单独一行靠左 */}
        <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
          <OpButton
            key="merge"
            label="并账"
            icon="🔗"
            onPress={() => handleAction('merge')}
          />
        </div>

        {/* 开台时间 */}
        <div
          style={{
            textAlign: 'center',
            fontSize: 13,
            color: T.text3,
            marginTop: 16,
            padding: '8px 0',
          }}
        >
          开台时间 {fmtTime(order.created_at)}
          {order.waiter_name && ` · ${order.waiter_name}`}
        </div>
      </div>

      {/* ── Toast 提示 ── */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 80,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.75)',
            color: '#fff',
            borderRadius: 24,
            padding: '10px 20px',
            fontSize: 15,
            zIndex: 200,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}
        >
          {toast}
        </div>
      )}

      {/* ── 加载遮罩 ── */}
      {loading && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 150,
          }}
        >
          <div
            style={{
              background: T.white,
              borderRadius: 12,
              padding: '20px 32px',
              fontSize: 16,
              color: T.text1,
            }}
          >
            处理中…
          </div>
        </div>
      )}

      {/* ── 弹窗区域 ── */}
      {modal === 'gift' && (
        <GiftModal
          items={order.items.filter((i) => !i.is_gift)}
          onConfirm={handleGift}
          onCancel={closeModal}
        />
      )}

      {modal === 'kitchen-msg' && (
        <InputModal
          title="📢 后厨通知"
          placeholder="输入通知内容（如：A1桌客人过敏花生）"
          onConfirm={async (msg) => {
            await sendKitchenMessage(msg, order.table_no);
            showToast('已通知后厨');
            closeModal();
          }}
          onCancel={closeModal}
        />
      )}

      {modal === 'weight' && (
        <InputModal
          title="⚖️ 称重点菜"
          placeholder="输入重量（克）"
          onConfirm={(w) => {
            showToast(`称重 ${w}克，已加入订单`);
            closeModal();
          }}
          onCancel={closeModal}
          inputType="number"
        />
      )}

      {modal === 'price-change' && (
        <InputModal
          title="💰 菜品变价"
          placeholder="输入新价格（元）"
          onConfirm={(p) => {
            showToast(`价格已变更为 ¥${p}`);
            closeModal();
          }}
          onCancel={closeModal}
          inputType="number"
        />
      )}

      {modal === 'close-table' && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.55)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            padding: '0 24px',
          }}
          onClick={closeModal}
        >
          <div
            style={{
              background: T.white,
              borderRadius: 16,
              padding: 24,
              width: '100%',
              maxWidth: 340,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontSize: 18, fontWeight: 700, color: T.text1, marginBottom: 12 }}>
              确认关台？
            </div>
            <div style={{ fontSize: 15, color: T.text2, marginBottom: 24, lineHeight: 1.6 }}>
              关台将清除 {displayNo} 的当前订单记录，确认关台前请先完成结账。
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={closeModal}
                style={{
                  flex: 1, minHeight: 56, background: T.bg, color: T.text2,
                  border: 'none', borderRadius: 10, fontSize: 17, cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleCloseTable}
                style={{
                  flex: 1, minHeight: 56, background: T.danger, color: '#fff',
                  border: 'none', borderRadius: 10, fontSize: 17, fontWeight: 700, cursor: 'pointer',
                }}
              >
                确认关台
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
