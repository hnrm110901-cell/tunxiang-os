/**
 * invite/index.tsx — 邀请有礼（老带新）
 *
 * Sections:
 *  1. My referral code — large display, copy, share, QR placeholder
 *  2. Milestone reward tracker — 1/3/5/10 friends
 *  3. Invited friends list — last 10, avatar placeholder, masked nickname, status
 *  4. Rules accordion — collapsible referral rules
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getReferralCode } from '../../../api/growth'
import type { ReferralCode } from '../../../api/growth'
import { txRequest } from '../../../utils/request'
import { useUserStore } from '../../../store/useUserStore'

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
  warning: '#FFC107',
  white: '#FFFFFF',
  gold: '#FFD700',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface InvitedFriend {
  memberId: string
  nickname: string
  joinedAt: string
  hasCompletedFirstOrder: boolean
  rewardIssued: boolean
}

interface InviteStats {
  referralCode: ReferralCode
  invitedFriends: InvitedFriend[]
}

// ─── Milestone definitions ─────────────────────────────────────────────────────

interface Milestone {
  count: number
  label: string
  reward: string
  icon: string
}

const MILESTONES: Milestone[] = [
  { count: 1,  label: '邀请1位好友',  reward: '5元优惠券',          icon: '🎫' },
  { count: 3,  label: '邀请3位好友',  reward: '20元券 + 积分×2一周', icon: '🎁' },
  { count: 5,  label: '邀请5位好友',  reward: '50元储值金',          icon: '💰' },
  { count: 10, label: '邀请10位好友', reward: '钻石会员体验7天',     icon: '💎' },
]

const RULES = [
  '邀请好友通过您的专属链接或二维码注册，即视为成功邀请。',
  '被邀请人须为屯象OS新用户（未注册过账号）。',
  '奖励在被邀请人完成首单后自动发放至您的账户。',
  '邀请数量以完成首单的好友数量计算，仅注册不下单不计入。',
  '各阶段奖励累计发放，不重复叠加（达到3人同时获得1人和3人奖励）。',
  '积分×2活动有效期为触发后7个自然日，届时自动恢复正常倍率。',
  '储值金和优惠券有效期为发放后90天，请及时使用。',
  '平台有权对异常邀请行为（刷单、虚假注册等）取消奖励资格。',
  '本活动最终解释权归屯象OS所有。',
]

// ─── Helper: mask nickname ─────────────────────────────────────────────────────

function maskNickname(nickname: string): string {
  if (!nickname) return '***'
  if (nickname.length <= 1) return nickname + '**'
  if (nickname.length === 2) return nickname[0] + '*'
  return nickname[0] + '*'.repeat(nickname.length - 2) + nickname[nickname.length - 1]
}

function formatRelativeTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = Date.now()
  const diff = Math.floor((now - d.getTime()) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface ReferralHeroProps {
  referralCode: ReferralCode | null
  loading: boolean
  onShare: () => void
}

function ReferralHero({ referralCode, loading, onShare }: ReferralHeroProps) {
  const handleCopy = useCallback(() => {
    if (!referralCode?.code) return
    Taro.setClipboardData({ data: referralCode.code })
      .then(() => Taro.showToast({ title: '邀请码已复制', icon: 'success', duration: 1500 }))
      .catch(() => Taro.showToast({ title: '复制失败', icon: 'none', duration: 1500 }))
  }, [referralCode?.code])

  return (
    <View
      style={{
        margin: '24rpx 24rpx 0',
        background: `linear-gradient(135deg, #1A2E3A 0%, ${C.bgCard} 100%)`,
        borderRadius: '28rpx',
        border: `1rpx solid ${C.border}`,
        overflow: 'hidden',
      }}
    >
      {/* Header strip */}
      <View
        style={{
          background: C.primary,
          padding: '20rpx 32rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '700' }}>
          我的专属邀请码
        </Text>
        <Text style={{ color: 'rgba(255,255,255,0.85)', fontSize: '24rpx' }}>
          邀请好友 · 共享福利
        </Text>
      </View>

      {/* Code + QR row */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '32rpx',
          gap: '32rpx',
        }}
      >
        {/* Code block */}
        <View style={{ flex: 1 }}>
          <Text style={{ color: C.text3, fontSize: '22rpx', marginBottom: '12rpx', display: 'block' }}>
            您的邀请码
          </Text>

          {/* Large code display */}
          <View
            style={{
              background: C.bgDeep,
              borderRadius: '16rpx',
              padding: '20rpx 24rpx',
              border: `2rpx solid ${C.primary}`,
              marginBottom: '20rpx',
            }}
          >
            <Text
              style={{
                color: C.primary,
                fontSize: '48rpx',
                fontWeight: '800',
                letterSpacing: '8rpx',
                fontFamily: 'monospace',
              }}
            >
              {loading ? '加载中…' : (referralCode?.code ?? '------')}
            </Text>
          </View>

          {/* Copy + Share buttons */}
          <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
            <View
              onClick={handleCopy}
              style={{
                flex: 1,
                background: C.bgHover,
                borderRadius: '40rpx',
                padding: '16rpx 0',
                textAlign: 'center',
                border: `1rpx solid ${C.border}`,
              }}
            >
              <Text style={{ color: C.text2, fontSize: '26rpx' }}>复制邀请码</Text>
            </View>
            <View
              onClick={onShare}
              style={{
                flex: 1,
                background: C.primary,
                borderRadius: '40rpx',
                padding: '16rpx 0',
                textAlign: 'center',
              }}
            >
              <Text style={{ color: C.white, fontSize: '26rpx', fontWeight: '600' }}>
                立即分享
              </Text>
            </View>
          </View>
        </View>

        {/* QR placeholder */}
        <View
          style={{
            width: '180rpx',
            height: '180rpx',
            background: '#E0E0E0',
            borderRadius: '16rpx',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          {/* Grid dots simulating QR */}
          <View
            style={{
              width: '120rpx',
              height: '120rpx',
              display: 'grid',
              gridTemplateColumns: 'repeat(7, 1fr)',
              gap: '4rpx',
              marginBottom: '12rpx',
            }}
          >
            {Array.from({ length: 49 }).map((_, i) => (
              <View
                key={i}
                style={{
                  background: Math.random() > 0.4 ? '#333' : 'transparent',
                  borderRadius: '2rpx',
                }}
              />
            ))}
          </View>
          <Text style={{ color: '#555', fontSize: '20rpx', textAlign: 'center' }}>
            长按识别
          </Text>
        </View>
      </View>

      {/* Stats row */}
      {referralCode && (
        <View
          style={{
            borderTop: `1rpx solid ${C.border}`,
            display: 'flex',
            flexDirection: 'row',
          }}
        >
          {[
            { label: '累计邀请', value: referralCode.totalReferrals, unit: '人' },
            { label: '成功邀请', value: referralCode.successfulReferrals, unit: '人' },
            { label: '获得积分', value: referralCode.earnedPoints, unit: 'pts' },
          ].map((item, i) => (
            <View
              key={i}
              style={{
                flex: 1,
                padding: '24rpx 16rpx',
                textAlign: 'center',
                borderRight: i < 2 ? `1rpx solid ${C.border}` : 'none',
              }}
            >
              <Text
                style={{
                  color: C.primary,
                  fontSize: '36rpx',
                  fontWeight: '700',
                  display: 'block',
                }}
              >
                {item.value}
                <Text style={{ fontSize: '20rpx', fontWeight: '400' }}>{item.unit}</Text>
              </Text>
              <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                {item.label}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

// ─── Milestone tracker ────────────────────────────────────────────────────────

interface MilestoneTrackerProps {
  successfulReferrals: number
}

function MilestoneTracker({ successfulReferrals }: MilestoneTrackerProps) {
  return (
    <View style={{ margin: '24rpx 24rpx 0' }}>
      <Text
        style={{
          color: C.text1,
          fontSize: '30rpx',
          fontWeight: '700',
          display: 'block',
          marginBottom: '20rpx',
        }}
      >
        已邀请 <Text style={{ color: C.primary }}>{successfulReferrals}</Text> 位好友
      </Text>

      {/* Progress bar background */}
      <View
        style={{
          height: '8rpx',
          background: C.bgCard,
          borderRadius: '8rpx',
          marginBottom: '28rpx',
          position: 'relative',
        }}
      >
        <View
          style={{
            height: '100%',
            background: `linear-gradient(90deg, ${C.primary}, ${C.gold})`,
            borderRadius: '8rpx',
            width: `${Math.min((successfulReferrals / 10) * 100, 100)}%`,
            transition: 'width 0.5s ease',
          }}
        />
      </View>

      {/* Milestone cards */}
      <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
        {MILESTONES.map((m) => {
          const reached = successfulReferrals >= m.count
          const isNext = !reached && (
            MILESTONES.findIndex((x) => !( successfulReferrals >= x.count)) ===
            MILESTONES.indexOf(m)
          )
          return (
            <View
              key={m.count}
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                background: reached ? `rgba(255,107,53,0.08)` : C.bgCard,
                borderRadius: '20rpx',
                padding: '20rpx 24rpx',
                border: `1rpx solid ${reached ? C.primary : isNext ? C.border : 'transparent'}`,
                opacity: reached ? 1 : isNext ? 1 : 0.6,
              }}
            >
              <Text style={{ fontSize: '40rpx', marginRight: '20rpx' }}>{m.icon}</Text>
              <View style={{ flex: 1 }}>
                <Text
                  style={{
                    color: reached ? C.primary : C.text2,
                    fontSize: '26rpx',
                    fontWeight: '600',
                    display: 'block',
                  }}
                >
                  {m.label}
                </Text>
                <Text style={{ color: C.text3, fontSize: '24rpx', marginTop: '4rpx', display: 'block' }}>
                  奖励：{m.reward}
                </Text>
              </View>
              {/* Status badge */}
              <View
                style={{
                  background: reached ? C.success : isNext ? C.primary : C.bgHover,
                  borderRadius: '20rpx',
                  padding: '8rpx 20rpx',
                }}
              >
                <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '600' }}>
                  {reached ? '已达成' : isNext ? '进行中' : '未达成'}
                </Text>
              </View>
            </View>
          )
        })}
      </View>
    </View>
  )
}

// ─── Friend list ──────────────────────────────────────────────────────────────

interface FriendsListProps {
  friends: InvitedFriend[]
  loading: boolean
}

function FriendsList({ friends, loading }: FriendsListProps) {
  if (loading) {
    return (
      <View style={{ padding: '48rpx', textAlign: 'center' }}>
        <Text style={{ color: C.text3, fontSize: '26rpx' }}>加载中…</Text>
      </View>
    )
  }

  if (friends.length === 0) {
    return (
      <View
        style={{
          padding: '64rpx 48rpx',
          textAlign: 'center',
          background: C.bgCard,
          borderRadius: '20rpx',
          margin: '0 24rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx', display: 'block', marginBottom: '16rpx' }}>👥</Text>
        <Text style={{ color: C.text3, fontSize: '28rpx' }}>还没有邀请记录</Text>
        <Text style={{ color: C.text3, fontSize: '24rpx', display: 'block', marginTop: '8rpx' }}>
          快去邀请好友，一起赚福利吧！
        </Text>
      </View>
    )
  }

  return (
    <View style={{ margin: '0 24rpx', display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
      {friends.map((friend) => {
        const initial = (friend.nickname || '?')[0].toUpperCase()
        const avatarColors = ['#FF6B35', '#4CAF50', '#2196F3', '#9C27B0', '#FF9800']
        const colorIdx = friend.memberId.charCodeAt(friend.memberId.length - 1) % avatarColors.length
        const avatarBg = avatarColors[colorIdx]
        const rewarded = friend.rewardIssued
        const hasOrder = friend.hasCompletedFirstOrder

        return (
          <View
            key={friend.memberId}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              background: C.bgCard,
              borderRadius: '20rpx',
              padding: '24rpx',
              border: `1rpx solid ${C.border}`,
            }}
          >
            {/* Avatar */}
            <View
              style={{
                width: '72rpx',
                height: '72rpx',
                borderRadius: '50%',
                background: avatarBg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginRight: '20rpx',
                flexShrink: 0,
              }}
            >
              <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                {initial}
              </Text>
            </View>

            {/* Info */}
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  color: C.text1,
                  fontSize: '28rpx',
                  fontWeight: '600',
                  display: 'block',
                }}
              >
                {maskNickname(friend.nickname)}
              </Text>
              <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                加入于 {formatRelativeTime(friend.joinedAt)}
              </Text>
            </View>

            {/* Status badge */}
            <View
              style={{
                background: rewarded
                  ? 'rgba(76,175,80,0.15)'
                  : 'rgba(90,122,136,0.15)',
                borderRadius: '16rpx',
                padding: '8rpx 20rpx',
                border: `1rpx solid ${rewarded ? C.success : C.border}`,
              }}
            >
              <Text
                style={{
                  color: rewarded ? C.success : C.text3,
                  fontSize: '22rpx',
                  fontWeight: '600',
                }}
              >
                {rewarded ? '已奖励' : hasOrder ? '奖励发放中' : '待完成首单'}
              </Text>
            </View>
          </View>
        )
      })}
    </View>
  )
}

// ─── Rules accordion ──────────────────────────────────────────────────────────

function RulesAccordion() {
  const [open, setOpen] = useState(false)

  return (
    <View
      style={{
        margin: '24rpx 24rpx 0',
        background: C.bgCard,
        borderRadius: '20rpx',
        border: `1rpx solid ${C.border}`,
        overflow: 'hidden',
      }}
    >
      <View
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '24rpx 28rpx',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '28rpx', fontWeight: '600' }}>
          活动规则
        </Text>
        <Text
          style={{
            color: C.text3,
            fontSize: '24rpx',
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.2s',
          }}
        >
          ▾
        </Text>
      </View>

      {open && (
        <View
          style={{
            padding: '0 28rpx 28rpx',
            borderTop: `1rpx solid ${C.border}`,
          }}
        >
          {RULES.map((rule, i) => (
            <View
              key={i}
              style={{
                display: 'flex',
                flexDirection: 'row',
                marginTop: '16rpx',
                alignItems: 'flex-start',
              }}
            >
              <Text
                style={{
                  color: C.primary,
                  fontSize: '22rpx',
                  fontWeight: '700',
                  marginRight: '12rpx',
                  marginTop: '2rpx',
                  flexShrink: 0,
                }}
              >
                {i + 1}.
              </Text>
              <Text style={{ color: C.text3, fontSize: '24rpx', lineHeight: '1.6' }}>
                {rule}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function InvitePage() {
  const { nickname } = useUserStore()
  const [referralCode, setReferralCode] = useState<ReferralCode | null>(null)
  const [friends, setFriends] = useState<InvitedFriend[]>([])
  const [loading, setLoading] = useState(true)
  const [friendsLoading, setFriendsLoading] = useState(true)

  // Load referral code
  useEffect(() => {
    getReferralCode()
      .then((code) => setReferralCode(code))
      .catch((err) =>
        Taro.showToast({ title: err?.message ?? '加载失败', icon: 'none', duration: 2000 }),
      )
      .finally(() => setLoading(false))
  }, [])

  // Load invited friends list
  useEffect(() => {
    txRequest<InvitedFriend[]>('/api/v1/referral/invited-friends?limit=10')
      .then((data) => setFriends(data))
      .catch(() => setFriends([]))
      .finally(() => setFriendsLoading(false))
  }, [])

  const handleShare = useCallback(() => {
    if (!referralCode?.code) return
    Taro.shareAppMessage({
      title: `${nickname || '朋友'} 邀请你加入屯象OS，首单立享优惠！`,
      path: `/pages/index/index?ref=${referralCode.code}`,
      imageUrl: '',
    })
  }, [referralCode, nickname])

  const successfulReferrals = referralCode?.successfulReferrals ?? 0

  return (
    <ScrollView
      scrollY
      style={{ height: '100vh', background: C.bgDeep }}
      enableFlex
    >
      {/* Page title */}
      <View
        style={{
          padding: '40rpx 32rpx 24rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
        }}
      >
        <View
          style={{
            width: '8rpx',
            height: '40rpx',
            background: C.primary,
            borderRadius: '4rpx',
            marginRight: '16rpx',
          }}
        />
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          邀请有礼
        </Text>
      </View>

      {/* 1. Referral hero card */}
      <ReferralHero
        referralCode={referralCode}
        loading={loading}
        onShare={handleShare}
      />

      {/* 2. Milestone tracker */}
      <MilestoneTracker successfulReferrals={successfulReferrals} />

      {/* 3. Friends list */}
      <View style={{ margin: '32rpx 0 0' }}>
        <Text
          style={{
            color: C.text1,
            fontSize: '30rpx',
            fontWeight: '700',
            display: 'block',
            margin: '0 24rpx 20rpx',
          }}
        >
          已邀请好友（最近10位）
        </Text>
        <FriendsList friends={friends} loading={friendsLoading} />
      </View>

      {/* 4. Rules accordion */}
      <RulesAccordion />

      {/* Bottom padding */}
      <View style={{ height: '48rpx' }} />
    </ScrollView>
  )
}
