/**
 * stored-value/index.tsx — 储值卡页
 *
 * Features:
 *  - StoredValueCard component showing real balance
 *  - Recharge section: quick amount chips + custom input + bonus table
 *  - "立即充值" → PaymentSheet (wechat only) → POST recharge → success toast
 *  - Transaction history list with pull-down refresh
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { StoredValueCard } from '../../../components/StoredValueCard'
import { PaymentSheet } from '../../../components/PaymentSheet'
import { getStoredValueBalance, rechargeStoredValue } from '../../../api/trade'
import type { StoredValueBalance } from '../../../api/trade'
import { useUserStore } from '../../../store/useUserStore'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B35',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#4A6572',
  success: '#4CAF50',
  white: '#FFFFFF',
} as const

// ─── Recharge quick amounts ────────────────────────────────────────────────────

interface QuickAmount {
  yuan: number
  bonusYuan: number
}

const QUICK_AMOUNTS: QuickAmount[] = [
  { yuan: 50, bonusYuan: 0 },
  { yuan: 100, bonusYuan: 10 },
  { yuan: 200, bonusYuan: 25 },
  { yuan: 500, bonusYuan: 80 },
]

const BONUS_RULES: { amount: string; bonus: string }[] = [
  { amount: '充 ¥100', bonus: '送 ¥10' },
  { amount: '充 ¥200', bonus: '送 ¥25' },
  { amount: '充 ¥500', bonus: '送 ¥80' },
  { amount: '充 ¥1000', bonus: '送 ¥200' },
]

// ─── Tx history types ─────────────────────────────────────────────────────────

type TxHistoryType = '充值' | '消费' | '赠送'

interface StoredValueTx {
  id: string
  type: TxHistoryType
  amountFen: number   // positive = in, negative = out
  balanceAfterFen: number
  createdAt: string
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

function txTypeColor(type: TxHistoryType): string {
  if (type === '充值' || type === '赠送') return C.success
  return '#E53935'
}

function txAmountStr(tx: StoredValueTx): string {
  const sign = tx.amountFen >= 0 ? '+' : ''
  return `${sign}${fenToYuanDisplay(tx.amountFen)}`
}

// ─── Transaction item ─────────────────────────────────────────────────────────

const TxItem: React.FC<{ tx: StoredValueTx }> = ({ tx }) => {
  const color = txTypeColor(tx.type)
  const iconMap: Record<TxHistoryType, string> = {
    '充值': '💳',
    '消费': '🍽',
    '赠送': '🎁',
  }
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
      {/* Icon */}
      <View
        style={{
          width: '72rpx',
          height: '72rpx',
          borderRadius: '36rpx',
          background: tx.amountFen >= 0 ? 'rgba(76,175,80,0.15)' : 'rgba(229,57,53,0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          marginRight: '24rpx',
        }}
      >
        <Text style={{ fontSize: '36rpx', lineHeight: '1' }}>{iconMap[tx.type]}</Text>
      </View>

      {/* Info */}
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
          {tx.type}
        </Text>
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '12rpx' }}>
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>{formatDate(tx.createdAt)}</Text>
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>
            余额 {fenToYuanDisplay(tx.balanceAfterFen)}
          </Text>
        </View>
      </View>

      {/* Amount */}
      <Text style={{ color, fontSize: '34rpx', fontWeight: '700', flexShrink: 0 }}>
        {txAmountStr(tx)}
      </Text>
    </View>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

const StoredValuePage: React.FC = () => {
  const { userId, storedValueFen, setMemberInfo, memberLevel, pointsBalance } = useUserStore()

  // Balance state
  const [balanceFen, setBalanceFen] = useState(storedValueFen)
  const [cardNo] = useState(userId.slice(-8) || '00000000')

  // Recharge state
  const [selectedQuick, setSelectedQuick] = useState<number | null>(null)
  const [customAmount, setCustomAmount] = useState('')
  const [showPaySheet, setShowPaySheet] = useState(false)
  const [recharging, setRecharging] = useState(false)

  // History state
  const [txHistory, setTxHistory] = useState<StoredValueTx[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const loadedRef = useRef(false)

  // Compute amount to recharge in fen
  const rechargeFen = (() => {
    if (customAmount && Number(customAmount) > 0) {
      return Math.round(Number(customAmount) * 100)
    }
    if (selectedQuick !== null) return selectedQuick * 100
    return 0
  })()

  // Bonus for the selected amount
  const bonusForAmount = (yuan: number): number => {
    if (yuan >= 1000) return 200
    if (yuan >= 500) return 80
    if (yuan >= 200) return 25
    if (yuan >= 100) return 10
    return 0
  }
  const bonusYuan = bonusForAmount(rechargeFen / 100)

  useEffect(() => {
    Taro.setNavigationBarTitle({ title: '储值卡' })
    loadBalance()
    loadHistory(false)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadBalance = useCallback(async () => {
    try {
      const res: StoredValueBalance = await getStoredValueBalance(userId)
      setBalanceFen(res.balanceFen)
      setMemberInfo(memberLevel, pointsBalance, res.balanceFen)
    } catch (_e) {
      // fallback to store value
    }
  }, [userId, memberLevel, pointsBalance, setMemberInfo])

  const loadHistory = useCallback(async (isPullRefresh: boolean) => {
    if (isPullRefresh) setRefreshing(true)
    else setHistoryLoading(true)
    try {
      // Simulated history – in production this hits a real endpoint
      // e.g. GET /api/v1/stored-value/:memberId/transactions
      await new Promise<void>((r) => setTimeout(r, 600))
      // Placeholder empty list if not yet loaded
      if (!loadedRef.current) {
        setTxHistory([])
        loadedRef.current = true
      }
    } catch (_e) {
      Taro.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      setRefreshing(false)
      setHistoryLoading(false)
    }
  }, [])

  // Scroll-view pull-down refresh
  const handleRefresherRefresh = useCallback(() => {
    loadHistory(true)
    loadBalance()
  }, [loadHistory, loadBalance])

  const handleQuickSelect = useCallback((yuan: number) => {
    setSelectedQuick(yuan)
    setCustomAmount('')
  }, [])

  const handleCustomInput = useCallback((e: { detail: { value: string } }) => {
    setCustomAmount(e.detail.value)
    setSelectedQuick(null)
  }, [])

  const handleRechargeBtn = useCallback(() => {
    if (rechargeFen <= 0) {
      Taro.showToast({ title: '请选择或输入充值金额', icon: 'none' })
      return
    }
    setShowPaySheet(true)
  }, [rechargeFen])

  const handlePayConfirm = useCallback(async () => {
    setShowPaySheet(false)
    if (recharging) return
    setRecharging(true)
    try {
      // Only wechat flow for stored-value recharge
      Taro.showLoading({ title: '充值中…' })
      const res = await rechargeStoredValue(userId, rechargeFen)
      setBalanceFen(res.balanceAfterFen)
      setMemberInfo(memberLevel, pointsBalance, res.balanceAfterFen)
      // Append to history
      const newTx: StoredValueTx = {
        id: res.transactionId,
        type: '充值',
        amountFen: rechargeFen,
        balanceAfterFen: res.balanceAfterFen,
        createdAt: res.createdAt,
      }
      setTxHistory((prev) => [newTx, ...prev])
      setSelectedQuick(null)
      setCustomAmount('')
      Taro.hideLoading()
      Taro.showToast({ title: `充值成功！已到账 ${fenToYuanDisplay(rechargeFen)}`, icon: 'success', duration: 2500 })
    } catch (_e) {
      Taro.hideLoading()
      Taro.showToast({ title: '充值失败，请重试', icon: 'none', duration: 2000 })
    } finally {
      setRecharging(false)
    }
  }, [recharging, rechargeFen, userId, memberLevel, pointsBalance, setMemberInfo])

  return (
    <>
      <ScrollView
        scrollY
        refresherEnabled
        refresherTriggered={refreshing}
        onRefresherRefresh={handleRefresherRefresh}
        style={{ minHeight: '100vh', background: C.bgDeep }}
      >
        <View style={{ padding: '32rpx 32rpx 0' }}>

          {/* Stored-value card */}
          <View style={{ marginBottom: '32rpx' }}>
            <StoredValueCard
              balance_fen={balanceFen}
              gift_balance_fen={0}
              card_no={cardNo}
              onRecharge={() => {
                Taro.pageScrollTo({ selector: '#recharge-section', duration: 300 })
              }}
              onViewHistory={() => {
                Taro.pageScrollTo({ selector: '#history-section', duration: 300 })
              }}
            />
          </View>

          {/* ─── Recharge section ──────────────────────────────────── */}
          <View
            id="recharge-section"
            style={{
              background: C.bgCard,
              borderRadius: '24rpx',
              border: `2rpx solid ${C.border}`,
              padding: '28rpx 28rpx 32rpx',
              marginBottom: '28rpx',
            }}
          >
            <Text
              style={{
                color: C.text1,
                fontSize: '32rpx',
                fontWeight: '700',
                display: 'block',
                marginBottom: '24rpx',
              }}
            >
              充值
            </Text>

            {/* Quick amounts */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                flexWrap: 'wrap',
                gap: '16rpx',
                marginBottom: '24rpx',
              }}
            >
              {QUICK_AMOUNTS.map((qa) => {
                const active = selectedQuick === qa.yuan && !customAmount
                return (
                  <View
                    key={qa.yuan}
                    style={{
                      flex: '1 0 calc(50% - 8rpx)',
                      height: '96rpx',
                      background: active ? C.primary : C.bgHover,
                      border: `2rpx solid ${active ? C.primary : C.border}`,
                      borderRadius: '20rpx',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                    onClick={() => handleQuickSelect(qa.yuan)}
                  >
                    <Text
                      style={{
                        color: active ? C.white : C.text1,
                        fontSize: '32rpx',
                        fontWeight: '700',
                      }}
                    >
                      ¥{qa.yuan}
                    </Text>
                    {qa.bonusYuan > 0 && (
                      <Text
                        style={{
                          color: active ? 'rgba(255,255,255,0.8)' : C.primary,
                          fontSize: '22rpx',
                          marginTop: '4rpx',
                        }}
                      >
                        送 ¥{qa.bonusYuan}
                      </Text>
                    )}
                  </View>
                )
              })}
            </View>

            {/* Custom amount input */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                background: C.bgHover,
                border: `2rpx solid ${customAmount ? C.primary : C.border}`,
                borderRadius: '20rpx',
                padding: '0 28rpx',
                height: '96rpx',
                marginBottom: '28rpx',
              }}
            >
              <Text style={{ color: C.text2, fontSize: '32rpx', marginRight: '8rpx' }}>¥</Text>
              <Input
                type="digit"
                placeholder="自定义金额"
                placeholderStyle={`color: ${C.text3}; font-size: 30rpx;`}
                value={customAmount}
                onInput={handleCustomInput}
                style={{
                  flex: 1,
                  color: C.text1,
                  fontSize: '32rpx',
                  height: '96rpx',
                  lineHeight: '96rpx',
                }}
              />
            </View>

            {/* Bonus rules table */}
            <View
              style={{
                background: 'rgba(255,107,53,0.06)',
                border: '1rpx solid rgba(255,107,53,0.2)',
                borderRadius: '16rpx',
                padding: '20rpx 24rpx',
                marginBottom: '28rpx',
              }}
            >
              <Text
                style={{
                  color: C.primary,
                  fontSize: '24rpx',
                  fontWeight: '700',
                  display: 'block',
                  marginBottom: '14rpx',
                }}
              >
                充值赠送规则
              </Text>
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  flexWrap: 'wrap',
                  gap: '12rpx',
                }}
              >
                {BONUS_RULES.map((r) => (
                  <View
                    key={r.amount}
                    style={{
                      background: 'rgba(255,107,53,0.12)',
                      borderRadius: '12rpx',
                      padding: '8rpx 20rpx',
                      display: 'flex',
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: '8rpx',
                    }}
                  >
                    <Text style={{ color: C.text2, fontSize: '24rpx' }}>{r.amount}</Text>
                    <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '700' }}>
                      {r.bonus}
                    </Text>
                  </View>
                ))}
              </View>
            </View>

            {/* Bonus hint */}
            {rechargeFen > 0 && bonusYuan > 0 && (
              <View
                style={{
                  background: 'rgba(76,175,80,0.1)',
                  border: '1rpx solid rgba(76,175,80,0.3)',
                  borderRadius: '14rpx',
                  padding: '16rpx 24rpx',
                  marginBottom: '24rpx',
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: '12rpx',
                }}
              >
                <Text style={{ fontSize: '28rpx', lineHeight: '1' }}>🎁</Text>
                <Text style={{ color: C.success, fontSize: '26rpx', fontWeight: '600' }}>
                  本次充值将额外赠送 ¥{bonusYuan}
                </Text>
              </View>
            )}

            {/* Recharge button */}
            <View
              style={{
                height: '96rpx',
                background: rechargeFen > 0 ? C.primary : '#2A4050',
                borderRadius: '48rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: rechargeFen > 0 ? '0 4rpx 24rpx rgba(255,107,53,0.4)' : 'none',
              }}
              onClick={handleRechargeBtn}
            >
              <Text
                style={{
                  color: rechargeFen > 0 ? C.white : C.text3,
                  fontSize: '34rpx',
                  fontWeight: '700',
                }}
              >
                {rechargeFen > 0
                  ? `立即充值 ${fenToYuanDisplay(rechargeFen)}`
                  : '请选择或输入充值金额'}
              </Text>
            </View>
          </View>

          {/* ─── Transaction history ───────────────────────────────── */}
          <View id="history-section" style={{ marginBottom: '40rpx' }}>
            <Text
              style={{
                color: C.text1,
                fontSize: '32rpx',
                fontWeight: '700',
                display: 'block',
                marginBottom: '20rpx',
              }}
            >
              交易记录
            </Text>

            <View
              style={{
                background: C.bgCard,
                borderRadius: '24rpx',
                border: `2rpx solid ${C.border}`,
                overflow: 'hidden',
              }}
            >
              {historyLoading ? (
                <View
                  style={{
                    padding: '60rpx 0',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中…</Text>
                </View>
              ) : txHistory.length === 0 ? (
                <View
                  style={{
                    padding: '80rpx 0',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '16rpx',
                  }}
                >
                  <Text style={{ fontSize: '64rpx', lineHeight: '1' }}>💳</Text>
                  <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无交易记录</Text>
                  <Text style={{ color: C.text3, fontSize: '24rpx' }}>充值后记录将在此显示</Text>
                </View>
              ) : (
                txHistory.map((tx) => <TxItem key={tx.id} tx={tx} />)
              )}
            </View>

            {/* Pull-down refresh hint */}
            {txHistory.length > 0 && (
              <View
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: '20rpx 0',
                }}
              >
                <Text style={{ color: C.text3, fontSize: '22rpx' }}>下拉可刷新</Text>
              </View>
            )}
          </View>
        </View>
      </ScrollView>

      {/* Payment sheet — wechat only */}
      <PaymentSheet
        visible={showPaySheet}
        totalFen={rechargeFen}
        storedValueFen={0}
        onClose={() => setShowPaySheet(false)}
        onConfirm={handlePayConfirm}
      />
    </>
  )
}

export default StoredValuePage
