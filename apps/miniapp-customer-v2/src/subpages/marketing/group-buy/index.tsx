/**
 * group-buy/index.tsx — 团购活动
 *
 * Three sections:
 *  1. Active group-buy activity list:
 *       - Dish image / name / group price (brand) / original price (strikethrough)
 *       - "X人成团" + current participants + progress bar
 *       - "发起拼单" → POST join → creates group → shows share poster
 *       - "参与拼单" → shown if URL param groupId exists
 *
 *  2. Ongoing groups (user is in):
 *       - Status badge: 拼单中 / 已成团 / 已失败
 *       - Countdown timer
 *       - Share button
 *
 *  3. My history: past group-buys
 *
 * URL params: groupId (pre-fill "join" mode)
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, ScrollView, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { joinGroupBuy, getActivities } from '../../api/growth'
import type { Activity, GroupBuyGroup, GroupBuyStatus } from '../../api/growth'
import { fenToYuanDisplay } from '../../utils/format'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  success: '#4CAF50',
  red: '#E53935',
  white: '#fff',
} as const

// ─── Type augment for activity with group-buy metadata ────────────────────────

interface GroupBuyActivity extends Activity {
  groupPriceFen?: number
  originalPriceFen?: number
  requiredParticipants?: number
  currentActiveGroups?: number
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<GroupBuyStatus, { label: string; color: string; bg: string }> = {
  recruiting: { label: '拼单中', color: C.primary, bg: 'rgba(255,107,53,0.15)' },
  full:       { label: '已满员', color: C.success, bg: 'rgba(76,175,80,0.15)' },
  success:    { label: '已成团', color: C.success, bg: 'rgba(76,175,80,0.15)' },
  failed:     { label: '已失败', color: C.red,     bg: 'rgba(229,57,53,0.15)' },
  cancelled:  { label: '已取消', color: C.text3,   bg: 'rgba(90,122,136,0.1)' },
}

function StatusBadge({ status }: { status: GroupBuyStatus }) {
  const cfg = STATUS_CONFIG[status]
  return (
    <View
      style={{
        display: 'inline-flex',
        background: cfg.bg,
        borderRadius: '8rpx',
        padding: '6rpx 14rpx',
      }}
    >
      <Text style={{ color: cfg.color, fontSize: '22rpx', fontWeight: '700' }}>{cfg.label}</Text>
    </View>
  )
}

// ─── Countdown hook ───────────────────────────────────────────────────────────

function useCountdown(expiresAt: string): string {
  const [remaining, setRemaining] = useState('')

  useEffect(() => {
    function calc() {
      const diff = new Date(expiresAt).getTime() - Date.now()
      if (diff <= 0) {
        setRemaining('已结束')
        return
      }
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setRemaining(
        `${h > 0 ? `${h}时` : ''}${String(m).padStart(2, '0')}分${String(s).padStart(2, '0')}秒`,
      )
    }
    calc()
    const id = setInterval(calc, 1000)
    return () => clearInterval(id)
  }, [expiresAt])

  return remaining
}

// ─── Ongoing group card ───────────────────────────────────────────────────────

interface OngoingGroupCardProps {
  group: GroupBuyGroup
  onShare: (group: GroupBuyGroup) => void
}

function OngoingGroupCard({ group, onShare }: OngoingGroupCardProps) {
  const countdown = useCountdown(group.expiresAt)
  const pct = (group.currentParticipants / group.requiredParticipants) * 100

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        padding: '28rpx',
        border: `1rpx solid ${C.border}`,
        marginBottom: '16rpx',
      }}
    >
      {/* Header */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16rpx',
        }}
      >
        <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600', flex: 1 }}>
          {group.activityName}
        </Text>
        <StatusBadge status={group.status} />
      </View>

      {/* Participants + countdown */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          justifyContent: 'space-between',
          marginBottom: '16rpx',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>
          {group.currentParticipants}/{group.requiredParticipants} 人
        </Text>
        {group.status === 'recruiting' && (
          <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '600' }}>
            ⏱ 剩余 {countdown}
          </Text>
        )}
      </View>

      {/* Progress bar */}
      <View
        style={{
          height: '8rpx',
          borderRadius: '4rpx',
          background: C.bgHover,
          overflow: 'hidden',
          marginBottom: '20rpx',
        }}
      >
        <View
          style={{
            height: '100%',
            borderRadius: '4rpx',
            background: pct >= 100 ? C.success : C.primary,
            width: `${Math.min(pct, 100)}%`,
          }}
        />
      </View>

      {/* Prices + share */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: '12rpx' }}>
          <Text style={{ color: C.primary, fontSize: '32rpx', fontWeight: '800' }}>
            {fenToYuanDisplay(group.groupPriceFen)}
          </Text>
          <Text
            style={{
              color: C.text3,
              fontSize: '24rpx',
              textDecoration: 'line-through',
            }}
          >
            {fenToYuanDisplay(group.originalPriceFen)}
          </Text>
        </View>
        {group.status === 'recruiting' && (
          <View
            style={{
              background: C.bgHover,
              borderRadius: '12rpx',
              padding: '14rpx 28rpx',
              border: `1rpx solid ${C.border}`,
            }}
            onClick={() => onShare(group)}
          >
            <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600' }}>
              📤 邀请好友
            </Text>
          </View>
        )}
      </View>
    </View>
  )
}

// ─── Activity card ────────────────────────────────────────────────────────────

interface ActivityCardProps {
  activity: GroupBuyActivity
  joinGroupId: string | null
  onInitiate: (activity: GroupBuyActivity) => void
  onJoin: (activity: GroupBuyActivity) => void
}

function ActivityCard({ activity, joinGroupId, onInitiate, onJoin }: ActivityCardProps) {
  const groupPrice = activity.groupPriceFen ?? 0
  const origPrice = activity.originalPriceFen ?? 0
  const required = activity.requiredParticipants ?? 2
  const current = activity.currentActiveGroups ?? 0

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '24rpx',
        overflow: 'hidden',
        border: `1rpx solid ${C.border}`,
        marginBottom: '20rpx',
      }}
    >
      {/* Dish image */}
      {activity.imageUrl ? (
        <Image
          src={activity.imageUrl}
          style={{ width: '100%', height: '320rpx', display: 'block', objectFit: 'cover' }}
          mode="aspectFill"
        />
      ) : (
        <View
          style={{
            width: '100%',
            height: '320rpx',
            background: C.bgHover,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>🍽️</Text>
        </View>
      )}

      {/* Badge overlay */}
      {activity.badgeText && (
        <View
          style={{
            position: 'absolute',
            top: '16rpx',
            left: '16rpx',
            background: C.primary,
            borderRadius: '8rpx',
            padding: '6rpx 16rpx',
          }}
        >
          <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '700' }}>
            {activity.badgeText}
          </Text>
        </View>
      )}

      <View style={{ padding: '28rpx' }}>
        {/* Name */}
        <Text
          style={{
            color: C.text1,
            fontSize: '32rpx',
            fontWeight: '700',
            display: 'block',
            marginBottom: '12rpx',
          }}
        >
          {activity.name}
        </Text>

        {/* Price row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'baseline',
            gap: '16rpx',
            marginBottom: '16rpx',
          }}
        >
          <Text style={{ color: C.primary, fontSize: '40rpx', fontWeight: '800' }}>
            {fenToYuanDisplay(groupPrice)}
          </Text>
          {origPrice > 0 && (
            <Text
              style={{
                color: C.text3,
                fontSize: '26rpx',
                textDecoration: 'line-through',
              }}
            >
              {fenToYuanDisplay(origPrice)}
            </Text>
          )}
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>
            /{required}人成团
          </Text>
        </View>

        {/* Participant info + progress */}
        <View style={{ marginBottom: '20rpx' }}>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              marginBottom: '10rpx',
            }}
          >
            <Text style={{ color: C.text3, fontSize: '24rpx' }}>
              已有 {current} 个拼单进行中
            </Text>
            <Text style={{ color: C.text2, fontSize: '24rpx' }}>
              {required}人成团
            </Text>
          </View>
          <View
            style={{
              height: '6rpx',
              borderRadius: '3rpx',
              background: C.bgHover,
              overflow: 'hidden',
            }}
          >
            <View
              style={{
                height: '100%',
                borderRadius: '3rpx',
                background: C.primary,
                width: `${Math.min((current / Math.max(required, 1)) * 60, 100)}%`,
              }}
            />
          </View>
        </View>

        {/* CTA buttons */}
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          {joinGroupId ? (
            // Join mode — someone shared a link
            <View
              style={{
                flex: 1,
                background: C.primary,
                borderRadius: '12rpx',
                padding: '20rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={() => onJoin(activity)}
            >
              <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>
                参与拼单
              </Text>
            </View>
          ) : (
            <>
              <View
                style={{
                  flex: 1,
                  background: C.primary,
                  borderRadius: '12rpx',
                  padding: '20rpx',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                onClick={() => onInitiate(activity)}
              >
                <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>
                  发起拼单
                </Text>
              </View>
              {current > 0 && (
                <View
                  style={{
                    flex: 1,
                    background: C.bgHover,
                    borderRadius: '12rpx',
                    padding: '20rpx',
                    border: `1rpx solid ${C.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                  onClick={() => onJoin(activity)}
                >
                  <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
                    参与拼单
                  </Text>
                </View>
              )}
            </>
          )}
        </View>
      </View>
    </View>
  )
}

// ─── Share modal ──────────────────────────────────────────────────────────────

interface ShareModalProps {
  visible: boolean
  group: GroupBuyGroup | null
  onClose: () => void
}

function ShareModal({ visible, group, onClose }: ShareModalProps) {
  if (!visible || !group) return null

  const handleShare = () => {
    Taro.shareAppMessage({
      title: `来和我一起拼单吧！${group.activityName} 仅需 ${fenToYuanDisplay(group.groupPriceFen)}`,
      path: `/subpackages/marketing/group-buy/index?groupId=${group.groupId}`,
    })
    onClose()
  }

  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 500,
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
          padding: '48rpx 40rpx',
          width: '560rpx',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '28rpx',
        }}
      >
        <Text style={{ fontSize: '60rpx', lineHeight: '1' }}>📤</Text>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', textAlign: 'center' }}>
          邀请好友参与拼单
        </Text>
        <View
          style={{
            background: C.bgHover,
            borderRadius: '16rpx',
            padding: '20rpx 24rpx',
            width: '100%',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '26rpx', textAlign: 'center', display: 'block' }}>
            {group.activityName}
          </Text>
          <Text
            style={{
              color: C.primary,
              fontSize: '32rpx',
              fontWeight: '800',
              textAlign: 'center',
              display: 'block',
              marginTop: '8rpx',
            }}
          >
            {fenToYuanDisplay(group.groupPriceFen)}/人
          </Text>
          <Text
            style={{
              color: C.text3,
              fontSize: '24rpx',
              textAlign: 'center',
              display: 'block',
              marginTop: '4rpx',
            }}
          >
            还需 {group.requiredParticipants - group.currentParticipants} 人成团
          </Text>
        </View>
        <View
          style={{
            background: C.primary,
            borderRadius: '48rpx',
            padding: '22rpx 64rpx',
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={handleShare}
        >
          <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>分享给好友</Text>
        </View>
        <View onClick={onClose}>
          <Text style={{ color: C.text3, fontSize: '26rpx' }}>取消</Text>
        </View>
      </View>
    </View>
  )
}

// ─── Section header ───────────────────────────────────────────────────────────

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: '12rpx',
        marginBottom: '16rpx',
        marginTop: '8rpx',
      }}
    >
      <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>{title}</Text>
      {sub && <Text style={{ color: C.text3, fontSize: '24rpx' }}>{sub}</Text>}
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function GroupBuyPage() {
  const [activities, setActivities] = useState<GroupBuyActivity[]>([])
  const [ongoingGroups, setOngoingGroups] = useState<GroupBuyGroup[]>([])
  const [historyGroups, setHistoryGroups] = useState<GroupBuyGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [joining, setJoining] = useState<string | null>(null)
  const [shareTarget, setShareTarget] = useState<GroupBuyGroup | null>(null)

  // groupId from URL params (someone shared a link)
  const joinGroupId = useRef<string | null>(null)

  useEffect(() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    joinGroupId.current = (params.groupId as string) ?? null
  }, [])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      getActivities(),
      txRequest<GroupBuyGroup[]>('/api/v1/group-buy/my-groups').catch(() => []),
    ])
      .then(([acts, myGroups]) => {
        const gbActs = acts.filter((a) => a.type === 'group_buy' && a.isActive)
        setActivities(gbActs as GroupBuyActivity[])

        const ongoing = (myGroups as GroupBuyGroup[]).filter((g) =>
          ['recruiting', 'full'].includes(g.status),
        )
        const history = (myGroups as GroupBuyGroup[]).filter((g) =>
          ['success', 'failed', 'cancelled'].includes(g.status),
        )
        setOngoingGroups(ongoing)
        setHistoryGroups(history)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleInitiate = useCallback(
    async (activity: GroupBuyActivity) => {
      if (joining) return
      setJoining(activity.activityId)
      try {
        // POST to create a new group for this activity
        const result = await txRequest<GroupBuyGroup>(
          `/api/v1/group-buy/create`,
          'POST',
          { activityId: activity.activityId },
        )
        setOngoingGroups((prev) => [result, ...prev])
        setShareTarget(result)
        Taro.showToast({ title: '拼单创建成功！', icon: 'success', duration: 1500 })
      } catch (err: any) {
        Taro.showToast({ title: err?.message ?? '创建失败', icon: 'none', duration: 2000 })
      } finally {
        setJoining(null)
      }
    },
    [joining],
  )

  const handleJoin = useCallback(
    async (activity: GroupBuyActivity) => {
      const groupId = joinGroupId.current
      if (!groupId) {
        // No specific group — let server pick the best one
        setJoining(activity.activityId)
        try {
          const result = await txRequest<GroupBuyGroup>(
            `/api/v1/group-buy/join-any`,
            'POST',
            { activityId: activity.activityId },
          )
          setOngoingGroups((prev) => {
            const exists = prev.find((g) => g.groupId === result.groupId)
            return exists ? prev : [result, ...prev]
          })
          Taro.showToast({ title: '已加入拼单！', icon: 'success', duration: 1500 })
        } catch (err: any) {
          Taro.showToast({ title: err?.message ?? '加入失败', icon: 'none', duration: 2000 })
        } finally {
          setJoining(null)
        }
        return
      }
      setJoining(groupId)
      try {
        await joinGroupBuy(groupId)
        // Refresh my groups
        const myGroups = await txRequest<GroupBuyGroup[]>('/api/v1/group-buy/my-groups')
        const ongoing = (myGroups as GroupBuyGroup[]).filter((g) =>
          ['recruiting', 'full'].includes(g.status),
        )
        setOngoingGroups(ongoing)
        Taro.showToast({ title: '已成功参与拼单！', icon: 'success', duration: 1500 })
        joinGroupId.current = null
      } catch (err: any) {
        Taro.showToast({ title: err?.message ?? '参与失败', icon: 'none', duration: 2000 })
      } finally {
        setJoining(null)
      }
    },
    [],
  )

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ShareModal
        visible={!!shareTarget}
        group={shareTarget}
        onClose={() => setShareTarget(null)}
      />

      <ScrollView scrollY style={{ minHeight: '100vh' }}>
        <View style={{ padding: '24rpx 24rpx 80rpx' }}>
          {loading ? (
            <View
              style={{
                height: '400rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中…</Text>
            </View>
          ) : (
            <>
              {/* Ongoing groups (user is in) */}
              {ongoingGroups.length > 0 && (
                <View style={{ marginBottom: '8rpx' }}>
                  <SectionHeader title="我的拼单" sub={`共 ${ongoingGroups.length} 个`} />
                  {ongoingGroups.map((g) => (
                    <OngoingGroupCard
                      key={g.groupId}
                      group={g}
                      onShare={(group) => setShareTarget(group)}
                    />
                  ))}
                </View>
              )}

              {/* Active activities */}
              <SectionHeader title="团购活动" sub={`${activities.length} 个活动` } />
              {activities.length === 0 ? (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    padding: '60rpx 40rpx',
                    gap: '20rpx',
                    background: C.bgCard,
                    borderRadius: '20rpx',
                    border: `1rpx solid ${C.border}`,
                    marginBottom: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '72rpx', lineHeight: '1' }}>🛒</Text>
                  <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
                    暂无团购活动
                  </Text>
                  <Text style={{ color: C.text3, fontSize: '26rpx', textAlign: 'center' }}>
                    新活动即将上线，敬请期待
                  </Text>
                </View>
              ) : (
                <View style={{ position: 'relative' }}>
                  {activities.map((act) => (
                    <ActivityCard
                      key={act.activityId}
                      activity={act}
                      joinGroupId={joinGroupId.current}
                      onInitiate={handleInitiate}
                      onJoin={handleJoin}
                    />
                  ))}
                </View>
              )}

              {/* History */}
              {historyGroups.length > 0 && (
                <View style={{ marginTop: '8rpx' }}>
                  <SectionHeader title="历史拼单" />
                  {historyGroups.map((g) => (
                    <View
                      key={g.groupId}
                      style={{
                        background: C.bgCard,
                        borderRadius: '16rpx',
                        padding: '24rpx 28rpx',
                        border: `1rpx solid ${C.border}`,
                        marginBottom: '12rpx',
                        display: 'flex',
                        flexDirection: 'row',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        opacity: 0.7,
                      }}
                    >
                      <View>
                        <Text
                          style={{
                            color: C.text2,
                            fontSize: '26rpx',
                            fontWeight: '600',
                            display: 'block',
                          }}
                        >
                          {g.activityName}
                        </Text>
                        <Text
                          style={{
                            color: C.text3,
                            fontSize: '22rpx',
                            display: 'block',
                            marginTop: '6rpx',
                          }}
                        >
                          {g.currentParticipants}/{g.requiredParticipants} 人 · {fenToYuanDisplay(g.groupPriceFen)}/人
                        </Text>
                      </View>
                      <StatusBadge status={g.status} />
                    </View>
                  ))}
                </View>
              )}
            </>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
