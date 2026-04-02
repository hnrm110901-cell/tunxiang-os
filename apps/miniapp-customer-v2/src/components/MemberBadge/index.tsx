import { View, Text } from '@tarojs/components'
import React from 'react'

type MemberLevel = 'bronze' | 'silver' | 'gold' | 'diamond'

interface MemberBadgeProps {
  level: MemberLevel
  points: number
}

interface LevelConfig {
  color: string
  bgColor: string
  borderColor: string
  label: string
  crown: string
}

const LEVEL_CONFIG: Record<MemberLevel, LevelConfig> = {
  bronze: {
    color: '#CD7F32',
    bgColor: 'rgba(205,127,50,0.12)',
    borderColor: 'rgba(205,127,50,0.35)',
    label: '铜牌',
    crown: '👑',
  },
  silver: {
    color: '#C0C0C0',
    bgColor: 'rgba(192,192,192,0.12)',
    borderColor: 'rgba(192,192,192,0.35)',
    label: '银牌',
    crown: '👑',
  },
  gold: {
    color: '#FFD700',
    bgColor: 'rgba(255,215,0,0.12)',
    borderColor: 'rgba(255,215,0,0.35)',
    label: '金牌',
    crown: '♛',
  },
  diamond: {
    color: '#B9F2FF',
    bgColor: 'rgba(185,242,255,0.12)',
    borderColor: 'rgba(185,242,255,0.35)',
    label: '钻石',
    crown: '💎',
  },
}

function formatPoints(pts: number): string {
  if (pts >= 10000) return (pts / 10000).toFixed(1) + 'w'
  return pts.toLocaleString()
}

const MemberBadge: React.FC<MemberBadgeProps> = ({ level, points }) => {
  const cfg = LEVEL_CONFIG[level]

  return (
    <View
      style={{
        display: 'inline-flex',
        flexDirection: 'row',
        alignItems: 'center',
        background: cfg.bgColor,
        border: `2rpx solid ${cfg.borderColor}`,
        borderRadius: '48rpx',
        padding: '8rpx 24rpx',
        gap: '10rpx',
        minHeight: '56rpx',
      }}
    >
      {/* Crown icon */}
      <Text style={{ fontSize: '28rpx', lineHeight: '1' }}>{cfg.crown}</Text>

      {/* Level label */}
      <Text
        style={{
          color: cfg.color,
          fontSize: '26rpx',
          fontWeight: '700',
          letterSpacing: '1rpx',
        }}
      >
        {cfg.label}会员
      </Text>

      {/* Divider */}
      <View
        style={{
          width: '2rpx',
          height: '28rpx',
          background: cfg.borderColor,
        }}
      />

      {/* Points */}
      <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: '4rpx' }}>
        <Text
          style={{
            color: cfg.color,
            fontSize: '28rpx',
            fontWeight: '700',
          }}
        >
          {formatPoints(points)}
        </Text>
        <Text style={{ color: '#9EB5C0', fontSize: '22rpx' }}>积分</Text>
      </View>
    </View>
  )
}

export default MemberBadge
