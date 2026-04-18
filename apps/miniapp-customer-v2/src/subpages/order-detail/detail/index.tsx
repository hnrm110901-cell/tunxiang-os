/**
 * order-detail/detail/index.tsx — 订单详情页
 *
 * URL params: ?orderId=xxx
 *
 * Sections:
 *  1. 状态卡   — large emoji icon + status text + estimated time (preparing)
 *  2. 门店信息  — store name / address / call button
 *  3. 菜品明细  — items list
 *  4. 价格明细  — subtotal / coupon / points / payable
 *  5. 订单信息  — order number (copy) / created time / dine mode / remark
 *  6. 操作按钮区 — context-sensitive actions
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, cancelOrder, Order, OrderStatus } from '../../../api/trade'
import { useCartStore } from '../../../store/useCartStore'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B35',
  primaryDim:  'rgba(255,107,53,0.15)',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  border:      '#1E3040',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  red:         '#E53935',
  redDim:      'rgba(229,57,53,0.15)',
  success:     '#4CAF50',
  successDim:  'rgba(76,175,80,0.15)',
  warning:     '#FFC107',
  warningDim:  'rgba(255,193,7,0.15)',
  white:       '#fff',
  disabled:    '#2A4050',
} as const

// ─── Status display config ────────────────────────────────────────────────────

interface StatusConfig {
  emoji:    string
  label:    string
  color:    string
  bgColor:  string
  showTime: boolean
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  pending_payment: {
    emoji:    '⏳',
    label:    '待支付',
    color:    C.warning,
    bgColor:  C.warningDim,
    showTime: false,
  },
  paid: {
    emoji:    '✅',
    label:    '已支付，等待备餐',
    color:    C.success,
    bgColor:  C.successDim,
    showTime: false,
  },
  preparing: {
    emoji:    '👨‍🍳',
    label:    '备餐中',
    color:    C.primary,
    bgColor:  C.primaryDim,
    showTime: true,
  },
  ready: {
    emoji:    '🔔',
    label:    '餐品已就绪',
    color:    C.success,
    bgColor:  C.successDim,
    showTime: false,
  },
  completed: {
    emoji:    '🎉',
    label:    '已完成',
    color:    C.text2,
    bgColor:  'rgba(158,181,192,0.1)',
    showTime: false,
  },
  cancelled: {
    emoji:    '❌',
    label:    '已取消',
    color:    C.red,
    bgColor:  C.redDim,
    showTime: false,
  },
  refunded: {
    emoji:    '↩️',
    label:    '已退款',
    color:    C.text2,
    bgColor:  'rgba(158,181,192,0.1)',
    showTime: false,
  },
}

const DINE_MODE_LABELS: Record<string, string> = {
  'dine-in':     '堂食',
  takeaway:      '外带',
  reservation:   '预约',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDateTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionCard({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        marginBottom: '20rpx',
        overflow: 'hidden',
        ...style,
      }}
    >
      {children}
    </View>
  )
}

function SectionTitle({ title }: { title: string }) {
  return (
    <View
      style={{
        padding: '24rpx 32rpx 16rpx',
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700' }}>{title}</Text>
    </View>
  )
}

function InfoRow({
  label,
  value,
  valueColor,
  valueBold,
  onAction,
  actionLabel,
}: {
  label:       string
  value:       string
  valueColor?: string
  valueBold?:  boolean
  onAction?:   () => void
  actionLabel?: string
}) {
  return (
    <View
      style={{
        display:         'flex',
        flexDirection:   'row',
        alignItems:      'center',
        padding:         '20rpx 32rpx',
        borderBottom:    `1rpx solid ${C.border}`,
      }}
    >
      <Text style={{ color: C.text2, fontSize: '26rpx', width: '160rpx', flexShrink: 0 }}>
        {label}
      </Text>
      <Text
        style={{
          color:      valueColor ?? C.text1,
          fontSize:   '26rpx',
          fontWeight: valueBold ? '600' : '400',
          flex:       1,
        }}
      >
        {value}
      </Text>
      {onAction && actionLabel && (
        <View
          onClick={onAction}
          style={{
            background:   C.primaryDim,
            borderRadius: '24rpx',
            padding:      '6rpx 20rpx',
            marginLeft:   '16rpx',
          }}
        >
          <Text style={{ color: C.primary, fontSize: '22rpx' }}>{actionLabel}</Text>
        </View>
      )}
    </View>
  )
}

// ─── Skeleton loader ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <View style={{ padding: '32rpx', display: 'flex', flexDirection: 'column', gap: '20rpx' }}>
      {[200, 120, 160, 100].map((w, i) => (
        <View
          key={i}
          style={{
            height:       '32rpx',
            width:        `${w}rpx`,
            background:   C.bgCard,
            borderRadius: '8rpx',
            opacity:      0.6,
          }}
        />
      ))}
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function OrderDetailPage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  const [order,   setOrder]   = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [reordering, setReordering] = useState(false)

  const addItem = useCartStore((s) => s.addItem)
  const setStoreId = useCartStore((s) => s.setStoreId)

  // ── Data fetch ──────────────────────────────────────────────────────────────

  const fetchOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setError('')
    try {
      const data = await getOrder(orderId)
      setOrder(data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    void fetchOrder()
  }, [fetchOrder])

  // ── Actions ─────────────────────────────────────────────────────────────────

  async function handleCancel() {
    if (!order) return
    const res = await Taro.showModal({ title: '确认取消', content: '确定要取消这笔订单吗？' })
    if (!res.confirm) return
    setCancelling(true)
    try {
      await cancelOrder(order.orderId)
      await fetchOrder()
      Taro.showToast({ title: '订单已取消', icon: 'success' })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '取消失败'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setCancelling(false)
    }
  }

  function handlePay() {
    if (!order) return
    Taro.navigateTo({ url: `/subpages/order-flow/checkout/index?orderId=${order.orderId}` })
  }

  function handleTrack() {
    if (!order) return
    Taro.navigateTo({ url: `/subpages/order-detail/track/index?orderId=${order.orderId}` })
  }

  async function handleReorder() {
    if (!order || reordering) return
    setReordering(true)
    try {
      // Populate cart from this order's items
      setStoreId(order.storeId)
      for (const item of order.items) {
        const specs = item.specName ? { 规格: item.specName } : undefined
        for (let i = 0; i < item.quantity; i++) {
          addItem(
            { dishId: item.dishId, name: item.dishName, price_fen: item.unitPriceFen },
            specs,
          )
        }
      }
      Taro.showToast({ title: '已加入购物车', icon: 'success', duration: 1200 })
      setTimeout(() => {
        Taro.navigateTo({ url: '/subpages/order-flow/cart/index' }).catch(() => {
          Taro.switchTab({ url: '/pages/menu/index' })
        })
      }, 1000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setReordering(false)
    }
  }

  function handleReview() {
    if (!order) return
    Taro.navigateTo({ url: `/subpages/order-detail/review/index?orderId=${order.orderId}` })
  }

  async function handleDelete() {
    if (!order) return
    const res = await Taro.showModal({ title: '删除订单', content: '删除后无法恢复，确认删除？' })
    if (!res.confirm) return
    // Optimistic: just navigate back (backend delete endpoint would be called in real impl)
    Taro.showToast({ title: '已删除', icon: 'success' })
    setTimeout(() => Taro.navigateBack({ delta: 1 }), 800)
  }

  function handleCopyOrderNo() {
    if (!order) return
    Taro.setClipboardData({ data: order.orderNo })
      .then(() => Taro.showToast({ title: '已复制', icon: 'success' }))
      .catch(() => {})
  }

  function handleCall() {
    Taro.makePhoneCall({ phoneNumber: '4000000000' })
  }

  // ── Render helpers ──────────────────────────────────────────────────────────

  function renderStatusCard(o: Order) {
    const cfg = STATUS_CONFIG[o.status] ?? STATUS_CONFIG.pending_payment
    return (
      <View
        style={{
          background: cfg.bgColor,
          borderRadius: '20rpx',
          padding:     '40rpx 32rpx',
          display:     'flex',
          flexDirection: 'column',
          alignItems:  'center',
          gap:         '16rpx',
          marginBottom: '20rpx',
        }}
      >
        <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>{cfg.emoji}</Text>
        <Text style={{ color: cfg.color, fontSize: '36rpx', fontWeight: '700' }}>
          {cfg.label}
        </Text>
        {cfg.showTime && (
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>预计还需 15 分钟</Text>
        )}
      </View>
    )
  }

  function renderStoreSection(o: Order) {
    return (
      <SectionCard>
        <SectionTitle title="门店信息" />
        <View style={{ padding: '20rpx 32rpx 8rpx' }}>
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600', display: 'block', marginBottom: '8rpx' }}>
            {o.storeName || '门店'}
          </Text>
          <Text style={{ color: C.text2, fontSize: '24rpx', display: 'block', marginBottom: '20rpx' }}>
            {/* Address not in Order type; show placeholder */}
            {'请至门店取餐'}
          </Text>
          <View
            onClick={handleCall}
            style={{
              display:        'inline-flex',
              alignItems:     'center',
              gap:            '8rpx',
              background:     C.primaryDim,
              borderRadius:   '30rpx',
              padding:        '12rpx 28rpx',
              marginBottom:   '20rpx',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '24rpx' }}>📞 呼叫门店</Text>
          </View>
        </View>
      </SectionCard>
    )
  }

  function renderItemsSection(o: Order) {
    return (
      <SectionCard>
        <SectionTitle title="菜品明细" />
        {o.items.map((item, i) => (
          <View
            key={`${item.dishId}-${i}`}
            style={{
              display:       'flex',
              flexDirection: 'row',
              alignItems:    'center',
              padding:       '20rpx 32rpx',
              borderBottom:  i < o.items.length - 1 ? `1rpx solid ${C.border}` : 'none',
            }}
          >
            {/* Name + spec */}
            <View style={{ flex: 1 }}>
              <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500', display: 'block' }}>
                {item.dishName}
              </Text>
              {item.specName && (
                <Text style={{ color: C.text2, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                  {item.specName}
                </Text>
              )}
              {item.remark && (
                <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                  备注：{item.remark}
                </Text>
              )}
            </View>
            {/* Quantity */}
            <Text style={{ color: C.text2, fontSize: '26rpx', marginRight: '24rpx' }}>
              ×{item.quantity}
            </Text>
            {/* Price */}
            <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600', minWidth: '100rpx', textAlign: 'right' }}>
              {fenToYuanDisplay(item.totalPriceFen)}
            </Text>
          </View>
        ))}
      </SectionCard>
    )
  }

  function renderPriceSection(o: Order) {
    const hasDiscount = o.discountFen > 0
    return (
      <SectionCard>
        <SectionTitle title="价格明细" />
        <InfoRow label="商品合计" value={fenToYuanDisplay(o.totalFen)} />
        {o.coupon && (
          <InfoRow
            label="优惠券减免"
            value={`-${fenToYuanDisplay(o.coupon.discountFen)}`}
            valueColor={C.primary}
          />
        )}
        {hasDiscount && !o.coupon && (
          <InfoRow
            label="积分抵扣"
            value={`-${fenToYuanDisplay(o.discountFen)}`}
            valueColor={C.primary}
          />
        )}
        {/* Last row: 实付款 — no bottom border, bigger */}
        <View
          style={{
            display:       'flex',
            flexDirection: 'row',
            alignItems:    'center',
            padding:       '24rpx 32rpx',
          }}
        >
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700', flex: 1 }}>实付款</Text>
          <Text style={{ color: C.primary, fontSize: '40rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(o.payableFen)}
          </Text>
        </View>
      </SectionCard>
    )
  }

  function renderOrderInfoSection(o: Order) {
    return (
      <SectionCard>
        <SectionTitle title="订单信息" />
        <InfoRow
          label="订单号"
          value={o.orderNo}
          onAction={handleCopyOrderNo}
          actionLabel="复制"
        />
        <InfoRow label="下单时间" value={formatDateTime(o.createdAt)} />
        {o.paidAt && <InfoRow label="支付时间" value={formatDateTime(o.paidAt)} />}
        <InfoRow
          label="用餐方式"
          value={o.tableNo ? `堂食 · ${o.tableNo}桌` : '外带'}
        />
        <View
          style={{
            padding:       '20rpx 32rpx',
            display:       'flex',
            flexDirection: 'row',
            alignItems:    'flex-start',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '26rpx', width: '160rpx', flexShrink: 0 }}>
            备注
          </Text>
          <Text style={{ color: o.remark ? C.text1 : C.text3, fontSize: '26rpx', flex: 1 }}>
            {o.remark || '无'}
          </Text>
        </View>
      </SectionCard>
    )
  }

  function renderActions(o: Order) {
    const status = o.status as OrderStatus

    // ── pending_payment ──────────────────────────────────────────────────────
    if (status === 'pending_payment') {
      return (
        <View style={styles.actionRow}>
          <ActionBtn
            label={cancelling ? '取消中...' : '取消订单'}
            onTap={handleCancel}
            variant="ghost"
            disabled={cancelling}
          />
          <ActionBtn
            label="去支付"
            onTap={handlePay}
            variant="primary"
          />
        </View>
      )
    }

    // ── preparing / paid / ready ─────────────────────────────────────────────
    if (status === 'paid' || status === 'preparing' || status === 'ready') {
      return (
        <View style={styles.actionRow}>
          <ActionBtn
            label="查看进度"
            onTap={handleTrack}
            variant="primary"
            fullWidth
          />
        </View>
      )
    }

    // ── completed ────────────────────────────────────────────────────────────
    if (status === 'completed') {
      return (
        <View style={styles.actionRow}>
          <ActionBtn
            label={reordering ? '加入中...' : '再来一单'}
            onTap={handleReorder}
            variant="ghost"
            disabled={reordering}
          />
          <ActionBtn
            label="评价"
            onTap={handleReview}
            variant="primary"
          />
        </View>
      )
    }

    // ── cancelled / refunded ─────────────────────────────────────────────────
    if (status === 'cancelled' || status === 'refunded') {
      return (
        <View style={styles.actionRow}>
          <ActionBtn
            label="删除订单"
            onTap={handleDelete}
            variant="danger"
            fullWidth
          />
        </View>
      )
    }

    return null
  }

  // ── Page render ─────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <View style={{ minHeight: '100vh', background: C.bgDeep }}>
        <Skeleton />
      </View>
    )
  }

  if (error || !order) {
    return (
      <View
        style={{
          minHeight:     '100vh',
          background:    C.bgDeep,
          display:       'flex',
          flexDirection: 'column',
          alignItems:    'center',
          justifyContent: 'center',
          gap:           '24rpx',
          padding:       '48rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx' }}>😕</Text>
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
          {error || '订单不存在'}
        </Text>
        <View
          onClick={() => void fetchOrder()}
          style={{
            background:   C.primary,
            borderRadius: '40rpx',
            padding:      '16rpx 48rpx',
            marginTop:    '8rpx',
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
        <View style={{ padding: '24rpx 24rpx 240rpx' }}>
          {renderStatusCard(order)}
          {renderStoreSection(order)}
          {renderItemsSection(order)}
          {renderPriceSection(order)}
          {renderOrderInfoSection(order)}
        </View>
      </ScrollView>

      {/* Sticky bottom action area */}
      <View
        style={{
          position:        'fixed',
          bottom:          0,
          left:            0,
          right:           0,
          background:      C.bgCard,
          borderTop:       `1rpx solid ${C.border}`,
          padding:         '24rpx 32rpx',
          paddingBottom:   'env(safe-area-inset-bottom)',
          backdropFilter:  'blur(12px)',
        }}
      >
        {renderActions(order)}
      </View>
    </View>
  )
}

// ─── Shared button component ──────────────────────────────────────────────────

interface ActionBtnProps {
  label:     string
  onTap:     () => void
  variant:   'primary' | 'ghost' | 'danger'
  disabled?: boolean
  fullWidth?: boolean
}

const C_BTN: Record<string, { bg: string; text: string; border?: string }> = {
  primary: { bg: '#FF6B35',                        text: '#fff' },
  ghost:   { bg: 'transparent',                    text: '#E8F4F8', border: '#1E3040' },
  danger:  { bg: 'rgba(229,57,53,0.15)',            text: '#E53935' },
}

function ActionBtn({ label, onTap, variant, disabled = false, fullWidth = false }: ActionBtnProps) {
  const cfg = C_BTN[variant]
  return (
    <View
      onClick={disabled ? undefined : onTap}
      style={{
        flex:           fullWidth ? 1 : undefined,
        height:         '88rpx',
        background:     disabled ? '#2A4050' : cfg.bg,
        border:         cfg.border ? `2rpx solid ${cfg.border}` : 'none',
        borderRadius:   '44rpx',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        padding:        fullWidth ? undefined : '0 48rpx',
        opacity:        disabled ? 0.6 : 1,
        minWidth:       '180rpx',
      }}
    >
      <Text style={{ color: disabled ? '#6B8A96' : cfg.text, fontSize: '30rpx', fontWeight: '600' }}>
        {label}
      </Text>
    </View>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = {
  actionRow: {
    display:        'flex',
    flexDirection:  'row' as const,
    gap:            '20rpx',
    alignItems:     'center',
  },
}
