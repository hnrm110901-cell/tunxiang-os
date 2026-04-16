/**
 * 反结账页面
 * 输入订单号/扫码 → 查看已结账订单 → 选择原因 → 店长授权 → 确认反结
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getOrder } from '../api/tradeApi';
import { formatPrice } from '@tx-ds/utils';

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const REVERSE_REASONS = [
  { key: 'complaint', label: '客诉处理', desc: '顾客投诉需重新处理订单' },
  { key: 'error', label: '操作错误', desc: '收银员录入有误需修正' },
  { key: 'return_dish', label: '退菜退款', desc: '菜品问题需退菜后重新结算' },
  { key: 'other', label: '其他原因', desc: '需在备注中说明具体原因' },
];

/* ---------- Mock 已结订单（后续对接 tx-trade API） ---------- */
interface SettledOrder {
  orderId: string;
  orderNo: string;
  tableNo: string;
  settledAt: string;
  totalFen: number;
  discountFen: number;
  paymentMethod: string;
  items: Array<{ name: string; quantity: number; priceFen: number }>;
}

const MOCK_SETTLED: Record<string, SettledOrder> = {
  'TX20260327001': {
    orderId: 'ord_001', orderNo: 'TX20260327001', tableNo: 'A03',
    settledAt: '2026-03-27 12:35:00', totalFen: 35600, discountFen: 0,
    paymentMethod: '微信支付',
    items: [
      { name: '剁椒鱼头', quantity: 1, priceFen: 8800 },
      { name: '口味虾', quantity: 1, priceFen: 12800 },
      { name: '农家小炒肉', quantity: 2, priceFen: 4200 },
      { name: '米饭', quantity: 4, priceFen: 300 },
      { name: '酸梅汤', quantity: 4, priceFen: 800 },
    ],
  },
  'TX20260327002': {
    orderId: 'ord_002', orderNo: 'TX20260327002', tableNo: 'B05',
    settledAt: '2026-03-27 13:10:00', totalFen: 14700, discountFen: 1000,
    paymentMethod: '支付宝',
    items: [
      { name: '凉拌黄瓜', quantity: 1, priceFen: 900 },
      { name: '农家小炒肉', quantity: 1, priceFen: 4200 },
      { name: '剁椒鱼头', quantity: 1, priceFen: 8800 },
      { name: '米饭', quantity: 2, priceFen: 300 },
    ],
  },
};

type Step = 'search' | 'detail' | 'auth' | 'done';

export function ReverseSettlePage() {
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('search');
  const [searchInput, setSearchInput] = useState('');
  const [order, setOrder] = useState<SettledOrder | null>(null);
  const [searchError, setSearchError] = useState('');

  const [selectedReason, setSelectedReason] = useState('');
  const [remark, setRemark] = useState('');

  const [authCode, setAuthCode] = useState('');
  const [authError, setAuthError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // 搜索订单
  const handleSearch = async () => {
    const input = searchInput.trim().toUpperCase();
    if (!input) return;
    setSearchError('');

    // 优先用 Mock，再尝试 API
    const mockOrder = MOCK_SETTLED[input];
    if (mockOrder) {
      setOrder(mockOrder);
      setStep('detail');
      return;
    }

    try {
      const result = await getOrder(input);
      if (result) {
        // 将 API 返回转化为本地格式（占位）
        setOrder({
          orderId: String(result.order_id || input),
          orderNo: String(result.order_no || input),
          tableNo: String(result.table_no || '--'),
          settledAt: String(result.settled_at || '--'),
          totalFen: Number(result.total_fen || 0),
          discountFen: Number(result.discount_fen || 0),
          paymentMethod: String(result.payment_method || '--'),
          items: Array.isArray(result.items) ? (result.items as Array<{ name: string; quantity: number; priceFen: number }>) : [],
        });
        setStep('detail');
        return;
      }
    } catch {
      // API 失败继续本地提示
    }

    setSearchError('未找到该订单，请检查订单号');
  };

  // 店长授权验证
  const handleAuth = async () => {
    if (!authCode.trim()) {
      setAuthError('请输入店长授权码');
      return;
    }
    setSubmitting(true);
    setAuthError('');

    // Mock 校验：授权码 888888 通过
    await new Promise((r) => setTimeout(r, 600));
    if (authCode === '888888') {
      // TODO: 调用 tx-trade 反结账 API
      // await txFetch(`/api/v1/trade/orders/${order!.orderId}/reverse-settle`, {
      //   method: 'POST',
      //   body: JSON.stringify({ reason: selectedReason, remark, auth_code: authCode }),
      // });
      setStep('done');
    } else {
      setAuthError('授权码错误，请联系店长');
    }
    setSubmitting(false);
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 流程步骤指示器 */}
      <div style={{ width: 200, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <h3 style={{ margin: '0 0 20px', fontSize: 20 }}>反结账</h3>
        {(['search', 'detail', 'auth', 'done'] as Step[]).map((s, i) => {
          const labels = ['查找订单', '确认详情', '权限验证', '完成'];
          const isCurrent = s === step;
          const isPast = ['search', 'detail', 'auth', 'done'].indexOf(step) > i;
          return (
            <div key={s} style={{
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
                {isPast ? '✓' : i + 1}
              </div>
              {labels[i]}
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
      <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column' }}>
        {/* Step 1: 搜索订单 */}
        {step === 'search' && (
          <div style={{ maxWidth: 600, margin: '0 auto', width: '100%' }}>
            <h2 style={{ fontSize: 24, marginBottom: 24 }}>查找已结账订单</h2>
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
                style={{
                  padding: '16px 32px', background: '#FF6B2C', border: 'none',
                  borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer',
                  minHeight: 56, fontWeight: 'bold', transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                查询
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

        {/* Step 2: 订单详情 + 原因选择 */}
        {step === 'detail' && order && (
          <div style={{ display: 'flex', gap: 24, flex: 1 }}>
            {/* 订单详情 */}
            <div style={{ flex: 1 }}>
              <h2 style={{ fontSize: 20, marginBottom: 16 }}>订单详情</h2>
              <div style={{ background: '#112B36', borderRadius: 12, padding: 20, marginBottom: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, fontSize: 16, marginBottom: 16 }}>
                  <div><span style={{ color: '#8899A6' }}>订单号:</span> {order.orderNo}</div>
                  <div><span style={{ color: '#8899A6' }}>桌号:</span> {order.tableNo}</div>
                  <div><span style={{ color: '#8899A6' }}>结算时间:</span> {order.settledAt}</div>
                  <div><span style={{ color: '#8899A6' }}>支付方式:</span> {order.paymentMethod}</div>
                </div>
                <div style={{ borderTop: '1px solid #1A3A48', paddingTop: 12 }}>
                  {order.items.map((item, idx) => (
                    <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', fontSize: 16, borderBottom: '1px solid #1a2a33' }}>
                      <span>{item.name} x{item.quantity}</span>
                      <span>{fen2yuan(item.priceFen * item.quantity)}</span>
                    </div>
                  ))}
                </div>
                <div style={{ borderTop: '1px solid #333', paddingTop: 12, marginTop: 8 }}>
                  {order.discountFen > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#999', marginBottom: 4 }}>
                      <span>优惠</span><span>-{fen2yuan(order.discountFen)}</span>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 22, fontWeight: 'bold', color: '#FF6B2C' }}>
                    <span>实付</span><span>{fen2yuan(order.totalFen - order.discountFen)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* 原因选择 */}
            <div style={{ width: 360, display: 'flex', flexDirection: 'column' }}>
              <h2 style={{ fontSize: 20, marginBottom: 16 }}>反结原因 <span style={{ color: '#A32D2D' }}>*</span></h2>
              <div style={{ flex: 1 }}>
                {REVERSE_REASONS.map((r) => (
                  <button
                    key={r.key}
                    onClick={() => setSelectedReason(r.key)}
                    style={{
                      width: '100%', padding: 16, marginBottom: 12, borderRadius: 12, textAlign: 'left',
                      background: selectedReason === r.key ? '#1A3A48' : '#112B36',
                      border: selectedReason === r.key ? '2px solid #FF6B2C' : '2px solid transparent',
                      color: '#fff', cursor: 'pointer', transition: 'transform 200ms ease, border-color 200ms ease',
                      minHeight: 56,
                    }}
                    onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                    onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                    onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  >
                    <div style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 4 }}>{r.label}</div>
                    <div style={{ fontSize: 16, color: '#8899A6' }}>{r.desc}</div>
                  </button>
                ))}
                {selectedReason === 'other' && (
                  <textarea
                    placeholder="请输入具体原因..."
                    value={remark}
                    onChange={(e) => setRemark(e.target.value)}
                    style={{
                      width: '100%', padding: 16, fontSize: 16, border: '2px solid #333',
                      borderRadius: 12, background: '#112228', color: '#fff',
                      minHeight: 80, resize: 'none', boxSizing: 'border-box', outline: 'none',
                    }}
                    onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                    onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
                  />
                )}
              </div>
              <button
                onClick={() => selectedReason && setStep('auth')}
                disabled={!selectedReason}
                style={{
                  width: '100%', padding: 16, background: selectedReason ? '#FF6B2C' : '#444',
                  border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, fontWeight: 'bold',
                  cursor: selectedReason ? 'pointer' : 'not-allowed', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (selectedReason) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                下一步 — 权限验证
              </button>
            </div>
          </div>
        )}

        {/* Step 3: 店长授权 */}
        {step === 'auth' && order && (
          <div style={{ maxWidth: 480, margin: '0 auto', width: '100%', textAlign: 'center' }}>
            <div style={{
              width: 80, height: 80, borderRadius: 40, background: '#BA7517', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, fontWeight: 'bold', margin: '0 auto 20px',
            }}>
              !
            </div>
            <h2 style={{ fontSize: 24, marginBottom: 8 }}>需要店长授权</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 32 }}>
              反结账操作需要店长授权码确认。请联系值班店长输入授权码。
            </div>

            {/* 订单摘要 */}
            <div style={{ background: '#112B36', borderRadius: 12, padding: 16, marginBottom: 24, textAlign: 'left', fontSize: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ color: '#8899A6' }}>订单号</span><span>{order.orderNo}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ color: '#8899A6' }}>金额</span><span style={{ color: '#FF6B2C', fontWeight: 'bold' }}>{fen2yuan(order.totalFen - order.discountFen)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: '#8899A6' }}>原因</span><span>{REVERSE_REASONS.find(r => r.key === selectedReason)?.label}</span>
              </div>
            </div>

            {/* 授权码输入 */}
            <input
              type="password"
              placeholder="请输入店长授权码"
              value={authCode}
              onChange={(e) => { setAuthCode(e.target.value); setAuthError(''); }}
              onKeyDown={(e) => e.key === 'Enter' && handleAuth()}
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

            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
              <button
                onClick={() => { setStep('detail'); setAuthCode(''); setAuthError(''); }}
                style={{ flex: 1, padding: 16, background: '#333', border: 'none', borderRadius: 12, color: '#fff', fontSize: 18, cursor: 'pointer', minHeight: 56 }}
              >
                返回
              </button>
              <button
                onClick={handleAuth}
                disabled={submitting || !authCode.trim()}
                style={{
                  flex: 2, padding: 16, border: 'none', borderRadius: 12, color: '#fff',
                  fontSize: 18, fontWeight: 'bold', minHeight: 56,
                  background: submitting || !authCode.trim() ? '#444' : '#A32D2D',
                  cursor: submitting || !authCode.trim() ? 'not-allowed' : 'pointer',
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { if (!submitting && authCode.trim()) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {submitting ? '验证中...' : '确认反结账'}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: 完成 */}
        {step === 'done' && order && (
          <div style={{ maxWidth: 480, margin: '0 auto', width: '100%', textAlign: 'center', paddingTop: 40 }}>
            <div style={{
              width: 80, height: 80, borderRadius: 40, background: '#0F6E56', color: '#fff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 36, fontWeight: 'bold', margin: '0 auto 20px',
            }}>
              ✓
            </div>
            <h2 style={{ fontSize: 24, marginBottom: 8, color: '#0F6E56' }}>反结账成功</h2>
            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 32 }}>
              订单 {order.orderNo} 已恢复为未结状态，可重新操作。
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
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
              <button
                onClick={() => navigate(`/cashier/${order.tableNo}`)}
                style={{
                  flex: 1, padding: 16, background: '#112B36', border: '2px solid #FF6B2C', borderRadius: 12,
                  color: '#FF6B2C', fontSize: 18, fontWeight: 'bold', cursor: 'pointer', minHeight: 56,
                  transition: 'transform 200ms ease',
                }}
                onPointerDown={(e) => { e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                重新点餐
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
