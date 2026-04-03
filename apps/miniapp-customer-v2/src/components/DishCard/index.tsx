import { View, Text, Image } from '@tarojs/components'
import React from 'react'

interface DishCardDish {
  id: string
  name: string
  price_fen: number
  image_url?: string
  tag?: string
  sold_out?: boolean
  description?: string
}

interface DishCardProps {
  dish: DishCardDish
  quantity: number
  onAdd: () => void
  onRemove: () => void
  onTap?: () => void
}

const TAG_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  new:       { bg: '#FF6B2C', color: '#fff',    label: '新品' },
  hot:       { bg: '#E53935', color: '#fff',    label: '热销' },
  recommend: { bg: '#FFD700', color: '#0B1A20', label: '推荐' },
}

/** Format fen → "¥XX.XX" */
function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2)
}

const DishCard: React.FC<DishCardProps> = ({ dish, quantity, onAdd, onRemove, onTap }) => {
  const tagInfo = dish.tag ? TAG_STYLES[dish.tag] ?? null : null

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        background: '#132029',
        borderRadius: '16rpx',
        padding: '20rpx',
        marginBottom: '16rpx',
        position: 'relative',
        overflow: 'hidden',
      }}
      onClick={onTap}
    >
      {/* Dish image */}
      <View
        style={{
          width: '160rpx',
          height: '160rpx',
          borderRadius: '12rpx',
          overflow: 'hidden',
          flexShrink: 0,
          background: '#0B1A20',
          position: 'relative',
        }}
      >
        {dish.image_url ? (
          <Image
            src={dish.image_url}
            style={{ width: '160rpx', height: '160rpx', display: 'block' }}
            mode='aspectFill'
          />
        ) : (
          <View
            style={{
              width: '160rpx',
              height: '160rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text style={{ fontSize: '48rpx' }}>🍽</Text>
          </View>
        )}

        {/* Tag badge on image */}
        {tagInfo && (
          <View
            style={{
              position: 'absolute',
              top: '8rpx',
              left: '8rpx',
              background: tagInfo.bg,
              borderRadius: '8rpx',
              padding: '4rpx 10rpx',
            }}
          >
            <Text style={{ color: tagInfo.color, fontSize: '20rpx', fontWeight: '600' }}>
              {tagInfo.label}
            </Text>
          </View>
        )}

        {/* Sold-out overlay */}
        {dish.sold_out && (
          <View
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '160rpx',
              height: '160rpx',
              background: 'rgba(11,26,32,0.72)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '12rpx',
            }}
          >
            <Text
              style={{
                color: '#9EB5C0',
                fontSize: '24rpx',
                fontWeight: '600',
                border: '2rpx solid #9EB5C0',
                borderRadius: '8rpx',
                padding: '4rpx 12rpx',
              }}
            >
              已售罄
            </Text>
          </View>
        )}
      </View>

      {/* Info area */}
      <View
        style={{
          flex: 1,
          marginLeft: '20rpx',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          height: '160rpx',
        }}
      >
        {/* Name */}
        <Text
          style={{
            color: '#E8F4F8',
            fontSize: '30rpx',
            fontWeight: '600',
            lineHeight: '40rpx',
          }}
          numberOfLines={2}
        >
          {dish.name}
        </Text>

        {/* Description */}
        {dish.description && (
          <Text
            style={{
              color: '#9EB5C0',
              fontSize: '22rpx',
              lineHeight: '32rpx',
              marginTop: '6rpx',
            }}
            numberOfLines={2}
          >
            {dish.description}
          </Text>
        )}

        {/* Price + counter */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginTop: 'auto',
          }}
        >
          <Text
            style={{
              color: '#FF6B2C',
              fontSize: '32rpx',
              fontWeight: '700',
            }}
          >
            {fenToYuan(dish.price_fen)}
          </Text>

          {/* +/- counter */}
          {!dish.sold_out && (
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: '0rpx',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {quantity > 0 && (
                <>
                  <View
                    style={{
                      width: '56rpx',
                      height: '56rpx',
                      borderRadius: '28rpx',
                      border: '2rpx solid #FF6B2C',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      minWidth: '88rpx',
                      minHeight: '88rpx',
                    }}
                    onClick={onRemove}
                  >
                    <Text style={{ color: '#FF6B2C', fontSize: '32rpx', lineHeight: '1' }}>−</Text>
                  </View>
                  <Text
                    style={{
                      color: '#E8F4F8',
                      fontSize: '28rpx',
                      fontWeight: '600',
                      minWidth: '40rpx',
                      textAlign: 'center',
                    }}
                  >
                    {quantity}
                  </Text>
                </>
              )}
              <View
                style={{
                  width: '56rpx',
                  height: '56rpx',
                  borderRadius: '28rpx',
                  background: '#FF6B2C',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minWidth: '88rpx',
                  minHeight: '88rpx',
                }}
                onClick={onAdd}
              >
                <Text style={{ color: '#fff', fontSize: '32rpx', lineHeight: '1' }}>+</Text>
              </View>
            </View>
          )}
        </View>
      </View>
    </View>
  )
}

export default DishCard
