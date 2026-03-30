import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { createOrder } from '@/api/orderApi';
import { fetchCoupons, initiatePayment, queryPaymentStatus } from '@/api/paymentApi';
import type { PayMethod, Coupon } from '@/api/paymentApi';

const PAY_METHODS: { key: PayMethod; icon: string }[] = [
  { key: 'wechat', icon: '💬' },
  { key: 'alipay', icon: '🅰️' },
  { key: 'unionpay', icon: '💳' },
];

/** 结账页 — 支付方式 + 优惠券 + 会员价 */
export default function Checkout() {
  const { t } = useLang();
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const tableNo = useOrderStore((s) => s.tableNo);
  const cart = useOrderStore((s) => s.cart);
  const remark = useOrderStore((s) => s.remark);
  const phone = useOrderStore((s) => s.phone);
  const setPhone = useOrderStore((s) => s.setPhone);
  const cartTotal = useOrderStore((s) => s.cartTotal);
  const clearCart = useOrderStore((s) => s.clearCart);

  const total = cartTotal();
  const [payMethod, setPayMethod] = useState<PayMethod>('wechat');
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [selectedCoupon, setSelectedCoupon] = useState<string>('');
  const [showCouponPicker, setShowCouponPicker] = useState(false);
  const [paying, setPaying] = useState(false);
  const [needPhone, setNeedPhone] = useState(!phone);
  const [verifyCodeSent, setVerifyCodeSent] = useState(false);

  // 加载优惠券
  useEffect(() => {
    if (phone) {
      fetchCoupons(phone).then(setCoupons).catch(() => { /* ignore */ });
    }
  }, [phone]);

  // 计算优惠后金额
  const coupon = coupons.find((c) => c.id === selectedCoupon);
  const discountAmount = coupon?.discountAmount ?? 0;
  const payableAmount = Math.max(0, total - discountAmount);

  // 发送验证码
  const handleSendCode = () => {
    if (!phone || phone.length < 11) return;
    setVerifyCodeSent(true);
    // API: sendVerifyCode(phone) — 略
  };

  // 确认手机号
  const handlePhoneConfirm = () => {
    if (phone.length >= 11) {
      setNeedPhone(false);
    }
  };

  // 支付
  const handlePay = useCallback(async () => {
    if (!phone) { setNeedPhone(true); return; }
    setPaying(true);
    try {
      // 1. 创建订单
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

      // 2. 发起支付
      const payResult = await initiatePayment({
        orderId,
        method: payMethod,
        couponId: selectedCoupon || undefined,
        phone,
      });

      // 3. 处理支付结果
      if (payResult.redirectUrl) {
        // 支付宝/银联 H5 跳转
        window.location.href = payResult.redirectUrl;
        return;
      }

      if (payResult.wechatPayParams && typeof (window as any).WeixinJSBridge !== 'undefined') {
        // 微信 JSAPI 支付
        (window as any).WeixinJSBridge.invoke(
          'getBrandWCPayRequest',
          payResult.wechatPayParams,
          () => { /* 支付回调 */ },
        );
      }

      // 4. 轮询支付状态
      const pollStatus = async () => {
        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const { status } = await queryPaymentStatus(payResult.paymentId);
          if (status === 'success') {
            clearCart();
            navigate(`/order/${orderId}/track`);
            return;
          }
          if (status === 'failed') {
            setPaying(false);
            return;
          }
        }
        setPaying(false);
      };
      pollStatus();
    } catch {
      setPaying(false);
    }
  }, [phone, storeId, tableNo, cart, remark, selectedCoupon, payMethod, clearCart, navigate]);

  const payMethodLabel: Record<PayMethod, string> = {
    wechat: t('wechatPay'),
    alipay: t('alipay'),
    unionpay: t('unionPay'),
  };

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 120,
    }}>
      {/* 顶部 */}
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
          {t('checkoutTitle')}
        </h1>
      </div>

      {/* 手机号输入 */}
      {needPhone && (
        <div style={{
          margin: '0 16px 16px', padding: 16,
          borderRadius: 'var(--tx-radius-md)',
          background: 'var(--tx-bg-card)',
        }}>
          <div style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)', marginBottom: 10 }}>
            {t('phoneRequired')}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder={t('phonePlaceholder')}
              maxLength={11}
              style={{
                flex: 1, height: 48, padding: '0 14px',
                borderRadius: 'var(--tx-radius-md)',
                background: 'var(--tx-bg-tertiary)',
                color: 'var(--tx-text-primary)',
                fontSize: 'var(--tx-font-md)',
              }}
            />
            <button
              className="tx-pressable"
              onClick={verifyCodeSent ? handlePhoneConfirm : handleSendCode}
              style={{
                padding: '0 16px', height: 48,
                borderRadius: 'var(--tx-radius-md)',
                background: 'var(--tx-brand)', color: '#fff',
                fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              {verifyCodeSent ? t('confirm') : t('getVerifyCode')}
            </button>
          </div>
        </div>
      )}

      {/* 支付方式 */}
      <div style={{
        margin: '0 16px 16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <div style={{ fontSize: 'var(--tx-font-md)', fontWeight: 600, color: 'var(--tx-text-primary)', marginBottom: 12 }}>
          {t('payMethod')}
        </div>
        {PAY_METHODS.map((pm) => (
          <button
            key={pm.key}
            className="tx-pressable"
            onClick={() => setPayMethod(pm.key)}
            style={{
              width: '100%', display: 'flex', alignItems: 'center',
              padding: '14px 0', gap: 12,
              borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}
          >
            <span style={{ fontSize: 24 }}>{pm.icon}</span>
            <span style={{ flex: 1, textAlign: 'left', fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-primary)' }}>
              {payMethodLabel[pm.key]}
            </span>
            <div style={{
              width: 22, height: 22, borderRadius: 11,
              border: payMethod === pm.key ? '6px solid var(--tx-brand)' : '2px solid var(--tx-text-tertiary)',
              transition: 'border 0.15s',
            }} />
          </button>
        ))}
      </div>

      {/* 优惠券 */}
      <div style={{
        margin: '0 16px 16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <button
          className="tx-pressable"
          onClick={() => setShowCouponPicker(!showCouponPicker)}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 'var(--tx-font-md)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {t('coupon')}
          </span>
          <span style={{ fontSize: 'var(--tx-font-sm)', color: coupon ? 'var(--tx-brand)' : 'var(--tx-text-tertiary)' }}>
            {coupon ? `-${t('yuan')}${coupon.discountAmount}` : t('selectCoupon')}
          </span>
        </button>
        {showCouponPicker && (
          <div style={{ marginTop: 12 }}>
            {coupons.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 16, color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)' }}>
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
                    background: selectedCoupon === c.id ? 'var(--tx-brand-light)' : 'var(--tx-bg-tertiary)',
                    border: selectedCoupon === c.id ? '1px solid var(--tx-brand)' : '1px solid transparent',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-brand)' }}>
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
      </div>

      {/* 金额明细 */}
      <div style={{
        margin: '0 16px 16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <Row label={t('total')} value={`${t('yuan')}${total.toFixed(2)}`} />
        {discountAmount > 0 && (
          <Row label={t('discount')} value={`-${t('yuan')}${discountAmount.toFixed(2)}`} highlight />
        )}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          paddingTop: 12, marginTop: 12,
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}>
          <span style={{ fontSize: 'var(--tx-font-md)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {t('payNow')}
          </span>
          <span style={{ fontSize: 'var(--tx-font-xxl)', fontWeight: 700, color: 'var(--tx-brand)' }}>
            {t('yuan')}{payableAmount.toFixed(2)}
          </span>
        </div>
      </div>

      {/* 底部支付按钮 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
        <button
          className="tx-pressable"
          onClick={handlePay}
          disabled={paying}
          style={{
            width: '100%', height: 54,
            borderRadius: 'var(--tx-radius-full)',
            background: paying ? 'var(--tx-bg-tertiary)' : 'var(--tx-brand)',
            color: paying ? 'var(--tx-text-tertiary)' : '#fff',
            fontSize: 'var(--tx-font-lg)', fontWeight: 700,
            transition: 'background 0.2s',
          }}
        >
          {paying ? t('loading') : `${t('payNow')} ${t('yuan')}${payableAmount.toFixed(2)}`}
        </button>
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
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
