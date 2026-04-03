/**
 * order-detail/track/index.tsx — 实时订单追踪页
 *
 * URL params: ?orderId=xxx
 *
 * Features:
 *  - OrderProgress component showing 5 milestone steps
 *  - 5s polling via useOrderStore.startPolling()
 *  - Countdown timer "预计还需 X 分钟" with CSS conic-gradient arc
 *  - Green "已就绪" banner with pulse animation when status = ready
 *  - "呼叫服务员" button → POST /api/v1/service-bell
 *  - Auto-stop polling on delivered / cancelled
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, Order, OrderStatus } from '../../../api/trade'
import { useOrderStore } from '../../../store/useOrderStore'
import { txRequest } from '../../../utils/request'
import OrderProgress from '../../../components/OrderProgress'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B2C',
  primaryDim: 'rgba(255,107,44,0.15)',
  bgDeep:     '#0B1A20',
  bgCard:     '#132029',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  success:    '#4CAF50',
  successDim: 'rgba(76,175,80,0.15)',
  white:      '#fff',
  disabled:   '#2A4050',
} as const

// ─── Step definitions ─────────────────────────────────────────────────────────

interface ProgressStep {
  label: string
  time?: string
  done:  boolean
}

/**
 * Maps an OrderStatus to which milestone steps are done.
 * Steps: 已下单 → 已支付 → 制作中 → 待取餐 → 已完成
 */
function buildSteps(order: Order | null): ProgressStep[] {
  const status = (order?.status ?? 'pending_payment') as OrderStatus

  const createdAt  = order?.createdAt  ? fmtTime(order.createdAt)  : undefined
  const paidAt     = order?.paidAt     ? fmtTime(order.paidAt)     : undefined
  const updatedAt  = order?.updatedAt  ? fmtTime(order.updatedAt)  : undefined

  const ORDER: OrderStatus[] = [
    'pending_payment',
    'paid',
    'preparing',
    'ready',
    'completed',
  ]
  const idx = ORDER.indexOf(status)

  return [
    { label: '已下单', time: createdAt,  done: idx >= 0 },
    { label: '已支付', time: paidAt,     done: idx >= 1 },
    { label: '制作中', time: idx >= 2 ? updatedAt : undefined, done: idx >= 2 },
    { label: '待取餐', time: idx >= 3 ? updatedAt : undefined, done: idx >= 3 },
    { label: '已完成', time: idx >= 4 ? updatedAt : undefined, done: idx >= 4 },
  ]
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const h  = String(d.getHours()).padStart(2, '0')
  const m  = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

// ─── Estimated minutes from status ───────────────────────────────────────────

const ESTIMATED_MINUTES: Record<string, number> = {
  pending_payment: 20,
  paid:            18,
  preparing:       12,
  ready:            0,
  completed:        0,
  cancelled:        0,
}

// ─── Progress arc (conic-gradient timer ring) ─────────────────────────────────

interface ArcTimerProps {
  totalMinutes:   number
  elapsedMinutes: number
}

function ArcTimer({ totalMinutes, elapsedMinutes }: ArcTimerProps) {
  const remaining   = Math.max(0, totalMinutes - elapsedMinutes)
  const pct         = totalMinutes > 0 ? Math.min(100, (elapsedMinutes / totalMinutes) * 100) : 100
  const deg         = Math.round(pct * 360 / 100)

  const arcStyle: React.CSSProperties = {
    width:          '200rpx',
    height:         '200rpx',
    borderRadius:   '50%',
    background:     `conic-gradient(${C.primary} ${deg}deg, ${C.border} ${deg}deg)`,
    display:        'flex',
    alignItems:     'center',
    justifyContent: 'center',
    position:       'relative',
  }

  return (
    <View style={arcStyle}>
      {/* Inner circle */}
      <View
        style={{
          width:          '160rpx',
          height:         '160rpx',
          borderRadius:   '50%',
          background:     C.bgDeep,
          display:        'flex',
          flexDirection:  'column',
          alignItems:     'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.primary, fontSize: '40rpx', fontWeight: '700', lineHeight: '1' }}>
          {remaining}
        </Text>
        <Text style={{ color: C.text2, fontSize: '20rpx', marginTop: '4rpx' }}>分钟</Text>
      </View>
    </View>
  )
}

// ─── Countdown hook ───────────────────────────────────────────────────────────

function useElapsedMinutes(createdAt: string | undefined): number {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!createdAt) return

    const origin = new Date(createdAt).getTime()
    const tick = () => {
      const diff = Math.floor((Date.now() - origin) / 60_000)
      setElapsed(diff)
    }
    tick()
    const id = setInterval(tick, 15_000)
    return () => clearInterval(id)
  }, [createdAt])

  return elapsed
}

// ─── "Ready" banner with pulse ────────────────────────────────────────────────

function ReadyBanner() {
  const [pulse, setPulse] = useState(false)

  useEffect(() => {
    // Alternate pulse every 800ms
    const id = setInterval(() => setPulse((p) => !p), 800)
    return () => clearInterval(id)
  }, [])

  return (
    <View
      style={{
        background:     C.successDim,
        border:         `2rpx solid ${C.success}`,
        borderRadius:   '20rpx',
        padding:        '28rpx 32rpx',
        display:        'flex',
        flexDirection:  'row',
        alignItems:     'center',
        gap:            '16rpx',
        marginBottom:   '20rpx',
      }}
    >
      <Text
        style={{
          fontSize:  '48rpx',
          lineHeight: '1',
          transform: `scale(${pulse ? 1.25 : 1})`,
          transition: 'transform 0.3s ease',
        }}
      >
        🔔
      </Text>
      <View style={{ flex: 1 }}>
        <Text style={{ color: C.success, fontSize: '30rpx', fontWeight: '700', display: 'block' }}>
          您的餐品已就绪，请取餐！
        </Text>
        <Text style={{ color: C.text2, fontSize: '24rpx', marginTop: '4rpx', display: 'block' }}>
          请尽快前往取餐窗口领取
        </Text>
      </View>
    </View>
  )
}

// ─── Spinner ──────────────────────────────────────────────────────────────────

function Spinner() {
  const [angle, setAngle] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setAngle((a) => (a + 30) % 360), 80)
    return () => clearInterval(id)
  }, [])
  return (
    <View
      style={{
        width:        '48rpx',
        height:       '48rpx',
        borderRadius: '50%',
        border:       `4rpx solid ${C.border}`,
        borderTop:    `4rpx solid ${C.primary}`,
        transform:    `rotate(${angle}deg)`,
      }}
    />
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function OrderTrackPage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  const [order,         setOrder]         = useState<Order | null>(null)
  const [loading,       setLoading]       = useState(true)
  const [error,         setError]         = useState('')
  const [bellLoading,   setBellLoading]   = useState(false)
  const [bellCooldown,  setBellCooldown]  = useState(false)

  const { startPolling, stopPolling, isPolling } = useOrderStore()

  // ── Adapter: trade.Order → store.Order ────────────────────────────────────
  // useOrderStore works with its own Order shape; we manage local state directly
  // and only call startPolling with a fetch wrapper.

  const fetchOrder = useCallback(async (): Promise<Order | null> => {
    try {
      const data = await getOrder(orderId)
      setOrder(data)
      setError('')
      return data
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败'
      setError(msg)
      return null
    }
  }, [orderId])

  useEffect(() => {
    if (!orderId) return

    // Initial load
    setLoading(true)
    fetchOrder().finally(() => setLoading(false))

    // Start polling: wrap our trade.getOrder to match store's fetchFn signature
    const TERMINAL: OrderStatus[] = ['completed', 'cancelled', 'refunded']

    startPolling(orderId, async (id: string) => {
      try {
        const data = await getOrder(id)
        setOrder(data)
        // Stop polling on terminal statuses
        if (TERMINAL.includes(data.status)) {
          stopPolling()
        }
        // Return null so the store doesn't try to map fields (we handle state ourselves)
        return null
      } catch {
        return null
      }
    })

    return () => {
      stopPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId])

  // ── Call waiter ───────────────────────────────────────────────────────────

  async function handleCallBell() {
    if (bellLoading || bellCooldown || !orderId) return
    setBellLoading(true)
    try {
      await txRequest('/api/v1/service-bell', 'POST', { orderId })
      Taro.showToast({ title: '服务员已收到呼叫', icon: 'success', duration: 2000 })
      // 30s cooldown to prevent spam
      setBellCooldown(true)
      setTimeout(() => setBellCooldown(false), 30_000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '呼叫失败，请稍后再试'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setBellLoading(false)
    }
  }

  // ── Elapsed minutes (for timer arc) ───────────────────────────────────────

  const elapsedMinutes = useElapsedMinutes(order?.createdAt)
  const totalMinutes   = ESTIMATED_MINUTES[order?.status ?? 'pending_payment'] ?? 20

  // ── Steps ──────────────────────────────────────────────────────────────────

  const steps = buildSteps(order)

  // ── Terminal statuses ──────────────────────────────────────────────────────

  const isTerminal = order?.status === 'completed'
    || order?.status === 'cancelled'
    || order?.status === 'refunded'

  const isReady    = order?.status === 'ready'
  const showTimer  = order && !isTerminal && !isReady

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <View
        style={{
          minHeight:      '100vh',
          background:     C.bgDeep,
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          flexDirection:  'column',
          gap:            '24rpx',
        }}
      >
        <Spinner />
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>加载订单中...</Text>
      </View>
    )
  }

  if (error || !order) {
    return (
      <View
        style={{
          minHeight:      '100vh',
          background:     C.bgDeep,
          display:        'flex',
          flexDirection:  'column',
          alignItems:     'center',
          justifyContent: 'center',
          gap:            '24rpx',
          padding:        '48rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx' }}>😕</Text>
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
          {error || '订单不存在'}
        </Text>
        <View
          onClick={() => { setLoading(true); void fetchOrder().finally(() => setLoading(false)) }}
          style={{
            background:   C.primary,
            borderRadius: '40rpx',
            padding:      '16rpx 48rpx',
          }}
        >
          <Text style={{ color: C.white, fontSize: '28rpx' }}>重试</Text>
        </View>
      </View>
    )
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '24rpx 24rpx 200rpx' }}>

          {/* ── Header: polling indicator ──────────────────────────────────── */}
          <View
            style={{
              display:       'flex',
              flexDirection: 'row',
              alignItems:    'center',
              justifyContent: 'space-between',
              marginBottom:  '20rpx',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>
              实时进度
            </Text>
            {isPolling && !isTerminal && (
              <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
                <View
                  style={{
                    width:        '12rpx',
                    height:       '12rpx',
                    borderRadius: '50%',
                    background:   C.primary,
                    // Pulse via opacity alternation — handled by parent state
                  }}
                />
                <Text style={{ color: C.text2, fontSize: '22rpx' }}>实时更新</Text>
              </View>
            )}
          </View>

          {/* ── Ready banner ───────────────────────────────────────────────── */}
          {isReady && <ReadyBanner />}

          {/* ── Countdown arc ──────────────────────────────────────────────── */}
          {showTimer && (
            <View
              style={{
                background:     C.bgCard,
                borderRadius:   '20rpx',
                padding:        '32rpx',
                display:        'flex',
                flexDirection:  'column',
                alignItems:     'center',
                gap:            '16rpx',
                marginBottom:   '20rpx',
              }}
            >
              <ArcTimer totalMinutes={totalMinutes} elapsedMinutes={elapsedMinutes} />
              <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '8rpx' }}>
                预计还需 <Text style={{ color: C.primary, fontWeight: '700' }}>
                  {Math.max(0, totalMinutes - elapsedMinutes)}
                </Text> 分钟
              </Text>
            </View>
          )}

          {/* ── Order progress steps ────────────────────────────────────────── */}
          <View
            style={{
              background:   C.bgCard,
              borderRadius: '20rpx',
              marginBottom: '20rpx',
              overflow:     'hidden',
            }}
          >
            <View
              style={{
                padding:      '24rpx 32rpx 16rpx',
                borderBottom: `1rpx solid ${C.border}`,
              }}
            >
              <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700' }}>
                订单进度
              </Text>
            </View>
            <OrderProgress status={order.status} steps={steps} />
          </View>

          {/* ── Order number + store ─────────────────────────────────────────── */}
          <View
            style={{
              background:    C.bgCard,
              borderRadius:  '20rpx',
              padding:       '24rpx 32rpx',
              marginBottom:  '20rpx',
            }}
          >
            <View style={{ display: 'flex', flexDirection: 'row', marginBottom: '12rpx' }}>
              <Text style={{ color: C.text2, fontSize: '26rpx', width: '140rpx' }}>门店</Text>
              <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1 }}>{order.storeName}</Text>
            </View>
            <View style={{ display: 'flex', flexDirection: 'row' }}>
              <Text style={{ color: C.text2, fontSize: '26rpx', width: '140rpx' }}>取餐号</Text>
              <Text style={{ color: C.primary, fontSize: '32rpx', fontWeight: '700', flex: 1 }}>
                {order.orderNo.slice(-4).toUpperCase()}
              </Text>
            </View>
          </View>

        </View>
      </ScrollView>

      {/* ── Sticky bottom: call waiter ──────────────────────────────────────── */}
      {!isTerminal && (
        <View
          style={{
            position:      'fixed',
            bottom:        0,
            left:          0,
            right:         0,
            background:    C.bgCard,
            borderTop:     `1rpx solid ${C.border}`,
            padding:       '24rpx 32rpx',
            paddingBottom: 'env(safe-area-inset-bottom)',
          }}
        >
          <View
            onClick={handleCallBell}
            style={{
              height:         '88rpx',
              background:     bellCooldown ? C.disabled : (bellLoading ? C.disabled : C.primary),
              borderRadius:   '44rpx',
              display:        'flex',
              alignItems:     'center',
              justifyContent: 'center',
              gap:            '12rpx',
              opacity:        bellCooldown || bellLoading ? 0.7 : 1,
            }}
          >
            <Text style={{ fontSize: '36rpx', lineHeight: '1' }}>🔔</Text>
            <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '600' }}>
              {bellLoading
                ? '呼叫中...'
                : bellCooldown
                ? '已呼叫服务员（请稍候）'
                : '呼叫服务员'}
            </Text>
          </View>
        </View>
      )}

      {/* Terminal: navigate back */}
      {isTerminal && (
        <View
          style={{
            position:      'fixed',
            bottom:        0,
            left:          0,
            right:         0,
            background:    C.bgCard,
            borderTop:     `1rpx solid ${C.border}`,
            padding:       '24rpx 32rpx',
            paddingBottom: 'env(safe-area-inset-bottom)',
          }}
        >
          <View
            onClick={() => Taro.navigateBack({ delta: 1 })}
            style={{
              height:         '88rpx',
              background:     C.bgCard,
              border:         `2rpx solid ${C.border}`,
              borderRadius:   '44rpx',
              display:        'flex',
              alignItems:     'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>返回</Text>
          </View>
        </View>
      )}
    </View>
  )
}
