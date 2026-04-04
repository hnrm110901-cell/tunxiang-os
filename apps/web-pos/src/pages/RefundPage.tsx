/**
 * 退款页面
 * 搜索已完成订单 → 选择退款类型(全额/部分) → 填写原因 → 店长授权(>100元) → 确认退款 → 打印退款小票
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getOrder, processRefund, printReceipt as apiPrintReceipt } from '../api/tradeApi';
import { printReceipt as bridgePrint } from '../bridge/TXBridge';

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const REFUND_REASONS = [
  { key: 'quality', label: '菜品质量问题' },
  { key: 'service', label: '服务问题' },
  { key: 'dissatisfied', label: '客户不满' },
  { key: 'order_error', label: '下单错误' },
  { key: 'other', label: '其他' },
];

const MANAGER_AUTH_THRESHOLD_FEN = 10000; // 100 元

// ─── 类型 ─────────────────────────────────────────────────────────────────────

interface OrderItem {
  item_id: string;
  dish_name: string;
  quantity: number;
  unit_price_fen: number;
  subtotal_fen: number;
}

interface OrderDetail {
  order_id: string;
  order_no: string;
  table_no: string;
  status: string;
  payment_id: string;
  payment_method: string;
  total_fen: number;
  discount_fen: number;
  final_fen: number;
  items: OrderItem[];
  settled_at: string;
}

type Step = 'search' | 'select' | 'reason' | 'confirm' | 'done';

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function RefundPage() {
  const navigate = useNavigate();

  // Step state
  const [step, setStep] = useState<Step>('search');

  // Search
  const [searchInput, setSearchInput] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  // Order
  const [order, setOrder] = useState<OrderDetail | null>(null);

  // Refund type
  const [refundType, setRefundType] = useState<'full' | 'partial'>('full');
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set());
  const [customAmountYuan, setCustomAmountYuan] = useState('');

  // Reason
  const [selectedReason, setSelectedReason] = useState('');
  const [notes, setNotes] = useState('');

  // Auth
  const [managerPin, setManagerPin] = useState('');
  const [authError, setAuthError] = useState('');

  // Submit
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [refundNo, setRefundNo] = useState('');
  const [printing, setPrinting] = useState(false);

  // ── 计算退款金额 ──

  const calcRefundAmountFen = (): number => {
    if (!order) return 0;
    if (refundType === 'full') return order.final_fen;

    // Custom amount takes priority if entered
    const customYuan = parseFloat(customAmountYuan);
    if (!isNaN(customYuan) && customYuan > 0) {
      return Math.round(customYuan * 100);
    }

    // Otherwise sum selected items
    if (selectedItems.size > 0) {
      return order.items
        .filter((it) => selectedItems.has(it.item_id))
        .reduce((sum, it) => sum + (it.subtotal_fen || it.unit_price_fen * it.quantity), 0);
    }

    return 0;
  };

  const refundAmountFen = calcRefundAmountFen();
  const needsManagerAuth = refundAmountFen > MANAGER_AUTH_THRESHOLD_FEN;

  // ── 搜索订单 ──

  const handleSearch = async () => {
    const input = searchInput.trim();
    if (!input) return;
    setSearchError('');
    setSearching(true);

    try {
      const result = await getOrder(input);
      if (!result) {
        setSearchError('未找到该订单，请检查订单号');
        return;
      }

      const items = Array.isArray(result.items)
        ? (result.items as Array<Record<string, unknown>>).map((it) => ({
            item_id: String(it.item_id ?? ''),
            dish_name: String(it.dish_name ?? it.name ?? ''),
            quantity: Number(it.quantity ?? 1),
            unit_price_fen: Number(it.unit_price_fen ?? 0),
            subtotal_fen: Number(it.subtotal_fen ?? Number(it.unit_price_fen ?? 0) * Number(it.quantity ?? 1)),
          }))
        : [];

      const totalFen = Number(result.total_amount_fen ?? result.total_fen ?? 0);
      const discountFen = Number(result.discount_amount_fen ?? result.discount_fen ?? 0);

      setOrder({
        order_id: String(result.order_id ?? input),
        order_no: String(result.order_no ?? input),
        table_no: String(result.table_no ?? '--'),
        status: String(result.status ?? ''),
        payment_id: String(result.payment_id ?? ''),
        payment_method: String(result.payment_method ?? '--'),
        total_fen: totalFen,
        discount_fen: discountFen,
        final_fen: Number(result.final_amount_fen ?? totalFen - discountFen),
        items,
        settled_at: String(result.settled_at ?? '--'),
      });
      setStep('select');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '查询失败，请稍后重试';
      setSearchError(message);
    } finally {
      setSearching(false);
    }
  };

  // ── 切换选中菜品 ──

  const toggleItem = (itemId: string) => {
    setSelectedItems((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
    setCustomAmountYuan('');
  };

  // ── 提交退款 ──

  const handleSubmit = async () => {
    if (!order) return;
    if (needsManagerAuth && !managerPin.trim()) {
      setAuthError('请输入店长授权码');
      return;
    }

    setSubmitting(true);
    setSubmitError('');

    try {
      const reasonLabel = REFUND_REASONS.find((r) => r.key === selectedReason)?.label ?? selectedReason;
      const fullReason = notes ? `${reasonLabel}: ${notes}` : reasonLabel;

      const result = await processRefund(order.order_id, order.payment_id, refundAmountFen, fullReason);
      setRefundNo(result.refund_no);
      setStep('done');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '退款失败，请稍后重试';
      setSubmitError(message);
    } finally {
      setSubmitting(false);
    }
  };

  // ── 打印退款小票 ──

  const handlePrintRefund = async () => {
    if (!order || printing) return;
    setPrinting(true);
    try {
      const { content_base64 } = await apiPrintReceipt(order.order_id);
      await bridgePrint(content_base64);
    } catch (err: unknown) {
      alert(`打印失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setPrinting(false);
    }
  };

  // ── 步骤可否前进 ──

  const canProceedFromSelect = refundType === 'full' || refundAmountFen > 0;
  const canProceedFromReason = !!selectedReason;

  // ── 渲染 ──

  const STEP_LABELS: { key: Step; label: string }[] = [
    { key: 'search', label: '查找订单' },
    { key: 'select', label: '退款类型' },
    { key: 'reason', label: '退款原因' },
    { key: 'confirm', label: '确认退款' },
    { key: 'done', label: '完成' },
  ];

  const stepIndex = (s: Step) => STEP_LABELS.findIndex((l) => l.key === s);

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 步骤指示器 */}
      <div style={{ width: 200, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <h3 style={{ margin: '0 0 20px', fontSize: 20 }}>退款</h3>
        {STEP_LABELS.map((s, i) => {
          const isCurrent = s.key === step;
          const isPast = stepIndex(step) > i;
          return (
            <div key={s.key} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
              borderRadius: 8, fontSize: 16,
              background: isCurrent ? '#1A3A48' : 'transparent',
              color: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#555',
              fontWeight: isCurrent ? 'bold' : 'normal',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: isCurrent ? '#FF6B2C' : isPast ? '#0F6E56' : '#333',
                color: '#fff', fontSize: 16, fontWeight: 'bold', flexShrink: 0,
              }}>
                {isPast ? '\u2713' : i + 1}
              </div>
              {s.label}
            </div>
          );
        })}
        <div style={{ marginTop: 'auto' }}>
          <button
            onClick={() => navigate(-1)}
            style={{ width: '100%', padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 16, cursor: 'pointer', minHeight: 56 }}
          >
            返回
          </button>
        </div>
      </div>

      {/* 右侧 — 主区域 */}
      <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>

        {/* ════ Step 1: 搜索订单 ════ */}
        {step === 'search' && (
          <div style={{ maxWidth: 600, margin: '0 auto', width: '100%' }}>
            <h2 style={{ fontSize: 24, marginBottom: 24 }}>查找已完成订单</h2>
            <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
              <input
                type="text"
                placeholder="输入订单号或扫码..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                autoFocus
                style={{
                  flex: 1, padding: 16, fontSize: 20, border: '2px solid #333',
                  borderRadius: 12, background: '#112228', color: '#fff',
                  outline: 'none', boxSizing: 'border-box',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
              />
              <button
                onClick={handleSearch}
                disabled={searching}
                style={{
                  padding: '16px 32px', border: 'none',
                  borderRadius: 12, color: '#fff', fontSize: 18,
                  minHeight: 56, fontWeight: 'bold', transition: 'transform 200ms ease',
                  background: searching ? '#444' : '#FF6B2C',
                  cursor: searching ? 'not-allowed' : 'pointer',
                }}
                onPointerDown={(e) => { if (!searching) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {searching ? '查询中...' : '查询'}
              </button>
            </div>
            {searchError && (
              <div style={{ color: '#A32D2D', fontSize: 16, padding: 12, background: '#2a1a1a', borderRadius: 8 }}>
                {searchError}
              </div>
            )}
            <div style={{ color: '#666', fontSize: 16, marginTop: 20 }}>
              提示: 可输入订单号（如 TX20260327001）或使用扫码枪扫描小票条码
            </div>
          </div>
        )}

        {/* ════ Step 2: 选择退款类型 ════ */}
        {step === 'select' && order && (
          <div style={{ display: 'flex', gap: 24, flex: 1 }}>
            {/* 订单详情 */}
            <div style={{ flex: 1 }}>
              <h2 style={{ fontSize: 20, marginBottom: 16 }}>订单详情</h2>
              <div style={{ background: '#112B36', borderRadius: 12, padding: 20, marginBottom: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, fontSize: 16, marginBottom: 16 }}>
                  <div><span style={{ color: '#8899A6' }}>订单号:</span> {order.order_no}</div>
                  <div><span style={{ color: '#8899A6' }}>桌号:</span> {order.table_no}</div>
                  <div><span style={{ color: '#8899A6' }}>结算时间:</span> {order.settled_at}</div>
                  <div><span style={{ color: '#8899A6' }}>支付方式:</span> {order.payment_method}</div>
                </div>
                <div style={{ borderTop: '1px solid #1A3A48', paddingTop: 12 }}>
                  {order.items.map((item) => {
                    const isSelected = selectedItems.has(item.item_id);
                    const isPartial = refundType === 'partial';
                    return (
                      <div
                        key={item.item_id}
                        onClick={() => isPartial && toggleItem(item.item_id)}
                        style={{
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          padding: '10px 8px', fontSize: 16, borderBottom: '1px solid #1a2a33',
                          cursor: isPartial ? 'pointer' : 'default',
                          background: isPartial && isSelected ? 'rgba(255,107,44,0.1)' : 'transparent',
                          borderRadius: 6, transition: 'background 150ms',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          {isPartial && (
                            <div style={{
                              width: 22, height: 22, borderRadius: 4,
                              border: isSelected ? '2px solid #FF6B2C' : '2px solid #555',
                              background: isSelected ? '#FF6B2C' : 'transparent',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              color: '#fff', fontSize: 14, fontWeight: 'bold', flexShrink: 0,
                            }}>
                              {isSelected && '\u2713'}
                            </div>
                          )}
                          <span>{item.dish_name} x{item.quantity}</span>
                        </div>
                        <span>{fen2yuan(item.subtotal_fen || item.unit_price_fen * item.quantity)}</span>
                      </div>
                    );
                  })}
                </div>
                <div style={{ borderTop: '1px solid #333', paddingTop: 12, marginTop: 8 }}>
                  {order.discount_fen > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#999', marginBottom: 4 }}>
                      <span>优惠</span><span>-{fen2yuan(order.discount_fen)}</span>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 'bold', color: '#FF6B2C' }}>
                    <span>实付</span><span>{fen2yuan(order.final_fen)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 退款类型选择 */}
            <div style={{ width: 360, display: 'flex', flexDirection: 'column' }}>
              <h2 style={{ fontSize: 20, marginBottom: 16 }}>退款类型</h2>

              {/* Full refund */}
              <button
                onClick={() => { setRefundType('full'); setSelectedItems(new Set()); setCustomAmountYuan(''); }}
                style={{
                  width: '100%', padding: 16, marginBottom: 12, borderRadius: 12, textAlign: 'left',
                  background: refundType === 'full' ? '#1A3A48' : '#112B36',
                  border: refundType === 'full' ? '2px solid #FF6B2C' : '2px solid transparent',
                  color: '#fff', cursor: 'pointer', transition: 'transform 200ms ease, border-color 200ms ease',
                  minHeight: 56,
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                <div style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 4 }}>全额退款</div>
                <div style={{ fontSize: 16, color: '#8899A6' }}>退还订单全部金额 {fen2yuan(order.final_fen)}</div>
              </button>

              {/* Partial refund */}
              <button
                onClick={() => setRefundType('partial')}
                style={{
                  width: '100%', padding: 16, marginBottom: 12, borderRadius: 12, textAlign: 'left',
                  background: refundType === 'partial' ? '#1A3A48' : '#112B36',
                  border: refundType === 'partial' ? '2px solid #FF6B2C' : '2px solid transparent',
                  color: '#fff', cursor: 'pointer', transition: 'transform 200ms ease, border-color 200ms ease',
                  minHeight: 56,
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                <div style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 4 }}>部分退款</div>
                <div style={{ fontSize: 16, color: '#8899A6' }}>选择菜品或输入自定义金额</div>
              </button>

              {/* Custom amount input (partial only) */}
              {refundType === 'partial' && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 14, color: '#8899A6', marginBottom: 8 }}>
                    在左侧勾选菜品，或输入自定义退款金额:
                  </div>
                  <input
                    type="number"
                    placeholder="自定义退款金额(元)"
                    value={customAmountYuan}
                    onChange={(e) => { setCustomAmountYuan(e.target.value); setSelectedItems(new Set()); }}
                    style={{
                      width: '100%', padding: 14, fontSize: 18, border: '2px solid #333',
                      borderRadius: 12, background: '#112228', color: '#fff',
                      outline: 'none', boxSizing: 'border-box',
                    }}
                    onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                    onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
                  />
                  {refundAmountFen > order.final_fen && (
                    <div style={{ color: '#A32D2D', fontSize: 14, marginTop: 6 }}>
                      退款金额不能超过实付金额 {fen2yuan(order.final_fen)}
                    </div>
                  )}
                </div>
              )}

              {/* Refund amount preview */}
              {refundAmountFen > 0 && (
                <div style={{
                  background: '#112B36', borderRadius: 12, padding: 16, marginBottom: 16,
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                }}>
                  <span style={{ fontSize: 16, color: '#8899A6' }}>退款金额</span>
                  <span style={{ fontSize: 24, fontWeight: 'bold', color: '#FF6B2C' }}>{fen2yuan(refundAmountFen)}</span>
                </div>
              )}

              <div style={{ marginTop: 'auto' }}>
                <button
                  onClick={() => {
                    if (canProceedFromSelect && refundAmountFen <= (order?.final_fen ?? 0)) {
                      setStep('reason');
                    }
                  }}
                  disabled={!canProceedFromSelect || refundAmountFen <= 0 || refundAmountFen > (order?.final_fen ?? 0)}
                  style={{
                    width: '100%', padding: 16,
                    background: canProceedFromSelect && refundAmountFen > 0 && refundAmountFen <= order.final_fen ? '#FF6B2C' : '#444',
                    border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, fontWeight: 'bold',
                    cursor: canProceedFromSelect && refundAmountFen > 0 && refundAmountFen <= order.final_fen ? 'pointer' : 'not-allowed',
                    minHeight: 56, transition: 'transform 200ms ease',
                  }}
                  onPointerDown={(e) => { if (canProceedFromSelect) e.currentTarget.style.transform = 'scale(0.97)'; }}
                  onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                >
                  下一步 — 退款原因
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ════ Step 3: 退款原因 ════ */}
        {step === 'reason' && order && (
          <div style={{ maxWidth: 560, margin: '0 auto', width: '100%' }}>
            <h2 style={{ fontSize: 24, marginBottom: 24 }}>退款原因 <span style={{ color: '#A32D2D' }}>*</span></h2>
            <div style={{ marginBottom: 24 }}>
              {REFUND_REASONS.map((r) => (
                <button
                  key={r.key}
                  onClick={() => setSelectedReason(r.key)}
                  style={{
                    width: '100%', padding: 16, marginBottom: 10, borderRadius: 12, textAlign: 'left',
                    background: selectedReason === r.key ? '#1A3A48' : '#112B36',
                    border: selectedReason === r.key ? '2px solid #FF6B2C' : '2px solid transparent',
                    color: '#fff', cursor: 'pointer', fontSize: 18, fontWeight: 500,
                    transition: 'transform 200ms ease, border-color 200ms ease', minHeight: 52,
                  }}
                  onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                  onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                >
                  {r.label}
                </button>
              ))}
            </div>

            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>补充说明（选填）</div>
              <textarea
                placeholder="请输入补充说明..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                style={{
                  width: '100%', padding: 16, fontSize: 16, border: '2px solid #333',
                  borderRadius: 12, background: '#112228', color: '#fff',
                  minHeight: 80, resize: 'none', boxSizing: 'border-box', outline: 'none',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
              />
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={() => setStep('select')}
                style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                上一步
              </button>
              <button
                onClick={() => canProceedFromReason && setStep('confirm')}
                disabled={!canProceedFromReason}
                style={{
                  flex: 2, padding: 16,
                  background: canProceedFromReason ? '#FF6B2C' : '#444',
                  border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, fontWeight: 'bold',
                  cursor: canProceedFromReason ? 'pointer' : 'not-allowed', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (canProceedFromReason) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                下一步 — 确认退款
              </button>
            </div>
          </div>
        )}

        {/* ════ Step 4: 确认退款 ════ */}
        {step === 'confirm' && order && (
          <div style={{ maxWidth: 480, margin: '0 auto', width: '100%', textAlign: 'center' }}>
            <div style={{
              width: 80, height: 80, borderRadius: 40, background: '#BA7517', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, fontWeight: 'bold', margin: '0 auto 20px',
            }}>
              !
            </div>
            <h2 style={{ fontSize: 24, marginBottom: 8 }}>确认退款</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 24 }}>
              请仔细核对退款信息后确认
            </div>

            {/* 退款摘要 */}
            <div style={{ background: '#112B36', borderRadius: 12, padding: 16, marginBottom: 24, textAlign: 'left', fontSize: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ color: '#8899A6' }}>订单号</span><span>{order.order_no}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ color: '#8899A6' }}>原订单金额</span><span>{fen2yuan(order.final_fen)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ color: '#8899A6' }}>退款金额</span>
                <span style={{ color: '#FF6B2C', fontWeight: 'bold', fontSize: 20 }}>{fen2yuan(refundAmountFen)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ color: '#8899A6' }}>退款方式</span><span>原路退回（{order.payment_method}）</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#8899A6' }}>退款原因</span>
                <span>{REFUND_REASONS.find((r) => r.key === selectedReason)?.label}</span>
              </div>
              {notes && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #1A3A48' }}>
                  <span style={{ color: '#8899A6' }}>补充说明: </span>{notes}
                </div>
              )}
            </div>

            {/* Manager PIN (if needed) */}
            {needsManagerAuth && (
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 16, color: '#BA7517', marginBottom: 12, fontWeight: 'bold' }}>
                  退款金额超过 100 元，需要店长授权
                </div>
                <input
                  type="password"
                  placeholder="请输入店长授权码"
                  value={managerPin}
                  onChange={(e) => { setManagerPin(e.target.value); setAuthError(''); }}
                  onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
                  autoFocus
                  style={{
                    width: '100%', padding: 20, fontSize: 24, textAlign: 'center',
                    border: authError ? '2px solid #A32D2D' : '2px solid #333',
                    borderRadius: 12, background: '#112228', color: '#fff',
                    boxSizing: 'border-box', outline: 'none', letterSpacing: 8,
                  }}
                  onFocus={(e) => { if (!authError) e.currentTarget.style.borderColor = '#FF6B2C'; }}
                  onBlur={(e) => { if (!authError) e.currentTarget.style.borderColor = '#333'; }}
                />
                {authError && (
                  <div style={{ color: '#A32D2D', fontSize: 16, marginTop: 8 }}>{authError}</div>
                )}
              </div>
            )}

            {submitError && (
              <div style={{ color: '#A32D2D', fontSize: 16, padding: 12, background: '#2a1a1a', borderRadius: 8, marginBottom: 16 }}>
                {submitError}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={() => { setStep('reason'); setManagerPin(''); setAuthError(''); setSubmitError(''); }}
                style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                返回
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting || (needsManagerAuth && !managerPin.trim())}
                style={{
                  flex: 2, padding: 16, border: 'none', borderRadius: 12, color: '#fff',
                  fontSize: 18, fontWeight: 'bold', minHeight: 56,
                  background: submitting || (needsManagerAuth && !managerPin.trim()) ? '#444' : '#A32D2D',
                  cursor: submitting || (needsManagerAuth && !managerPin.trim()) ? 'not-allowed' : 'pointer',
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (!submitting) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {submitting ? '处理中...' : `确认退款 ${fen2yuan(refundAmountFen)}`}
              </button>
            </div>
          </div>
        )}

        {/* ════ Step 5: 完成 ════ */}
        {step === 'done' && order && (
          <div style={{ maxWidth: 480, margin: '0 auto', width: '100%', textAlign: 'center', paddingTop: 40 }}>
            <div style={{
              width: 80, height: 80, borderRadius: 40, background: '#0F6E56', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, fontWeight: 'bold', margin: '0 auto 20px',
            }}>
              {'\u2713'}
            </div>
            <h2 style={{ fontSize: 24, marginBottom: 8, color: '#0F6E56' }}>退款成功</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>
              订单 {order.order_no} 已退款 {fen2yuan(refundAmountFen)}
            </div>
            {refundNo && (
              <div style={{ fontSize: 14, color: '#666', marginBottom: 32 }}>
                退款单号: {refundNo}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={handlePrintRefund}
                disabled={printing}
                style={{
                  flex: 1, padding: 16, background: '#112B36', border: '2px solid #FF6B2C', borderRadius: 12,
                  color: '#FF6B2C', fontSize: 18, fontWeight: 'bold',
                  cursor: printing ? 'not-allowed' : 'pointer', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (!printing) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {printing ? '打印中...' : '打印退款小票'}
              </button>
              <button
                onClick={() => navigate('/tables')}
                style={{
                  flex: 1, padding: 16, background: '#FF6B2C', border: 'none', borderRadius: 12,
                  color: '#fff', fontSize: 18, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                返回桌台
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
