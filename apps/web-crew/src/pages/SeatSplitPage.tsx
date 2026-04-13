/**
 * SeatSplitPage — AA均等分摊结账
 * 路由: /seat-split?table=A01&order_id=xxx
 *
 * 流程:
 *   Step 1: 选份数 (2-6) + 显示原价/每份金额 → [开始分摊]
 *   Step 2: 逐份收款 (选支付方式 → 收款)
 *   Step 3: 全部完成 → 3秒返回桌台列表
 */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { txFetch } from '../api/index';

// ─── 颜色常量 ───────────────────────────────────────────────
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentDim: 'rgba(255,107,53,0.15)',
  accentBorder: 'rgba(255,107,53,0.6)',
  green: '#22c55e',
  greenDim: 'rgba(34,197,94,0.15)',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  red: '#ef4444',
};

// ─── 工具函数 ────────────────────────────────────────────────
/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── 类型定义 ────────────────────────────────────────────────
interface SplitItem {
  split_no: number;
  amount_fen: number;
  status: 'pending' | 'paid';
}

// ─── 支付方式 ────────────────────────────────────────────────
const PAY_METHODS = [
  { key: 'cash', label: '现金', icon: '💵' },
  { key: 'wechat', label: '微信', icon: '💚' },
  { key: 'alipay', label: '支付宝', icon: '💙' },
];

// ─── 均分计算（尾差加到最后一份）─────────────────────────────
function calcSplits(totalFen: number, count: number): number[] {
  const base = Math.floor(totalFen / count);
  const remainder = totalFen - base * count;
  return Array.from({ length: count }, (_, i) =>
    i === count - 1 ? base + remainder : base,
  );
}

// ─── 支付方式选择器（内联组件）───────────────────────────────
interface PayMethodPickerProps {
  selected: string;
  onChange: (key: string) => void;
}

function PayMethodPicker({ selected, onChange }: PayMethodPickerProps) {
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
      {PAY_METHODS.map(m => (
        <button
          key={m.key}
          onClick={() => onChange(m.key)}
          style={{
            flex: 1,
            minHeight: 48,
            borderRadius: 10,
            border: selected === m.key
              ? `2px solid ${C.accent}`
              : `1px solid ${C.border}`,
            background: selected === m.key ? C.accentDim : C.card,
            color: selected === m.key ? C.accent : C.text,
            fontSize: 15,
            fontWeight: selected === m.key ? 700 : 400,
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
          }}
        >
          <span style={{ fontSize: 18 }}>{m.icon}</span>
          <span>{m.label}</span>
        </button>
      ))}
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────
export function SeatSplitPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const orderId = searchParams.get('order_id') || '';
  const tableNo = searchParams.get('table') || '';
  const tenantId = (window as any).__TENANT_ID__ || '';

  // ── Step 1 状态
  const [totalFen, setTotalFen] = useState<number | null>(null);
  const [loadingOrder, setLoadingOrder] = useState(false);
  const [orderError, setOrderError] = useState('');
  const [splitCount, setSplitCount] = useState(2);

  // ── Step 2 状态
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [splits, setSplits] = useState<SplitItem[]>([]);
  const [initLoading, setInitLoading] = useState(false);
  const [initError, setInitError] = useState('');

  // ── 逐份收款状态
  // activeSplit: 当前展开的待收份数编号
  const [activeSplit, setActiveSplit] = useState<number | null>(null);
  const [payMethods, setPayMethods] = useState<Record<number, string>>({});
  const [settling, setSettling] = useState<number | null>(null);
  const [settleError, setSettleError] = useState('');

  // ── 成功后倒计时
  const [countdown, setCountdown] = useState(3);

  // ─── 获取订单原价 ─────────────────────────────────────────
  useEffect(() => {
    if (!orderId) return;
    setLoadingOrder(true);
    setOrderError('');
    fetch(`/api/v1/orders/${orderId}`, {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then(r => r.json())
      .then(res => {
        if (res.ok) {
          setTotalFen(res.data.final_amount_fen ?? res.data.total_amount_fen ?? 0);
        } else {
          setOrderError(res.error?.message || '获取订单失败');
        }
      })
      .catch(() => setOrderError('网络错误，无法加载订单'))
      .finally(() => setLoadingOrder(false));
  }, [orderId, tenantId]);

  // ─── 成功后倒计时 ─────────────────────────────────────────
  useEffect(() => {
    if (step !== 3) return;
    if (countdown <= 0) {
      navigate('/tables', { replace: true });
      return;
    }
    const timer = setTimeout(() => setCountdown(c => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [step, countdown, navigate]);

  // ─── 初始化分摊 ───────────────────────────────────────────
  const handleStartSplit = async () => {
    if (!orderId || totalFen === null) return;
    setInitLoading(true);
    setInitError('');
    try {
      const data = await txFetch<{
        splits: Array<{ split_no: number; amount_fen: number; status: 'pending' }>;
      }>(`/api/v1/orders/${encodeURIComponent(orderId)}/split-pay/init`, {
        method: 'POST',
        body: JSON.stringify({ total_splits: splitCount, tenant_id: tenantId }),
      });
      const items: SplitItem[] = data.splits.map(s => ({
        split_no: s.split_no,
        amount_fen: s.amount_fen,
        status: s.status,
      }));
      setSplits(items);
      // 默认展开第一个待收款项
      const firstPending = items.find(s => s.status === 'pending');
      setActiveSplit(firstPending?.split_no ?? null);
      // 初始化每份支付方式默认"现金"
      const methods: Record<number, string> = {};
      items.forEach(s => { methods[s.split_no] = 'cash'; });
      setPayMethods(methods);
      setStep(2);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '初始化分摊失败';
      setInitError(message);
    } finally {
      setInitLoading(false);
    }
  };

  // ─── 某份收款 ─────────────────────────────────────────────
  const handleSettle = async (splitNo: number) => {
    const method = payMethods[splitNo] || 'cash';
    setSettling(splitNo);
    setSettleError('');
    try {
      const data = await txFetch<{ all_paid: boolean }>(
        `/api/v1/orders/${encodeURIComponent(orderId)}/split-pay/${splitNo}/settle`,
        {
          method: 'POST',
          body: JSON.stringify({ payment_method: method, tenant_id: tenantId }),
        },
      );
      // 标记本份已付
      setSplits(prev =>
        prev.map(s => s.split_no === splitNo ? { ...s, status: 'paid' } : s),
      );
      setActiveSplit(null);

      if (data.all_paid) {
        setStep(3);
      } else {
        // 自动展开下一个待收款项
        setSplits(prev => {
          const next = prev.find(
            s => s.split_no !== splitNo && s.status === 'pending',
          );
          setActiveSplit(next?.split_no ?? null);
          return prev;
        });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '收款失败，请重试';
      setSettleError(message);
    } finally {
      setSettling(null);
    }
  };

  // ─── 每份金额预估（Step 1）───────────────────────────────
  const perAmounts = totalFen !== null ? calcSplits(totalFen, splitCount) : null;

  // ─── Step 3: 成功界面 ─────────────────────────────────────
  if (step === 3) {
    return (
      <div style={{
        background: C.bg,
        minHeight: '100vh',
        color: C.white,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '0 24px',
        textAlign: 'center',
      }}>
        <div style={{
          width: 80, height: 80, borderRadius: '50%',
          background: C.greenDim, border: `3px solid ${C.green}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 40, marginBottom: 24,
        }}>
          ✓
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>AA分摊完成！</div>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 32 }}>
          {tableNo} 桌 · 全部 {splits.length} 份已收款
        </div>
        <div style={{
          fontSize: 15, color: C.muted,
          background: C.card, padding: '12px 24px',
          borderRadius: 12, border: `1px solid ${C.border}`,
        }}>
          {countdown} 秒后返回桌台列表…
        </div>
        <button
          onClick={() => navigate('/tables', { replace: true })}
          style={{
            marginTop: 24, padding: '14px 36px', minHeight: 52,
            borderRadius: 12, background: C.accent, color: C.white,
            border: 'none', fontSize: 17, fontWeight: 700, cursor: 'pointer',
          }}
        >
          立即返回
        </button>
      </div>
    );
  }

  // ─── 顶部导航栏（Step 1 & 2 共用）────────────────────────
  const NavBar = (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '0 8px', height: 56,
      borderBottom: `1px solid ${C.border}`,
      background: C.card,
      position: 'sticky', top: 0, zIndex: 10,
    }}>
      <button
        onClick={() => step === 2 ? setStep(1) : navigate(-1)}
        style={{
          width: 48, height: 48, background: 'transparent', border: 'none',
          color: C.text, fontSize: 22, cursor: 'pointer', borderRadius: 8,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
        aria-label="返回"
      >
        ←
      </button>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>AA分摊结账</div>
        {tableNo && (
          <div style={{ fontSize: 14, color: C.muted, marginTop: 1 }}>
            {tableNo} 桌{step === 2 ? ` · ${splits.length} 份` : ''}
          </div>
        )}
      </div>
      <div style={{ width: 48 }} />
    </div>
  );

  // ─── Step 2: 分摊收款视图 ─────────────────────────────────
  if (step === 2) {
    const paidCount = splits.filter(s => s.status === 'paid').length;

    return (
      <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
        {NavBar}

        {/* 进度条 */}
        <div style={{
          padding: '12px 16px 0',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <div style={{
            flex: 1, height: 6, borderRadius: 3,
            background: C.border, overflow: 'hidden',
          }}>
            <div style={{
              width: `${(paidCount / splits.length) * 100}%`,
              height: '100%', background: C.green,
              transition: 'width 0.4s ease',
            }} />
          </div>
          <span style={{ fontSize: 14, color: C.muted, whiteSpace: 'nowrap' }}>
            {paidCount}/{splits.length} 已收款
          </span>
        </div>

        {/* 错误提示 */}
        {settleError && (
          <div style={{
            margin: '10px 16px 0',
            padding: '10px 14px',
            background: 'rgba(239,68,68,0.1)',
            border: `1px solid ${C.red}`,
            borderRadius: 10, fontSize: 15, color: C.red,
          }}>
            {settleError}
          </div>
        )}

        {/* 分摊列表 */}
        <div style={{ padding: '12px 16px 32px' }}>
          {splits.map((split, idx) => {
            const isPaid = split.status === 'paid';
            const isActive = activeSplit === split.split_no;
            const isSettling = settling === split.split_no;
            const isLast = idx === splits.length - 1;
            const method = payMethods[split.split_no] || 'cash';
            const methodLabel = PAY_METHODS.find(m => m.key === method)?.label || '';

            return (
              <div
                key={split.split_no}
                style={{
                  background: C.card,
                  border: `1px solid ${isPaid ? C.green : isActive ? C.accent : C.border}`,
                  borderRadius: 12,
                  marginBottom: 10,
                  overflow: 'hidden',
                  transition: 'border-color 0.2s',
                }}
              >
                {/* 行头：份数 + 金额 + 状态 */}
                <button
                  onClick={() => {
                    if (isPaid) return;
                    setActiveSplit(isActive ? null : split.split_no);
                    setSettleError('');
                  }}
                  disabled={isPaid}
                  style={{
                    width: '100%',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '14px 16px', minHeight: 60,
                    background: 'transparent', border: 'none', color: C.white,
                    cursor: isPaid ? 'default' : 'pointer',
                  }}
                >
                  {/* 左侧：序号圆圈 + 标签 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: '50%',
                      background: isPaid ? C.greenDim : isActive ? C.accentDim : C.border,
                      border: `1px solid ${isPaid ? C.green : isActive ? C.accent : C.border}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 14, fontWeight: 700,
                      color: isPaid ? C.green : isActive ? C.accent : C.muted,
                      flexShrink: 0,
                    }}>
                      {isPaid ? '✓' : split.split_no}
                    </div>
                    <div>
                      <div style={{ fontSize: 17, fontWeight: 600 }}>
                        第 {split.split_no} 份
                        {isLast && splits.length > 1 && (
                          <span style={{ fontSize: 13, color: C.muted, marginLeft: 6 }}>
                            (含尾差)
                          </span>
                        )}
                      </div>
                      {isPaid && (
                        <div style={{ fontSize: 13, color: C.green, marginTop: 2 }}>
                          已收款 · {methodLabel}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 右侧：金额 + 展开箭头 */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{
                      fontSize: 20, fontWeight: 700,
                      color: isPaid ? C.green : C.accent,
                    }}>
                      {fen2yuan(split.amount_fen)}
                    </span>
                    {!isPaid && (
                      <span style={{ fontSize: 16, color: C.muted }}>
                        {isActive ? '▲' : '▼'}
                      </span>
                    )}
                  </div>
                </button>

                {/* 展开区：选支付方式 + 收款按钮 */}
                {isActive && !isPaid && (
                  <div style={{ padding: '0 16px 16px' }}>
                    <div style={{
                      borderTop: `1px solid ${C.border}`,
                      paddingTop: 12,
                    }}>
                      <div style={{ fontSize: 14, color: C.muted, marginBottom: 4 }}>
                        选择支付方式
                      </div>
                      <PayMethodPicker
                        selected={method}
                        onChange={key =>
                          setPayMethods(prev => ({ ...prev, [split.split_no]: key }))
                        }
                      />
                      <button
                        onClick={() => handleSettle(split.split_no)}
                        disabled={isSettling}
                        style={{
                          width: '100%', minHeight: 52, marginTop: 12,
                          borderRadius: 10, background: C.accent, color: C.white,
                          border: 'none', fontSize: 17, fontWeight: 700,
                          cursor: isSettling ? 'default' : 'pointer',
                          opacity: isSettling ? 0.7 : 1,
                          transition: 'opacity 0.15s',
                        }}
                      >
                        {isSettling
                          ? '收款中…'
                          : `收款 ${fen2yuan(split.amount_fen)} · ${methodLabel}`}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // ─── Step 1: 选份数界面 ───────────────────────────────────
  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
      {NavBar}

      <div style={{ padding: '20px 16px' }}>

        {/* 订单金额卡片 */}
        <div style={{
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 14, padding: '18px 20px',
          marginBottom: 24,
        }}>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 6 }}>订单总金额</div>
          {loadingOrder ? (
            <div style={{ fontSize: 16, color: C.muted }}>加载中…</div>
          ) : orderError ? (
            <div style={{ fontSize: 15, color: C.red }}>{orderError}</div>
          ) : (
            <div style={{ fontSize: 34, fontWeight: 800, color: C.accent, letterSpacing: '-0.5px' }}>
              {totalFen !== null ? fen2yuan(totalFen) : '—'}
            </div>
          )}
        </div>

        {/* 份数选择 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 14 }}>
            选择分摊份数
          </div>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 10,
          }}>
            {[2, 3, 4, 5, 6].map(n => {
              const isSelected = splitCount === n;
              return (
                <button
                  key={n}
                  onClick={() => setSplitCount(n)}
                  style={{
                    minHeight: 72,
                    borderRadius: 14,
                    border: isSelected
                      ? `2px solid ${C.accent}`
                      : `1px solid ${C.border}`,
                    background: isSelected ? C.accentDim : C.card,
                    color: isSelected ? C.accent : C.text,
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 4,
                    transition: 'all 0.15s',
                  }}
                >
                  <span style={{
                    fontSize: 28, fontWeight: 800,
                    color: isSelected ? C.accent : C.white,
                  }}>
                    {n}
                  </span>
                  <span style={{ fontSize: 13, color: C.muted }}>份</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* 每份金额预估 */}
        {totalFen !== null && perAmounts !== null && (
          <div style={{
            background: C.card,
            border: `1px solid ${C.accentBorder}`,
            borderRadius: 14, padding: '16px 20px',
            marginBottom: 32,
          }}>
            <div style={{ fontSize: 14, color: C.muted, marginBottom: 10 }}>
              金额分摊预览（尾差自动加到最后一份）
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {perAmounts.map((amount, idx) => {
                const isLast = idx === perAmounts.length - 1;
                return (
                  <div
                    key={idx}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      fontSize: 16,
                    }}
                  >
                    <span style={{ color: C.text }}>
                      第 {idx + 1} 份
                      {isLast && splitCount > 1 && (
                        <span style={{ fontSize: 13, color: C.muted, marginLeft: 6 }}>
                          (含尾差)
                        </span>
                      )}
                    </span>
                    <span style={{ fontWeight: 700, color: C.accent }}>
                      {fen2yuan(amount)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 错误提示 */}
        {initError && (
          <div style={{
            marginBottom: 16, padding: '12px 14px',
            background: 'rgba(239,68,68,0.1)',
            border: `1px solid ${C.red}`,
            borderRadius: 10, fontSize: 15, color: C.red,
          }}>
            {initError}
          </div>
        )}

        {/* 开始分摊按钮 */}
        <button
          onClick={handleStartSplit}
          disabled={initLoading || loadingOrder || totalFen === null || !!orderError}
          style={{
            width: '100%', minHeight: 56,
            borderRadius: 14, background: C.accent, color: C.white,
            border: 'none', fontSize: 18, fontWeight: 700,
            cursor: (initLoading || loadingOrder || totalFen === null || !!orderError)
              ? 'not-allowed' : 'pointer',
            opacity: (initLoading || loadingOrder || totalFen === null || !!orderError) ? 0.6 : 1,
            transition: 'opacity 0.15s',
          }}
        >
          {initLoading ? '初始化中…' : `开始 ${splitCount} 份 AA 分摊`}
        </button>
      </div>
    </div>
  );
}
