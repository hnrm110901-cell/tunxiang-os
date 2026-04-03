/**
 * subpages/retail-mall/index.tsx — 零售商城
 *
 * Sections:
 *   1. Top search bar → retail search
 *   2. Category tabs: 全部 / 调味品 / 半成品食材 / 品牌周边 / 礼盒套装
 *   3. Delivery banner: 满99元包邮 · 顺丰冷链 · 3-5工作日
 *   4. Product grid (2-column)
 *   5. Product detail bottom sheet (half-screen)
 *   6. Retail cart bottom bar (separate from food cart)
 *
 * API: GET /api/v1/retail/products?category=&page=&size=20
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, ScrollView, Input } from '@tarojs/components'
import { fenToYuanDisplay } from '../../utils/format'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary:    '#FF6B2C',
  primaryDk:  '#E55A1F',
  primaryBg:  'rgba(255,107,44,0.12)',
  bgDeep:     '#0B1A20',
  bgCard:     '#132029',
  bgHover:    '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  red:        '#E53935',
  success:    '#4CAF50',
  warning:    '#FF9800',
  overlay:    'rgba(0,0,0,0.72)',
  white:      '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProductSpec {
  id: string
  name: string     // e.g. "500g" or "原味"
  price_delta_fen: number  // price delta vs base
}

interface SpecGroup {
  id: string
  name: string     // e.g. "规格" or "口味"
  specs: ProductSpec[]
}

interface RetailProduct {
  id: string
  name: string
  brand: string
  description: string
  image_url: string
  price_fen: number
  original_price_fen: number
  stock: number
  sold_out: boolean
  spec_groups: SpecGroup[]
  category: string
}

// Retail cart line item (separate from food cart)
interface RetailCartItem {
  productId: string
  name: string
  image_url: string
  price_fen: number
  quantity: number
  selectedSpecs: Record<string, string>   // groupId → specId
  specLabel: string                        // human-readable, e.g. "500g · 原味"
}

// ─── Constants ────────────────────────────────────────────────────────────────

const CATEGORIES = [
  { id: '',          label: '全部' },
  { id: 'seasoning', label: '调味品' },
  { id: 'semi',      label: '半成品食材' },
  { id: 'brand',     label: '品牌周边' },
  { id: 'gift',      label: '礼盒套装' },
]

const PAGE_SIZE = 20

// ─── Helpers ─────────────────────────────────────────────────────────────────

function cartKey(productId: string, specs: Record<string, string>): string {
  const sorted = Object.keys(specs).sort().map((k) => `${k}:${specs[k]}`).join('|')
  return sorted ? `${productId}__${sorted}` : productId
}

function specLabel(groups: SpecGroup[], selected: Record<string, string>): string {
  return groups
    .map((g) => {
      const spec = g.specs.find((s) => s.id === selected[g.id])
      return spec?.name ?? ''
    })
    .filter(Boolean)
    .join(' · ')
}

function effectivePrice(product: RetailProduct, selected: Record<string, string>): number {
  const delta = product.spec_groups.reduce((acc, g) => {
    const spec = g.specs.find((s) => s.id === selected[g.id])
    return acc + (spec?.price_delta_fen ?? 0)
  }, 0)
  return product.price_fen + delta
}

// ─── Sub-components ──────────────────────────────────────────────────────────

interface ProductCardProps {
  product: RetailProduct
  cartQty: number
  onTap: () => void
  onAddToCart: () => void
}

function ProductCard({ product, cartQty, onTap, onAddToCart }: ProductCardProps) {
  const lowStock = !product.sold_out && product.stock > 0 && product.stock < 10

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        overflow: 'hidden',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
      }}
      onClick={onTap}
    >
      {/* Product image */}
      <View style={{ position: 'relative', width: '100%', aspectRatio: '1' }}>
        <Image
          src={product.image_url || 'https://via.placeholder.com/300'}
          style={{ width: '100%', height: '100%', display: 'block' }}
          mode="aspectFill"
          lazyLoad
        />
        {/* Sold-out overlay */}
        {product.sold_out && (
          <View
            style={{
              position: 'absolute',
              inset: '0',
              background: 'rgba(0,0,0,0.6)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                background: 'rgba(255,255,255,0.15)',
                border: `2rpx solid rgba(255,255,255,0.3)`,
                borderRadius: '50rpx',
                padding: '10rpx 28rpx',
              }}
            >
              <Text style={{ color: C.white, fontSize: '26rpx', fontWeight: '600' }}>已售罄</Text>
            </View>
          </View>
        )}
        {/* Low-stock tag */}
        {lowStock && (
          <View
            style={{
              position: 'absolute',
              top: '12rpx',
              left: '12rpx',
              background: C.warning,
              borderRadius: '8rpx',
              padding: '4rpx 12rpx',
            }}
          >
            <Text style={{ color: C.white, fontSize: '20rpx', fontWeight: '600' }}>
              仅剩{product.stock}件
            </Text>
          </View>
        )}
        {/* Cart quantity badge */}
        {cartQty > 0 && (
          <View
            style={{
              position: 'absolute',
              top: '10rpx',
              right: '10rpx',
              background: C.primary,
              borderRadius: '50%',
              width: '40rpx',
              height: '40rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '700' }}>{cartQty}</Text>
          </View>
        )}
      </View>

      {/* Info */}
      <View style={{ padding: '16rpx 16rpx 12rpx', flex: 1, display: 'flex', flexDirection: 'column' }}>
        <Text
          style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600', lineHeight: '1.4', marginBottom: '8rpx' }}
          numberOfLines={2}
        >
          {product.name}
        </Text>
        <Text style={{ color: C.text3, fontSize: '22rpx', marginBottom: '12rpx' }}>{product.brand}</Text>

        {/* Price row */}
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: '10rpx', marginBottom: '16rpx' }}>
          <Text style={{ color: C.primary, fontSize: '30rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(product.price_fen)}
          </Text>
          {product.original_price_fen > product.price_fen && (
            <Text style={{ color: C.text3, fontSize: '22rpx', textDecoration: 'line-through' }}>
              {fenToYuanDisplay(product.original_price_fen)}
            </Text>
          )}
        </View>

        {/* Add to cart button */}
        <View
          style={{
            background: product.sold_out ? C.bgHover : C.primary,
            borderRadius: '12rpx',
            padding: '14rpx 0',
            textAlign: 'center',
            opacity: product.sold_out ? 0.5 : 1,
          }}
          onClick={(e) => {
            e.stopPropagation()
            if (!product.sold_out) onAddToCart()
          }}
        >
          <Text style={{ color: C.white, fontSize: '24rpx', fontWeight: '600' }}>
            {product.sold_out ? '已售罄' : '加入购物车'}
          </Text>
        </View>
      </View>
    </View>
  )
}

// ─── Detail Sheet ─────────────────────────────────────────────────────────────

interface DetailSheetProps {
  product: RetailProduct | null
  visible: boolean
  onClose: () => void
  onAddToCart: (item: RetailCartItem) => void
}

function DetailSheet({ product, visible, onClose, onAddToCart }: DetailSheetProps) {
  const [selectedSpecs, setSelectedSpecs] = useState<Record<string, string>>({})
  const [qty, setQty] = useState(1)

  // Reset when product changes
  useEffect(() => {
    if (product) {
      const defaultSpecs: Record<string, string> = {}
      product.spec_groups.forEach((g) => {
        if (g.specs.length > 0) defaultSpecs[g.id] = g.specs[0].id
      })
      setSelectedSpecs(defaultSpecs)
      setQty(1)
    }
  }, [product?.id])

  if (!visible || !product) return null

  const price = effectivePrice(product, selectedSpecs)
  const label = specLabel(product.spec_groups, selectedSpecs)

  function handleAdd() {
    onAddToCart({
      productId: product!.id,
      name: product!.name,
      image_url: product!.image_url,
      price_fen: price,
      quantity: qty,
      selectedSpecs,
      specLabel: label,
    })
    onClose()
  }

  return (
    <>
      {/* Mask */}
      <View
        style={{ position: 'fixed', inset: '0', background: C.overlay, zIndex: 99 }}
        onClick={onClose}
      />
      {/* Sheet */}
      <View
        style={{
          position: 'fixed',
          left: '0',
          right: '0',
          bottom: '0',
          background: C.bgCard,
          borderRadius: '32rpx 32rpx 0 0',
          zIndex: 100,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Handle */}
        <View style={{ display: 'flex', justifyContent: 'center', padding: '16rpx 0 8rpx' }}>
          <View style={{ width: '80rpx', height: '8rpx', background: C.text3, borderRadius: '4rpx' }} />
        </View>

        <ScrollView scrollY style={{ flex: 1, padding: '0 32rpx' }}>
          {/* Hero image */}
          <Image
            src={product.image_url || 'https://via.placeholder.com/600'}
            style={{ width: '100%', borderRadius: '20rpx', aspectRatio: '1', marginBottom: '24rpx' }}
            mode="aspectFill"
            lazyLoad
          />

          {/* Name + brand */}
          <Text style={{ color: C.text1, fontSize: '34rpx', fontWeight: '700', display: 'block', marginBottom: '8rpx' }}>
            {product.name}
          </Text>
          <Text style={{ color: C.text3, fontSize: '26rpx', display: 'block', marginBottom: '16rpx' }}>
            {product.brand}
          </Text>

          {/* Description */}
          {product.description && (
            <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.6', display: 'block', marginBottom: '28rpx' }}>
              {product.description}
            </Text>
          )}

          {/* Spec selectors */}
          {product.spec_groups.map((group) => (
            <View key={group.id} style={{ marginBottom: '28rpx' }}>
              <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600', display: 'block', marginBottom: '16rpx' }}>
                {group.name}
              </Text>
              <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '16rpx' }}>
                {group.specs.map((spec) => {
                  const isSelected = selectedSpecs[group.id] === spec.id
                  return (
                    <View
                      key={spec.id}
                      style={{
                        padding: '12rpx 28rpx',
                        borderRadius: '50rpx',
                        border: `2rpx solid ${isSelected ? C.primary : C.border}`,
                        background: isSelected ? C.primaryBg : 'transparent',
                      }}
                      onClick={() => setSelectedSpecs((prev) => ({ ...prev, [group.id]: spec.id }))}
                    >
                      <Text style={{ color: isSelected ? C.primary : C.text2, fontSize: '26rpx', fontWeight: isSelected ? '600' : '400' }}>
                        {spec.name}
                        {spec.price_delta_fen !== 0 && (
                          <Text style={{ fontSize: '22rpx' }}>
                            {spec.price_delta_fen > 0 ? ` +¥${(spec.price_delta_fen / 100).toFixed(2)}` : ` -¥${(-spec.price_delta_fen / 100).toFixed(2)}`}
                          </Text>
                        )}
                      </Text>
                    </View>
                  )
                })}
              </View>
            </View>
          ))}

          {/* Quantity stepper */}
          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: '32rpx' }}>
            <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>数量</Text>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '0' }}>
              <View
                style={{
                  width: '64rpx', height: '64rpx',
                  background: C.bgHover, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  opacity: qty <= 1 ? 0.4 : 1,
                }}
                onClick={() => setQty((q) => Math.max(1, q - 1))}
              >
                <Text style={{ color: C.text1, fontSize: '36rpx', lineHeight: '1' }}>−</Text>
              </View>
              <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', width: '72rpx', textAlign: 'center' }}>{qty}</Text>
              <View
                style={{
                  width: '64rpx', height: '64rpx',
                  background: C.primary, borderRadius: '50%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
                onClick={() => setQty((q) => q + 1)}
              >
                <Text style={{ color: C.white, fontSize: '36rpx', lineHeight: '1' }}>+</Text>
              </View>
            </View>
          </View>

          {/* Bottom safe area */}
          <View style={{ height: '160rpx' }} />
        </ScrollView>

        {/* Sticky CTA */}
        <View
          style={{
            padding: '24rpx 32rpx',
            paddingBottom: 'env(safe-area-inset-bottom, 24rpx)',
            background: C.bgCard,
            borderTop: `1rpx solid ${C.border}`,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '24rpx',
          }}
        >
          <View>
            <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
              {fenToYuanDisplay(price * qty)}
            </Text>
          </View>
          <View
            style={{
              flex: 1,
              background: product.sold_out ? C.bgHover : C.primary,
              borderRadius: '50rpx',
              padding: '24rpx 0',
              textAlign: 'center',
              opacity: product.sold_out ? 0.5 : 1,
            }}
            onClick={!product.sold_out ? handleAdd : undefined}
          >
            <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>
              {product.sold_out ? '已售罄' : '加入购物车'}
            </Text>
          </View>
        </View>
      </View>
    </>
  )
}

// ─── Retail Cart Bar ──────────────────────────────────────────────────────────

interface RetailCartBarProps {
  items: RetailCartItem[]
  onCheckout: () => void
}

function RetailCartBar({ items, onCheckout }: RetailCartBarProps) {
  const totalCount = items.reduce((acc, i) => acc + i.quantity, 0)
  const totalFen = items.reduce((acc, i) => acc + i.price_fen * i.quantity, 0)

  if (totalCount === 0) return null

  return (
    <View
      style={{
        position: 'fixed',
        left: '0',
        right: '0',
        bottom: '0',
        background: C.bgCard,
        borderTop: `1rpx solid ${C.border}`,
        padding: '20rpx 32rpx',
        paddingBottom: 'env(safe-area-inset-bottom, 20rpx)',
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        zIndex: 50,
      }}
    >
      {/* Cart icon + badge */}
      <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '16rpx' }}>
        <View style={{ position: 'relative' }}>
          <Text style={{ fontSize: '52rpx' }}>🛒</Text>
          <View
            style={{
              position: 'absolute',
              top: '-8rpx',
              right: '-8rpx',
              background: C.primary,
              borderRadius: '50%',
              minWidth: '36rpx',
              height: '36rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 6rpx',
            }}
          >
            <Text style={{ color: C.white, fontSize: '20rpx', fontWeight: '700' }}>{totalCount}</Text>
          </View>
        </View>
        <View>
          <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(totalFen)}
          </Text>
        </View>
      </View>

      {/* Checkout CTA */}
      <View
        style={{
          background: C.primary,
          borderRadius: '50rpx',
          padding: '20rpx 48rpx',
        }}
        onClick={onCheckout}
      >
        <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>去结算</Text>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function RetailMallPage() {
  const [activeCategory, setActiveCategory] = useState('')
  const [products, setProducts] = useState<RetailProduct[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [detailProduct, setDetailProduct] = useState<RetailProduct | null>(null)
  const [sheetVisible, setSheetVisible] = useState(false)
  const [cartItems, setCartItems] = useState<RetailCartItem[]>([])
  const loadingRef = useRef(false)

  const fetchProducts = useCallback(async (cat: string, pg: number, reset: boolean) => {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    try {
      const res = await txRequest<{ items: RetailProduct[]; total: number }>(
        `/api/v1/retail/products?category=${cat}&page=${pg}&size=${PAGE_SIZE}`,
      )
      const items = res?.items ?? []
      setProducts((prev) => (reset ? items : [...prev, ...items]))
      setHasMore(items.length === PAGE_SIZE)
      setPage(pg)
    } catch {
      Taro.showToast({ title: '加载失败，请重试', icon: 'none' })
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [])

  useEffect(() => {
    fetchProducts(activeCategory, 1, true)
  }, [activeCategory, fetchProducts])

  function handleCategoryChange(id: string) {
    if (id === activeCategory) return
    setActiveCategory(id)
    setHasMore(true)
  }

  function handleLoadMore() {
    if (!loading && hasMore) {
      fetchProducts(activeCategory, page + 1, false)
    }
  }

  function handleProductTap(product: RetailProduct) {
    setDetailProduct(product)
    setSheetVisible(true)
  }

  // Direct "add to cart" from card (shows sheet only if product has specs)
  function handleCardAddToCart(product: RetailProduct) {
    if (product.sold_out) return
    if (product.spec_groups.length > 0) {
      setDetailProduct(product)
      setSheetVisible(true)
    } else {
      addToCart({
        productId: product.id,
        name: product.name,
        image_url: product.image_url,
        price_fen: product.price_fen,
        quantity: 1,
        selectedSpecs: {},
        specLabel: '',
      })
    }
  }

  function addToCart(incoming: RetailCartItem) {
    setCartItems((prev) => {
      const key = cartKey(incoming.productId, incoming.selectedSpecs)
      const existing = prev.find(
        (i) => cartKey(i.productId, i.selectedSpecs) === key,
      )
      if (existing) {
        return prev.map((i) =>
          cartKey(i.productId, i.selectedSpecs) === key
            ? { ...i, quantity: i.quantity + incoming.quantity }
            : i,
        )
      }
      return [...prev, incoming]
    })
    Taro.showToast({ title: '已加入购物车', icon: 'success', duration: 1000 })
  }

  function handleRetailCheckout() {
    Taro.showToast({ title: '零售结算功能即将上线', icon: 'none', duration: 2000 })
  }

  function getCartQty(productId: string): number {
    return cartItems
      .filter((i) => i.productId === productId)
      .reduce((acc, i) => acc + i.quantity, 0)
  }

  const hasCart = cartItems.reduce((acc, i) => acc + i.quantity, 0) > 0

  return (
    <View style={{ background: C.bgDeep, minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* ─── Top bar: search ─── */}
      <View
        style={{
          background: C.bgCard,
          padding: '16rpx 32rpx 20rpx',
          paddingTop: 'calc(env(safe-area-inset-top, 0px) + 16rpx)',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '16rpx',
        }}
      >
        <View
          style={{
            flex: 1,
            background: C.bgHover,
            borderRadius: '50rpx',
            padding: '18rpx 28rpx',
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '12rpx',
          }}
          onClick={() => Taro.navigateTo({ url: '/subpages/search/index?scope=retail' })}
        >
          <Text style={{ fontSize: '30rpx' }}>🔍</Text>
          <Text style={{ color: C.text3, fontSize: '28rpx' }}>搜索商品</Text>
        </View>
      </View>

      {/* ─── Category tabs ─── */}
      <View style={{ background: C.bgCard, borderBottom: `1rpx solid ${C.border}` }}>
        <ScrollView scrollX style={{ whiteSpace: 'nowrap', padding: '0 16rpx' }}>
          {CATEGORIES.map((cat) => {
            const active = cat.id === activeCategory
            return (
              <View
                key={cat.id}
                style={{
                  display: 'inline-flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  padding: '20rpx 28rpx 16rpx',
                  position: 'relative',
                }}
                onClick={() => handleCategoryChange(cat.id)}
              >
                <Text
                  style={{
                    color: active ? C.primary : C.text2,
                    fontSize: '28rpx',
                    fontWeight: active ? '700' : '400',
                  }}
                >
                  {cat.label}
                </Text>
                {active && (
                  <View
                    style={{
                      position: 'absolute',
                      bottom: '0',
                      left: '50%',
                      transform: 'translateX(-50%)',
                      width: '40rpx',
                      height: '6rpx',
                      background: C.primary,
                      borderRadius: '3rpx',
                    }}
                  />
                )}
              </View>
            )
          })}
        </ScrollView>
      </View>

      {/* ─── Delivery banner ─── */}
      <View
        style={{
          background: 'rgba(255,107,44,0.08)',
          borderBottom: `1rpx solid rgba(255,107,44,0.15)`,
          padding: '18rpx 32rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '12rpx',
        }}
      >
        <Text style={{ fontSize: '26rpx' }}>🚚</Text>
        <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '500' }}>
          满99元包邮 · 顺丰冷链配送 · 3-5个工作日
        </Text>
      </View>

      {/* ─── Product grid ─── */}
      <ScrollView
        scrollY
        style={{ flex: 1 }}
        onScrollToLower={handleLoadMore}
        lowerThreshold={200}
      >
        {loading && products.length === 0 ? (
          /* Skeleton grid */
          <View
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '20rpx',
              padding: '24rpx 24rpx',
            }}
          >
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <View
                key={i}
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  aspectRatio: '0.75',
                  opacity: 0.5,
                }}
              />
            ))}
          </View>
        ) : products.length === 0 ? (
          <View
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '120rpx 32rpx',
              gap: '24rpx',
            }}
          >
            <Text style={{ fontSize: '80rpx' }}>📦</Text>
            <Text style={{ color: C.text2, fontSize: '30rpx' }}>该分类暂无商品</Text>
          </View>
        ) : (
          <View
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '20rpx',
              padding: '24rpx 24rpx',
            }}
          >
            {products.map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                cartQty={getCartQty(product.id)}
                onTap={() => handleProductTap(product)}
                onAddToCart={() => handleCardAddToCart(product)}
              />
            ))}
          </View>
        )}

        {/* Loading more indicator */}
        {loading && products.length > 0 && (
          <View style={{ padding: '24rpx', textAlign: 'center' }}>
            <Text style={{ color: C.text3, fontSize: '24rpx' }}>加载中...</Text>
          </View>
        )}

        {!hasMore && products.length > 0 && (
          <View style={{ padding: '32rpx', textAlign: 'center' }}>
            <Text style={{ color: C.text3, fontSize: '24rpx' }}>— 已加载全部商品 —</Text>
          </View>
        )}

        {/* Bottom padding above cart bar */}
        <View style={{ height: hasCart ? '160rpx' : '40rpx' }} />
      </ScrollView>

      {/* ─── Detail sheet ─── */}
      <DetailSheet
        product={detailProduct}
        visible={sheetVisible}
        onClose={() => setSheetVisible(false)}
        onAddToCart={addToCart}
      />

      {/* ─── Retail cart bar ─── */}
      <RetailCartBar items={cartItems} onCheckout={handleRetailCheckout} />
    </View>
  )
}
