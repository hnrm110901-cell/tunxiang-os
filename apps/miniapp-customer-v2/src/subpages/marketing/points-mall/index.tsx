/**
 * points-mall/index.tsx — 积分商城
 *
 * Features:
 *  - Current points balance (from useUserStore) + "去赚积分" link
 *  - Category tabs: 全部 / 优惠券 / 实物 / 体验
 *  - 2-column item grid: image + name + points cost (coin icon) + stock
 *  - Sort: 积分升序 / 积分降序 / 热门
 *  - "立即兑换" → confirm modal (points deduction + remaining balance)
 *  - POST redeemPoints → success toast + update store points
 *  - Empty / out-of-stock states
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { View, Text, ScrollView, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getPointsMall, redeemPoints } from '../../api/growth'
import type { PointsMallItem, PointsMallItemType } from '../../api/growth'
import { useUserStore } from '../../store/useUserStore'

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
  gold: '#FFD700',
} as const

// ─── Category tabs ────────────────────────────────────────────────────────────

type Category = 'all' | PointsMallItemType

interface Tab {
  key: Category
  label: string
}

const TABS: Tab[] = [
  { key: 'all',          label: '全部' },
  { key: 'coupon',       label: '优惠券' },
  { key: 'physical',     label: '实物' },
  { key: 'free_item',    label: '体验' },
  { key: 'stored_value', label: '储值' },
]

// ─── Sort options ─────────────────────────────────────────────────────────────

type SortKey = 'points_asc' | 'points_desc' | 'popular'

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: 'popular',     label: '热门' },
  { key: 'points_asc',  label: '积分↑' },
  { key: 'points_desc', label: '积分↓' },
]

// ─── Coin icon ────────────────────────────────────────────────────────────────

function CoinIcon({ size = 28 }: { size?: number }) {
  return (
    <View
      style={{
        width: `${size}rpx`,
        height: `${size}rpx`,
        borderRadius: '50%',
        background: `radial-gradient(circle at 35% 35%, #FFE680, ${C.gold})`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        boxShadow: `0 2rpx 6rpx rgba(255,215,0,0.4)`,
      }}
    >
      <Text style={{ color: '#8B6914', fontSize: `${size * 0.5}rpx`, fontWeight: '800', lineHeight: '1' }}>
        ¥
      </Text>
    </View>
  )
}

// ─── Confirm modal ────────────────────────────────────────────────────────────

interface ConfirmModalProps {
  visible: boolean
  item: PointsMallItem | null
  currentPoints: number
  onConfirm: () => void
  onClose: () => void
  redeeming: boolean
}

function ConfirmModal({
  visible,
  item,
  currentPoints,
  onConfirm,
  onClose,
  redeeming,
}: ConfirmModalProps) {
  if (!visible || !item) return null

  const remaining = currentPoints - item.pointsCost
  const canAfford = remaining >= 0

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
          gap: '24rpx',
        }}
      >
        {/* Handle */}
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', textAlign: 'center' }}>
          确认兑换
        </Text>

        {/* Item name */}
        <View
          style={{
            background: C.bgHover,
            borderRadius: '16rpx',
            padding: '24rpx',
            display: 'flex',
            flexDirection: 'column',
            gap: '16rpx',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '26rpx' }}>兑换商品</Text>
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
            {item.name}
          </Text>

          <View style={{ width: '100%', height: '1rpx', background: C.border }} />

          {/* Points breakdown */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <Text style={{ color: C.text3, fontSize: '26rpx' }}>消耗积分</Text>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
              <CoinIcon size={24} />
              <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '700' }}>
                -{item.pointsCost}
              </Text>
            </View>
          </View>

          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <Text style={{ color: C.text3, fontSize: '26rpx' }}>兑换后剩余</Text>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
              <CoinIcon size={24} />
              <Text
                style={{
                  color: canAfford ? C.text2 : C.text3,
                  fontSize: '28rpx',
                  fontWeight: '600',
                }}
              >
                {canAfford ? remaining : '--'}
              </Text>
            </View>
          </View>
        </View>

        {/* Cannot afford hint */}
        {!canAfford && (
          <Text style={{ color: '#E53935', fontSize: '24rpx', textAlign: 'center' }}>
            积分不足，无法兑换
          </Text>
        )}

        {/* Buttons */}
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          <View
            style={{
              flex: 1,
              background: C.bgHover,
              borderRadius: '12rpx',
              padding: '22rpx',
              border: `1rpx solid ${C.border}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={onClose}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>取消</Text>
          </View>
          <View
            style={{
              flex: 1,
              background: canAfford ? C.primary : C.bgHover,
              borderRadius: '12rpx',
              padding: '22rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: redeeming ? 0.7 : 1,
            }}
            onClick={canAfford && !redeeming ? onConfirm : undefined}
          >
            <Text
              style={{
                color: canAfford ? C.white : C.text3,
                fontSize: '28rpx',
                fontWeight: '700',
              }}
            >
              {redeeming ? '兑换中…' : '确认兑换'}
            </Text>
          </View>
        </View>
      </View>
    </View>
  )
}

// ─── Item card (half-width for 2-column grid) ─────────────────────────────────

interface ItemCardProps {
  item: PointsMallItem
  currentPoints: number
  onRedeem: (item: PointsMallItem) => void
}

function ItemCard({ item, currentPoints, onRedeem }: ItemCardProps) {
  const outOfStock = item.stock !== undefined && item.stock !== null && item.stock <= 0
  const canAfford = currentPoints >= item.pointsCost
  const disabled = outOfStock || !item.isActive

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        overflow: 'hidden',
        border: `1rpx solid ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        opacity: disabled ? 0.55 : 1,
      }}
    >
      {/* Image */}
      <View style={{ position: 'relative' }}>
        {item.imageUrl ? (
          <Image
            src={item.imageUrl}
            style={{ width: '100%', height: '220rpx', display: 'block', objectFit: 'cover' }}
            mode="aspectFill"
          />
        ) : (
          <View
            style={{
              width: '100%',
              height: '220rpx',
              background: C.bgHover,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ fontSize: '60rpx', lineHeight: '1' }}>
              {item.type === 'coupon' ? '🎟️' : item.type === 'physical' ? '📦' : item.type === 'stored_value' ? '💳' : '🎁'}
            </Text>
          </View>
        )}

        {/* Out of stock overlay */}
        {(outOfStock || !item.isActive) && (
          <View
            style={{
              position: 'absolute',
              inset: 0,
              background: 'rgba(0,0,0,0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                background: 'rgba(0,0,0,0.7)',
                borderRadius: '12rpx',
                padding: '12rpx 24rpx',
              }}
            >
              <Text style={{ color: C.text3, fontSize: '24rpx', fontWeight: '700' }}>
                {!item.isActive ? '🔒 已下架' : '已售罄'}
              </Text>
            </View>
          </View>
        )}

        {/* Stock badge */}
        {!outOfStock && item.stock !== undefined && item.stock !== null && item.stock <= 10 && (
          <View
            style={{
              position: 'absolute',
              top: '10rpx',
              right: '10rpx',
              background: 'rgba(229,57,53,0.9)',
              borderRadius: '8rpx',
              padding: '4rpx 12rpx',
            }}
          >
            <Text style={{ color: C.white, fontSize: '20rpx', fontWeight: '700' }}>
              仅剩{item.stock}件
            </Text>
          </View>
        )}
      </View>

      {/* Info */}
      <View style={{ padding: '20rpx', flex: 1, display: 'flex', flexDirection: 'column', gap: '12rpx' }}>
        <Text
          style={{
            color: C.text1,
            fontSize: '26rpx',
            fontWeight: '600',
            lineHeight: '1.4',
          }}
          numberOfLines={2}
        >
          {item.name}
        </Text>

        {/* Points cost */}
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
          <CoinIcon size={28} />
          <Text style={{ color: C.primary, fontSize: '30rpx', fontWeight: '800' }}>
            {item.pointsCost}
          </Text>
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>积分</Text>
        </View>

        {/* Cannot afford hint */}
        {!canAfford && !disabled && (
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>
            还差 {item.pointsCost - currentPoints} 积分
          </Text>
        )}

        {/* Redeem button */}
        <View
          style={{
            background: disabled || !canAfford ? C.bgHover : C.primary,
            borderRadius: '10rpx',
            padding: '14rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginTop: 'auto',
            border: `1rpx solid ${disabled || !canAfford ? C.border : 'transparent'}`,
          }}
          onClick={disabled || !canAfford ? undefined : () => onRedeem(item)}
        >
          <Text
            style={{
              color: disabled || !canAfford ? C.text3 : C.white,
              fontSize: '24rpx',
              fontWeight: '700',
            }}
          >
            {disabled ? (outOfStock ? '已售罄' : '🔒') : !canAfford ? '积分不足' : '立即兑换'}
          </Text>
        </View>
      </View>
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function PointsMallPage() {
  const { pointsBalance, setMemberInfo, memberLevel, storedValueFen } = useUserStore()

  const [items, setItems] = useState<PointsMallItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<Category>('all')
  const [sortKey, setSortKey] = useState<SortKey>('popular')
  const [confirmItem, setConfirmItem] = useState<PointsMallItem | null>(null)
  const [redeeming, setRedeeming] = useState(false)

  useEffect(() => {
    setLoading(true)
    getPointsMall()
      .then((data) => setItems(data))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [])

  // Filtered + sorted items
  const displayItems = useMemo(() => {
    let filtered = activeTab === 'all' ? items : items.filter((i) => i.type === activeTab)
    filtered = filtered.filter((i) => i.isActive || (i.stock !== undefined && i.stock! > 0))

    switch (sortKey) {
      case 'points_asc':
        return [...filtered].sort((a, b) => a.pointsCost - b.pointsCost)
      case 'points_desc':
        return [...filtered].sort((a, b) => b.pointsCost - a.pointsCost)
      case 'popular':
      default:
        // Keep original API order (server returns by popularity)
        return filtered
    }
  }, [items, activeTab, sortKey])

  const handleConfirmRedeem = useCallback(async () => {
    if (!confirmItem || redeeming) return
    setRedeeming(true)
    try {
      const result = await redeemPoints(confirmItem.itemId, confirmItem.pointsCost)
      // Update store points
      setMemberInfo(memberLevel, result.pointsBalanceAfter, storedValueFen)
      setConfirmItem(null)

      const successMsg = result.coupon
        ? `兑换成功！${result.coupon.name} 已发至您的优惠券`
        : '兑换成功！奖励已发放至您的账户'
      Taro.showToast({ title: successMsg, icon: 'success', duration: 2500 })

      // Refresh items (stock may have changed)
      getPointsMall().then((data) => setItems(data)).catch(() => {})
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '兑换失败', icon: 'none', duration: 2000 })
    } finally {
      setRedeeming(false)
    }
  }, [confirmItem, redeeming, memberLevel, storedValueFen, setMemberInfo])

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
      <ConfirmModal
        visible={!!confirmItem}
        item={confirmItem}
        currentPoints={pointsBalance}
        onConfirm={handleConfirmRedeem}
        onClose={() => setConfirmItem(null)}
        redeeming={redeeming}
      />

      {/* Points balance header */}
      <View
        style={{
          background: `linear-gradient(135deg, #1A3040 0%, ${C.bgCard} 100%)`,
          padding: '32rpx 32rpx 28rpx',
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <View>
            <Text
              style={{
                color: C.text3,
                fontSize: '24rpx',
                display: 'block',
                marginBottom: '8rpx',
              }}
            >
              我的积分
            </Text>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '12rpx' }}>
              <CoinIcon size={40} />
              <Text style={{ color: C.gold, fontSize: '52rpx', fontWeight: '800', lineHeight: '1' }}>
                {pointsBalance.toLocaleString()}
              </Text>
              <Text style={{ color: C.text3, fontSize: '24rpx', alignSelf: 'flex-end', marginBottom: '6rpx' }}>
                积分
              </Text>
            </View>
          </View>

          <View
            style={{
              background: 'rgba(255,107,53,0.15)',
              borderRadius: '48rpx',
              padding: '16rpx 28rpx',
              border: `1rpx solid rgba(255,107,53,0.3)`,
            }}
            onClick={() => Taro.navigateTo({ url: '/subpackages/member/points/index' })}
          >
            <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
              去赚积分 →
            </Text>
          </View>
        </View>
      </View>

      {/* Category tabs */}
      <ScrollView
        scrollX
        style={{
          background: C.bgCard,
          borderBottom: `1rpx solid ${C.border}`,
          flexShrink: 0,
        }}
      >
        <View style={{ display: 'flex', flexDirection: 'row', padding: '0 16rpx' }}>
          {TABS.map((tab) => {
            const isActive = tab.key === activeTab
            return (
              <View
                key={tab.key}
                style={{
                  flexShrink: 0,
                  padding: '24rpx 20rpx 16rpx',
                  position: 'relative',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '8rpx',
                }}
                onClick={() => setActiveTab(tab.key)}
              >
                <Text
                  style={{
                    color: isActive ? C.primary : C.text3,
                    fontSize: '28rpx',
                    fontWeight: isActive ? '700' : '400',
                  }}
                >
                  {tab.label}
                </Text>
                {isActive && (
                  <View
                    style={{
                      position: 'absolute',
                      bottom: 0,
                      width: '32rpx',
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
      </ScrollView>

      {/* Sort bar */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '12rpx',
          padding: '16rpx 24rpx',
          background: C.bgDeep,
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <Text style={{ color: C.text3, fontSize: '24rpx', marginRight: '8rpx' }}>排序：</Text>
        {SORT_OPTIONS.map((opt) => {
          const isActive = sortKey === opt.key
          return (
            <View
              key={opt.key}
              style={{
                background: isActive ? 'rgba(255,107,53,0.15)' : 'transparent',
                borderRadius: '8rpx',
                padding: '8rpx 20rpx',
                border: `1rpx solid ${isActive ? 'rgba(255,107,53,0.4)' : C.border}`,
              }}
              onClick={() => setSortKey(opt.key)}
            >
              <Text
                style={{
                  color: isActive ? C.primary : C.text3,
                  fontSize: '24rpx',
                  fontWeight: isActive ? '700' : '400',
                }}
              >
                {opt.label}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Item grid */}
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '20rpx 20rpx 80rpx' }}>
          {loading ? (
            /* Skeleton */
            <View
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '16rpx',
              }}
            >
              {[0, 1, 2, 3].map((i) => (
                <View
                  key={i}
                  style={{
                    background: C.bgCard,
                    borderRadius: '20rpx',
                    height: '380rpx',
                    opacity: 0.4,
                  }}
                />
              ))}
            </View>
          ) : displayItems.length === 0 ? (
            <View
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '80rpx 40rpx',
                gap: '24rpx',
              }}
            >
              <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>🔒</Text>
              <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
                该分类暂无商品
              </Text>
              <Text style={{ color: C.text3, fontSize: '26rpx', textAlign: 'center' }}>
                更多好礼即将上架，敬请期待
              </Text>
              {activeTab !== 'all' && (
                <View
                  style={{
                    background: C.bgCard,
                    borderRadius: '48rpx',
                    padding: '18rpx 48rpx',
                    border: `1rpx solid ${C.border}`,
                    marginTop: '8rpx',
                  }}
                  onClick={() => setActiveTab('all')}
                >
                  <Text style={{ color: C.text2, fontSize: '26rpx' }}>查看全部商品</Text>
                </View>
              )}
            </View>
          ) : (
            <View
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '16rpx',
              }}
            >
              {displayItems.map((item) => (
                <ItemCard
                  key={item.itemId}
                  item={item}
                  currentPoints={pointsBalance}
                  onRedeem={(i) => setConfirmItem(i)}
                />
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
