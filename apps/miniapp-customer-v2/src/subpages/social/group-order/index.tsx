/**
 * social/group-order — 社群拼单
 *
 * 发起拼单→分享到群→好友加入→各点各的→合并结算
 * 满N人享折扣（如4人同行95折）
 *
 * API: POST /api/v1/trade/group-orders (创建拼单)
 *      GET  /api/v1/trade/group-orders/{id} (查看拼单)
 *      POST /api/v1/trade/group-orders/{id}/join (加入拼单)
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { useStoreInfo } from '../../../store/useStoreInfo'
import { useUserStore } from '../../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  primaryBg: 'rgba(255,107,44,0.12)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  success: '#34C759',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface GroupOrder {
  id: string
  code: string
  store_id: string
  store_name: string
  creator_name: string
  status: 'open' | 'locked' | 'paid' | 'cancelled'
  min_people: number
  max_people: number
  discount_rate: number // 0.95 = 95折
  participants: Participant[]
  total_fen: number
  expires_at: string
}

interface Participant {
  user_id: string
  nickname: string
  avatar_url: string
  item_count: number
  subtotal_fen: number
  is_ready: boolean
}

type Tab = 'create' | 'join' | 'active'

// ─── Component ────────────────────────────────────────────────────────────────

export default function GroupOrderPage() {
  const [tab, setTab] = useState<Tab>('create')
  const [groupCode, setGroupCode] = useState('')
  const [activeGroup, setActiveGroup] = useState<GroupOrder | null>(null)
  const [loading, setLoading] = useState(false)
  const { storeId, storeName } = useStoreInfo()
  const { nickname } = useUserStore()

  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`

  // ─── 创建拼单 ──────────────────────────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    setLoading(true)
    try {
      const data = await txRequest<GroupOrder>(
        '/trade/group-orders',
        'POST',
        { store_id: storeId, min_people: 2, max_people: 8, discount_rate: 0.95 } as Record<string, unknown>,
      )
      if (data?.id) {
        setActiveGroup(data)
        setTab('active')
        // 分享到微信群
        Taro.showShareMenu({ withShareTicket: true })
      }
    } catch {
      Taro.showToast({ title: '创建失败', icon: 'none' })
    }
    setLoading(false)
  }, [storeId])

  // ─── 加入拼单 ──────────────────────────────────────────────────────────────

  const handleJoin = useCallback(async () => {
    if (!groupCode.trim()) return
    setLoading(true)
    try {
      const data = await txRequest<GroupOrder>(
        `/trade/group-orders/${groupCode}/join`,
        'POST',
      )
      if (data?.id) {
        setActiveGroup(data)
        setTab('active')
      }
    } catch {
      Taro.showToast({ title: '拼单不存在或已结束', icon: 'none' })
    }
    setLoading(false)
  }, [groupCode])

  // ─── 分享 ──────────────────────────────────────────────────────────────────

  const handleShare = () => {
    if (!activeGroup) return
    Taro.showShareMenu({ withShareTicket: true })
  }

  // ─── 去点餐 ──────────────────────────────────────────────────────────────

  const goToMenu = () => {
    Taro.navigateTo({
      url: `/pages/menu/index?group_order_id=${activeGroup?.id || ''}`,
    })
  }

  // ─── Render: Create Tab ─────────────────────────────────────────────────────

  const renderCreate = () => (
    <View style={{ padding: '32rpx' }}>
      <View style={{ textAlign: 'center', padding: '40rpx 0' }}>
        <Text style={{ fontSize: '64rpx', display: 'block' }}>🍽️</Text>
        <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginTop: '16rpx' }}>
          发起拼单
        </Text>
        <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx' }}>
          邀请好友一起点，各点各的，合并结算享折扣
        </Text>
      </View>

      {/* 规则卡片 */}
      <View style={{ background: C.bgCard, borderRadius: '16rpx', padding: '24rpx', marginBottom: '24rpx' }}>
        <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '12rpx' }}>拼单规则</Text>
        {[
          '2人以上即可拼单，最多8人',
          '每人独立点餐，互不影响',
          '满2人享95折，满4人享9折',
          '30分钟内未凑齐自动取消',
        ].map((rule, i) => (
          <View key={i} style={{ display: 'flex', alignItems: 'center', gap: '8rpx', marginBottom: '8rpx' }}>
            <Text style={{ fontSize: '24rpx', color: C.primary }}>•</Text>
            <Text style={{ fontSize: '26rpx', color: C.text2 }}>{rule}</Text>
          </View>
        ))}
      </View>

      <View style={{ background: C.bgCard, borderRadius: '16rpx', padding: '20rpx', marginBottom: '32rpx' }}>
        <Text style={{ fontSize: '26rpx', color: C.text2 }}>📍 {storeName || '请先选择门店'}</Text>
      </View>

      <View
        onClick={handleCreate}
        style={{
          padding: '28rpx 0', borderRadius: '16rpx',
          background: loading ? C.bgCard : C.primary,
          textAlign: 'center', opacity: loading ? 0.6 : 1,
        }}
      >
        <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>
          {loading ? '创建中...' : '发起拼单'}
        </Text>
      </View>
    </View>
  )

  // ─── Render: Join Tab ───────────────────────────────────────────────────────

  const renderJoin = () => (
    <View style={{ padding: '32rpx' }}>
      <View style={{ textAlign: 'center', padding: '40rpx 0' }}>
        <Text style={{ fontSize: '64rpx', display: 'block' }}>🔗</Text>
        <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginTop: '16rpx' }}>
          加入拼单
        </Text>
        <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx' }}>
          输入好友分享的拼单码
        </Text>
      </View>

      <Input
        value={groupCode}
        onInput={e => setGroupCode(e.detail.value)}
        placeholder="输入6位拼单码"
        maxlength={6}
        style={{
          padding: '24rpx', borderRadius: '12rpx',
          background: C.bgCard, border: `2rpx solid ${C.border}`,
          color: C.text1, fontSize: '36rpx', textAlign: 'center',
          letterSpacing: '16rpx', fontWeight: '700',
        }}
        placeholderStyle={`color: ${C.text3}; font-weight: 400; letter-spacing: 4rpx`}
      />

      <View
        onClick={handleJoin}
        style={{
          marginTop: '32rpx', padding: '28rpx 0', borderRadius: '16rpx',
          background: groupCode.length === 6 ? C.primary : C.bgCard,
          textAlign: 'center',
        }}
      >
        <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>
          {loading ? '加入中...' : '加入拼单'}
        </Text>
      </View>
    </View>
  )

  // ─── Render: Active Group ───────────────────────────────────────────────────

  const renderActive = () => {
    if (!activeGroup) return renderCreate()
    const pCount = activeGroup.participants.length
    const discount = Math.round((1 - activeGroup.discount_rate) * 100)

    return (
      <View style={{ padding: '32rpx' }}>
        {/* 拼单信息 */}
        <View style={{
          background: C.primaryBg, borderRadius: '16rpx', padding: '24rpx',
          border: `2rpx solid ${C.primary}40`, marginBottom: '20rpx',
        }}>
          <View style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1 }}>拼单码: {activeGroup.code}</Text>
            <View style={{ padding: '6rpx 16rpx', borderRadius: '8rpx', background: C.primary }}>
              <Text style={{ fontSize: '24rpx', color: C.white }}>{discount}%OFF</Text>
            </View>
          </View>
          <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginTop: '8rpx' }}>
            {activeGroup.store_name} · {pCount}/{activeGroup.max_people}人
          </Text>
        </View>

        {/* 参与者列表 */}
        <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '12rpx' }}>
          参与者 ({pCount})
        </Text>
        {activeGroup.participants.map(p => (
          <View key={p.user_id} style={{
            display: 'flex', alignItems: 'center', padding: '16rpx 20rpx',
            background: C.bgCard, borderRadius: '12rpx', marginBottom: '8rpx',
          }}>
            <View style={{
              width: '64rpx', height: '64rpx', borderRadius: '50%', background: C.border,
              display: 'flex', alignItems: 'center', justifyContent: 'center', marginRight: '16rpx',
            }}>
              <Text style={{ fontSize: '28rpx', color: C.text1 }}>{p.nickname.charAt(0)}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: '28rpx', color: C.text1 }}>{p.nickname}</Text>
              <Text style={{ fontSize: '22rpx', color: C.text3 }}>
                {p.item_count > 0 ? `${p.item_count}道菜 · ${fenToYuan(p.subtotal_fen)}` : '还没点餐'}
              </Text>
            </View>
            {p.is_ready && (
              <Text style={{ fontSize: '24rpx', color: C.success }}>✓ 已确认</Text>
            )}
          </View>
        ))}

        {/* 操作按钮 */}
        <View style={{ display: 'flex', gap: '16rpx', marginTop: '24rpx' }}>
          <View
            onClick={handleShare}
            style={{
              flex: 1, padding: '24rpx 0', borderRadius: '12rpx',
              background: C.bgCard, border: `2rpx solid ${C.border}`, textAlign: 'center',
            }}
          >
            <Text style={{ fontSize: '28rpx', color: C.text1 }}>邀请好友</Text>
          </View>
          <View
            onClick={goToMenu}
            style={{
              flex: 2, padding: '24rpx 0', borderRadius: '12rpx',
              background: C.primary, textAlign: 'center',
            }}
          >
            <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.white }}>去点餐</Text>
          </View>
        </View>
      </View>
    )
  }

  // ─── Main ───────────────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      {/* Tab bar */}
      <View style={{ display: 'flex', borderBottom: `1rpx solid ${C.border}` }}>
        {([['create', '发起拼单'], ['join', '加入拼单'], ['active', '进行中']] as [Tab, string][]).map(([key, label]) => (
          <View
            key={key}
            onClick={() => setTab(key)}
            style={{
              flex: 1, padding: '24rpx 0', textAlign: 'center',
              borderBottom: tab === key ? `4rpx solid ${C.primary}` : 'none',
            }}
          >
            <Text style={{
              fontSize: '28rpx',
              color: tab === key ? C.primary : C.text3,
              fontWeight: tab === key ? '600' : '400',
            }}>{label}</Text>
          </View>
        ))}
      </View>

      {tab === 'create' && renderCreate()}
      {tab === 'join' && renderJoin()}
      {tab === 'active' && renderActive()}
    </View>
  )
}
