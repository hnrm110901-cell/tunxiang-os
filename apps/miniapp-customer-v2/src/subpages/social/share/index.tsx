/**
 * share/index.tsx — 分享中心
 *
 * Sections:
 *  1. Poster builder — dish picker, store selector, badge customizer, preview, "生成海报"
 *  2. Quick share options — 菜单/门店/优惠/活动
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getActivities } from '../../../api/growth'
import type { Activity } from '../../../api/growth'
import { SharePoster } from '../../../components/SharePoster'
import { txRequest } from '../../../utils/request'
import { useUserStore } from '../../../store/useUserStore'
import { truncate } from '../../../utils/format'

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
  white: '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface PopularDish {
  dishId: string
  name: string
  imageUrl?: string
  category: string
}

interface StoreInfo {
  storeId: string
  name: string
  address: string
  lat?: number
  lng?: number
}

type BadgeOption = 'none' | '80' | '90' | 'limited' | 'custom'

interface BadgeDef {
  key: BadgeOption
  label: string
  displayText: string
}

const BADGE_OPTIONS: BadgeDef[] = [
  { key: 'none',    label: '无',       displayText: '' },
  { key: '80',      label: '8折',      displayText: '8折优惠' },
  { key: '90',      label: '9折',      displayText: '9折优惠' },
  { key: 'limited', label: '限时优惠', displayText: '限时优惠' },
  { key: 'custom',  label: '自定义',   displayText: '' },
]

// ─── Dish picker ──────────────────────────────────────────────────────────────

interface DishPickerProps {
  dishes: PopularDish[]
  selectedId: string | null
  onSelect: (dish: PopularDish) => void
}

function DishPicker({ dishes, selectedId, onSelect }: DishPickerProps) {
  if (dishes.length === 0) {
    return (
      <View
        style={{
          height: '160rpx',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.text3, fontSize: '26rpx' }}>暂无热门菜品</Text>
      </View>
    )
  }

  return (
    <ScrollView scrollX style={{ margin: '0 24rpx' }}>
      <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx', paddingBottom: '4rpx' }}>
        {dishes.map((dish) => {
          const active = selectedId === dish.dishId
          return (
            <View
              key={dish.dishId}
              onClick={() => onSelect(dish)}
              style={{
                width: '140rpx',
                flexShrink: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
              }}
            >
              {/* Dish image placeholder */}
              <View
                style={{
                  width: '120rpx',
                  height: '120rpx',
                  borderRadius: '16rpx',
                  background: active ? `rgba(255,107,44,0.15)` : C.bgCard,
                  border: `2rpx solid ${active ? C.primary : C.border}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '8rpx',
                  overflow: 'hidden',
                }}
              >
                {dish.imageUrl ? (
                  // In a real app: <Image src={dish.imageUrl} style={{ width: '100%', height: '100%' }} mode='aspectFill' />
                  <Text style={{ fontSize: '48rpx' }}>🍜</Text>
                ) : (
                  <Text style={{ fontSize: '48rpx' }}>🍜</Text>
                )}
              </View>
              <Text
                style={{
                  color: active ? C.primary : C.text2,
                  fontSize: '22rpx',
                  textAlign: 'center',
                  fontWeight: active ? '600' : '400',
                }}
              >
                {truncate(dish.name, 5)}
              </Text>
            </View>
          )
        })}
      </View>
    </ScrollView>
  )
}

// ─── Store selector ───────────────────────────────────────────────────────────

interface StoreSelectorProps {
  stores: StoreInfo[]
  selectedId: string | null
  onSelect: (store: StoreInfo) => void
}

function StoreSelector({ stores, selectedId, onSelect }: StoreSelectorProps) {
  if (stores.length <= 1) return null // single-store users skip this

  return (
    <View style={{ margin: '0 24rpx' }}>
      {stores.map((store) => {
        const active = selectedId === store.storeId
        return (
          <View
            key={store.storeId}
            onClick={() => onSelect(store)}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              background: active ? `rgba(255,107,44,0.08)` : C.bgCard,
              borderRadius: '16rpx',
              padding: '20rpx 24rpx',
              marginBottom: '12rpx',
              border: `1rpx solid ${active ? C.primary : C.border}`,
            }}
          >
            <View
              style={{
                width: '12rpx',
                height: '12rpx',
                borderRadius: '50%',
                background: active ? C.primary : C.border,
                marginRight: '16rpx',
                flexShrink: 0,
              }}
            />
            <View style={{ flex: 1 }}>
              <Text style={{ color: active ? C.primary : C.text1, fontSize: '28rpx', fontWeight: '600', display: 'block' }}>
                {store.name}
              </Text>
              <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                {store.address}
              </Text>
            </View>
          </View>
        )
      })}
    </View>
  )
}

// ─── Badge customizer ─────────────────────────────────────────────────────────

interface BadgeCustomizerProps {
  selectedBadge: BadgeOption
  customText: string
  onBadgeChange: (badge: BadgeOption) => void
  onCustomTextChange: (text: string) => void
}

function BadgeCustomizer({
  selectedBadge,
  customText,
  onBadgeChange,
  onCustomTextChange,
}: BadgeCustomizerProps) {
  return (
    <View style={{ margin: '0 24rpx' }}>
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: '12rpx',
          marginBottom: selectedBadge === 'custom' ? '16rpx' : 0,
        }}
      >
        {BADGE_OPTIONS.map((opt) => {
          const active = selectedBadge === opt.key
          return (
            <View
              key={opt.key}
              onClick={() => onBadgeChange(opt.key)}
              style={{
                padding: '14rpx 28rpx',
                borderRadius: '40rpx',
                background: active ? C.primary : C.bgCard,
                border: `1rpx solid ${active ? C.primary : C.border}`,
              }}
            >
              <Text
                style={{
                  color: active ? C.white : C.text2,
                  fontSize: '26rpx',
                  fontWeight: active ? '600' : '400',
                }}
              >
                {opt.label}
              </Text>
            </View>
          )
        })}
      </View>

      {selectedBadge === 'custom' && (
        <View
          style={{
            background: C.bgCard,
            borderRadius: '16rpx',
            border: `1rpx solid ${C.border}`,
            padding: '18rpx 24rpx',
          }}
        >
          <Input
            placeholder='自定义文字（最多8字）'
            placeholderStyle={`color: ${C.text3}; font-size: 26rpx;`}
            value={customText}
            onInput={(e) => onCustomTextChange(e.detail.value.slice(0, 8))}
            maxlength={8}
            style={{ color: C.text1, fontSize: '28rpx' }}
          />
        </View>
      )}
    </View>
  )
}

// ─── Poster preview mock ──────────────────────────────────────────────────────

interface PosterPreviewProps {
  dishName: string
  storeName: string
  badgeText: string
}

function PosterPreview({ dishName, storeName, badgeText }: PosterPreviewProps) {
  return (
    <View style={{ margin: '0 24rpx' }}>
      <View
        style={{
          background: `linear-gradient(160deg, #1A2E3A 0%, ${C.bgDeep} 100%)`,
          borderRadius: '24rpx',
          border: `1rpx solid ${C.border}`,
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {/* Dish image area */}
        <View
          style={{
            height: '280rpx',
            background: C.bgCard,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative',
          }}
        >
          <Text style={{ fontSize: '100rpx' }}>🍜</Text>

          {/* Badge */}
          {badgeText && (
            <View
              style={{
                position: 'absolute',
                top: '20rpx',
                right: '20rpx',
                background: C.primary,
                borderRadius: '40rpx',
                padding: '8rpx 20rpx',
              }}
            >
              <Text style={{ color: C.white, fontSize: '24rpx', fontWeight: '700' }}>
                {badgeText}
              </Text>
            </View>
          )}
        </View>

        {/* Info area */}
        <View style={{ padding: '24rpx 28rpx' }}>
          <Text
            style={{
              color: C.text1,
              fontSize: '32rpx',
              fontWeight: '700',
              display: 'block',
              marginBottom: '8rpx',
            }}
          >
            {dishName || '选择一道菜品'}
          </Text>
          <Text style={{ color: C.text3, fontSize: '24rpx', display: 'block', marginBottom: '16rpx' }}>
            {storeName || '屯象OS门店'}
          </Text>

          {/* Mock QR */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '16rpx',
            }}
          >
            <View
              style={{
                width: '72rpx',
                height: '72rpx',
                background: '#E0E0E0',
                borderRadius: '8rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ fontSize: '40rpx' }}>▦</Text>
            </View>
            <View>
              <Text style={{ color: C.text2, fontSize: '24rpx', display: 'block' }}>
                扫码点餐
              </Text>
              <Text style={{ color: C.text3, fontSize: '20rpx' }}>
                长按识别二维码
              </Text>
            </View>
          </View>
        </View>
      </View>
    </View>
  )
}

// ─── Quick share options ──────────────────────────────────────────────────────

interface QuickShareOption {
  key: string
  icon: string
  label: string
  desc: string
  color: string
  buildShare: (stores: StoreInfo[], activities: Activity[]) => {
    title: string
    path: string
    imageUrl: string
  }
}

const QUICK_SHARE_OPTIONS: QuickShareOption[] = [
  {
    key: 'menu',
    icon: '📋',
    label: '分享菜单',
    desc: '让朋友提前看菜单',
    color: '#2196F3',
    buildShare: (stores) => ({
      title: '屯象OS美食菜单，快来看看！',
      path: `/pages/menu/index?storeId=${stores[0]?.storeId ?? ''}`,
      imageUrl: '',
    }),
  },
  {
    key: 'store',
    icon: '📍',
    label: '分享门店',
    desc: '附地图位置一键导航',
    color: '#4CAF50',
    buildShare: (stores) => ({
      title: `${stores[0]?.name ?? '屯象OS'} — 美味等你来！`,
      path: `/pages/store/index?storeId=${stores[0]?.storeId ?? ''}`,
      imageUrl: '',
    }),
  },
  {
    key: 'coupon',
    icon: '🎫',
    label: '分享优惠',
    desc: '好友领券立享折扣',
    color: '#FF6B2C',
    buildShare: () => ({
      title: '屯象OS优惠券，限时领取！',
      path: '/pages/coupon/claim/index',
      imageUrl: '',
    }),
  },
  {
    key: 'activity',
    icon: '🔥',
    label: '分享活动',
    desc: '当前热门促销活动',
    color: '#FF5722',
    buildShare: (_, activities) => {
      const active = activities.find((a) => a.isActive)
      return {
        title: active ? active.name : '屯象OS精彩活动，不容错过！',
        path: active
          ? `/pages/activity/detail/index?activityId=${active.activityId}`
          : '/pages/activity/index',
        imageUrl: active?.imageUrl ?? '',
      }
    },
  },
]

interface QuickSharePanelProps {
  stores: StoreInfo[]
  activities: Activity[]
}

function QuickSharePanel({ stores, activities }: QuickSharePanelProps) {
  const handleQuickShare = useCallback(
    (opt: QuickShareOption) => {
      const shareData = opt.buildShare(stores, activities)
      Taro.shareAppMessage({
        title: shareData.title,
        path: shareData.path,
        imageUrl: shareData.imageUrl,
      })
    },
    [stores, activities],
  )

  return (
    <View style={{ margin: '0 24rpx' }}>
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: '16rpx',
        }}
      >
        {QUICK_SHARE_OPTIONS.map((opt) => (
          <View
            key={opt.key}
            onClick={() => handleQuickShare(opt)}
            style={{
              width: 'calc(50% - 8rpx)',
              background: C.bgCard,
              borderRadius: '20rpx',
              border: `1rpx solid ${C.border}`,
              padding: '24rpx',
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '16rpx',
            }}
          >
            {/* Icon circle */}
            <View
              style={{
                width: '72rpx',
                height: '72rpx',
                borderRadius: '50%',
                background: `${opt.color}22`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Text style={{ fontSize: '36rpx' }}>{opt.icon}</Text>
            </View>

            <View style={{ flex: 1, minWidth: 0 }}>
              <Text
                style={{
                  color: C.text1,
                  fontSize: '26rpx',
                  fontWeight: '600',
                  display: 'block',
                }}
              >
                {opt.label}
              </Text>
              <Text
                style={{
                  color: C.text3,
                  fontSize: '22rpx',
                  display: 'block',
                  marginTop: '4rpx',
                }}
              >
                {opt.desc}
              </Text>
            </View>
          </View>
        ))}
      </View>
    </View>
  )
}

// ─── Section header ───────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <View style={{ margin: '32rpx 24rpx 16rpx' }}>
      <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '12rpx' }}>
        <View
          style={{
            width: '6rpx',
            height: '32rpx',
            background: C.primary,
            borderRadius: '3rpx',
          }}
        />
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>{title}</Text>
      </View>
      {subtitle && (
        <Text
          style={{
            color: C.text3,
            fontSize: '24rpx',
            display: 'block',
            marginTop: '6rpx',
            marginLeft: '18rpx',
          }}
        >
          {subtitle}
        </Text>
      )}
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SharePage() {
  const { nickname } = useUserStore()

  // Data
  const [dishes, setDishes] = useState<PopularDish[]>([])
  const [stores, setStores] = useState<StoreInfo[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [loading, setLoading] = useState(true)

  // Poster builder state
  const [selectedDish, setSelectedDish] = useState<PopularDish | null>(null)
  const [selectedStore, setSelectedStore] = useState<StoreInfo | null>(null)
  const [selectedBadge, setSelectedBadge] = useState<BadgeOption>('none')
  const [customBadgeText, setCustomBadgeText] = useState('')
  const [posterVisible, setPosterVisible] = useState(false)

  // Load data
  useEffect(() => {
    const loadData = async () => {
      try {
        const [dishData, storeData, activityData] = await Promise.allSettled([
          txRequest<PopularDish[]>('/api/v1/menu/popular-dishes?limit=10'),
          txRequest<StoreInfo[]>('/api/v1/stores/my-stores'),
          getActivities(),
        ])

        if (dishData.status === 'fulfilled') setDishes(dishData.value)
        if (storeData.status === 'fulfilled') {
          const storeList = storeData.value
          setStores(storeList)
          if (storeList.length > 0) setSelectedStore(storeList[0])
        }
        if (activityData.status === 'fulfilled') setActivities(activityData.value)
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [])

  const effectiveBadgeText =
    selectedBadge === 'none'
      ? ''
      : selectedBadge === 'custom'
      ? customBadgeText
      : BADGE_OPTIONS.find((b) => b.key === selectedBadge)?.displayText ?? ''

  const handleGeneratePoster = useCallback(() => {
    if (!selectedDish) {
      Taro.showToast({ title: '请先选择一道菜品', icon: 'none', duration: 1500 })
      return
    }
    setPosterVisible(true)
  }, [selectedDish])

  return (
    <View style={{ height: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
      {/* Page title */}
      <View
        style={{
          padding: '40rpx 32rpx 16rpx',
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
          分享中心
        </Text>
      </View>

      <ScrollView scrollY style={{ flex: 1 }}>
        {/* ── Section 1: Poster builder ────────────────────────────────── */}
        <SectionHeader
          title="制作推广海报"
          subtitle="选择菜品和样式，一键生成精美海报"
        />

        {/* Dish picker */}
        <Text
          style={{
            color: C.text3,
            fontSize: '24rpx',
            display: 'block',
            margin: '0 24rpx 12rpx',
          }}
        >
          选择主角菜品
        </Text>
        {loading ? (
          <View style={{ padding: '32rpx', textAlign: 'center' }}>
            <Text style={{ color: C.text3, fontSize: '26rpx' }}>加载中…</Text>
          </View>
        ) : (
          <DishPicker
            dishes={dishes}
            selectedId={selectedDish?.dishId ?? null}
            onSelect={setSelectedDish}
          />
        )}

        {/* Store selector (only if multi-store) */}
        {stores.length > 1 && (
          <>
            <Text
              style={{
                color: C.text3,
                fontSize: '24rpx',
                display: 'block',
                margin: '20rpx 24rpx 12rpx',
              }}
            >
              选择门店
            </Text>
            <StoreSelector
              stores={stores}
              selectedId={selectedStore?.storeId ?? null}
              onSelect={setSelectedStore}
            />
          </>
        )}

        {/* Badge customizer */}
        <Text
          style={{
            color: C.text3,
            fontSize: '24rpx',
            display: 'block',
            margin: '20rpx 24rpx 12rpx',
          }}
        >
          优惠标签
        </Text>
        <BadgeCustomizer
          selectedBadge={selectedBadge}
          customText={customBadgeText}
          onBadgeChange={setSelectedBadge}
          onCustomTextChange={setCustomBadgeText}
        />

        {/* Poster preview */}
        <Text
          style={{
            color: C.text3,
            fontSize: '24rpx',
            display: 'block',
            margin: '20rpx 24rpx 12rpx',
          }}
        >
          海报预览
        </Text>
        <PosterPreview
          dishName={selectedDish?.name ?? ''}
          storeName={selectedStore?.name ?? ''}
          badgeText={effectiveBadgeText}
        />

        {/* Generate button */}
        <View style={{ margin: '20rpx 24rpx 0' }}>
          <View
            onClick={handleGeneratePoster}
            style={{
              background: selectedDish ? C.primary : C.bgCard,
              borderRadius: '48rpx',
              padding: '28rpx 0',
              textAlign: 'center',
              border: `1rpx solid ${selectedDish ? C.primary : C.border}`,
            }}
          >
            <Text
              style={{
                color: selectedDish ? C.white : C.text3,
                fontSize: '32rpx',
                fontWeight: '700',
              }}
            >
              生成海报
            </Text>
          </View>
        </View>

        {/* Tip */}
        {!selectedDish && (
          <Text
            style={{
              color: C.text3,
              fontSize: '22rpx',
              display: 'block',
              textAlign: 'center',
              marginTop: '12rpx',
            }}
          >
            请先选择一道菜品
          </Text>
        )}

        {/* ── Section 2: Quick share ────────────────────────────────────── */}
        <SectionHeader
          title="快速分享"
          subtitle="一键分享给微信好友或朋友圈"
        />
        <QuickSharePanel stores={stores} activities={activities} />

        {/* Share tips */}
        <View
          style={{
            margin: '24rpx 24rpx 48rpx',
            background: C.bgCard,
            borderRadius: '20rpx',
            padding: '24rpx 28rpx',
            border: `1rpx solid ${C.border}`,
          }}
        >
          <Text style={{ color: C.text2, fontSize: '26rpx', fontWeight: '600', display: 'block', marginBottom: '12rpx' }}>
            分享小贴士
          </Text>
          {[
            '生成海报后可长按保存到相册，再发给朋友',
            '分享链接后，好友点击可直接跳转到对应页面',
            '附带邀请码分享，好友注册后您可获得邀请奖励',
          ].map((tip, i) => (
            <Text
              key={i}
              style={{
                color: C.text3,
                fontSize: '24rpx',
                display: 'block',
                marginTop: '8rpx',
              }}
            >
              · {tip}
            </Text>
          ))}
        </View>
      </ScrollView>

      {/* SharePoster modal — rendered by the component itself */}
      <SharePoster
        visible={posterVisible}
        dishName={selectedDish?.name ?? ''}
        storeName={selectedStore?.name ?? ''}
        discount={effectiveBadgeText || undefined}
        dishImageUrl={selectedDish?.imageUrl}
        onClose={() => setPosterVisible(false)}
      />
    </View>
  )
}
