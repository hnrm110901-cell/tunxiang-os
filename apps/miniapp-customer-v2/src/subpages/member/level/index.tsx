/**
 * level/index.tsx — 会员等级页
 *
 * Features:
 *  - Gradient hero card with current level color, masked card number,
 *    current points, next-level threshold, and progress bar
 *  - 4-tier level ladder (bronze → silver → gold → diamond)
 *  - Benefits comparison grid
 *  - Member QR code section with refresh
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getMemberLevel } from '../../../api/member'
import { useUserStore } from '../../../store/useUserStore'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#4A6572',
  white: '#FFFFFF',
} as const

// ─── Level definitions ────────────────────────────────────────────────────────

type LevelKey = 'bronze' | 'silver' | 'gold' | 'diamond'

interface LevelDef {
  key: LevelKey
  label: string
  icon: string
  color: string
  gradientStart: string
  gradientEnd: string
  borderColor: string
  minPoints: number
  maxPoints: number | null
  condition: string
  keyBenefit: string
  discount: string
  birthdayBonus: boolean
  freeDelivery: boolean
  priorityService: boolean
  monthlyGift: boolean
  exclusiveCs: boolean
}

const LEVELS: LevelDef[] = [
  {
    key: 'bronze',
    label: '铜牌会员',
    icon: '🥉',
    color: '#CD7F32',
    gradientStart: '#2A1A0E',
    gradientEnd: '#1A0F08',
    borderColor: 'rgba(205,127,50,0.5)',
    minPoints: 0,
    maxPoints: 999,
    condition: '0 – 999 积分',
    keyBenefit: '95折优惠',
    discount: '95折',
    birthdayBonus: false,
    freeDelivery: false,
    priorityService: false,
    monthlyGift: false,
    exclusiveCs: false,
  },
  {
    key: 'silver',
    label: '银牌会员',
    icon: '🥈',
    color: '#C0C0C0',
    gradientStart: '#1E2226',
    gradientEnd: '#141618',
    borderColor: 'rgba(192,192,192,0.5)',
    minPoints: 1000,
    maxPoints: 4999,
    condition: '1000 – 4999 积分',
    keyBenefit: '9折 + 生日双倍积分',
    discount: '9折',
    birthdayBonus: true,
    freeDelivery: false,
    priorityService: false,
    monthlyGift: false,
    exclusiveCs: false,
  },
  {
    key: 'gold',
    label: '金牌会员',
    icon: '🥇',
    color: '#FFD700',
    gradientStart: '#2A2000',
    gradientEnd: '#1A1400',
    borderColor: 'rgba(255,215,0,0.5)',
    minPoints: 5000,
    maxPoints: 19999,
    condition: '5000 – 19999 积分',
    keyBenefit: '85折 + 专属客服 + 免配送费',
    discount: '85折',
    birthdayBonus: true,
    freeDelivery: true,
    priorityService: false,
    monthlyGift: false,
    exclusiveCs: true,
  },
  {
    key: 'diamond',
    label: '钻石会员',
    icon: '💎',
    color: '#B9F2FF',
    gradientStart: '#0A1E2A',
    gradientEnd: '#061218',
    borderColor: 'rgba(185,242,255,0.5)',
    minPoints: 20000,
    maxPoints: null,
    condition: '20000+ 积分',
    keyBenefit: '8折 + 优先出餐 + 专属礼遇',
    discount: '8折',
    birthdayBonus: true,
    freeDelivery: true,
    priorityService: true,
    monthlyGift: true,
    exclusiveCs: true,
  },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function maskMemberId(id: string): string {
  if (!id || id.length < 4) return `****${id}`
  return `****${id.slice(-4).toUpperCase()}`
}

function getProgressPct(points: number, levelDef: LevelDef): number {
  if (!levelDef.maxPoints) return 100
  const range = levelDef.maxPoints - levelDef.minPoints + 1
  const earned = points - levelDef.minPoints
  return Math.min(100, Math.max(0, Math.round((earned / range) * 100)))
}

function getNextLevelPoints(levelDef: LevelDef): number | null {
  if (!levelDef.maxPoints) return null
  return levelDef.maxPoints + 1
}

const BENEFIT_COLS: { key: keyof LevelDef; label: string }[] = [
  { key: 'discount', label: '折扣' },
  { key: 'birthdayBonus', label: '生日双倍' },
  { key: 'freeDelivery', label: '免配送费' },
  { key: 'exclusiveCs', label: '专属客服' },
  { key: 'priorityService', label: '优先出餐' },
  { key: 'monthlyGift', label: '每月礼遇' },
]

// ─── Sub-components ───────────────────────────────────────────────────────────

interface HeroCardProps {
  levelDef: LevelDef
  points: number
  memberId: string
}

const HeroCard: React.FC<HeroCardProps> = ({ levelDef, points, memberId }) => {
  const nextPoints = getNextLevelPoints(levelDef)
  const pct = getProgressPct(points, levelDef)
  const remaining = nextPoints ? Math.max(0, nextPoints - points) : 0

  return (
    <View
      style={{
        borderRadius: '32rpx',
        background: `linear-gradient(135deg, ${levelDef.gradientStart} 0%, ${levelDef.gradientEnd} 100%)`,
        border: `2rpx solid ${levelDef.borderColor}`,
        padding: '44rpx 36rpx 40rpx',
        margin: '0 0 32rpx',
        position: 'relative',
        overflow: 'hidden',
        boxShadow: `0 8rpx 40rpx rgba(0,0,0,0.5)`,
      }}
    >
      {/* Decorative orb */}
      <View
        style={{
          position: 'absolute',
          right: '-60rpx',
          top: '-60rpx',
          width: '300rpx',
          height: '300rpx',
          borderRadius: '150rpx',
          background: `radial-gradient(circle, ${levelDef.color}22 0%, transparent 70%)`,
          pointerEvents: 'none',
        }}
      />

      {/* Level name */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '16rpx',
          marginBottom: '12rpx',
        }}
      >
        <Text style={{ fontSize: '56rpx', lineHeight: '1' }}>{levelDef.icon}</Text>
        <Text
          style={{
            color: levelDef.color,
            fontSize: '44rpx',
            fontWeight: '800',
            letterSpacing: '2rpx',
          }}
        >
          {levelDef.label}
        </Text>
      </View>

      {/* Card number */}
      <Text
        style={{
          color: 'rgba(158,181,192,0.7)',
          fontSize: '26rpx',
          fontFamily: 'monospace',
          letterSpacing: '4rpx',
          marginBottom: '36rpx',
          display: 'block',
        }}
      >
        会员卡号 {maskMemberId(memberId)}
      </Text>

      {/* Points row */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'baseline',
          gap: '8rpx',
          marginBottom: nextPoints ? '28rpx' : '0',
        }}
      >
        <Text
          style={{
            color: C.white,
            fontSize: '72rpx',
            fontWeight: '800',
            lineHeight: '1',
            letterSpacing: '-2rpx',
          }}
        >
          {points.toLocaleString()}
        </Text>
        <Text style={{ color: C.text2, fontSize: '28rpx' }}>积分</Text>
        {nextPoints && (
          <Text style={{ color: C.text2, fontSize: '26rpx', marginLeft: '8rpx' }}>
            / 距{LEVELS.find(l => l.minPoints === nextPoints)?.label ?? '下一级'} 还需{' '}
            <Text style={{ color: levelDef.color, fontWeight: '700' }}>
              {remaining.toLocaleString()}
            </Text>{' '}
            分
          </Text>
        )}
      </View>

      {/* Progress bar */}
      {nextPoints && (
        <View>
          <View
            style={{
              width: '100%',
              height: '10rpx',
              background: 'rgba(255,255,255,0.1)',
              borderRadius: '5rpx',
              overflow: 'hidden',
              marginBottom: '10rpx',
            }}
          >
            <View
              style={{
                height: '10rpx',
                width: `${pct}%`,
                background: `linear-gradient(90deg, ${levelDef.color}CC 0%, ${levelDef.color} 100%)`,
                borderRadius: '5rpx',
              }}
            />
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'flex-end' }}>
            <Text style={{ color: levelDef.color, fontSize: '22rpx', fontWeight: '600' }}>
              {pct}%
            </Text>
          </View>
        </View>
      )}

      {!nextPoints && (
        <View
          style={{
            background: `${levelDef.color}22`,
            borderRadius: '16rpx',
            padding: '12rpx 24rpx',
            alignSelf: 'flex-start',
            marginTop: '16rpx',
          }}
        >
          <Text style={{ color: levelDef.color, fontSize: '26rpx', fontWeight: '600' }}>
            已达最高等级 ✦
          </Text>
        </View>
      )}
    </View>
  )
}

// ─── Level Ladder ─────────────────────────────────────────────────────────────

interface LevelLadderProps {
  currentLevel: LevelKey
}

const LevelLadder: React.FC<LevelLadderProps> = ({ currentLevel }) => (
  <View style={{ marginBottom: '32rpx' }}>
    <Text
      style={{
        color: C.text1,
        fontSize: '32rpx',
        fontWeight: '700',
        display: 'block',
        marginBottom: '20rpx',
      }}
    >
      等级阶梯
    </Text>

    <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
      {LEVELS.map((lvl) => {
        const isCurrent = lvl.key === currentLevel
        return (
          <View
            key={lvl.key}
            style={{
              background: isCurrent ? `${lvl.gradientStart}` : C.bgCard,
              border: `2rpx solid ${isCurrent ? lvl.borderColor : '#1E3040'}`,
              borderRadius: '24rpx',
              padding: '24rpx 28rpx',
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '20rpx',
            }}
          >
            {/* Icon */}
            <View
              style={{
                width: '88rpx',
                height: '88rpx',
                borderRadius: '44rpx',
                background: `${lvl.color}22`,
                border: `2rpx solid ${lvl.color}55`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Text style={{ fontSize: '48rpx', lineHeight: '1' }}>{lvl.icon}</Text>
            </View>

            {/* Info */}
            <View style={{ flex: 1 }}>
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: '12rpx',
                  marginBottom: '8rpx',
                }}
              >
                <Text style={{ color: lvl.color, fontSize: '30rpx', fontWeight: '700' }}>
                  {lvl.label}
                </Text>
                {isCurrent && (
                  <View
                    style={{
                      background: C.primary,
                      borderRadius: '8rpx',
                      padding: '2rpx 12rpx',
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '20rpx', fontWeight: '600' }}>
                      当前
                    </Text>
                  </View>
                )}
              </View>
              <Text style={{ color: C.text2, fontSize: '24rpx', display: 'block', marginBottom: '4rpx' }}>
                {lvl.condition}
              </Text>
              <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600' }}>
                {lvl.keyBenefit}
              </Text>
            </View>
          </View>
        )
      })}
    </View>
  </View>
)

// ─── Benefits Grid ─────────────────────────────────────────────────────────────

interface BenefitsGridProps {
  currentLevel: LevelKey
}

const BenefitsGrid: React.FC<BenefitsGridProps> = ({ currentLevel }) => (
  <View style={{ marginBottom: '32rpx' }}>
    <Text
      style={{
        color: C.text1,
        fontSize: '32rpx',
        fontWeight: '700',
        display: 'block',
        marginBottom: '20rpx',
      }}
    >
      权益对比
    </Text>

    <View
      style={{
        background: C.bgCard,
        borderRadius: '24rpx',
        overflow: 'hidden',
        border: '2rpx solid #1E3040',
      }}
    >
      {/* Header row */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          background: '#0F1F28',
          borderBottom: '1rpx solid #1E3040',
        }}
      >
        <View style={{ width: '160rpx', padding: '20rpx 16rpx' }}>
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>权益</Text>
        </View>
        {LEVELS.map((lvl) => {
          const isCurrent = lvl.key === currentLevel
          return (
            <View
              key={lvl.key}
              style={{
                flex: 1,
                padding: '16rpx 8rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isCurrent ? `${lvl.color}18` : 'transparent',
              }}
            >
              <Text style={{ fontSize: '28rpx', lineHeight: '1', display: 'block', textAlign: 'center' }}>
                {lvl.icon}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Benefit rows */}
      {BENEFIT_COLS.map((col, rowIdx) => (
        <View
          key={col.key as string}
          style={{
            display: 'flex',
            flexDirection: 'row',
            borderBottom: rowIdx < BENEFIT_COLS.length - 1 ? '1rpx solid #1A2C38' : 'none',
          }}
        >
          <View style={{ width: '160rpx', padding: '20rpx 16rpx', display: 'flex', alignItems: 'center' }}>
            <Text style={{ color: C.text2, fontSize: '24rpx' }}>{col.label}</Text>
          </View>
          {LEVELS.map((lvl) => {
            const isCurrent = lvl.key === currentLevel
            const val = lvl[col.key]
            let display: React.ReactNode
            if (typeof val === 'boolean') {
              display = (
                <Text
                  style={{
                    fontSize: '28rpx',
                    lineHeight: '1',
                    color: val ? '#4CAF50' : '#4A6572',
                  }}
                >
                  {val ? '✓' : '—'}
                </Text>
              )
            } else {
              display = (
                <Text
                  style={{
                    color: isCurrent ? lvl.color : C.text1,
                    fontSize: '24rpx',
                    fontWeight: isCurrent ? '700' : '400',
                    textAlign: 'center',
                  }}
                >
                  {String(val)}
                </Text>
              )
            }
            return (
              <View
                key={lvl.key}
                style={{
                  flex: 1,
                  padding: '20rpx 8rpx',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: isCurrent ? `${lvl.color}10` : 'transparent',
                }}
              >
                {display}
              </View>
            )
          })}
        </View>
      ))}
    </View>
  </View>
)

// ─── QR Section ───────────────────────────────────────────────────────────────

interface QRSectionProps {
  onRefresh: () => void
}

const QRSection: React.FC<QRSectionProps> = ({ onRefresh }) => (
  <View
    style={{
      background: C.bgCard,
      borderRadius: '24rpx',
      border: '2rpx solid #1E3040',
      padding: '40rpx 32rpx',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      marginBottom: '40rpx',
    }}
  >
    <Text
      style={{
        color: C.text1,
        fontSize: '32rpx',
        fontWeight: '700',
        display: 'block',
        marginBottom: '32rpx',
      }}
    >
      会员码
    </Text>

    {/* QR placeholder */}
    <View
      style={{
        width: '320rpx',
        height: '320rpx',
        background: '#1A2E38',
        borderRadius: '20rpx',
        border: '2rpx dashed #2A4558',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: '24rpx',
      }}
    >
      <Text style={{ fontSize: '80rpx', lineHeight: '1', marginBottom: '16rpx' }}>⬛</Text>
      <Text style={{ color: C.text2, fontSize: '24rpx', textAlign: 'center' }}>
        扫码享会员权益
      </Text>
    </View>

    {/* Refresh button */}
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: '8rpx',
        background: 'rgba(255,107,44,0.12)',
        border: '2rpx solid rgba(255,107,44,0.3)',
        borderRadius: '40rpx',
        padding: '16rpx 40rpx',
      }}
      onClick={onRefresh}
    >
      <Text style={{ color: C.primary, fontSize: '28rpx', lineHeight: '1' }}>↻</Text>
      <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '600' }}>刷新会员码</Text>
    </View>
  </View>
)

// ─── Page ─────────────────────────────────────────────────────────────────────

const LevelPage: React.FC = () => {
  const { memberLevel, pointsBalance, userId } = useUserStore()
  const [loading, setLoading] = useState(true)
  const [qrKey, setQrKey] = useState(0)

  useEffect(() => {
    Taro.setNavigationBarTitle({ title: '会员等级' })
    getMemberLevel()
      .catch(() => {/* use store data as fallback */})
      .finally(() => setLoading(false))
  }, [])

  const handleRefreshQr = useCallback(() => {
    setQrKey((k) => k + 1)
    Taro.showToast({ title: '会员码已刷新', icon: 'success', duration: 1500 })
  }, [])

  const currentLevelDef = LEVELS.find((l) => l.key === memberLevel) ?? LEVELS[0]

  return (
    <ScrollView
      scrollY
      style={{ minHeight: '100vh', background: C.bgDeep }}
    >
      <View style={{ padding: '32rpx 32rpx 0' }}>
        {loading ? (
          <View
            style={{
              height: '240rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中…</Text>
          </View>
        ) : (
          <HeroCard
            levelDef={currentLevelDef}
            points={pointsBalance}
            memberId={userId}
          />
        )}

        <LevelLadder currentLevel={memberLevel} />
        <BenefitsGrid currentLevel={memberLevel} />
        <QRSection key={qrKey} onRefresh={handleRefreshQr} />
      </View>
    </ScrollView>
  )
}

export default LevelPage
