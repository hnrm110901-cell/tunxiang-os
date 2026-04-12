/**
 * 供应链管理 — 收货验收 + 门店调拨
 * 深色主题，与 EventBusHealthPage 风格一致
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

interface ReceivingItem {
  id: string;
  ingredient_name: string;
  expected_qty: number;
  received_qty?: number;
  unit: string;
  unit_price_fen: number;
  quality_grade?: 'normal' | 'minor_damage' | 'rejected';
}

interface ReceivingOrder {
  id: string;
  store_id: string;
  store_name?: string;
  supplier_name: string;
  status: 'pending' | 'inspecting' | 'completed' | 'rejected';
  items: ReceivingItem[];
  created_at: string;
}

interface TransferOrder {
  id: string;
  from_store_name: string;
  to_store_name: string;
  status: 'draft' | 'approved' | 'shipped' | 'received' | 'cancelled';
  items: { ingredient_name: string; qty: number; unit: string }[];
  created_at: string;
  operator_name?: string;
}

// ─── 常量 ───

const RECEIVING_STATUS_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  pending:    { label: '待验收', color: '#BA7517', bg: '#BA751722' },
  inspecting: { label: '验收中', color: '#2196f3', bg: '#2196f322' },
  completed:  { label: '已完成', color: '#0F6E56', bg: '#0F6E5622' },
  rejected:   { label: '已拒收', color: '#FF4D4D', bg: '#FF4D4D22' },
};

const TRANSFER_STATUS_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  draft:     { label: '待审批', color: '#BA7517', bg: '#BA751722' },
  approved:  { label: '已审批', color: '#2196f3', bg: '#2196f322' },
  shipped:   { label: '发货中', color: '#9c27b0', bg: '#9c27b022' },
  received:  { label: '已收货', color: '#0F6E56', bg: '#0F6E5622' },
  cancelled: { label: '已取消', color: '#666',    bg: '#66666622' },
};

const QUALITY_LABELS = {
  normal:       '正常',
  minor_damage: '轻微损坏',
  rejected:     '拒收',
};

// ─── 工具函数 ───

function formatTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return isoStr;
  }
}

function priceFenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── 子组件：收货单卡片 ───

interface ReceivingCardProps {
  order: ReceivingOrder;
  onOpenDrawer: (order: ReceivingOrder) => void;
  onStartInspect: (orderId: string) => void;
  successIds: Set<string>;
}

function ReceivingCard({ order, onOpenDrawer, onStartInspect, successIds }: ReceivingCardProps) {
  const st = RECEIVING_STATUS_LABELS[order.status] || RECEIVING_STATUS_LABELS.pending;
  const totalExpected = order.items.reduce((s, i) => s + i.expected_qty, 0);
  const isSuccess = successIds.has(order.id);

  return (
    <div style={{
      background: '#1a2a33',
      border: `1px solid ${isSuccess ? '#0F6E56' : '#2a3a44'}`,
      borderRadius: 10,
      padding: '16px 20px',
      marginBottom: 12,
      transition: 'border-color 0.3s',
    }}>
      {/* 顶行 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 16 }}>📦</span>
          <span style={{ color: '#fff', fontWeight: 700, fontSize: 14 }}>
            收货单 #{order.id.slice(-10).toUpperCase()}
          </span>
          <span style={{
            padding: '2px 10px', borderRadius: 10, fontSize: 11,
            background: st.bg, color: st.color,
          }}>
            {st.label}
          </span>
          {order.store_name && (
            <span style={{ color: '#888', fontSize: 12 }}>🏪 {order.store_name}</span>
          )}
        </div>
        {isSuccess && (
          <span style={{ color: '#0F6E56', fontSize: 13, fontWeight: 600 }}>入库成功 ✅</span>
        )}
      </div>

      {/* 中行摘要 */}
      <div style={{ color: '#aaa', fontSize: 13, marginBottom: 12 }}>
        供应商：{order.supplier_name} &nbsp;·&nbsp;
        食材：{order.items.length}种 &nbsp;·&nbsp;
        预计总量：{totalExpected.toFixed(1)}kg
      </div>

      {/* 底行操作 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#666', fontSize: 12 }}>创建时间：{formatTime(order.created_at)}</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => onOpenDrawer(order)}
            style={{
              padding: '5px 14px', borderRadius: 6, border: '1px solid #2a3a44',
              background: 'transparent', color: '#ccc', cursor: 'pointer', fontSize: 12,
            }}
          >
            查看详情
          </button>
          {(order.status === 'pending' || order.status === 'inspecting') && (
            <button
              onClick={() => onStartInspect(order.id)}
              style={{
                padding: '5px 14px', borderRadius: 6, border: 'none',
                background: '#2196f3', color: '#fff', cursor: 'pointer', fontSize: 12,
                fontWeight: 600,
              }}
            >
              开始验收
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：收货详情抽屉 ───

interface ReceivingDrawerProps {
  order: ReceivingOrder;
  onClose: () => void;
  onComplete: (orderId: string) => void;
  onRejectAll: (orderId: string) => void;
  onInspectItem: (orderId: string, itemId: string, data: { received_qty: number; quality_grade: string }) => void;
}

function ReceivingDrawer({ order, onClose, onComplete, onRejectAll, onInspectItem }: ReceivingDrawerProps) {
  const [itemEdits, setItemEdits] = useState<Record<string, { qty: string; grade: string }>>(() => {
    const init: Record<string, { qty: string; grade: string }> = {};
    order.items.forEach(item => {
      init[item.id] = {
        qty: item.received_qty != null ? String(item.received_qty) : String(item.expected_qty),
        grade: item.quality_grade || 'normal',
      };
    });
    return init;
  });
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [completing, setCompleting] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  const handleSaveItem = async (itemId: string) => {
    const edit = itemEdits[itemId];
    if (!edit) return;
    setSaving(s => ({ ...s, [itemId]: true }));
    try {
      await onInspectItem(order.id, itemId, {
        received_qty: parseFloat(edit.qty) || 0,
        quality_grade: edit.grade,
      });
    } finally {
      setSaving(s => ({ ...s, [itemId]: false }));
    }
  };

  return (
    <>
      {/* 背景遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 199,
        }}
      />
      {/* 抽屉本体 */}
      <div style={{
        position: 'fixed', right: 0, top: 0, height: '100vh', width: 420,
        background: '#1a2a33', zIndex: 200,
        boxShadow: '-4px 0 24px rgba(0,0,0,0.4)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        {/* 抽屉头 */}
        <div style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid #2a3a44',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>
              📦 收货单 #{order.id.slice(-10).toUpperCase()}
            </div>
            <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
              {order.supplier_name} · {order.store_name || order.store_id}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent', border: 'none', color: '#888',
              fontSize: 20, cursor: 'pointer', padding: '0 4px',
            }}
          >
            ✕
          </button>
        </div>

        {/* 食材列表 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
          {order.items.map(item => {
            const edit = itemEdits[item.id] || { qty: String(item.expected_qty), grade: 'normal' };
            return (
              <div key={item.id} style={{
                background: '#0d1e28', borderRadius: 8, padding: '14px 16px',
                marginBottom: 12, border: '1px solid #2a3a44',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                  <span style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>
                    {item.ingredient_name}
                  </span>
                  <span style={{ color: '#888', fontSize: 12 }}>
                    ¥{priceFenToYuan(item.unit_price_fen)}/{item.unit}
                  </span>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#666', marginBottom: 4 }}>预期数量</div>
                    <div style={{ fontSize: 14, color: '#aaa' }}>
                      {item.expected_qty} {item.unit}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#666', marginBottom: 4 }}>实收数量</div>
                    <input
                      type="number"
                      value={edit.qty}
                      onChange={e => setItemEdits(s => ({ ...s, [item.id]: { ...edit, qty: e.target.value } }))}
                      style={{
                        width: '100%', padding: '5px 8px', borderRadius: 5,
                        border: '1px solid #2a3a44', background: '#1a2a33',
                        color: '#fff', fontSize: 13, outline: 'none',
                      }}
                    />
                  </div>
                </div>

                {/* 质量评级 */}
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, color: '#666', marginBottom: 6 }}>质量评级</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {(['normal', 'minor_damage', 'rejected'] as const).map(grade => (
                      <label key={grade} style={{
                        display: 'flex', alignItems: 'center', gap: 5,
                        cursor: 'pointer', fontSize: 12, color: edit.grade === grade ? '#fff' : '#888',
                      }}>
                        <input
                          type="radio"
                          name={`grade-${item.id}`}
                          value={grade}
                          checked={edit.grade === grade}
                          onChange={() => setItemEdits(s => ({ ...s, [item.id]: { ...edit, grade } }))}
                          style={{ accentColor: '#2196f3' }}
                        />
                        {QUALITY_LABELS[grade]}
                      </label>
                    ))}
                  </div>
                </div>

                <button
                  onClick={() => handleSaveItem(item.id)}
                  disabled={saving[item.id]}
                  style={{
                    padding: '5px 14px', borderRadius: 5, border: 'none',
                    background: saving[item.id] ? '#2a3a44' : '#2196f3',
                    color: '#fff', cursor: saving[item.id] ? 'default' : 'pointer',
                    fontSize: 12, fontWeight: 600,
                  }}
                >
                  {saving[item.id] ? '保存中...' : '保存验收'}
                </button>
              </div>
            );
          })}
        </div>

        {/* 底部操作 */}
        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid #2a3a44',
          display: 'flex', gap: 12,
        }}>
          <button
            onClick={async () => { setCompleting(true); try { await onComplete(order.id); onClose(); } finally { setCompleting(false); } }}
            disabled={completing}
            style={{
              flex: 1, padding: '10px 0', borderRadius: 7, border: 'none',
              background: completing ? '#2a3a44' : '#0F6E56',
              color: '#fff', cursor: completing ? 'default' : 'pointer',
              fontSize: 14, fontWeight: 700,
            }}
          >
            {completing ? '处理中...' : '✅ 完成入库'}
          </button>
          <button
            onClick={async () => { setRejecting(true); try { await onRejectAll(order.id); onClose(); } finally { setRejecting(false); } }}
            disabled={rejecting}
            style={{
              flex: 1, padding: '10px 0', borderRadius: 7, border: 'none',
              background: rejecting ? '#2a3a44' : '#A32D2D',
              color: '#fff', cursor: rejecting ? 'default' : 'pointer',
              fontSize: 14, fontWeight: 700,
            }}
          >
            {rejecting ? '处理中...' : '❌ 全部拒收'}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── 子组件：调拨单卡片 ───

interface TransferCardProps {
  order: TransferOrder;
  onAction: (orderId: string, action: 'approve' | 'ship' | 'receive' | 'cancel') => Promise<void>;
}

function TransferCard({ order, onAction }: TransferCardProps) {
  const st = TRANSFER_STATUS_LABELS[order.status] || TRANSFER_STATUS_LABELS.draft;
  const [loading, setLoading] = useState<string | null>(null);

  const handleAction = async (action: 'approve' | 'ship' | 'receive' | 'cancel') => {
    setLoading(action);
    try { await onAction(order.id, action); } finally { setLoading(null); }
  };

  const itemSummary = order.items.map(i => `${i.ingredient_name}: ${i.qty}${i.unit}`).join(' / ');

  return (
    <div style={{
      background: '#1a2a33', border: '1px solid #2a3a44', borderRadius: 10,
      padding: '16px 20px', marginBottom: 12,
    }}>
      {/* 顶行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 16 }}>🔄</span>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 14 }}>
          调拨单 #{order.id.slice(-10).toUpperCase()}
        </span>
        <span style={{
          padding: '2px 10px', borderRadius: 10, fontSize: 11,
          background: st.bg, color: st.color,
        }}>
          {st.label}
        </span>
      </div>

      {/* 中行摘要 */}
      <div style={{ color: '#aaa', fontSize: 13, marginBottom: 12 }}>
        {order.from_store_name} → {order.to_store_name}
        &nbsp;&nbsp;
        <span style={{ color: '#888' }}>{itemSummary}</span>
      </div>

      {/* 底行操作 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#666', fontSize: 12 }}>
          申请时间：{formatTime(order.created_at)}
          {order.operator_name && ` · ${order.operator_name}`}
        </span>
        <div style={{ display: 'flex', gap: 8 }}>
          {order.status === 'draft' && (
            <>
              <button
                onClick={() => handleAction('approve')}
                disabled={loading === 'approve'}
                style={actionBtnStyle('#0F6E56', loading === 'approve')}
              >
                {loading === 'approve' ? '...' : '审批通过'}
              </button>
              <button
                onClick={() => handleAction('cancel')}
                disabled={loading === 'cancel'}
                style={actionBtnStyle('#A32D2D', loading === 'cancel')}
              >
                {loading === 'cancel' ? '...' : '取消'}
              </button>
            </>
          )}
          {order.status === 'approved' && (
            <button
              onClick={() => handleAction('ship')}
              disabled={loading === 'ship'}
              style={actionBtnStyle('#9c27b0', loading === 'ship')}
            >
              {loading === 'ship' ? '...' : '确认发货'}
            </button>
          )}
          {order.status === 'shipped' && (
            <button
              onClick={() => handleAction('receive')}
              disabled={loading === 'receive'}
              style={actionBtnStyle('#2196f3', loading === 'receive')}
            >
              {loading === 'receive' ? '...' : '确认收货'}
            </button>
          )}
          {(order.status === 'received' || order.status === 'cancelled') && (
            <span style={{ fontSize: 12, color: '#666', fontStyle: 'italic' }}>
              {order.status === 'received' ? '已完结' : '已取消'}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function actionBtnStyle(bg: string, disabled: boolean): React.CSSProperties {
  return {
    padding: '5px 14px', borderRadius: 6, border: 'none',
    background: disabled ? '#2a3a44' : bg,
    color: '#fff', cursor: disabled ? 'default' : 'pointer',
    fontSize: 12, fontWeight: 600,
  };
}

// ─── 主页面 ───

export function SupplyChainPage() {
  const [activeTab, setActiveTab] = useState<'receiving' | 'transfer'>('receiving');

  // ── 收货验收状态 ──
  const [receivingOrders, setReceivingOrders] = useState<ReceivingOrder[]>([]);
  const [receivingLoading, setReceivingLoading] = useState(true);
  const [receivingStatusFilter, setReceivingStatusFilter] = useState('');
  const [receivingStoreFilter, setReceivingStoreFilter] = useState('');
  const [receivingDateFilter, setReceivingDateFilter] = useState('');
  const [drawerOrder, setDrawerOrder] = useState<ReceivingOrder | null>(null);
  const [successIds, setSuccessIds] = useState<Set<string>>(new Set());

  // ── 调拨管理状态 ──
  const [transferOrders, setTransferOrders] = useState<TransferOrder[]>([]);
  const [transferLoading, setTransferLoading] = useState(true);
  const [transferStatusFilter, setTransferStatusFilter] = useState('');
  const [transferPerspective, setTransferPerspective] = useState('all');

  // ── 拉取收货单 ──
  const fetchReceivingOrders = useCallback(async () => {
    setReceivingLoading(true);
    try {
      const params = new URLSearchParams();
      if (receivingStoreFilter) params.set('store_id', receivingStoreFilter);
      if (receivingStatusFilter) params.set('status', receivingStatusFilter);
      if (receivingDateFilter) params.set('date', receivingDateFilter);
      const qs = params.toString() ? `?${params.toString()}` : '';
      const data = await txFetchData<{ items: ReceivingOrder[] }>(`/api/v1/receiving/orders${qs}`);
      setReceivingOrders(data.items || []);
    } catch {
      /* 保留旧数据 */
    } finally {
      setReceivingLoading(false);
    }
  }, [receivingStoreFilter, receivingStatusFilter, receivingDateFilter]);

  // ── 拉取调拨单 ──
  const fetchTransferOrders = useCallback(async () => {
    setTransferLoading(true);
    try {
      const params = new URLSearchParams();
      if (transferStatusFilter) params.set('status', transferStatusFilter);
      if (transferPerspective !== 'all') params.set('perspective', transferPerspective);
      const qs = params.toString() ? `?${params.toString()}` : '';
      const data = await txFetchData<{ items: TransferOrder[] }>(`/api/v1/transfers${qs}`);
      setTransferOrders(data.items || []);
    } catch {
      /* 保留旧数据 */
    } finally {
      setTransferLoading(false);
    }
  }, [transferStatusFilter, transferPerspective]);

  useEffect(() => { fetchReceivingOrders(); }, [fetchReceivingOrders]);
  useEffect(() => { fetchTransferOrders(); }, [fetchTransferOrders]);

  // ── 收货操作 ──
  const handleStartInspect = useCallback(async (orderId: string) => {
    // 乐观更新状态为验收中
    setReceivingOrders(orders =>
      orders.map(o => o.id === orderId ? { ...o, status: 'inspecting' } : o)
    );
    // 打开抽屉
    const order = receivingOrders.find(o => o.id === orderId);
    if (order) setDrawerOrder({ ...order, status: 'inspecting' });
  }, [receivingOrders]);

  const handleInspectItem = useCallback(async (
    orderId: string,
    itemId: string,
    data: { received_qty: number; quality_grade: string },
  ) => {
    await txFetchData(`/api/v1/receiving/orders/${orderId}/items/${itemId}/inspect`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    // 乐观更新抽屉数据
    setDrawerOrder(prev => {
      if (!prev || prev.id !== orderId) return prev;
      return {
        ...prev,
        items: prev.items.map(item =>
          item.id === itemId
            ? { ...item, received_qty: data.received_qty, quality_grade: data.quality_grade as ReceivingItem['quality_grade'] }
            : item
        ),
      };
    });
  }, []);

  const handleComplete = useCallback(async (orderId: string) => {
    await txFetchData(`/api/v1/receiving/orders/${orderId}/complete`, { method: 'POST' });
    setSuccessIds(s => new Set([...s, orderId]));
    setReceivingOrders(orders =>
      orders.map(o => o.id === orderId ? { ...o, status: 'completed' } : o)
    );
    await fetchReceivingOrders();
  }, [fetchReceivingOrders]);

  const handleRejectAll = useCallback(async (orderId: string) => {
    await txFetchData(`/api/v1/receiving/orders/${orderId}/reject-all`, { method: 'POST' });
    setReceivingOrders(orders =>
      orders.map(o => o.id === orderId ? { ...o, status: 'rejected' } : o)
    );
    await fetchReceivingOrders();
  }, [fetchReceivingOrders]);

  // ── 调拨操作 ──
  const handleTransferAction = useCallback(async (
    orderId: string,
    action: 'approve' | 'ship' | 'receive' | 'cancel',
  ) => {
    await txFetchData(`/api/v1/transfers/${orderId}/${action}`, { method: 'POST' });
    // 乐观更新状态
    const nextStatus: Record<string, TransferOrder['status']> = {
      approve: 'approved',
      ship:    'shipped',
      receive: 'received',
      cancel:  'cancelled',
    };
    setTransferOrders(orders =>
      orders.map(o => o.id === orderId ? { ...o, status: nextStatus[action] } : o)
    );
    await fetchTransferOrders();
  }, [fetchTransferOrders]);

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: '8px 24px', borderRadius: 6, cursor: 'pointer', fontSize: 14, fontWeight: 600,
    border: 'none',
    background: active ? '#2196f3' : 'transparent',
    color: active ? '#fff' : '#888',
    transition: 'all 0.15s',
  });

  const selectStyle: React.CSSProperties = {
    padding: '6px 12px', borderRadius: 6, border: '1px solid #2a3a44',
    background: '#1a2a33', color: '#ccc', fontSize: 13, outline: 'none', cursor: 'pointer',
  };

  const inputStyle: React.CSSProperties = {
    padding: '6px 12px', borderRadius: 6, border: '1px solid #2a3a44',
    background: '#1a2a33', color: '#ccc', fontSize: 13, outline: 'none',
  };

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🚛 收货与调拨</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            供应链管理 · 收货验收 & 门店调拨
          </p>
        </div>
        <button
          onClick={() => activeTab === 'receiving' ? fetchReceivingOrders() : fetchTransferOrders()}
          style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13,
          }}
        >
          ↻ 刷新
        </button>
      </div>

      {/* Tab 切换 */}
      <div style={{
        display: 'flex', gap: 4, marginBottom: 24,
        background: '#1a2a33', padding: 4, borderRadius: 8, width: 'fit-content',
      }}>
        <button style={tabStyle(activeTab === 'receiving')} onClick={() => setActiveTab('receiving')}>
          📦 收货验收
        </button>
        <button style={tabStyle(activeTab === 'transfer')} onClick={() => setActiveTab('transfer')}>
          🔄 门店调拨
        </button>
      </div>

      {/* ── Tab 1：收货验收 ── */}
      {activeTab === 'receiving' && (
        <>
          {/* 筛选栏 */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <input
              placeholder="门店ID筛选"
              value={receivingStoreFilter}
              onChange={e => setReceivingStoreFilter(e.target.value)}
              style={inputStyle}
            />
            <select
              value={receivingStatusFilter}
              onChange={e => setReceivingStatusFilter(e.target.value)}
              style={selectStyle}
            >
              <option value="">全部状态</option>
              <option value="pending">待验收</option>
              <option value="inspecting">验收中</option>
              <option value="completed">已完成</option>
              <option value="rejected">已拒收</option>
            </select>
            <input
              type="date"
              value={receivingDateFilter}
              onChange={e => setReceivingDateFilter(e.target.value)}
              style={inputStyle}
            />
          </div>

          {/* 收货单列表 */}
          {receivingLoading ? (
            <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
          ) : receivingOrders.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: 60, color: '#888',
              background: '#1a2a33', borderRadius: 12,
            }}>
              暂无收货单
            </div>
          ) : (
            receivingOrders.map(order => (
              <ReceivingCard
                key={order.id}
                order={order}
                onOpenDrawer={setDrawerOrder}
                onStartInspect={handleStartInspect}
                successIds={successIds}
              />
            ))
          )}
        </>
      )}

      {/* ── Tab 2：门店调拨 ── */}
      {activeTab === 'transfer' && (
        <>
          {/* 筛选栏 */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <select
              value={transferPerspective}
              onChange={e => setTransferPerspective(e.target.value)}
              style={selectStyle}
            >
              <option value="all">全部调拨</option>
              <option value="sent">我发出的</option>
              <option value="received">我收到的</option>
            </select>
            <select
              value={transferStatusFilter}
              onChange={e => setTransferStatusFilter(e.target.value)}
              style={selectStyle}
            >
              <option value="">全部状态</option>
              <option value="draft">待审批</option>
              <option value="approved">已审批</option>
              <option value="shipped">发货中</option>
              <option value="received">已收货</option>
              <option value="cancelled">已取消</option>
            </select>
          </div>

          {/* 调拨单列表 */}
          {transferLoading ? (
            <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
          ) : transferOrders.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: 60, color: '#888',
              background: '#1a2a33', borderRadius: 12,
            }}>
              暂无调拨单
            </div>
          ) : (
            transferOrders.map(order => (
              <TransferCard
                key={order.id}
                order={order}
                onAction={handleTransferAction}
              />
            ))
          )}
        </>
      )}

      {/* 收货详情抽屉 */}
      {drawerOrder && (
        <ReceivingDrawer
          order={drawerOrder}
          onClose={() => setDrawerOrder(null)}
          onComplete={handleComplete}
          onRejectAll={handleRejectAll}
          onInspectItem={handleInspectItem}
        />
      )}
    </div>
  );
}
