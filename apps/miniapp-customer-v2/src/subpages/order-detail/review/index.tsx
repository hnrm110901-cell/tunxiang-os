/**
 * order-detail/review/index.tsx — 订单评价页
 *
 * URL params: ?orderId=xxx
 *
 * Features:
 *  - Overall 5-star rating
 *  - Per-dish 5-star rating rows
 *  - Text review textarea (200 chars max + counter)
 *  - Quick-select tag chips (multi-select, brand color when selected)
 *  - Image upload up to 3 photos via Taro.chooseImage → thumbnails with delete X
 *  - Anonymous toggle
 *  - Submit → POST /api/v1/orders/{id}/review
 *  - Success: confetti emoji burst + "感谢您的评价！" + auto navigate back after 2s
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Textarea, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, Order } from '../../../api/trade'
import { txRequest } from '../../../utils/request'

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
  red:        '#E53935',
  success:    '#4CAF50',
  successDim: 'rgba(76,175,80,0.15)',
  white:      '#fff',
  disabled:   '#2A4050',
  star:       '#FF6B2C',
  starEmpty:  '#2A4050',
} as const

const MAX_TEXT   = 200
const MAX_PHOTOS = 3

const QUICK_TAGS = ['味道好', '分量足', '服务棒', '环境好', '上菜快'] as const
type QuickTag = typeof QUICK_TAGS[number]

// ─── Star rating row ──────────────────────────────────────────────────────────

interface StarRowProps {
  value:    number
  onChange: (v: number) => void
  size?:    number
}

function StarRow({ value, onChange, size = 48 }: StarRowProps) {
  return (
    <View style={{ display: 'flex', flexDirection: 'row', gap: '8rpx' }}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Text
          key={star}
          onClick={() => onChange(star)}
          style={{
            fontSize:   `${size}rpx`,
            color:      star <= value ? C.star : C.starEmpty,
            lineHeight: '1',
            transition: 'color 0.15s',
          }}
        >
          ★
        </Text>
      ))}
    </View>
  )
}

// ─── Section card ─────────────────────────────────────────────────────────────

function SectionCard({ children, title }: { children: React.ReactNode; title?: string }) {
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

// ─── Confetti success overlay ─────────────────────────────────────────────────

const CONFETTI_EMOJIS = ['🎉', '✨', '🎊', '⭐', '🌟', '🎈', '🥳', '🎁']

interface ConfettiPiece {
  id:    number
  emoji: string
  left:  number
  delay: number
  size:  number
}

function SuccessOverlay() {
  const [pieces] = useState<ConfettiPiece[]>(() =>
    Array.from({ length: 16 }, (_, i) => ({
      id:    i,
      emoji: CONFETTI_EMOJIS[i % CONFETTI_EMOJIS.length],
      left:  Math.random() * 90,
      delay: Math.random() * 0.4,
      size:  32 + Math.floor(Math.random() * 24),
    })),
  )

  const [scale, setScale] = useState(0.3)
  useEffect(() => {
    const t = setTimeout(() => setScale(1), 50)
    return () => clearTimeout(t)
  }, [])

  return (
    <View
      style={{
        position:       'fixed',
        inset:          0,
        background:     'rgba(11,26,32,0.92)',
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        zIndex:         999,
        overflow:       'hidden',
      }}
    >
      {/* Falling confetti */}
      {pieces.map((p) => (
        <Text
          key={p.id}
          style={{
            position:        'absolute',
            top:             '-40rpx',
            left:            `${p.left}%`,
            fontSize:        `${p.size}rpx`,
            lineHeight:      '1',
            animationDelay:  `${p.delay}s`,
            // Simulate fall with transform + opacity (no keyframes in miniapp inline)
            // We just scatter them across screen, relying on render timing
            transform:       `translateY(${60 + p.id * 40}rpx)`,
            opacity:         0.9,
          }}
        >
          {p.emoji}
        </Text>
      ))}

      {/* Central card */}
      <View
        style={{
          background:     C.bgCard,
          borderRadius:   '32rpx',
          padding:        '56rpx 64rpx',
          display:        'flex',
          flexDirection:  'column',
          alignItems:     'center',
          gap:            '20rpx',
          transform:      `scale(${scale})`,
          transition:     'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}
      >
        <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>🎉</Text>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700', textAlign: 'center' }}>
          感谢您的评价！
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx', textAlign: 'center' }}>
          您的反馈将帮助我们持续改进
        </Text>
        <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '8rpx' }}>
          即将自动返回...
        </Text>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

interface DishRating {
  dishId:   string
  dishName: string
  rating:   number
}

export default function ReviewPage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  // ── Remote data ────────────────────────────────────────────────────────────
  const [order,   setOrder]   = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  // ── Form state ─────────────────────────────────────────────────────────────
  const [overallRating,   setOverallRating]   = useState(5)
  const [dishRatings,     setDishRatings]     = useState<DishRating[]>([])
  const [reviewText,      setReviewText]      = useState('')
  const [selectedTags,    setSelectedTags]    = useState<Set<QuickTag>>(new Set())
  const [photos,          setPhotos]          = useState<string[]>([])
  const [isAnonymous,     setIsAnonymous]     = useState(false)
  const [submitting,      setSubmitting]      = useState(false)
  const [submitted,       setSubmitted]       = useState(false)

  // ── Load order ─────────────────────────────────────────────────────────────

  const fetchOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setError('')
    try {
      const data = await getOrder(orderId)
      setOrder(data)
      // Initialize per-dish ratings
      const unique = data.items.reduce<DishRating[]>((acc, item) => {
        if (!acc.find((d) => d.dishId === item.dishId)) {
          acc.push({ dishId: item.dishId, dishName: item.dishName, rating: 5 })
        }
        return acc
      }, [])
      setDishRatings(unique)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    void fetchOrder()
  }, [fetchOrder])

  // ── Auto-navigate after success ────────────────────────────────────────────

  useEffect(() => {
    if (!submitted) return
    const t = setTimeout(() => {
      Taro.navigateBack({ delta: 2 }).catch(() => Taro.navigateBack({ delta: 1 }))
    }, 2000)
    return () => clearTimeout(t)
  }, [submitted])

  // ── Handlers ────────────────────────────────────────────────────────────────

  function updateDishRating(dishId: string, rating: number) {
    setDishRatings((prev) =>
      prev.map((d) => (d.dishId === dishId ? { ...d, rating } : d)),
    )
  }

  function toggleTag(tag: QuickTag) {
    setSelectedTags((prev) => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  async function handleChooseImage() {
    if (photos.length >= MAX_PHOTOS) {
      Taro.showToast({ title: `最多上传${MAX_PHOTOS}张图片`, icon: 'none' })
      return
    }
    try {
      const res = await Taro.chooseImage({
        count:     MAX_PHOTOS - photos.length,
        sizeType:  ['compressed'],
        sourceType: ['album', 'camera'],
      })
      setPhotos((prev) => [...prev, ...res.tempFilePaths].slice(0, MAX_PHOTOS))
    } catch {
      // User cancelled or permission denied — silent
    }
  }

  function removePhoto(idx: number) {
    setPhotos((prev) => prev.filter((_, i) => i !== idx))
  }

  async function handleSubmit() {
    if (overallRating === 0) {
      Taro.showToast({ title: '请选择总体评分', icon: 'none' })
      return
    }
    if (!orderId) return

    setSubmitting(true)
    try {
      await txRequest(`/api/v1/orders/${encodeURIComponent(orderId)}/review`, 'POST', {
        overallRating,
        dishRatings,
        content:     reviewText.trim(),
        tags:        Array.from(selectedTags),
        photos,
        anonymous:   isAnonymous,
      })
      setSubmitted(true)
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
          alignItems:     'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
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

  // ── Main render ────────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      {submitted && <SuccessOverlay />}

      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '24rpx 24rpx 200rpx' }}>

          {/* ── 1. Overall rating ─────────────────────────────────────────── */}
          <SectionCard>
            <View
              style={{
                padding:        '40rpx 32rpx',
                display:        'flex',
                flexDirection:  'column',
                alignItems:     'center',
                gap:            '20rpx',
              }}
            >
              <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>
                总体评分
              </Text>
              <StarRow value={overallRating} onChange={setOverallRating} size={64} />
              <Text style={{ color: C.text2, fontSize: '24rpx' }}>
                {['', '非常不满意', '不满意', '一般', '满意', '非常满意'][overallRating]}
              </Text>
            </View>
          </SectionCard>

          {/* ── 2. Per-dish ratings ───────────────────────────────────────── */}
          {dishRatings.length > 0 && (
            <SectionCard title="菜品评分">
              {dishRatings.map((d, i) => (
                <View
                  key={d.dishId}
                  style={{
                    display:       'flex',
                    flexDirection: 'row',
                    alignItems:    'center',
                    padding:       '20rpx 32rpx',
                    borderBottom:  i < dishRatings.length - 1 ? `1rpx solid ${C.border}` : 'none',
                  }}
                >
                  <Text
                    style={{
                      color:    C.text1,
                      fontSize: '26rpx',
                      flex:     1,
                    }}
                  >
                    {d.dishName}
                  </Text>
                  <StarRow value={d.rating} onChange={(v) => updateDishRating(d.dishId, v)} size={36} />
                </View>
              ))}
            </SectionCard>
          )}

          {/* ── 3. Quick tags ─────────────────────────────────────────────── */}
          <SectionCard title="快速标签">
            <View
              style={{
                padding:       '20rpx 32rpx',
                display:       'flex',
                flexDirection: 'row',
                flexWrap:      'wrap',
                gap:           '16rpx',
              }}
            >
              {QUICK_TAGS.map((tag) => {
                const selected = selectedTags.has(tag)
                return (
                  <View
                    key={tag}
                    onClick={() => toggleTag(tag)}
                    style={{
                      background:   selected ? C.primaryDim : C.bgDeep,
                      border:       `2rpx solid ${selected ? C.primary : C.border}`,
                      borderRadius: '32rpx',
                      padding:      '12rpx 28rpx',
                    }}
                  >
                    <Text
                      style={{
                        color:      selected ? C.primary : C.text2,
                        fontSize:   '26rpx',
                        fontWeight: selected ? '600' : '400',
                      }}
                    >
                      {tag}
                    </Text>
                  </View>
                )
              })}
            </View>
          </SectionCard>

          {/* ── 4. Text review ────────────────────────────────────────────── */}
          <SectionCard title="文字评价">
            <View style={{ padding: '16rpx 32rpx 24rpx', position: 'relative' }}>
              <Textarea
                value={reviewText}
                onInput={(e) => setReviewText(String(e.detail.value).slice(0, MAX_TEXT))}
                placeholder="分享您的用餐感受（选填）..."
                placeholderStyle={`color: ${C.text3}; font-size: 26rpx;`}
                maxlength={MAX_TEXT}
                style={{
                  width:        '100%',
                  height:       '200rpx',
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
                  color:     reviewText.length >= MAX_TEXT ? C.red : C.text3,
                  fontSize:  '22rpx',
                  marginTop: '8rpx',
                }}
              >
                {reviewText.length}/{MAX_TEXT}
              </Text>
            </View>
          </SectionCard>

          {/* ── 5. Image upload ───────────────────────────────────────────── */}
          <SectionCard title="上传图片（选填）">
            <View
              style={{
                padding:       '20rpx 32rpx',
                display:       'flex',
                flexDirection: 'row',
                flexWrap:      'wrap',
                gap:           '16rpx',
              }}
            >
              {/* Existing thumbnails */}
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
                  {/* Delete button */}
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
                      ×
                    </Text>
                  </View>
                </View>
              ))}

              {/* Add button */}
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

          {/* ── 6. Anonymous toggle ───────────────────────────────────────── */}
          <SectionCard>
            <View
              style={{
                display:       'flex',
                flexDirection: 'row',
                alignItems:    'center',
                padding:       '24rpx 32rpx',
              }}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500', display: 'block' }}>
                  匿名评价
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                  开启后不显示您的昵称
                </Text>
              </View>
              {/* Toggle switch */}
              <View
                onClick={() => setIsAnonymous((v) => !v)}
                style={{
                  width:          '96rpx',
                  height:         '52rpx',
                  borderRadius:   '26rpx',
                  background:     isAnonymous ? C.primary : C.disabled,
                  position:       'relative',
                  transition:     'background 0.2s',
                  flexShrink:     0,
                }}
              >
                <View
                  style={{
                    position:     'absolute',
                    top:          '6rpx',
                    left:         isAnonymous ? '48rpx' : '6rpx',
                    width:        '40rpx',
                    height:       '40rpx',
                    borderRadius: '50%',
                    background:   C.white,
                    transition:   'left 0.2s',
                    boxShadow:    '0 1rpx 4rpx rgba(0,0,0,0.3)',
                  }}
                />
              </View>
            </View>
          </SectionCard>

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
          padding:        '24rpx 32rpx',
          paddingBottom:  'env(safe-area-inset-bottom)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <View
          onClick={submitting ? undefined : handleSubmit}
          style={{
            height:         '88rpx',
            background:     submitting ? C.disabled : C.primary,
            borderRadius:   '44rpx',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            opacity:        submitting ? 0.7 : 1,
          }}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : '提交评价'}
          </Text>
        </View>
      </View>
    </View>
  )
}
