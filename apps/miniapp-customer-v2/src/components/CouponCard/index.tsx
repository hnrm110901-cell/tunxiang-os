/**
 * CouponCard — displays a single coupon with optional radio-select behaviour
 *
 * Coupon states:
 *  available — brand-colour left stripe, selectable
 *  used      — grey stripe + diagonal "已使用" watermark
 *  expired   — grey stripe + diagonal "已过期" watermark, full grey-out
 */
import { View, Text } from '@tarojs/components'
import React from 'react'
import { fenToYuanDisplay } from '../../utils/format'
import { formatDate } from '../../utils/format'

// ─── Types ────────────────────────────────────────────────────────────────────

export type CouponType = 'discount' | 'cash' | 'free'
export type CouponStatus = 'available' | 'used' | 'expired'

export interface Coupon {
  id: string
  title: string
  discount_fen: number
  min_order_fen: number
  expire_at: string
  type: CouponType
  status: CouponStatus
}

export interface CouponCardProps {
  coupon: Coupon
  selectable?: boolean
  selected?: boolean
  onSelect?: (id: string) => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_LABEL: Record<CouponType, string> = {
  discount: '折扣券',
  cash: '满减券',
  free: '免单券',
}

function discountLabel(coupon: Coupon): string {
  switch (coupon.type) {
    case 'cash':
      return fenToYuanDisplay(coupon.discount_fen)
    case 'discount': {
      // discount_fen stores the discount expressed as a percentage point in fen
      // e.g. 800 fen = 80% = 8折. We display as "8折"
      const pct = Math.round(coupon.discount_fen / 100)
      return `${pct}折`
    }
    case 'free':
      return '免单'
  }
}

function discountFontSize(coupon: Coupon): string {
  // Free / discount have shorter text — larger font is fine
  if (coupon.type === 'free') return '40rpx'
  if (coupon.type === 'discount') return '52rpx'
  return '48rpx'
}

// ─── Component ────────────────────────────────────────────────────────────────

const CouponCard: React.FC<CouponCardProps> = ({
  coupon,
  selectable = false,
  selected = false,
  onSelect,
}) => {
  const isActive = coupon.status === 'available'
  const isUsed = coupon.status === 'used'

  // Colour palette
  const stripeColor = isActive ? '#FF6B35' : '#3A4E5A'
  const cardBg = isActive ? '#1A2E38' : '#132029'
  const textPrimary = isActive ? '#FFFFFF' : '#5A7080'
  const textSecondary = isActive ? '#9EB5C0' : '#3A4E5A'
  const amountColor = isActive ? '#FF6B35' : '#3A4E5A'

  const handleTap = () => {
    if (isActive && selectable && onSelect) {
      onSelect(coupon.id)
    }
  }

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        background: cardBg,
        borderRadius: '24rpx',
        overflow: 'hidden',
        border: selected
          ? '2rpx solid #FF6B35'
          : `2rpx solid ${isActive ? '#1E3340' : '#1A2532'}`,
        minHeight: '160rpx',
        position: 'relative',
        transition: 'border 0.15s',
        opacity: coupon.status === 'expired' ? 0.55 : 1,
      }}
      onClick={handleTap}
    >
      {/* Left colour stripe */}
      <View
        style={{
          width: '12rpx',
          background: stripeColor,
          flexShrink: 0,
        }}
      />

      {/* Left section: discount amount + type label */}
      <View
        style={{
          width: '188rpx',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24rpx 16rpx',
          borderRight: `2rpx dashed ${isActive ? '#1E3340' : '#1A2532'}`,
          gap: '8rpx',
        }}
      >
        <Text
          style={{
            color: amountColor,
            fontSize: discountFontSize(coupon),
            fontWeight: '800',
            lineHeight: '1.1',
          }}
        >
          {discountLabel(coupon)}
        </Text>
        <Text
          style={{
            color: textSecondary,
            fontSize: '22rpx',
            fontWeight: '500',
            letterSpacing: '1rpx',
          }}
        >
          {TYPE_LABEL[coupon.type]}
        </Text>
      </View>

      {/* Dashed circle notches on the dashed border */}
      <View
        style={{
          position: 'absolute',
          left: '196rpx',
          top: '-16rpx',
          width: '32rpx',
          height: '32rpx',
          borderRadius: '16rpx',
          background: '#0B1A20',
          zIndex: 2,
        }}
      />
      <View
        style={{
          position: 'absolute',
          left: '196rpx',
          bottom: '-16rpx',
          width: '32rpx',
          height: '32rpx',
          borderRadius: '16rpx',
          background: '#0B1A20',
          zIndex: 2,
        }}
      />

      {/* Right section: title + condition + expiry */}
      <View
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '24rpx 28rpx 24rpx 32rpx',
          gap: '10rpx',
        }}
      >
        <Text
          style={{
            color: textPrimary,
            fontSize: '30rpx',
            fontWeight: '600',
            lineHeight: '1.3',
          }}
          numberOfLines={2}
        >
          {coupon.title}
        </Text>
        {coupon.min_order_fen > 0 && (
          <Text
            style={{
              color: textSecondary,
              fontSize: '24rpx',
            }}
          >
            满 {fenToYuanDisplay(coupon.min_order_fen)} 可用
          </Text>
        )}
        <Text
          style={{
            color: textSecondary,
            fontSize: '22rpx',
          }}
        >
          有效至 {formatDate(coupon.expire_at).split(' ')[0]}
        </Text>
      </View>

      {/* Selectable radio */}
      {selectable && isActive && (
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            paddingRight: '28rpx',
            flexShrink: 0,
          }}
        >
          <View
            style={{
              width: '44rpx',
              height: '44rpx',
              borderRadius: '22rpx',
              border: `3rpx solid ${selected ? '#FF6B35' : '#2A4558'}`,
              background: selected ? '#FF6B35' : 'transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background 0.2s, border 0.2s',
            }}
          >
            {selected && (
              <Text
                style={{
                  color: '#FFFFFF',
                  fontSize: '26rpx',
                  fontWeight: '700',
                  lineHeight: '1',
                }}
              >
                ✓
              </Text>
            )}
          </View>
        </View>
      )}

      {/* Watermark for used / expired — diagonal text overlay */}
      {!isActive && (
        <View
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
            // rotate the watermark ~-25deg using a wrapping trick
            overflow: 'hidden',
          }}
        >
          <View
            style={{
              position: 'absolute',
              right: '32rpx',
              top: '28rpx',
              transform: 'rotate(-25deg)',
              border: `4rpx solid ${isUsed ? '#3A4E5A' : '#2E3E48'}`,
              borderRadius: '8rpx',
              padding: '6rpx 18rpx',
            }}
          >
            <Text
              style={{
                color: isUsed ? '#3A4E5A' : '#2E3E48',
                fontSize: '28rpx',
                fontWeight: '700',
                letterSpacing: '4rpx',
              }}
            >
              {isUsed ? '已使用' : '已过期'}
            </Text>
          </View>
        </View>
      )}
    </View>
  )
}

export default CouponCard
