import { View, Text, ScrollView, Textarea } from '@tarojs/components'
import React, { useState, useEffect, useCallback } from 'react'

// ─── Types ──────────────────────────────────────────────────────────────────

interface SpecOption {
  id: string
  label: string
  price_delta_fen?: number // extra price relative to base
}

interface SpecGroup {
  id: string
  name: string
  options: SpecOption[]
}

interface CustomizeDish {
  id: string
  name: string
  price_fen: number
  image_url?: string
  spec_groups?: SpecGroup[]
}

interface DishCustomizeProps {
  dish: CustomizeDish | null
  visible: boolean
  onClose: () => void
  onConfirm: (specs: Record<string, string>, quantity: number, remark: string) => void
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2)
}

// Default spec groups if dish doesn't supply them
const DEFAULT_SPEC_GROUPS: SpecGroup[] = [
  {
    id: 'size',
    name: '规格',
    options: [
      { id: 'small',  label: '小份' },
      { id: 'medium', label: '中份', price_delta_fen: 200 },
      { id: 'large',  label: '大份', price_delta_fen: 500 },
    ],
  },
  {
    id: 'spice',
    name: '辣度',
    options: [
      { id: 'none',   label: '不辣' },
      { id: 'mild',   label: '微辣' },
      { id: 'medium', label: '中辣' },
      { id: 'hot',    label: '特辣' },
    ],
  },
  {
    id: 'temperature',
    name: '温度',
    options: [
      { id: 'hot',  label: '热' },
      { id: 'warm', label: '温' },
      { id: 'cold', label: '冰' },
    ],
  },
]

// ─── Component ──────────────────────────────────────────────────────────────

const DishCustomize: React.FC<DishCustomizeProps> = ({ dish, visible, onClose, onConfirm }) => {
  const specGroups: SpecGroup[] = dish?.spec_groups?.length
    ? dish.spec_groups
    : DEFAULT_SPEC_GROUPS

  // Default to first option of each group
  const buildDefaultSpecs = useCallback((): Record<string, string> => {
    const map: Record<string, string> = {}
    specGroups.forEach((g) => {
      if (g.options.length > 0) map[g.id] = g.options[0].id
    })
    return map
  }, [specGroups])

  const [selectedSpecs, setSelectedSpecs] = useState<Record<string, string>>(buildDefaultSpecs)
  const [quantity, setQuantity] = useState(1)
  const [remark, setRemark] = useState('')

  // Reset state whenever the sheet opens or dish changes
  useEffect(() => {
    if (visible) {
      setSelectedSpecs(buildDefaultSpecs())
      setQuantity(1)
      setRemark('')
    }
  }, [visible, dish?.id, buildDefaultSpecs])

  // ── Price calculation ──────────────────────────────────────────────────────

  const extraFen = specGroups.reduce((acc, group) => {
    const chosen = selectedSpecs[group.id]
    const option = group.options.find((o) => o.id === chosen)
    return acc + (option?.price_delta_fen ?? 0)
  }, 0)

  const unitPrice = (dish?.price_fen ?? 0) + extraFen
  const totalFen  = unitPrice * quantity

  // ── Handlers ──────────────────────────────────────────────────────────────

  function handleSelectSpec(groupId: string, optionId: string) {
    setSelectedSpecs((prev) => ({ ...prev, [groupId]: optionId }))
  }

  function handleConfirm() {
    onConfirm(selectedSpecs, quantity, remark)
    onClose()
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (!dish) return null

  return (
    <>
      {/* Backdrop */}
      <View
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.55)',
          zIndex: 1000,
          opacity: visible ? 1 : 0,
          pointerEvents: visible ? 'auto' : 'none',
          transition: 'opacity 0.25s ease',
        }}
        onClick={onClose}
      />

      {/* Bottom sheet */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 1001,
          background: '#132029',
          borderRadius: '32rpx 32rpx 0 0',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s cubic-bezier(0.32, 0.72, 0, 1)',
          maxHeight: '88vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Drag handle */}
        <View
          style={{
            display: 'flex',
            justifyContent: 'center',
            padding: '16rpx 0 8rpx',
          }}
        >
          <View
            style={{
              width: '80rpx',
              height: '8rpx',
              background: '#2A4050',
              borderRadius: '4rpx',
            }}
          />
        </View>

        {/* Dish title row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16rpx 32rpx 24rpx',
          }}
        >
          <Text
            style={{
              color: '#E8F4F8',
              fontSize: '36rpx',
              fontWeight: '700',
            }}
          >
            {dish.name}
          </Text>
          <View
            style={{
              width: '64rpx',
              height: '64rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: '88rpx',
              minHeight: '88rpx',
            }}
            onClick={onClose}
          >
            <Text style={{ color: '#9EB5C0', fontSize: '40rpx' }}>×</Text>
          </View>
        </View>

        {/* Scrollable spec content */}
        <ScrollView
          scrollY
          style={{ flex: 1, overflow: 'hidden' }}
        >
          <View style={{ padding: '0 32rpx 24rpx' }}>

            {/* Spec groups */}
            {specGroups.map((group) => (
              <View key={group.id} style={{ marginBottom: '32rpx' }}>
                <Text
                  style={{
                    color: '#9EB5C0',
                    fontSize: '26rpx',
                    fontWeight: '600',
                    marginBottom: '16rpx',
                    display: 'block',
                  }}
                >
                  {group.name}
                </Text>
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    flexWrap: 'wrap',
                    gap: '16rpx',
                  }}
                >
                  {group.options.map((opt) => {
                    const isSelected = selectedSpecs[group.id] === opt.id
                    return (
                      <View
                        key={opt.id}
                        style={{
                          minWidth: '120rpx',
                          minHeight: '72rpx',
                          padding: '12rpx 24rpx',
                          borderRadius: '12rpx',
                          border: isSelected ? '2rpx solid #FF6B35' : '2rpx solid #2A4050',
                          background: isSelected ? 'rgba(255,107,53,0.12)' : '#0B1A20',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                        onClick={() => handleSelectSpec(group.id, opt.id)}
                      >
                        <Text
                          style={{
                            color: isSelected ? '#FF6B35' : '#C8DDE6',
                            fontSize: '26rpx',
                            fontWeight: isSelected ? '600' : '400',
                          }}
                        >
                          {opt.label}
                        </Text>
                        {opt.price_delta_fen != null && opt.price_delta_fen !== 0 && (
                          <Text
                            style={{
                              color: isSelected ? '#FF6B35' : '#6B8A96',
                              fontSize: '20rpx',
                              marginTop: '4rpx',
                            }}
                          >
                            +{fenToYuan(opt.price_delta_fen)}
                          </Text>
                        )}
                      </View>
                    )
                  })}
                </View>
              </View>
            ))}

            {/* Quantity stepper */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '32rpx',
              }}
            >
              <Text style={{ color: '#9EB5C0', fontSize: '26rpx', fontWeight: '600' }}>数量</Text>
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: '24rpx',
                }}
              >
                <View
                  style={{
                    width: '64rpx',
                    height: '64rpx',
                    borderRadius: '32rpx',
                    border: quantity > 1 ? '2rpx solid #FF6B35' : '2rpx solid #2A4050',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minWidth: '88rpx',
                    minHeight: '88rpx',
                    opacity: quantity <= 1 ? 0.4 : 1,
                  }}
                  onClick={() => quantity > 1 && setQuantity((q) => q - 1)}
                >
                  <Text style={{ color: '#FF6B35', fontSize: '36rpx', lineHeight: '1' }}>−</Text>
                </View>
                <Text style={{ color: '#E8F4F8', fontSize: '32rpx', fontWeight: '600', minWidth: '48rpx', textAlign: 'center' }}>
                  {quantity}
                </Text>
                <View
                  style={{
                    width: '64rpx',
                    height: '64rpx',
                    borderRadius: '32rpx',
                    background: '#FF6B35',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minWidth: '88rpx',
                    minHeight: '88rpx',
                  }}
                  onClick={() => setQuantity((q) => q + 1)}
                >
                  <Text style={{ color: '#fff', fontSize: '36rpx', lineHeight: '1' }}>+</Text>
                </View>
              </View>
            </View>

            {/* Remark input */}
            <View>
              <Text
                style={{
                  color: '#9EB5C0',
                  fontSize: '26rpx',
                  fontWeight: '600',
                  marginBottom: '12rpx',
                  display: 'block',
                }}
              >
                备注
              </Text>
              <Textarea
                value={remark}
                onInput={(e) => setRemark(e.detail.value)}
                maxlength={50}
                placeholder='口味偏好、忌口等...'
                placeholderStyle='color: #4A6878; font-size: 26rpx;'
                style={{
                  width: '100%',
                  minHeight: '120rpx',
                  background: '#0B1A20',
                  borderRadius: '12rpx',
                  padding: '20rpx',
                  color: '#E8F4F8',
                  fontSize: '26rpx',
                  lineHeight: '40rpx',
                  border: '2rpx solid #2A4050',
                  boxSizing: 'border-box',
                }}
                autoHeight
              />
              <Text
                style={{
                  color: '#4A6878',
                  fontSize: '22rpx',
                  marginTop: '8rpx',
                  display: 'block',
                  textAlign: 'right',
                }}
              >
                {remark.length}/50
              </Text>
            </View>
          </View>
        </ScrollView>

        {/* Bottom confirm bar */}
        <View
          style={{
            padding: '16rpx 32rpx',
            background: '#132029',
            borderTop: '1rpx solid #1E3040',
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingBottom: 'calc(16rpx + env(safe-area-inset-bottom))',
          }}
        >
          <View>
            <Text style={{ color: '#9EB5C0', fontSize: '24rpx' }}>合计</Text>
            <Text
              style={{
                color: '#FF6B35',
                fontSize: '40rpx',
                fontWeight: '700',
                marginLeft: '8rpx',
              }}
            >
              {fenToYuan(totalFen)}
            </Text>
          </View>
          <View
            style={{
              background: '#FF6B35',
              borderRadius: '48rpx',
              padding: '0 56rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: '240rpx',
            }}
            onClick={handleConfirm}
          >
            <Text style={{ color: '#fff', fontSize: '32rpx', fontWeight: '700' }}>加入购物车</Text>
          </View>
        </View>
      </View>
    </>
  )
}

export default DishCustomize
