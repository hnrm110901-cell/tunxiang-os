/**
 * dish-detail/index.tsx — 菜品详情页
 *
 * 展示菜品详情、规格选择、数量控制、加入购物车
 * 来源：从菜单页/搜索页点击菜品进入
 *
 * Params:
 *   id — 菜品 ID
 *   store_id — 门店 ID（可选，用于拉取相关推荐）
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, Image, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useCartStore } from '../../store/useCartStore'
import { useStoreInfo } from '../../store/useStoreInfo'
import { txRequest } from '../../utils/request'
import './index.scss'

// ─── Brand tokens ────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  bgHover:     '#1A2E38',
  border:      '#1E3340',
  success:     '#34C759',
  danger:      '#FF3B30',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Types ──────────────────────────────────────────────────────────────────

interface DishSpec {
  key: string
  name: string
  price_fen: number
}

interface DishDetail {
  id: string
  name: string
  description: string
  image_url: string
  price_fen: number
  original_price_fen?: number
  category_id: string
  specs: DishSpec[]
  allergens: string[]
  ingredients: string[]
  sold_count: number
  likes: number
  is_available: boolean
}

interface RelatedDish {
  id: string
  name: string
  image_url: string
  price_fen: number
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  if (fen % 100 === 0) return String(fen / 100)
  return (fen / 100).toFixed(2)
}

// ─── Component ──────────────────────────────────────────────────────────────

const DishDetailPage: React.FC = () => {
  const router = useRouter()
  const addItem = useCartStore((s) => s.addItem)
  const storeInfo = useStoreInfo()

  const [dish, setDish] = useState<DishDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedSpec, setSelectedSpec] = useState('')
  const [selectedPriceFen, setSelectedPriceFen] = useState(0)
  const [qty, setQty] = useState(1)
  const [showAllergen, setShowAllergen] = useState(false)
  const [related, setRelated] = useState<RelatedDish[]>([])
  const [adding, setAdding] = useState(false)

  // ─── Load dish detail ──────────────────────────────────────────────────────

  const loadDish = useCallback(async (dishId: string) => {
    setLoading(true)
    try {
      const data = await txRequest<DishDetail>(`/api/v1/menu/dishes/${dishId}`)
      setDish(data)

      // Init spec
      if (data.specs && data.specs.length > 0) {
        setSelectedSpec(data.specs[0].key)
        setSelectedPriceFen(data.specs[0].price_fen)
      } else {
        setSelectedPriceFen(data.price_fen)
      }
    } catch (err) {
      Taro.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      setLoading(false)
    }
  }, [])

  // ─── Load related dishes ───────────────────────────────────────────────────

  const loadRelated = useCallback(async (categoryId: string, currentId: string) => {
    const storeId = router.params.store_id || storeInfo.storeId
    if (!storeId) return

    try {
      const data = await txRequest<{ items: RelatedDish[] }>(
        `/api/v1/menu/dishes?store_id=${storeId}&category_id=${categoryId}&size=7`,
      )
      setRelated((data.items || []).filter((d) => d.id !== currentId).slice(0, 6))
    } catch (_) {
      // non-critical
    }
  }, [router.params.store_id, storeInfo.storeId])

  useEffect(() => {
    const dishId = router.params.id || router.params.dish_id || ''
    if (!dishId) {
      Taro.showToast({ title: '菜品信息缺失', icon: 'none' })
      return
    }
    loadDish(dishId)
  }, [router.params.id, router.params.dish_id, loadDish])

  useEffect(() => {
    if (dish && dish.category_id) {
      loadRelated(dish.category_id, dish.id)
    }
  }, [dish, loadRelated])

  // ─── Actions ───────────────────────────────────────────────────────────────

  const currentPriceFen = selectedPriceFen || dish?.price_fen || 0
  const subtotalFen = currentPriceFen * qty
  const subtotalYuan = fenToYuan(subtotalFen)

  const onSelectSpec = (spec: DishSpec) => {
    setSelectedSpec(spec.key)
    setSelectedPriceFen(spec.price_fen)
  }

  const onDecrease = () => {
    if (qty > 1) setQty(qty - 1)
  }

  const onIncrease = () => {
    if (qty < 99) setQty(qty + 1)
  }

  const onAddToCart = () => {
    if (!dish || adding) return
    setAdding(true)

    const specName = dish.specs?.find((s) => s.key === selectedSpec)?.name
    addItem({
      dishId: dish.id,
      name: dish.name,
      price_fen: currentPriceFen,
      quantity: qty,
      specs: specName ? { spec: specName } : undefined,
    })

    Taro.showToast({ title: '已加入购物车', icon: 'success' })
    setTimeout(() => setAdding(false), 600)
  }

  const onGoRelated = (id: string) => {
    Taro.navigateTo({ url: `/subpages/dish-detail/index?id=${id}` })
  }

  const onShare = () => {
    // Taro will auto-handle share via useShareAppMessage
  }

  // ─── Share config ──────────────────────────────────────────────────────────

  Taro.useShareAppMessage(() => ({
    title: `${dish?.name || '菜品详情'} — ${dish?.description || ''}`,
    path: `/subpages/dish-detail/index?id=${dish?.id || ''}`,
  }))

  // ─── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <View className="dish-detail-page">
        <View className="skeleton-hero" />
        <View className="skeleton-info">
          <View className="skeleton-line w60" />
          <View className="skeleton-line w40" />
          <View className="skeleton-line w80" />
        </View>
      </View>
    )
  }

  if (!dish) {
    return (
      <View className="dish-detail-page">
        <View className="empty-state">
          <Text className="empty-text">菜品不存在或已下架</Text>
        </View>
      </View>
    )
  }

  return (
    <View className="dish-detail-page">
      <ScrollView scrollY className="scroll-content">
        {/* Hero Image */}
        <View className="hero-section">
          {dish.image_url ? (
            <Image className="hero-image" src={dish.image_url} mode="aspectFill" />
          ) : (
            <View className="hero-placeholder">
              <Text className="hero-placeholder-text">暂无图片</Text>
            </View>
          )}
          {!dish.is_available && (
            <View className="sold-out-badge">
              <Text className="sold-out-text">已售罄</Text>
            </View>
          )}
        </View>

        {/* Basic Info */}
        <View className="info-section">
          <Text className="dish-name">{dish.name}</Text>
          <View className="price-row">
            <Text className="price-symbol">¥</Text>
            <Text className="price-value">{fenToYuan(currentPriceFen)}</Text>
            {dish.original_price_fen && dish.original_price_fen > currentPriceFen && (
              <Text className="original-price">¥{fenToYuan(dish.original_price_fen)}</Text>
            )}
          </View>
          <View className="meta-row">
            <Text className="meta-item">已售 {dish.sold_count}</Text>
            <Text className="meta-dot">·</Text>
            <Text className="meta-item">{dish.likes} 人点赞</Text>
          </View>
          {dish.description && (
            <Text className="dish-desc">{dish.description}</Text>
          )}
        </View>

        {/* Specs */}
        {dish.specs && dish.specs.length > 0 && (
          <View className="specs-section">
            <Text className="section-title">规格</Text>
            <View className="specs-list">
              {dish.specs.map((spec) => (
                <View
                  key={spec.key}
                  className={`spec-tag ${selectedSpec === spec.key ? 'active' : ''}`}
                  onClick={() => onSelectSpec(spec)}
                >
                  <Text className="spec-name">{spec.name}</Text>
                  <Text className="spec-price">¥{fenToYuan(spec.price_fen)}</Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {/* Allergens */}
        {dish.allergens && dish.allergens.length > 0 && (
          <View className="allergen-section">
            <View className="allergen-header" onClick={() => setShowAllergen(!showAllergen)}>
              <Text className="section-title">过敏原信息</Text>
              <Text className="arrow-icon">{showAllergen ? '∧' : '∨'}</Text>
            </View>
            {showAllergen && (
              <View className="allergen-tags">
                {dish.allergens.map((a) => (
                  <View key={a} className="allergen-tag">
                    <Text className="allergen-text">{a}</Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}

        {/* Ingredients */}
        {dish.ingredients && dish.ingredients.length > 0 && (
          <View className="ingredients-section">
            <Text className="section-title">主要食材</Text>
            <Text className="ingredients-text">{dish.ingredients.join('、')}</Text>
          </View>
        )}

        {/* Related */}
        {related.length > 0 && (
          <View className="related-section">
            <Text className="section-title">相关推荐</Text>
            <ScrollView scrollX className="related-scroll">
              {related.map((r) => (
                <View key={r.id} className="related-card" onClick={() => onGoRelated(r.id)}>
                  {r.image_url ? (
                    <Image className="related-image" src={r.image_url} mode="aspectFill" />
                  ) : (
                    <View className="related-image-placeholder" />
                  )}
                  <Text className="related-name" numberOfLines={1}>{r.name}</Text>
                  <Text className="related-price">¥{fenToYuan(r.price_fen)}</Text>
                </View>
              ))}
            </ScrollView>
          </View>
        )}

        {/* Bottom spacer for fixed bar */}
        <View className="bottom-spacer" />
      </ScrollView>

      {/* Fixed Bottom Bar */}
      <View className="bottom-bar">
        <View className="qty-control">
          <View className="qty-btn" onClick={onDecrease}>
            <Text className="qty-btn-text">-</Text>
          </View>
          <Text className="qty-value">{qty}</Text>
          <View className="qty-btn" onClick={onIncrease}>
            <Text className="qty-btn-text">+</Text>
          </View>
        </View>
        <View
          className={`add-cart-btn ${!dish.is_available ? 'disabled' : ''} ${adding ? 'adding' : ''}`}
          onClick={onAddToCart}
        >
          <Text className="add-cart-text">
            {!dish.is_available ? '已售罄' : `加入购物车 ¥${subtotalYuan}`}
          </Text>
        </View>
      </View>
    </View>
  )
}

export default DishDetailPage
