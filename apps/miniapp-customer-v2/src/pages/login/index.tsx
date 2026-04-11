/**
 * pages/login/index.tsx — 登录 / 引导页
 *
 * Sections:
 *   1. Safe-area top padding
 *   2. Logo section: "屯象" + "OS" superscript + tagline
 *   3. Feature cards horizontal row (4 cards, ScrollView)
 *   4. Privacy checkbox (required to enable login)
 *   5. "微信一键登录" CTA (WeChat green, full-width)
 *   6. "游客浏览" ghost text button
 *   7. Bottom: 《用户协议》+《隐私政策》 tappable links
 *
 * On login success:
 *   - Check router params for `redirect`
 *   - navigateTo(redirect) OR switchTab('pages/index/index')
 */

import React, { useState, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, ScrollView } from '@tarojs/components'
import { useUserStore } from '../../store/useUserStore'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary:     '#FF6B35',
  primaryDk:   '#E55A1F',
  primaryBg:   'rgba(255,107,53,0.10)',
  wechat:      '#07C160',
  wechatDk:    '#059A4C',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  bgHover:     '#1A2E38',
  border:      '#1E3040',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Feature cards data ───────────────────────────────────────────────────────

const FEATURES = [
  {
    id: 'ai',
    emoji: '🤖',
    title: 'AI推荐',
    desc: '千人千面菜品推荐',
    gradient: ['#1A2E3E', '#0F1E2A'],
    accent: '#5FA8E8',
  },
  {
    id: 'points',
    emoji: '💰',
    title: '会员积分',
    desc: '消费得积分享权益',
    gradient: ['#2E1A10', '#1A0F08'],
    accent: '#FFD700',
  },
  {
    id: 'stored',
    emoji: '💳',
    title: '储值优惠',
    desc: '充值享赠送金',
    gradient: ['#1A2E1A', '#0F1F0F'],
    accent: '#4CAF50',
  },
  {
    id: 'diamond',
    emoji: '⭐',
    title: '专属服务',
    desc: '钻石会员优先',
    gradient: ['#2E2210', '#1A1508'],
    accent: '#FF9800',
  },
] as const

// ─── API types ────────────────────────────────────────────────────────────────

interface WxLoginResponse {
  token: string
  refresh_token: string
  user_id: string
  tenant_id: string
  nickname: string
  avatar_url: string
  member_level: string
  is_new_user: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function wxLogin(): Promise<WxLoginResponse> {
  const loginRes = await Taro.login()
  if (!loginRes.code) throw new Error('WeChat login failed — no code returned')
  return txRequest<WxLoginResponse>('/api/v1/auth/wx-login', 'POST', { code: loginRes.code })
}

// ─── Sub-components ──────────────────────────────────────────────────────────

interface FeatureCardProps {
  emoji: string
  title: string
  desc: string
  gradient: readonly [string, string]
  accent: string
}

function FeatureCard({ emoji, title, desc, gradient, accent }: FeatureCardProps) {
  return (
    <View
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        width: '220rpx',
        padding: '28rpx 24rpx',
        borderRadius: '24rpx',
        background: `linear-gradient(145deg, ${gradient[0]}, ${gradient[1]})`,
        border: `1rpx solid ${C.border}`,
        marginRight: '20rpx',
        flexShrink: 0,
        verticalAlign: 'top',
      }}
    >
      <View
        style={{
          width: '72rpx',
          height: '72rpx',
          borderRadius: '18rpx',
          background: `${accent}22`,
          border: `1rpx solid ${accent}44`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '20rpx',
        }}
      >
        <Text style={{ fontSize: '36rpx', lineHeight: '1' }}>{emoji}</Text>
      </View>
      <Text
        style={{
          color: C.text1,
          fontSize: '26rpx',
          fontWeight: '700',
          display: 'block',
          marginBottom: '8rpx',
        }}
      >
        {title}
      </Text>
      <Text style={{ color: C.text2, fontSize: '22rpx', lineHeight: '1.5', display: 'block' }}>
        {desc}
      </Text>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const [privacyChecked, setPrivacyChecked] = useState(false)
  const [loggingIn, setLoggingIn] = useState(false)
  const setUser = useUserStore((s) => s.setUser)

  // Read redirect param from router
  const router = Taro.getCurrentInstance().router
  const redirectParam = router?.params?.redirect as string | undefined

  function resolveRedirect() {
    if (redirectParam) {
      try {
        Taro.navigateTo({ url: decodeURIComponent(redirectParam) })
        return
      } catch {
        // fall through to switchTab
      }
    }
    Taro.switchTab({ url: '/pages/index/index' })
  }

  const handleWxLogin = useCallback(async () => {
    if (!privacyChecked) {
      Taro.showToast({ title: '请先同意用户协议与隐私政策', icon: 'none', duration: 2000 })
      return
    }
    if (loggingIn) return

    setLoggingIn(true)
    try {
      const res = await wxLogin()

      // Persist auth tokens
      Taro.setStorageSync('tx_token', res.token)
      Taro.setStorageSync('tx_refresh_token', res.refresh_token)
      Taro.setStorageSync('tx_user_id', res.user_id)
      Taro.setStorageSync('tx_tenant_id', res.tenant_id)

      // Update user store
      setUser({
        userId: res.user_id,
        nickname: res.nickname,
        avatarUrl: res.avatar_url,
        memberLevel: res.member_level as any,
      })

      if (res.is_new_user) {
        Taro.showToast({ title: '欢迎加入屯象！', icon: 'success', duration: 1500 })
        await new Promise((r) => setTimeout(r, 1500))
      }

      resolveRedirect()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '登录失败，请重试'
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setLoggingIn(false)
    }
  }, [privacyChecked, loggingIn, setUser])

  function handleGuestBrowse() {
    resolveRedirect()
  }

  function handleAgreement(type: 'agreement' | 'privacy') {
    Taro.navigateTo({
      url: `/subpages/settings/agreement/index?type=${type}`,
    })
  }

  const loginEnabled = privacyChecked && !loggingIn

  return (
    <View
      style={{
        background: C.bgDeep,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingBottom: 'env(safe-area-inset-bottom, 32rpx)',
      }}
    >
      {/* ─── Logo section ─── */}
      <View
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          paddingTop: '80rpx',
          paddingBottom: '40rpx',
        }}
      >
        {/* Brand mark */}
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'flex-start', marginBottom: '20rpx' }}>
          <Text
            style={{
              color: C.text1,
              fontSize: '88rpx',
              fontWeight: '800',
              letterSpacing: '-2rpx',
              lineHeight: '1',
            }}
          >
            屯象
          </Text>
          <Text
            style={{
              color: C.primary,
              fontSize: '36rpx',
              fontWeight: '700',
              marginLeft: '4rpx',
              marginTop: '8rpx',
              lineHeight: '1',
            }}
          >
            OS
          </Text>
        </View>

        {/* Tagline */}
        <Text style={{ color: C.text2, fontSize: '30rpx', letterSpacing: '2rpx' }}>
          AI赋能餐饮新体验
        </Text>

        {/* Accent line */}
        <View
          style={{
            width: '80rpx',
            height: '6rpx',
            background: `linear-gradient(90deg, ${C.primary}, transparent)`,
            borderRadius: '3rpx',
            marginTop: '24rpx',
          }}
        />
      </View>

      {/* ─── Feature cards ─── */}
      <View style={{ marginBottom: '64rpx' }}>
        <ScrollView
          scrollX
          style={{ whiteSpace: 'nowrap', paddingLeft: '40rpx' }}
          showScrollbar={false}
        >
          {FEATURES.map((f) => (
            <FeatureCard key={f.id} {...f} />
          ))}
          {/* Trailing spacer */}
          <View style={{ display: 'inline-block', width: '24rpx' }} />
        </ScrollView>
      </View>

      {/* ─── Login actions ─── */}
      <View style={{ padding: '0 40rpx' }}>
        {/* Privacy checkbox row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            gap: '16rpx',
            marginBottom: '36rpx',
            padding: '0 4rpx',
          }}
          onClick={() => setPrivacyChecked((v) => !v)}
        >
          {/* Checkbox */}
          <View
            style={{
              width: '44rpx',
              height: '44rpx',
              borderRadius: '50%',
              border: `2rpx solid ${privacyChecked ? C.primary : C.border}`,
              background: privacyChecked ? C.primary : 'transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              transition: 'all 0.2s',
            }}
          >
            {privacyChecked && (
              <Text style={{ color: C.white, fontSize: '26rpx', lineHeight: '1', fontWeight: '700' }}>✓</Text>
            )}
          </View>
          <Text style={{ color: C.text2, fontSize: '24rpx', lineHeight: '1.5', flex: 1 }}>
            我已阅读并同意{' '}
            <Text
              style={{ color: C.primary }}
              onClick={(e) => { e.stopPropagation(); handleAgreement('agreement') }}
            >
              《用户协议》
            </Text>
            {' '}和{' '}
            <Text
              style={{ color: C.primary }}
              onClick={(e) => { e.stopPropagation(); handleAgreement('privacy') }}
            >
              《隐私政策》
            </Text>
          </Text>
        </View>

        {/* WeChat login button */}
        <View
          style={{
            width: '100%',
            height: '96rpx',
            borderRadius: '50rpx',
            background: loginEnabled ? C.wechat : `${C.wechat}55`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16rpx',
            marginBottom: '28rpx',
            transition: 'opacity 0.2s',
            cursor: loginEnabled ? 'pointer' : 'not-allowed',
          }}
          onClick={handleWxLogin}
        >
          {loggingIn ? (
            /* Loading spinner (CSS animation via border trick) */
            <>
              <View
                style={{
                  width: '40rpx',
                  height: '40rpx',
                  borderRadius: '50%',
                  border: `4rpx solid rgba(255,255,255,0.3)`,
                  borderTopColor: C.white,
                  animation: 'spin 0.8s linear infinite',
                }}
              />
              <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>登录中...</Text>
            </>
          ) : (
            <>
              <Text style={{ fontSize: '36rpx', lineHeight: '1' }}>💬</Text>
              <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>微信一键登录</Text>
            </>
          )}
        </View>

        {/* Guest browse */}
        <View
          style={{ padding: '16rpx', textAlign: 'center' }}
          onClick={handleGuestBrowse}
        >
          <Text style={{ color: C.text3, fontSize: '28rpx' }}>游客浏览</Text>
        </View>
      </View>

      {/* ─── Bottom agreement links ─── */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8rpx',
          padding: '24rpx 40rpx 0',
          flexWrap: 'wrap',
        }}
      >
        <Text style={{ color: C.text3, fontSize: '22rpx' }}>登录即代表同意</Text>
        <Text
          style={{ color: C.text2, fontSize: '22rpx' }}
          onClick={() => handleAgreement('agreement')}
        >
          《用户协议》
        </Text>
        <Text style={{ color: C.text3, fontSize: '22rpx' }}>与</Text>
        <Text
          style={{ color: C.text2, fontSize: '22rpx' }}
          onClick={() => handleAgreement('privacy')}
        >
          《隐私政策》
        </Text>
      </View>
    </View>
  )
}
