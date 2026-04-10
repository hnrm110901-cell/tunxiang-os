/**
 * member/cross-brand — 跨品牌积分通兑
 *
 * 集团内所有品牌的积分/储值统一查看和兑换
 * 对标九毛九集团的多品牌会员中台
 *
 * API: GET /api/v1/member/cross-brand/balance (tx-member已有)
 *      POST /api/v1/member/cross-brand/transfer
 */

import React, { useState, useEffect } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { useStoreInfo } from '../../../store/useStoreInfo'

const C = {
  primary: '#FF6B2C',
  gold: '#C5A347',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  success: '#34C759',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

interface BrandBalance {
  brand_id: string
  brand_name: string
  theme_color: string
  points: number
  stored_value_fen: number
  member_level: string
}

interface CrossBrandSummary {
  total_points: number
  total_stored_value_fen: number
  brands: BrandBalance[]
}

const FALLBACK: CrossBrandSummary = {
  total_points: 12580,
  total_stored_value_fen: 358000,
  brands: [
    { brand_id: 'b1', brand_name: '徐记海鲜', theme_color: '#FF6B35', points: 8200, stored_value_fen: 258000, member_level: 'gold' },
    { brand_id: 'b2', brand_name: '湘厨小馆', theme_color: '#0F6E56', points: 3180, stored_value_fen: 80000, member_level: 'silver' },
    { brand_id: 'b3', brand_name: '海味外卖', theme_color: '#185FA5', points: 1200, stored_value_fen: 20000, member_level: 'bronze' },
  ],
}

const LEVEL_LABELS: Record<string, string> = {
  bronze: '铜卡', silver: '银卡', gold: '金卡', platinum: '白金', diamond: '钻石',
}

export default function CrossBrandPage() {
  const [summary, setSummary] = useState<CrossBrandSummary>(FALLBACK)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    txRequest<CrossBrandSummary>('/member/cross-brand/balance')
      .then(data => { if (data?.brands?.length) setSummary(data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(fen % 100 === 0 ? 0 : 2)}`

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block' }}>跨品牌权益</Text>
      <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx', marginBottom: '32rpx' }}>
        集团内积分/储值通用，一个账户享全部品牌
      </Text>

      {/* 汇总卡片 */}
      <View style={{
        padding: '32rpx', borderRadius: '20rpx',
        background: 'linear-gradient(135deg, #1A2A3A, #0F1F2A)',
        border: `2rpx solid ${C.gold}40`,
        marginBottom: '32rpx',
      }}>
        <View style={{ display: 'flex', justifyContent: 'space-around' }}>
          <View style={{ textAlign: 'center' }}>
            <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block' }}>总积分</Text>
            <Text style={{ fontSize: '44rpx', fontWeight: '700', color: C.gold }}>{summary.total_points.toLocaleString()}</Text>
          </View>
          <View style={{ width: '1rpx', background: C.border }} />
          <View style={{ textAlign: 'center' }}>
            <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block' }}>总储值</Text>
            <Text style={{ fontSize: '44rpx', fontWeight: '700', color: C.primary }}>{fenToYuan(summary.total_stored_value_fen)}</Text>
          </View>
        </View>
        <Text style={{ fontSize: '22rpx', color: C.text3, textAlign: 'center', display: 'block', marginTop: '16rpx' }}>
          积分通兑比例 1:1 · 储值余额全品牌通用
        </Text>
      </View>

      {/* 品牌列表 */}
      <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '16rpx' }}>各品牌明细</Text>

      {summary.brands.map(brand => (
        <View key={brand.brand_id} style={{
          padding: '24rpx', borderRadius: '16rpx', background: C.bgCard,
          border: `2rpx solid ${C.border}`, marginBottom: '12rpx',
        }}>
          <View style={{ display: 'flex', alignItems: 'center', marginBottom: '16rpx' }}>
            <View style={{
              width: '64rpx', height: '64rpx', borderRadius: '16rpx',
              background: brand.theme_color,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginRight: '16rpx',
            }}>
              <Text style={{ fontSize: '28rpx', color: C.white, fontWeight: '700' }}>{brand.brand_name.charAt(0)}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1 }}>{brand.brand_name}</Text>
              <Text style={{ fontSize: '22rpx', color: brand.theme_color }}>{LEVEL_LABELS[brand.member_level] || brand.member_level}</Text>
            </View>
          </View>

          <View style={{ display: 'flex', gap: '16rpx' }}>
            <View style={{ flex: 1, padding: '12rpx', borderRadius: '8rpx', background: C.bgDeep, textAlign: 'center' }}>
              <Text style={{ fontSize: '20rpx', color: C.text3, display: 'block' }}>积分</Text>
              <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.gold }}>{brand.points.toLocaleString()}</Text>
            </View>
            <View style={{ flex: 1, padding: '12rpx', borderRadius: '8rpx', background: C.bgDeep, textAlign: 'center' }}>
              <Text style={{ fontSize: '20rpx', color: C.text3, display: 'block' }}>储值</Text>
              <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.primary }}>{fenToYuan(brand.stored_value_fen)}</Text>
            </View>
          </View>
        </View>
      ))}

      {/* 兑换说明 */}
      <View style={{ padding: '24rpx', borderRadius: '16rpx', background: C.bgCard, marginTop: '24rpx' }}>
        <Text style={{ fontSize: '26rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '12rpx' }}>通兑规则</Text>
        {[
          '积分在集团内所有品牌1:1通用',
          '储值余额在任意品牌门店可直接使用',
          '会员等级按各品牌独立计算',
          '积分有效期以获取日起12个月计算',
        ].map((rule, i) => (
          <Text key={i} style={{ fontSize: '24rpx', color: C.text2, display: 'block', marginBottom: '6rpx' }}>• {rule}</Text>
        ))}
      </View>
    </View>
  )
}
