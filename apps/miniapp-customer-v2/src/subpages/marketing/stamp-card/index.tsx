/**
 * stamp-card/index.tsx — 集章卡
 *
 * Features:
 *  - Activity selector (if multiple active stamp_card campaigns)
 *  - Visual N×M stamp grid: earned = brand-color filled ✓ circle; empty = dashed circle
 *  - Stamp count display: "已集 X/N 个章"
 *  - How-to-earn & reward preview sections
 *  - Rules section (valid period, conditions)
 *  - Redeem button (enabled when earnedStamps === totalStamps)
 *  - POST redeem → confetti animation + reward display modal
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getStampCard, getActivities } from '../../api/growth'
import type { StampCard, Activity } from '../../api/growth'
import { txRequest } from '../../utils/request'

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
  success: '#4CAF50',
  white: '#fff',
} as const

// ─── Confetti animation ───────────────────────────────────────────────────────

function ConfettiOverlay({ visible }: { visible: boolean }) {
  if (!visible) return null

  // Simple confetti dots using absolute-positioned boxes with CSS animation
  const dots = Array.from({ length: 20 }, (_, i) => ({
    id: i,
    left: `${Math.random() * 100}%`,
    color: [C.primary, '#FFD700', '#4CAF50', '#2196F3', '#E91E63'][i % 5],
    delay: `${Math.random() * 0.5}s`,
    size: `${16 + Math.random() * 16}rpx`,
  }))

  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        pointerEvents: 'none',
        overflow: 'hidden',
      }}
    >
      {dots.map((d) => (
        <View
          key={d.id}
          style={{
            position: 'absolute',
            top: '-20rpx',
            left: d.left,
            width: d.size,
            height: d.size,
            borderRadius: '50%',
            background: d.color,
            animation: `fall 1.5s ${d.delay} ease-in forwards`,
          }}
        />
      ))}
    </View>
  )
}

// ─── Reward modal ─────────────────────────────────────────────────────────────

interface RewardModalProps {
  visible: boolean
  rewardDesc: string
  onClose: () => void
}

function RewardModal({ visible, rewardDesc, onClose }: RewardModalProps) {
  if (!visible) return null
  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 300,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <View
        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.7)' }}
        onClick={onClose}
      />
      <View
        style={{
          position: 'relative',
          background: C.bgCard,
          borderRadius: '32rpx',
          padding: '56rpx 48rpx 48rpx',
          width: '560rpx',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '24rpx',
          border: `2rpx solid ${C.primary}`,
        }}
      >
        <Text style={{ fontSize: '72rpx', lineHeight: '1' }}>🎉</Text>
        <Text style={{ color: C.text1, fontSize: '34rpx', fontWeight: '800', textAlign: 'center' }}>
          兑换成功！
        </Text>
        <Text style={{ color: C.text2, fontSize: '28rpx', textAlign: 'center' }}>
          您已获得：{rewardDesc}
        </Text>
        <Text style={{ color: C.text3, fontSize: '24rpx', textAlign: 'center' }}>
          奖励将在订单结算时自动生效
        </Text>
        <View
          style={{
            background: C.primary,
            borderRadius: '48rpx',
            padding: '20rpx 64rpx',
            marginTop: '8rpx',
          }}
          onClick={onClose}
        >
          <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>知道了</Text>
        </View>
      </View>
    </View>
  )
}

// ─── Stamp grid ───────────────────────────────────────────────────────────────

interface StampGridProps {
  total: number
  earned: number
}

function StampGrid({ total, earned }: StampGridProps) {
  // Determine columns: prefer 3 cols, unless total is a perfect square like 16
  const cols = total <= 6 ? 3 : total <= 9 ? 3 : total <= 16 ? 4 : 5
  const cellSize = cols === 3 ? '160rpx' : cols === 4 ? '140rpx' : '110rpx'

  return (
    <View
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, ${cellSize})`,
        gap: '20rpx',
        justifyContent: 'center',
        padding: '8rpx 0',
      }}
    >
      {Array.from({ length: total }, (_, i) => {
        const isEarned = i < earned
        return (
          <View
            key={i}
            style={{
              width: cellSize,
              height: cellSize,
              borderRadius: '50%',
              border: isEarned ? 'none' : `3rpx dashed ${C.border}`,
              background: isEarned
                ? `radial-gradient(circle at 35% 35%, #FF8F5C, ${C.primary})`
                : 'transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: isEarned ? `0 4rpx 16rpx rgba(255,107,44,0.4)` : 'none',
              transition: 'background 0.3s',
            }}
          >
            {isEarned ? (
              <Text
                style={{
                  color: C.white,
                  fontSize: cols === 3 ? '52rpx' : '40rpx',
                  fontWeight: '800',
                  lineHeight: '1',
                }}
              >
                ✓
              </Text>
            ) : (
              <Text
                style={{
                  color: C.border,
                  fontSize: cols === 3 ? '40rpx' : '30rpx',
                  lineHeight: '1',
                }}
              >
                ★
              </Text>
            )}
          </View>
        )
      })}
    </View>
  )
}

// ─── Activity selector ────────────────────────────────────────────────────────

interface ActivitySelectorProps {
  activities: Activity[]
  selectedId: string
  onSelect: (id: string) => void
}

function ActivitySelector({ activities, selectedId, onSelect }: ActivitySelectorProps) {
  if (activities.length <= 1) return null
  return (
    <ScrollView scrollX style={{ marginBottom: '24rpx' }}>
      <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx', padding: '4rpx 0' }}>
        {activities.map((act) => {
          const isSelected = act.activityId === selectedId
          return (
            <View
              key={act.activityId}
              style={{
                flexShrink: 0,
                padding: '16rpx 28rpx',
                borderRadius: '48rpx',
                background: isSelected ? C.primary : C.bgCard,
                border: `2rpx solid ${isSelected ? C.primary : C.border}`,
              }}
              onClick={() => onSelect(act.activityId)}
            >
              <Text
                style={{
                  color: isSelected ? C.white : C.text2,
                  fontSize: '26rpx',
                  fontWeight: isSelected ? '700' : '400',
                }}
              >
                {act.name}
              </Text>
            </View>
          )
        })}
      </View>
    </ScrollView>
  )
}

// ─── Info row ─────────────────────────────────────────────────────────────────

function InfoRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: '12rpx',
        padding: '16rpx 0',
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      <Text style={{ fontSize: '28rpx', lineHeight: '1', flexShrink: 0 }}>{icon}</Text>
      <Text style={{ color: C.text3, fontSize: '26rpx', flexShrink: 0, width: '120rpx' }}>
        {label}
      </Text>
      <Text style={{ color: C.text2, fontSize: '26rpx', flex: 1 }}>{value}</Text>
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function StampCardPage() {
  const [stampActivities, setStampActivities] = useState<Activity[]>([])
  const [selectedActivityId, setSelectedActivityId] = useState<string>('')
  const [card, setCard] = useState<StampCard | null>(null)
  const [loading, setLoading] = useState(false)
  const [redeeming, setRedeeming] = useState(false)
  const [showConfetti, setShowConfetti] = useState(false)
  const [showRewardModal, setShowRewardModal] = useState(false)

  // Load stamp activities
  useEffect(() => {
    getActivities()
      .then((acts) => {
        const stampActs = acts.filter((a) => a.type === 'stamp_card' && a.isActive)
        setStampActivities(stampActs)
        if (stampActs.length > 0) {
          setSelectedActivityId(stampActs[0].activityId)
        }
      })
      .catch(() => {})
  }, [])

  // Load stamp card when activity changes
  useEffect(() => {
    if (!selectedActivityId) return
    setLoading(true)
    getStampCard(selectedActivityId)
      .then((data) => setCard(data))
      .catch(() => setCard(null))
      .finally(() => setLoading(false))
  }, [selectedActivityId])

  const handleRedeem = useCallback(async () => {
    if (!card || redeeming) return
    setRedeeming(true)
    try {
      await txRequest<unknown>(`/api/v1/stamp-cards/${encodeURIComponent(card.cardId)}/redeem`, 'POST')
      // Refresh card
      const updated = await getStampCard(selectedActivityId)
      setCard(updated)
      setShowConfetti(true)
      setShowRewardModal(true)
      setTimeout(() => setShowConfetti(false), 2000)
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '兑换失败', icon: 'none', duration: 2000 })
    } finally {
      setRedeeming(false)
    }
  }, [card, redeeming, selectedActivityId])

  const canRedeem =
    card !== null &&
    card.status === 'in_progress' &&
    card.earnedStamps >= card.totalStamps

  // Format date helper
  function fmtDate(iso: string) {
    if (!iso) return ''
    return iso.slice(0, 10)
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ConfettiOverlay visible={showConfetti} />
      <RewardModal
        visible={showRewardModal}
        rewardDesc={card?.reward?.description ?? ''}
        onClose={() => setShowRewardModal(false)}
      />

      <ScrollView scrollY style={{ minHeight: '100vh' }}>
        <View style={{ padding: '24rpx 24rpx 80rpx' }}>
          {/* Activity selector */}
          <ActivitySelector
            activities={stampActivities}
            selectedId={selectedActivityId}
            onSelect={setSelectedActivityId}
          />

          {/* Loading */}
          {loading && (
            <View
              style={{
                height: '500rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中…</Text>
            </View>
          )}

          {/* No activities */}
          {!loading && stampActivities.length === 0 && (
            <View
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '80rpx 40rpx',
                gap: '24rpx',
              }}
            >
              <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>🎴</Text>
              <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
                暂无集章活动
              </Text>
              <Text style={{ color: C.text3, fontSize: '26rpx', textAlign: 'center' }}>
                敬请期待新活动上线
              </Text>
            </View>
          )}

          {/* Stamp card */}
          {!loading && card && (
            <>
              {/* Card visual */}
              <View
                style={{
                  background: `linear-gradient(135deg, #1A3040 0%, ${C.bgCard} 100%)`,
                  borderRadius: '28rpx',
                  padding: '40rpx 32rpx',
                  border: `1rpx solid ${C.border}`,
                  marginBottom: '28rpx',
                }}
              >
                {/* Card header */}
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    marginBottom: '32rpx',
                  }}
                >
                  <View>
                    <Text
                      style={{
                        color: C.text1,
                        fontSize: '32rpx',
                        fontWeight: '700',
                        display: 'block',
                      }}
                    >
                      {card.activityName}
                    </Text>
                    <Text
                      style={{
                        color: C.text3,
                        fontSize: '24rpx',
                        display: 'block',
                        marginTop: '8rpx',
                      }}
                    >
                      有效期至 {fmtDate(card.validUntil)}
                    </Text>
                  </View>
                  {/* Progress badge */}
                  <View
                    style={{
                      background: 'rgba(255,107,44,0.15)',
                      borderRadius: '12rpx',
                      padding: '8rpx 20rpx',
                      border: `1rpx solid rgba(255,107,44,0.3)`,
                    }}
                  >
                    <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '700' }}>
                      {card.earnedStamps}/{card.totalStamps}
                    </Text>
                  </View>
                </View>

                {/* Stamp grid */}
                <StampGrid total={card.totalStamps} earned={card.earnedStamps} />

                {/* Stamp count */}
                <Text
                  style={{
                    color: C.text2,
                    fontSize: '26rpx',
                    textAlign: 'center',
                    display: 'block',
                    marginTop: '28rpx',
                  }}
                >
                  已集{' '}
                  <Text style={{ color: C.primary, fontWeight: '700' }}>
                    {card.earnedStamps}
                  </Text>
                  /{card.totalStamps} 个章
                </Text>

                {/* Progress bar */}
                <View
                  style={{
                    marginTop: '20rpx',
                    height: '8rpx',
                    borderRadius: '4rpx',
                    background: C.bgHover,
                    overflow: 'hidden',
                  }}
                >
                  <View
                    style={{
                      height: '100%',
                      borderRadius: '4rpx',
                      background: C.primary,
                      width: `${(card.earnedStamps / card.totalStamps) * 100}%`,
                      transition: 'width 0.4s ease',
                    }}
                  />
                </View>
              </View>

              {/* How to earn */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '28rpx',
                  marginBottom: '20rpx',
                  border: `1rpx solid ${C.border}`,
                }}
              >
                <Text
                  style={{
                    color: C.text1,
                    fontSize: '28rpx',
                    fontWeight: '700',
                    display: 'block',
                    marginBottom: '16rpx',
                  }}
                >
                  📖 如何获得章
                </Text>
                <View
                  style={{
                    background: 'rgba(255,107,44,0.08)',
                    borderRadius: '12rpx',
                    padding: '20rpx 24rpx',
                  }}
                >
                  <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.7' }}>
                    每消费满 30 元得 1 个章
                  </Text>
                  <Text
                    style={{
                      color: C.text3,
                      fontSize: '24rpx',
                      lineHeight: '1.7',
                      display: 'block',
                      marginTop: '8rpx',
                    }}
                  >
                    消费后系统自动发放，不可叠加使用优惠券
                  </Text>
                </View>
              </View>

              {/* Reward preview */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '28rpx',
                  marginBottom: '20rpx',
                  border: `1rpx solid ${C.border}`,
                }}
              >
                <Text
                  style={{
                    color: C.text1,
                    fontSize: '28rpx',
                    fontWeight: '700',
                    display: 'block',
                    marginBottom: '16rpx',
                  }}
                >
                  🎁 集满可兑换
                </Text>
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    alignItems: 'center',
                    gap: '16rpx',
                    background: `linear-gradient(90deg, rgba(255,107,44,0.12), rgba(255,107,44,0.04))`,
                    borderRadius: '12rpx',
                    padding: '20rpx 24rpx',
                    border: `1rpx solid rgba(255,107,44,0.2)`,
                  }}
                >
                  <Text style={{ fontSize: '40rpx', lineHeight: '1', flexShrink: 0 }}>🏆</Text>
                  <Text
                    style={{ color: C.primary, fontSize: '28rpx', fontWeight: '600', flex: 1 }}
                  >
                    {card.reward.description}
                  </Text>
                </View>
              </View>

              {/* Rules */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '28rpx',
                  marginBottom: '32rpx',
                  border: `1rpx solid ${C.border}`,
                }}
              >
                <Text
                  style={{
                    color: C.text1,
                    fontSize: '28rpx',
                    fontWeight: '700',
                    display: 'block',
                    marginBottom: '8rpx',
                  }}
                >
                  📋 活动规则
                </Text>
                <InfoRow icon="📅" label="有效期" value={`${fmtDate(card.startedAt)} 至 ${fmtDate(card.validUntil)}`} />
                <InfoRow icon="🏷️" label="集章条件" value="每消费满30元得1章，不设上限" />
                <InfoRow icon="🔄" label="兑换规则" value="集满后方可兑换，奖励一次性发放" />
                <InfoRow icon="⚠️" label="注意事项" value="过期未集满的章不予保留" />
              </View>

              {/* Redeem button */}
              <View
                style={{
                  background: canRedeem ? C.primary : C.bgCard,
                  borderRadius: '20rpx',
                  padding: '28rpx',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: `2rpx solid ${canRedeem ? C.primary : C.border}`,
                  opacity: redeeming ? 0.7 : 1,
                }}
                onClick={canRedeem ? handleRedeem : undefined}
              >
                <Text
                  style={{
                    color: canRedeem ? C.white : C.text3,
                    fontSize: '32rpx',
                    fontWeight: '700',
                  }}
                >
                  {card.status === 'redeemed'
                    ? '✅ 已兑换'
                    : card.status === 'expired'
                    ? '已过期'
                    : canRedeem
                    ? redeeming
                      ? '兑换中…'
                      : '🎉 立即兑换奖励'
                    : `还差 ${card.totalStamps - card.earnedStamps} 章可兑换`}
                </Text>
              </View>

              {/* Status disabled hint */}
              {(card.status === 'redeemed' || card.status === 'expired') && (
                <Text
                  style={{
                    color: C.text3,
                    fontSize: '24rpx',
                    textAlign: 'center',
                    display: 'block',
                    marginTop: '16rpx',
                  }}
                >
                  {card.status === 'redeemed' ? '奖励已发放至您的账户' : '本期集章已过期'}
                </Text>
              )}
            </>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
