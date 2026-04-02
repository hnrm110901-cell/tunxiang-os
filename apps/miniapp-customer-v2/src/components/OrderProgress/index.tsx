import { View, Text } from '@tarojs/components'
import React from 'react'

interface ProgressStep {
  label: string
  time?: string
  done: boolean
}

interface OrderProgressProps {
  status: string
  steps: ProgressStep[]
}

// Determine which step index is the "current" (first not-done after all done ones)
function getCurrentIndex(steps: ProgressStep[]): number {
  const firstPending = steps.findIndex((s) => !s.done)
  return firstPending === -1 ? steps.length - 1 : firstPending
}

const BRAND = '#FF6B2C'
const GREY  = '#2A4050'
const GREY_TEXT = '#6B8A96'

const OrderProgress: React.FC<OrderProgressProps> = ({ status: _status, steps }) => {
  const currentIdx = getCurrentIndex(steps)

  return (
    <View style={{ padding: '24rpx 32rpx' }}>
      {steps.map((step, i) => {
        const isDone    = step.done
        const isCurrent = i === currentIdx && !isDone
        const isPending = !isDone && !isCurrent
        const isLast    = i === steps.length - 1

        const dotColor  = isDone || isCurrent ? BRAND : GREY
        const lineColor = isDone ? BRAND : GREY

        return (
          <View
            key={i}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'flex-start',
              minHeight: '88rpx',
            }}
          >
            {/* Left column: dot + connector line */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                width: '40rpx',
                flexShrink: 0,
                marginRight: '24rpx',
              }}
            >
              {/* Dot */}
              <View
                style={{
                  position: 'relative',
                  width: '24rpx',
                  height: '24rpx',
                  borderRadius: '12rpx',
                  background: dotColor,
                  flexShrink: 0,
                  marginTop: '4rpx',
                  // Glow for current step
                  boxShadow: isCurrent ? `0 0 0 6rpx rgba(255,107,44,0.22)` : 'none',
                }}
              >
                {/* Inner check for done */}
                {isDone && (
                  <Text
                    style={{
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      transform: 'translate(-50%, -50%)',
                      color: '#fff',
                      fontSize: '14rpx',
                      lineHeight: '1',
                      fontWeight: '700',
                    }}
                  >
                    ✓
                  </Text>
                )}
                {/* Pulsing ring for current step — CSS keyframe via style tag not available
                    in WeChat miniapp; simulate with static outer ring */}
                {isCurrent && (
                  <View
                    style={{
                      position: 'absolute',
                      top: '-8rpx',
                      left: '-8rpx',
                      width: '40rpx',
                      height: '40rpx',
                      borderRadius: '20rpx',
                      border: `3rpx solid ${BRAND}`,
                      opacity: 0.5,
                    }}
                  />
                )}
              </View>

              {/* Connector line (not shown after last step) */}
              {!isLast && (
                <View
                  style={{
                    width: '2rpx',
                    flex: 1,
                    minHeight: '48rpx',
                    background: lineColor,
                    // Dashed via gradient for pending
                    backgroundImage: isPending
                      ? `repeating-linear-gradient(to bottom, ${GREY} 0, ${GREY} 8rpx, transparent 8rpx, transparent 16rpx)`
                      : 'none',
                    marginTop: '4rpx',
                  }}
                />
              )}
            </View>

            {/* Right column: label + time */}
            <View
              style={{
                flex: 1,
                paddingBottom: isLast ? 0 : '32rpx',
              }}
            >
              <Text
                style={{
                  color: isDone || isCurrent ? '#E8F4F8' : GREY_TEXT,
                  fontSize: isCurrent ? '30rpx' : '28rpx',
                  fontWeight: isCurrent || isDone ? '600' : '400',
                  display: 'block',
                  lineHeight: '40rpx',
                }}
              >
                {step.label}
              </Text>
              {step.time && (
                <Text
                  style={{
                    color: GREY_TEXT,
                    fontSize: '22rpx',
                    marginTop: '4rpx',
                    display: 'block',
                  }}
                >
                  {step.time}
                </Text>
              )}
            </View>
          </View>
        )
      })}
    </View>
  )
}

export default OrderProgress
