/**
 * pages/order/index.tsx — 订单列表
 *
 * Features:
 *   - Tab bar: 全部 / 待付款 / 进行中 / 已完成
 *   - Order cards with status colour + action buttons
 *   - Pull-down refresh (Taro onPullDownRefresh)
 *   - Infinite scroll (page=1,2,3…)
 *   - Empty state illustration
 *   - Loading skeleton
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Taro, { useDidShow, usePullDownRefresh, useReachBottom } from '@tarojs/taro'
import {
  View,
  Text,
  ScrollView,
} from '@tarojs/components'
import { listOrders } from '../../api/trade'
import { fenToYuanDisplay } from '../../utils/format'
import type { Order, OrderStatus } from '../../api/trade'

// ─── Constants ────────────────────────────────────────────────────────────────

const C = {
  bg:      '#0B1A20',
  card:    '#132029',
  primary: '#FF6B35',
  text1:   '#E8F4F8',
  text2:   '#9EB5C0',
  divider: 'rgba(255,255,255,0.06)',
}

type TabKey = 'all' | 'pending_payment' | 'in_progress' | 'completed'

const TABS: { key: TabKey; label: string; status?: OrderStatus | OrderStatus[] }[] = [
  { key: 'all',             label: '全部' },
  { key: 'pending_payment', label: '待付款',  status: 'pending_payment' },
  { key: 'in_progress',     label: '进行中',  status: ['paid', 'preparing', 'ready'] },
  { key: 'completed',       label: '已完成',  status: ['completed', 'cancelled', 'refunded'] },
]

const STATUS_META: Record<
  OrderStatus,
  { label: string; color: string; bg: string }
> = {
  pending_payment: { label: '待付款', color: '#FF6B35',  bg: 'rgba(255,107,53,0.12)' },
  paid:            { label: '已支付', color: '#5FA8E8',  bg: 'rgba(24,95,165,0.15)' },
  preparing:       { label: '备餐中', color: '#5FA8E8',  bg: 'rgba(24,95,165,0.15)' },
  ready:           { label: '待取餐', color: '#3DBE8A',  bg: 'rgba(15,110,86,0.15)' },
  completed:       { label: '已完成', color: '#3DBE8A',  bg: 'rgba(15,110,86,0.15)' },
  cancelled:       { label: '已取消', color: '#9EB5C0',  bg: 'rgba(158,181,192,0.1)' },
  refunded:        { label: '已退款', color: '#9EB5C0',  bg: 'rgba(158,181,192,0.1)' },
}

const PAGE_SIZE = 10

// ─── Helpers ──────────────────────────────────────────────────────────────────

function statusMeta(status: OrderStatus) {
  return STATUS_META[status] ?? { label: status, color: '#9EB5C0', bg: 'rgba(158,181,192,0.1)' }
}

function resolveTabStatus(tab: typeof TABS[0]): OrderStatus | undefined {
  // We pass a single status to the API; for in_progress we filter client-side
  if (!tab.status) return undefined
  if (Array.isArray(tab.status)) return tab.status[0]
  return tab.status
}

// ─── Skeleton card ────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <View
      style={{
        background: C.card,
        borderRadius: '20rpx',
        padding: '28rpx',
        marginBottom: '20rpx',
        display: 'flex',
        flexDirection: 'column',
        gap: '16rpx',
      }}
    >
      <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between' }}>
        <View style={{ width: '220rpx', height: '28rpx', background: C.bg, borderRadius: '8rpx' }} />
        <View style={{ width: '80rpx', height: '28rpx', background: C.bg, borderRadius: '8rpx' }} />
      </View>
      <View style={{ width: '100%', height: '1rpx', background: C.divider }} />
      <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
        {[1, 2, 3].map((i) => (
          <View key={i} style={{ width: '80rpx', height: '80rpx', background: C.bg, borderRadius: '12rpx' }} />
        ))}
      </View>
      <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginTop: '8rpx' }}>
        <View style={{ width: '140rpx', height: '28rpx', background: C.bg, borderRadius: '8rpx' }} />
        <View style={{ width: '120rpx', height: '64rpx', background: C.bg, borderRadius: '12rpx' }} />
      </View>
    </View>
  )
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState({ tab }: { tab: TabKey }) {
  const labels: Record<TabKey, string> = {
    all:             '暂无订单',
    pending_payment: '暂无待付款订单',
    in_progress:     '暂无进行中订单',
    completed:       '暂无历史订单',
  }
  return (
    <View
      style={{
        padding: '80rpx 32rpx',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '24rpx',
      }}
    >
      <Text style={{ fontSize: '100rpx', lineHeight: '1' }}>🧾</Text>
      <Text style={{ color: C.text2, fontSize: '30rpx' }}>{labels[tab]}</Text>
      <View
        style={{
          background: C.primary,
          borderRadius: '16rpx',
          padding: '16rpx 48rpx',
          marginTop: '8rpx',
        }}
        onClick={() => Taro.switchTab({ url: '/pages/menu/index' })}
      >
        <Text style={{ color: '#fff', fontSize: '28rpx', fontWeight: '600' }}>去点餐</Text>
      </View>
    </View>
  )
}

// ─── Order Card ───────────────────────────────────────────────────────────────

interface OrderCardProps {
  order: Order
  onReorder: (order: Order) => void
  onDelete: (orderId: string) => void
}

function OrderCard({ order, onReorder, onDelete }: OrderCardProps) {
  const meta = statusMeta(order.status)
  const previewItems = order.items.slice(0, 3)
  const extraCount = order.items.length - previewItems.length

  const goDetail = () =>
    Taro.navigateTo({
      url: `/subpackages/order-detail/detail/index?order_id=${order.orderId}`,
    }).catch(() => Taro.showToast({ title: '订单详情开发中', icon: 'none' }))

  const goProgress = () =>
    Taro.navigateTo({
      url: `/subpackages/order-detail/track/index?order_id=${order.orderId}`,
    }).catch(() => Taro.showToast({ title: '进度追踪开发中', icon: 'none' }))

  const goPay = () =>
    Taro.navigateTo({
      url: `/subpackages/order-flow/checkout/index?order_id=${order.orderId}`,
    }).catch(() => Taro.showToast({ title: '支付页开发中', icon: 'none' }))

  const confirmDelete = () => {
    Taro.showModal({
      title: '删除订单',
      content: '确定要删除这条订单记录吗？',
      confirmColor: '#FF6B35',
      success: ({ confirm }) => { if (confirm) onDelete(order.orderId) },
    })
  }

  return (
    <View
      style={{
        background: C.card,
        borderRadius: '20rpx',
        marginBottom: '20rpx',
        overflow: 'hidden',
      }}
      onClick={goDetail}
    >
      {/* Header */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '24rpx 28rpx 16rpx',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '24rpx' }}>
          订单 {order.orderNo}
          {order.tableNo ? `  · ${order.tableNo}号桌` : ''}
        </Text>
        <View
          style={{
            background: meta.bg,
            borderRadius: '10rpx',
            padding: '6rpx 16rpx',
          }}
        >
          <Text style={{ color: meta.color, fontSize: '24rpx', fontWeight: '600' }}>
            {meta.label}
          </Text>
        </View>
      </View>

      {/* Divider */}
      <View style={{ height: '1rpx', background: C.divider, margin: '0 28rpx' }} />

      {/* Items preview */}
      <View style={{ padding: '20rpx 28rpx', display: 'flex', flexDirection: 'column', gap: '10rpx' }}>
        {previewItems.map((item, idx) => (
          <View
            key={idx}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '10rpx', flex: 1 }}>
              <Text style={{ color: C.text2, fontSize: '24rpx' }}>·</Text>
              <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1 }} numberOfLines={1}>
                {item.dishName}
                {item.specName ? ` (${item.specName})` : ''}
              </Text>
              <Text style={{ color: C.text2, fontSize: '24rpx', marginLeft: '12rpx' }}>
                ×{item.quantity}
              </Text>
            </View>
            <Text style={{ color: C.text2, fontSize: '24rpx', marginLeft: '16rpx' }}>
              {fenToYuanDisplay(item.totalPriceFen)}
            </Text>
          </View>
        ))}
        {extraCount > 0 && (
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>…等 {order.items.length} 件菜品</Text>
        )}
      </View>

      {/* Divider */}
      <View style={{ height: '1rpx', background: C.divider, margin: '0 28rpx' }} />

      {/* Footer: total + actions */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '20rpx 28rpx',
        }}
      >
        <View>
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>合计 </Text>
          <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(order.payableFen)}
          </Text>
          {order.discountFen > 0 && (
            <Text style={{ color: '#3DBE8A', fontSize: '22rpx', marginLeft: '8rpx' }}>
              省{fenToYuanDisplay(order.discountFen)}
            </Text>
          )}
        </View>

        {/* Action buttons */}
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }} onClick={(e) => e.stopPropagation()}>
          {order.status === 'pending_payment' && (
            <View
              style={{
                background: C.primary,
                borderRadius: '12rpx',
                padding: '12rpx 28rpx',
                height: '64rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={goPay}
            >
              <Text style={{ color: '#fff', fontSize: '26rpx', fontWeight: '600' }}>去支付</Text>
            </View>
          )}
          {(order.status === 'preparing' || order.status === 'ready' || order.status === 'paid') && (
            <View
              style={{
                background: 'rgba(24,95,165,0.2)',
                borderRadius: '12rpx',
                padding: '12rpx 28rpx',
                height: '64rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={goProgress}
            >
              <Text style={{ color: '#5FA8E8', fontSize: '26rpx', fontWeight: '600' }}>查看进度</Text>
            </View>
          )}
          {order.status === 'completed' && (
            <View
              style={{
                background: 'rgba(255,107,53,0.12)',
                borderRadius: '12rpx',
                padding: '12rpx 28rpx',
                height: '64rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={() => onReorder(order)}
            >
              <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>再来一单</Text>
            </View>
          )}
          {order.status === 'cancelled' && (
            <View
              style={{
                background: 'rgba(158,181,192,0.12)',
                borderRadius: '12rpx',
                padding: '12rpx 28rpx',
                height: '64rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={confirmDelete}
            >
              <Text style={{ color: C.text2, fontSize: '26rpx' }}>删除</Text>
            </View>
          )}
        </View>
      </View>
    </View>
  )
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function OrderPage() {
  const [activeTab,  setActiveTab]  = useState<TabKey>('all')
  const [orders,     setOrders]     = useState<Order[]>([])
  const [loading,    setLoading]    = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [hasMore,    setHasMore]    = useState(true)
  const [page,       setPage]       = useState(1)
  const [error,      setError]      = useState<string | null>(null)

  const loadingRef = useRef(false)

  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchOrders = useCallback(
    async (p: number, reset: boolean) => {
      if (loadingRef.current) return
      loadingRef.current = true

      if (reset) {
        setLoading(true)
        setError(null)
      }

      try {
        const tab = TABS.find((t) => t.key === activeTab)!
        // For in_progress tab we pass the first status and filter client-side
        const statusParam = tab.status
          ? Array.isArray(tab.status) ? undefined : tab.status
          : undefined

        const result = await listOrders({ page: p, size: PAGE_SIZE, status: statusParam })
        let items = result.items

        // Client-side filter for multi-status tabs
        if (tab.key === 'in_progress') {
          items = items.filter((o) =>
            (['paid', 'preparing', 'ready'] as OrderStatus[]).includes(o.status),
          )
        } else if (tab.key === 'completed') {
          items = items.filter((o) =>
            (['completed', 'cancelled', 'refunded'] as OrderStatus[]).includes(o.status),
          )
        }

        setOrders((prev) => (reset ? items : [...prev, ...items]))
        setHasMore(result.page < result.totalPages)
        setPage(p)
      } catch (err) {
        console.error('[OrderPage] fetch error', err)
        setError('订单加载失败，请重试')
      } finally {
        loadingRef.current = false
        setLoading(false)
        setRefreshing(false)
        Taro.stopPullDownRefresh()
      }
    },
    [activeTab],
  )

  useEffect(() => {
    setOrders([])
    setPage(1)
    setHasMore(true)
    fetchOrders(1, true)
  }, [activeTab])

  // Refresh when tab becomes visible again (e.g. after paying)
  useDidShow(() => {
    setOrders([])
    setPage(1)
    setHasMore(true)
    fetchOrders(1, true)
  })

  // Pull-down refresh
  usePullDownRefresh(() => {
    setRefreshing(true)
    setOrders([])
    fetchOrders(1, true)
  })

  // Infinite scroll
  useReachBottom(() => {
    if (hasMore && !loadingRef.current) {
      fetchOrders(page + 1, false)
    }
  })

  // ── Reorder ────────────────────────────────────────────────────────────────
  const handleReorder = (order: Order) => {
    Taro.navigateTo({
      url: `/subpackages/order-flow/checkout/index?reorder_id=${order.orderId}`,
    }).catch(() => Taro.showToast({ title: '点餐页开发中', icon: 'none' }))
  }

  // ── Delete (local only — no real API delete in spec) ──────────────────────
  const handleDelete = (orderId: string) => {
    setOrders((prev) => prev.filter((o) => o.orderId !== orderId))
    Taro.showToast({ title: '已删除', icon: 'success', duration: 1200 })
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <View style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column' }}>

      {/* ─── Tab bar ─── */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          background: C.bg,
          borderBottom: `1rpx solid ${C.divider}`,
          flexShrink: 0,
        }}
      >
        {TABS.map((tab) => {
          const isActive = tab.key === activeTab
          return (
            <View
              key={tab.key}
              style={{
                flex: 1,
                height: '88rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderBottom: isActive ? `4rpx solid ${C.primary}` : '4rpx solid transparent',
                transition: 'border-color 0.2s',
              }}
              onClick={() => setActiveTab(tab.key)}
            >
              <Text
                style={{
                  color: isActive ? C.primary : C.text2,
                  fontSize: '28rpx',
                  fontWeight: isActive ? '600' : '400',
                }}
              >
                {tab.label}
              </Text>
            </View>
          )
        })}
      </View>

      {/* ─── List ─── */}
      <ScrollView
        scrollY
        style={{ flex: 1 }}
        enablePullDownRefresh={false}
      >
        <View style={{ padding: '24rpx 24rpx 60rpx' }}>
          {loading ? (
            [1, 2, 3].map((i) => <SkeletonCard key={i} />)
          ) : error ? (
            <View
              style={{
                margin: '32rpx 0',
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
                style={{ background: C.primary, borderRadius: '12rpx', padding: '12rpx 32rpx' }}
                onClick={() => {
                  setOrders([])
                  fetchOrders(1, true)
                }}
              >
                <Text style={{ color: '#fff', fontSize: '28rpx' }}>重新加载</Text>
              </View>
            </View>
          ) : orders.length === 0 ? (
            <EmptyState tab={activeTab} />
          ) : (
            <>
              {orders.map((order) => (
                <OrderCard
                  key={order.orderId}
                  order={order}
                  onReorder={handleReorder}
                  onDelete={handleDelete}
                />
              ))}
              {/* Load-more indicator */}
              <View style={{ textAlign: 'center', padding: '24rpx 0' }}>
                {hasMore ? (
                  <Text style={{ color: C.text2, fontSize: '26rpx' }}>上拉加载更多…</Text>
                ) : (
                  <Text style={{ color: C.text2, fontSize: '26rpx' }}>— 已显示全部订单 —</Text>
                )}
              </View>
            </>
          )}
        </View>
      </ScrollView>
    </View>
  )
}
