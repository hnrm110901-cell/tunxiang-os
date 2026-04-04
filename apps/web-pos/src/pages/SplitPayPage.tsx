/**
 * 部分结账/拆单结账页面
 * 勾选菜品 → 计算金额 → 多种支付方式分摊 → 剩余保留
 */
import { useState, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore, type OrderItem } from '../store/orderStore';
import { createPayment, settleOrder } from '../api/tradeApi';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const PAYMENT_METHODS = [
  { key: 'wechat', label: '微信支付', color: '#07C160' },
  { key: 'alipay', label: '支付宝', color: '#1677FF' },
  { key: 'cash', label: '现金', color: '#faad14' },
  { key: 'unionpay', label: '银联刷卡', color: '#e6002d' },
  { key: 'member_balance', label: '会员余额', color: '#13c2c2' },
];

interface SplitPayment {
  id: string;
  method: string;
  methodLabel: string;
  amountFen: number;
}

let splitCounter = 0;

export function SplitPayPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { items, totalFen, discountFen, tableNo } = useOrderStore();
  const finalFen = totalFen - discountFen;

  // 菜品勾选状态
  const [selectedItemIds, setSelectedItemIds] = useState<Set<string>>(new Set());
  // 支付分摊列表
  const [payments, setPayments] = useState<SplitPayment[]>([]);
  // 当前选择的支付方式（用于添加分摊）
  const [activeMethod, setActiveMethod] = useState('');
  // 自定义金额输入
  const [customAmountStr, setCustomAmountStr] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<'select' | 'pay'>('select');

  // 选中菜品的总金额
  const selectedTotalFen = useMemo(() => {
    return items
      .filter((item) => selectedItemIds.has(item.id))
      .reduce((sum, item) => sum + item.priceFen * item.quantity, 0);
  }, [items, selectedItemIds]);

  // 已分摊支付总额
  const paidTotalFen = useMemo(() => {
    return payments.reduce((sum, p) => sum + p.amountFen, 0);
  }, [payments]);

  // 剩余待付
  const remainingFen = selectedTotalFen - paidTotalFen;

  const toggleItem = (id: string) => {
    setSelectedItemIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedItemIds.size === items.length) {
      setSelectedItemIds(new Set());
    } else {
      setSelectedItemIds(new Set(items.map((i) => i.id)));
    }
  };

  const addPayment = () => {
    if (!activeMethod || !customAmountStr) return;
    const amountFen = Math.round(parseFloat(customAmountStr) * 100);
    if (isNaN(amountFen) || amountFen <= 0) return;
    if (amountFen > remainingFen) return;

    const methodInfo = PAYMENT_METHODS.find((m) => m.key === activeMethod);
    setPayments((prev) => [
      ...prev,
      {
        id: `sp_${++splitCounter}`,
        method: activeMethod,
        methodLabel: methodInfo?.label || activeMethod,
        amountFen,
      },
    ]);
    setCustomAmountStr('');
    setActiveMethod('');
  };

  const removePayment = (id: string) => {
    setPayments((prev) => prev.filter((p) => p.id !== id));
  };

  const fillRemaining = () => {
    if (remainingFen > 0) {
      setCustomAmountStr((remainingFen / 100).toFixed(2));
    }
  };

  const handleConfirm = async () => {
    if (submitting || remainingFen !== 0) return;
    setSubmitting(true);
    try {
      if (orderId) {
        // 1. 初始化拆单分摊
        const BASE = import.meta.env.VITE_API_BASE_URL || '';
        const TENANT = import.meta.env.VITE_TENANT_ID || '';
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (TENANT) headers['X-Tenant-ID'] = TENANT;

        await fetch(`${BASE}/api/v1/trade/orders/${orderId}/split-pay/init`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            splits: payments.map((p, idx) => ({
              split_no: idx + 1,
              amount_fen: p.amountFen,
              payment_method: p.method,
              label: p.methodLabel,
            })),
            item_ids: Array.from(selectedItemIds),
          }),
        });

        // 2. 逐笔创建支付并结算分摊
        for (let i = 0; i < payments.length; i++) {
          const p = payments[i];
          await createPayment(orderId, p.method, p.amountFen);
          await fetch(`${BASE}/api/v1/trade/orders/${orderId}/split-pay/${i + 1}/settle`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ payment_method: p.method }),
          });
        }

        // 3. 若全部菜品都已选中（全额拆单），结算整单
        if (selectedItemIds.size === items.length) {
          await settleOrder(orderId);
        }
      }
      navigate('/tables');
    } catch (e) {
      alert(`结账失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 菜品选择 */}
      <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>拆单结账 · 桌号 {tableNo}</h2>
          <button
            onClick={selectAll}
            style={{
              padding: '8px 20px', background: '#1A3A48', border: '1px solid #333',
              borderRadius: 8, color: '#fff', fontSize: 16, cursor: 'pointer', minHeight: 48,
            }}
          >
            {selectedItemIds.size === items.length ? '取消全选' : '全选'}
          </button>
        </div>

        {/* 菜品列表 */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
          {items.map((item) => {
            const isSelected = selectedItemIds.has(item.id);
            return (
              <button
                key={item.id}
                onClick={() => step === 'select' && toggleItem(item.id)}
                disabled={step !== 'select'}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 16,
                  padding: 16, marginBottom: 8, borderRadius: 12, textAlign: 'left',
                  background: isSelected ? '#1A3A48' : '#112B36',
                  border: isSelected ? '2px solid #FF6B2C' : '2px solid transparent',
                  color: '#fff', cursor: step === 'select' ? 'pointer' : 'default',
                  transition: 'transform 200ms ease, border-color 200ms ease',
                  opacity: step !== 'select' ? 0.7 : 1,
                  minHeight: 56,
                }}
                onPointerDown={(e) => { if (step === 'select') e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {/* 勾选框 */}
                <div style={{
                  width: 28, height: 28, borderRadius: 6, flexShrink: 0,
                  border: isSelected ? 'none' : '2px solid #555',
                  background: isSelected ? '#FF6B2C' : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff', fontSize: 16, fontWeight: 'bold',
                }}>
                  {isSelected && '✓'}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 'bold' }}>{item.name}</div>
                  <div style={{ fontSize: 16, color: '#8899A6' }}>
                    {fen2yuan(item.priceFen)} x {item.quantity}
                  </div>
                </div>
                <div style={{ fontSize: 18, fontWeight: 'bold', color: isSelected ? '#FF6B2C' : '#fff' }}>
                  {fen2yuan(item.priceFen * item.quantity)}
                </div>
              </button>
            );
          })}
        </div>

        {/* 选中汇总 + 操作 */}
        <div style={{ borderTop: '1px solid #333', paddingTop: 16, marginTop: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#8899A6', marginBottom: 8 }}>
            <span>已选 {selectedItemIds.size}/{items.length} 项</span>
            <span>未选金额: {fen2yuan(finalFen - selectedTotalFen)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 'bold', color: '#FF6B2C', marginBottom: 12 }}>
            <span>选中金额</span>
            <span>{fen2yuan(selectedTotalFen)}</span>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={() => navigate(-1)}
              style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
            >
              返回
            </button>
            {step === 'select' && (
              <button
                onClick={() => selectedItemIds.size > 0 && setStep('pay')}
                disabled={selectedItemIds.size === 0}
                style={{
                  flex: 2, padding: 16, border: 'none', borderRadius: 12, color: '#fff',
                  fontSize: 18, fontWeight: 'bold', minHeight: 56,
                  background: selectedItemIds.size > 0 ? '#FF6B2C' : '#444',
                  cursor: selectedItemIds.size > 0 ? 'pointer' : 'not-allowed',
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (selectedItemIds.size > 0) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                去支付
              </button>
            )}
            {step === 'pay' && (
              <button
                onClick={() => { setStep('select'); setPayments([]); }}
                style={{ flex: 2, padding: 16, background: '#1A3A48', border: '1px solid #FF6B2C', borderRadius: 12, color: '#FF6B2C', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                返回选菜
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 右侧 — 支付分摊面板（step=pay 时展开） */}
      {step === 'pay' && (
        <div style={{ width: 400, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 20 }}>支付分摊</h3>

          {/* 金额摘要 */}
          <div style={{ background: '#0B1A20', borderRadius: 12, padding: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 8 }}>
              <span style={{ color: '#8899A6' }}>选中金额</span>
              <span>{fen2yuan(selectedTotalFen)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 8 }}>
              <span style={{ color: '#8899A6' }}>已分摊</span>
              <span style={{ color: '#0F6E56' }}>{fen2yuan(paidTotalFen)}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 20, fontWeight: 'bold', borderTop: '1px solid #333', paddingTop: 8 }}>
              <span>待付</span>
              <span style={{ color: remainingFen > 0 ? '#FF6B2C' : '#0F6E56' }}>{fen2yuan(remainingFen)}</span>
            </div>
          </div>

          {/* 已分摊记录 */}
          {payments.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              {payments.map((p) => (
                <div key={p.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: 12, marginBottom: 8, borderRadius: 8, background: '#1A3A48', fontSize: 16,
                }}>
                  <span>{p.methodLabel}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontWeight: 'bold' }}>{fen2yuan(p.amountFen)}</span>
                    <button
                      onClick={() => removePayment(p.id)}
                      style={{
                        width: 32, height: 32, borderRadius: 6, border: 'none',
                        background: '#A32D2D', color: '#fff', fontSize: 16,
                        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      x
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 添加分摊 */}
          {remainingFen > 0 && (
            <>
              <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>选择支付方式</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
                {PAYMENT_METHODS.map((m) => (
                  <button
                    key={m.key}
                    onClick={() => setActiveMethod(m.key)}
                    style={{
                      padding: 12, borderRadius: 8, border: activeMethod === m.key ? '2px solid #FF6B2C' : '2px solid transparent',
                      background: activeMethod === m.key ? '#1A3A48' : '#112B36',
                      color: '#fff', fontSize: 16, cursor: 'pointer', minHeight: 48,
                      transition: 'transform 200ms ease',
                    }}
                    onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                    onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                    onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  >
                    {m.label}
                  </button>
                ))}
              </div>

              <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>输入金额</div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="0.00"
                  value={customAmountStr}
                  onChange={(e) => setCustomAmountStr(e.target.value)}
                  style={{
                    flex: 1, padding: 14, fontSize: 20, border: '2px solid #333',
                    borderRadius: 12, background: '#0B1A20', color: '#fff',
                    outline: 'none', boxSizing: 'border-box', textAlign: 'right',
                  }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
                />
                <button
                  onClick={fillRemaining}
                  style={{
                    padding: '0 16px', background: '#1A3A48', border: '1px solid #555',
                    borderRadius: 12, color: '#fff', fontSize: 16, cursor: 'pointer', whiteSpace: 'nowrap', minHeight: 48,
                  }}
                >
                  剩余全付
                </button>
              </div>
              <button
                onClick={addPayment}
                disabled={!activeMethod || !customAmountStr}
                style={{
                  width: '100%', padding: 14, border: 'none', borderRadius: 12, fontSize: 18,
                  background: activeMethod && customAmountStr ? '#1677FF' : '#444',
                  color: '#fff', cursor: activeMethod && customAmountStr ? 'pointer' : 'not-allowed',
                  marginBottom: 12, minHeight: 56, fontWeight: 'bold',
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (activeMethod && customAmountStr) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                添加分摊
              </button>
            </>
          )}

          {/* 确认按钮 */}
          <button
            onClick={handleConfirm}
            disabled={remainingFen !== 0 || submitting}
            style={{
              width: '100%', padding: 16, border: 'none', borderRadius: 12,
              background: remainingFen === 0 && !submitting ? '#FF6B2C' : '#444',
              color: '#fff', fontSize: 20, fontWeight: 'bold', marginTop: 'auto',
              cursor: remainingFen === 0 && !submitting ? 'pointer' : 'not-allowed',
              minHeight: 72, transition: 'transform 200ms ease',
            }}
            onPointerDown={(e) => { if (remainingFen === 0 && !submitting) e.currentTarget.style.transform = 'scale(0.97)'; }}
            onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
            onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
          >
            {submitting ? '处理中...' : remainingFen === 0 ? '确认结账' : `还需分摊 ${fen2yuan(remainingFen)}`}
          </button>
        </div>
      )}
    </div>
  );
}
