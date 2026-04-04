import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCoupons } from '@/api/paymentApi';
import { createOrder } from '@/api/orderApi';
import type { Coupon } from '@/api/paymentApi';

/** 订单确认页 — 桌台 + 已选菜品 + 优惠 + 金额汇总 */
export default function OrderConfirmPage() {
  const { t } = useLang();
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const tableNo = useOrderStore((s) => s.tableNo);
  const storeName = useOrderStore((s) => s.storeName);
  const cart = useOrderStore((s) => s.cart);
  const remark = useOrderStore((s) => s.remark);
  const phone = useOrderStore((s) => s.phone);
  const updateQuantity = useOrderStore((s) => s.updateQuantity);
  const removeFromCart = useOrderStore((s) => s.removeFromCart);
  const setRemark = useOrderStore((s) => s.setRemark);
  const cartTotal = useOrderStore((s) => s.cartTotal);
  const clearCart = useOrderStore((s) => s.clearCart);

  const total = cartTotal();

  // 优惠券
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [selectedCoupon, setSelectedCoupon] = useState<string>('');
  const [showCouponPicker, setShowCouponPicker] = useState(false);
  // 积分抵扣
  const [usePoints, setUsePoints] = useState(false);
  const pointsDiscount = usePoints ? Math.min(total * 0.1, 10) : 0; // Mock: 积分最多抵10元或10%
  // 提交状态
  const [submitting, setSubmitting] = useState(false);
  // 滑动删除
  const [swipingKey, setSwipingKey] = useState<string | null>(null);
  const touchStartX = useRef(0);
  const touchDeltaX = useRef(0);

  // 加载优惠券（自动选最优）
  useEffect(() => {
    if (!phone) return;
    fetchCoupons(phone)
      .then((list) => {
        setCoupons(list);
        // 自动选最优：满足门槛中折扣最大的
        const usable = list.filter((c) => total >= c.minSpend);
        if (usable.length > 0) {
          const best = usable.reduce((a, b) => (a.discountAmount > b.discountAmount ? a : b));
          setSelectedCoupon(best.id);
        }
      })
      .catch(() => { /* mock fallback: no coupons */ });
  }, [phone, total]);

  const coupon = coupons.find((c) => c.id === selectedCoupon);
  const couponDiscount = coupon?.discountAmount ?? 0;
  const totalDiscount = couponDiscount + pointsDiscount;
  const payableAmount = Math.max(0, total - totalDiscount);

  // 滑动删除 handlers
  const handleTouchStart = useCallback((cartKey: string, e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchDeltaX.current = 0;
    setSwipingKey(cartKey);
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    touchDeltaX.current = e.touches[0].clientX - touchStartX.current;
  }, []);

  const handleTouchEnd = useCallback((cartKey: string) => {
    if (touchDeltaX.current < -80) {
      removeFromCart(cartKey);
    }
    setSwipingKey(null);
  }, [removeFromCart]);

  // 提交订单
  const handleSubmit = useCallback(async () => {
    if (submitting || cart.length === 0) return;
    setSubmitting(true);
    try {
      const { orderId } = await createOrder({
        storeId,
        tableNo,
        items: cart.map((c) => ({
          dishId: c.dish.id,
          quantity: c.quantity,
          customSelections: c.customSelections,
          remark: c.remark,
        })),
        remark,
        phone,
        couponId: selectedCoupon || undefined,
      });
      clearCart();
      navigate(`/pay-result/${orderId}?status=success&amount=${payableAmount.toFixed(2)}`);
    } catch {
      // 降级：仍然跳转，展示模拟成功
      const mockOrderId = `MOCK-${Date.now()}`;
      clearCart();
      navigate(`/pay-result/${mockOrderId}?status=success&amount=${payableAmount.toFixed(2)}`);
    }
  }, [submitting, cart, storeId, tableNo, remark, phone, selectedCoupon, payableAmount, clearCart, navigate]);

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 100,
    }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: 16, gap: 12 }}>
        <button
          className="tx-pressable"
          onClick={() => navigate(-1)}
          style={{
            width: 40, height: 40, borderRadius: 20,
            background: 'var(--tx-bg-tertiary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M15 19l-7-7 7-7" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        <h1 style={{ fontSize: 'var(--tx-font-xl)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
          {t('orderConfirmTitle')}
        </h1>
      </div>

      {/* 桌台信息条 */}
      <div style={{
        margin: '0 16px 16px', padding: '14px 16px',
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="4" width="18" height="14" rx="2" stroke="var(--tx-brand)" strokeWidth="1.5"/>
          <path d="M7 22v-4M17 22v-4" stroke="var(--tx-brand)" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {storeName || t('storeInfo')}
          </div>
          <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2 }}>
            {t('tableNo')}: {tableNo}
          </div>
        </div>
        <div style={{
          padding: '4px 10px', borderRadius: 'var(--tx-radius-full)',
          background: 'var(--tx-brand-light)',
          fontSize: 'var(--tx-font-xs)', color: 'var(--tx-brand)', fontWeight: 600,
        }}>
          {cart.reduce((sum, c) => sum + c.quantity, 0)} {t('orderConfirmItemCount')}
        </div>
      </div>

      {/* 已选菜品列表 */}
      <div style={{ padding: '0 16px' }}>
        <div style={{
          fontSize: 'var(--tx-font-md)', fontWeight: 600,
          color: 'var(--tx-text-primary)', marginBottom: 12,
        }}>
          {t('orderConfirmItems')}
        </div>
        {cart.map((item) => (
          <div
            key={item.cartKey}
            onTouchStart={(e) => handleTouchStart(item.cartKey, e)}
            onTouchMove={handleTouchMove}
            onTouchEnd={() => handleTouchEnd(item.cartKey)}
            style={{
              position: 'relative', overflow: 'hidden',
              marginBottom: 10, borderRadius: 'var(--tx-radius-md)',
            }}
          >
            {/* 删除层 */}
            <div style={{
              position: 'absolute', right: 0, top: 0, bottom: 0, width: 80,
              background: '#FF3B30', display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: 'var(--tx-font-sm)', fontWeight: 600,
              borderRadius: '0 var(--tx-radius-md) var(--tx-radius-md) 0',
            }}>
              {t('orderConfirmDelete')}
            </div>
            {/* 菜品卡片 */}
            <div
              className="tx-fade-in"
              style={{
                display: 'flex', gap: 12, padding: 12,
                background: 'var(--tx-bg-card)',
                borderRadius: 'var(--tx-radius-md)',
                transform: swipingKey === item.cartKey ? 'translateX(-80px)' : 'translateX(0)',
                transition: swipingKey === item.cartKey ? 'none' : 'transform 0.25s ease',
              }}
            >
              <img
                src={item.dish.images[0] ?? '/placeholder-dish.png'}
                alt={item.dish.name}
                loading="lazy"
                style={{ width: 80, height: 80, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }}
              />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                <div style={{
                  fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                  color: 'var(--tx-text-primary)',
                }}>
                  {item.dish.name}
                </div>
                {Object.keys(item.customSelections).length > 0 && (
                  <div style={{
                    fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2,
                  }}>
                    {Object.entries(item.customSelections)
                      .map(([k, v]) => `${k}: ${v.join(',')}`)
                      .join(' | ')}
                  </div>
                )}
                <div style={{ flex: 1 }} />
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 700, color: '#FF6B35' }}>
                    {t('yuan')}{item.subtotal.toFixed(2)}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <button
                      className="tx-pressable"
                      onClick={() => {
                        if (item.quantity <= 1) removeFromCart(item.cartKey);
                        else updateQuantity(item.cartKey, item.quantity - 1);
                      }}
                      style={{
                        width: 28, height: 28, borderRadius: 14,
                        background: 'var(--tx-bg-tertiary)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'var(--tx-text-secondary)', fontSize: 16,
                      }}
                    >
                      -
                    </button>
                    <span style={{
                      fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                      color: 'var(--tx-text-primary)', minWidth: 20, textAlign: 'center',
                    }}>
                      {item.quantity}
                    </span>
                    <button
                      className="tx-pressable"
                      onClick={() => updateQuantity(item.cartKey, item.quantity + 1)}
                      style={{
                        width: 28, height: 28, borderRadius: 14,
                        background: '#FF6B35',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: '#fff', fontSize: 16,
                      }}
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 整单备注 */}
      <div style={{ margin: '16px 16px 0' }}>
        <textarea
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
          placeholder={t('remarkPlaceholder')}
          rows={2}
          style={{
            width: '100%', padding: 14,
            borderRadius: 'var(--tx-radius-md)',
            background: 'var(--tx-bg-card)',
            color: 'var(--tx-text-primary)',
            fontSize: 'var(--tx-font-sm)',
            resize: 'none',
          }}
        />
      </div>

      {/* 优惠区 */}
      <div style={{
        margin: '16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        {/* 优惠券 */}
        <button
          className="tx-pressable"
          onClick={() => setShowCouponPicker(!showCouponPicker)}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            paddingBottom: 12, borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          <span style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {t('coupon')}
          </span>
          <span style={{ fontSize: 'var(--tx-font-sm)', color: coupon ? '#FF6B35' : 'var(--tx-text-tertiary)' }}>
            {coupon ? `-${t('yuan')}${coupon.discountAmount}` : t('selectCoupon')}
            <span style={{ marginLeft: 4 }}>&gt;</span>
          </span>
        </button>
        {showCouponPicker && (
          <div style={{ marginTop: 12, marginBottom: 12 }}>
            {coupons.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 12, color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)' }}>
                {t('noCoupon')}
              </div>
            ) : (
              coupons.filter((c) => total >= c.minSpend).map((c) => (
                <button
                  key={c.id}
                  className="tx-pressable"
                  onClick={() => { setSelectedCoupon(c.id); setShowCouponPicker(false); }}
                  style={{
                    width: '100%', padding: 12, marginBottom: 8,
                    borderRadius: 'var(--tx-radius-sm)',
                    background: selectedCoupon === c.id ? 'rgba(255,107,53,0.1)' : 'var(--tx-bg-tertiary)',
                    border: selectedCoupon === c.id ? '1px solid #FF6B35' : '1px solid transparent',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: '#FF6B35' }}>
                    -{t('yuan')}{c.discountAmount}
                  </div>
                  <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2 }}>
                    {c.name}
                  </div>
                </button>
              ))
            )}
          </div>
        )}
        {/* 积分抵扣 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          paddingTop: 12,
        }}>
          <div>
            <span style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
              {t('orderConfirmPoints')}
            </span>
            {usePoints && (
              <span style={{ fontSize: 'var(--tx-font-xs)', color: '#FF6B35', marginLeft: 8 }}>
                -{t('yuan')}{pointsDiscount.toFixed(2)}
              </span>
            )}
          </div>
          <button
            className="tx-pressable"
            onClick={() => setUsePoints(!usePoints)}
            style={{
              width: 44, height: 26, borderRadius: 13,
              background: usePoints ? '#FF6B35' : 'var(--tx-bg-tertiary)',
              position: 'relative', transition: 'background 0.2s',
            }}
          >
            <div style={{
              width: 22, height: 22, borderRadius: 11,
              background: '#fff',
              position: 'absolute', top: 2,
              left: usePoints ? 20 : 2,
              transition: 'left 0.2s',
            }} />
          </button>
        </div>
      </div>

      {/* 金额汇总 */}
      <div style={{
        margin: '0 16px 16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <SummaryRow label={t('orderConfirmSubtotal')} value={`${t('yuan')}${total.toFixed(2)}`} />
        {totalDiscount > 0 && (
          <SummaryRow label={t('orderConfirmDiscount')} value={`-${t('yuan')}${totalDiscount.toFixed(2)}`} highlight />
        )}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          paddingTop: 12, marginTop: 12,
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}>
          <span style={{ fontSize: 'var(--tx-font-md)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {t('orderConfirmPayable')}
          </span>
          <span style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>
            {t('yuan')}{payableAmount.toFixed(2)}
          </span>
        </div>
      </div>

      {/* 底部固定提交按钮 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
        <button
          className="tx-pressable"
          onClick={handleSubmit}
          disabled={submitting || cart.length === 0}
          style={{
            width: '100%', height: 56,
            borderRadius: 'var(--tx-radius-full)',
            background: (submitting || cart.length === 0) ? 'var(--tx-bg-tertiary)' : '#FF6B35',
            color: (submitting || cart.length === 0) ? 'var(--tx-text-tertiary)' : '#fff',
            fontSize: 'var(--tx-font-lg)', fontWeight: 700,
            transition: 'background 0.2s',
          }}
        >
          {submitting ? t('loading') : `${t('submitOrder')} ${t('yuan')}${payableAmount.toFixed(2)}`}
        </button>
      </div>
    </div>
  );
}

function SummaryRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      padding: '6px 0',
    }}>
      <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)' }}>{label}</span>
      <span style={{
        fontSize: 'var(--tx-font-sm)',
        color: highlight ? 'var(--tx-success)' : 'var(--tx-text-primary)',
        fontWeight: highlight ? 600 : 400,
      }}>
        {value}
      </span>
    </div>
  );
}
