/**
 * PaymentSheet — bottom-sheet payment method selector
 *
 * Three modes:
 *  1. 微信支付       — always available
 *  2. 储值卡支付     — disabled when balance < total
 *  3. 混合支付       — only shown when 0 < balance < total
 *
 * All amounts are in fen (整数分). Display via fenToYuanDisplay.
 */
import { View, Text } from '@tarojs/components'
import React, { useState, useEffect, useCallback } from 'react'
import { fenToYuanDisplay } from '../../utils/format'

// ─── Types ────────────────────────────────────────────────────────────────────

type PaymentMethod = 'wechat' | 'stored_value' | 'mixed'

export interface PaymentSheetProps {
  visible: boolean
  totalFen: number
  storedValueFen: number
  onClose: () => void
  onConfirm: (method: PaymentMethod, mixedStoredFen?: number) => void
}

// ─── Internal option descriptor ───────────────────────────────────────────────

interface PayOption {
  method: PaymentMethod
  title: string
  subtitle: string
  badge?: string
  disabled: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Clamp number to [min, max] */
const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))

// ─── Component ────────────────────────────────────────────────────────────────

const PaymentSheet: React.FC<PaymentSheetProps> = ({
  visible,
  totalFen,
  storedValueFen,
  onClose,
  onConfirm,
}) => {
  // Slide-up animation state: 0 = hidden, 1 = visible
  const [translateY, setTranslateY] = useState(100)
  const [rendered, setRendered] = useState(false)

  useEffect(() => {
    if (visible) {
      setRendered(true)
      // Trigger slide-up on next paint
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setTranslateY(0))
      })
    } else {
      setTranslateY(100)
      const timer = setTimeout(() => setRendered(false), 320)
      return () => clearTimeout(timer)
    }
  }, [visible])

  // Derive which options are relevant
  const canPayFull = storedValueFen >= totalFen
  const canMixed = storedValueFen > 0 && storedValueFen < totalFen
  const wechatOnlyDelta = canMixed ? totalFen - storedValueFen : totalFen

  const options: PayOption[] = [
    {
      method: 'wechat',
      title: '微信支付',
      subtitle: fenToYuanDisplay(totalFen),
      disabled: false,
    },
    {
      method: 'stored_value',
      title: '储值卡支付',
      subtitle: `余额 ${fenToYuanDisplay(storedValueFen)}`,
      badge: canPayFull ? undefined : '余额不足',
      disabled: !canPayFull,
    },
    ...(canMixed
      ? [
          {
            method: 'mixed' as PaymentMethod,
            title: '混合支付',
            subtitle: `储值卡 ${fenToYuanDisplay(storedValueFen)} + 微信支付 ${fenToYuanDisplay(wechatOnlyDelta)}`,
            disabled: false,
          },
        ]
      : []),
  ]

  const defaultMethod: PaymentMethod = canMixed ? 'mixed' : canPayFull ? 'stored_value' : 'wechat'
  const [selected, setSelected] = useState<PaymentMethod>(defaultMethod)

  // Re-derive default when props change (e.g. balance updated)
  useEffect(() => {
    const dm: PaymentMethod = canMixed ? 'mixed' : canPayFull ? 'stored_value' : 'wechat'
    setSelected(dm)
  }, [storedValueFen, totalFen, canMixed, canPayFull])

  const handleConfirm = useCallback(() => {
    const mixedFen = selected === 'mixed' ? clamp(storedValueFen, 0, totalFen) : undefined
    onConfirm(selected, mixedFen)
  }, [selected, storedValueFen, totalFen, onConfirm])

  if (!rendered) return null

  return (
    <>
      {/* Backdrop */}
      <View
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.6)',
          zIndex: 800,
          opacity: translateY === 0 ? 1 : 0,
          transition: 'opacity 0.3s ease',
        }}
        onClick={onClose}
      />

      {/* Sheet */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 801,
          background: '#132029',
          borderRadius: '32rpx 32rpx 0 0',
          paddingBottom: 'env(safe-area-inset-bottom)',
          transform: `translateY(${translateY}%)`,
          transition: 'transform 0.32s cubic-bezier(0.32,0.72,0,1)',
          boxShadow: '0 -8rpx 40rpx rgba(0,0,0,0.4)',
        }}
      >
        {/* Handle bar */}
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: '20rpx',
            paddingBottom: '8rpx',
          }}
        >
          <View
            style={{
              width: '80rpx',
              height: '8rpx',
              borderRadius: '4rpx',
              background: '#2A4558',
            }}
          />
        </View>

        {/* Header */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '24rpx 32rpx 32rpx',
          }}
        >
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '36rpx',
              fontWeight: '700',
            }}
          >
            选择支付方式
          </Text>
          <View
            style={{
              width: '64rpx',
              height: '64rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={onClose}
          >
            <Text style={{ color: '#9EB5C0', fontSize: '40rpx', lineHeight: '1' }}>×</Text>
          </View>
        </View>

        {/* Payment option cards */}
        <View style={{ padding: '0 32rpx', display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
          {options.map((opt) => {
            const isSelected = selected === opt.method
            const isDisabled = opt.disabled

            return (
              <View
                key={opt.method}
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  background: isSelected ? 'rgba(255,107,53,0.12)' : '#1A2E38',
                  border: `2rpx solid ${isSelected ? '#FF6B35' : '#1E3340'}`,
                  borderRadius: '24rpx',
                  padding: '28rpx 32rpx',
                  minHeight: '96rpx',
                  opacity: isDisabled ? 0.45 : 1,
                  transition: 'border 0.2s, background 0.2s',
                }}
                onClick={() => {
                  if (!isDisabled) setSelected(opt.method)
                }}
              >
                {/* Icon area */}
                <View
                  style={{
                    width: '72rpx',
                    height: '72rpx',
                    borderRadius: '16rpx',
                    background: opt.method === 'wechat' ? '#07C160' : '#FF6B35',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    marginRight: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '38rpx', lineHeight: '1' }}>
                    {opt.method === 'wechat' ? '💬' : opt.method === 'stored_value' ? '💳' : '🔀'}
                  </Text>
                </View>

                {/* Text block */}
                <View style={{ flex: 1 }}>
                  <View
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: '12rpx',
                      marginBottom: '6rpx',
                    }}
                  >
                    <Text
                      style={{
                        color: '#FFFFFF',
                        fontSize: '32rpx',
                        fontWeight: '600',
                      }}
                    >
                      {opt.title}
                    </Text>
                    {opt.badge && (
                      <View
                        style={{
                          background: 'rgba(255,59,48,0.2)',
                          borderRadius: '8rpx',
                          padding: '2rpx 10rpx',
                        }}
                      >
                        <Text
                          style={{
                            color: '#FF3B30',
                            fontSize: '22rpx',
                            fontWeight: '600',
                          }}
                        >
                          {opt.badge}
                        </Text>
                      </View>
                    )}
                  </View>
                  <Text
                    style={{
                      color: '#9EB5C0',
                      fontSize: '26rpx',
                    }}
                  >
                    {opt.subtitle}
                  </Text>
                </View>

                {/* Radio circle */}
                <View
                  style={{
                    width: '44rpx',
                    height: '44rpx',
                    borderRadius: '22rpx',
                    border: `3rpx solid ${isSelected ? '#FF6B35' : '#2A4558'}`,
                    background: isSelected ? '#FF6B35' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    transition: 'background 0.2s, border 0.2s',
                  }}
                >
                  {isSelected && (
                    <Text
                      style={{
                        color: '#FFFFFF',
                        fontSize: '26rpx',
                        fontWeight: '700',
                        lineHeight: '1',
                      }}
                    >
                      ✓
                    </Text>
                  )}
                </View>
              </View>
            )
          })}
        </View>

        {/* Confirm button */}
        <View style={{ padding: '32rpx 32rpx 16rpx' }}>
          <View
            style={{
              background: '#FF6B35',
              borderRadius: '44rpx',
              height: '96rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4rpx 24rpx rgba(255,107,53,0.35)',
            }}
            onClick={handleConfirm}
          >
            <Text
              style={{
                color: '#FFFFFF',
                fontSize: '36rpx',
                fontWeight: '700',
              }}
            >
              确认支付 {fenToYuanDisplay(totalFen)}
            </Text>
          </View>
        </View>
      </View>
    </>
  )
}

export default PaymentSheet
