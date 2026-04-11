/**
 * pay-result/index.tsx — 支付结果页
 *
 * URL params:
 *   orderId        — order ID
 *   status         — "success" | "failed" | "pending"
 *   dineMode       — "dine-in" | "takeaway" | "reservation"
 *   errorCode      — (optional) error code on failure
 *   errorMessage   — (optional) human-readable error message
 *
 * Features:
 *  - Success: green checkmark + order number + wait time + OrderProgress
 *    Auto-navigate away after 3s
 *  - Failed: red X + error message + retry / contact support
 *  - Pending: spinner + "支付处理中..."
 */

import React, { useState, useRef, useEffect } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useOrderStore } from '../../../store/useOrderStore'
import OrderProgress from '../../../components/OrderProgress'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Helpers ──────────────────────────────────────────────────────────────────

type OrderStatus = 'pending' | 'paid' | 'preparing' | 'ready' | 'delivered' | 'cancelled'

function buildProgressSteps(status: OrderStatus) {
  const statusOrder: OrderStatus[] = ['paid', 'preparing', 'ready', 'delivered']
  const labels = ['已支付', '备餐中', '出餐中', '已送达']
  const currentIdx = statusOrder.indexOf(status)
  return labels.map((label, i) => ({
    label,
    done: i < currentIdx || (i === currentIdx && status !== 'pending'),
  }))
}

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  success: '#4CAF50',
  white: '#fff',
  disabled: '#2A4050',
} as const

type PageStatus = 'success' | 'failed' | 'pending'

// ─── Auto-navigate countdown ──────────────────────────────────────────────────

function useAutoNavigate(
  active: boolean,
  delayMs: number,
  destination: string,
) {
  const [remaining, setRemaining] = useState(Math.ceil(delayMs / 1000))
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!active) return

    timerRef.current = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current)
          Taro.redirectTo({ url: destination }).catch(() => {
            Taro.switchTab({ url: destination })
          })
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [active, destination])

  return remaining
}

// ─── Animated checkmark ───────────────────────────────────────────────────────

function SuccessIcon() {
  const [scale, setScale] = useState(0.4)
  const [opacity, setOpacity] = useState(0)

  useEffect(() => {
    // Two-frame pop-in animation using Taro.createAnimation
    const t1 = setTimeout(() => {
      setScale(1.15)
      setOpacity(1)
    }, 50)
    const t2 = setTimeout(() => setScale(1), 280)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [])

  return (
    <View
      style={{
        width: '160rpx',
        height: '160rpx',
        borderRadius: '80rpx',
        background: C.success,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transform: `scale(${scale})`,
        opacity,
        transition: 'transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.15s ease',
      }}
    >
      <Text style={{ color: C.white, fontSize: '80rpx', lineHeight: '1' }}>✓</Text>
    </View>
  )
}

function FailIcon() {
  return (
    <View
      style={{
        width: '160rpx',
        height: '160rpx',
        borderRadius: '80rpx',
        background: C.red,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Text style={{ color: C.white, fontSize: '80rpx', lineHeight: '1' }}>✕</Text>
    </View>
  )
}

function PendingSpinner() {
  const [angle, setAngle] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setAngle((a) => (a + 30) % 360)
    }, 80)
    return () => clearInterval(timer)
  }, [])

  return (
    <View
      style={{
        width: '160rpx',
        height: '160rpx',
        borderRadius: '80rpx',
        border: `8rpx solid ${C.border}`,
        borderTop: `8rpx solid ${C.primary}`,
        transform: `rotate(${angle}deg)`,
      }}
    />
  )
}

// ─── Estimated wait time bar ──────────────────────────────────────────────────

function WaitTimeBar({ estimatedMinutes }: { estimatedMinutes: number }) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '16rpx',
        padding: '24rpx',
        width: '100%',
        maxWidth: '640rpx',
      }}
    >
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16rpx',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '24rpx' }}>预计等待</Text>
        <Text style={{ color: C.primary, fontSize: '32rpx', fontWeight: '700' }}>
          约{estimatedMinutes}分钟
        </Text>
      </View>
      {/* Progress bar placeholder — animation simulates "in queue" */}
      <View
        style={{
          height: '8rpx',
          background: C.border,
          borderRadius: '4rpx',
          overflow: 'hidden',
        }}
      >
        <View
          style={{
            height: '100%',
            width: '15%',
            background: C.primary,
            borderRadius: '4rpx',
          }}
        />
      </View>
      <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '12rpx' }}>
        厨房已收到您的订单，正在备餐...
      </Text>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PayResultPage() {
  // Parse URL params
  const { orderId, status, dineMode, errorCode, errorMessage } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return {
      orderId: (params.orderId as string | undefined) ?? '',
      status: ((params.status as string | undefined) ?? 'pending') as PageStatus,
      dineMode: (params.dineMode as string | undefined) ?? 'dine-in',
      errorCode: (params.errorCode as string | undefined) ?? '',
      errorMessage: decodeURIComponent(
        (params.errorMessage as string | undefined) ?? '支付失败，请重试',
      ),
    }
  })()

  const { currentOrder } = useOrderStore()

  // Estimated wait time for dine-in success (simplified: always show for dine-in)
  const estimatedMinutes = 15

  // Auto-navigate after success
  const autoNavRemaining = useAutoNavigate(
    status === 'success',
    3000,
    '/pages/order/index',
  )

  function goToOrders() {
    Taro.switchTab({ url: '/pages/order/index' }).catch(() =>
      Taro.navigateTo({ url: '/pages/order/index' }),
    )
  }

  function goToMenu() {
    Taro.switchTab({ url: '/pages/menu/index' }).catch(() =>
      Taro.navigateTo({ url: '/pages/menu/index' }),
    )
  }

  function retryPayment() {
    Taro.navigateBack({ delta: 1 })
  }

  function contactSupport() {
    Taro.makePhoneCall({
      phoneNumber: '4000000000',
      fail: () => {
        Taro.showToast({ title: '请拨打 400-000-0000', icon: 'none', duration: 3000 })
      },
    })
  }

  // ── Pending state ──────────────────────────────────────────────────────────
  if (status === 'pending') {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '40rpx',
        }}
      >
        <PendingSpinner />
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>
          支付处理中...
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>
          请勿关闭页面，正在确认支付结果
        </Text>
      </View>
    )
  }

  // ── Failed state ───────────────────────────────────────────────────────────
  if (status === 'failed') {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 48rpx',
          gap: '32rpx',
        }}
      >
        <FailIcon />

        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          支付未完成
        </Text>

        <Text
          style={{
            color: C.text2,
            fontSize: '26rpx',
            textAlign: 'center',
            lineHeight: '40rpx',
          }}
        >
          {errorMessage}
        </Text>

        {errorCode && errorCode !== 'USER_CANCELLED' && (
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>
            错误码: {errorCode}
          </Text>
        )}

        {orderId !== '' && (
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>
            订单号: {orderId}
          </Text>
        )}

        {/* CTA buttons */}
        <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx', width: '100%' }}>
          <View
            style={{
              background: C.primary,
              borderRadius: '44rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={retryPayment}
          >
            <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
              重试支付
            </Text>
          </View>
          <View
            style={{
              border: `2rpx solid ${C.border}`,
              borderRadius: '44rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={contactSupport}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>联系客服</Text>
          </View>
          <View
            style={{
              height: '72rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={goToMenu}
          >
            <Text style={{ color: C.text3, fontSize: '26rpx' }}>返回点餐</Text>
          </View>
        </View>
      </View>
    )
  }

  // ── Success state ──────────────────────────────────────────────────────────
  const isDineIn = dineMode === 'dine-in'
  const orderDisplayNo = currentOrder?.id
    ? currentOrder.id.slice(-6).toUpperCase()
    : orderId.slice(-6).toUpperCase()
  const finalFen = currentOrder?.final_fen

  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '80rpx 40rpx 48rpx',
        gap: '32rpx',
      }}
    >
      <SuccessIcon />

      <Text style={{ color: C.text1, fontSize: '40rpx', fontWeight: '700' }}>
        支付成功
      </Text>

      {finalFen !== undefined && (
        <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
          {fenToYuanDisplay(finalFen)}
        </Text>
      )}

      {/* Order number */}
      <View
        style={{
          background: C.bgCard,
          borderRadius: '16rpx',
          padding: '20rpx 32rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '16rpx',
          alignSelf: 'stretch',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>订单号</Text>
        <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600', flex: 1 }}>
          #{orderDisplayNo}
        </Text>
        <Text
          style={{ color: C.primary, fontSize: '24rpx' }}
          onClick={() => {
            Taro.setClipboardData({ data: orderDisplayNo })
              .then(() => Taro.showToast({ title: '已复制', icon: 'success' }))
              .catch(() => {})
          }}
        >
          复制
        </Text>
      </View>

      {/* Dine-in: estimated wait + order progress */}
      {isDineIn && (
        <>
          <WaitTimeBar estimatedMinutes={estimatedMinutes} />
          {currentOrder && (
            <View style={{ alignSelf: 'stretch' }}>
              <OrderProgress
                status={currentOrder.status}
                steps={buildProgressSteps(currentOrder.status as OrderStatus)}
              />
            </View>
          )}
        </>
      )}

      {/* CTA buttons */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
          alignSelf: 'stretch',
          marginTop: '16rpx',
        }}
      >
        <View
          style={{
            flex: 1,
            height: '88rpx',
            border: `2rpx solid ${C.border}`,
            borderRadius: '44rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={goToOrders}
        >
          <Text style={{ color: C.text1, fontSize: '28rpx' }}>查看订单</Text>
        </View>
        <View
          style={{
            flex: 1,
            height: '88rpx',
            background: C.primary,
            borderRadius: '44rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={goToMenu}
        >
          <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '600' }}>
            继续点餐
          </Text>
        </View>
      </View>

      {/* Auto-navigate countdown */}
      <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '8rpx' }}>
        {autoNavRemaining > 0
          ? `${autoNavRemaining}秒后自动跳转到订单页`
          : '正在跳转...'}
      </Text>
    </View>
  )
}
