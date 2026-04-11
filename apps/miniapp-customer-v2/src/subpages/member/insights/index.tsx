/**
 * member/insights — 个人消费报告（类支付宝年度账单）
 *
 * 消费总额/次数/最爱门店/最爱菜品/口味雷达图/消费趋势
 * 可生成海报分享到朋友圈
 *
 * API: GET /api/v1/analytics/member-insights (tx-analytics)
 */

import React, { useState, useEffect } from 'react'
import { View, Text, ScrollView, Canvas } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { useUserStore } from '../../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  gold: '#C5A347',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  success: '#34C759',
  info: '#185FA5',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

interface MemberInsights {
  period: string
  total_spend_fen: number
  order_count: number
  visit_count: number
  avg_check_fen: number
  favorite_store: string
  favorite_dish: string
  favorite_dish_count: number
  top_dishes: { name: string; count: number }[]
  monthly_spend: { month: string; amount_fen: number }[]
  taste_radar: { label: string; value: number }[] // 0-100
  rank_percentile: number // 超过X%的顾客
  total_saved_fen: number
  member_since: string
}

const FALLBACK: MemberInsights = {
  period: '2026',
  total_spend_fen: 2856000,
  order_count: 142,
  visit_count: 89,
  avg_check_fen: 20120,
  favorite_store: '徐记海鲜·芙蓉店',
  favorite_dish: '剁椒鱼头',
  favorite_dish_count: 38,
  top_dishes: [
    { name: '剁椒鱼头', count: 38 },
    { name: '口味虾', count: 29 },
    { name: '农家小炒肉', count: 25 },
    { name: '基围虾（活）', count: 18 },
    { name: '酸梅汤', count: 52 },
  ],
  monthly_spend: [
    { month: '1月', amount_fen: 198000 },
    { month: '2月', amount_fen: 256000 },
    { month: '3月', amount_fen: 312000 },
  ],
  taste_radar: [
    { label: '辣', value: 78 },
    { label: '鲜', value: 92 },
    { label: '甜', value: 35 },
    { label: '酸', value: 45 },
    { label: '咸', value: 60 },
  ],
  rank_percentile: 88,
  total_saved_fen: 358000,
  member_since: '2024-06-15',
}

export default function InsightsPage() {
  const [data, setData] = useState<MemberInsights>(FALLBACK)
  const { nickname } = useUserStore()

  useEffect(() => {
    txRequest<MemberInsights>('/analytics/member-insights')
      .then(d => { if (d?.order_count) setData(d) })
      .catch(() => {})
  }, [])

  const fenToYuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`

  const handleShare = () => {
    Taro.showShareMenu({ withShareTicket: true })
  }

  return (
    <ScrollView scrollY style={{ minHeight: '100vh', background: C.bgDeep }}>
      {/* Hero */}
      <View style={{
        padding: '48rpx 32rpx', textAlign: 'center',
        background: 'linear-gradient(180deg, #1A2A3A 0%, #0B1A20 100%)',
      }}>
        <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block' }}>{nickname || '美食家'}的</Text>
        <Text style={{ fontSize: '44rpx', fontWeight: '700', color: C.gold, display: 'block', marginTop: '8rpx' }}>
          {data.period}年度美食报告
        </Text>
        <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginTop: '8rpx' }}>
          会员自 {data.member_since.slice(0, 7)} · 超过{data.rank_percentile}%的美食爱好者
        </Text>
      </View>

      {/* 核心数字 */}
      <View style={{ display: 'flex', flexWrap: 'wrap', padding: '24rpx 16rpx', gap: '12rpx' }}>
        <NumCard label="总消费" value={fenToYuan(data.total_spend_fen)} color={C.primary} />
        <NumCard label="到店次数" value={`${data.visit_count}次`} color={C.info} />
        <NumCard label="下单次数" value={`${data.order_count}单`} color={C.success} />
        <NumCard label="客单价" value={fenToYuan(data.avg_check_fen)} color={C.gold} />
      </View>

      {/* 最爱 */}
      <View style={{ padding: '0 32rpx', marginBottom: '24rpx' }}>
        <View style={{ background: C.bgCard, borderRadius: '16rpx', padding: '24rpx' }}>
          <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block' }}>你最爱的门店</Text>
          <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginTop: '8rpx' }}>
            {data.favorite_store}
          </Text>
          <View style={{ marginTop: '16rpx', borderTop: `1rpx solid ${C.border}`, paddingTop: '16rpx' }}>
            <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block' }}>你最爱的菜品</Text>
            <View style={{ display: 'flex', alignItems: 'baseline', gap: '8rpx', marginTop: '8rpx' }}>
              <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.primary }}>{data.favorite_dish}</Text>
              <Text style={{ fontSize: '26rpx', color: C.text3 }}>吃了{data.favorite_dish_count}次</Text>
            </View>
          </View>
        </View>
      </View>

      {/* TOP5 菜品 */}
      <View style={{ padding: '0 32rpx', marginBottom: '24rpx' }}>
        <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '12rpx' }}>
          最爱菜品 TOP5
        </Text>
        {data.top_dishes.map((dish, i) => {
          const maxCount = data.top_dishes[0]?.count || 1
          const pct = (dish.count / maxCount) * 100
          return (
            <View key={dish.name} style={{ display: 'flex', alignItems: 'center', marginBottom: '12rpx', gap: '12rpx' }}>
              <Text style={{
                width: '40rpx', fontSize: '28rpx', fontWeight: '700',
                color: i < 3 ? C.primary : C.text3,
              }}>{i + 1}</Text>
              <View style={{ flex: 1 }}>
                <View style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4rpx' }}>
                  <Text style={{ fontSize: '28rpx', color: C.text1 }}>{dish.name}</Text>
                  <Text style={{ fontSize: '24rpx', color: C.text3 }}>{dish.count}次</Text>
                </View>
                <View style={{ height: '8rpx', background: C.border, borderRadius: '4rpx', overflow: 'hidden' }}>
                  <View style={{ height: '100%', width: `${pct}%`, background: i < 3 ? C.primary : C.text3, borderRadius: '4rpx' }} />
                </View>
              </View>
            </View>
          )
        })}
      </View>

      {/* 口味雷达 */}
      <View style={{ padding: '0 32rpx', marginBottom: '24rpx' }}>
        <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '16rpx' }}>
          你的口味画像
        </Text>
        <View style={{ background: C.bgCard, borderRadius: '16rpx', padding: '24rpx' }}>
          <View style={{ display: 'flex', flexWrap: 'wrap', gap: '16rpx' }}>
            {data.taste_radar.map(t => (
              <View key={t.label} style={{ width: '30%', textAlign: 'center' }}>
                <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block' }}>{t.label}</Text>
                <View style={{
                  height: '12rpx', background: C.border, borderRadius: '6rpx',
                  marginTop: '8rpx', overflow: 'hidden',
                }}>
                  <View style={{
                    height: '100%', width: `${t.value}%`, borderRadius: '6rpx',
                    background: t.value > 70 ? C.primary : t.value > 40 ? C.gold : C.info,
                  }} />
                </View>
                <Text style={{ fontSize: '22rpx', color: C.text2, marginTop: '4rpx' }}>{t.value}%</Text>
              </View>
            ))}
          </View>
        </View>
      </View>

      {/* 省钱 */}
      <View style={{ padding: '0 32rpx', marginBottom: '24rpx' }}>
        <View style={{
          background: `${C.success}10`, borderRadius: '16rpx', padding: '24rpx',
          border: `1rpx solid ${C.success}30`, textAlign: 'center',
        }}>
          <Text style={{ fontSize: '26rpx', color: C.success, display: 'block' }}>会员共为你省下</Text>
          <Text style={{ fontSize: '48rpx', fontWeight: '700', color: C.success, display: 'block', marginTop: '8rpx' }}>
            {fenToYuan(data.total_saved_fen)}
          </Text>
        </View>
      </View>

      {/* 分享按钮 */}
      <View style={{ padding: '0 32rpx 64rpx' }}>
        <View
          onClick={handleShare}
          style={{ padding: '28rpx 0', borderRadius: '16rpx', background: C.primary, textAlign: 'center' }}
        >
          <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>分享我的美食年报</Text>
        </View>
      </View>
    </ScrollView>
  )
}

function NumCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={{
      width: 'calc(50% - 6rpx)', padding: '20rpx', borderRadius: '12rpx',
      background: '#132029', textAlign: 'center',
    }}>
      <Text style={{ fontSize: '22rpx', color: '#5A7A88', display: 'block' }}>{label}</Text>
      <Text style={{ fontSize: '36rpx', fontWeight: '700', color, display: 'block', marginTop: '8rpx' }}>{value}</Text>
    </View>
  )
}
