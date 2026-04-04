/**
 * pages/points-mall/index.tsx — 积分商城入口（重定向页）
 *
 * 积分商城的完整实现位于 subpages/marketing/points-mall/index.tsx。
 * 此页面作为主包入口，在 onLoad 时立即跳转到分包页面，
 * 确保从 TabBar / navigateTo 等任意路径都能正确进入积分商城。
 *
 * 为什么这样设计：
 *  - 小程序分包规则要求分包页面不能被 TabBar 或主包直接引用
 *  - 通过主包 "门卫" 页面做一次 redirectTo，体验无感知
 */

import React, { useEffect } from 'react'
import Taro from '@tarojs/taro'
import { View, Text } from '@tarojs/components'

const C = {
  bg:    '#0B1A20',
  text3: '#5A7A88',
} as const

export default function PointsMallEntryPage() {
  useEffect(() => {
    // Immediately redirect to the full implementation in the marketing subpackage.
    // Use redirectTo so there's no back-navigation to this blank page.
    Taro.redirectTo({
      url: '/subpages/marketing/points-mall/index',
    }).catch(() => {
      // Fallback: navigate if redirect fails (e.g. during dev H5 mode)
      Taro.navigateTo({ url: '/subpages/marketing/points-mall/index' }).catch(() => {
        Taro.showToast({ title: '积分商城加载中', icon: 'loading' })
      })
    })
  }, [])

  // Minimal loading state shown for the brief moment before redirect
  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载积分商城…</Text>
    </View>
  )
}
