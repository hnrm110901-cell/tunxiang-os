/**
 * checkout/index.tsx — 结账确认页
 *
 * Features:
 *  - Read-only order items summary
 *  - 用餐方式: 堂食 / 外带 / 预约
 *  - 整单备注 textarea
 *  - 优惠券 picker row → coupon half-sheet
 *  - 积分抵扣 row (checkbox)
 *  - Payment method: 微信支付 / 储值卡 / 混合支付
 *  - Price breakdown
 *  - "提交订单" → createCartOrder → payOrder → navigate to pay-result
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Textarea } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useCartStore } from '../../../store/useCartStore'
import { useUserStore } from '../../../store/useUserStore'
import { useOrderStore } from '../../../store/useOrderStore'
import { createCartOrder, payOrder, applyCoupon } from '../../../api/trade'
import { listCoupons, Coupon } from '../../../api/growth'
import { fenToYuanDisplay } from '../../../utils/format'
import { usePayment, PaymentMethod } from '../../../hooks/usePayment'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B2C',
  primaryDark: '#E55A1F',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  success: '#4CAF50',
  white: '#fff',
  disabled: '#2A4050',
} as const

type DineMode = 'dine-in' | 'takeaway' | 'reservation'

const DINE_MODES: { value: DineMode; label: string; icon: string }[] = [
  { value: 'dine-in', label: '堂食', icon: '🍽' },
  { value: 'takeaway', label: '外带', icon: '🥡' },
  { value: 'reservation', label: '预约', icon: '📅' },
]

// ─── Coupon Sheet ─────────────────────────────────────────────────────────────

interface CouponSheetProps {
  visible: boolean
  coupons: Coupon[]
  loading: boolean
  selectedId: string | null
  orderTotalFen: number
  onSelect: (coupon: Coupon | null) => void
  onClose: () => void
}

function CouponSheet({
  visible,
  coupons,
  loading,
  selectedId,
  orderTotalFen,
  onSelect,
  onClose,
}: CouponSheetProps) {
  if (!visible) return null

  const available = coupons.filter(
    (c) => c.status === 'available' && c.minOrderFen <= orderTotalFen,
  )
  const unavailable = coupons.filter(
    (c) => c.status === 'available' && c.minOrderFen > orderTotalFen,
  )

  function couponValueLabel(c: Coupon): string {
    if (c.type === 'discount_fen') return `减${fenToYuanDisplay(c.discountValue)}`
    if (c.type === 'discount_percent') return `${c.discountValue}折`
    if (c.type === 'free_item') return '免费菜品'
    return '优惠'
  }

  function renderCoupon(coupon: Coupon, dimmed?: boolean) {
    const isSelected = selectedId === coupon.couponId
    return (
      <View
        key={coupon.couponId}
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          background: isSelected ? 'rgba(255,107,44,0.12)' : C.bgDeep,
          border: `2rpx solid ${isSelected ? C.primary : C.border}`,
          borderRadius: '16rpx',
          padding: '20rpx 24rpx',
          marginBottom: '16rpx',
          opacity: dimmed ? 0.45 : 1,
        }}
        onClick={() => !dimmed && onSelect(isSelected ? null : coupon)}
      >
        <View
          style={{
            background: dimmed ? C.disabled : C.primary,
            borderRadius: '12rpx',
            padding: '8rpx 16rpx',
            marginRight: '20rpx',
            minWidth: '100rpx',
            alignItems: 'center',
          }}
        >
          <Text
            style={{
              color: C.white,
              fontSize: '28rpx',
              fontWeight: '700',
              textAlign: 'center',
            }}
          >
            {couponValueLabel(coupon)}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500' }} numberOfLines={1}>
            {coupon.name}
          </Text>
          <Text style={{ color: C.text2, fontSize: '22rpx', marginTop: '6rpx' }}>
            满{fenToYuanDisplay(coupon.minOrderFen)}可用
          </Text>
          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
            {coupon.validUntil.slice(0, 10)} 到期
          </Text>
        </View>
        <View
          style={{
            width: '40rpx',
            height: '40rpx',
            borderRadius: '20rpx',
            border: `2rpx solid ${isSelected ? C.primary : C.text3}`,
            background: isSelected ? C.primary : 'transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {isSelected && (
            <Text style={{ color: C.white, fontSize: '20rpx', lineHeight: '1' }}>✓</Text>
          )}
        </View>
      </View>
    )
  }

  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
      }}
    >
      <View
        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }}
        onClick={onClose}
      />
      <View
        style={{
          position: 'relative',
          background: C.bgCard,
          borderRadius: '24rpx 24rpx 0 0',
          maxHeight: '75vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Handle */}
        <View style={{ display: 'flex', justifyContent: 'center', padding: '16rpx 0 0' }}>
          <View style={{ width: '64rpx', height: '8rpx', borderRadius: '4rpx', background: C.border }} />
        </View>

        {/* Title bar */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '20rpx 32rpx 16rpx',
          }}
        >
          <View>
            <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>
              优惠券
            </Text>
            <Text style={{ color: C.text2, fontSize: '24rpx', marginLeft: '12rpx' }}>
              可用{available.length}张
            </Text>
          </View>
          <Text
            style={{ color: C.text2, fontSize: '28rpx', padding: '8rpx' }}
            onClick={onClose}
          >
            关闭
          </Text>
        </View>

        <ScrollView scrollY style={{ flex: 1, padding: '0 24rpx 32rpx' }}>
          {loading ? (
            <View style={{ padding: '48rpx', textAlign: 'center' }}>
              <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
            </View>
          ) : coupons.length === 0 ? (
            <View style={{ padding: '48rpx', textAlign: 'center' }}>
              <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无优惠券</Text>
            </View>
          ) : (
            <>
              {available.map((c) => renderCoupon(c))}
              {unavailable.length > 0 && (
                <>
                  <Text
                    style={{
                      color: C.text3,
                      fontSize: '24rpx',
                      margin: '16rpx 0 12rpx',
                    }}
                  >
                    金额不满足条件（{unavailable.length}张）
                  </Text>
                  {unavailable.map((c) => renderCoupon(c, true))}
                </>
              )}
            </>
          )}
        </ScrollView>
      </View>
    </View>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '16rpx',
        margin: '0 24rpx 16rpx',
        overflow: 'hidden',
      }}
    >
      <View
        style={{
          padding: '20rpx 24rpx 12rpx',
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

// ─── Radio option ─────────────────────────────────────────────────────────────

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
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '16rpx 0',
        opacity: disabled ? 0.4 : 1,
      }}
      onClick={!disabled ? onSelect : undefined}
    >
      <View
        style={{
          width: '40rpx',
          height: '40rpx',
          borderRadius: '20rpx',
          border: `2rpx solid ${selected ? C.primary : C.text3}`,
          background: selected ? C.primary : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginRight: '20rpx',
          flexShrink: 0,
        }}
      >
        {selected && (
          <View
            style={{
              width: '18rpx',
              height: '18rpx',
              borderRadius: '9rpx',
              background: C.white,
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

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CheckoutPage() {
  const { items, totalFen, storeId, clearCart } = useCartStore()
  const { storedValueFen, pointsBalance, isLoggedIn } = useUserStore()
  const { setCurrentOrder } = useOrderStore()
  const { pay, isProcessing: isPayProcessing } = usePayment()

  // Form state
  const [dineMode, setDineMode] = useState<DineMode>('dine-in')
  const [remark, setRemark] = useState('')
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('wechat')
  const [usePoints, setUsePoints] = useState(false)

  // Coupon state
  const [couponSheetVisible, setCouponSheetVisible] = useState(false)
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponsLoading, setCouponsLoading] = useState(false)
  const [selectedCoupon, setSelectedCoupon] = useState<Coupon | null>(null)
  const [couponDiscountFen, setCouponDiscountFen] = useState(0)

  // Loading / error
  const [isCreating, setIsCreating] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Points deduction logic: 1 point = 1 fen (configurable per tenant, here simplified)
  const MAX_POINTS_DEDUCTION_FEN = Math.min(pointsBalance, Math.round(totalFen * 0.2))
  const pointsDeductFen = usePoints ? MAX_POINTS_DEDUCTION_FEN : 0

  // Pricing
  const subtotalFen = totalFen
  const afterCouponFen = Math.max(0, subtotalFen - couponDiscountFen)
  const finalFen = Math.max(0, afterCouponFen - pointsDeductFen)

  // Payment method availability
  const storedValueSufficient = storedValueFen >= finalFen
  const storedValueLabel = `储值卡余额 ${fenToYuanDisplay(storedValueFen)}`
  const mixedLabel = storedValueFen > 0
    ? `混合支付（储值${fenToYuanDisplay(storedValueFen)} + 微信支付${fenToYuanDisplay(Math.max(0, finalFen - storedValueFen))}）`
    : '混合支付（储值不足）'

  // ── Load coupons ───────────────────────────────────────────────────────────
  async function openCouponSheet() {
    setCouponSheetVisible(true)
    if (coupons.length === 0) {
      setCouponsLoading(true)
      try {
        const list = await listCoupons('available')
        setCoupons(list)
      } catch {
        // tolerate — show empty state
      } finally {
        setCouponsLoading(false)
      }
    }
  }

  function handleSelectCoupon(coupon: Coupon | null) {
    setSelectedCoupon(coupon)
    setCouponSheetVisible(false)

    if (!coupon) {
      setCouponDiscountFen(0)
      return
    }

    // Preview discount locally (will be confirmed server-side on order create)
    if (coupon.type === 'discount_fen') {
      setCouponDiscountFen(totalFen >= coupon.minOrderFen ? coupon.discountValue : 0)
    } else if (coupon.type === 'discount_percent') {
      setCouponDiscountFen(
        totalFen >= coupon.minOrderFen
          ? Math.round(totalFen * (1 - coupon.discountValue / 100))
          : 0,
      )
    } else {
      setCouponDiscountFen(0)
    }
  }

  // ── Submit order ───────────────────────────────────────────────────────────
  const handleSubmit = useCallback(async () => {
    if (items.length === 0) return
    if (!isLoggedIn) {
      Taro.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    setIsCreating(true)
    setSubmitError(null)

    try {
      // 1. Create cart order
      const cartItems = items.map((item) => ({
        dishId: item.dishId,
        specId: item.specs ? Object.values(item.specs)[0] : undefined,
        quantity: item.quantity,
        remark: item.remark,
      }))

      const orderRemark = [
        dineMode === 'takeaway' ? '【外带】' : dineMode === 'reservation' ? '【预约】' : '',
        remark,
      ]
        .filter(Boolean)
        .join(' ')

      const order = await createCartOrder(storeId, cartItems, orderRemark || undefined)

      // 2. Apply coupon if selected
      if (selectedCoupon) {
        try {
          await applyCoupon(order.orderId, selectedCoupon.couponId)
        } catch {
          // Non-fatal: continue with order
        }
      }

      setCurrentOrder({
        id: order.orderId,
        status: 'pending',
        items: items.map((i) => ({
          dishId: i.dishId,
          name: i.name,
          quantity: i.quantity,
          price_fen: i.price_fen,
          specs: i.specs,
          remark: i.remark,
        })),
        total_fen: order.totalFen,
        discount_fen: order.discountFen,
        final_fen: order.payableFen,
        created_at: order.createdAt,
        store_name: order.storeName,
        table_no: order.tableNo ?? '',
      })

      // 3. Pay
      const payResult = await pay(order.orderId, paymentMethod)

      if (payResult.success) {
        clearCart()
        Taro.redirectTo({
          url: `/subpages/order-flow/pay-result/index?orderId=${encodeURIComponent(order.orderId)}&status=success&dineMode=${dineMode}`,
        })
      } else {
        Taro.redirectTo({
          url: `/subpages/order-flow/pay-result/index?orderId=${encodeURIComponent(order.orderId)}&status=failed&errorCode=${payResult.errorCode ?? ''}&errorMessage=${encodeURIComponent(payResult.errorMessage ?? '支付失败')}`,
        })
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '下单失败，请重试'
      setSubmitError(msg)
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setIsCreating(false)
    }
  }, [
    items,
    storeId,
    dineMode,
    remark,
    selectedCoupon,
    paymentMethod,
    isLoggedIn,
    pay,
    setCurrentOrder,
    clearCart,
  ])

  const isSubmitting = isCreating || isPayProcessing

  // ── Empty cart guard ───────────────────────────────────────────────────────
  if (items.length === 0) {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '28rpx' }}>购物车为空</Text>
      </View>
    )
  }

  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        paddingBottom: 'calc(180rpx + env(safe-area-inset-bottom))',
      }}
    >
      {/* Page title */}
      <View style={{ padding: '24rpx 32rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          确认订单
        </Text>
      </View>

      <ScrollView scrollY style={{ flex: 1 }}>
        {/* ── Order items (read-only) ── */}
        <Section title={`已选菜品（${items.length}种）`}>
          {items.map((item) => {
            const specText = item.specs
              ? Object.values(item.specs).join(' · ')
              : ''
            return (
              <View
                key={`${item.dishId}__${JSON.stringify(item.specs ?? {})}`}
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'flex-start',
                  paddingVertical: '10rpx',
                  borderBottom: `1rpx solid ${C.border}`,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ color: C.text1, fontSize: '28rpx' }}>{item.name}</Text>
                  {specText !== '' && (
                    <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                      {specText}
                    </Text>
                  )}
                  {item.remark && (
                    <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                      备注: {item.remark}
                    </Text>
                  )}
                </View>
                <View style={{ alignItems: 'flex-end', marginLeft: '16rpx' }}>
                  <Text style={{ color: C.text2, fontSize: '24rpx' }}>×{item.quantity}</Text>
                  <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600', marginTop: '6rpx' }}>
                    {fenToYuanDisplay(item.price_fen * item.quantity)}
                  </Text>
                </View>
              </View>
            )
          })}
        </Section>

        {/* ── 用餐方式 ── */}
        <Section title="用餐方式">
          <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
            {DINE_MODES.map((mode) => (
              <View
                key={mode.value}
                style={{
                  flex: 1,
                  height: '88rpx',
                  borderRadius: '16rpx',
                  border: `2rpx solid ${dineMode === mode.value ? C.primary : C.border}`,
                  background:
                    dineMode === mode.value ? 'rgba(255,107,44,0.12)' : C.bgDeep,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '4rpx',
                }}
                onClick={() => setDineMode(mode.value)}
              >
                <Text style={{ fontSize: '28rpx', lineHeight: '1' }}>{mode.icon}</Text>
                <Text
                  style={{
                    color: dineMode === mode.value ? C.primary : C.text2,
                    fontSize: '24rpx',
                    fontWeight: dineMode === mode.value ? '600' : '400',
                  }}
                >
                  {mode.label}
                </Text>
              </View>
            ))}
          </View>
        </Section>

        {/* ── 备注 ── */}
        <Section title="整单备注">
          <Textarea
            value={remark}
            onInput={(e) => setRemark(e.detail.value)}
            placeholder='特殊要求、过敏原、桌号等...'
            placeholderStyle={`color:${C.text3}`}
            style={{
              background: C.bgDeep,
              color: C.text1,
              fontSize: '26rpx',
              borderRadius: '12rpx',
              padding: '16rpx',
              width: '100%',
              minHeight: '96rpx',
              border: `1rpx solid ${C.border}`,
            }}
            maxlength={200}
          />
        </Section>

        {/* ── 优惠券 ── */}
        <Section title="优惠券">
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              padding: '8rpx 0',
            }}
            onClick={openCouponSheet}
          >
            <Text style={{ fontSize: '28rpx', marginRight: '12rpx' }}>🎟</Text>
            <Text style={{ color: C.text1, fontSize: '28rpx', flex: 1 }}>
              {selectedCoupon
                ? `已选：${selectedCoupon.name}`
                : `可用${coupons.filter((c) => c.status === 'available').length}张`}
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

        {/* ── 积分抵扣 ── */}
        {isLoggedIn && pointsBalance > 0 && (
          <Section title="积分抵扣">
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
              }}
              onClick={() => setUsePoints(!usePoints)}
            >
              {/* Checkbox */}
              <View
                style={{
                  width: '40rpx',
                  height: '40rpx',
                  borderRadius: '8rpx',
                  border: `2rpx solid ${usePoints ? C.primary : C.text3}`,
                  background: usePoints ? C.primary : 'transparent',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginRight: '20rpx',
                  flexShrink: 0,
                }}
              >
                {usePoints && (
                  <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '700' }}>
                    ✓
                  </Text>
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: C.text1, fontSize: '28rpx' }}>
                  使用积分抵扣{' '}
                  <Text style={{ color: C.primary }}>
                    {fenToYuanDisplay(MAX_POINTS_DEDUCTION_FEN)}
                  </Text>
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                  可用积分：{pointsBalance}分（最多抵扣订单金额20%）
                </Text>
              </View>
            </View>
          </Section>
        )}

        {/* ── 支付方式 ── */}
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

        {/* ── 价格明细 ── */}
        <View
          style={{
            background: C.bgCard,
            borderRadius: '16rpx',
            margin: '0 24rpx 16rpx',
            padding: '20rpx 24rpx',
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
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'baseline',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>实付</Text>
            <Text style={{ color: C.primary, fontSize: '44rpx', fontWeight: '800' }}>
              {fenToYuanDisplay(finalFen)}
            </Text>
          </View>
        </View>

        {/* Error message */}
        {submitError && (
          <View style={{ padding: '8rpx 32rpx' }}>
            <Text style={{ color: C.red, fontSize: '24rpx' }}>{submitError}</Text>
          </View>
        )}
      </ScrollView>

      {/* ── Submit CTA ── */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          background: C.bgCard,
          borderTop: `1rpx solid ${C.border}`,
          padding: '20rpx 24rpx',
          paddingBottom: 'calc(20rpx + env(safe-area-inset-bottom))',
          zIndex: 100,
        }}
      >
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '12rpx',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>
            共{items.reduce((s, i) => s + i.quantity, 0)}件
          </Text>
          <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(finalFen)}
          </Text>
        </View>
        <View
          style={{
            background: isSubmitting ? C.disabled : C.primary,
            borderRadius: '44rpx',
            height: '88rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: isSubmitting ? 0.7 : 1,
          }}
          onClick={isSubmitting ? undefined : handleSubmit}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {isCreating ? '下单中...' : isPayProcessing ? '支付中...' : '提交订单'}
          </Text>
        </View>
      </View>

      {/* Coupon sheet */}
      <CouponSheet
        visible={couponSheetVisible}
        coupons={coupons}
        loading={couponsLoading}
        selectedId={selectedCoupon?.couponId ?? null}
        orderTotalFen={totalFen}
        onSelect={handleSelectCoupon}
        onClose={() => setCouponSheetVisible(false)}
      />
    </View>
  )
}

// ─── Helper: Price line ───────────────────────────────────────────────────────

function PriceLine({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '10rpx',
      }}
    >
      <Text style={{ color: C.text2, fontSize: '26rpx' }} numberOfLines={1}>
        {label}
      </Text>
      <Text
        style={{
          color: accent ? C.primary : C.text1,
          fontSize: '26rpx',
          fontWeight: accent ? '600' : '400',
          marginLeft: '24rpx',
        }}
      >
        {value}
      </Text>
    </View>
  )
}
