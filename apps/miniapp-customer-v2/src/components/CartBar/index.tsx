import { View, Text } from '@tarojs/components'
import React from 'react'

interface CartBarProps {
  totalFen: number
  count: number
  onViewCart: () => void
  onCheckout: () => void
}

function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2)
}

const CartBar: React.FC<CartBarProps> = ({ totalFen, count, onViewCart, onCheckout }) => {
  // Only render when there are items
  if (count <= 0) return null

  const canCheckout = count > 0

  return (
    <View
      style={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 900,
        background: '#132029',
        borderTop: '1rpx solid #1E3040',
        // height: 100rpx + safe-area-inset-bottom
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      <View
        style={{
          height: '100rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '0 24rpx',
          gap: '16rpx',
        }}
      >
        {/* Left: cart icon + badge + price */}
        <View
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '16rpx',
            minHeight: '88rpx',
          }}
          onClick={onViewCart}
        >
          {/* Cart icon with badge */}
          <View style={{ position: 'relative', width: '64rpx', height: '64rpx' }}>
            <View
              style={{
                width: '64rpx',
                height: '64rpx',
                borderRadius: '32rpx',
                background: '#FF6B35',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* Shopping cart unicode icon */}
              <Text style={{ fontSize: '34rpx', lineHeight: '1' }}>🛒</Text>
            </View>

            {/* Badge */}
            <View
              style={{
                position: 'absolute',
                top: '-8rpx',
                right: '-8rpx',
                background: '#E53935',
                borderRadius: '24rpx',
                minWidth: '36rpx',
                height: '36rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 6rpx',
                border: '2rpx solid #0B1A20',
              }}
            >
              <Text
                style={{
                  color: '#fff',
                  fontSize: '20rpx',
                  fontWeight: '700',
                  lineHeight: '1',
                }}
              >
                {count > 99 ? '99+' : count}
              </Text>
            </View>
          </View>

          {/* Total price */}
          <View>
            <Text
              style={{
                color: '#FF6B35',
                fontSize: '36rpx',
                fontWeight: '700',
              }}
            >
              {fenToYuan(totalFen)}
            </Text>
            <Text
              style={{
                color: '#6B8A96',
                fontSize: '22rpx',
                marginLeft: '4rpx',
              }}
            >
              含配送费
            </Text>
          </View>
        </View>

        {/* Right: checkout button */}
        <View
          style={{
            background: canCheckout ? '#FF6B35' : '#2A4050',
            borderRadius: '44rpx',
            height: '88rpx',
            minWidth: '216rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 40rpx',
            opacity: canCheckout ? 1 : 0.5,
            transition: 'background 0.2s ease',
          }}
          onClick={canCheckout ? onCheckout : undefined}
        >
          <Text
            style={{
              color: '#fff',
              fontSize: '32rpx',
              fontWeight: '700',
            }}
          >
            去结算
          </Text>
        </View>
      </View>
    </View>
  )
}

export default CartBar
