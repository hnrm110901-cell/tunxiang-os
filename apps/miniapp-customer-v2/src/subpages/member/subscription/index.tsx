/**
 * member/subscription — 付费会员卡（订阅制）
 *
 * 对标瑞幸自由卡/喜茶黑卡：
 * - 月卡 ¥19.9/月（每单9折+免配送+生日双倍积分）
 * - 季卡 ¥49.9/季（月卡权益+每月1张50减20券）
 * - 年卡 ¥168/年（季卡权益+专属客服+优先排队）
 *
 * API: POST /api/v1/member/subscriptions (tx-member)
 *      GET  /api/v1/member/subscriptions/my
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { useUserStore } from '../../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  gold: '#C5A347',
  goldBg: 'linear-gradient(135deg, #C5A347, #E8D48B)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Plans ────────────────────────────────────────────────────────────────────

interface Plan {
  id: string
  name: string
  priceFen: number
  period: string
  perMonthFen: number
  badge: string
  popular?: boolean
  benefits: string[]
}

const PLANS: Plan[] = [
  {
    id: 'monthly',
    name: '月卡',
    priceFen: 1990,
    period: '月',
    perMonthFen: 1990,
    badge: '🥈',
    benefits: [
      '每单享9折优惠',
      '免外卖配送费',
      '生日月双倍积分',
      '专属会员价菜品',
    ],
  },
  {
    id: 'quarterly',
    name: '季卡',
    priceFen: 4990,
    period: '季',
    perMonthFen: 1663,
    badge: '🥇',
    popular: true,
    benefits: [
      '月卡全部权益',
      '每月1张满50减20券',
      '新品优先体验',
      '积分1.5倍加速',
    ],
  },
  {
    id: 'yearly',
    name: '年卡',
    priceFen: 16800,
    period: '年',
    perMonthFen: 1400,
    badge: '👑',
    benefits: [
      '季卡全部权益',
      '专属1对1客服',
      '排队优先叫号',
      '生日免费菜品1道',
      '积分2倍加速',
      '跨品牌权益通用',
    ],
  },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function SubscriptionPage() {
  const [selectedPlan, setSelectedPlan] = useState('quarterly')
  const [currentSub, setCurrentSub] = useState<{ plan_id: string; expires_at: string } | null>(null)
  const [purchasing, setPurchasing] = useState(false)
  const { memberLevel } = useUserStore()

  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(fen % 100 === 0 ? 0 : 1)}`

  // 加载当前订阅
  useEffect(() => {
    txRequest<{ plan_id: string; expires_at: string }>('/member/subscriptions/my')
      .then(data => { if (data?.plan_id) setCurrentSub(data) })
      .catch(() => {})
  }, [])

  const handlePurchase = useCallback(async () => {
    if (purchasing) return
    setPurchasing(true)

    try {
      const data = await txRequest<{ payment_params: Record<string, string> }>(
        '/member/subscriptions',
        'POST',
        { plan_id: selectedPlan } as Record<string, unknown>,
      )

      // 调起微信支付
      if (data?.payment_params) {
        await Taro.requestPayment({
          timeStamp: data.payment_params.timeStamp,
          nonceStr: data.payment_params.nonceStr,
          package: data.payment_params.package,
          signType: data.payment_params.signType as 'MD5' | 'HMAC-SHA256' | 'RSA',
          paySign: data.payment_params.paySign,
        })
        Taro.showToast({ title: '开通成功！', icon: 'success' })
        // 刷新订阅状态
        const sub = await txRequest<{ plan_id: string; expires_at: string }>('/member/subscriptions/my')
        if (sub?.plan_id) setCurrentSub(sub)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '支付失败'
      if (!msg.includes('cancel')) {
        Taro.showToast({ title: msg, icon: 'none' })
      }
    }

    setPurchasing(false)
  }, [selectedPlan, purchasing])

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      {/* Hero */}
      <View style={{
        padding: '48rpx 32rpx 32rpx',
        background: 'linear-gradient(180deg, #1A2A3A 0%, #0B1A20 100%)',
        textAlign: 'center',
      }}>
        <Text style={{ fontSize: '44rpx', fontWeight: '700', color: C.gold, display: 'block' }}>
          屯象会员
        </Text>
        <Text style={{ fontSize: '26rpx', color: C.text2, marginTop: '8rpx', display: 'block' }}>
          开通即享专属折扣 · 积分加速 · 优先服务
        </Text>
        {currentSub && (
          <View style={{
            marginTop: '20rpx', padding: '12rpx 24rpx', borderRadius: '24rpx',
            background: `${C.gold}20`, display: 'inline-block',
          }}>
            <Text style={{ fontSize: '24rpx', color: C.gold }}>
              当前: {PLANS.find(p => p.id === currentSub.plan_id)?.name || '会员'} · 有效期至 {currentSub.expires_at.slice(0, 10)}
            </Text>
          </View>
        )}
      </View>

      {/* Plan Cards */}
      <ScrollView scrollX style={{ padding: '24rpx 0', whiteSpace: 'nowrap' }}>
        {PLANS.map(plan => {
          const isSelected = selectedPlan === plan.id
          return (
            <View
              key={plan.id}
              onClick={() => setSelectedPlan(plan.id)}
              style={{
                display: 'inline-block',
                width: '320rpx',
                marginLeft: '24rpx',
                padding: '28rpx 24rpx',
                borderRadius: '20rpx',
                background: isSelected ? C.bgCard : C.bgDeep,
                border: isSelected ? `3rpx solid ${C.gold}` : `2rpx solid ${C.border}`,
                verticalAlign: 'top',
                position: 'relative',
              }}
            >
              {plan.popular && (
                <View style={{
                  position: 'absolute', top: '-2rpx', right: '20rpx',
                  padding: '4rpx 16rpx', borderRadius: '0 0 8rpx 8rpx',
                  background: C.primary,
                }}>
                  <Text style={{ fontSize: '20rpx', color: C.white }}>最受欢迎</Text>
                </View>
              )}

              <Text style={{ fontSize: '36rpx', display: 'block' }}>{plan.badge}</Text>
              <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginTop: '8rpx' }}>
                {plan.name}
              </Text>
              <View style={{ marginTop: '12rpx' }}>
                <Text style={{ fontSize: '44rpx', fontWeight: '700', color: C.gold }}>{fenToYuan(plan.priceFen)}</Text>
                <Text style={{ fontSize: '24rpx', color: C.text3 }}>/{plan.period}</Text>
              </View>
              <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>
                约 {fenToYuan(plan.perMonthFen)}/月
              </Text>
            </View>
          )
        })}
        <View style={{ display: 'inline-block', width: '24rpx' }} />
      </ScrollView>

      {/* Benefits */}
      <View style={{ padding: '0 32rpx' }}>
        <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '16rpx' }}>
          {PLANS.find(p => p.id === selectedPlan)?.badge} {PLANS.find(p => p.id === selectedPlan)?.name}权益
        </Text>
        {PLANS.find(p => p.id === selectedPlan)?.benefits.map((b, i) => (
          <View key={i} style={{
            display: 'flex', alignItems: 'center', gap: '12rpx',
            padding: '16rpx 20rpx', marginBottom: '8rpx',
            borderRadius: '12rpx', background: C.bgCard,
          }}>
            <Text style={{ fontSize: '24rpx', color: C.gold }}>✓</Text>
            <Text style={{ fontSize: '28rpx', color: C.text1 }}>{b}</Text>
          </View>
        ))}
      </View>

      {/* Compare table */}
      <View style={{ padding: '32rpx', marginTop: '16rpx' }}>
        <Text style={{ fontSize: '26rpx', color: C.text3, textAlign: 'center', display: 'block', marginBottom: '16rpx' }}>
          普通会员 vs 付费会员
        </Text>
        {[
          { label: '消费折扣', free: '无', paid: '每单9折' },
          { label: '积分倍率', free: '1x', paid: '最高2x' },
          { label: '配送费', free: '¥5起', paid: '免费' },
          { label: '生日权益', free: '积分', paid: '免费菜品' },
          { label: '排队', free: '正常', paid: '优先叫号' },
        ].map(row => (
          <View key={row.label} style={{
            display: 'flex', padding: '14rpx 0', borderBottom: `1rpx solid ${C.border}`,
          }}>
            <Text style={{ flex: 1, fontSize: '26rpx', color: C.text2 }}>{row.label}</Text>
            <Text style={{ width: '160rpx', fontSize: '26rpx', color: C.text3, textAlign: 'center' }}>{row.free}</Text>
            <Text style={{ width: '160rpx', fontSize: '26rpx', color: C.gold, textAlign: 'center', fontWeight: '500' }}>{row.paid}</Text>
          </View>
        ))}
      </View>

      {/* Purchase button */}
      <View style={{ padding: '24rpx 32rpx 64rpx', position: 'sticky', bottom: 0, background: C.bgDeep }}>
        <View
          onClick={handlePurchase}
          style={{
            padding: '28rpx 0',
            borderRadius: '16rpx',
            background: purchasing ? C.bgCard : C.goldBg,
            textAlign: 'center',
            opacity: purchasing ? 0.6 : 1,
          }}
        >
          <Text style={{ fontSize: '32rpx', fontWeight: '600', color: purchasing ? C.text3 : '#1a1a00' }}>
            {purchasing
              ? '处理中...'
              : currentSub
                ? `续费 ${PLANS.find(p => p.id === selectedPlan)?.name} ${fenToYuan(PLANS.find(p => p.id === selectedPlan)?.priceFen || 0)}`
                : `立即开通 ${fenToYuan(PLANS.find(p => p.id === selectedPlan)?.priceFen || 0)}`
            }
          </Text>
        </View>
        <Text style={{ fontSize: '22rpx', color: C.text3, textAlign: 'center', display: 'block', marginTop: '12rpx' }}>
          开通即同意《屯象会员服务协议》· 支持微信委托代扣自动续费
        </Text>
      </View>
    </View>
  )
}
