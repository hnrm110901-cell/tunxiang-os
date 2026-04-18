/**
 * QueueTicket — queuing status card
 *
 * States:
 *  waiting  — normal display, countdown, "放弃排号" button
 *  called   — green pulsing ticket number, "请立即入座！" message
 *  expired  — full grey-out, ticket invalid
 */
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import React, { useEffect, useRef, useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

export type QueueStatus = 'waiting' | 'called' | 'expired'

export interface QueueTicketProps {
  ticketNo: string
  queueAhead: number
  estimatedWait: number
  status: QueueStatus
  onGiveUp?: () => void
}

// ─── Pulse animation hook ─────────────────────────────────────────────────────

/** Returns an oscillating opacity value (0.6 → 1 → 0.6) when active */
function usePulse(active: boolean): number {
  const [opacity, setOpacity] = useState(1)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef<number>(0)

  useEffect(() => {
    if (!active) {
      setOpacity(1)
      return
    }

    const animate = (ts: number) => {
      if (!startRef.current) startRef.current = ts
      const elapsed = (ts - startRef.current) % 1500
      // Sine oscillation: 0 → 1 → 0 over 1500 ms, mapped to 0.6 → 1
      const sin = Math.sin((elapsed / 1500) * Math.PI * 2)
      setOpacity(0.7 + 0.3 * ((sin + 1) / 2))
      rafRef.current = requestAnimationFrame(animate)
    }

    rafRef.current = requestAnimationFrame(animate)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [active])

  return opacity
}

// ─── Component ────────────────────────────────────────────────────────────────

const QueueTicket: React.FC<QueueTicketProps> = ({
  ticketNo,
  queueAhead,
  estimatedWait,
  status,
  onGiveUp,
}) => {
  const isCalled = status === 'called'
  const isExpired = status === 'expired'
  const isWaiting = status === 'waiting'

  const pulseOpacity = usePulse(isCalled)

  // Colour configuration per status
  const ticketColor = isCalled ? '#34C759' : isExpired ? '#3A4E5A' : '#FF6B35'
  const cardBg = isExpired ? '#0F1C24' : '#132029'
  const overallOpacity = isExpired ? 0.6 : 1

  const handleGiveUp = () => {
    Taro.showModal({
      title: '确认放弃排号',
      content: `放弃后将失去当前排号 ${ticketNo}，需重新排队。`,
      confirmText: '确认放弃',
      cancelText: '我再想想',
      confirmColor: '#FF3B30',
      success: (res) => {
        if (res.confirm && onGiveUp) {
          onGiveUp()
        }
      },
    })
  }

  return (
    <View
      style={{
        background: cardBg,
        borderRadius: '32rpx',
        overflow: 'hidden',
        border: `2rpx solid ${isCalled ? 'rgba(52,199,89,0.4)' : '#1E3340'}`,
        opacity: overallOpacity,
        position: 'relative',
      }}
    >
      {/* Called state: green ambient glow at top */}
      {isCalled && (
        <View
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '8rpx',
            background: 'linear-gradient(90deg, transparent, #34C759, transparent)',
          }}
        />
      )}

      {/* Card body */}
      <View style={{ padding: '48rpx 40rpx 40rpx' }}>
        {/* Status label */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '32rpx',
          }}
        >
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '12rpx',
            }}
          >
            {/* Status dot */}
            <View
              style={{
                width: '16rpx',
                height: '16rpx',
                borderRadius: '8rpx',
                background: ticketColor,
                opacity: isCalled ? pulseOpacity : 1,
              }}
            />
            <Text
              style={{
                color: ticketColor,
                fontSize: '28rpx',
                fontWeight: '600',
              }}
            >
              {isCalled ? '叫号中' : isExpired ? '已过号' : '排队中'}
            </Text>
          </View>
        </View>

        {/* Ticket number — huge */}
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '40rpx',
          }}
        >
          <Text
            style={{
              color: ticketColor,
              fontSize: '120rpx',
              fontWeight: '900',
              lineHeight: '1',
              letterSpacing: '-4rpx',
              opacity: isCalled ? pulseOpacity : 1,
              // Webkit text stroke for crisp large text
              WebkitTextStroke: isCalled ? '1rpx rgba(52,199,89,0.3)' : 'none',
            }}
          >
            {ticketNo}
          </Text>
        </View>

        {/* Status message */}
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '40rpx',
          }}
        >
          {isCalled ? (
            <View
              style={{
                background: 'rgba(52,199,89,0.12)',
                borderRadius: '16rpx',
                padding: '16rpx 40rpx',
                border: '2rpx solid rgba(52,199,89,0.3)',
              }}
            >
              <Text
                style={{
                  color: '#34C759',
                  fontSize: '36rpx',
                  fontWeight: '700',
                }}
              >
                请立即入座！
              </Text>
            </View>
          ) : isExpired ? (
            <Text
              style={{
                color: '#4A6572',
                fontSize: '32rpx',
                fontWeight: '600',
              }}
            >
              排号已失效，请重新排队
            </Text>
          ) : (
            <View
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12rpx',
              }}
            >
              <Text
                style={{
                  color: '#9EB5C0',
                  fontSize: '32rpx',
                }}
              >
                前面还有{' '}
                <Text
                  style={{
                    color: '#FFFFFF',
                    fontWeight: '700',
                    fontSize: '40rpx',
                  }}
                >
                  {queueAhead}
                </Text>{' '}
                桌
              </Text>
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: '8rpx',
                }}
              >
                <Text style={{ fontSize: '28rpx', lineHeight: '1' }}>⏱</Text>
                <Text
                  style={{
                    color: '#9EB5C0',
                    fontSize: '28rpx',
                  }}
                >
                  预计等待{' '}
                  <Text
                    style={{
                      color: '#FF6B35',
                      fontWeight: '700',
                    }}
                  >
                    {estimatedWait}
                  </Text>{' '}
                  分钟
                </Text>
              </View>
            </View>
          )}
        </View>

        {/* Divider */}
        <View
          style={{
            height: '1rpx',
            background: '#1E3340',
            marginBottom: '32rpx',
          }}
        />

        {/* Give-up button — only when waiting */}
        {isWaiting && (
          <View
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <View
              style={{
                height: '88rpx',
                padding: '0 56rpx',
                border: '2rpx solid rgba(255,59,48,0.4)',
                borderRadius: '44rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={handleGiveUp}
            >
              <Text
                style={{
                  color: '#FF3B30',
                  fontSize: '30rpx',
                  fontWeight: '600',
                }}
              >
                放弃排号
              </Text>
            </View>
          </View>
        )}

        {/* Called state: no button — customer should sit down */}
        {isCalled && (
          <View
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text
              style={{
                color: 'rgba(52,199,89,0.7)',
                fontSize: '26rpx',
              }}
            >
              工作人员将为您引位
            </Text>
          </View>
        )}
      </View>
    </View>
  )
}

export default QueueTicket
