/**
 * review-reward/index.tsx — 评价激励系统
 *
 * 消费后评价奖励：
 * - 文字评价 → 20积分
 * - 带图评价 → 50积分
 * - 精选评价（被选为精选） → 100积分 + 优惠券
 * - 首次评价额外奖励
 *
 * UGC展示：
 * - 精选晒图瀑布流
 * - AI评价摘要（门店级别汇总好评/差评关键词）
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Image, Textarea } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../utils/request'
import { useUserStore } from '../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  gold: '#C5A347',
  success: '#34C759',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
  star: '#FFD700',
} as const

type Tab = 'write' | 'gallery' | 'summary'

interface ReviewPhoto {
  id: string
  url: string
  reviewer: string
  dish: string
  rating: number
  content: string
  likes: number
  created_at: string
}

interface AiSummary {
  total_reviews: number
  avg_rating: number
  positive_keywords: string[]
  negative_keywords: string[]
  ai_summary: string
}

// ─── Fallback ──────────────────────────────────────────────────────────────

const MOCK_GALLERY: ReviewPhoto[] = [
  { id: '1', url: '', reviewer: '张**', dish: '剁椒鱼头', rating: 5, content: '鲜辣适口，鱼肉嫩滑，必点！', likes: 42, created_at: '2h前' },
  { id: '2', url: '', reviewer: '李**', dish: '口味虾', rating: 5, content: '个大肉多，调味绝了', likes: 38, created_at: '3h前' },
  { id: '3', url: '', reviewer: '王**', dish: '红烧肉', rating: 4, content: '入口即化，就是有点甜', likes: 15, created_at: '5h前' },
  { id: '4', url: '', reviewer: '赵**', dish: '蒜蓉扇贝', rating: 5, content: '蒜蓉很香，扇贝新鲜', likes: 28, created_at: '1天前' },
]

const MOCK_SUMMARY: AiSummary = {
  total_reviews: 1268,
  avg_rating: 4.6,
  positive_keywords: ['新鲜', '好吃', '服务好', '环境棒', '性价比高', '上菜快'],
  negative_keywords: ['等位久', '包间小', '停车不便'],
  ai_summary: '顾客对食材新鲜度和菜品口味评价极高，特别是海鲜类菜品获得一致好评。服务态度广受认可。主要改进建议集中在高峰期等位时间和停车便利性。',
}

// ─── 主组件 ──────────────────────────────────────────────────────────────

export default function ReviewRewardPage() {
  const [tab, setTab] = useState<Tab>('write')
  const [gallery, setGallery] = useState<ReviewPhoto[]>(MOCK_GALLERY)
  const [summary, setSummary] = useState<AiSummary>(MOCK_SUMMARY)

  // ─── 写评价Tab ──────────────────────────────────────────────────────────

  const [rating, setRating] = useState(5)
  const [reviewText, setReviewText] = useState('')
  const [photos, setPhotos] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  const handleAddPhoto = () => {
    Taro.chooseImage({
      count: 3 - photos.length,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
    }).then(res => {
      setPhotos(prev => [...prev, ...res.tempFilePaths].slice(0, 3))
    }).catch(() => {})
  }

  const handleSubmit = useCallback(async () => {
    if (!reviewText.trim()) {
      Taro.showToast({ title: '请输入评价内容', icon: 'none' })
      return
    }
    setSubmitting(true)

    const points = photos.length > 0 ? 50 : 20

    try {
      await txRequest('/growth/reviews', 'POST', {
        rating, content: reviewText, photo_count: photos.length,
      } as Record<string, unknown>)
      Taro.showToast({ title: `评价成功！+${points}积分`, icon: 'success' })
      setTimeout(() => Taro.navigateBack(), 1500)
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' })
    }
    setSubmitting(false)
  }, [rating, reviewText, photos])

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      {/* Tabs */}
      <View style={{ display: 'flex', borderBottom: `1rpx solid ${C.border}` }}>
        {([['write', '写评价'], ['gallery', '美食晒图'], ['summary', 'AI摘要']] as [Tab, string][]).map(([key, label]) => (
          <View key={key} onClick={() => setTab(key)} style={{
            flex: 1, padding: '24rpx 0', textAlign: 'center',
            borderBottom: tab === key ? `4rpx solid ${C.primary}` : 'none',
          }}>
            <Text style={{ fontSize: '28rpx', color: tab === key ? C.primary : C.text3, fontWeight: tab === key ? '600' : '400' }}>{label}</Text>
          </View>
        ))}
      </View>

      {/* 写评价 */}
      {tab === 'write' && (
        <View style={{ padding: '32rpx' }}>
          {/* 奖励提示 */}
          <View style={{ padding: '20rpx', borderRadius: '12rpx', background: `${C.gold}15`, border: `1rpx solid ${C.gold}30`, marginBottom: '24rpx' }}>
            <Text style={{ fontSize: '26rpx', color: C.gold }}>⭐ 文字评价+20积分 · 带图评价+50积分 · 精选评价+100积分</Text>
          </View>

          {/* 星级 */}
          <View style={{ display: 'flex', alignItems: 'center', gap: '12rpx', marginBottom: '24rpx' }}>
            <Text style={{ fontSize: '28rpx', color: C.text2 }}>整体评分</Text>
            <View style={{ display: 'flex', gap: '8rpx' }}>
              {[1, 2, 3, 4, 5].map(s => (
                <Text key={s} onClick={() => setRating(s)} style={{ fontSize: '40rpx', color: s <= rating ? C.star : C.text3 }}>★</Text>
              ))}
            </View>
          </View>

          {/* 文字 */}
          <Textarea
            value={reviewText}
            onInput={e => setReviewText(e.detail.value)}
            placeholder="分享你的用餐体验..."
            maxlength={500}
            style={{
              width: '100%', minHeight: '200rpx', padding: '20rpx',
              background: C.bgCard, border: `2rpx solid ${C.border}`, borderRadius: '12rpx',
              color: C.text1, fontSize: '28rpx',
            }}
            placeholderStyle={`color: ${C.text3}`}
          />
          <Text style={{ fontSize: '22rpx', color: C.text3, textAlign: 'right', display: 'block', marginTop: '8rpx' }}>{reviewText.length}/500</Text>

          {/* 图片 */}
          <View style={{ display: 'flex', gap: '12rpx', marginTop: '16rpx', flexWrap: 'wrap' }}>
            {photos.map((p, i) => (
              <View key={i} style={{ width: '160rpx', height: '160rpx', borderRadius: '12rpx', background: C.bgCard, overflow: 'hidden', position: 'relative' }}>
                <Image src={p} style={{ width: '100%', height: '100%' }} mode="aspectFill" />
                <Text onClick={() => setPhotos(prev => prev.filter((_, j) => j !== i))}
                  style={{ position: 'absolute', top: '4rpx', right: '8rpx', fontSize: '28rpx', color: C.white }}>✕</Text>
              </View>
            ))}
            {photos.length < 3 && (
              <View onClick={handleAddPhoto} style={{
                width: '160rpx', height: '160rpx', borderRadius: '12rpx',
                background: C.bgCard, border: `2rpx dashed ${C.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column',
              }}>
                <Text style={{ fontSize: '40rpx', color: C.text3 }}>+</Text>
                <Text style={{ fontSize: '20rpx', color: C.text3 }}>添加图片</Text>
              </View>
            )}
          </View>

          {/* 提交 */}
          <View onClick={handleSubmit} style={{
            marginTop: '32rpx', padding: '28rpx 0', borderRadius: '16rpx',
            background: submitting ? C.bgCard : C.primary, textAlign: 'center',
          }}>
            <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>
              {submitting ? '提交中...' : `提交评价 (+${photos.length > 0 ? 50 : 20}积分)`}
            </Text>
          </View>
        </View>
      )}

      {/* 美食晒图 */}
      {tab === 'gallery' && (
        <ScrollView scrollY style={{ padding: '16rpx' }}>
          <View style={{ display: 'flex', flexWrap: 'wrap', gap: '12rpx' }}>
            {gallery.map(item => (
              <View key={item.id} style={{
                width: 'calc(50% - 6rpx)', background: C.bgCard, borderRadius: '16rpx', overflow: 'hidden',
              }}>
                <View style={{ height: '240rpx', background: `${C.primary}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Text style={{ fontSize: '64rpx' }}>📸</Text>
                </View>
                <View style={{ padding: '16rpx' }}>
                  <Text style={{ fontSize: '26rpx', fontWeight: '600', color: C.text1, display: 'block' }}>{item.dish}</Text>
                  <Text style={{ fontSize: '22rpx', color: C.text2, display: 'block', marginTop: '4rpx' }}>{item.content}</Text>
                  <View style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8rpx' }}>
                    <Text style={{ fontSize: '20rpx', color: C.text3 }}>{item.reviewer} · {item.created_at}</Text>
                    <Text style={{ fontSize: '20rpx', color: C.primary }}>❤ {item.likes}</Text>
                  </View>
                </View>
              </View>
            ))}
          </View>
        </ScrollView>
      )}

      {/* AI摘要 */}
      {tab === 'summary' && (
        <View style={{ padding: '32rpx' }}>
          <View style={{ display: 'flex', gap: '16rpx', marginBottom: '24rpx' }}>
            <View style={{ flex: 1, textAlign: 'center', padding: '20rpx', background: C.bgCard, borderRadius: '12rpx' }}>
              <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.gold }}>{summary.avg_rating}</Text>
              <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block' }}>评分</Text>
            </View>
            <View style={{ flex: 1, textAlign: 'center', padding: '20rpx', background: C.bgCard, borderRadius: '12rpx' }}>
              <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1 }}>{summary.total_reviews}</Text>
              <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block' }}>评价数</Text>
            </View>
          </View>

          <View style={{ background: `rgba(24,95,165,0.08)`, borderRadius: '16rpx', padding: '24rpx', marginBottom: '24rpx' }}>
            <Text style={{ fontSize: '26rpx', color: '#185FA5', display: 'block', marginBottom: '8rpx' }}>💡 AI 评价摘要</Text>
            <Text style={{ fontSize: '26rpx', color: C.text1, lineHeight: '40rpx' }}>{summary.ai_summary}</Text>
          </View>

          <View style={{ marginBottom: '16rpx' }}>
            <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.success, display: 'block', marginBottom: '8rpx' }}>👍 好评关键词</Text>
            <View style={{ display: 'flex', flexWrap: 'wrap', gap: '8rpx' }}>
              {summary.positive_keywords.map(k => (
                <View key={k} style={{ padding: '8rpx 16rpx', borderRadius: '24rpx', background: `${C.success}15` }}>
                  <Text style={{ fontSize: '24rpx', color: C.success }}>{k}</Text>
                </View>
              ))}
            </View>
          </View>

          <View>
            <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.primary, display: 'block', marginBottom: '8rpx' }}>💬 改进建议</Text>
            <View style={{ display: 'flex', flexWrap: 'wrap', gap: '8rpx' }}>
              {summary.negative_keywords.map(k => (
                <View key={k} style={{ padding: '8rpx 16rpx', borderRadius: '24rpx', background: `${C.primary}15` }}>
                  <Text style={{ fontSize: '24rpx', color: C.primary }}>{k}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>
      )}
    </View>
  )
}
