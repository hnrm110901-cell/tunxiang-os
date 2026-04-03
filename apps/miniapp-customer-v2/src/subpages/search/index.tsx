/**
 * search/index.tsx — 搜索页
 *
 * Features:
 *  - Auto-focused search bar with clear + cancel
 *  - Hot searches (before typing)
 *  - Search history (Taro.getStorageSync, last 10)
 *  - Debounced real-time results: dish list / category hint / empty state
 *  - Recent views (horizontal scroll, no query)
 *  - On submit: call searchDishes → full results list
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Input, ScrollView } from '@tarojs/components'
import { searchDishes } from '../../api/menu'
import { useCartStore } from '../../store/useCartStore'
import { DishCard } from '../../components/DishCard'
import { fenToYuanDisplay } from '../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#fff',
} as const

// ─── Constants ────────────────────────────────────────────────────────────────
const HISTORY_KEY = 'tx_search_history'
const RECENT_VIEWS_KEY = 'tx_recent_views'
const MAX_HISTORY = 10
const MAX_RECENT = 10
const DEBOUNCE_MS = 300

const HOT_SEARCHES = [
  '招牌菜', '今日特价', '素食', '海鲜', '火锅',
  '新品', '推荐套餐', '小吃', '饮品', '儿童餐',
]

// ─── Types ────────────────────────────────────────────────────────────────────
interface SearchResult {
  dishes: any[]
  categories: Array<{ name: string; count: number }>
  total: number
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function getHistory(): string[] {
  try {
    return Taro.getStorageSync<string[]>(HISTORY_KEY) || []
  } catch {
    return []
  }
}

function saveHistory(keyword: string): void {
  try {
    const list = getHistory().filter((k) => k !== keyword)
    list.unshift(keyword)
    Taro.setStorageSync(HISTORY_KEY, list.slice(0, MAX_HISTORY))
  } catch {
    // ignore
  }
}

function clearHistory(): void {
  try {
    Taro.removeStorageSync(HISTORY_KEY)
  } catch {
    // ignore
  }
}

function getRecentViews(): any[] {
  try {
    return Taro.getStorageSync<any[]>(RECENT_VIEWS_KEY) || []
  } catch {
    return []
  }
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function TagChip({ label, onTap }: { label: string; onTap: () => void }) {
  return (
    <View
      onClick={onTap}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '10rpx 24rpx',
        background: C.bgCard,
        border: `1rpx solid ${C.border}`,
        borderRadius: '40rpx',
        marginRight: '16rpx',
        marginBottom: '16rpx',
        cursor: 'pointer',
      }}
    >
      <Text style={{ fontSize: '26rpx', color: C.text2 }}>{label}</Text>
    </View>
  )
}

function SectionHeader({
  title,
  action,
  onAction,
}: {
  title: string
  action?: string
  onAction?: () => void
}) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '20rpx',
      }}
    >
      <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1 }}>{title}</Text>
      {action && (
        <Text
          onClick={onAction}
          style={{ fontSize: '26rpx', color: C.text3, cursor: 'pointer' }}
        >
          {action}
        </Text>
      )}
    </View>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [history, setHistory] = useState<string[]>([])
  const [recentViews, setRecentViews] = useState<any[]>([])
  const [results, setResults] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const storeId = Taro.getStorageSync<string>('tx_store_id') || ''

  const { items: cartItems, addItem, removeItem } = useCartStore()

  // Load history + recent views on mount
  useEffect(() => {
    setHistory(getHistory())
    setRecentViews(getRecentViews())
  }, [])

  // Debounced search while typing
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)

    if (!query.trim() || submitted) {
      if (!submitted) setResults(null)
      return
    }

    debounceTimer.current = setTimeout(async () => {
      if (!query.trim()) return
      setLoading(true)
      try {
        const res = await searchDishes(storeId, query.trim())
        setResults(res as SearchResult)
      } catch {
        setResults({ dishes: [], categories: [], total: 0 })
      } finally {
        setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current)
    }
  }, [query, storeId, submitted])

  const handleSearch = useCallback(
    async (keyword: string) => {
      if (!keyword.trim()) return
      setQuery(keyword)
      setSubmitted(true)
      setLoading(true)
      saveHistory(keyword)
      setHistory(getHistory())
      try {
        const res = await searchDishes(storeId, keyword.trim())
        setResults(res as SearchResult)
      } catch {
        setResults({ dishes: [], categories: [], total: 0 })
      } finally {
        setLoading(false)
      }
    },
    [storeId],
  )

  const handleClear = () => {
    setQuery('')
    setResults(null)
    setSubmitted(false)
  }

  const handleCancel = () => {
    Taro.navigateBack()
  }

  const handleClearHistory = () => {
    clearHistory()
    setHistory([])
  }

  function cartQty(dishId: string): number {
    return cartItems.filter((i) => i.dishId === dishId).reduce((s, i) => s + i.quantity, 0)
  }

  const showEmpty = !loading && results && results.dishes.length === 0 && results.categories.length === 0
  const showDishes = results && results.dishes.length > 0
  const showCategories = results && results.categories.length > 0

  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* ── Search bar ── */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '24rpx 32rpx',
          paddingTop: 'calc(24rpx + env(safe-area-inset-top))',
          background: C.bgCard,
          borderBottom: `1rpx solid ${C.border}`,
          gap: '20rpx',
        }}
      >
        <View
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            background: C.bgHover,
            border: `1rpx solid ${C.border}`,
            borderRadius: '48rpx',
            padding: '0 24rpx',
            height: '72rpx',
            gap: '12rpx',
          }}
        >
          {/* Search icon */}
          <Text style={{ fontSize: '32rpx', color: C.text3 }}>🔍</Text>
          <Input
            value={query}
            placeholder="搜索菜品、分类..."
            placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
            focus
            style={{
              flex: 1,
              fontSize: '28rpx',
              color: C.text1,
              lineHeight: '72rpx',
            }}
            onInput={(e) => {
              setQuery(e.detail.value)
              setSubmitted(false)
            }}
            onConfirm={(e) => handleSearch(e.detail.value)}
          />
          {query.length > 0 && (
            <View
              onClick={handleClear}
              style={{
                width: '40rpx',
                height: '40rpx',
                borderRadius: '50%',
                background: C.text3,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
              }}
            >
              <Text style={{ fontSize: '24rpx', color: C.bgDeep, lineHeight: '40rpx', textAlign: 'center' }}>✕</Text>
            </View>
          )}
        </View>
        <Text
          onClick={handleCancel}
          style={{
            fontSize: '30rpx',
            color: C.text2,
            whiteSpace: 'nowrap',
            cursor: 'pointer',
          }}
        >
          取消
        </Text>
      </View>

      {/* ── Content area ── */}
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '32rpx' }}>

          {/* ── Loading indicator ── */}
          {loading && (
            <View style={{ textAlign: 'center', padding: '60rpx 0' }}>
              <Text style={{ color: C.text3, fontSize: '28rpx' }}>搜索中...</Text>
            </View>
          )}

          {/* ── No-query state: hot searches + history + recent views ── */}
          {!query && !loading && (
            <>
              {/* Hot searches */}
              <View style={{ marginBottom: '48rpx' }}>
                <SectionHeader title="热门搜索" />
                <View style={{ display: 'flex', flexWrap: 'wrap' }}>
                  {HOT_SEARCHES.map((tag) => (
                    <TagChip key={tag} label={tag} onTap={() => handleSearch(tag)} />
                  ))}
                </View>
              </View>

              {/* Search history */}
              {history.length > 0 && (
                <View style={{ marginBottom: '48rpx' }}>
                  <SectionHeader
                    title="搜索历史"
                    action="清除"
                    onAction={handleClearHistory}
                  />
                  <View style={{ display: 'flex', flexWrap: 'wrap' }}>
                    {history.map((kw) => (
                      <TagChip key={kw} label={kw} onTap={() => handleSearch(kw)} />
                    ))}
                  </View>
                </View>
              )}

              {/* Recent views */}
              {recentViews.length > 0 && (
                <View>
                  <SectionHeader title="最近浏览" />
                  <ScrollView
                    scrollX
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    <View style={{ display: 'inline-flex', gap: '20rpx', paddingBottom: '8rpx' }}>
                      {recentViews.map((dish) => (
                        <View
                          key={dish.dishId}
                          style={{
                            width: '280rpx',
                            display: 'inline-block',
                            verticalAlign: 'top',
                            background: C.bgCard,
                            borderRadius: '16rpx',
                            overflow: 'hidden',
                          }}
                        >
                          <DishCard
                            dish={{
                              id: dish.dishId,
                              name: dish.name,
                              price_fen: dish.basePriceFen,
                              image_url: dish.imageUrl,
                            }}
                            quantity={cartQty(dish.dishId)}
                            onAdd={() =>
                              addItem({ dishId: dish.dishId, name: dish.name, price_fen: dish.basePriceFen })
                            }
                            onRemove={() => removeItem(dish.dishId)}
                          />
                        </View>
                      ))}
                    </View>
                  </ScrollView>
                </View>
              )}
            </>
          )}

          {/* ── Results state ── */}
          {!loading && results && (
            <>
              {/* Dish results */}
              {showDishes && (
                <View style={{ marginBottom: '40rpx' }}>
                  <SectionHeader title={`菜品 (${results.dishes.length})`} />
                  {results.dishes.map((dish: any) => (
                    <DishCard
                      key={dish.dishId}
                      dish={{
                        id: dish.dishId,
                        name: dish.name,
                        price_fen: dish.basePriceFen,
                        image_url: dish.imageUrl,
                        tag: dish.tags?.[0],
                        sold_out: dish.status === 'sold_out',
                        description: dish.description,
                      }}
                      quantity={cartQty(dish.dishId)}
                      onAdd={() =>
                        addItem({ dishId: dish.dishId, name: dish.name, price_fen: dish.basePriceFen })
                      }
                      onRemove={() => removeItem(dish.dishId)}
                    />
                  ))}
                </View>
              )}

              {/* Category results */}
              {showCategories && (
                <View style={{ marginBottom: '40rpx' }}>
                  <SectionHeader title="相关分类" />
                  {results.categories.map((cat) => (
                    <View
                      key={cat.name}
                      style={{
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '28rpx 32rpx',
                        background: C.bgCard,
                        borderRadius: '16rpx',
                        marginBottom: '16rpx',
                        border: `1rpx solid ${C.border}`,
                      }}
                    >
                      <Text style={{ fontSize: '30rpx', color: C.text1 }}>
                        在「{cat.name}」分类下找到 {cat.count} 个菜品
                      </Text>
                      <Text style={{ fontSize: '28rpx', color: C.primary }}>查看 &gt;</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* Empty state */}
              {showEmpty && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    padding: '80rpx 0',
                    gap: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '64rpx' }}>🍽️</Text>
                  <Text style={{ fontSize: '32rpx', color: C.text1, fontWeight: '600' }}>
                    没有找到「{query}」
                  </Text>
                  <Text style={{ fontSize: '26rpx', color: C.text3 }}>
                    试试其他关键词，或从热门搜索中选择
                  </Text>
                  <View style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', marginTop: '16rpx' }}>
                    {HOT_SEARCHES.slice(0, 5).map((tag) => (
                      <TagChip key={tag} label={tag} onTap={() => handleSearch(tag)} />
                    ))}
                  </View>
                </View>
              )}
            </>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
