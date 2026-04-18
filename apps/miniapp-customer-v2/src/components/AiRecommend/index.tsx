import { View, Text, Image, ScrollView } from '@tarojs/components'
import React from 'react'

// ─── Types ──────────────────────────────────────────────────────────────────

interface AiRecommendItem {
  dish_id: string
  name: string
  reason: string
  price_fen: number
  image_url?: string
}

interface AiRecommendProps {
  recommendations: AiRecommendItem[]
  onAdd: (dishId: string) => void
  loading?: boolean
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2)
}

// ─── Skeleton card ───────────────────────────────────────────────────────────

const SkeletonCard: React.FC = () => (
  <View
    style={{
      width: '280rpx',
      borderRadius: '20rpx',
      background: '#132029',
      overflow: 'hidden',
      flexShrink: 0,
      marginRight: '16rpx',
    }}
  >
    {/* Image placeholder */}
    <View
      style={{
        width: '280rpx',
        height: '200rpx',
        background: 'linear-gradient(90deg, #1A2E38 25%, #1E3545 50%, #1A2E38 75%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.4s infinite',
      }}
    />
    <View style={{ padding: '16rpx' }}>
      {/* Name skeleton */}
      <View
        style={{
          height: '28rpx',
          width: '60%',
          background: '#1E3545',
          borderRadius: '8rpx',
          marginBottom: '12rpx',
        }}
      />
      {/* Reason skeleton */}
      <View
        style={{
          height: '22rpx',
          width: '90%',
          background: '#1A2E38',
          borderRadius: '8rpx',
          marginBottom: '6rpx',
        }}
      />
      <View
        style={{
          height: '22rpx',
          width: '70%',
          background: '#1A2E38',
          borderRadius: '8rpx',
          marginBottom: '16rpx',
        }}
      />
      {/* Price + button skeleton */}
      <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <View style={{ height: '32rpx', width: '30%', background: '#1E3545', borderRadius: '8rpx' }} />
        <View style={{ height: '56rpx', width: '80rpx', background: '#1E3545', borderRadius: '28rpx' }} />
      </View>
    </View>
  </View>
)

// ─── Recommendation card ─────────────────────────────────────────────────────

interface RecommendCardProps {
  item: AiRecommendItem
  onAdd: () => void
}

const RecommendCard: React.FC<RecommendCardProps> = ({ item, onAdd }) => (
  <View
    style={{
      width: '280rpx',
      borderRadius: '20rpx',
      background: '#132029',
      overflow: 'hidden',
      flexShrink: 0,
      marginRight: '16rpx',
      border: '1rpx solid #1E3040',
    }}
  >
    {/* Dish image */}
    <View
      style={{
        width: '280rpx',
        height: '200rpx',
        background: '#0B1A20',
        overflow: 'hidden',
      }}
    >
      {item.image_url ? (
        <Image
          src={item.image_url}
          style={{ width: '280rpx', height: '200rpx', display: 'block' }}
          mode='aspectFill'
        />
      ) : (
        <View
          style={{
            width: '280rpx',
            height: '200rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ fontSize: '64rpx' }}>🍽</Text>
        </View>
      )}
    </View>

    {/* Card body */}
    <View style={{ padding: '16rpx 20rpx' }}>
      {/* Dish name */}
      <Text
        style={{
          color: '#E8F4F8',
          fontSize: '28rpx',
          fontWeight: '600',
          lineHeight: '40rpx',
          display: 'block',
          marginBottom: '8rpx',
        }}
        numberOfLines={1}
      >
        {item.name}
      </Text>

      {/* AI reason — italic, muted teal */}
      <Text
        style={{
          color: '#9EB5C0',
          fontSize: '22rpx',
          fontStyle: 'italic',
          lineHeight: '34rpx',
          display: 'block',
          marginBottom: '16rpx',
        }}
        numberOfLines={2}
      >
        {item.reason}
      </Text>

      {/* Price + add button */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Text
          style={{
            color: '#FF6B35',
            fontSize: '30rpx',
            fontWeight: '700',
          }}
        >
          {fenToYuan(item.price_fen)}
        </Text>
        <View
          style={{
            background: '#FF6B35',
            borderRadius: '28rpx',
            width: '64rpx',
            height: '64rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: '88rpx',
            minHeight: '88rpx',
          }}
          onClick={(e) => { e.stopPropagation(); onAdd() }}
        >
          <Text style={{ color: '#fff', fontSize: '36rpx', lineHeight: '1' }}>+</Text>
        </View>
      </View>
    </View>
  </View>
)

// ─── Main component ──────────────────────────────────────────────────────────

const AiRecommend: React.FC<AiRecommendProps> = ({ recommendations, onAdd, loading = false }) => {
  // Don't render when no data and not loading
  if (!loading && recommendations.length === 0) return null

  return (
    <View
      style={{
        background: '#0D1E27',
        borderRadius: '24rpx',
        padding: '24rpx 0 24rpx 24rpx',
        marginBottom: '16rpx',
        border: '1rpx solid rgba(255,107,53,0.15)',
      }}
    >
      {/* Header */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          marginBottom: '20rpx',
          paddingRight: '24rpx',
        }}
      >
        <Text style={{ fontSize: '28rpx', marginRight: '8rpx' }}>✨</Text>
        <Text
          style={{
            color: '#E8F4F8',
            fontSize: '30rpx',
            fontWeight: '700',
          }}
        >
          AI为你推荐
        </Text>
        <View
          style={{
            marginLeft: '12rpx',
            background: 'rgba(255,107,53,0.15)',
            borderRadius: '8rpx',
            padding: '4rpx 12rpx',
          }}
        >
          <Text style={{ color: '#FF6B35', fontSize: '20rpx', fontWeight: '600' }}>
            {loading ? '分析中...' : `${recommendations.length}道好菜`}
          </Text>
        </View>
      </View>

      {/* Horizontal scroll strip */}
      <ScrollView
        scrollX
        style={{ whiteSpace: 'nowrap' }}
        showsHorizontalScrollIndicator={false}
      >
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'stretch',
            paddingRight: '24rpx',
          }}
        >
          {loading
            ? Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)
            : recommendations.map((item) => (
                <RecommendCard
                  key={item.dish_id}
                  item={item}
                  onAdd={() => onAdd(item.dish_id)}
                />
              ))}
        </View>
      </ScrollView>
    </View>
  )
}

export default AiRecommend
