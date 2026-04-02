/**
 * points/index.tsx — 积分中心页
 *
 * Features:
 *  - Dark gradient balance card (PointsBalance component)
 *  - Tab bar: 积分明细 / 积分规则
 *  - 积分明细: filter pills (全部/收入/支出), transaction list, load-more, empty state
 *  - 积分规则: static content card
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getPointsBalance, getPointsHistory } from '../../../api/member'
import type { PointsTransaction, PointsHistory } from '../../../api/member'
import { useUserStore } from '../../../store/useUserStore'
import { PointsBalance } from '../../../components/PointsBalance'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#4A6572',
  success: '#4CAF50',
  danger: '#E53935',
  white: '#FFFFFF',
} as const

// ─── Level thresholds for next level hint ─────────────────────────────────────

const NEXT_LEVEL_POINTS: Record<string, number | undefined> = {
  bronze: 1000,
  silver: 5000,
  gold: 20000,
  diamond: undefined,
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

type FilterType = 'all' | 'earn' | 'spend'

const FILTER_OPTIONS: { value: FilterType; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'earn', label: '收入' },
  { value: 'spend', label: '支出' },
]

function isEarn(tx: PointsTransaction): boolean {
  return tx.delta > 0
}

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${min}`
}

function txIcon(tx: PointsTransaction): string {
  if (tx.delta > 0) return '+'
  if (tx.delta < 0) return '−'
  return '•'
}

function txTypeLabel(type: string): string {
  const map: Record<string, string> = {
    earn_order: '消费积分',
    earn_signup: '注册奖励',
    earn_referral: '推荐奖励',
    earn_activity: '活动积分',
    spend_redeem: '积分兑换',
    spend_order: '积分抵扣',
    expire: '积分过期',
    admin_adjust: '系统调整',
  }
  return map[type] ?? type
}

// ─── Transaction item ─────────────────────────────────────────────────────────

const TxItem: React.FC<{ tx: PointsTransaction }> = ({ tx }) => {
  const earn = isEarn(tx)
  const iconColor = earn ? C.success : C.danger
  const pointsStr = `${earn ? '+' : ''}${tx.delta.toLocaleString()}`

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '28rpx 32rpx',
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      {/* Direction icon */}
      <View
        style={{
          width: '72rpx',
          height: '72rpx',
          borderRadius: '36rpx',
          background: earn ? 'rgba(76,175,80,0.15)' : 'rgba(229,57,53,0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          marginRight: '24rpx',
        }}
      >
        <Text
          style={{
            color: iconColor,
            fontSize: '36rpx',
            fontWeight: '700',
            lineHeight: '1',
          }}
        >
          {txIcon(tx)}
        </Text>
      </View>

      {/* Description block */}
      <View style={{ flex: 1 }}>
        <Text
          style={{
            color: C.text1,
            fontSize: '30rpx',
            fontWeight: '600',
            display: 'block',
            marginBottom: '6rpx',
          }}
        >
          {tx.description || txTypeLabel(tx.type)}
        </Text>
        <Text style={{ color: C.text2, fontSize: '24rpx' }}>
          {formatDate(tx.createdAt)}
        </Text>
      </View>

      {/* Points */}
      <Text
        style={{
          color: iconColor,
          fontSize: '36rpx',
          fontWeight: '700',
          flexShrink: 0,
        }}
      >
        {pointsStr}
      </Text>
    </View>
  )
}

// ─── 积分明细 tab ─────────────────────────────────────────────────────────────

const HistoryTab: React.FC = () => {
  const [filter, setFilter] = useState<FilterType>('all')
  const [items, setItems] = useState<PointsTransaction[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const loadingRef = useRef(false)

  const loadData = useCallback(async (reset: boolean, currentFilter: FilterType) => {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    try {
      const nextPage = reset ? 1 : page
      const res: PointsHistory = await getPointsHistory(nextPage, 20)
      let fetched = res.items ?? []

      // Client-side filter (server may not support filter query param)
      if (currentFilter === 'earn') fetched = fetched.filter(isEarn)
      if (currentFilter === 'spend') fetched = fetched.filter((tx) => !isEarn(tx))

      if (reset) {
        setItems(fetched)
        setPage(2)
      } else {
        setItems((prev) => [...prev, ...fetched])
        setPage((p) => p + 1)
      }

      setHasMore(fetched.length === 20)
    } catch (_e) {
      Taro.showToast({ title: '加载失败，请重试', icon: 'none' })
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [page])

  useEffect(() => {
    setPage(1)
    setItems([])
    setHasMore(true)
    loadData(true, filter)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  const handleLoadMore = useCallback(() => {
    if (!loading && hasMore) loadData(false, filter)
  }, [loading, hasMore, loadData, filter])

  return (
    <View>
      {/* Filter pills */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
          padding: '24rpx 32rpx 20rpx',
        }}
      >
        {FILTER_OPTIONS.map((opt) => {
          const active = filter === opt.value
          return (
            <View
              key={opt.value}
              style={{
                padding: '12rpx 32rpx',
                borderRadius: '40rpx',
                background: active ? C.primary : C.bgCard,
                border: `2rpx solid ${active ? C.primary : C.border}`,
              }}
              onClick={() => setFilter(opt.value)}
            >
              <Text
                style={{
                  color: active ? C.white : C.text2,
                  fontSize: '28rpx',
                  fontWeight: active ? '700' : '400',
                }}
              >
                {opt.label}
              </Text>
            </View>
          )
        })}
      </View>

      {/* List */}
      <View
        style={{
          background: C.bgCard,
          borderRadius: '24rpx',
          border: `2rpx solid ${C.border}`,
          overflow: 'hidden',
          marginBottom: '24rpx',
        }}
      >
        {items.length === 0 && !loading ? (
          <View
            style={{
              padding: '80rpx 0',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16rpx',
            }}
          >
            <Text style={{ fontSize: '64rpx', lineHeight: '1' }}>🪙</Text>
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无积分记录</Text>
          </View>
        ) : (
          items.map((tx) => <TxItem key={tx.txId} tx={tx} />)
        )}
      </View>

      {/* Load more */}
      {(hasMore || loading) && items.length > 0 && (
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24rpx 0 32rpx',
          }}
          onClick={handleLoadMore}
        >
          <Text style={{ color: loading ? C.text3 : C.primary, fontSize: '28rpx' }}>
            {loading ? '加载中…' : '加载更多'}
          </Text>
        </View>
      )}

      {!hasMore && items.length > 0 && (
        <View style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24rpx 0 32rpx' }}>
          <Text style={{ color: C.text3, fontSize: '24rpx' }}>— 已加载全部记录 —</Text>
        </View>
      )}
    </View>
  )
}

// ─── 积分规则 tab ─────────────────────────────────────────────────────────────

interface RuleItem {
  icon: string
  title: string
  desc: string
}

const RULES: RuleItem[] = [
  {
    icon: '🛍',
    title: '消费积分',
    desc: '每消费 1 元得 1 积分，实时到账。',
  },
  {
    icon: '🎂',
    title: '生日双倍',
    desc: '生日当月消费积分 ×2（银牌及以上会员专享）。',
  },
  {
    icon: '⏳',
    title: '积分有效期',
    desc: '自获得之日起 2 年内有效，到期自动清零。',
  },
  {
    icon: '💸',
    title: '积分使用',
    desc: '100 积分抵 1 元，单次最多抵扣订单金额的 20%。',
  },
  {
    icon: '🚫',
    title: '积分不可用于',
    desc: '储值卡充值、礼品卡购买。',
  },
]

const RulesTab: React.FC = () => (
  <View
    style={{
      background: C.bgCard,
      borderRadius: '24rpx',
      border: `2rpx solid ${C.border}`,
      overflow: 'hidden',
      marginBottom: '40rpx',
    }}
  >
    {RULES.map((rule, idx) => (
      <View
        key={rule.title}
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-start',
          padding: '28rpx 32rpx',
          borderBottom: idx < RULES.length - 1 ? `1rpx solid ${C.border}` : 'none',
          gap: '20rpx',
        }}
      >
        <Text style={{ fontSize: '40rpx', lineHeight: '1', flexShrink: 0, marginTop: '4rpx' }}>
          {rule.icon}
        </Text>
        <View style={{ flex: 1 }}>
          <Text
            style={{
              color: C.text1,
              fontSize: '30rpx',
              fontWeight: '700',
              display: 'block',
              marginBottom: '8rpx',
            }}
          >
            {rule.title}
          </Text>
          <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.6' }}>
            {rule.desc}
          </Text>
        </View>
      </View>
    ))}
  </View>
)

// ─── Page ─────────────────────────────────────────────────────────────────────

type TabKey = 'history' | 'rules'

const PointsPage: React.FC = () => {
  const { memberLevel, pointsBalance } = useUserStore()
  const [activeTab, setActiveTab] = useState<TabKey>('history')
  const [balance, setBalance] = useState(pointsBalance)

  useEffect(() => {
    Taro.setNavigationBarTitle({ title: '积分中心' })
    getPointsBalance()
      .then((res) => setBalance(res.currentPoints))
      .catch(() => {/* fallback to store value */})
  }, [])

  const nextLevel = NEXT_LEVEL_POINTS[memberLevel]
  const levelLabelMap: Record<string, string> = {
    bronze: '铜牌会员',
    silver: '银牌会员',
    gold: '金牌会员',
    diamond: '钻石会员',
  }

  return (
    <ScrollView scrollY style={{ minHeight: '100vh', background: C.bgDeep }}>
      <View style={{ padding: '32rpx 32rpx 0' }}>

        {/* Balance card */}
        <View style={{ marginBottom: '32rpx' }}>
          <PointsBalance
            points={balance}
            nextLevelPoints={nextLevel}
            level={levelLabelMap[memberLevel] ?? '会员'}
            onUse={() => setActiveTab('rules')}
          />
        </View>

        {/* 积分规则 link */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'flex-end',
            marginBottom: '24rpx',
          }}
        >
          <View
            onClick={() => setActiveTab('rules')}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '4rpx',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '26rpx' }}>积分规则</Text>
            <Text style={{ color: C.primary, fontSize: '26rpx' }}>›</Text>
          </View>
        </View>

        {/* Tab bar */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            background: C.bgCard,
            borderRadius: '20rpx',
            padding: '6rpx',
            marginBottom: '24rpx',
            border: `2rpx solid ${C.border}`,
          }}
        >
          {([
            { key: 'history', label: '积分明细' },
            { key: 'rules', label: '积分规则' },
          ] as { key: TabKey; label: string }[]).map((tab) => {
            const active = activeTab === tab.key
            return (
              <View
                key={tab.key}
                style={{
                  flex: 1,
                  height: '72rpx',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: '16rpx',
                  background: active ? C.primary : 'transparent',
                  transition: 'background 0.2s',
                }}
                onClick={() => setActiveTab(tab.key)}
              >
                <Text
                  style={{
                    color: active ? C.white : C.text2,
                    fontSize: '30rpx',
                    fontWeight: active ? '700' : '400',
                  }}
                >
                  {tab.label}
                </Text>
              </View>
            )
          })}
        </View>

        {/* Tab content */}
        {activeTab === 'history' ? <HistoryTab /> : <RulesTab />}
      </View>
    </ScrollView>
  )
}

export default PointsPage
