/**
 * pages/menu/index.tsx — 点餐页
 *
 * Layout:
 *   ┌─────────────────────────┐
 *   │  Search bar             │
 *   ├────────┬────────────────┤
 *   │ L-nav  │  Dish list     │
 *   │ 120rpx │  (ScrollView)  │
 *   │ cats   │  sticky headers│
 *   │        │  DishCard ×N   │
 *   ├────────┴────────────────┤
 *   │  CartBar (fixed)        │
 *   └─────────────────────────┘
 *
 * State:
 *   - loading: show skeleton rows
 *   - selectedCategory: drives left-nav highlight + right-scroll anchor
 *   - dishCustomizeVisible + selectedDish: bottom sheet for spec selection
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import {
  View,
  Text,
  ScrollView,
} from '@tarojs/components'
import { useCartStore } from '../../store/useCartStore'
import { useStoreInfo } from '../../store/useStoreInfo'
import { getCategories, getDishes } from '../../api/menu'
import { CartBar } from '../../components/CartBar'
import { DishCard } from '../../components/DishCard'
import { AiChatAssistant } from '../../components/AiChatAssistant'
import type { MenuCategory, Dish } from '../../api/menu'

// ─── Inline colours ───────────────────────────────────────────────────────────

const C = {
  bg:      '#0B1A20',
  card:    '#132029',
  nav:     '#0D2030',
  primary: '#FF6B35',
  text1:   '#E8F4F8',
  text2:   '#9EB5C0',
  divider: 'rgba(255,255,255,0.06)',
}

// ─── Skeleton row ─────────────────────────────────────────────────────────────

function SkeletonDishRow() {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '20rpx',
        marginBottom: '16rpx',
        background: C.card,
        borderRadius: '16rpx',
        gap: '20rpx',
      }}
    >
      <View style={{ width: '160rpx', height: '160rpx', borderRadius: '12rpx', background: C.bg, flexShrink: 0 }} />
      <View style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12rpx' }}>
        <View style={{ height: '32rpx', borderRadius: '8rpx', background: C.bg, width: '60%' }} />
        <View style={{ height: '24rpx', borderRadius: '8rpx', background: C.bg, width: '80%' }} />
        <View style={{ height: '28rpx', borderRadius: '8rpx', background: C.bg, width: '40%' }} />
      </View>
    </View>
  )
}

// ─── Category skeleton ────────────────────────────────────────────────────────

function SkeletonCat() {
  return (
    <View style={{ display: 'flex', flexDirection: 'column', gap: '8rpx', padding: '16rpx 8rpx' }}>
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <View
          key={i}
          style={{
            height: '64rpx',
            borderRadius: '12rpx',
            background: C.bg,
            marginBottom: '4rpx',
          }}
        />
      ))}
    </View>
  )
}

// ─── DishCustomize bottom-sheet ───────────────────────────────────────────────

interface DishCustomizeProps {
  dish: Dish | null
  visible: boolean
  onClose: () => void
  onConfirm: (dish: Dish, specSelections: Record<string, string>) => void
}

function DishCustomizeSheet({ dish, visible, onClose, onConfirm }: DishCustomizeProps) {
  const [selections, setSelections] = useState<Record<string, string>>({})

  useEffect(() => {
    if (dish) setSelections({})
  }, [dish])

  if (!visible || !dish) return null

  const canConfirm = !dish.specGroups?.some(
    (g) => g.required && !selections[g.groupId],
  )

  return (
    <>
      {/* Backdrop */}
      <View
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.6)',
          zIndex: 100,
        }}
        onClick={onClose}
      />
      {/* Sheet */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          background: '#1A2E3A',
          borderRadius: '32rpx 32rpx 0 0',
          zIndex: 101,
          padding: '32rpx 32rpx 60rpx',
          maxHeight: '70vh',
          overflow: 'auto',
        }}
      >
        {/* Handle */}
        <View
          style={{
            width: '80rpx',
            height: '8rpx',
            background: 'rgba(255,255,255,0.15)',
            borderRadius: '4rpx',
            margin: '0 auto 28rpx',
          }}
        />
        <Text style={{ color: C.text1, fontSize: '34rpx', fontWeight: '700', display: 'block', marginBottom: '24rpx' }}>
          {dish.name}
        </Text>

        {dish.specGroups && dish.specGroups.length > 0 ? (
          dish.specGroups.map((group) => (
            <View key={group.groupId} style={{ marginBottom: '28rpx' }}>
              <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '12rpx', marginBottom: '16rpx' }}>
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>{group.groupName}</Text>
                {group.required && (
                  <View
                    style={{
                      background: 'rgba(255,107,53,0.15)',
                      borderRadius: '8rpx',
                      padding: '2rpx 10rpx',
                    }}
                  >
                    <Text style={{ color: C.primary, fontSize: '20rpx' }}>必选</Text>
                  </View>
                )}
              </View>
              <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '12rpx' }}>
                {group.specs.map((spec) => {
                  const selected = selections[group.groupId] === spec.specId
                  return (
                    <View
                      key={spec.specId}
                      style={{
                        background: selected ? C.primary : C.bg,
                        borderRadius: '12rpx',
                        padding: '12rpx 24rpx',
                        border: selected ? 'none' : `2rpx solid ${C.divider}`,
                      }}
                      onClick={() =>
                        setSelections((prev) => ({ ...prev, [group.groupId]: spec.specId }))
                      }
                    >
                      <Text style={{ color: selected ? '#fff' : C.text2, fontSize: '26rpx' }}>
                        {spec.specName}
                        {spec.priceFen > 0
                          ? ` +¥${(spec.priceFen / 100).toFixed(0)}`
                          : ''}
                      </Text>
                    </View>
                  )
                })}
              </View>
            </View>
          ))
        ) : (
          <Text style={{ color: C.text2, fontSize: '26rpx', display: 'block', marginBottom: '24rpx' }}>
            该菜品无需选规格，直接加入购物车
          </Text>
        )}

        <View
          style={{
            background: canConfirm ? C.primary : '#3A4A50',
            borderRadius: '16rpx',
            height: '88rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginTop: '12rpx',
          }}
          onClick={() => canConfirm && onConfirm(dish, selections)}
        >
          <Text style={{ color: '#fff', fontSize: '30rpx', fontWeight: '600' }}>
            加入购物车
          </Text>
        </View>
      </View>
    </>
  )
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function MenuPage() {
  const storeId = useStoreInfo((s) => s.storeId)
  const { addItem, removeItem, items, totalFen, totalCount } = useCartStore()

  const [categories,        setCategories]        = useState<MenuCategory[]>([])
  const [dishes,            setDishes]            = useState<Dish[]>([])
  const [selectedCategory,  setSelectedCategory]  = useState<string>('')
  const [loading,           setLoading]           = useState(true)
  const [error,             setError]             = useState<string | null>(null)
  const [customizeVisible,  setCustomizeVisible]  = useState(false)
  const [selectedDish,      setSelectedDish]      = useState<Dish | null>(null)

  const rightScrollId = useRef<string>('')

  // ── Load ───────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!storeId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([getCategories(storeId), getDishes(storeId)])
      .then(([cats, ds]) => {
        if (cancelled) return
        const activeCats = cats
          .filter((c) => c.isActive)
          .sort((a, b) => a.sortOrder - b.sortOrder)
        setCategories(activeCats)
        setDishes(ds.filter((d) => d.isActive))
        if (activeCats.length > 0) setSelectedCategory(activeCats[0].categoryId)
      })
      .catch((err) => {
        if (cancelled) return
        console.error('[MenuPage] load error', err)
        setError('菜单加载失败，请重试')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [storeId])

  // ── Dishes for current category ────────────────────────────────────────────
  const filteredDishes = dishes.filter(
    (d) => !selectedCategory || d.categoryId === selectedCategory,
  )

  // ── Cart helpers ───────────────────────────────────────────────────────────
  const getQty = useCallback(
    (id: string) => items.find((i) => i.dishId === id)?.quantity ?? 0,
    [items],
  )

  const handleAddDish = useCallback(
    (dish: Dish) => {
      if (dish.hasSpecs && dish.specGroups && dish.specGroups.length > 0) {
        setSelectedDish(dish)
        setCustomizeVisible(true)
      } else {
        addItem({ dishId: dish.dishId, name: dish.name, price_fen: dish.basePriceFen })
      }
    },
    [addItem],
  )

  const handleRemoveDish = useCallback(
    (dish: Dish) => { removeItem(dish.dishId) },
    [removeItem],
  )

  const handleCustomizeConfirm = useCallback(
    (dish: Dish, specs: Record<string, string>) => {
      // Find spec price additions
      let extraFen = 0
      if (dish.specGroups) {
        for (const group of dish.specGroups) {
          const specId = specs[group.groupId]
          if (specId) {
            const spec = group.specs.find((s) => s.specId === specId)
            if (spec) extraFen += spec.priceFen
          }
        }
      }
      addItem(
        {
          dishId: dish.dishId,
          name: dish.name,
          price_fen: dish.basePriceFen + extraFen,
        },
        specs,
      )
      setCustomizeVisible(false)
      setSelectedDish(null)
    },
    [addItem],
  )

  // ── Category select → scroll anchor ───────────────────────────────────────
  const handleCategorySelect = (catId: string) => {
    setSelectedCategory(catId)
    rightScrollId.current = `cat-${catId}`
  }

  // ── Search nav ─────────────────────────────────────────────────────────────
  const handleSearchTap = () => {
    Taro.navigateTo({
      url: '/subpackages/order-flow/scan-order/index?mode=search',
    }).catch(() => Taro.showToast({ title: '搜索页开发中', icon: 'none' }))
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <View style={{ height: '100vh', background: C.bg, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ─── Search bar ─── */}
      <View
        style={{
          padding: '16rpx 32rpx',
          background: C.bg,
          flexShrink: 0,
        }}
        onClick={handleSearchTap}
      >
        <View
          style={{
            background: C.card,
            borderRadius: '48rpx',
            height: '72rpx',
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            padding: '0 28rpx',
            gap: '12rpx',
          }}
        >
          <Text style={{ fontSize: '28rpx', color: C.text2 }}>🔍</Text>
          <Text style={{ color: C.text2, fontSize: '28rpx' }}>搜索菜品…</Text>
        </View>
      </View>

      {/* ─── Main body: left nav + right list ─── */}
      <View style={{ flex: 1, display: 'flex', flexDirection: 'row', overflow: 'hidden', minHeight: 0 }}>

        {/* Left category nav */}
        <ScrollView
          scrollY
          style={{
            width: '120rpx',
            background: C.nav,
            flexShrink: 0,
            height: '100%',
          }}
        >
          {loading ? (
            <SkeletonCat />
          ) : (
            categories.map((cat) => {
              const isActive = cat.categoryId === selectedCategory
              return (
                <View
                  key={cat.categoryId}
                  style={{
                    padding: '24rpx 8rpx',
                    textAlign: 'center',
                    background: isActive ? C.bg : 'transparent',
                    borderLeft: isActive ? `4rpx solid ${C.primary}` : '4rpx solid transparent',
                    transition: 'all 0.2s',
                  }}
                  onClick={() => handleCategorySelect(cat.categoryId)}
                >
                  <Text
                    style={{
                      color: isActive ? C.primary : C.text2,
                      fontSize: '24rpx',
                      fontWeight: isActive ? '600' : '400',
                      lineHeight: '36rpx',
                    }}
                    numberOfLines={3}
                  >
                    {cat.name}
                  </Text>
                </View>
              )
            })
          )}
        </ScrollView>

        {/* Right dish list */}
        <ScrollView
          scrollY
          style={{ flex: 1, background: C.bg, height: '100%' }}
          scrollIntoView={rightScrollId.current}
          onScroll={() => { rightScrollId.current = '' }}
        >
          {loading ? (
            <View style={{ padding: '16rpx' }}>
              {[1, 2, 3, 4, 5].map((i) => <SkeletonDishRow key={i} />)}
            </View>
          ) : error ? (
            <View
              style={{
                margin: '32rpx',
                background: 'rgba(163,45,45,0.12)',
                borderRadius: '16rpx',
                padding: '28rpx',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '16rpx',
              }}
            >
              <Text style={{ fontSize: '48rpx' }}>😕</Text>
              <Text style={{ color: '#E8A0A0', fontSize: '28rpx' }}>{error}</Text>
              <View
                style={{
                  background: C.primary,
                  borderRadius: '12rpx',
                  padding: '12rpx 32rpx',
                  marginTop: '8rpx',
                }}
                onClick={() => {
                  setError(null)
                  setLoading(true)
                  // Re-trigger effect by faking a re-mount; simpler: duplicate load logic inline
                  if (storeId) {
                    Promise.all([getCategories(storeId), getDishes(storeId)])
                      .then(([cats, ds]) => {
                        const activeCats = cats.filter((c) => c.isActive).sort((a, b) => a.sortOrder - b.sortOrder)
                        setCategories(activeCats)
                        setDishes(ds.filter((d) => d.isActive))
                        if (activeCats.length > 0) setSelectedCategory(activeCats[0].categoryId)
                      })
                      .catch(() => setError('加载失败，请重试'))
                      .finally(() => setLoading(false))
                  }
                }}
              >
                <Text style={{ color: '#fff', fontSize: '28rpx' }}>重新加载</Text>
              </View>
            </View>
          ) : (
            <View style={{ padding: '0 16rpx 200rpx' }}>
              {categories.map((cat) => {
                const catDishes = dishes.filter((d) => d.categoryId === cat.categoryId)
                if (catDishes.length === 0) return null
                return (
                  <View key={cat.categoryId} id={`cat-${cat.categoryId}`}>
                    {/* Sticky category header */}
                    <View
                      style={{
                        position: 'sticky',
                        top: 0,
                        background: C.bg,
                        zIndex: 10,
                        padding: '20rpx 4rpx 12rpx',
                        borderBottom: `1rpx solid ${C.divider}`,
                        marginBottom: '12rpx',
                      }}
                    >
                      <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700' }}>
                        {cat.name}
                      </Text>
                    </View>

                    {catDishes.map((dish) => {
                      const cardDish = {
                        id:          dish.dishId,
                        name:        dish.name,
                        price_fen:   dish.basePriceFen,
                        image_url:   dish.imageUrl,
                        tag:         dish.tags?.[0],
                        description: dish.description,
                        sold_out:    dish.status === 'sold_out',
                      }
                      return (
                        <DishCard
                          key={dish.dishId}
                          dish={cardDish}
                          quantity={getQty(dish.dishId)}
                          onAdd={() => handleAddDish(dish)}
                          onRemove={() => handleRemoveDish(dish)}
                          onTap={() => {
                            if (dish.hasSpecs) {
                              setSelectedDish(dish)
                              setCustomizeVisible(true)
                            }
                          }}
                        />
                      )
                    })}
                  </View>
                )
              })}

              {categories.length === 0 && !loading && (
                <View
                  style={{
                    padding: '80rpx 32rpx',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '20rpx',
                  }}
                >
                  <Text style={{ fontSize: '80rpx' }}>🍽</Text>
                  <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无菜品</Text>
                </View>
              )}
            </View>
          )}
        </ScrollView>
      </View>

      {/* ─── DishCustomize sheet ─── */}
      <DishCustomizeSheet
        dish={selectedDish}
        visible={customizeVisible}
        onClose={() => { setCustomizeVisible(false); setSelectedDish(null) }}
        onConfirm={handleCustomizeConfirm}
      />

      {/* ─── AI 点餐助手 ─── */}
      <AiChatAssistant storeId={storeId} />

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
