import { View, Text, Image } from '@tarojs/components'
import React from 'react'

export interface DishCardDish {
  id: string
  name: string
  price_fen: number
  image_url?: string
  tag?: string
  sold_out?: boolean
  description?: string
}

export interface DishCardStyleConfig {
  variant?: 'default' | 'elegant' | 'compact' | 'large-image'
  show_tag?: boolean
  show_description?: boolean
  price_color?: string
  background_color?: string
  border_radius?: string
}

interface DishCardProps {
  dish: DishCardDish
  quantity: number
  onAdd: () => void
  onRemove: () => void
  onTap?: () => void
  /** Optional theme-driven style overrides */
  themeStyle?: DishCardStyleConfig
}

const TAG_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  new:       { bg: '#FF6B35', color: '#fff',    label: '新品' },
  hot:       { bg: '#E53935', color: '#fff',    label: '热销' },
  recommend: { bg: '#FFD700', color: '#0B1A20', label: '推荐' },
}

/** Format fen → "¥XX.XX" */
function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2)
}

/**
 * Resolve card style from theme config with defaults fallback.
 * Uses CSS variables for dynamic brand colors when themeStyle is not provided.
 */
function resolveStyles(style?: DishCardStyleConfig) {
  const variant = style?.variant ?? 'default'
  const showTag = style?.show_tag ?? true
  const showDescription = style?.show_description ?? true
  const priceColor = style?.price_color ?? 'var(--tx-dish-price, #FF6B35)'
  const bgColor = style?.background_color ?? 'var(--tx-dish-card-bg, #132029)'
  const borderRadius = style?.border_radius ?? 'var(--tx-dish-card-radius, 16rpx)'
  return { variant, showTag, showDescription, priceColor, bgColor, borderRadius }
}

const DishCard: React.FC<DishCardProps> = ({ dish, quantity, onAdd, onRemove, onTap, themeStyle }) => {
  const tagInfo = dish.tag ? TAG_STYLES[dish.tag] ?? null : null
  const style = resolveStyles(themeStyle)
  const isVertical = style.variant === 'compact' || style.variant === 'large-image'

  // ── Variant: compact (vertical card for grid layout) ──────────────────
  if (isVertical) {
    return (
      <View
        style={{
          display: 'flex',
          flexDirection: 'column',
          background: style.bgColor,
          borderRadius: style.borderRadius,
          overflow: 'hidden',
          marginBottom: '16rpx',
          position: 'relative',
        }}
        onClick={onTap}
      >
        {/* Image area */}
        <View
          style={{
            width: '100%',
            height: style.variant === 'large-image' ? '280rpx' : '200rpx',
            background: 'var(--tx-page-bg, #0B1A20)',
            position: 'relative',
          }}
        >
          {dish.image_url ? (
            <Image
              src={dish.image_url}
              style={{ width: '100%', height: '100%', display: 'block' }}
              mode='aspectFill'
            />
          ) : (
            <View
              style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ fontSize: '48rpx' }}>🍽</Text>
            </View>
          )}

          {/* Tag badge */}
          {style.showTag && tagInfo && (
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
                width: '100%',
                height: '100%',
                background: 'rgba(11,26,32,0.72)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text
                style={{
                  color: 'var(--tx-text-secondary, #9EB5C0)',
                  fontSize: '24rpx',
                  fontWeight: '600',
                  border: '2rpx solid var(--tx-text-secondary, #9EB5C0)',
                  borderRadius: '8rpx',
                  padding: '4rpx 12rpx',
                }}
              >
                已售罄
              </Text>
            </View>
          )}
        </View>

        {/* Info */}
        <View style={{ padding: '16rpx' }}>
          <Text
            style={{
              color: 'var(--tx-text-primary, #E8F4F8)',
              fontSize: '28rpx',
              fontWeight: '600',
            }}
            numberOfLines={1}
          >
            {dish.name}
          </Text>

          {style.showDescription && dish.description && (
            <Text
              style={{
                color: 'var(--tx-text-secondary, #9EB5C0)',
                fontSize: '22rpx',
                lineHeight: '32rpx',
                marginTop: '6rpx',
              }}
              numberOfLines={1}
            >
              {dish.description}
            </Text>
          )}

          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginTop: '12rpx',
            }}
          >
            <Text style={{ color: style.priceColor, fontSize: '30rpx', fontWeight: '700' }}>
              {fenToYuan(dish.price_fen)}
            </Text>

            {!dish.sold_out && (
              <View
                style={{
                  background: style.priceColor,
                  borderRadius: '50%',
                  width: '56rpx',
                  height: '56rpx',
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
            )}
          </View>
        </View>
      </View>
    )
  }

  // ── Variant: elegant (refined horizontal card) ────────────────────────
  if (style.variant === 'elegant') {
    return (
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          background: style.bgColor,
          borderRadius: style.borderRadius,
          padding: '16rpx',
          marginBottom: '16rpx',
          position: 'relative',
          overflow: 'hidden',
          border: '1rpx solid rgba(255,255,255,0.04)',
        }}
        onClick={onTap}
      >
        {/* Dish image */}
        <View
          style={{
            width: '180rpx',
            height: '180rpx',
            borderRadius: '12rpx',
            overflow: 'hidden',
            flexShrink: 0,
            background: 'var(--tx-page-bg, #0B1A20)',
            position: 'relative',
          }}
        >
          {dish.image_url ? (
            <Image
              src={dish.image_url}
              style={{ width: '180rpx', height: '180rpx', display: 'block' }}
              mode='aspectFill'
            />
          ) : (
            <View
              style={{
                width: '180rpx', height: '180rpx',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <Text style={{ fontSize: '48rpx' }}>🍽</Text>
            </View>
          )}

          {style.showTag && tagInfo && (
            <View
              style={{
                position: 'absolute', top: '8rpx', left: '8rpx',
                background: tagInfo.bg, borderRadius: '8rpx', padding: '4rpx 10rpx',
              }}
            >
              <Text style={{ color: tagInfo.color, fontSize: '20rpx', fontWeight: '600' }}>
                {tagInfo.label}
              </Text>
            </View>
          )}

          {dish.sold_out && (
            <View
              style={{
                position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                background: 'rgba(11,26,32,0.72)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <Text style={{ color: 'var(--tx-text-secondary, #9EB5C0)', fontSize: '24rpx', fontWeight: '600', border: '2rpx solid var(--tx-text-secondary, #9EB5C0)', borderRadius: '8rpx', padding: '4rpx 12rpx' }}>
                已售罄
              </Text>
            </View>
          )}
        </View>

        <View style={{ flex: 1, marginLeft: '20rpx', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '180rpx' }}>
          <Text style={{ color: 'var(--tx-text-primary, #E8F4F8)', fontSize: '30rpx', fontWeight: '600' }} numberOfLines={2}>
            {dish.name}
          </Text>

          {style.showDescription && dish.description && (
            <Text style={{ color: 'var(--tx-text-secondary, #9EB5C0)', fontSize: '22rpx', lineHeight: '32rpx' }} numberOfLines={2}>
              {dish.description}
            </Text>
          )}

          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 'auto' }}>
            <Text style={{ color: style.priceColor, fontSize: '32rpx', fontWeight: '700' }}>
              {fenToYuan(dish.price_fen)}
            </Text>

            {!dish.sold_out && (
              <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
                {quantity > 0 && (
                  <>
                    <View
                      style={{
                        width: '56rpx', height: '56rpx', borderRadius: '28rpx',
                        border: `2rpx solid ${style.priceColor}`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        minWidth: '88rpx', minHeight: '88rpx',
                      }}
                      onClick={onRemove}
                    >
                      <Text style={{ color: style.priceColor, fontSize: '32rpx', lineHeight: '1' }}>−</Text>
                    </View>
                    <Text style={{ color: 'var(--tx-text-primary, #E8F4F8)', fontSize: '28rpx', fontWeight: '600', minWidth: '40rpx', textAlign: 'center' }}>
                      {quantity}
                    </Text>
                  </>
                )}
                <View
                  style={{
                    width: '56rpx', height: '56rpx', borderRadius: '28rpx',
                    background: style.priceColor,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    minWidth: '88rpx', minHeight: '88rpx',
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

  // ── Variant: default (original horizontal card with CSS variable colors) ─
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        background: style.bgColor,
        borderRadius: style.borderRadius,
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
          background: 'var(--tx-page-bg, #0B1A20)',
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
        {style.showTag && tagInfo && (
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
                color: 'var(--tx-text-secondary, #9EB5C0)',
                fontSize: '24rpx',
                fontWeight: '600',
                border: '2rpx solid var(--tx-text-secondary, #9EB5C0)',
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
            color: 'var(--tx-text-primary, #E8F4F8)',
            fontSize: '30rpx',
            fontWeight: '600',
            lineHeight: '40rpx',
          }}
          numberOfLines={2}
        >
          {dish.name}
        </Text>

        {/* Description */}
        {style.showDescription && dish.description && (
          <Text
            style={{
              color: 'var(--tx-text-secondary, #9EB5C0)',
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
              color: style.priceColor,
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
                      border: `2rpx solid ${style.priceColor}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      minWidth: '88rpx',
                      minHeight: '88rpx',
                    }}
                    onClick={onRemove}
                  >
                    <Text style={{ color: style.priceColor, fontSize: '32rpx', lineHeight: '1' }}>−</Text>
                  </View>
                  <Text
                    style={{
                      color: 'var(--tx-text-primary, #E8F4F8)',
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
                  background: style.priceColor,
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
