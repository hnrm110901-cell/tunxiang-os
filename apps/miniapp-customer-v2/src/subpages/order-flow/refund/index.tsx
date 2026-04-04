/**
 * order-flow/refund/index.tsx — 退款/售后申请页
 *
 * URL params: ?orderId=xxx
 *
 * Features:
 *  - Load order data and display items
 *  - Refund reason selector (radio)
 *  - Optional text description (200 chars)
 *  - Upload evidence photos (up to 3)
 *  - Refund amount display (auto-calculated, non-editable)
 *  - Submit → POST /api/v1/orders/{id}/refund
 *  - Success state with refund ticket number
 *  - Refund policy notice
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Textarea, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, Order } from '../../../api/trade'
import { txRequest } from '../../../utils/request'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B2C',
  primaryDim: 'rgba(255,107,44,0.15)',
  bgDeep:     '#0B1A20',
  bgCard:     '#132029',
  bgHover:    '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  red:        '#E53935',
  redDim:     'rgba(229,57,53,0.15)',
  success:    '#4CAF50',
  successDim: 'rgba(76,175,80,0.15)',
  warning:    '#FFC107',
  warningDim: 'rgba(255,193,7,0.15)',
  white:      '#fff',
  disabled:   '#2A4050',
} as const

// ─── Refund reasons ───────────────────────────────────────────────────────────

interface RefundReason {
  key: string
  label: string
  description: string
}

const REFUND_REASONS: RefundReason[] = [
  { key: 'wrong_dish',     label: '菜品做错',     description: '收到的菜品与下单不符' },
  { key: 'quality_issue',  label: '质量问题',     description: '菜品变质、有异物等' },
  { key: 'missing_item',   label: '缺少菜品',     description: '有菜品未送达' },
  { key: 'late_delivery',  label: '配送超时',     description: '等待时间过长' },
  { key: 'duplicate_order', label: '重复下单',    description: '不小心下了重复的订单' },
  { key: 'changed_mind',   label: '不想要了',     description: '个人原因取消' },
  { key: 'other',          label: '其他原因',     description: '以上都不是' },
]

const MAX_DESCRIPTION = 200
const MAX_PHOTOS = 3

// ─── Refund API types ─────────────────────────────────────────────────────────

interface RefundSubmitResult {
  refundId: string
  refundNo: string
  status: 'pending' | 'approved' | 'rejected'
  refundAmountFen: number
  estimatedDays: number
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionCard({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        background:   C.bgCard,
        borderRadius: '20rpx',
        marginBottom: '20rpx',
        overflow:     'hidden',
      }}
    >
      {title && (
        <View
          style={{
            padding:      '24rpx 32rpx 16rpx',
            borderBottom: `1rpx solid ${C.border}`,
          }}
        >
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700' }}>{title}</Text>
        </View>
      )}
      {children}
    </View>
  )
}

function ReasonRadio({
  reason,
  selected,
  onSelect,
}: {
  reason: RefundReason
  selected: boolean
  onSelect: () => void
}) {
  return (
    <View
      style={{
        display:       'flex',
        flexDirection: 'row',
        alignItems:    'center',
        padding:       '24rpx 32rpx',
        borderBottom:  `1rpx solid ${C.border}`,
        background:    selected ? C.primaryDim : 'transparent',
      }}
      onClick={onSelect}
    >
      <View
        style={{
          width:          '40rpx',
          height:         '40rpx',
          borderRadius:   '20rpx',
          border:         `2rpx solid ${selected ? C.primary : C.text3}`,
          background:     selected ? C.primary : 'transparent',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          marginRight:    '20rpx',
          flexShrink:     0,
        }}
      >
        {selected && (
          <View
            style={{
              width:        '18rpx',
              height:       '18rpx',
              borderRadius: '9rpx',
              background:   C.white,
            }}
          />
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ color: selected ? C.primary : C.text1, fontSize: '28rpx', fontWeight: '500' }}>
          {reason.label}
        </Text>
        <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
          {reason.description}
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

export default function RefundPage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  // ── Remote data ────────────────────────────────────────────────────────────
  const [order,   setOrder]   = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  // ── Form state ─────────────────────────────────────────────────────────────
  const [selectedReason,  setSelectedReason]  = useState<string | null>(null)
  const [description,     setDescription]     = useState('')
  const [photos,          setPhotos]          = useState<string[]>([])
  const [submitting,      setSubmitting]      = useState(false)

  // ── Success state ──────────────────────────────────────────────────────────
  const [refundResult, setRefundResult] = useState<RefundSubmitResult | null>(null)

  // ── Load order ─────────────────────────────────────────────────────────────

  const fetchOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setError('')
    try {
      const data = await getOrder(orderId)
      setOrder(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    void fetchOrder()
  }, [fetchOrder])

  // ── Handlers ───────────────────────────────────────────────────────────────

  async function handleChooseImage() {
    if (photos.length >= MAX_PHOTOS) {
      Taro.showToast({ title: `最多上传${MAX_PHOTOS}张图片`, icon: 'none' })
      return
    }
    try {
      const res = await Taro.chooseImage({
        count:      MAX_PHOTOS - photos.length,
        sizeType:   ['compressed'],
        sourceType: ['album', 'camera'],
      })
      setPhotos((prev) => [...prev, ...res.tempFilePaths].slice(0, MAX_PHOTOS))
    } catch {
      // User cancelled
    }
  }

  function removePhoto(idx: number) {
    setPhotos((prev) => prev.filter((_, i) => i !== idx))
  }

  async function handleSubmit() {
    if (!selectedReason) {
      Taro.showToast({ title: '请选择退款原因', icon: 'none' })
      return
    }
    if (!orderId || !order) return

    setSubmitting(true)
    try {
      const result = await txRequest<RefundSubmitResult>(
        `/api/v1/orders/${encodeURIComponent(orderId)}/refund`,
        'POST',
        {
          reason:      selectedReason,
          description: description.trim() || undefined,
          photos:      photos.length > 0 ? photos : undefined,
        },
      )
      setRefundResult(result)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '提交失败，请重试'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setSubmitting(false)
    }
  }

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
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
          onClick={() => void fetchOrder()}
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

  // ── Success state ──────────────────────────────────────────────────────────

  if (refundResult) {
    return (
      <View
        style={{
          minHeight:      '100vh',
          background:     C.bgDeep,
          display:        'flex',
          flexDirection:  'column',
          alignItems:     'center',
          justifyContent: 'center',
          padding:        '48rpx',
          gap:            '32rpx',
        }}
      >
        <View
          style={{
            width:          '160rpx',
            height:         '160rpx',
            borderRadius:   '80rpx',
            background:     C.successDim,
            border:         `2rpx solid ${C.success}`,
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: C.success, fontSize: '80rpx', lineHeight: '1' }}>✓</Text>
        </View>

        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          退款申请已提交
        </Text>

        <View
          style={{
            background:   C.bgCard,
            borderRadius: '20rpx',
            padding:      '24rpx 32rpx',
            width:        '100%',
          }}
        >
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '16rpx' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>退款单号</Text>
            <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600' }}>
              #{refundResult.refundNo}
            </Text>
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '16rpx' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>退款金额</Text>
            <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
              {fenToYuanDisplay(refundResult.refundAmountFen)}
            </Text>
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>预计到账</Text>
            <Text style={{ color: C.text1, fontSize: '26rpx' }}>
              {refundResult.estimatedDays}个工作日内
            </Text>
          </View>
        </View>

        <View
          style={{
            background:   C.warningDim,
            borderRadius: '16rpx',
            padding:      '20rpx 24rpx',
            width:        '100%',
          }}
        >
          <Text style={{ color: C.warning, fontSize: '24rpx', lineHeight: '36rpx' }}>
            退款将原路返回至您的支付账户，请留意到账通知。如有疑问请联系客服 400-000-0000。
          </Text>
        </View>

        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx', width: '100%', marginTop: '16rpx' }}>
          <View
            style={{
              flex:           1,
              height:         '88rpx',
              border:         `2rpx solid ${C.border}`,
              borderRadius:   '44rpx',
              display:        'flex',
              alignItems:     'center',
              justifyContent: 'center',
            }}
            onClick={() => Taro.navigateBack({ delta: 1 })}
          >
            <Text style={{ color: C.text1, fontSize: '28rpx' }}>返回订单</Text>
          </View>
          <View
            style={{
              flex:           1,
              height:         '88rpx',
              background:     C.primary,
              borderRadius:   '44rpx',
              display:        'flex',
              alignItems:     'center',
              justifyContent: 'center',
            }}
            onClick={() => {
              Taro.switchTab({ url: '/pages/order/index' }).catch(() =>
                Taro.navigateTo({ url: '/pages/order/index' }),
              )
            }}
          >
            <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '600' }}>查看全部订单</Text>
          </View>
        </View>
      </View>
    )
  }

  // ── Main form ──────────────────────────────────────────────────────────────

  const refundableAmount = order.payableFen

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '24rpx 24rpx 200rpx' }}>

          {/* ── Order summary ──────────────────────────────────────────────── */}
          <SectionCard title="退款订单">
            <View style={{ padding: '20rpx 32rpx' }}>
              <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '12rpx' }}>
                <Text style={{ color: C.text2, fontSize: '26rpx' }}>订单号</Text>
                <Text style={{ color: C.text1, fontSize: '26rpx' }}>{order.orderNo}</Text>
              </View>
              <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '12rpx' }}>
                <Text style={{ color: C.text2, fontSize: '26rpx' }}>菜品数量</Text>
                <Text style={{ color: C.text1, fontSize: '26rpx' }}>
                  {order.items.reduce((s, i) => s + i.quantity, 0)}件
                </Text>
              </View>
              <View
                style={{
                  display:        'flex',
                  flexDirection:  'row',
                  justifyContent: 'space-between',
                  paddingTop:     '12rpx',
                  borderTop:      `1rpx solid ${C.border}`,
                }}
              >
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>可退金额</Text>
                <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
                  {fenToYuanDisplay(refundableAmount)}
                </Text>
              </View>
            </View>
          </SectionCard>

          {/* ── Items preview ──────────────────────────────────────────────── */}
          <SectionCard title="包含菜品">
            {order.items.map((item, i) => (
              <View
                key={`${item.dishId}-${i}`}
                style={{
                  display:       'flex',
                  flexDirection: 'row',
                  alignItems:    'center',
                  padding:       '16rpx 32rpx',
                  borderBottom:  i < order.items.length - 1 ? `1rpx solid ${C.border}` : 'none',
                }}
              >
                <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1 }} numberOfLines={1}>
                  {item.dishName}
                  {item.specName ? ` (${item.specName})` : ''}
                </Text>
                <Text style={{ color: C.text2, fontSize: '24rpx', marginLeft: '16rpx' }}>
                  x{item.quantity}
                </Text>
              </View>
            ))}
          </SectionCard>

          {/* ── Refund reason ──────────────────────────────────────────────── */}
          <SectionCard title="退款原因 *">
            {REFUND_REASONS.map((reason) => (
              <ReasonRadio
                key={reason.key}
                reason={reason}
                selected={selectedReason === reason.key}
                onSelect={() => setSelectedReason(reason.key)}
              />
            ))}
          </SectionCard>

          {/* ── Description ────────────────────────────────────────────────── */}
          <SectionCard title="补充说明（选填）">
            <View style={{ padding: '16rpx 32rpx 24rpx' }}>
              <Textarea
                value={description}
                onInput={(e) => setDescription(String(e.detail.value).slice(0, MAX_DESCRIPTION))}
                placeholder="请详细描述问题，有助于加快处理..."
                placeholderStyle={`color: ${C.text3}; font-size: 26rpx;`}
                maxlength={MAX_DESCRIPTION}
                style={{
                  width:        '100%',
                  height:       '160rpx',
                  background:   C.bgDeep,
                  borderRadius: '12rpx',
                  padding:      '20rpx',
                  color:        C.text1,
                  fontSize:     '26rpx',
                  lineHeight:   '1.6',
                  boxSizing:    'border-box',
                  border:       `1rpx solid ${C.border}`,
                }}
              />
              <Text
                style={{
                  display:   'block',
                  textAlign: 'right',
                  color:     description.length >= MAX_DESCRIPTION ? C.red : C.text3,
                  fontSize:  '22rpx',
                  marginTop: '8rpx',
                }}
              >
                {description.length}/{MAX_DESCRIPTION}
              </Text>
            </View>
          </SectionCard>

          {/* ── Photo evidence ─────────────────────────────────────────────── */}
          <SectionCard title="上传凭证（选填）">
            <View
              style={{
                padding:       '20rpx 32rpx',
                display:       'flex',
                flexDirection: 'row',
                flexWrap:      'wrap',
                gap:           '16rpx',
              }}
            >
              {photos.map((src, i) => (
                <View
                  key={i}
                  style={{ position: 'relative', width: '180rpx', height: '180rpx' }}
                >
                  <Image
                    src={src}
                    mode="aspectFill"
                    style={{
                      width:        '180rpx',
                      height:       '180rpx',
                      borderRadius: '12rpx',
                      border:       `1rpx solid ${C.border}`,
                    }}
                  />
                  <View
                    onClick={() => removePhoto(i)}
                    style={{
                      position:       'absolute',
                      top:            '-12rpx',
                      right:          '-12rpx',
                      width:          '44rpx',
                      height:         '44rpx',
                      borderRadius:   '50%',
                      background:     C.red,
                      display:        'flex',
                      alignItems:     'center',
                      justifyContent: 'center',
                      zIndex:         1,
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '24rpx', lineHeight: '1', fontWeight: '700' }}>
                      x
                    </Text>
                  </View>
                </View>
              ))}

              {photos.length < MAX_PHOTOS && (
                <View
                  onClick={handleChooseImage}
                  style={{
                    width:          '180rpx',
                    height:         '180rpx',
                    borderRadius:   '12rpx',
                    border:         `2rpx dashed ${C.border}`,
                    display:        'flex',
                    flexDirection:  'column',
                    alignItems:     'center',
                    justifyContent: 'center',
                    gap:            '8rpx',
                  }}
                >
                  <Text style={{ color: C.text2, fontSize: '48rpx', lineHeight: '1' }}>+</Text>
                  <Text style={{ color: C.text3, fontSize: '22rpx' }}>
                    {photos.length}/{MAX_PHOTOS}
                  </Text>
                </View>
              )}
            </View>
          </SectionCard>

          {/* ── Refund policy notice ────────────────────────────────────────── */}
          <View
            style={{
              background:   C.bgCard,
              borderRadius: '16rpx',
              padding:      '20rpx 24rpx',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600', marginBottom: '8rpx', display: 'block' }}>
              退款须知
            </Text>
            <Text style={{ color: C.text3, fontSize: '22rpx', lineHeight: '34rpx' }}>
              1. 退款申请提交后，将在1-3个工作日内审核{'\n'}
              2. 审核通过后，退款将原路返回至付款账户{'\n'}
              3. 微信支付退款预计1-5个工作日到账{'\n'}
              4. 储值卡支付的退款将即时返还至储值余额{'\n'}
              5. 如有争议，请联系客服 400-000-0000
            </Text>
          </View>

        </View>
      </ScrollView>

      {/* ── Sticky submit button ───────────────────────────────────────────── */}
      <View
        style={{
          position:       'fixed',
          bottom:         0,
          left:           0,
          right:          0,
          background:     C.bgCard,
          borderTop:      `1rpx solid ${C.border}`,
          padding:        '20rpx 32rpx',
          paddingBottom:  'calc(20rpx + env(safe-area-inset-bottom))',
          backdropFilter: 'blur(12px)',
        }}
      >
        <View
          style={{
            display:        'flex',
            flexDirection:  'row',
            alignItems:     'center',
            justifyContent: 'space-between',
            marginBottom:   '12rpx',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>退款金额</Text>
          <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(refundableAmount)}
          </Text>
        </View>
        <View
          onClick={submitting ? undefined : handleSubmit}
          style={{
            height:         '88rpx',
            background:     submitting || !selectedReason ? C.disabled : C.red,
            borderRadius:   '44rpx',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            opacity:        submitting ? 0.7 : (!selectedReason ? 0.5 : 1),
          }}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : '申请退款'}
          </Text>
        </View>
      </View>
    </View>
  )
}
