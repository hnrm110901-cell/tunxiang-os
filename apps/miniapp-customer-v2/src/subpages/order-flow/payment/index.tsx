/**
 * order-flow/payment/index.tsx — 支付选择页（待支付订单独立支付入口）
 *
 * URL params: ?orderId=xxx
 *
 * Purpose:
 *   When a user taps "去支付" on a pending order from the order list,
 *   they land here to select a payment method and confirm payment.
 *   Unlike checkout (which creates a new order from cart), this page
 *   only handles payment for an existing pending_payment order.
 *
 * Features:
 *  - Order summary: items, store name, order number
 *  - Payment method selection: WeChat / Stored Value / Mixed
 *  - Coupon application (if not already applied)
 *  - Points deduction toggle
 *  - Price breakdown with real-time discount preview
 *  - Pay button → usePayment hook → navigate to pay-result
 *  - 15min payment countdown timer
 *  - Cancel order option
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, cancelOrder, Order } from '../../../api/trade'
import { listCoupons, Coupon } from '../../../api/growth'
import { useUserStore } from '../../../store/useUserStore'
import { usePayment, PaymentMethod } from '../../../hooks/usePayment'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B2C',
  primaryDim: 'rgba(255,107,44,0.15)',
  bgDeep:     '#0B1A20',
  bgCard:     '#132029',
  bgHover:    '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  red:        '#E53935',
  redDim:     'rgba(229,57,53,0.15)',
  success:    '#4CAF50',
  warning:    '#FFC107',
  warningDim: 'rgba(255,193,7,0.15)',
  white:      '#fff',
  disabled:   '#2A4050',
} as const

// ─── Sub-components ───────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        background:   C.bgCard,
        borderRadius: '16rpx',
        margin:       '0 24rpx 16rpx',
        overflow:     'hidden',
      }}
    >
      <View
        style={{
          padding:      '20rpx 24rpx 12rpx',
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600' }}>
          {title}
        </Text>
      </View>
      <View style={{ padding: '16rpx 24rpx 20rpx' }}>{children}</View>
    </View>
  )
}

function RadioOption({
  label,
  sublabel,
  selected,
  disabled,
  onSelect,
}: {
  label: string
  sublabel?: string
  selected: boolean
  disabled?: boolean
  onSelect: () => void
}) {
  return (
    <View
      style={{
        display:       'flex',
        flexDirection: 'row',
        alignItems:    'center',
        padding:       '16rpx 0',
        opacity:       disabled ? 0.4 : 1,
      }}
      onClick={!disabled ? onSelect : undefined}
    >
      <View
        style={{
          width:          '40rpx',
          height:         '40rpx',
          borderRadius:   '20rpx',
          border:         `2rpx solid ${selected ? C.primary : C.text3}`,
          background:     selected ? C.primary : 'transparent',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          marginRight:    '20rpx',
          flexShrink:     0,
        }}
      >
        {selected && (
          <View
            style={{
              width:        '18rpx',
              height:       '18rpx',
              borderRadius: '9rpx',
              background:   C.white,
            }}
          />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ color: disabled ? C.text3 : C.text1, fontSize: '28rpx' }}>
          {label}
        </Text>
        {sublabel && (
          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
            {sublabel}
          </Text>
        )}
      </View>
    </View>
  )
}

function PriceLine({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <View
      style={{
        display:        'flex',
        flexDirection:  'row',
        justifyContent: 'space-between',
        alignItems:     'center',
        marginBottom:   '10rpx',
      }}
    >
      <Text style={{ color: C.text2, fontSize: '26rpx' }} numberOfLines={1}>{label}</Text>
      <Text
        style={{
          color:      accent ? C.primary : C.text1,
          fontSize:   '26rpx',
          fontWeight: accent ? '600' : '400',
          marginLeft: '24rpx',
        }}
      >
        {value}
      </Text>
    </View>
  )
}

// ─── Countdown timer ──────────────────────────────────────────────────────────

function useCountdown(createdAt: string, timeoutMinutes: number): { minutes: number; seconds: number; expired: boolean } {
  const [remaining, setRemaining] = useState(0)

  useEffect(() => {
    if (!createdAt) return

    const created = new Date(createdAt).getTime()
    const deadline = created + timeoutMinutes * 60_000

    function tick() {
      const left = Math.max(0, deadline - Date.now())
      setRemaining(left)
    }

    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [createdAt, timeoutMinutes])

  const totalSeconds = Math.floor(remaining / 1000)
  return {
    minutes: Math.floor(totalSeconds / 60),
    seconds: totalSeconds % 60,
    expired: remaining <= 0,
  }
}

// ─── Spinner ──────────────────────────────────────────────────────────────────

function Spinner() {
  const [angle, setAngle] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setAngle((a) => (a + 30) % 360), 80)
    return () => clearInterval(id)
  }, [])
  return (
    <View
      style={{
        width: '48rpx', height: '48rpx', borderRadius: '50%',
        border: `4rpx solid ${C.border}`, borderTop: `4rpx solid ${C.primary}`,
        transform: `rotate(${angle}deg)`,
      }}
    />
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const PAYMENT_TIMEOUT_MINUTES = 15

export default function PaymentPage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  // ── Remote data ────────────────────────────────────────────────────────────
  const [order,   setOrder]   = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  // ── User state ─────────────────────────────────────────────────────────────
  const { storedValueFen, pointsBalance, isLoggedIn } = useUserStore()
  const { pay, isProcessing } = usePayment()

  // ── Form state ─────────────────────────────────────────────────────────────
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('wechat')
  const [usePoints,     setUsePoints]     = useState(false)
  const [cancelling,    setCancelling]    = useState(false)

  // ── Coupon state ───────────────────────────────────────────────────────────
  const [coupons,          setCoupons]          = useState<Coupon[]>([])
  const [couponsLoading,   setCouponsLoading]   = useState(false)
  const [selectedCoupon,   setSelectedCoupon]   = useState<Coupon | null>(null)
  const [couponSheetOpen,  setCouponSheetOpen]  = useState(false)
  const [couponDiscountFen, setCouponDiscountFen] = useState(0)

  // ── Load order ─────────────────────────────────────────────────────────────

  const fetchOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setError('')
    try {
      const data = await getOrder(orderId)
      if (data.status !== 'pending_payment') {
        setError('此订单已支付或已取消')
      } else {
        setOrder(data)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    void fetchOrder()
  }, [fetchOrder])

  // ── Countdown ──────────────────────────────────────────────────────────────

  const countdown = useCountdown(order?.createdAt ?? '', PAYMENT_TIMEOUT_MINUTES)

  useEffect(() => {
    if (countdown.expired && order) {
      Taro.showModal({
        title: '支付超时',
        content: '订单已超时未支付，请重新下单',
        showCancel: false,
        success: () => {
          Taro.switchTab({ url: '/pages/order/index' }).catch(() =>
            Taro.navigateBack({ delta: 1 }),
          )
        },
      })
    }
  }, [countdown.expired, order])

  // ── Pricing ────────────────────────────────────────────────────────────────

  const subtotalFen = order?.payableFen ?? 0
  const MAX_POINTS_DEDUCTION_FEN = Math.min(pointsBalance, Math.round(subtotalFen * 0.2))
  const pointsDeductFen = usePoints ? MAX_POINTS_DEDUCTION_FEN : 0
  const afterCouponFen = Math.max(0, subtotalFen - couponDiscountFen)
  const finalFen = Math.max(0, afterCouponFen - pointsDeductFen)

  const storedValueSufficient = storedValueFen >= finalFen
  const storedValueLabel = `储值卡余额 ${fenToYuanDisplay(storedValueFen)}`
  const mixedLabel = storedValueFen > 0
    ? `混合支付（储值${fenToYuanDisplay(storedValueFen)} + 微信${fenToYuanDisplay(Math.max(0, finalFen - storedValueFen))}）`
    : '混合支付（储值不足）'

  // ── Coupon ─────────────────────────────────────────────────────────────────

  async function openCouponSheet() {
    setCouponSheetOpen(true)
    if (coupons.length === 0) {
      setCouponsLoading(true)
      try {
        const list = await listCoupons('available')
        setCoupons(list)
      } catch {
        // empty list
      } finally {
        setCouponsLoading(false)
      }
    }
  }

  function handleSelectCoupon(coupon: Coupon | null) {
    setSelectedCoupon(coupon)
    setCouponSheetOpen(false)

    if (!coupon) {
      setCouponDiscountFen(0)
      return
    }

    if (coupon.type === 'discount_fen') {
      setCouponDiscountFen(subtotalFen >= coupon.minOrderFen ? coupon.discountValue : 0)
    } else if (coupon.type === 'discount_percent') {
      setCouponDiscountFen(
        subtotalFen >= coupon.minOrderFen
          ? Math.round(subtotalFen * (1 - coupon.discountValue / 100))
          : 0,
      )
    } else {
      setCouponDiscountFen(0)
    }
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async function handlePay() {
    if (!order || !isLoggedIn || isProcessing) return

    const payResult = await pay(order.orderId, paymentMethod)

    if (payResult.success) {
      Taro.redirectTo({
        url: `/subpages/order-flow/pay-result/index?orderId=${encodeURIComponent(order.orderId)}&status=success`,
      })
    } else {
      Taro.redirectTo({
        url: `/subpages/order-flow/pay-result/index?orderId=${encodeURIComponent(order.orderId)}&status=failed&errorCode=${payResult.errorCode ?? ''}&errorMessage=${encodeURIComponent(payResult.errorMessage ?? '支付失败')}`,
      })
    }
  }

  async function handleCancel() {
    if (!order || cancelling) return
    const res = await Taro.showModal({ title: '取消订单', content: '确定要取消这笔订单吗？' })
    if (!res.confirm) return

    setCancelling(true)
    try {
      await cancelOrder(order.orderId)
      Taro.showToast({ title: '订单已取消', icon: 'success' })
      setTimeout(() => Taro.navigateBack({ delta: 1 }), 800)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '取消失败'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setCancelling(false)
    }
  }

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <View
        style={{
          minHeight: '100vh', background: C.bgDeep,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: '24rpx',
        }}
      >
        <Spinner />
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>加载订单中...</Text>
      </View>
    )
  }

  if (error || !order) {
    return (
      <View
        style={{
          minHeight: '100vh', background: C.bgDeep,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: '24rpx', padding: '48rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx' }}>😕</Text>
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
          {error || '订单不存在'}
        </Text>
        <View
          onClick={() => Taro.navigateBack({ delta: 1 })}
          style={{ background: C.primary, borderRadius: '40rpx', padding: '16rpx 48rpx' }}
        >
          <Text style={{ color: C.white, fontSize: '28rpx' }}>返回</Text>
        </View>
      </View>
    )
  }

  const isSubmitting = isProcessing || cancelling

  // ── Main render ────────────────────────────────────────────────────────────

  return (
    <View
      style={{
        minHeight:     '100vh',
        background:    C.bgDeep,
        paddingBottom: 'calc(200rpx + env(safe-area-inset-bottom))',
      }}
    >
      {/* Page header */}
      <View style={{ padding: '24rpx 32rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          订单支付
        </Text>
      </View>

      {/* Countdown timer */}
      {!countdown.expired && (
        <View
          style={{
            background:   C.warningDim,
            margin:       '0 24rpx 16rpx',
            borderRadius: '16rpx',
            padding:      '16rpx 24rpx',
            display:      'flex',
            flexDirection: 'row',
            alignItems:   'center',
            gap:          '12rpx',
          }}
        >
          <Text style={{ color: C.warning, fontSize: '28rpx' }}>
            ⏰
          </Text>
          <Text style={{ color: C.warning, fontSize: '26rpx', flex: 1 }}>
            请在{' '}
            <Text style={{ fontWeight: '700' }}>
              {String(countdown.minutes).padStart(2, '0')}:{String(countdown.seconds).padStart(2, '0')}
            </Text>
            {' '}内完成支付
          </Text>
        </View>
      )}

      <ScrollView scrollY style={{ flex: 1 }}>
        {/* ── Order summary ── */}
        <Section title={`订单 #${order.orderNo.slice(-6).toUpperCase()}`}>
          <View style={{ marginBottom: '8rpx' }}>
            <Text style={{ color: C.text2, fontSize: '24rpx' }}>{order.storeName}</Text>
          </View>
          {order.items.slice(0, 4).map((item, i) => (
            <View
              key={`${item.dishId}-${i}`}
              style={{
                display: 'flex', flexDirection: 'row', alignItems: 'center',
                justifyContent: 'space-between', paddingVertical: '6rpx',
              }}
            >
              <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1 }} numberOfLines={1}>
                {item.dishName}
                {item.specName ? ` (${item.specName})` : ''}
              </Text>
              <Text style={{ color: C.text2, fontSize: '24rpx', marginLeft: '16rpx' }}>x{item.quantity}</Text>
              <Text style={{ color: C.text1, fontSize: '26rpx', marginLeft: '16rpx', minWidth: '100rpx', textAlign: 'right' }}>
                {fenToYuanDisplay(item.totalPriceFen)}
              </Text>
            </View>
          ))}
          {order.items.length > 4 && (
            <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '8rpx' }}>
              ...等{order.items.length}种菜品
            </Text>
          )}
        </Section>

        {/* ── Coupon row ── */}
        <Section title="优惠券">
          <View
            style={{
              display: 'flex', flexDirection: 'row', alignItems: 'center', padding: '8rpx 0',
            }}
            onClick={openCouponSheet}
          >
            <Text style={{ fontSize: '28rpx', marginRight: '12rpx' }}>🎟</Text>
            <Text style={{ color: C.text1, fontSize: '28rpx', flex: 1 }}>
              {selectedCoupon ? `已选：${selectedCoupon.name}` : '选择优惠券'}
            </Text>
            {selectedCoupon ? (
              <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
                -{fenToYuanDisplay(couponDiscountFen)}
              </Text>
            ) : (
              <Text style={{ color: C.text2, fontSize: '26rpx' }}>选择 ›</Text>
            )}
          </View>
        </Section>

        {/* ── Points deduction ── */}
        {isLoggedIn && pointsBalance > 0 && (
          <Section title="积分抵扣">
            <View
              style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }}
              onClick={() => setUsePoints(!usePoints)}
            >
              <View
                style={{
                  width: '40rpx', height: '40rpx', borderRadius: '8rpx',
                  border: `2rpx solid ${usePoints ? C.primary : C.text3}`,
                  background: usePoints ? C.primary : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginRight: '20rpx', flexShrink: 0,
                }}
              >
                {usePoints && (
                  <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '700' }}>✓</Text>
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: C.text1, fontSize: '28rpx' }}>
                  使用积分抵扣{' '}
                  <Text style={{ color: C.primary }}>{fenToYuanDisplay(MAX_POINTS_DEDUCTION_FEN)}</Text>
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                  可用积分：{pointsBalance}分（最多抵扣20%）
                </Text>
              </View>
            </View>
          </Section>
        )}

        {/* ── Payment method ── */}
        <Section title="支付方式">
          <RadioOption
            label="微信支付"
            selected={paymentMethod === 'wechat'}
            onSelect={() => setPaymentMethod('wechat')}
          />
          <View style={{ height: '1rpx', background: C.border }} />
          <RadioOption
            label={storedValueLabel}
            disabled={!storedValueSufficient || storedValueFen === 0}
            sublabel={!storedValueSufficient && storedValueFen > 0 ? '余额不足' : undefined}
            selected={paymentMethod === 'stored_value'}
            onSelect={() => setPaymentMethod('stored_value')}
          />
          {storedValueFen > 0 && (
            <>
              <View style={{ height: '1rpx', background: C.border }} />
              <RadioOption
                label={mixedLabel}
                disabled={storedValueFen === 0}
                selected={paymentMethod === 'mixed'}
                onSelect={() => setPaymentMethod('mixed')}
              />
            </>
          )}
        </Section>

        {/* ── Price breakdown ── */}
        <View
          style={{
            background: C.bgCard, borderRadius: '16rpx',
            margin: '0 24rpx 16rpx', padding: '20rpx 24rpx',
          }}
        >
          <PriceLine label="商品合计" value={fenToYuanDisplay(subtotalFen)} />
          {couponDiscountFen > 0 && (
            <PriceLine
              label={`优惠券（${selectedCoupon?.name ?? ''}）`}
              value={`-${fenToYuanDisplay(couponDiscountFen)}`}
              accent
            />
          )}
          {pointsDeductFen > 0 && (
            <PriceLine
              label={`积分抵扣（${MAX_POINTS_DEDUCTION_FEN}分）`}
              value={`-${fenToYuanDisplay(pointsDeductFen)}`}
              accent
            />
          )}
          <View style={{ height: '1rpx', background: C.border, margin: '12rpx 0' }} />
          <View
            style={{
              display: 'flex', flexDirection: 'row',
              justifyContent: 'space-between', alignItems: 'baseline',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>实付</Text>
            <Text style={{ color: C.primary, fontSize: '44rpx', fontWeight: '800' }}>
              {fenToYuanDisplay(finalFen)}
            </Text>
          </View>
        </View>

      </ScrollView>

      {/* ── Bottom CTA ── */}
      <View
        style={{
          position: 'fixed', left: 0, right: 0, bottom: 0,
          background: C.bgCard, borderTop: `1rpx solid ${C.border}`,
          padding: '16rpx 24rpx', paddingBottom: 'calc(16rpx + env(safe-area-inset-bottom))',
          zIndex: 100,
        }}
      >
        {/* Price row */}
        <View
          style={{
            display: 'flex', flexDirection: 'row', alignItems: 'center',
            justifyContent: 'space-between', marginBottom: '12rpx',
          }}
        >
          <Text
            style={{ color: C.text3, fontSize: '24rpx' }}
            onClick={handleCancel}
          >
            {cancelling ? '取消中...' : '取消订单'}
          </Text>
          <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(finalFen)}
          </Text>
        </View>
        {/* Pay button */}
        <View
          style={{
            background:     isSubmitting ? C.disabled : C.primary,
            borderRadius:   '44rpx',
            height:         '88rpx',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            opacity:        isSubmitting ? 0.7 : 1,
          }}
          onClick={isSubmitting ? undefined : handlePay}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {isProcessing ? '支付中...' : '确认支付'}
          </Text>
        </View>
      </View>

      {/* ── Coupon Sheet (simplified) ── */}
      {couponSheetOpen && (
        <View
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
          }}
        >
          <View
            style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }}
            onClick={() => setCouponSheetOpen(false)}
          />
          <View
            style={{
              position: 'relative', background: C.bgCard,
              borderRadius: '24rpx 24rpx 0 0', maxHeight: '75vh',
              display: 'flex', flexDirection: 'column',
            }}
          >
            {/* Handle */}
            <View style={{ display: 'flex', justifyContent: 'center', padding: '16rpx 0 0' }}>
              <View style={{ width: '64rpx', height: '8rpx', borderRadius: '4rpx', background: C.border }} />
            </View>

            {/* Title */}
            <View
              style={{
                display: 'flex', flexDirection: 'row', alignItems: 'center',
                justifyContent: 'space-between', padding: '20rpx 32rpx 16rpx',
              }}
            >
              <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>优惠券</Text>
              <Text
                style={{ color: C.text2, fontSize: '28rpx', padding: '8rpx' }}
                onClick={() => setCouponSheetOpen(false)}
              >
                关闭
              </Text>
            </View>

            {/* "Not using coupon" option */}
            <View
              style={{
                padding: '20rpx 32rpx', borderBottom: `1rpx solid ${C.border}`,
                background: selectedCoupon === null ? C.primaryDim : 'transparent',
              }}
              onClick={() => handleSelectCoupon(null)}
            >
              <Text style={{ color: selectedCoupon === null ? C.primary : C.text2, fontSize: '28rpx' }}>
                不使用优惠券
              </Text>
            </View>

            <ScrollView scrollY style={{ flex: 1, padding: '0 24rpx 32rpx' }}>
              {couponsLoading ? (
                <View style={{ padding: '48rpx', textAlign: 'center' }}>
                  <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
                </View>
              ) : coupons.length === 0 ? (
                <View style={{ padding: '48rpx', textAlign: 'center' }}>
                  <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无优惠券</Text>
                </View>
              ) : (
                coupons
                  .filter((c) => c.status === 'available')
                  .map((coupon) => {
                    const isSelected = selectedCoupon?.couponId === coupon.couponId
                    const canUse = coupon.minOrderFen <= subtotalFen
                    return (
                      <View
                        key={coupon.couponId}
                        style={{
                          display: 'flex', flexDirection: 'row', alignItems: 'center',
                          background: isSelected ? C.primaryDim : C.bgDeep,
                          border: `2rpx solid ${isSelected ? C.primary : C.border}`,
                          borderRadius: '16rpx', padding: '20rpx 24rpx',
                          marginTop: '16rpx', opacity: canUse ? 1 : 0.45,
                        }}
                        onClick={() => canUse && handleSelectCoupon(isSelected ? null : coupon)}
                      >
                        <View
                          style={{
                            background: canUse ? C.primary : C.disabled,
                            borderRadius: '12rpx', padding: '8rpx 16rpx',
                            marginRight: '20rpx', minWidth: '100rpx', alignItems: 'center',
                          }}
                        >
                          <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700', textAlign: 'center' }}>
                            {coupon.type === 'discount_fen'
                              ? `减${fenToYuanDisplay(coupon.discountValue)}`
                              : coupon.type === 'discount_percent'
                              ? `${coupon.discountValue}折`
                              : '优惠'}
                          </Text>
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500' }} numberOfLines={1}>
                            {coupon.name}
                          </Text>
                          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                            满{fenToYuanDisplay(coupon.minOrderFen)}可用 · {coupon.validUntil.slice(0, 10)}到期
                          </Text>
                        </View>
                        <View
                          style={{
                            width: '40rpx', height: '40rpx', borderRadius: '20rpx',
                            border: `2rpx solid ${isSelected ? C.primary : C.text3}`,
                            background: isSelected ? C.primary : 'transparent',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                          }}
                        >
                          {isSelected && (
                            <Text style={{ color: C.white, fontSize: '20rpx', lineHeight: '1' }}>✓</Text>
                          )}
                        </View>
                      </View>
                    )
                  })
              )}
            </ScrollView>
          </View>
        </View>
      )}
    </View>
  )
}
