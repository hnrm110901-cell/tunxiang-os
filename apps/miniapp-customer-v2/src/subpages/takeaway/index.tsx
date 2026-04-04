/**
 * takeaway/index.tsx — 外卖点餐
 *
 * 外卖点餐首页：选地址、浏览菜品、加购物车、去结算
 * 与堂食菜单页(pages/menu)类似但增加了配送地址和起送金额逻辑
 *
 * Entry: 首页外卖入口 / 小程序外卖场景码
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, Image, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useCartStore } from '../../store/useCartStore'
import { useStoreInfo } from '../../store/useStoreInfo'
import { txRequest } from '../../utils/request'
import './index.scss'

// ─── Brand tokens ────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B2C',
  primaryDark: '#E55A1F',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  bgHover:     '#1A2E38',
  border:      '#1E3340',
  success:     '#34C759',
  warning:     '#FF9F0A',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Types ──────────────────────────────────────────────────────────────────

interface DeliveryAddress {
  id: string
  name: string
  phone: string
  region: string
  detail: string
  tag: string
  is_default: boolean
}

interface MenuCategory {
  id: string
  name: string
  sort_order: number
}

interface TakeawayDish {
  id: string
  name: string
  image_url: string
  price_fen: number
  original_price_fen?: number
  description: string
  category_id: string
  sold_count: number
  is_available: boolean
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  if (fen % 100 === 0) return String(fen / 100)
  return (fen / 100).toFixed(2)
}

function calcEstimatedTime(): string {
  const now = new Date()
  let min = now.getMinutes() + 35
  let h = now.getHours()
  if (min >= 60) { h += 1; min -= 60 }
  if (h >= 24) h -= 24
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`)
  return `${pad(h)}:${pad(min)}`
}

// ─── Component ──────────────────────────────────────────────────────────────

const TakeawayPage: React.FC = () => {
  const router = useRouter()
  const storeInfo = useStoreInfo()
  const cartItems = useCartStore((s) => s.items)
  const totalFen = useCartStore((s) => s.totalFen)
  const totalCount = useCartStore((s) => s.totalCount)
  const addItem = useCartStore((s) => s.addItem)

  // Address
  const [address, setAddress] = useState<DeliveryAddress | null>(null)
  const [estimatedTime, setEstimatedTime] = useState('')

  // Menu
  const [categories, setCategories] = useState<MenuCategory[]>([])
  const [dishes, setDishes] = useState<TakeawayDish[]>([])
  const [activeCategoryId, setActiveCategoryId] = useState('')
  const [loading, setLoading] = useState(true)

  // Delivery minimum
  const [minDeliveryFen] = useState(2000) // 20 yuan default
  const reachedMin = totalFen >= minDeliveryFen
  const remainFen = Math.max(0, minDeliveryFen - totalFen)

  // Cart popup
  const [showCartPopup, setShowCartPopup] = useState(false)

  const storeId = router.params.store_id || storeInfo.storeId || ''

  // ─── Load default address ──────────────────────────────────────────────────

  const loadDefaultAddress = useCallback(async () => {
    try {
      const data = await txRequest<{ items: DeliveryAddress[] } | DeliveryAddress[]>(
        '/api/v1/member/addresses',
      )
      const items = Array.isArray(data) ? data : (data.items || [])
      const defaultAddr = items.find((a) => a.is_default) || items[0] || null
      setAddress(defaultAddr)
      setEstimatedTime(calcEstimatedTime())
    } catch (_) {
      // Dev fallback
      setAddress({
        id: 'mock1', name: '张三', phone: '138****8888',
        region: '湖南省长沙市岳麓区', detail: '麓谷街道中电软件园1号楼',
        tag: '公司', is_default: true,
      })
      setEstimatedTime(calcEstimatedTime())
    }
  }, [])

  // ─── Load menu ─────────────────────────────────────────────────────────────

  const loadMenu = useCallback(async () => {
    if (!storeId) return
    setLoading(true)

    try {
      const [catData, dishData] = await Promise.all([
        txRequest<{ items: MenuCategory[] }>(`/api/v1/menu/categories?store_id=${storeId}`),
        txRequest<{ items: TakeawayDish[] }>(
          `/api/v1/menu/dishes?store_id=${storeId}&channel=takeaway`,
        ),
      ])

      const cats = catData.items || []
      const allDishes = (dishData.items || []).filter((d) => d.is_available)

      cats.sort((a, b) => a.sort_order - b.sort_order)
      setCategories(cats)
      setDishes(allDishes)

      if (cats.length > 0) {
        setActiveCategoryId(cats[0].id)
      }
    } catch (_) {
      Taro.showToast({ title: '菜单加载失败', icon: 'none' })
    } finally {
      setLoading(false)
    }
  }, [storeId])

  useEffect(() => {
    loadDefaultAddress()
    loadMenu()
  }, [loadDefaultAddress, loadMenu])

  // ─── Actions ───────────────────────────────────────────────────────────────

  const onChooseAddress = () => {
    Taro.navigateTo({ url: '/subpages/address/index?select=1' })
  }

  // Check for returned address on show
  Taro.useDidShow(() => {
    const pages = Taro.getCurrentPages()
    const currentPage = pages[pages.length - 1] as Record<string, unknown>
    if (currentPage._selectedAddress) {
      setAddress(currentPage._selectedAddress as DeliveryAddress)
      setEstimatedTime(calcEstimatedTime())
      currentPage._selectedAddress = null
    }
  })

  const onSelectCategory = (catId: string) => {
    setActiveCategoryId(catId)
  }

  const filteredDishes = activeCategoryId
    ? dishes.filter((d) => d.category_id === activeCategoryId)
    : dishes

  const onAddDish = (dish: TakeawayDish) => {
    addItem({
      dishId: dish.id,
      name: dish.name,
      price_fen: dish.price_fen,
      quantity: 1,
    })
    Taro.showToast({ title: '已加入', icon: 'success', duration: 800 })
  }

  const onDishDetail = (id: string) => {
    Taro.navigateTo({
      url: `/subpages/dish-detail/index?id=${id}&store_id=${storeId}`,
    })
  }

  const onGoCheckout = () => {
    if (!reachedMin) {
      Taro.showToast({
        title: `还差¥${fenToYuan(remainFen)}起送`,
        icon: 'none',
      })
      return
    }
    if (!address) {
      Taro.showToast({ title: '请先选择收货地址', icon: 'none' })
      return
    }
    Taro.navigateTo({ url: '/subpages/order-flow/checkout/index?channel=takeaway' })
  }

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <View className="takeaway-page">
      {/* Address Bar */}
      <View className="address-bar" onClick={onChooseAddress}>
        {address ? (
          <View className="address-info">
            <View className="address-row-top">
              <Text className="address-label">{address.tag || '送至'}</Text>
              <Text className="address-brief">{address.region}{address.detail}</Text>
            </View>
            <View className="address-row-bottom">
              <Text className="address-contact">{address.name} {address.phone}</Text>
              <Text className="estimated-time">预计 {estimatedTime} 送达</Text>
            </View>
          </View>
        ) : (
          <View className="address-empty">
            <Text className="address-empty-text">请选择收货地址</Text>
          </View>
        )}
        <Text className="arrow-right">›</Text>
      </View>

      {/* Main content: categories + dishes */}
      <View className="menu-body">
        {/* Left category nav */}
        <ScrollView scrollY className="category-nav">
          {categories.map((cat) => (
            <View
              key={cat.id}
              className={`cat-item ${activeCategoryId === cat.id ? 'active' : ''}`}
              onClick={() => onSelectCategory(cat.id)}
            >
              <Text className="cat-name">{cat.name}</Text>
            </View>
          ))}
        </ScrollView>

        {/* Right dish list */}
        <ScrollView scrollY className="dish-list">
          {loading && (
            <View className="loading-area">
              {[1, 2, 3, 4].map((i) => (
                <View key={i} className="skeleton-dish">
                  <View className="skeleton-img" />
                  <View className="skeleton-text">
                    <View className="skeleton-line w60" />
                    <View className="skeleton-line w40" />
                  </View>
                </View>
              ))}
            </View>
          )}

          {!loading && filteredDishes.length === 0 && (
            <View className="empty-dishes">
              <Text className="empty-dishes-text">暂无可配送菜品</Text>
            </View>
          )}

          {!loading && filteredDishes.map((dish) => (
            <View key={dish.id} className="dish-card" onClick={() => onDishDetail(dish.id)}>
              {dish.image_url ? (
                <Image className="dish-image" src={dish.image_url} mode="aspectFill" />
              ) : (
                <View className="dish-image-placeholder" />
              )}
              <View className="dish-info">
                <Text className="dish-name" numberOfLines={1}>{dish.name}</Text>
                {dish.description && (
                  <Text className="dish-desc" numberOfLines={1}>{dish.description}</Text>
                )}
                <View className="dish-bottom">
                  <View className="dish-price-row">
                    <Text className="dish-price">¥{fenToYuan(dish.price_fen)}</Text>
                    {dish.original_price_fen && dish.original_price_fen > dish.price_fen && (
                      <Text className="dish-original-price">
                        ¥{fenToYuan(dish.original_price_fen)}
                      </Text>
                    )}
                  </View>
                  <Text className="dish-sold">月售 {dish.sold_count}</Text>
                </View>
              </View>
              <View
                className="add-btn"
                onClick={(e) => { e.stopPropagation(); onAddDish(dish) }}
              >
                <Text className="add-btn-text">+</Text>
              </View>
            </View>
          ))}

          <View className="list-bottom-spacer" />
        </ScrollView>
      </View>

      {/* Cart popup overlay */}
      {showCartPopup && (
        <View className="cart-popup-mask" onClick={() => setShowCartPopup(false)}>
          <View className="cart-popup" onClick={(e) => e.stopPropagation()}>
            <View className="popup-header">
              <Text className="popup-title">购物车</Text>
              <Text className="popup-close" onClick={() => setShowCartPopup(false)}>收起</Text>
            </View>
            <ScrollView scrollY className="popup-items">
              {cartItems.map((item, idx) => (
                <View key={`${item.dishId}-${idx}`} className="popup-item">
                  <Text className="popup-item-name">{item.name}</Text>
                  <Text className="popup-item-qty">x{item.quantity}</Text>
                  <Text className="popup-item-price">
                    ¥{fenToYuan(item.price_fen * item.quantity)}
                  </Text>
                </View>
              ))}
            </ScrollView>
          </View>
        </View>
      )}

      {/* Bottom cart bar */}
      <View className="cart-bar">
        <View className="cart-left" onClick={() => totalCount > 0 && setShowCartPopup(true)}>
          <View className="cart-icon-wrap">
            <Text className="cart-icon-text">🛒</Text>
            {totalCount > 0 && (
              <View className="cart-badge">
                <Text className="cart-badge-text">{totalCount > 99 ? '99+' : totalCount}</Text>
              </View>
            )}
          </View>
          <View className="cart-amount-info">
            {totalCount > 0 ? (
              <>
                <Text className="cart-total">¥{fenToYuan(totalFen)}</Text>
                {!reachedMin && (
                  <Text className="cart-remain">还差¥{fenToYuan(remainFen)}起送</Text>
                )}
              </>
            ) : (
              <Text className="cart-empty-text">购物车是空的</Text>
            )}
          </View>
        </View>
        <View
          className={`checkout-btn ${reachedMin && totalCount > 0 ? '' : 'disabled'}`}
          onClick={onGoCheckout}
        >
          <Text className="checkout-btn-text">
            {reachedMin ? '去结算' : `¥${fenToYuan(minDeliveryFen)}起送`}
          </Text>
        </View>
      </View>
    </View>
  )
}

export default TakeawayPage
