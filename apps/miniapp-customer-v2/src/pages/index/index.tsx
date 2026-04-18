/**
 * pages/index/index.tsx — 首页
 *
 * Sections:
 *   1. Store header (name + table number)
 *   2. Banner carousel (3 slides, auto-scroll 3 s)
 *   3. Quick-entry 2×3 grid
 *   4. AI推荐横向滚动条
 *   5. 今日活动 (max 3 cards)
 *   6. 热销菜品 (top 8, 2-col grid)
 *   7. CartBar fixed at bottom
 */

import React, { useCallback, useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import {
  View,
  Text,
  Image,
  ScrollView,
  Swiper,
  SwiperItem,
} from '@tarojs/components'
import { useCartStore } from '../../store/useCartStore'
import { useStoreInfo } from '../../store/useStoreInfo'
import { useUserStore } from '../../store/useUserStore'
import { getDishes } from '../../api/menu'
import { getActivities } from '../../api/growth'
import { CartBar } from '../../components/CartBar'
import { AiRecommend } from '../../components/AiRecommend'
import { DishCard } from '../../components/DishCard'
import { ReorderBanner } from '../../components/ReorderBanner'
import { getPersonalizedLayout, type PersonalizedLayout } from '../../engine/personalization'
import type { Dish } from '../../api/menu'
import type { Activity } from '../../api/growth'

// ─── Types ────────────────────────────────────────────────────────────────────

interface MockDish {
  id: string
  name: string
  price_fen: number
  image_url?: string
  tag?: string
  description?: string
  sold_out?: boolean
}

// ─── Mock / static data ───────────────────────────────────────────────────────

const BANNERS = [
  { id: '1', title: '春季新品上线', subtitle: '限时特惠，先到先得', color: '#1A3A4A' },
  { id: '2', title: '满100减20', subtitle: '本周五六日全天有效', color: '#1A2A3A' },
  { id: '3', title: '会员双倍积分', subtitle: '消费即可累积，随时兑换', color: '#2A1A3A' },
]

const QUICK_ENTRIES = [
  { id: 'scan',     icon: '📱', label: '扫码点餐', tabPath: '/pages/menu/index' },
  { id: 'delivery', icon: '🛵', label: '外卖配送',  navPath: '/subpackages/special/chef-at-home/index' },
  { id: 'reserve',  icon: '📅', label: '预约订座',  navPath: '/subpackages/reservation/index/index' },
  { id: 'chef',     icon: '👨‍🍳', label: '大厨到家', navPath: '/subpackages/special/chef-at-home/index' },
  { id: 'corp',     icon: '🏢', label: '企业团餐', navPath: '/subpackages/special/corporate/index' },
  { id: 'banquet',  icon: '🎊', label: '宴会',     navPath: '/subpackages/special/banquet/index' },
]

const AI_MOCK: MockDish[] = [
  { id: 'ai1', name: '招牌红烧肉',  price_fen: 6800,  tag: 'hot',       description: '入口即化，经典传承' },
  { id: 'ai2', name: '清蒸鲈鱼',   price_fen: 8800,  tag: 'recommend', description: '鲜嫩爽滑，当日新鲜' },
  { id: 'ai3', name: '夫妻肺片',   price_fen: 3800,  tag: 'hot',       description: '麻辣鲜香，下饭神器' },
  { id: 'ai4', name: '口水鸡',     price_fen: 4200,  tag: 'new',       description: '藤椒风味，嫩滑爽口' },
  { id: 'ai5', name: '松茸炖鸡汤', price_fen: 9800,  tag: 'recommend', description: '滋补养生，汤醇味美' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function activityEmoji(type: Activity['type']): string {
  const m: Record<Activity['type'], string> = {
    limited_time_offer: '⏰',
    group_buy:          '👥',
    stamp_card:         '🎟',
    points_double:      '⭐',
    new_member:         '🎁',
    flash_sale:         '⚡',
  }
  return m[type] ?? '🎉'
}

function dishToCard(d: Dish): MockDish {
  return {
    id:          d.dishId,
    name:        d.name,
    price_fen:   d.basePriceFen,
    image_url:   d.imageUrl,
    tag:         d.tags?.[0],
    description: d.description,
    sold_out:    d.status === 'sold_out',
  }
}

// ─── Inline style constants ───────────────────────────────────────────────────

const C = {
  bg:       '#0B1A20',
  card:     '#132029',
  primary:  '#FF6B35',
  text1:    '#E8F4F8',
  text2:    '#9EB5C0',
}

// ─── Skeleton strip ───────────────────────────────────────────────────────────

function SkeletonBox({ w, h, radius = '16rpx' }: { w: string; h: string; radius?: string }) {
  return (
    <View
      style={{
        width: w,
        height: h,
        borderRadius: radius,
        background: C.card,
        opacity: 0.7,
        flexShrink: 0,
      }}
    />
  )
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function IndexPage() {
  const storeId   = useStoreInfo((s) => s.storeId)
  const storeName = useStoreInfo((s) => s.storeName)
  const tableNo   = useStoreInfo((s) => s.tableNo)
  const { addItem, removeItem, items, totalFen, totalCount } = useCartStore()

  const [hotDishes,  setHotDishes]  = useState<MockDish[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string | null>(null)

  // ── 千人千面布局引擎 ───────────────────────────────────────────────────────
  const { memberLevel, pointsBalance, nickname } = useUserStore()
  const [layout, setLayout] = useState<PersonalizedLayout | null>(null)

  useEffect(() => {
    const l = getPersonalizedLayout({
      memberLevel: memberLevel || 'none',
      pointsBalance: pointsBalance || 0,
      isSubscriber: false, // TODO: 从订阅状态读取
      daysSinceLastVisit: 3,
      nickname: nickname || '',
    })
    setLayout(l)
  }, [memberLevel, pointsBalance, nickname])

  // ── Load ───────────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const dishProm = storeId
      ? getDishes(storeId).then((ds) =>
          ds
            .filter((d) => d.isActive && d.status !== 'off_shelf')
            .sort((a, b) => (b.salesCount ?? 0) - (a.salesCount ?? 0))
            .slice(0, 8)
            .map(dishToCard),
        )
      : Promise.resolve([] as MockDish[])

    const actProm = getActivities().then((acts) =>
      acts.filter((a) => a.isActive).slice(0, 3),
    )

    Promise.all([dishProm, actProm])
      .then(([dishes, acts]) => {
        if (cancelled) return
        setHotDishes(dishes)
        setActivities(acts)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('[IndexPage] load error', err)
        setError('加载失败，请下拉刷新重试')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [storeId])

  // ── Cart helpers ───────────────────────────────────────────────────────────
  const getQty = useCallback(
    (id: string) => items.find((i) => i.dishId === id)?.quantity ?? 0,
    [items],
  )
  const handleAdd = useCallback(
    (d: MockDish) => addItem({ dishId: d.id, name: d.name, price_fen: d.price_fen }),
    [addItem],
  )
  const handleRemove = useCallback((id: string) => removeItem(id), [removeItem])

  // ── Navigation ─────────────────────────────────────────────────────────────
  const goEntry = (entry: Record<string, unknown>) => {
    const path = (entry.tabPath || entry.navPath || entry.path || '') as string
    if (!path) return
    // TabBar页面用switchTab，其他用navigateTo
    if (path.startsWith('/pages/')) {
      Taro.switchTab({ url: path }).catch(() =>
        Taro.navigateTo({ url: path }).catch(() =>
          Taro.showToast({ title: '页面开发中', icon: 'none' }),
        ),
      )
    } else {
      Taro.navigateTo({ url: path }).catch(() =>
        Taro.showToast({ title: '页面开发中', icon: 'none' }),
      )
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <View style={{ minHeight: '100vh', background: C.bg }}>
      <ScrollView
        scrollY
        style={{ minHeight: '100vh' }}
        enablePullDownRefresh={false}
      >
        {/* ─── Store header ─── */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '48rpx 32rpx 20rpx',
          }}
        >
          <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
            {storeName || '屯象餐厅'}
          </Text>
          <View
            style={{
              background: 'rgba(255,107,53,0.12)',
              borderRadius: '20rpx',
              padding: '8rpx 22rpx',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '26rpx' }}>
              {tableNo ? `${tableNo}号桌` : '请扫码入座'}
            </Text>
          </View>
        </View>

        {/* ─── 智能复购提醒 ─── */}
        <ReorderBanner storeId={storeId} />

        {/* ─── Banner carousel ─── */}
        {loading ? (
          <View
            style={{
              height: '320rpx',
              borderRadius: '20rpx',
              margin: '0 32rpx 32rpx',
              background: C.card,
            }}
          />
        ) : (
          <Swiper
            style={{
              height: '320rpx',
              borderRadius: '20rpx',
              margin: '0 32rpx 32rpx',
              overflow: 'hidden',
            }}
            autoplay
            interval={3000}
            circular
            indicatorDots
            indicatorColor="rgba(255,255,255,0.3)"
            indicatorActiveColor={C.primary}
          >
            {BANNERS.map((b) => (
              <SwiperItem key={b.id}>
                <View
                  style={{
                    height: '320rpx',
                    background: b.color,
                    borderRadius: '20rpx',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '0 40rpx',
                  }}
                >
                  <Text
                    style={{
                      color: C.text1,
                      fontSize: '40rpx',
                      fontWeight: '700',
                      lineHeight: '56rpx',
                    }}
                  >
                    {b.title}
                  </Text>
                  <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '12rpx' }}>
                    {b.subtitle}
                  </Text>
                </View>
              </SwiperItem>
            ))}
          </Swiper>
        )}

        {/* ─── Quick entry 2×3 ─── */}
        <View style={{ padding: '0 32rpx 12rpx' }}>
          <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', marginBottom: '20rpx', display: 'block' }}>
            快捷入口
          </Text>
          <View
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '16rpx',
            }}
          >
            {(layout?.quickEntries ?? QUICK_ENTRIES).map((e) => (
              <View
                key={e.id}
                style={{
                  background: C.card,
                  borderRadius: '20rpx',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '28rpx 0',
                  gap: '10rpx',
                }}
                onClick={() => goEntry(e)}
              >
                <Text style={{ fontSize: '44rpx', lineHeight: '1' }}>{e.icon}</Text>
                <Text style={{ color: C.text2, fontSize: '24rpx' }}>{e.label}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* ─── AI 推荐 ─── */}
        <View style={{ padding: '28rpx 32rpx 12rpx' }}>
          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', marginBottom: '16rpx', gap: '12rpx' }}>
            <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>AI 智能推荐</Text>
            <View
              style={{
                background: 'rgba(24,95,165,0.2)',
                borderRadius: '8rpx',
                padding: '4rpx 14rpx',
              }}
            >
              <Text style={{ color: '#5FA8E8', fontSize: '20rpx', fontWeight: '600' }}>AI</Text>
            </View>
          </View>
        </View>
        <AiRecommend
          dishes={AI_MOCK}
          onAdd={handleAdd}
          onRemove={handleRemove}
          getQuantity={getQty}
        />

        {/* ─── 今日活动 ─── */}
        {(loading || activities.length > 0) && (
          <View style={{ marginTop: '12rpx' }}>
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '20rpx 32rpx 16rpx',
              }}
            >
              <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>今日活动</Text>
              <Text
                style={{ color: C.primary, fontSize: '26rpx' }}
                onClick={() => Taro.showToast({ title: '更多活动开发中', icon: 'none' })}
              >
                更多
              </Text>
            </View>
            <ScrollView scrollX style={{ paddingLeft: '32rpx', paddingBottom: '4rpx', whiteSpace: 'nowrap' }}>
              {loading
                ? [1, 2, 3].map((i) => (
                    <View
                      key={i}
                      style={{
                        display: 'inline-block',
                        width: '360rpx',
                        height: '260rpx',
                        background: C.card,
                        borderRadius: '20rpx',
                        marginRight: '20rpx',
                        verticalAlign: 'top',
                      }}
                    />
                  ))
                : activities.map((act) => (
                    <View
                      key={act.activityId}
                      style={{
                        display: 'inline-flex',
                        flexDirection: 'column',
                        width: '360rpx',
                        background: C.card,
                        borderRadius: '20rpx',
                        marginRight: '20rpx',
                        overflow: 'hidden',
                        verticalAlign: 'top',
                      }}
                      onClick={() => Taro.showToast({ title: act.name, icon: 'none' })}
                    >
                      <View
                        style={{
                          width: '360rpx',
                          height: '180rpx',
                          background: '#1A3040',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        {act.imageUrl ? (
                          <Image
                            src={act.imageUrl}
                            style={{ width: '360rpx', height: '180rpx' }}
                            mode="aspectFill"
                            lazyLoad
                          />
                        ) : (
                          <Text style={{ fontSize: '56rpx' }}>{activityEmoji(act.type)}</Text>
                        )}
                      </View>
                      <View style={{ padding: '16rpx 20rpx' }}>
                        {act.badgeText && (
                          <View
                            style={{
                              display: 'inline-block',
                              background: 'rgba(255,107,53,0.15)',
                              borderRadius: '8rpx',
                              padding: '4rpx 12rpx',
                              marginBottom: '8rpx',
                            }}
                          >
                            <Text style={{ color: C.primary, fontSize: '20rpx' }}>{act.badgeText}</Text>
                          </View>
                        )}
                        <Text
                          style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600', display: 'block' }}
                          numberOfLines={1}
                        >
                          {act.name}
                        </Text>
                        <Text style={{ color: C.text2, fontSize: '22rpx', marginTop: '6rpx', display: 'block' }}>
                          至 {act.validUntil.slice(0, 10)}
                        </Text>
                      </View>
                    </View>
                  ))}
              {/* trailing spacer for scroll */}
              <View style={{ display: 'inline-block', width: '12rpx' }} />
            </ScrollView>
          </View>
        )}

        {/* ─── Error banner ─── */}
        {error && (
          <View
            style={{
              margin: '24rpx 32rpx 0',
              background: 'rgba(163,45,45,0.12)',
              borderRadius: '16rpx',
              padding: '20rpx 24rpx',
              display: 'flex',
              alignItems: 'center',
              gap: '12rpx',
            }}
          >
            <Text style={{ fontSize: '32rpx' }}>⚠️</Text>
            <Text style={{ color: '#E8A0A0', fontSize: '26rpx', flex: 1 }}>{error}</Text>
          </View>
        )}

        {/* ─── 热销推荐 ─── */}
        <View style={{ marginTop: '28rpx' }}>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 32rpx 20rpx',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>热销推荐</Text>
            <Text
              style={{ color: C.primary, fontSize: '26rpx' }}
              onClick={() => Taro.switchTab({ url: '/pages/menu/index' })}
            >
              查看全部
            </Text>
          </View>

          {loading ? (
            <View
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: '16rpx',
                padding: '0 32rpx',
              }}
            >
              {[1, 2, 3, 4].map((i) => (
                <View key={i} style={{ height: '260rpx', background: C.card, borderRadius: '16rpx' }} />
              ))}
            </View>
          ) : hotDishes.length > 0 ? (
            <View
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: '16rpx',
                padding: '0 32rpx',
              }}
            >
              {hotDishes.map((dish) => (
                <DishCard
                  key={dish.id}
                  dish={dish}
                  quantity={getQty(dish.id)}
                  onAdd={() => handleAdd(dish)}
                  onRemove={() => handleRemove(dish.id)}
                  onTap={() =>
                    Taro.navigateTo({
                      url: `/subpackages/order-flow/scan-order/index?dish_id=${dish.id}`,
                    })
                  }
                />
              ))}
            </View>
          ) : (
            !error && (
              <View
                style={{
                  padding: '48rpx 32rpx',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '16rpx',
                }}
              >
                <Text style={{ fontSize: '64rpx' }}>🍽</Text>
                <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无热销菜品</Text>
              </View>
            )
          )}
        </View>

        {/* Bottom safe area above CartBar */}
        <View style={{ height: '180rpx' }} />
      </ScrollView>

      {/* ─── CartBar ─── */}
      <CartBar
        totalFen={totalFen}
        totalCount={totalCount}
        onTap={() => Taro.navigateTo({ url: '/subpackages/order-flow/cart/index' })}
        onCheckout={() => Taro.navigateTo({ url: '/subpackages/order-flow/checkout/index' })}
      />
    </View>
  )
}
