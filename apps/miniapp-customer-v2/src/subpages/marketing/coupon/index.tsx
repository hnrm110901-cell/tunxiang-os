/**
 * coupon/index.tsx — 优惠券中心
 *
 * Three-tab layout:
 *   可用(N)  → claim section + CouponCard list with "立即使用" CTA
 *   已使用   → CouponCard in disabled state
 *   已过期   → CouponCard in disabled state + greyed-out style
 *
 * Claim flow: getActivities() filtered by type=coupon → claimCoupon(activityId)
 * Use flow:   navigate back with couponId pre-selected, or go to menu
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { listCoupons, claimCoupon, getActivities } from '../../api/growth'
import type { Coupon, CouponStatus, Activity } from '../../api/growth'
import { CouponCard } from '../../components/CouponCard'
import { fenToYuanDisplay } from '../../utils/format'

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
  white: '#fff',
} as const

// ─── Tab definition ───────────────────────────────────────────────────────────

type TabKey = 'available' | 'used' | 'expired'

interface Tab {
  key: TabKey
  label: string
  status: CouponStatus
}

const TABS: Tab[] = [
  { key: 'available', label: '可用', status: 'available' },
  { key: 'used',      label: '已使用', status: 'used' },
  { key: 'expired',   label: '已过期', status: 'expired' },
]

// ─── Coupon adapter ───────────────────────────────────────────────────────────
// CouponCard expects its own local Coupon shape; map from API Coupon

function adaptCoupon(c: Coupon) {
  let type: 'discount' | 'cash' | 'free' = 'cash'
  if (c.type === 'discount_percent') type = 'discount'
  else if (c.type === 'free_item' || c.type === 'free_shipping') type = 'free'

  // For discount_percent CouponCard expects discount_fen = discountValue * 100 (e.g. 85 → 8500)
  const discount_fen = c.type === 'discount_percent'
    ? c.discountValue * 100
    : c.discountValue

  return {
    id: c.couponId,
    title: c.name,
    discount_fen,
    min_order_fen: c.minOrderFen,
    expire_at: c.validUntil,
    type,
    status: c.status,
  }
}

// ─── Claim button ─────────────────────────────────────────────────────────────

interface ClaimButtonProps {
  activity: Activity
  onClaimed: () => void
}

function ClaimButton({ activity, onClaimed }: ClaimButtonProps) {
  const [claiming, setClaiming] = useState(false)
  const [claimed, setClaimed] = useState(activity.hasParticipated ?? false)

  const handleClaim = useCallback(async () => {
    if (claiming || claimed) return
    setClaiming(true)
    try {
      await claimCoupon(activity.activityId)
      setClaimed(true)
      Taro.showToast({ title: '领取成功！', icon: 'success', duration: 1500 })
      onClaimed()
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '领取失败', icon: 'none', duration: 2000 })
    } finally {
      setClaiming(false)
    }
  }, [claiming, claimed, activity.activityId, onClaimed])

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: C.bgCard,
        borderRadius: '20rpx',
        padding: '24rpx 28rpx',
        border: `1rpx solid ${C.border}`,
      }}
    >
      {/* Activity info */}
      <View style={{ flex: 1, marginRight: '24rpx' }}>
        <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
          {activity.name}
        </Text>
        {activity.description ? (
          <Text style={{ color: C.text3, fontSize: '24rpx', marginTop: '8rpx', display: 'block' }}>
            {activity.description}
          </Text>
        ) : null}
        {activity.badgeText ? (
          <View
            style={{
              display: 'inline-flex',
              marginTop: '10rpx',
              background: 'rgba(255,107,53,0.15)',
              borderRadius: '8rpx',
              padding: '4rpx 12rpx',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '22rpx', fontWeight: '600' }}>
              {activity.badgeText}
            </Text>
          </View>
        ) : null}
      </View>

      {/* Claim button */}
      <View
        style={{
          background: claimed ? C.bgHover : C.primary,
          borderRadius: '12rpx',
          padding: '16rpx 28rpx',
          opacity: claiming ? 0.7 : 1,
          flexShrink: 0,
        }}
        onClick={handleClaim}
      >
        <Text style={{ color: C.white, fontSize: '26rpx', fontWeight: '700' }}>
          {claimed ? '已领取' : claiming ? '领取中…' : '立即领取'}
        </Text>
      </View>
    </View>
  )
}

// ─── Empty state ──────────────────────────────────────────────────────────────

interface EmptyStateProps {
  tab: TabKey
  onGoMenu: () => void
}

function EmptyState({ tab, onGoMenu }: EmptyStateProps) {
  const config: Record<TabKey, { emoji: string; title: string; sub: string; cta: string | null }> = {
    available: {
      emoji: '🎟️',
      title: '暂无可用优惠券',
      sub: '领取上方优惠券，点餐时自动抵扣',
      cta: '去点餐',
    },
    used: {
      emoji: '✅',
      title: '暂无已使用记录',
      sub: '使用优惠券后，记录会显示在这里',
      cta: null,
    },
    expired: {
      emoji: '⏰',
      title: '暂无过期券',
      sub: '过期的优惠券会在这里留存记录',
      cta: null,
    },
  }
  const { emoji, title, sub, cta } = config[tab]

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '80rpx 40rpx',
        gap: '24rpx',
      }}
    >
      <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>{emoji}</Text>
      <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>{title}</Text>
      <Text style={{ color: C.text3, fontSize: '26rpx', textAlign: 'center' }}>{sub}</Text>
      {cta ? (
        <View
          style={{
            background: C.primary,
            borderRadius: '48rpx',
            padding: '20rpx 56rpx',
            marginTop: '8rpx',
          }}
          onClick={onGoMenu}
        >
          <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>{cta}</Text>
        </View>
      ) : null}
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function CouponCenter() {
  const [activeTab, setActiveTab] = useState<TabKey>('available')
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [couponActivities, setCouponActivities] = useState<Activity[]>([])
  const [loading, setLoading] = useState(false)
  const [activitiesLoaded, setActivitiesLoaded] = useState(false)

  // Fetch coupon activities once
  useEffect(() => {
    getActivities()
      .then((acts) => {
        // Filter to activities that grant coupons (new_member, limited_time_offer, flash_sale, points_double)
        // The spec says type=coupon but ActivityType doesn't have 'coupon' — use the union excluding group_buy/stamp_card
        const couponTypes = new Set(['limited_time_offer', 'new_member', 'flash_sale', 'points_double'])
        setCouponActivities(acts.filter((a) => couponTypes.has(a.type) && a.isActive))
        setActivitiesLoaded(true)
      })
      .catch(() => setActivitiesLoaded(true))
  }, [])

  const fetchCoupons = useCallback(async (status: CouponStatus) => {
    setLoading(true)
    try {
      const data = await listCoupons(status)
      setCoupons(data)
    } catch {
      setCoupons([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const tab = TABS.find((t) => t.key === activeTab)!
    fetchCoupons(tab.status)
  }, [activeTab, fetchCoupons])

  const handleUse = useCallback((coupon: Coupon) => {
    // Navigate back with coupon pre-selected, or go to menu
    const pages = Taro.getCurrentPages()
    if (pages.length > 1) {
      const prevPage = pages[pages.length - 2]
      // Pass couponId via event data
      prevPage.$taroParams = { ...(prevPage.$taroParams ?? {}), selectedCouponId: coupon.couponId }
      Taro.navigateBack()
    } else {
      Taro.switchTab({ url: '/pages/menu/index' })
    }
  }, [])

  const handleGoMenu = useCallback(() => {
    Taro.switchTab({ url: '/pages/menu/index' })
  }, [])

  const availableCount = activeTab === 'available' ? coupons.length : 0

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
      {/* Tab bar */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          background: C.bgCard,
          borderBottom: `1rpx solid ${C.border}`,
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab
          const label =
            tab.key === 'available' && availableCount > 0
              ? `${tab.label}(${availableCount})`
              : tab.label
          return (
            <View
              key={tab.key}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '28rpx 0 20rpx',
                gap: '8rpx',
                position: 'relative',
              }}
              onClick={() => setActiveTab(tab.key)}
            >
              <Text
                style={{
                  color: isActive ? C.primary : C.text3,
                  fontSize: '28rpx',
                  fontWeight: isActive ? '700' : '400',
                  transition: 'color 0.15s',
                }}
              >
                {label}
              </Text>
              {isActive && (
                <View
                  style={{
                    position: 'absolute',
                    bottom: 0,
                    width: '40rpx',
                    height: '4rpx',
                    borderRadius: '2rpx',
                    background: C.primary,
                  }}
                />
              )}
            </View>
          )
        })}
      </View>

      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '24rpx 24rpx 48rpx' }}>
          {/* Claim section — only on available tab */}
          {activeTab === 'available' && activitiesLoaded && couponActivities.length > 0 && (
            <View style={{ marginBottom: '32rpx' }}>
              <Text
                style={{
                  color: C.text2,
                  fontSize: '24rpx',
                  fontWeight: '600',
                  letterSpacing: '1rpx',
                  textTransform: 'uppercase',
                  display: 'block',
                  marginBottom: '16rpx',
                }}
              >
                限时领取
              </Text>
              <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
                {couponActivities.map((act) => (
                  <ClaimButton
                    key={act.activityId}
                    activity={act}
                    onClaimed={() => fetchCoupons('available')}
                  />
                ))}
              </View>
            </View>
          )}

          {/* Divider label */}
          {activeTab === 'available' && (
            <Text
              style={{
                color: C.text2,
                fontSize: '24rpx',
                fontWeight: '600',
                letterSpacing: '1rpx',
                display: 'block',
                marginBottom: '16rpx',
              }}
            >
              我的优惠券
            </Text>
          )}

          {/* Loading skeleton */}
          {loading ? (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
              {[0, 1, 2].map((i) => (
                <View
                  key={i}
                  style={{
                    height: '160rpx',
                    background: C.bgCard,
                    borderRadius: '24rpx',
                    opacity: 0.5,
                  }}
                />
              ))}
            </View>
          ) : coupons.length === 0 ? (
            <EmptyState tab={activeTab} onGoMenu={handleGoMenu} />
          ) : (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
              {coupons.map((coupon) => (
                <View key={coupon.couponId}>
                  <CouponCard coupon={adaptCoupon(coupon)} selectable={false} />
                  {/* Use button — only for available */}
                  {coupon.status === 'available' && (
                    <View
                      style={{
                        display: 'flex',
                        justifyContent: 'flex-end',
                        marginTop: '12rpx',
                        paddingRight: '4rpx',
                      }}
                    >
                      <View
                        style={{
                          background: C.primary,
                          borderRadius: '10rpx',
                          padding: '14rpx 32rpx',
                        }}
                        onClick={() => handleUse(coupon)}
                      >
                        <Text style={{ color: C.white, fontSize: '26rpx', fontWeight: '700' }}>
                          立即使用
                        </Text>
                      </View>
                    </View>
                  )}
                </View>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
