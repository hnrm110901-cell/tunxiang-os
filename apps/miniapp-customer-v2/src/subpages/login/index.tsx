/**
 * login/index.tsx — 登录 / 引导页
 *
 * Flow:
 *   1. User sees full-screen dark page with logo, food illustration, and benefits.
 *   2. Tap "微信一键登录" → agree to privacy policy → useAuth.login() → navigate back.
 *   3. Tap "游客浏览" → navigate back without logging in (limited features).
 *
 * Privacy policy checkbox must be ticked before login is allowed.
 * Loading state disables the button during the async login call.
 */

import React, { useState, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, ScrollView } from '@tarojs/components'
import { useAuth } from '../../hooks/useAuth'

// ─── Brand tokens (dark-mode app palette) ─────────────────────────────────────
const C = {
  appBg:      '#0B1A20',
  cardBg:     '#132029',
  surface:    '#1A2E38',
  border:     '#1E3340',
  primary:    '#FF6B35',
  wechat:     '#07C160',
  wechatDark: '#059B4F',
  text1:      '#FFFFFF',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  link:       '#4DBFE8',
} as const

// ─── Benefits list ────────────────────────────────────────────────────────────
const BENEFITS = [
  { icon: '🤖', label: '智能推荐',  desc: 'AI 为你匹配最合适的菜品组合' },
  { icon: '💎', label: '会员积分',  desc: '每笔消费积分，换取专属特权' },
  { icon: '🎁', label: '储值优惠',  desc: '储值享折扣，余额随时可用' },
  { icon: '👑', label: '专属服务',  desc: '专属客服 · 优先叫号 · 生日礼遇' },
] as const

// ─── Component ────────────────────────────────────────────────────────────────

const LoginPage: React.FC = () => {
  const { login } = useAuth()

  const [agreed, setAgreed]     = useState(false)
  const [loading, setLoading]   = useState(false)

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleLogin = useCallback(async () => {
    if (!agreed) {
      Taro.showToast({ title: '请先同意用户协议和隐私政策', icon: 'none', duration: 2000 }).catch(
        () => undefined,
      )
      return
    }

    setLoading(true)
    try {
      await login()
      // Try navigating back; if there's no page to go back to, switch to home tab
      const pages = Taro.getCurrentPages()
      if (pages.length > 1) {
        Taro.navigateBack({ delta: 1 }).catch(() => undefined)
      } else {
        Taro.switchTab({ url: '/pages/index/index' }).catch(() => undefined)
      }
    } catch (_err) {
      // useAuth already shows a toast on failure
    } finally {
      setLoading(false)
    }
  }, [agreed, login])

  const handleGuestBrowse = useCallback(() => {
    const pages = Taro.getCurrentPages()
    if (pages.length > 1) {
      Taro.navigateBack({ delta: 1 }).catch(() => undefined)
    } else {
      Taro.switchTab({ url: '/pages/index/index' }).catch(() => undefined)
    }
  }, [])

  const openPrivacyPolicy = useCallback(() => {
    Taro.navigateTo({ url: '/subpages/settings/privacy' }).catch(() => undefined)
  }, [])

  const openUserAgreement = useCallback(() => {
    Taro.navigateTo({ url: '/subpages/settings/agreement' }).catch(() => undefined)
  }, [])

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <ScrollView
      scrollY
      style={{
        height: '100vh',
        background: C.appBg,
      }}
    >
      <View
        style={{
          minHeight: '100vh',
          background: C.appBg,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '0 40rpx',
          paddingBottom: 'env(safe-area-inset-bottom)',
        }}
      >
        {/* ── Logo & tagline ── */}
        <View
          style={{
            marginTop: '96rpx',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <Text
            style={{
              fontSize: '72rpx',
              fontWeight: '800',
              color: C.primary,
              letterSpacing: '4rpx',
              lineHeight: '1.1',
            }}
          >
            屯象OS
          </Text>
          <Text
            style={{
              marginTop: '12rpx',
              fontSize: '30rpx',
              color: C.text2,
              letterSpacing: '6rpx',
              fontWeight: '400',
            }}
          >
            AI 餐饮新体验
          </Text>
        </View>

        {/* ── Food illustration card ── */}
        <View
          style={{
            marginTop: '56rpx',
            width: '100%',
            background: C.cardBg,
            borderRadius: '32rpx',
            padding: '40rpx',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            border: `1rpx solid ${C.border}`,
          }}
        >
          {/* Emoji food art */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'center',
              flexWrap: 'wrap',
              gap: '8rpx',
            }}
          >
            {['🍜', '🥟', '🦞', '🍱', '🍣', '🥗'].map((emoji) => (
              <Text
                key={emoji}
                style={{
                  fontSize: '64rpx',
                  lineHeight: '1.2',
                  margin: '4rpx 8rpx',
                }}
              >
                {emoji}
              </Text>
            ))}
          </View>

          <Text
            style={{
              marginTop: '24rpx',
              fontSize: '26rpx',
              color: C.text3,
              textAlign: 'center',
              lineHeight: '1.6',
            }}
          >
            扫码点餐 · 智能推荐 · 会员储值
          </Text>
        </View>

        {/* ── Benefits list ── */}
        <View
          style={{
            marginTop: '40rpx',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: '0rpx',
          }}
        >
          {BENEFITS.map((b) => (
            <View
              key={b.label}
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                padding: '20rpx 0',
                borderBottom: `1rpx solid ${C.border}`,
              }}
            >
              {/* Icon bubble */}
              <View
                style={{
                  width: '72rpx',
                  height: '72rpx',
                  borderRadius: '18rpx',
                  background: C.surface,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <Text style={{ fontSize: '36rpx' }}>{b.icon}</Text>
              </View>

              {/* Text */}
              <View style={{ flex: 1, marginLeft: '24rpx' }}>
                <Text
                  style={{
                    fontSize: '30rpx',
                    fontWeight: '600',
                    color: C.text1,
                    display: 'block',
                  }}
                >
                  {b.label}
                </Text>
                <Text
                  style={{
                    marginTop: '4rpx',
                    fontSize: '24rpx',
                    color: C.text2,
                    display: 'block',
                  }}
                >
                  {b.desc}
                </Text>
              </View>

              {/* Check icon */}
              <Text style={{ color: C.wechat, fontSize: '36rpx', marginLeft: '16rpx' }}>✓</Text>
            </View>
          ))}
        </View>

        {/* Spacer */}
        <View style={{ flex: 1, minHeight: '48rpx' }} />

        {/* ── Privacy agreement ── */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-start',
            width: '100%',
            marginTop: '48rpx',
          }}
          onClick={() => setAgreed((prev) => !prev)}
        >
          {/* Custom checkbox */}
          <View
            style={{
              width: '40rpx',
              height: '40rpx',
              borderRadius: '10rpx',
              border: agreed ? 'none' : `2rpx solid ${C.text3}`,
              background: agreed ? C.wechat : 'transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              marginTop: '2rpx',
            }}
          >
            {agreed && (
              <Text style={{ color: '#fff', fontSize: '26rpx', fontWeight: '700' }}>✓</Text>
            )}
          </View>

          {/* Agreement text */}
          <Text
            style={{
              flex: 1,
              marginLeft: '16rpx',
              fontSize: '24rpx',
              color: C.text2,
              lineHeight: '1.6',
            }}
          >
            登录即同意{' '}
            <Text
              style={{ color: C.link }}
              onClick={(e) => {
                e.stopPropagation()
                openUserAgreement()
              }}
            >
              《用户协议》
            </Text>
            和{' '}
            <Text
              style={{ color: C.link }}
              onClick={(e) => {
                e.stopPropagation()
                openPrivacyPolicy()
              }}
            >
              《隐私政策》
            </Text>
          </Text>
        </View>

        {/* ── WeChat login button ── */}
        <View
          style={{
            marginTop: '32rpx',
            width: '100%',
            height: '96rpx',
            borderRadius: '48rpx',
            background: loading || !agreed ? '#1A3A28' : C.wechat,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: loading ? 0.7 : 1,
            transition: 'background 200ms ease, opacity 200ms ease',
          }}
          onClick={handleLogin}
          hoverStyle={{ background: agreed ? C.wechatDark : undefined }}
        >
          {loading ? (
            <Text style={{ fontSize: '32rpx', color: '#fff', fontWeight: '600' }}>
              登录中...
            </Text>
          ) : (
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: '12rpx',
              }}
            >
              <Text style={{ fontSize: '40rpx' }}>微</Text>
              <Text style={{ fontSize: '32rpx', color: '#fff', fontWeight: '600' }}>
                微信一键登录
              </Text>
            </View>
          )}
        </View>

        {/* ── Guest browse ── */}
        <View
          style={{
            marginTop: '28rpx',
            padding: '20rpx 40rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={handleGuestBrowse}
        >
          <Text
            style={{
              fontSize: '26rpx',
              color: C.text3,
              textDecoration: 'underline',
            }}
          >
            游客浏览（功能受限）
          </Text>
        </View>

        {/* Bottom safe-area spacer */}
        <View style={{ height: '32rpx' }} />
      </View>
    </ScrollView>
  )
}

export default LoginPage
