/**
 * 25个操作面板 — POS大屏横向工具栏
 * 三个Tab切换：基础操作(10) | 高级操作(10) | 财务操作(5)
 * 每个按钮 72px 正方形，深色主题，触控优化
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import {
  preBill, fireToKitchen, markServed, pauseItem, overridePrice,
  giftOrder, returnOrder, rushOrder, modifyTableOpen, transferItem,
  transferTable, closeTable, verifyOrder, printReceipt, verifyMember,
  kitchenMessage, transferPayment, mergeOrders, markSoldOut, setDishLimit,
  changeWaiter, fetchTableStatus,
} from '../api/posOpsApi';

/* ─── 样式常量 ─── */
const C = {
  bg: '#0B1A20',
  panel: '#0D2229',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  green: '#0F6E56',
  blue: '#185FA5',
  yellow: '#BA7517',
  danger: '#A32D2D',
  purple: '#722ed1',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
};

/* ─── 操作定义 ─── */
interface ActionDef {
  key: string;
  label: string;
  icon: string;
  color: string;
  needsOrder?: boolean;   // 需要有活跃订单
  confirm?: string;       // 二次确认文案
}

const BASIC_ACTIONS: ActionDef[] = [
  { key: 'add-item', label: '加单', icon: '＋', color: C.accent },
  { key: 'settle', label: '结算', icon: '￥', color: C.green, needsOrder: true },
  { key: 'pre-bill', label: '埋单', icon: '📋', color: C.blue, needsOrder: true },
  { key: 'fire', label: '起菜', icon: '🔥', color: '#E25822', needsOrder: true },
  { key: 'served', label: '上菜', icon: '🍽', color: C.green, needsOrder: true },
  { key: 'pause', label: '停菜', icon: '⏸', color: C.yellow, needsOrder: true, confirm: '确认暂停当前菜品制作？' },
  { key: 'price', label: '变价', icon: '✏', color: C.purple, needsOrder: true },
  { key: 'weigh', label: '称重', icon: '⚖', color: C.blue, needsOrder: true },
  { key: 'gift', label: '赠单', icon: '🎁', color: '#D4A017', needsOrder: true, confirm: '确认赠送？赠送需主管授权' },
  { key: 'return', label: '退单', icon: '↩', color: C.danger, needsOrder: true, confirm: '确认退单？退单需主管授权' },
];

const ADVANCED_ACTIONS: ActionDef[] = [
  { key: 'rush', label: '催单', icon: '⏰', color: '#E25822', needsOrder: true },
  { key: 'modify-open', label: '修改开台', icon: '👥', color: C.blue, needsOrder: true },
  { key: 'transfer-item', label: '单品转台', icon: '➡', color: C.purple, needsOrder: true },
  { key: 'transfer-table', label: '换台', icon: '🔄', color: C.blue, needsOrder: true },
  { key: 'close-table', label: '关台', icon: '✕', color: C.danger, confirm: '确认关台？将清空该桌所有数据' },
  { key: 'verify', label: '核对', icon: '✓', color: C.green, needsOrder: true },
  { key: 'print', label: '打印', icon: '🖨', color: C.muted, needsOrder: true },
  { key: 'member', label: '验会员', icon: '👤', color: '#13c2c2' },
  { key: 'kitchen-msg', label: '后厨通知', icon: '📢', color: C.yellow },
  { key: 'transfer-pay', label: '转账', icon: '💳', color: C.purple, needsOrder: true },
];

const FINANCE_ACTIONS: ActionDef[] = [
  { key: 'merge', label: '并账', icon: '🔗', color: C.blue },
  { key: 'sold-out', label: '沽清', icon: '🚫', color: C.danger },
  { key: 'limit', label: '限量', icon: '📊', color: C.yellow },
  { key: 'change-waiter', label: '改服务员', icon: '🔀', color: C.purple, needsOrder: true },
  { key: 'refresh', label: '刷新', icon: '↻', color: C.green },
];

type TabKey = 'basic' | 'advanced' | 'finance';
const TABS: { key: TabKey; label: string; actions: ActionDef[] }[] = [
  { key: 'basic', label: '基础操作', actions: BASIC_ACTIONS },
  { key: 'advanced', label: '高级操作', actions: ADVANCED_ACTIONS },
  { key: 'finance', label: '财务操作', actions: FINANCE_ACTIONS },
];

/* ─── 弹层 ─── */
interface ModalState {
  type: string;
  title: string;
  content?: string;
  onConfirm?: () => void;
  inputLabel?: string;
  inputValue?: string;
}

/* ─── 组件 ─── */
interface OrderActionPanelProps {
  /** 当前选中的桌号（从 TableMapPage 传入） */
  tableNo?: string;
  /** 当前选中桌的 orderId */
  orderId?: string;
  /** 面板关闭回调 */
  onClose?: () => void;
  /** 操作完成后刷新回调 */
  onRefresh?: () => void;
}

export function OrderActionPanel({ tableNo, orderId, onClose, onRefresh }: OrderActionPanelProps) {
  const navigate = useNavigate();
  const store = useOrderStore();
  const [activeTab, setActiveTab] = useState<TabKey>('basic');
  const [loading, setLoading] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const activeOrderId = orderId || store.orderId;
  const activeTableNo = tableNo || store.tableNo;

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2000);
  }, []);

  const showConfirm = useCallback((title: string, content: string, onConfirm: () => void) => {
    setModal({ type: 'confirm', title, content, onConfirm });
  }, []);

  const handleAction = useCallback(async (action: ActionDef) => {
    // 需要订单但没有
    if (action.needsOrder && !activeOrderId) {
      showToast('请先选择桌台或订单');
      return;
    }

    // 需要二次确认
    if (action.confirm) {
      showConfirm(action.label, action.confirm, () => executeAction(action.key));
      return;
    }

    await executeAction(action.key);
  }, [activeOrderId, activeTableNo]);

  const executeAction = async (key: string) => {
    setModal(null);
    setLoading(key);

    try {
      switch (key) {
        case 'add-item':
          if (activeTableNo) {
            navigate(`/cashier/${activeTableNo}`);
          } else {
            navigate('/tables');
          }
          break;

        case 'settle':
          if (activeOrderId) navigate(`/settle/${activeOrderId}`);
          break;

        case 'pre-bill':
          if (activeOrderId) {
            const result = await preBill(activeOrderId);
            showToast(`埋单成功 #${result.pre_bill_no}，金额 ¥${(result.amount_fen / 100).toFixed(2)}`);
          }
          break;

        case 'fire':
          if (activeOrderId) {
            const result = await fireToKitchen(activeOrderId);
            showToast(`已起菜 ${result.fired_count} 道`);
          }
          break;

        case 'served':
          // 简化处理：标记全部已上
          if (activeOrderId) {
            showToast('请在订单详情中逐道标记上菜');
            navigate(`/order/${activeOrderId}`);
          }
          break;

        case 'pause':
          if (activeOrderId) {
            showToast('请在订单详情中选择要停菜的菜品');
            navigate(`/order/${activeOrderId}`);
          }
          break;

        case 'price':
          if (activeOrderId) {
            showToast('请在订单详情中点击菜品修改价格');
            navigate(`/order/${activeOrderId}`);
          }
          break;

        case 'weigh':
          showToast('称重模式已开启，请将商品放置于电子秤');
          break;

        case 'gift':
          if (activeOrderId) {
            const result = await giftOrder(activeOrderId, undefined, '前台赠送');
            showToast(`赠单完成，赠送金额 ¥${(result.gifted_amount_fen / 100).toFixed(2)}`);
            onRefresh?.();
          }
          break;

        case 'return':
          if (activeOrderId) {
            const result = await returnOrder(activeOrderId, undefined, '前台退单');
            showToast(`退单完成，退回金额 ¥${(result.returned_amount_fen / 100).toFixed(2)}`);
            onRefresh?.();
          }
          break;

        case 'rush':
          if (activeOrderId) {
            await rushOrder(activeOrderId);
            showToast('催单已发送到后厨');
          }
          break;

        case 'modify-open':
          if (activeOrderId) {
            setModal({
              type: 'input',
              title: '修改开台信息',
              inputLabel: '用餐人数',
              inputValue: '',
              onConfirm: async () => {
                const val = modal?.inputValue;
                if (val && activeOrderId) {
                  await modifyTableOpen(activeOrderId, parseInt(val, 10));
                  showToast('开台信息已更新');
                  onRefresh?.();
                }
                setModal(null);
              },
            });
            return; // 不关闭 loading
          }
          break;

        case 'transfer-item':
          showToast('请在订单详情中选择要转台的菜品');
          if (activeOrderId) navigate(`/order/${activeOrderId}`);
          break;

        case 'transfer-table':
          navigate('/tables');
          break;

        case 'close-table':
          if (activeTableNo) {
            await closeTable(activeTableNo);
            showToast(`${activeTableNo} 桌已关台`);
            onRefresh?.();
            onClose?.();
          }
          break;

        case 'verify':
          if (activeOrderId) {
            const data = await verifyOrder(activeOrderId);
            setModal({
              type: 'verify',
              title: `核对 · ${activeTableNo || ''}`,
              content: `共 ${data.items.length} 道菜，合计 ¥${(data.total_fen / 100).toFixed(2)}，优惠 ¥${(data.discount_fen / 100).toFixed(2)}，应付 ¥${(data.final_fen / 100).toFixed(2)}`,
            });
          }
          break;

        case 'print':
          if (activeOrderId) {
            await printReceipt(activeOrderId);
            showToast('小票已发送打印');
          }
          break;

        case 'member':
          setModal({
            type: 'input',
            title: '验证会员',
            inputLabel: '手机号或会员码',
            inputValue: '',
            onConfirm: async () => {
              const q = modal?.inputValue;
              if (q) {
                const member = await verifyMember(q);
                setModal({
                  type: 'verify',
                  title: '会员信息',
                  content: `${member.name} | ${member.level}\n手机: ${member.phone}\n余额: ¥${(member.balance_fen / 100).toFixed(2)} | 积分: ${member.points}`,
                });
              }
            },
          });
          return;

        case 'kitchen-msg':
          setModal({
            type: 'input',
            title: '后厨通知',
            inputLabel: '通知内容',
            inputValue: '',
            onConfirm: async () => {
              const msg = modal?.inputValue;
              if (msg) {
                await kitchenMessage('', msg);
                showToast('通知已发送到后厨');
                setModal(null);
              }
            },
          });
          return;

        case 'transfer-pay':
          showToast('转账功能请在结算页操作');
          if (activeOrderId) navigate(`/settle/${activeOrderId}`);
          break;

        case 'merge':
          showToast('并账功能：请在桌台页长按选择多桌');
          navigate('/tables');
          break;

        case 'sold-out':
          showToast('沽清：请在菜品管理中操作');
          break;

        case 'limit':
          showToast('限量：请在菜品管理中操作');
          break;

        case 'change-waiter':
          setModal({
            type: 'input',
            title: '更换服务员',
            inputLabel: '服务员工号',
            inputValue: '',
            onConfirm: async () => {
              const wid = modal?.inputValue;
              if (wid && activeOrderId) {
                await changeWaiter(activeOrderId, wid);
                showToast('服务员已更换');
                setModal(null);
                onRefresh?.();
              }
            },
          });
          return;

        case 'refresh':
          onRefresh?.();
          showToast('已刷新');
          break;

        default:
          showToast(`${key} 功能开发中`);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '操作失败';
      showToast(`错误: ${msg}`);
    } finally {
      setLoading(null);
    }
  };

  const currentActions = TABS.find(t => t.key === activeTab)?.actions || [];

  return (
    <div style={{
      background: C.panel,
      borderTop: `1px solid ${C.border}`,
      padding: '12px 16px 16px',
      position: 'relative',
    }}>
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 60, left: '50%', transform: 'translateX(-50%)',
          background: '#1A3A48', color: C.white, padding: '12px 24px',
          borderRadius: 12, fontSize: 16, fontWeight: 600, zIndex: 9999,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
          border: `1px solid ${C.border}`,
        }}>
          {toast}
        </div>
      )}

      {/* Modal */}
      {modal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9998,
        }}
          onClick={() => setModal(null)}
        >
          <div
            style={{
              background: C.card, borderRadius: 16, padding: 24,
              minWidth: 360, maxWidth: 480, border: `1px solid ${C.border}`,
            }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: 20, color: C.white, fontWeight: 700 }}>
              {modal.title}
            </h3>

            {modal.type === 'confirm' && (
              <>
                <p style={{ fontSize: 16, color: C.text, lineHeight: 1.6, margin: '0 0 20px' }}>
                  {modal.content}
                </p>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button
                    onClick={() => setModal(null)}
                    style={{
                      flex: 1, minHeight: 56, borderRadius: 12,
                      background: C.card, border: `1px solid ${C.border}`,
                      color: C.text, fontSize: 18, cursor: 'pointer',
                    }}
                  >
                    取消
                  </button>
                  <button
                    onClick={() => modal.onConfirm?.()}
                    style={{
                      flex: 1, minHeight: 56, borderRadius: 12,
                      background: C.accent, color: C.white, border: 'none',
                      fontSize: 18, fontWeight: 700, cursor: 'pointer',
                    }}
                  >
                    确认
                  </button>
                </div>
              </>
            )}

            {modal.type === 'input' && (
              <>
                <label style={{ fontSize: 16, color: C.muted, display: 'block', marginBottom: 8 }}>
                  {modal.inputLabel}
                </label>
                <input
                  autoFocus
                  value={modal.inputValue || ''}
                  onChange={e => setModal(prev => prev ? { ...prev, inputValue: e.target.value } : null)}
                  onKeyDown={e => e.key === 'Enter' && modal.onConfirm?.()}
                  style={{
                    width: '100%', minHeight: 56, padding: '0 16px',
                    background: C.bg, border: `1px solid ${C.border}`,
                    borderRadius: 12, color: C.white, fontSize: 20,
                    outline: 'none', boxSizing: 'border-box',
                  }}
                />
                <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
                  <button
                    onClick={() => setModal(null)}
                    style={{
                      flex: 1, minHeight: 56, borderRadius: 12,
                      background: C.card, border: `1px solid ${C.border}`,
                      color: C.text, fontSize: 18, cursor: 'pointer',
                    }}
                  >
                    取消
                  </button>
                  <button
                    onClick={() => modal.onConfirm?.()}
                    style={{
                      flex: 1, minHeight: 56, borderRadius: 12,
                      background: C.accent, color: C.white, border: 'none',
                      fontSize: 18, fontWeight: 700, cursor: 'pointer',
                    }}
                  >
                    确认
                  </button>
                </div>
              </>
            )}

            {modal.type === 'verify' && (
              <>
                <pre style={{
                  fontSize: 16, color: C.text, lineHeight: 1.8, margin: '0 0 20px',
                  whiteSpace: 'pre-wrap', fontFamily: 'inherit',
                }}>
                  {modal.content}
                </pre>
                <button
                  onClick={() => setModal(null)}
                  style={{
                    width: '100%', minHeight: 56, borderRadius: 12,
                    background: C.accent, color: C.white, border: 'none',
                    fontSize: 18, fontWeight: 700, cursor: 'pointer',
                  }}
                >
                  关闭
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Tab 切换 */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 12, borderRadius: 12, overflow: 'hidden' }}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              flex: 1, minHeight: 48, border: 'none',
              background: activeTab === tab.key ? C.accent : C.card,
              color: activeTab === tab.key ? C.white : C.muted,
              fontSize: 16, fontWeight: activeTab === tab.key ? 700 : 400,
              cursor: 'pointer',
              transition: 'background 200ms ease',
            }}
          >
            {tab.label}
            <span style={{ fontSize: 16, marginLeft: 4, opacity: 0.6 }}>
              ({tab.actions.length})
            </span>
          </button>
        ))}
      </div>

      {/* 操作按钮网格 */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 12,
        overflowX: 'auto', WebkitOverflowScrolling: 'touch',
      }}>
        {currentActions.map(action => {
          const isLoading = loading === action.key;
          const isDisabled = action.needsOrder && !activeOrderId;

          return (
            <button
              key={action.key}
              onClick={() => !isLoading && !isDisabled && handleAction(action)}
              disabled={isDisabled || isLoading}
              style={{
                width: 72, height: 72,
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                gap: 4,
                background: isLoading ? `${action.color}33` : C.card,
                border: `1px solid ${isDisabled ? C.border : action.color}44`,
                borderRadius: 12,
                color: isDisabled ? C.muted : C.white,
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                opacity: isDisabled ? 0.4 : 1,
                transition: 'transform 200ms ease, background 200ms ease',
                flexShrink: 0,
              }}
              onPointerDown={e => {
                if (!isDisabled) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
              }}
              onPointerUp={e => {
                (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
              }}
              onPointerLeave={e => {
                (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
              }}
            >
              <span style={{ fontSize: 22, lineHeight: 1 }}>{action.icon}</span>
              <span style={{ fontSize: 16, fontWeight: 600, lineHeight: 1 }}>
                {isLoading ? '...' : action.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* 当前桌台信息条 */}
      {(activeTableNo || activeOrderId) && (
        <div style={{
          marginTop: 12, padding: '8px 12px',
          background: `${C.accent}11`, borderRadius: 8,
          fontSize: 16, color: C.muted,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>
            {activeTableNo && <span>桌号: <span style={{ color: C.accent, fontWeight: 700 }}>{activeTableNo}</span></span>}
            {activeOrderId && <span style={{ marginLeft: 12 }}>订单: <span style={{ color: C.text }}>{activeOrderId.slice(0, 8)}...</span></span>}
          </span>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                minHeight: 48, minWidth: 48, padding: '8px 16px',
                background: 'transparent', border: `1px solid ${C.border}`,
                borderRadius: 8, color: C.muted, fontSize: 16, cursor: 'pointer',
              }}
            >
              收起
            </button>
          )}
        </div>
      )}
    </div>
  );
}
