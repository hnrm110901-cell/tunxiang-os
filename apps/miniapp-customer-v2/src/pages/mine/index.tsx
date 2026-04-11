/**
 * pages/mine/index.tsx — 我的
 *
 * Sections:
 *   1. Top card: avatar + nickname + member badge + "未登录请点击登录"
 *   2. Stats row: 积分 / 储值余额 / 优惠券 (3 columns)
 *   3. 我的订单 icon row (全部/待付款/进行中/已完成)
 *   4. 会员服务 list
 *   5. 特色服务 list
 *   6. 设置 list
 *   7. Version number
 */

import React, { useCallback, useEffect, useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { View, Text, Image, ScrollView } from '@tarojs/components'
import { useUserStore } from '../../store/useUserStore'
import { getMemberLevel, getPointsBalance } from '../../api/member'
import { MemberBadge } from '../../components/MemberBadge'
import { fenToYuanDisplay } from '../../utils/format'
import type { MemberLevel, PointsBalance } from '../../api/member'

// ─── Colours ─────────────────────────────────────────────────────────────────

const C = {
  bg:       '#0B1A20',
  card:     '#132029',
  primary:  '#FF6B35',
  text1:    '#E8F4F8',
  text2:    '#9EB5C0',
  divider:  'rgba(255,255,255,0.07)',
}

// ─── Level gradient map ───────────────────────────────────────────────────────

const LEVEL_GRADIENT: Record<string, [string, string]> = {
  bronze:   ['#8B6A40', '#C9965F'],
  silver:   ['#6B8899', '#9EB5C0'],
  gold:     ['#B8860B', '#FFD700'],
  platinum: ['#7B8FA1', '#B0C4DE'],
  diamond:  ['#1A4A7A', '#5FA8E8'],
}

function levelGradient(level: string): string {
  const [a, b] = LEVEL_GRADIENT[level] ?? ['#3A4A50', '#6B8899']
  return `linear-gradient(135deg, ${a}, ${b})`
}

// ─── Coupon count (mock; real API not in spec) ────────────────────────────────

const MOCK_COUPON_COUNT = 3

// ─── Section list item ────────────────────────────────────────────────────────

interface ListItemProps {
  icon: string
  label: string
  badge?: string | number
  arrow?: boolean
  danger?: boolean
  onTap?: () => void
}

function ListItem({ icon, label, badge, arrow = true, danger, onTap }: ListItemProps) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '28rpx 32rpx',
        borderBottom: `1rpx solid ${C.divider}`,
        background: C.card,
      }}
      onClick={onTap}
    >
      <Text style={{ fontSize: '36rpx', marginRight: '20rpx', lineHeight: '1' }}>{icon}</Text>
      <Text
        style={{
          flex: 1,
          color: danger ? '#E88080' : C.text1,
          fontSize: '28rpx',
        }}
      >
        {label}
      </Text>
      {badge !== undefined && (
        <View
          style={{
            background: 'rgba(255,107,53,0.15)',
            borderRadius: '20rpx',
            padding: '4rpx 16rpx',
            marginRight: '8rpx',
          }}
        >
          <Text style={{ color: C.primary, fontSize: '22rpx' }}>{badge}</Text>
        </View>
      )}
      {arrow && (
        <Text style={{ color: C.text2, fontSize: '28rpx', marginLeft: '4rpx' }}>›</Text>
      )}
    </View>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: '24rpx' }}>
      <Text
        style={{
          color: C.text2,
          fontSize: '24rpx',
          padding: '20rpx 32rpx 10rpx',
          display: 'block',
        }}
      >
        {title}
      </Text>
      <View style={{ borderRadius: '16rpx', overflow: 'hidden', margin: '0 24rpx' }}>
        {children}
      </View>
    </View>
  )
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function MinePage() {
  const isLoggedIn   = useUserStore((s) => s.isLoggedIn)
  const userId       = useUserStore((s) => s.userId)
  const nickname     = useUserStore((s) => s.nickname)
  const avatarUrl    = useUserStore((s) => s.avatarUrl)
  const memberLevel  = useUserStore((s) => s.memberLevel)
  const pointsLocal  = useUserStore((s) => s.pointsBalance)
  const storedFen    = useUserStore((s) => s.storedValueFen)
  const setMemberInfo = useUserStore((s) => s.setMemberInfo)

  const [level,       setLevel]       = useState<MemberLevel | null>(null)
  const [points,      setPoints]      = useState<PointsBalance | null>(null)
  const [loadingStats, setLoadingStats] = useState(false)

  // ── Load member stats ──────────────────────────────────────────────────────
  const loadStats = useCallback(() => {
    if (!isLoggedIn) return
    setLoadingStats(true)
    Promise.all([getMemberLevel(), getPointsBalance()])
      .then(([lv, pt]) => {
        setLevel(lv)
        setPoints(pt)
        setMemberInfo(lv.name, pt.currentPoints, storedFen)
      })
      .catch((err) => {
        console.error('[MinePage] stats error', err)
        // Non-fatal: use local state fallback
      })
      .finally(() => setLoadingStats(false))
  }, [isLoggedIn, storedFen, setMemberInfo])

  useEffect(() => { loadStats() }, [loadStats])
  useDidShow(() => { loadStats() })

  // ── Navigation helpers ─────────────────────────────────────────────────────
  const nav = (path: string) =>
    Taro.navigateTo({ url: path }).catch(() =>
      Taro.showToast({ title: '页面开发中', icon: 'none' }),
    )

  const goOrderTab = (status?: string) => {
    // Orders tab is a main tab; pass status query for initial filter
    if (status) {
      nav(`/pages/order/index?status=${status}`)
    } else {
      Taro.switchTab({ url: '/pages/order/index' })
    }
  }

  const handleLogin = () => {
    nav('/subpackages/member/level/index')
  }

  const handleLogout = () => {
    Taro.showModal({
      title: '退出登录',
      content: '确定要退出登录吗？',
      confirmColor: '#E55A28',
      success: ({ confirm }) => {
        if (confirm) {
          useUserStore.getState().logout()
          Taro.showToast({ title: '已退出', icon: 'success' })
        }
      },
    })
  }

  // ─── Derived display values ────────────────────────────────────────────────
  const displayNickname = isLoggedIn ? (nickname || '屯象会员') : '未登录'
  const displayPoints   = points?.currentPoints ?? pointsLocal
  const displayStored   = fenToYuanDisplay(storedFen)
  const couponCount     = MOCK_COUPON_COUNT
  const levelName       = level?.name ?? memberLevel
  const levelLabel      = level?.label ?? {
    bronze: '青铜', silver: '白银', gold: '黄金', platinum: '铂金', diamond: '钻石',
  }[levelName] ?? '普通会员'

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <ScrollView scrollY style={{ minHeight: '100vh', background: C.bg }}>
      <View style={{ minHeight: '100vh', background: C.bg, paddingBottom: '60rpx' }}>

        {/* ─── Top user card ─── */}
        <View
          style={{
            background: levelGradient(levelName),
            padding: '60rpx 32rpx 36rpx',
            position: 'relative',
            overflow: 'hidden',
          }}
          onClick={!isLoggedIn ? handleLogin : undefined}
        >
          {/* Decorative circle */}
          <View
            style={{
              position: 'absolute',
              top: '-80rpx',
              right: '-60rpx',
              width: '320rpx',
              height: '320rpx',
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.07)',
              pointerEvents: 'none',
            }}
          />
          <View
            style={{
              position: 'absolute',
              bottom: '-60rpx',
              left: '40%',
              width: '200rpx',
              height: '200rpx',
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.05)',
              pointerEvents: 'none',
            }}
          />

          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '24rpx' }}>
            {/* Avatar */}
            <View
              style={{
                width: '120rpx',
                height: '120rpx',
                borderRadius: '50%',
                overflow: 'hidden',
                background: 'rgba(255,255,255,0.2)',
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {avatarUrl ? (
                <Image
                  src={avatarUrl}
                  style={{ width: '120rpx', height: '120rpx' }}
                  mode="aspectFill"
                  lazyLoad
                />
              ) : (
                <Text style={{ fontSize: '56rpx', lineHeight: '1' }}>
                  {isLoggedIn ? '👤' : '🔒'}
                </Text>
              )}
            </View>

            {/* Name + level */}
            <View style={{ flex: 1 }}>
              <Text
                style={{
                  color: '#fff',
                  fontSize: '36rpx',
                  fontWeight: '700',
                  display: 'block',
                  marginBottom: '10rpx',
                }}
              >
                {displayNickname}
              </Text>
              {isLoggedIn ? (
                <MemberBadge level={levelName} label={levelLabel} />
              ) : (
                <Text style={{ color: 'rgba(255,255,255,0.7)', fontSize: '26rpx' }}>
                  点击登录 / 注册
                </Text>
              )}
            </View>
          </View>
        </View>

        {/* ─── Stats row ─── */}
        <View
          style={{
            background: C.card,
            margin: '0 0 24rpx',
            display: 'flex',
            flexDirection: 'row',
          }}
        >
          {[
            {
              label: '积分',
              value: loadingStats ? '…' : String(displayPoints),
              onTap: () => nav('/subpackages/member/points/index'),
            },
            {
              label: '储值余额',
              value: loadingStats ? '…' : displayStored,
              onTap: () => nav('/subpackages/member/stored-value/index'),
            },
            {
              label: '优惠券',
              value: loadingStats ? '…' : String(couponCount),
              onTap: () => nav('/subpackages/marketing/coupon/index'),
            },
          ].map((item, idx, arr) => (
            <View
              key={item.label}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '28rpx 0',
                borderRight: idx < arr.length - 1 ? `1rpx solid ${C.divider}` : 'none',
              }}
              onClick={item.onTap}
            >
              <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700', display: 'block', marginBottom: '8rpx' }}>
                {item.value}
              </Text>
              <Text style={{ color: C.text2, fontSize: '24rpx' }}>{item.label}</Text>
            </View>
          ))}
        </View>

        {/* ─── 我的订单 icon row ─── */}
        <Section title="我的订单">
          <View
            style={{
              background: C.card,
              display: 'flex',
              flexDirection: 'row',
              padding: '24rpx 0',
            }}
          >
            {[
              { icon: '📋', label: '全部',   status: undefined },
              { icon: '💰', label: '待付款', status: 'pending_payment' },
              { icon: '🍳', label: '进行中', status: 'preparing' },
              { icon: '✅', label: '已完成', status: 'completed' },
            ].map((item) => (
              <View
                key={item.label}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '10rpx',
                }}
                onClick={() => goOrderTab(item.status)}
              >
                <Text style={{ fontSize: '44rpx', lineHeight: '1' }}>{item.icon}</Text>
                <Text style={{ color: C.text2, fontSize: '24rpx' }}>{item.label}</Text>
              </View>
            ))}
          </View>
        </Section>

        {/* ─── 会员服务 ─── */}
        <Section title="会员服务">
          <ListItem
            icon="🏆"
            label="会员等级"
            badge={levelLabel}
            onTap={() => nav('/subpackages/member/level/index')}
          />
          <ListItem
            icon="⭐"
            label="积分商城"
            onTap={() => nav('/subpackages/marketing/points-mall/index')}
          />
          <ListItem
            icon="🎟"
            label="集章卡"
            onTap={() => nav('/subpackages/marketing/stamp-card/index')}
          />
          <ListItem
            icon="🎁"
            label="礼品卡"
            onTap={() => nav('/subpackages/social/gift-card/index')}
          />
        </Section>

        {/* ─── 特色服务 ─── */}
        <Section title="特色服务">
          <ListItem
            icon="👨‍🍳"
            label="大厨到家"
            onTap={() => nav('/subpackages/special/chef-at-home/index')}
          />
          <ListItem
            icon="🏢"
            label="企业团餐"
            onTap={() => nav('/subpackages/special/corporate/index')}
          />
          <ListItem
            icon="🎊"
            label="宴会预订"
            onTap={() => nav('/subpackages/special/banquet/index')}
          />
        </Section>

        {/* ─── 设置 ─── */}
        <Section title="设置">
          <ListItem
            icon="📍"
            label="收货地址"
            onTap={() => nav('/subpackages/member/preferences/index?tab=address')}
          />
          <ListItem
            icon="🍽"
            label="口味偏好"
            onTap={() => nav('/subpackages/member/preferences/index?tab=flavor')}
          />
          <ListItem
            icon="🔔"
            label="消息通知"
            onTap={() => nav('/subpackages/member/preferences/index?tab=notification')}
          />
          <ListItem
            icon="ℹ️"
            label="关于屯象"
            onTap={() => Taro.showModal({
              title: '关于屯象OS',
              content: '屯象OS是AI-Native连锁餐饮经营操作系统，以一套智能系统替换连锁餐饮企业现有所有业务系统。',
              showCancel: false,
            })}
          />
          {isLoggedIn && (
            <ListItem
              icon="🚪"
              label="退出登录"
              arrow={false}
              danger
              onTap={handleLogout}
            />
          )}
        </Section>

        {/* ─── Version ─── */}
        <View
          style={{
            padding: '24rpx 0 48rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: 'rgba(158,181,192,0.35)', fontSize: '22rpx' }}>
            屯象OS · v0.1.0
          </Text>
        </View>
      </View>
    </ScrollView>
  )
}
