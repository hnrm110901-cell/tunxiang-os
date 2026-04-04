/**
 * UrgePage — 服务员催菜/加菜核心工作页
 *
 * 功能：
 *  1. 顶部桌台选择器（大号，高48px，背景#1E2A3A）
 *  2. 展示所选桌台制作中的菜品列表（已等待时间 + 催菜按钮）
 *  3. 催菜理由快选（底部Sheet弹出）
 *  4. 催菜成功 → 绿色Toast 2秒消失
 *  5. 底部"加菜"大按钮 → 打开 AddDishSheet
 *
 * 设计规范：
 *  - 纯内联CSS，禁止Ant Design
 *  - 所有点击区域 ≥ 48×48px
 *  - TypeScript strict
 *  - X-Tenant-ID 通过 txFetch 统一注入
 *  - API失败降级 Toast，不阻断操作
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';
import { AddDishSheet } from '../components/AddDishSheet';

// ─── Design Tokens ───
const T = {
  bg: '#0B1A20',
  card: '#112228',
  cardAlt: '#1E2A3A',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  successLight: '#0F6E5622',
  warning: '#BA7517',
  danger: '#A32D2D',
  dangerLight: '#A32D2D22',
  text: '#e2e8f0',
  textSecondary: '#94a3b8',
  muted: '#64748b',
  white: '#ffffff',
} as const;

// ─── API 类型 ───

interface TableStatusItem {
  table_id: string;
  table_no: string;
  status: 'idle' | 'occupied' | 'reserved' | 'cleaning';
  order_id: string | null;
  seated_at: string | null;
  guest_count: number;
}

interface PreparingOrderItem {
  item_id: string;
  dish_id: string;
  dish_name: string;
  quantity: number;
  spec?: string;
  status: 'pending' | 'preparing' | 'done';
  created_at: string;
  urged?: boolean;
}

interface PreparingOrder {
  order_id: string;
  table_id: string;
  table_no: string;
  items: PreparingOrderItem[];
}

// ─── 工具函数 ───

function calcWaitMin(createdAt: string): number {
  return Math.floor((Date.now() - new Date(createdAt).getTime()) / 60000);
}

function waitColor(min: number): string {
  if (min >= 15) return T.danger;
  if (min >= 8) return T.warning;
  return T.accent;
}

// ─── 子组件：Toast ───

interface ToastProps {
  message: string;
  type: 'success' | 'error';
  visible: boolean;
}

function Toast({ message, type, visible }: ToastProps) {
  return (
    <div style={{
      position: 'fixed',
      top: 64,
      left: '50%',
      transform: `translateX(-50%) translateY(${visible ? '0' : '-80px'})`,
      transition: 'transform 280ms ease',
      background: type === 'success' ? T.success : T.danger,
      color: T.white,
      padding: '12px 24px',
      borderRadius: 12,
      fontSize: 16,
      fontWeight: 600,
      zIndex: 999,
      whiteSpace: 'nowrap',
      boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
      pointerEvents: 'none',
    }}>
      {type === 'success' ? '✓ ' : '✕ '}{message}
    </div>
  );
}

// ─── 子组件：桌台选择器 ───

interface TableSelectorProps {
  tables: TableStatusItem[];
  selectedId: string;
  onSelect: (tableId: string) => void;
}

function TableSelector({ tables, selectedId, onSelect }: TableSelectorProps) {
  const [open, setOpen] = useState(false);
  const occupied = tables.filter(t => t.status === 'occupied');
  const selected = tables.find(t => t.table_id === selectedId);

  return (
    <>
      {/* 触发按钮 */}
      <button
        onClick={() => setOpen(true)}
        style={{
          width: '100%',
          height: 48,
          background: T.cardAlt,
          border: `1px solid ${T.border}`,
          borderRadius: 12,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          cursor: 'pointer',
          color: selected ? T.white : T.muted,
          fontSize: 18,
          fontWeight: selected ? 600 : 400,
        }}
      >
        <span>{selected ? `${selected.table_no} 桌` : '请选择桌台'}</span>
        <span style={{
          fontSize: 16,
          color: T.muted,
          transition: 'transform 200ms',
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
        }}>▼</span>
      </button>

      {/* 选择弹层（底部Sheet） */}
      {open && (
        <>
          {/* 遮罩 */}
          <div
            onClick={() => setOpen(false)}
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(0,0,0,0.6)',
              zIndex: 100,
            }}
          />
          {/* 弹层 */}
          <div style={{
            position: 'fixed',
            bottom: 0, left: 0, right: 0,
            background: T.card,
            borderRadius: '16px 16px 0 0',
            zIndex: 101,
            maxHeight: '60vh',
            display: 'flex',
            flexDirection: 'column',
            animation: 'slideUp 300ms ease-out',
          }}>
            {/* 标题 */}
            <div style={{
              padding: '16px 20px 12px',
              borderBottom: `1px solid ${T.border}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <span style={{ fontSize: 18, fontWeight: 700, color: T.white }}>选择桌台</span>
              <button
                onClick={() => setOpen(false)}
                style={{
                  width: 36, height: 36,
                  background: 'transparent',
                  border: 'none',
                  color: T.muted,
                  fontSize: 20,
                  cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >✕</button>
            </div>

            {/* 桌台列表 */}
            <div style={{
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
              flex: 1,
              padding: '8px 0',
            }}>
              {occupied.length === 0 ? (
                <div style={{ padding: '32px 20px', textAlign: 'center', color: T.muted, fontSize: 16 }}>
                  暂无就餐中桌台
                </div>
              ) : (
                occupied.map(t => {
                  const seatedMin = t.seated_at ? Math.floor((Date.now() - new Date(t.seated_at).getTime()) / 60000) : 0;
                  const isSelected = t.table_id === selectedId;
                  return (
                    <button
                      key={t.table_id}
                      onClick={() => { onSelect(t.table_id); setOpen(false); }}
                      style={{
                        width: '100%',
                        minHeight: 56,
                        padding: '12px 20px',
                        background: isSelected ? `${T.accent}22` : 'transparent',
                        border: 'none',
                        borderBottom: `1px solid ${T.border}`,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        textAlign: 'left',
                      }}
                    >
                      <div>
                        <span style={{ fontSize: 18, fontWeight: 700, color: isSelected ? T.accent : T.white }}>
                          {t.table_no} 桌
                        </span>
                        <span style={{ fontSize: 16, color: T.muted, marginLeft: 8 }}>
                          {t.guest_count}人 · {seatedMin}分钟
                        </span>
                      </div>
                      {isSelected && (
                        <span style={{ color: T.accent, fontSize: 18 }}>✓</span>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}

// ─── 子组件：催菜理由Sheet ───

const URGE_REASONS = ['超时未出', '顾客催促', '特殊需求', '其他'];

interface UrgeReasonSheetProps {
  visible: boolean;
  dishName: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

function UrgeReasonSheet({ visible, dishName, onConfirm, onCancel }: UrgeReasonSheetProps) {
  const [selected, setSelected] = useState('顾客催促');

  if (!visible) return null;

  return (
    <>
      <div
        onClick={onCancel}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.6)',
          zIndex: 200,
        }}
      />
      <div style={{
        position: 'fixed',
        bottom: 0, left: 0, right: 0,
        background: T.card,
        borderRadius: '16px 16px 0 0',
        zIndex: 201,
        padding: '20px 20px 40px',
        animation: 'slideUp 300ms ease-out',
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: T.white, marginBottom: 4 }}>
          催菜理由
        </div>
        <div style={{ fontSize: 16, color: T.muted, marginBottom: 20 }}>
          {dishName}
        </div>

        {/* 理由选项 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
          {URGE_REASONS.map(r => (
            <button
              key={r}
              onClick={() => setSelected(r)}
              style={{
                minHeight: 52,
                borderRadius: 10,
                border: `1.5px solid ${selected === r ? T.accent : T.border}`,
                background: selected === r ? `${T.accent}22` : T.cardAlt,
                color: selected === r ? T.accent : T.text,
                fontSize: 16,
                fontWeight: selected === r ? 600 : 400,
                cursor: 'pointer',
                transition: 'all 200ms',
              }}
            >
              {r}
            </button>
          ))}
        </div>

        {/* 确认按钮 */}
        <button
          onClick={() => onConfirm(selected)}
          style={{
            width: '100%',
            height: 52,
            borderRadius: 12,
            background: T.accent,
            border: 'none',
            color: T.white,
            fontSize: 18,
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'transform 200ms, background 200ms',
          }}
          onPointerDown={e => (e.currentTarget.style.transform = 'scale(0.97)')}
          onPointerUp={e => (e.currentTarget.style.transform = 'scale(1)')}
          onPointerLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          确认催菜
        </button>
      </div>
    </>
  );
}

// ─── 主页面 ───

export function UrgePage() {
  const navigate = useNavigate();
  const storeId = (window as any).__STORE_ID__ || 'store_001';

  // 状态
  const [tables, setTables] = useState<TableStatusItem[]>([]);
  const [selectedTableId, setSelectedTableId] = useState<string>('');
  const [order, setOrder] = useState<PreparingOrder | null>(null);
  const [loadingTables, setLoadingTables] = useState(true);
  const [loadingOrder, setLoadingOrder] = useState(false);

  // Toast
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error'; visible: boolean }>({
    msg: '', type: 'success', visible: false,
  });
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 催菜理由Sheet
  const [urgeSheet, setUrgeSheet] = useState<{ visible: boolean; itemId: string; dishName: string }>({
    visible: false, itemId: '', dishName: '',
  });

  // 加菜弹层
  const [addDishVisible, setAddDishVisible] = useState(false);

  // 下拉刷新（轮询）
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 显示 Toast ──
  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ msg, type, visible: true });
    toastTimerRef.current = setTimeout(() => {
      setToast(prev => ({ ...prev, visible: false }));
    }, 2000);
  }, []);

  // ── 加载催单列表（规范路径：/api/v1/trade/kds/urge-list）──
  const loadTables = useCallback(async () => {
    try {
      const res = await txFetch<{ items: TableStatusItem[] }>(
        `/api/v1/trade/tables?store_id=${encodeURIComponent(storeId)}&status=occupied`
      );
      setTables(res.items ?? []);
    } catch {
      setTables([]);
    } finally {
      setLoadingTables(false);
    }
  }, [storeId]);

  // ── 加载选中桌台订单（制作中菜品）──
  const loadOrder = useCallback(async (tableId: string) => {
    const tbl = tables.find(t => t.table_id === tableId);
    if (!tbl?.order_id) {
      setOrder(null);
      return;
    }
    setLoadingOrder(true);
    try {
      const res = await txFetch<{ items: PreparingOrderItem[]; order_id: string }>(
        `/api/v1/trade/orders?table_id=${encodeURIComponent(tableId)}&status=preparing`
      );
      setOrder({
        order_id: res.order_id || tbl.order_id!,
        table_id: tableId,
        table_no: tbl.table_no,
        items: res.items ?? [],
      });
    } catch {
      setOrder(null);
    } finally {
      setLoadingOrder(false);
    }
  }, [tables]);

  // ── 初始化 + 轮询 ──
  useEffect(() => {
    loadTables();
    pollRef.current = setInterval(() => {
      loadTables();
    }, 30000); // 30秒轮询
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadTables]);

  // 切换桌台时加载订单
  useEffect(() => {
    if (selectedTableId) loadOrder(selectedTableId);
    else setOrder(null);
  }, [selectedTableId, loadOrder]);

  // 桌台数据更新后刷新当前订单
  useEffect(() => {
    if (selectedTableId && tables.length > 0) loadOrder(selectedTableId);
  }, [tables]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 手动下拉刷新 ──
  const handleRefresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    await loadTables();
    if (selectedTableId) await loadOrder(selectedTableId);
    setRefreshing(false);
  }, [refreshing, loadTables, loadOrder, selectedTableId]);

  // ── 打开催菜理由Sheet ──
  const openUrgeSheet = (itemId: string, dishName: string) => {
    setUrgeSheet({ visible: true, itemId, dishName });
  };

  // ── 确认催菜 ──
  const handleUrgeConfirm = async (reason: string) => {
    const { itemId } = urgeSheet;
    setUrgeSheet(prev => ({ ...prev, visible: false }));

    // 乐观更新
    setOrder(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map(it =>
          it.item_id === itemId ? { ...it, urged: true } : it
        ),
      };
    });

    try {
      if (order) {
        await txFetch(
          `/api/v1/trade/kds/orders/${encodeURIComponent(order.order_id)}/urge`,
          {
            method: 'POST',
            body: JSON.stringify({ dish_id: urgeSheet.itemId, reason }),
          }
        );
      }
      showToast('已通知厨房', 'success');
    } catch {
      showToast('通知失败，请重试', 'error');
      // 回滚乐观更新
      setOrder(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          items: prev.items.map(it =>
            it.item_id === itemId ? { ...it, urged: false } : it
          ),
        };
      });
    }
  };

  // ── 渲染 ──
  const preparingItems = order?.items.filter(it => it.status !== 'done') ?? [];
  const doneItems = order?.items.filter(it => it.status === 'done') ?? [];
  const selectedTable = tables.find(t => t.table_id === selectedTableId);

  return (
    <div style={{
      background: T.bg,
      minHeight: '100vh',
      paddingBottom: 88, // 底部加菜按钮高度 + 安全区
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
    }}>
      {/* CSS 动画 */}
      <style>{`
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>

      {/* Toast */}
      <Toast message={toast.msg} type={toast.type} visible={toast.visible} />

      {/* ── 顶部栏 ── */}
      <div style={{
        background: T.card,
        borderBottom: `1px solid ${T.border}`,
        padding: '12px 16px 16px',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        {/* 标题行 */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <button
            onClick={() => navigate(-1)}
            style={{
              width: 40, height: 40,
              background: 'transparent',
              border: 'none',
              color: T.text,
              fontSize: 20,
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginRight: 8,
            }}
          >
            ←
          </button>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: T.white, margin: 0, flex: 1 }}>
            催菜
          </h1>
          {/* 刷新按钮 */}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            style={{
              width: 40, height: 40,
              background: 'transparent',
              border: 'none',
              color: refreshing ? T.muted : T.text,
              fontSize: 18,
              cursor: refreshing ? 'default' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              animation: refreshing ? 'spin 1s linear infinite' : 'none',
            }}
          >
            ↻
          </button>
        </div>

        {/* 桌台选择器 */}
        {loadingTables ? (
          <div style={{
            height: 48, background: T.cardAlt, borderRadius: 12,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: T.muted, fontSize: 16,
          }}>
            加载桌台中...
          </div>
        ) : (
          <TableSelector
            tables={tables}
            selectedId={selectedTableId}
            onSelect={setSelectedTableId}
          />
        )}
      </div>

      {/* ── 内容区 ── */}
      <div style={{ padding: '16px 16px 0' }}>

        {/* 未选桌台提示 */}
        {!selectedTableId && (
          <div style={{
            textAlign: 'center',
            padding: '60px 20px',
            color: T.muted,
            fontSize: 16,
          }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🍽</div>
            <div>请先选择桌台</div>
            <div style={{ fontSize: 16, marginTop: 6, color: T.muted }}>
              选中桌台后即可查看制作中菜品并催菜
            </div>
          </div>
        )}

        {/* 加载中 */}
        {selectedTableId && loadingOrder && (
          <div style={{ textAlign: 'center', padding: '40px 20px', color: T.muted, fontSize: 16 }}>
            加载中...
          </div>
        )}

        {/* 无制作中菜品 */}
        {selectedTableId && !loadingOrder && preparingItems.length === 0 && order !== null && (
          <div style={{
            textAlign: 'center',
            padding: '48px 20px',
            color: T.muted,
            fontSize: 16,
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
            <div style={{ fontWeight: 600, color: T.success }}>菜品已全部上齐</div>
            {doneItems.length > 0 && (
              <div style={{ marginTop: 6 }}>共 {doneItems.length} 道菜</div>
            )}
          </div>
        )}

        {/* 桌台 + 订单信息头 */}
        {selectedTableId && !loadingOrder && order && preparingItems.length > 0 && (
          <>
            {/* 桌台信息条 */}
            <div style={{
              background: T.cardAlt,
              borderRadius: 10,
              padding: '10px 16px',
              marginBottom: 12,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ fontSize: 16, color: T.text }}>
                <span style={{ fontWeight: 700, color: T.white }}>{selectedTable?.table_no} 桌</span>
                <span style={{ color: T.muted, marginLeft: 8 }}>
                  {selectedTable?.guest_count}人
                </span>
              </div>
              <div style={{ fontSize: 16, color: T.muted }}>
                就餐{selectedTable?.seated_at
                  ? Math.floor((Date.now() - new Date(selectedTable.seated_at).getTime()) / 60000)
                  : '—'}分钟
              </div>
            </div>

            {/* 制作中菜品列表 */}
            <div style={{
              background: T.card,
              borderRadius: 12,
              border: `1px solid ${T.border}`,
              overflow: 'hidden',
              marginBottom: 12,
            }}>
              {/* 区块标题 */}
              <div style={{
                padding: '12px 16px',
                borderBottom: `1px solid ${T.border}`,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: T.accent,
                  display: 'inline-block',
                  boxShadow: `0 0 6px ${T.accent}`,
                }} />
                <span style={{ fontSize: 16, fontWeight: 600, color: T.text }}>
                  制作中 ({preparingItems.length})
                </span>
              </div>

              {preparingItems.map((item, idx) => {
                const waitMin = calcWaitMin(item.created_at);
                const wColor = waitColor(waitMin);
                const isLast = idx === preparingItems.length - 1;

                return (
                  <div
                    key={item.item_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      padding: '14px 16px',
                      borderBottom: isLast ? 'none' : `1px solid ${T.border}`,
                      minHeight: 64,
                      gap: 12,
                    }}
                  >
                    {/* 菜品信息 */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 18,
                        fontWeight: 600,
                        color: T.white,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {item.dish_name}
                        <span style={{ fontWeight: 400, color: T.muted, marginLeft: 4 }}>
                          ×{item.quantity}
                        </span>
                        {item.spec && (
                          <span style={{ fontWeight: 400, color: T.muted, marginLeft: 4, fontSize: 16 }}>
                            ({item.spec})
                          </span>
                        )}
                      </div>
                      {/* 等待时间 */}
                      <div style={{
                        fontSize: 16,
                        color: wColor,
                        marginTop: 2,
                        fontWeight: waitMin >= 15 ? 700 : 400,
                      }}>
                        {waitMin >= 15 && '⚠ '}等待 {waitMin} 分钟
                        {item.status === 'pending' && (
                          <span style={{ color: T.muted, fontWeight: 400, marginLeft: 8 }}>待制作</span>
                        )}
                      </div>
                    </div>

                    {/* 催菜按钮 */}
                    <button
                      onClick={() => !item.urged && openUrgeSheet(item.item_id, item.dish_name)}
                      disabled={!!item.urged}
                      style={{
                        minWidth: 68,
                        height: 48,
                        borderRadius: 10,
                        background: item.urged ? `${T.muted}22` : T.accent,
                        border: 'none',
                        color: item.urged ? T.muted : T.white,
                        fontSize: 16,
                        fontWeight: 700,
                        cursor: item.urged ? 'default' : 'pointer',
                        flexShrink: 0,
                        transition: 'transform 200ms, background 200ms',
                      }}
                      onPointerDown={e => { if (!item.urged) e.currentTarget.style.transform = 'scale(0.95)'; }}
                      onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; }}
                      onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; }}
                    >
                      {item.urged ? '已催' : '催菜'}
                    </button>
                  </div>
                );
              })}
            </div>

            {/* 已出品菜品（折叠摘要） */}
            {doneItems.length > 0 && (
              <div style={{
                background: T.card,
                borderRadius: 12,
                border: `1px solid ${T.border}`,
                padding: '12px 16px',
                marginBottom: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: T.success,
                  display: 'inline-block',
                }} />
                <span style={{ fontSize: 16, color: T.muted }}>
                  已出品 {doneItems.length} 道：
                  {doneItems.slice(0, 3).map(d => d.dish_name).join('、')}
                  {doneItems.length > 3 ? ` 等` : ''}
                </span>
              </div>
            )}
          </>
        )}

        {/* 无订单（桌台空闲/无有效订单）*/}
        {selectedTableId && !loadingOrder && order === null && (
          <div style={{
            textAlign: 'center',
            padding: '48px 20px',
            color: T.muted,
            fontSize: 16,
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>📋</div>
            <div>该桌台暂无进行中的订单</div>
          </div>
        )}
      </div>

      {/* ── 底部固定：加菜大按钮 ── */}
      {selectedTableId && order && (
        <div style={{
          position: 'fixed',
          bottom: 0, left: 0, right: 0,
          padding: '12px 16px',
          paddingBottom: 'calc(12px + env(safe-area-inset-bottom, 0px))',
          background: T.bg,
          borderTop: `1px solid ${T.border}`,
          zIndex: 20,
        }}>
          <button
            onClick={() => setAddDishVisible(true)}
            style={{
              width: '100%',
              height: 56,
              borderRadius: 14,
              background: T.accent,
              border: 'none',
              color: T.white,
              fontSize: 18,
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              boxShadow: `0 4px 16px ${T.accent}66`,
              transition: 'transform 200ms, background 200ms',
            }}
            onPointerDown={e => { e.currentTarget.style.transform = 'scale(0.97)'; e.currentTarget.style.background = T.accentActive; }}
            onPointerUp={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.background = T.accent; }}
            onPointerLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.background = T.accent; }}
          >
            <span style={{ fontSize: 22, lineHeight: 1 }}>+</span>
            加菜
          </button>
        </div>
      )}

      {/* ── 催菜理由 Sheet ── */}
      <UrgeReasonSheet
        visible={urgeSheet.visible}
        dishName={urgeSheet.dishName}
        onConfirm={handleUrgeConfirm}
        onCancel={() => setUrgeSheet(prev => ({ ...prev, visible: false }))}
      />

      {/* ── 加菜弹层 ── */}
      {order && (
        <AddDishSheet
          visible={addDishVisible}
          onClose={() => setAddDishVisible(false)}
          orderId={order.order_id}
          storeId={storeId}
          onSuccess={() => {
            showToast('加菜成功，已通知厨房', 'success');
            loadOrder(selectedTableId);
          }}
        />
      )}
    </div>
  );
}
