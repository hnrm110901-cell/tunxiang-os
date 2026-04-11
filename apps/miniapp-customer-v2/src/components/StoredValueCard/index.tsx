/**
 * StoredValueCard — gradient dark card for stored-value balance
 *
 * Shows:
 *  - Main balance ¥XX.XX (large)
 *  - Promotional/gift balance (brand colour, small)
 *  - Masked card number ****XXXX
 *  - "充值" and "消费记录" buttons
 */
import { View, Text } from '@tarojs/components'
import React from 'react'
import { fenToYuanDisplay } from '../../utils/format'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface StoredValueCardProps {
  balance_fen: number
  gift_balance_fen: number
  card_no: string
  onRecharge: () => void
  onViewHistory: () => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function maskCardNo(no: string): string {
  if (!no || no.length < 4) return no
  return `****${no.slice(-4)}`
}

// ─── Component ────────────────────────────────────────────────────────────────

const StoredValueCard: React.FC<StoredValueCardProps> = ({
  balance_fen,
  gift_balance_fen,
  card_no,
  onRecharge,
  onViewHistory,
}) => {
  const totalFen = balance_fen + gift_balance_fen

  return (
    <View
      style={{
        borderRadius: '32rpx',
        overflow: 'hidden',
        // Multi-stop gradient for premium dark card feel
        background:
          'linear-gradient(135deg, #1B3244 0%, #0E2030 45%, #0A1820 100%)',
        border: '1rpx solid rgba(158,181,192,0.15)',
        boxShadow: '0 8rpx 40rpx rgba(0,0,0,0.5)',
        position: 'relative',
        padding: '40rpx 36rpx 32rpx',
      }}
    >
      {/* Decorative accent orb — top-right */}
      <View
        style={{
          position: 'absolute',
          right: '-48rpx',
          top: '-48rpx',
          width: '240rpx',
          height: '240rpx',
          borderRadius: '120rpx',
          background: 'radial-gradient(circle, rgba(255,107,53,0.18) 0%, transparent 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* Decorative accent orb — bottom-left */}
      <View
        style={{
          position: 'absolute',
          left: '-40rpx',
          bottom: '-40rpx',
          width: '200rpx',
          height: '200rpx',
          borderRadius: '100rpx',
          background: 'radial-gradient(circle, rgba(10,132,255,0.12) 0%, transparent 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* Card header row: chip icon + "储值卡" label + card number */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '36rpx',
        }}
      >
        {/* Chip icon + label */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '12rpx',
          }}
        >
          {/* Chip */}
          <View
            style={{
              width: '48rpx',
              height: '36rpx',
              borderRadius: '8rpx',
              background: 'linear-gradient(135deg, #FFD700 0%, #C8A400 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                width: '32rpx',
                height: '24rpx',
                borderRadius: '4rpx',
                border: '1rpx solid rgba(0,0,0,0.3)',
                background: 'linear-gradient(135deg, #FFE566 0%, #D4A800 100%)',
              }}
            />
          </View>
          <Text
            style={{
              color: 'rgba(255,255,255,0.85)',
              fontSize: '28rpx',
              fontWeight: '600',
              letterSpacing: '2rpx',
            }}
          >
            储值卡
          </Text>
        </View>

        {/* Card number */}
        <Text
          style={{
            color: 'rgba(158,181,192,0.7)',
            fontSize: '26rpx',
            fontFamily: 'monospace',
            letterSpacing: '3rpx',
          }}
        >
          {maskCardNo(card_no)}
        </Text>
      </View>

      {/* Balance section */}
      <View style={{ marginBottom: '40rpx' }}>
        {/* Label */}
        <Text
          style={{
            color: 'rgba(158,181,192,0.7)',
            fontSize: '26rpx',
            marginBottom: '10rpx',
            display: 'block',
          }}
        >
          可用余额（元）
        </Text>

        {/* Main balance */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-end',
            gap: '4rpx',
            marginBottom: '16rpx',
          }}
        >
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '36rpx',
              fontWeight: '400',
              lineHeight: '1',
              marginBottom: '10rpx',
            }}
          >
            ¥
          </Text>
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '88rpx',
              fontWeight: '800',
              lineHeight: '1',
              letterSpacing: '-3rpx',
            }}
          >
            {(balance_fen / 100).toFixed(2)}
          </Text>
        </View>

        {/* Gift balance */}
        {gift_balance_fen > 0 && (
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
                background: 'rgba(255,107,53,0.2)',
                borderRadius: '8rpx',
                padding: '4rpx 12rpx',
              }}
            >
              <Text
                style={{
                  color: '#FF6B35',
                  fontSize: '22rpx',
                  fontWeight: '600',
                }}
              >
                赠送
              </Text>
            </View>
            <Text
              style={{
                color: '#FF6B35',
                fontSize: '28rpx',
                fontWeight: '600',
              }}
            >
              余额 {fenToYuanDisplay(gift_balance_fen)}
            </Text>
          </View>
        )}
      </View>

      {/* Divider */}
      <View
        style={{
          height: '1rpx',
          background: 'rgba(158,181,192,0.12)',
          marginBottom: '32rpx',
        }}
      />

      {/* Action buttons */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '20rpx',
        }}
      >
        {/* 充值 — primary */}
        <View
          style={{
            flex: 1,
            height: '88rpx',
            background: '#FF6B35',
            borderRadius: '44rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4rpx 20rpx rgba(255,107,53,0.4)',
          }}
          onClick={onRecharge}
        >
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '32rpx',
              fontWeight: '700',
            }}
          >
            充值
          </Text>
        </View>

        {/* 消费记录 — secondary */}
        <View
          style={{
            flex: 1,
            height: '88rpx',
            background: 'rgba(158,181,192,0.1)',
            border: '2rpx solid rgba(158,181,192,0.25)',
            borderRadius: '44rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={onViewHistory}
        >
          <Text
            style={{
              color: '#9EB5C0',
              fontSize: '30rpx',
              fontWeight: '600',
            }}
          >
            消费记录
          </Text>
        </View>
      </View>
    </View>
  )
}

export default StoredValueCard
