/**
 * PointsBalance — member points display card
 *
 * Shows:
 *  - Large coin icon + current points number
 *  - "可兑换 ¥XX.XX" (100 pts = ¥1)
 *  - Optional progress bar toward next level
 *  - "去使用" link button
 */
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import React, { useMemo } from 'react'
import { fenToYuanDisplay } from '../../utils/format'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PointsBalanceProps {
  points: number
  nextLevelPoints?: number
  level: string
  onUse?: () => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const POINTS_PER_YUAN = 100

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatPoints(pts: number): string {
  if (pts >= 100_000) return (pts / 10000).toFixed(1) + 'w'
  return pts.toLocaleString()
}

function pointsToYuan(pts: number): string {
  // 100 points = ¥1  =>  stored as fen: pts / 100 yuan * 100 fen/yuan = pts fen
  return fenToYuanDisplay(pts) // pts directly equal to fen amount
}

// ─── Component ────────────────────────────────────────────────────────────────

const PointsBalance: React.FC<PointsBalanceProps> = ({
  points,
  nextLevelPoints,
  level,
  onUse,
}) => {
  const progressPct = useMemo(() => {
    if (!nextLevelPoints || nextLevelPoints <= 0) return null
    const pct = Math.min(100, Math.round((points / nextLevelPoints) * 100))
    return pct
  }, [points, nextLevelPoints])

  const remaining = nextLevelPoints ? Math.max(0, nextLevelPoints - points) : null

  const handleUse = () => {
    if (onUse) {
      onUse()
    } else {
      Taro.navigateTo({ url: '/pages/member/points' })
    }
  }

  return (
    <View
      style={{
        background: 'linear-gradient(135deg, #1A2E38 0%, #0F1F28 100%)',
        borderRadius: '24rpx',
        padding: '40rpx 32rpx 36rpx',
        border: '2rpx solid #1E3340',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Decorative background circle */}
      <View
        style={{
          position: 'absolute',
          right: '-60rpx',
          top: '-60rpx',
          width: '280rpx',
          height: '280rpx',
          borderRadius: '140rpx',
          background: 'rgba(255,107,53,0.06)',
          pointerEvents: 'none',
        }}
      />

      {/* Header row: level badge + "去使用" */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '32rpx',
        }}
      >
        {/* Level badge */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '8rpx',
            background: 'rgba(255,107,53,0.15)',
            borderRadius: '32rpx',
            padding: '6rpx 20rpx',
          }}
        >
          <Text style={{ fontSize: '26rpx', lineHeight: '1' }}>✦</Text>
          <Text
            style={{
              color: '#FF6B35',
              fontSize: '26rpx',
              fontWeight: '600',
            }}
          >
            {level}
          </Text>
        </View>

        {/* 去使用 button */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '4rpx',
            minHeight: '88rpx',
            padding: '0 8rpx',
          }}
          onClick={handleUse}
        >
          <Text
            style={{
              color: '#FF6B35',
              fontSize: '28rpx',
              fontWeight: '600',
            }}
          >
            去使用
          </Text>
          <Text
            style={{
              color: '#FF6B35',
              fontSize: '28rpx',
              lineHeight: '1',
            }}
          >
            ›
          </Text>
        </View>
      </View>

      {/* Main points display */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-end',
          gap: '16rpx',
          marginBottom: '16rpx',
        }}
      >
        {/* Coin icon */}
        <View
          style={{
            width: '80rpx',
            height: '80rpx',
            borderRadius: '40rpx',
            background: 'linear-gradient(145deg, #FFD700 0%, #FF9F0A 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4rpx 16rpx rgba(255,159,10,0.4)',
            flexShrink: 0,
            marginBottom: '8rpx',
          }}
        >
          <Text style={{ fontSize: '44rpx', lineHeight: '1' }}>🪙</Text>
        </View>

        {/* Points number */}
        <View>
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '72rpx',
              fontWeight: '800',
              lineHeight: '1',
              letterSpacing: '-2rpx',
            }}
          >
            {formatPoints(points)}
          </Text>
          <Text
            style={{
              color: '#9EB5C0',
              fontSize: '26rpx',
              marginLeft: '4rpx',
            }}
          >
            {' '}积分
          </Text>
        </View>
      </View>

      {/* 可兑换 */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '8rpx',
          marginBottom: progressPct !== null ? '32rpx' : '0',
        }}
      >
        <Text style={{ color: '#9EB5C0', fontSize: '26rpx' }}>可兑换</Text>
        <Text
          style={{
            color: '#FF6B35',
            fontSize: '26rpx',
            fontWeight: '600',
          }}
        >
          {pointsToYuan(points)}
        </Text>
        <Text style={{ color: '#9EB5C0', fontSize: '24rpx' }}>（100积分 = ¥1）</Text>
      </View>

      {/* Progress bar to next level */}
      {progressPct !== null && nextLevelPoints !== undefined && (
        <View>
          {/* Label row */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '12rpx',
            }}
          >
            <Text style={{ color: '#9EB5C0', fontSize: '24rpx' }}>距下一等级</Text>
            <Text
              style={{
                color: '#9EB5C0',
                fontSize: '24rpx',
              }}
            >
              还需{' '}
              <Text style={{ color: '#FF6B35', fontWeight: '600' }}>
                {remaining?.toLocaleString()}
              </Text>{' '}
              积分
            </Text>
          </View>

          {/* Track */}
          <View
            style={{
              width: '100%',
              height: '12rpx',
              background: '#1E3340',
              borderRadius: '6rpx',
              overflow: 'hidden',
            }}
          >
            {/* Fill */}
            <View
              style={{
                height: '12rpx',
                width: `${progressPct}%`,
                background: 'linear-gradient(90deg, #FF6B35 0%, #FF9F0A 100%)',
                borderRadius: '6rpx',
                transition: 'width 0.5s ease',
              }}
            />
          </View>

          {/* Percentage */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'flex-end',
              marginTop: '8rpx',
            }}
          >
            <Text style={{ color: '#4A6572', fontSize: '22rpx' }}>{progressPct}%</Text>
          </View>
        </View>
      )}
    </View>
  )
}

export default PointsBalance
