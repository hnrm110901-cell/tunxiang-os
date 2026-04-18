/**
 * subpages/error/index.tsx — 通用错误 / 空状态页
 *
 * URL params:
 *   ?type=404|500|network|empty
 *   &message=xxx     (custom message, used for "empty" type)
 *   &returnPath=xxx  (optional path to navigate back to)
 *
 * Designs per type:
 *   404      🔍  页面不见了          您访问的内容已下架或不存在
 *   500      ⚠️   服务开小差了        系统繁忙，请稍后再试
 *   network  📡  网络连接失败        检查网络后点击重试
 *   empty    📭  (message param)   暂无内容
 *
 * Buttons:
 *   "重试"       → navigateBack           (network / 500)
 *   "返回首页"   → switchTab index        (all)
 *   "联系客服"   → showToast stub         (404 only)
 */

import React, { useMemo } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { View, Text } from '@tarojs/components'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary:   '#FF6B35',
  primaryBg: 'rgba(255,107,53,0.12)',
  bgDeep:    '#0B1A20',
  bgCard:    '#132029',
  border:    '#1E3040',
  text1:     '#E8F4F8',
  text2:     '#9EB5C0',
  text3:     '#5A7A88',
  red:       '#E53935',
  white:     '#FFFFFF',
} as const

// ─── Type config map ──────────────────────────────────────────────────────────

type ErrorType = '404' | '500' | 'network' | 'empty'

interface ErrorConfig {
  emoji: string
  title: string
  subtitle: string
  showRetry: boolean
  showContact: boolean
  accentColor: string
}

const ERROR_CONFIG: Record<ErrorType, ErrorConfig> = {
  '404': {
    emoji: '🔍',
    title: '页面不见了',
    subtitle: '您访问的内容已下架或不存在',
    showRetry: false,
    showContact: true,
    accentColor: '#9EB5C0',
  },
  '500': {
    emoji: '⚠️',
    title: '服务开小差了',
    subtitle: '系统繁忙，请稍后再试',
    showRetry: true,
    showContact: false,
    accentColor: '#FF9800',
  },
  network: {
    emoji: '📡',
    title: '网络连接失败',
    subtitle: '检查网络后点击重试',
    showRetry: true,
    showContact: false,
    accentColor: '#5FA8E8',
  },
  empty: {
    emoji: '📭',
    title: '暂无内容',
    subtitle: '',
    showRetry: false,
    showContact: false,
    accentColor: '#9EB5C0',
  },
}

// ─── Sub-components ──────────────────────────────────────────────────────────

interface ActionButtonProps {
  label: string
  primary?: boolean
  onTap: () => void
}

function ActionButton({ label, primary = false, onTap }: ActionButtonProps) {
  return (
    <View
      style={{
        padding: '26rpx 64rpx',
        borderRadius: '50rpx',
        background: primary ? C.primary : 'transparent',
        border: `2rpx solid ${primary ? C.primary : C.border}`,
        minWidth: '240rpx',
        textAlign: 'center',
      }}
      onClick={onTap}
    >
      <Text
        style={{
          color: primary ? C.white : C.text2,
          fontSize: '28rpx',
          fontWeight: primary ? '700' : '400',
        }}
      >
        {label}
      </Text>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ErrorPage() {
  const router = useRouter()
  const params = router.params as { type?: string; message?: string; returnPath?: string }

  const errorType: ErrorType = (['404', '500', 'network', 'empty'] as ErrorType[]).includes(
    params.type as ErrorType,
  )
    ? (params.type as ErrorType)
    : '404'

  const config = ERROR_CONFIG[errorType]

  // For "empty" type, allow custom message from URL param
  const subtitle =
    errorType === 'empty' && params.message
      ? decodeURIComponent(params.message)
      : config.subtitle

  const title =
    errorType === 'empty' && params.message
      ? decodeURIComponent(params.message)
      : config.title

  // For empty with custom message: don't double-render the message as both title and subtitle
  const displaySubtitle =
    errorType === 'empty' && params.message ? '' : subtitle

  function handleRetry() {
    Taro.navigateBack({ delta: 1 })
  }

  function handleGoHome() {
    Taro.switchTab({ url: '/pages/index/index' })
  }

  function handleContact() {
    Taro.showToast({ title: '客服功能即将上线', icon: 'none', duration: 2000 })
  }

  return (
    <View
      style={{
        background: C.bgDeep,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '0 48rpx',
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
    >
      {/* Decorative ring */}
      <View
        style={{
          width: '240rpx',
          height: '240rpx',
          borderRadius: '50%',
          background: `radial-gradient(circle at 40% 40%, rgba(255,107,53,0.08), transparent 70%)`,
          border: `2rpx solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '48rpx',
          position: 'relative',
        }}
      >
        {/* Outer ring accent */}
        <View
          style={{
            position: 'absolute',
            inset: '-16rpx',
            borderRadius: '50%',
            border: `1rpx solid ${config.accentColor}22`,
          }}
        />
        <Text style={{ fontSize: '96rpx', lineHeight: '1' }}>{config.emoji}</Text>
      </View>

      {/* Title */}
      <Text
        style={{
          color: C.text1,
          fontSize: '40rpx',
          fontWeight: '700',
          textAlign: 'center',
          marginBottom: '20rpx',
        }}
      >
        {title}
      </Text>

      {/* Subtitle */}
      {displaySubtitle ? (
        <Text
          style={{
            color: C.text2,
            fontSize: '28rpx',
            textAlign: 'center',
            lineHeight: '1.6',
            marginBottom: '12rpx',
            maxWidth: '540rpx',
          }}
        >
          {displaySubtitle}
        </Text>
      ) : null}

      {/* Error type badge */}
      {errorType !== 'empty' && (
        <View
          style={{
            marginTop: '8rpx',
            marginBottom: '64rpx',
            background: C.bgCard,
            borderRadius: '8rpx',
            padding: '6rpx 20rpx',
            border: `1rpx solid ${C.border}`,
          }}
        >
          <Text style={{ color: C.text3, fontSize: '22rpx', fontFamily: 'monospace' }}>
            ERR_{errorType.toUpperCase()}
          </Text>
        </View>
      )}
      {errorType === 'empty' && <View style={{ marginBottom: '64rpx' }} />}

      {/* Action buttons */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '24rpx',
          width: '100%',
          maxWidth: '480rpx',
        }}
      >
        {config.showRetry && (
          <ActionButton label="重试" primary onTap={handleRetry} />
        )}
        <ActionButton label="返回首页" primary={!config.showRetry} onTap={handleGoHome} />
        {config.showContact && (
          <ActionButton label="联系客服" onTap={handleContact} />
        )}
      </View>

      {/* Bottom decorative dots */}
      <View
        style={{
          position: 'absolute',
          bottom: '80rpx',
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
          alignItems: 'center',
        }}
      >
        {[C.border, C.text3, C.border].map((color, i) => (
          <View
            key={i}
            style={{
              width: i === 1 ? '16rpx' : '10rpx',
              height: i === 1 ? '16rpx' : '10rpx',
              borderRadius: '50%',
              background: color,
            }}
          />
        ))}
      </View>
    </View>
  )
}
