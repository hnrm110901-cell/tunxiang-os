/**
 * ReorderBanner — 智能复购提醒
 *
 * 首页顶部横幅: "上次在芙蓉店点了剁椒鱼头，再来一单？"
 * 基于最近消费记录，一键复购（加载上次订单到购物车）
 *
 * 展示条件:
 * 1. 用户已登录且有历史订单
 * 2. 距离上次消费3-14天
 * 3. 未被用户关闭
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../utils/request'
import { useCartStore } from '../../store/useCartStore'
import { useUserStore } from '../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  primaryBg: 'rgba(255,107,44,0.08)',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

interface LastOrder {
  order_id: string
  store_name: string
  top_dish: string
  total_fen: number
  days_ago: number
  items: Array<{ dish_id: string; name: string; price_fen: number; quantity: number }>
}

interface ReorderBannerProps {
  storeId?: string
}

export function ReorderBanner({ storeId }: ReorderBannerProps) {
  const [lastOrder, setLastOrder] = useState<LastOrder | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const { isLoggedIn } = useUserStore()
  const { addItem, clearCart } = useCartStore()

  useEffect(() => {
    if (!isLoggedIn) return

    txRequest<LastOrder>('/trade/orders/last-reorderable')
      .then(data => {
        if (data?.order_id && data.days_ago >= 3 && data.days_ago <= 14) {
          setLastOrder(data)
        }
      })
      .catch(() => {
        // 降级: 不显示
      })
  }, [isLoggedIn])

  const handleReorder = useCallback(() => {
    if (!lastOrder?.items?.length) return
    clearCart()
    for (const item of lastOrder.items) {
      addItem({
        id: item.dish_id,
        name: item.name,
        priceFen: item.price_fen,
        quantity: item.quantity,
        specs: '',
        remark: '',
      })
    }
    Taro.showToast({ title: '已加入购物车', icon: 'success' })
    // 跳转到购物车
    Taro.navigateTo({ url: '/subpages/order-flow/cart/index' })
  }, [lastOrder, addItem, clearCart])

  if (!lastOrder || dismissed) return null

  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`

  return (
    <View style={{
      margin: '16rpx 24rpx',
      padding: '20rpx 24rpx',
      borderRadius: '16rpx',
      background: C.primaryBg,
      border: `1rpx solid ${C.primary}30`,
      display: 'flex',
      alignItems: 'center',
    }}>
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: '26rpx', color: C.text1, display: 'block' }}>
          {lastOrder.days_ago}天前在{lastOrder.store_name}点了{lastOrder.top_dish}
        </Text>
        <Text style={{ fontSize: '22rpx', color: C.text3, marginTop: '4rpx', display: 'block' }}>
          共{lastOrder.items.length}道菜 · {fenToYuan(lastOrder.total_fen)}
        </Text>
      </View>
      <View
        onClick={handleReorder}
        style={{
          padding: '12rpx 24rpx',
          borderRadius: '24rpx',
          background: C.primary,
          marginLeft: '16rpx',
          flexShrink: 0,
        }}
      >
        <Text style={{ fontSize: '24rpx', color: C.white, fontWeight: '500' }}>再来一单</Text>
      </View>
      <Text
        onClick={() => setDismissed(true)}
        style={{ fontSize: '28rpx', color: C.text3, marginLeft: '12rpx', padding: '8rpx' }}
      >
        ✕
      </Text>
    </View>
  )
}
