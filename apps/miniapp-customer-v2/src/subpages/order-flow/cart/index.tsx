/**
 * cart/index.tsx — 购物车页
 *
 * Features:
 *  - Empty state with navigation back to menu
 *  - Item list with swipe-left to delete, inline remark editing
 *  - Per-item quantity stepper
 *  - Coupon picker sheet (bottom half-screen)
 *  - Price summary: 合计 / 折扣 / 实付
 *  - "去结算" CTA → checkout
 */

import React, { useState, useCallback, useRef } from 'react'
import { View, Text, ScrollView, Textarea, MovableArea, MovableView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useCartStore, CartItem } from '../../../store/useCartStore'
import { useUserStore } from '../../../store/useUserStore'
import { applyCoupon } from '../../../api/trade'
import { listCoupons, Coupon } from '../../../api/growth'
import { fenToYuanDisplay } from '../../../utils/format'

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
} as const

// ─── Swipe threshold ──────────────────────────────────────────────────────────
const SWIPE_DELETE_THRESHOLD = 80 // rpx worth of pixels, approximate

// ─── Coupon Sheet ─────────────────────────────────────────────────────────────

interface CouponSheetProps {
  visible: boolean
  coupons: Coupon[]
  loading: boolean
  selectedId: string | null
  onSelect: (coupon: Coupon) => void
  onClose: () => void
}

function CouponSheet({
  visible,
  coupons,
  loading,
  selectedId,
  onSelect,
  onClose,
}: CouponSheetProps) {
  if (!visible) return null

  const available = coupons.filter((c) => c.status === 'available')

  function couponValueLabel(c: Coupon): string {
    if (c.type === 'discount_fen') return `减${fenToYuanDisplay(c.discountValue)}`
    if (c.type === 'discount_percent') return `${c.discountValue}折`
    if (c.type === 'free_item') return '免费菜品'
    return '优惠'
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
      {/* Backdrop */}
      <View
        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }}
        onClick={onClose}
      />

      {/* Sheet */}
      <View
        style={{
          position: 'relative',
          background: '#132029',
          borderRadius: '24rpx 24rpx 0 0',
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Handle */}
        <View style={{ display: 'flex', justifyContent: 'center', padding: '16rpx 0 0' }}>
          <View
            style={{
              width: '64rpx',
              height: '8rpx',
              borderRadius: '4rpx',
              background: C.border,
            }}
          />
        </View>

        {/* Title */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '20rpx 32rpx 16rpx',
          }}
        >
          <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>
            选择优惠券
          </Text>
          <Text
            style={{ color: C.text2, fontSize: '28rpx', padding: '8rpx' }}
            onClick={onClose}
          >
            关闭
          </Text>
        </View>

        {/* List */}
        <ScrollView scrollY style={{ flex: 1, padding: '0 24rpx 32rpx' }}>
          {loading ? (
            <View style={{ padding: '48rpx', textAlign: 'center' }}>
              <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
            </View>
          ) : available.length === 0 ? (
            <View style={{ padding: '48rpx', textAlign: 'center' }}>
              <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无可用优惠券</Text>
            </View>
          ) : (
            available.map((coupon) => {
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
                  }}
                  onClick={() => onSelect(coupon)}
                >
                  {/* Value badge */}
                  <View
                    style={{
                      background: C.primary,
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

                  {/* Info */}
                  <View style={{ flex: 1 }}>
                    <Text
                      style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500' }}
                      numberOfLines={1}
                    >
                      {coupon.name}
                    </Text>
                    {coupon.minOrderFen > 0 && (
                      <Text
                        style={{ color: C.text2, fontSize: '22rpx', marginTop: '6rpx' }}
                      >
                        满{fenToYuanDisplay(coupon.minOrderFen)}可用
                      </Text>
                    )}
                    <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                      {coupon.validUntil.slice(0, 10)} 到期
                    </Text>
                  </View>

                  {/* Selection indicator */}
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
                      <Text style={{ color: C.white, fontSize: '20rpx', lineHeight: '1' }}>
                        ✓
                      </Text>
                    )}
                  </View>
                </View>
              )
            })
          )}
        </ScrollView>
      </View>
    </View>
  )
}

// ─── Cart Item Row ────────────────────────────────────────────────────────────

interface CartItemRowProps {
  item: CartItem
  onAdd: () => void
  onRemove: () => void
  onDelete: () => void
  onRemarkChange: (remark: string) => void
}

function CartItemRow({
  item,
  onAdd,
  onRemove,
  onDelete,
  onRemarkChange,
}: CartItemRowProps) {
  const [swiped, setSwiped] = useState(false)
  const [editingRemark, setEditingRemark] = useState(false)
  const [remarkDraft, setRemarkDraft] = useState(item.remark ?? '')

  function handleSwipeLeft() {
    setSwiped(true)
  }
  function handleSwipeRight() {
    setSwiped(false)
  }

  function handleSaveRemark() {
    onRemarkChange(remarkDraft)
    setEditingRemark(false)
  }

  const specText = item.specs
    ? Object.entries(item.specs)
        .map(([, v]) => v)
        .join(' · ')
    : ''

  return (
    <View
      style={{
        marginBottom: '16rpx',
        overflow: 'hidden',
        borderRadius: '16rpx',
        position: 'relative',
      }}
    >
      {/* Delete action revealed on swipe */}
      <View
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: '160rpx',
          background: C.red,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: '0 16rpx 16rpx 0',
          zIndex: 1,
        }}
        onClick={onDelete}
      >
        <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '600' }}>删除</Text>
      </View>

      {/* Swipeable card */}
      <View
        style={{
          background: C.bgCard,
          borderRadius: '16rpx',
          padding: '20rpx',
          position: 'relative',
          zIndex: 2,
          transform: swiped ? 'translateX(-160rpx)' : 'translateX(0)',
          transition: 'transform 0.25s ease',
        }}
        onTouchStart={(e) => {
          const touch = (e as unknown as { touches: { clientX: number }[] }).touches[0]
          ;(e.currentTarget as unknown as { _startX: number })._startX = touch.clientX
        }}
        onTouchEnd={(e) => {
          const el = e.currentTarget as unknown as { _startX: number }
          const touch = (e as unknown as { changedTouches: { clientX: number }[] })
            .changedTouches[0]
          const dx = touch.clientX - el._startX
          if (dx < -SWIPE_DELETE_THRESHOLD) handleSwipeLeft()
          else if (dx > SWIPE_DELETE_THRESHOLD) handleSwipeRight()
        }}
      >
        {/* Main row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-start',
          }}
        >
          {/* Left: name + specs */}
          <View style={{ flex: 1 }}>
            <Text
              style={{
                color: C.text1,
                fontSize: '30rpx',
                fontWeight: '600',
                lineHeight: '40rpx',
              }}
            >
              {item.name}
            </Text>
            {specText !== '' && (
              <Text
                style={{
                  color: C.text2,
                  fontSize: '24rpx',
                  lineHeight: '34rpx',
                  marginTop: '4rpx',
                }}
              >
                {specText}
              </Text>
            )}

            {/* Remark row */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                marginTop: '12rpx',
                gap: '8rpx',
              }}
              onClick={() => !editingRemark && setEditingRemark(true)}
            >
              <Text style={{ color: C.text3, fontSize: '22rpx' }}>备注：</Text>
              {editingRemark ? (
                <View style={{ flex: 1 }}>
                  <Textarea
                    value={remarkDraft}
                    onInput={(e) => setRemarkDraft(e.detail.value)}
                    placeholder='如：少辣、去葱...'
                    placeholderStyle={`color:${C.text3}`}
                    style={{
                      background: C.bgDeep,
                      color: C.text1,
                      fontSize: '24rpx',
                      borderRadius: '8rpx',
                      padding: '12rpx',
                      width: '100%',
                      minHeight: '72rpx',
                      border: `1rpx solid ${C.border}`,
                    }}
                    maxlength={80}
                    autoFocus
                  />
                  <View
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      gap: '16rpx',
                      marginTop: '12rpx',
                    }}
                  >
                    <View
                      style={{
                        flex: 1,
                        height: '64rpx',
                        border: `1rpx solid ${C.border}`,
                        borderRadius: '32rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                      onClick={() => {
                        setRemarkDraft(item.remark ?? '')
                        setEditingRemark(false)
                      }}
                    >
                      <Text style={{ color: C.text2, fontSize: '24rpx' }}>取消</Text>
                    </View>
                    <View
                      style={{
                        flex: 1,
                        height: '64rpx',
                        background: C.primary,
                        borderRadius: '32rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                      onClick={handleSaveRemark}
                    >
                      <Text style={{ color: C.white, fontSize: '24rpx', fontWeight: '600' }}>
                        确定
                      </Text>
                    </View>
                  </View>
                </View>
              ) : (
                <Text
                  style={{
                    color: item.remark ? C.text2 : C.text3,
                    fontSize: '24rpx',
                    flex: 1,
                  }}
                  numberOfLines={1}
                >
                  {item.remark || '点击添加备注'}
                </Text>
              )}
            </View>
          </View>

          {/* Right: price + stepper */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              gap: '16rpx',
              marginLeft: '16rpx',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '30rpx', fontWeight: '700' }}>
              {fenToYuanDisplay(item.price_fen * item.quantity)}
            </Text>

            {/* Stepper */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: '8rpx',
              }}
            >
              <View
                style={{
                  width: '56rpx',
                  height: '56rpx',
                  borderRadius: '28rpx',
                  border: `2rpx solid ${C.primary}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                onClick={onRemove}
              >
                <Text style={{ color: C.primary, fontSize: '30rpx', lineHeight: '1' }}>−</Text>
              </View>
              <Text
                style={{
                  color: C.text1,
                  fontSize: '28rpx',
                  fontWeight: '600',
                  minWidth: '40rpx',
                  textAlign: 'center',
                }}
              >
                {item.quantity}
              </Text>
              <View
                style={{
                  width: '56rpx',
                  height: '56rpx',
                  borderRadius: '28rpx',
                  background: C.primary,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                onClick={onAdd}
              >
                <Text style={{ color: C.white, fontSize: '30rpx', lineHeight: '1' }}>+</Text>
              </View>
            </View>
          </View>
        </View>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CartPage() {
  const { items, totalFen, discountFen, storeId, addItem, removeItem, updateRemark, setDiscount } =
    useCartStore()

  // Coupon state
  const [couponSheetVisible, setCouponSheetVisible] = useState(false)
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponsLoading, setCouponsLoading] = useState(false)
  const [selectedCoupon, setSelectedCoupon] = useState<Coupon | null>(null)
  const [couponError, setCouponError] = useState<string | null>(null)
  const [applyingCoupon, setApplyingCoupon] = useState(false)

  // Pending coupon order ID (set after createCartOrder in checkout; here we preview only)
  const pendingOrderIdRef = useRef<string | null>(null)

  const finalFen = Math.max(0, totalFen - discountFen)
  const isEmpty = items.length === 0

  // Load coupons
  async function openCouponSheet() {
    setCouponSheetVisible(true)
    if (coupons.length === 0) {
      setCouponsLoading(true)
      try {
        const list = await listCoupons('available')
        setCoupons(list)
      } catch {
        // keep empty list — user can still close sheet
      } finally {
        setCouponsLoading(false)
      }
    }
  }

  async function handleSelectCoupon(coupon: Coupon) {
    setSelectedCoupon(coupon)
    setCouponSheetVisible(false)

    // If we have a pending order, apply coupon live; otherwise just preview discount
    if (pendingOrderIdRef.current) {
      setApplyingCoupon(true)
      setCouponError(null)
      try {
        const result = await applyCoupon(pendingOrderIdRef.current, coupon.couponId)
        setDiscount(result.discountFen)
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '优惠券应用失败'
        setCouponError(msg)
        setSelectedCoupon(null)
        setDiscount(0)
      } finally {
        setApplyingCoupon(false)
      }
    } else {
      // Preview: compute estimated discount from coupon metadata
      if (coupon.type === 'discount_fen') {
        setDiscount(totalFen >= coupon.minOrderFen ? coupon.discountValue : 0)
      } else if (coupon.type === 'discount_percent') {
        setDiscount(
          totalFen >= coupon.minOrderFen
            ? Math.round(totalFen * (1 - coupon.discountValue / 100))
            : 0,
        )
      }
    }
  }

  function goToMenu() {
    Taro.navigateBack({ delta: 1 })
  }

  function goToCheckout() {
    if (isEmpty) return
    Taro.navigateTo({
      url: '/subpages/order-flow/checkout/index',
      success: () => {
        // Pass couponId via eventChannel if available
        if (selectedCoupon) {
          const pages = Taro.getCurrentPages()
          const currentPage = pages[pages.length - 1] as unknown as {
            getOpenerEventChannel?: () => { emit: (evt: string, data: unknown) => void }
          }
          currentPage.getOpenerEventChannel?.()?.emit('couponSelected', {
            couponId: selectedCoupon.couponId,
          })
        }
      },
    })
  }

  // ── Render: empty state ────────────────────────────────────────────────────
  if (isEmpty) {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 48rpx',
        }}
      >
        {/* Illustration placeholder */}
        <View
          style={{
            width: '240rpx',
            height: '240rpx',
            borderRadius: '120rpx',
            background: C.bgCard,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '40rpx',
          }}
        >
          <Text style={{ fontSize: '96rpx', lineHeight: '1' }}>🛒</Text>
        </View>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>
          购物车是空的
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '16rpx' }}>
          快去选几道心仪的菜品吧
        </Text>
        <View
          style={{
            marginTop: '48rpx',
            background: C.primary,
            borderRadius: '44rpx',
            height: '88rpx',
            minWidth: '240rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 48rpx',
          }}
          onClick={goToMenu}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            去点餐
          </Text>
        </View>
      </View>
    )
  }

  // ── Render: cart with items ────────────────────────────────────────────────
  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
        paddingBottom: 'calc(280rpx + env(safe-area-inset-bottom))',
      }}
    >
      {/* Header */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '24rpx 32rpx 16rpx',
          gap: '12rpx',
        }}
      >
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>购物车</Text>
        {storeId !== '' && (
          <Text style={{ color: C.text2, fontSize: '26rpx' }}>· {storeId}</Text>
        )}
        <View style={{ flex: 1 }} />
        <Text
          style={{ color: C.text2, fontSize: '26rpx', padding: '8rpx' }}
          onClick={() => {
            Taro.showModal({
              title: '清空购物车',
              content: '确认移除所有已选菜品吗？',
              confirmColor: C.red,
              success: (res) => {
                if (res.confirm) {
                  useCartStore.getState().clearCart()
                  setSelectedCoupon(null)
                }
              },
            })
          }}
        >
          清空
        </Text>
      </View>

      {/* Items */}
      <ScrollView
        scrollY
        style={{ flex: 1, padding: '0 24rpx' }}
      >
        {items.map((item) => (
          <CartItemRow
            key={`${item.dishId}__${JSON.stringify(item.specs ?? {})}`}
            item={item}
            onAdd={() => addItem({ dishId: item.dishId, name: item.name, price_fen: item.price_fen }, item.specs)}
            onRemove={() => removeItem(item.dishId, item.specs)}
            onDelete={() =>
              Taro.showModal({
                title: '移除菜品',
                content: `确认移除「${item.name}」吗？`,
                confirmColor: C.red,
                success: (res) => {
                  if (res.confirm) {
                    // Remove all quantity
                    const store = useCartStore.getState()
                    const found = store.items.find(
                      (i) =>
                        i.dishId === item.dishId &&
                        JSON.stringify(i.specs ?? {}) === JSON.stringify(item.specs ?? {}),
                    )
                    if (found) {
                      for (let n = 0; n < found.quantity; n++) {
                        store.removeItem(item.dishId, item.specs)
                      }
                    }
                  }
                },
              })
            }
            onRemarkChange={(remark) => updateRemark(item.dishId, remark)}
          />
        ))}

        {/* Coupon row */}
        <View
          style={{
            background: C.bgCard,
            borderRadius: '16rpx',
            padding: '24rpx',
            marginTop: '8rpx',
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
          }}
          onClick={openCouponSheet}
        >
          <Text style={{ fontSize: '28rpx', marginRight: '12rpx' }}>🎟</Text>
          <Text style={{ color: C.text1, fontSize: '28rpx', flex: 1 }}>
            {selectedCoupon ? selectedCoupon.name : '选择优惠券'}
          </Text>
          {applyingCoupon ? (
            <Text style={{ color: C.text2, fontSize: '24rpx' }}>应用中...</Text>
          ) : selectedCoupon ? (
            <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
              -{fenToYuanDisplay(discountFen)}
            </Text>
          ) : (
            <Text style={{ color: C.text2, fontSize: '24rpx' }}>›</Text>
          )}
        </View>
        {couponError && (
          <Text
            style={{ color: C.red, fontSize: '22rpx', padding: '8rpx 24rpx' }}
          >
            {couponError}
          </Text>
        )}
      </ScrollView>

      {/* Bottom summary + CTA */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          background: C.bgCard,
          borderTop: `1rpx solid ${C.border}`,
          paddingBottom: 'env(safe-area-inset-bottom)',
          zIndex: 100,
        }}
      >
        {/* Price breakdown */}
        <View style={{ padding: '20rpx 32rpx 8rpx' }}>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              marginBottom: '8rpx',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>合计</Text>
            <Text style={{ color: C.text1, fontSize: '26rpx' }}>
              {fenToYuanDisplay(totalFen)}
            </Text>
          </View>
          {discountFen > 0 && (
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                marginBottom: '8rpx',
              }}
            >
              <Text style={{ color: C.text2, fontSize: '26rpx' }}>折扣</Text>
              <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
                -{fenToYuanDisplay(discountFen)}
              </Text>
            </View>
          )}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              borderTop: `1rpx solid ${C.border}`,
              paddingTop: '12rpx',
              marginTop: '4rpx',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>实付</Text>
            <Text
              style={{ color: C.primary, fontSize: '40rpx', fontWeight: '800' }}
            >
              {fenToYuanDisplay(finalFen)}
            </Text>
          </View>
        </View>

        {/* CTA */}
        <View style={{ padding: '12rpx 24rpx 16rpx' }}>
          <View
            style={{
              background: C.primary,
              borderRadius: '44rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={goToCheckout}
          >
            <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
              去结算（共{items.reduce((s, i) => s + i.quantity, 0)}件）
            </Text>
          </View>
        </View>
      </View>

      {/* Coupon sheet */}
      <CouponSheet
        visible={couponSheetVisible}
        coupons={coupons}
        loading={couponsLoading}
        selectedId={selectedCoupon?.couponId ?? null}
        onSelect={handleSelectCoupon}
        onClose={() => setCouponSheetVisible(false)}
      />
    </View>
  )
}
