/**
 * gift-card/index.tsx — 礼品卡
 *
 * Three tabs:
 *  购买礼品卡 — Amount picker, custom amount, recipient, card design, purchase CTA
 *  我的礼品卡 — Card list: number, balance, expiry, reveal, transfer
 *  兑换礼品卡 — 16-digit code input, redeem → show credited amount + new balance
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { fenToYuanDisplay, fenToYuan } from '../../../utils/format'
import { useUserStore } from '../../../store/useUserStore'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  success: '#4CAF50',
  white: '#FFFFFF',
  gold: '#FFD700',
  disabled: '#2A3A44',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type TabKey = 'buy' | 'mine' | 'redeem'

interface Tab {
  key: TabKey
  label: string
}

const TABS: Tab[] = [
  { key: 'buy',    label: '购买礼品卡' },
  { key: 'mine',   label: '我的礼品卡' },
  { key: 'redeem', label: '兑换礼品卡' },
]

type CardDesign = 'general' | 'birthday' | 'holiday' | 'business'

interface CardDesignOption {
  key: CardDesign
  label: string
  gradient: [string, string]
  emoji: string
}

const CARD_DESIGNS: CardDesignOption[] = [
  { key: 'general',  label: '通用款', gradient: ['#1A2E3A', '#0B1A20'], emoji: '🎴' },
  { key: 'birthday', label: '生日款', gradient: ['#4A1A2E', '#2E0B1A'], emoji: '🎂' },
  { key: 'holiday',  label: '节日款', gradient: ['#1A3A1A', '#0B200B'], emoji: '🎉' },
  { key: 'business', label: '商务款', gradient: ['#1A1A3A', '#0B0B20'], emoji: '💼' },
]

const PRESET_AMOUNTS = [50, 100, 200, 500]

type RecipientType = 'self' | 'friend'

export interface MyGiftCard {
  cardId: string
  cardNumber: string
  balanceFen: number
  originalAmountFen: number
  expiresAt: string
  status: 'active' | 'depleted' | 'expired' | 'transferred'
  isRevealed?: boolean
}

interface RedeemResult {
  creditedFen: number
  newBalanceFen: number
  cardNumber: string
}

// ─── Tab bar ──────────────────────────────────────────────────────────────────

interface TabBarProps {
  activeTab: TabKey
  onTabChange: (tab: TabKey) => void
}

function TabBar({ activeTab, onTabChange }: TabBarProps) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        background: C.bgCard,
        margin: '16rpx 24rpx',
        borderRadius: '20rpx',
        padding: '6rpx',
        border: `1rpx solid ${C.border}`,
      }}
    >
      {TABS.map((tab) => {
        const active = tab.key === activeTab
        return (
          <View
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            style={{
              flex: 1,
              textAlign: 'center',
              padding: '16rpx 8rpx',
              borderRadius: '16rpx',
              background: active ? C.primary : 'transparent',
              transition: 'background 0.2s',
            }}
          >
            <Text
              style={{
                color: active ? C.white : C.text3,
                fontSize: '26rpx',
                fontWeight: active ? '700' : '400',
              }}
            >
              {tab.label}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

// ─── Buy tab ──────────────────────────────────────────────────────────────────

function BuyTab() {
  const [selectedAmount, setSelectedAmount] = useState<number | null>(100)
  const [customAmount, setCustomAmount] = useState('')
  const [recipient, setRecipient] = useState<RecipientType>('self')
  const [friendPhone, setFriendPhone] = useState('')
  const [message, setMessage] = useState('')
  const [selectedDesign, setSelectedDesign] = useState<CardDesign>('general')
  const [purchasing, setPurchasing] = useState(false)

  const effectiveAmount = customAmount
    ? parseInt(customAmount, 10) || 0
    : selectedAmount ?? 0

  const handleCustomAmountChange = (e: any) => {
    const val = e.detail.value as string
    // Only digits, cap at 4 chars
    const clean = val.replace(/\D/g, '').slice(0, 4)
    setCustomAmount(clean)
    if (clean) setSelectedAmount(null)
  }

  const handlePresetSelect = (amount: number) => {
    setSelectedAmount(amount)
    setCustomAmount('')
  }

  const validateAndPurchase = useCallback(async () => {
    if (effectiveAmount < 50 || effectiveAmount > 2000) {
      Taro.showToast({ title: '金额须在50-2000元之间', icon: 'none', duration: 2000 })
      return
    }
    if (recipient === 'friend') {
      if (!/^1[3-9]\d{9}$/.test(friendPhone)) {
        Taro.showToast({ title: '请输入正确的手机号', icon: 'none', duration: 2000 })
        return
      }
    }

    setPurchasing(true)
    try {
      await txRequest('/api/v1/gift-cards/purchase', 'POST', {
        amountFen: effectiveAmount * 100,
        design: selectedDesign,
        recipient: recipient === 'friend' ? { phone: friendPhone, message } : null,
      })
      Taro.showToast({ title: '购买成功！', icon: 'success', duration: 2000 })
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '购买失败', icon: 'none', duration: 2000 })
    } finally {
      setPurchasing(false)
    }
  }, [effectiveAmount, recipient, friendPhone, message, selectedDesign])

  const activeDesign = CARD_DESIGNS.find((d) => d.key === selectedDesign)!

  return (
    <ScrollView scrollY style={{ flex: 1 }}>
      {/* Card preview */}
      <View style={{ margin: '0 24rpx 24rpx' }}>
        <View
          style={{
            height: '240rpx',
            borderRadius: '24rpx',
            background: `linear-gradient(135deg, ${activeDesign.gradient[0]}, ${activeDesign.gradient[1]})`,
            border: `1rpx solid ${C.primary}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {/* Decorative circles */}
          <View
            style={{
              position: 'absolute',
              top: '-40rpx',
              right: '-40rpx',
              width: '200rpx',
              height: '200rpx',
              borderRadius: '50%',
              background: 'rgba(255,107,53,0.08)',
            }}
          />
          <View
            style={{
              position: 'absolute',
              bottom: '-60rpx',
              left: '-30rpx',
              width: '240rpx',
              height: '240rpx',
              borderRadius: '50%',
              background: 'rgba(255,107,53,0.05)',
            }}
          />
          <Text style={{ fontSize: '64rpx', marginBottom: '12rpx' }}>{activeDesign.emoji}</Text>
          <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>
            屯象OS 礼品卡
          </Text>
          <Text style={{ color: C.primary, fontSize: '48rpx', fontWeight: '800', marginTop: '8rpx' }}>
            ¥{effectiveAmount > 0 ? effectiveAmount : '---'}
          </Text>
          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '8rpx' }}>
            {activeDesign.label}
          </Text>
        </View>
      </View>

      {/* Amount presets */}
      <SectionHeader title="选择金额" />
      <View
        style={{
          margin: '0 24rpx 8rpx',
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: '16rpx',
        }}
      >
        {PRESET_AMOUNTS.map((amt) => {
          const active = selectedAmount === amt && !customAmount
          return (
            <View
              key={amt}
              onClick={() => handlePresetSelect(amt)}
              style={{
                width: 'calc(50% - 8rpx)',
                padding: '24rpx 0',
                textAlign: 'center',
                background: active ? `rgba(255,107,53,0.12)` : C.bgCard,
                borderRadius: '16rpx',
                border: `2rpx solid ${active ? C.primary : C.border}`,
              }}
            >
              <Text
                style={{
                  color: active ? C.primary : C.text1,
                  fontSize: '36rpx',
                  fontWeight: '700',
                }}
              >
                ¥{amt}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Custom amount */}
      <View style={{ margin: '16rpx 24rpx' }}>
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            background: C.bgCard,
            borderRadius: '16rpx',
            border: `1rpx solid ${customAmount ? C.primary : C.border}`,
            padding: '20rpx 24rpx',
          }}
        >
          <Text style={{ color: C.text3, fontSize: '28rpx', marginRight: '12rpx' }}>¥</Text>
          <Input
            type='number'
            placeholder='自定义金额 (50-2000)'
            placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
            value={customAmount}
            onInput={handleCustomAmountChange}
            style={{ flex: 1, color: C.text1, fontSize: '28rpx' }}
          />
        </View>
      </View>

      {/* Recipient */}
      <SectionHeader title="收件人" />
      <View
        style={{
          margin: '0 24rpx 16rpx',
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
        }}
      >
        {(['self', 'friend'] as RecipientType[]).map((type) => {
          const active = recipient === type
          return (
            <View
              key={type}
              onClick={() => setRecipient(type)}
              style={{
                flex: 1,
                padding: '20rpx 0',
                textAlign: 'center',
                background: active ? `rgba(255,107,53,0.12)` : C.bgCard,
                borderRadius: '16rpx',
                border: `2rpx solid ${active ? C.primary : C.border}`,
              }}
            >
              <Text style={{ color: active ? C.primary : C.text2, fontSize: '28rpx', fontWeight: '600' }}>
                {type === 'self' ? '送给自己' : '送给朋友'}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Friend details */}
      {recipient === 'friend' && (
        <View style={{ margin: '0 24rpx 16rpx', display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
          <View
            style={{
              background: C.bgCard,
              borderRadius: '16rpx',
              border: `1rpx solid ${C.border}`,
              padding: '20rpx 24rpx',
            }}
          >
            <Input
              type='number'
              placeholder='朋友手机号'
              placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
              value={friendPhone}
              onInput={(e) => setFriendPhone(e.detail.value)}
              maxlength={11}
              style={{ color: C.text1, fontSize: '28rpx' }}
            />
          </View>
          <View
            style={{
              background: C.bgCard,
              borderRadius: '16rpx',
              border: `1rpx solid ${C.border}`,
              padding: '20rpx 24rpx',
            }}
          >
            <Input
              placeholder='寄语（选填，最多50字）'
              placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
              value={message}
              onInput={(e) => setMessage(e.detail.value.slice(0, 50))}
              maxlength={50}
              style={{ color: C.text1, fontSize: '28rpx' }}
            />
          </View>
        </View>
      )}

      {/* Card design picker */}
      <SectionHeader title="选择卡面" />
      <ScrollView scrollX style={{ margin: '0 24rpx 24rpx' }}>
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx', paddingBottom: '4rpx' }}>
          {CARD_DESIGNS.map((design) => {
            const active = selectedDesign === design.key
            return (
              <View
                key={design.key}
                onClick={() => setSelectedDesign(design.key)}
                style={{
                  width: '160rpx',
                  flexShrink: 0,
                }}
              >
                {/* Design swatch */}
                <View
                  style={{
                    height: '100rpx',
                    borderRadius: '16rpx',
                    background: `linear-gradient(135deg, ${design.gradient[0]}, ${design.gradient[1]})`,
                    border: `2rpx solid ${active ? C.primary : C.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: '8rpx',
                  }}
                >
                  <Text style={{ fontSize: '40rpx' }}>{design.emoji}</Text>
                </View>
                <Text
                  style={{
                    color: active ? C.primary : C.text3,
                    fontSize: '24rpx',
                    textAlign: 'center',
                    display: 'block',
                    fontWeight: active ? '600' : '400',
                  }}
                >
                  {design.label}
                </Text>
              </View>
            )
          })}
        </View>
      </ScrollView>

      {/* Purchase CTA */}
      <View style={{ margin: '8rpx 24rpx 48rpx' }}>
        <View
          onClick={purchasing ? undefined : validateAndPurchase}
          style={{
            background: purchasing ? C.disabled : C.primary,
            borderRadius: '48rpx',
            padding: '28rpx 0',
            textAlign: 'center',
          }}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {purchasing ? '处理中…' : `立即购买 ¥${effectiveAmount || '--'}`}
          </Text>
        </View>
      </View>
    </ScrollView>
  )
}

// ─── My cards tab ─────────────────────────────────────────────────────────────

function MyCardsTab() {
  const [cards, setCards] = useState<MyGiftCard[]>([])
  const [loading, setLoading] = useState(true)
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set())
  const [transferringId, setTransferringId] = useState<string | null>(null)
  const [transferPhone, setTransferPhone] = useState('')

  useEffect(() => {
    txRequest<MyGiftCard[]>('/api/v1/gift-cards/mine')
      .then((data) => setCards(data))
      .catch(() => setCards([]))
      .finally(() => setLoading(false))
  }, [])

  const handleReveal = useCallback((cardId: string) => {
    setRevealedIds((prev) => new Set([...prev, cardId]))
  }, [])

  const handleTransfer = useCallback(
    async (cardId: string) => {
      if (!/^1[3-9]\d{9}$/.test(transferPhone)) {
        Taro.showToast({ title: '请输入正确的手机号', icon: 'none', duration: 2000 })
        return
      }
      try {
        await txRequest('/api/v1/gift-cards/transfer', 'POST', { cardId, toPhone: transferPhone })
        Taro.showToast({ title: '转赠成功！', icon: 'success', duration: 1500 })
        setCards((prev) =>
          prev.map((c) => (c.cardId === cardId ? { ...c, status: 'transferred' } : c)),
        )
        setTransferringId(null)
        setTransferPhone('')
      } catch (err: any) {
        Taro.showToast({ title: err?.message ?? '转赠失败', icon: 'none', duration: 2000 })
      }
    },
    [transferPhone],
  )

  if (loading) {
    return (
      <View style={{ padding: '80rpx', textAlign: 'center' }}>
        <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中…</Text>
      </View>
    )
  }

  if (cards.length === 0) {
    return (
      <View style={{ padding: '80rpx 48rpx', textAlign: 'center' }}>
        <Text style={{ fontSize: '80rpx', display: 'block', marginBottom: '20rpx' }}>🎴</Text>
        <Text style={{ color: C.text3, fontSize: '28rpx' }}>暂无礼品卡</Text>
        <Text style={{ color: C.text3, fontSize: '24rpx', display: 'block', marginTop: '8rpx' }}>
          购买或兑换礼品卡后将在此显示
        </Text>
      </View>
    )
  }

  const statusInfo = (status: MyGiftCard['status']) => {
    switch (status) {
      case 'active':      return { label: '可用',  color: C.success }
      case 'depleted':    return { label: '已用完', color: C.text3 }
      case 'expired':     return { label: '已过期', color: C.text3 }
      case 'transferred': return { label: '已转赠', color: C.text3 }
    }
  }

  function maskCardNumber(num: string) {
    if (num.length <= 4) return num
    return '**** **** **** ' + num.slice(-4)
  }

  function formatCardNumber(num: string) {
    return num.replace(/(\d{4})(?=\d)/g, '$1 ').trim()
  }

  function formatExpiry(iso: string) {
    if (!iso) return '--'
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  return (
    <ScrollView scrollY style={{ flex: 1, padding: '0 24rpx' }}>
      <View style={{ display: 'flex', flexDirection: 'column', gap: '20rpx', paddingBottom: '48rpx' }}>
        {cards.map((card) => {
          const revealed = revealedIds.has(card.cardId)
          const { label: statusLabel, color: statusColor } = statusInfo(card.status)
          const canTransfer = card.status === 'active' && card.balanceFen === card.originalAmountFen
          const isTransferring = transferringId === card.cardId

          return (
            <View
              key={card.cardId}
              style={{
                background: C.bgCard,
                borderRadius: '24rpx',
                border: `1rpx solid ${C.border}`,
                overflow: 'hidden',
              }}
            >
              {/* Card header */}
              <View
                style={{
                  background: `linear-gradient(135deg, #1A2E3A, ${C.bgDeep})`,
                  padding: '28rpx',
                  position: 'relative',
                }}
              >
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                  }}
                >
                  <View>
                    <Text style={{ color: C.text3, fontSize: '22rpx', display: 'block', marginBottom: '8rpx' }}>
                      屯象OS 礼品卡
                    </Text>
                    <Text
                      style={{
                        color: C.text2,
                        fontSize: '26rpx',
                        fontFamily: 'monospace',
                        letterSpacing: '4rpx',
                      }}
                    >
                      {revealed ? formatCardNumber(card.cardNumber) : maskCardNumber(card.cardNumber)}
                    </Text>
                  </View>
                  <View
                    style={{
                      background: `${statusColor}22`,
                      borderRadius: '12rpx',
                      padding: '6rpx 16rpx',
                      border: `1rpx solid ${statusColor}`,
                    }}
                  >
                    <Text style={{ color: statusColor, fontSize: '22rpx', fontWeight: '600' }}>
                      {statusLabel}
                    </Text>
                  </View>
                </View>

                <View
                  style={{
                    marginTop: '20rpx',
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'flex-end',
                  }}
                >
                  <View>
                    <Text style={{ color: C.text3, fontSize: '22rpx', display: 'block' }}>余额</Text>
                    <Text style={{ color: C.primary, fontSize: '48rpx', fontWeight: '800' }}>
                      {fenToYuanDisplay(card.balanceFen)}
                    </Text>
                  </View>
                  <Text style={{ color: C.text3, fontSize: '22rpx' }}>
                    有效期至 {formatExpiry(card.expiresAt)}
                  </Text>
                </View>
              </View>

              {/* Actions */}
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  borderTop: `1rpx solid ${C.border}`,
                }}
              >
                {!revealed && (
                  <View
                    onClick={() => handleReveal(card.cardId)}
                    style={{
                      flex: 1,
                      padding: '20rpx',
                      textAlign: 'center',
                      borderRight: canTransfer ? `1rpx solid ${C.border}` : 'none',
                    }}
                  >
                    <Text style={{ color: C.text2, fontSize: '26rpx' }}>查看卡号</Text>
                  </View>
                )}
                {canTransfer && (
                  <View
                    onClick={() =>
                      setTransferringId(isTransferring ? null : card.cardId)
                    }
                    style={{
                      flex: 1,
                      padding: '20rpx',
                      textAlign: 'center',
                    }}
                  >
                    <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
                      转赠
                    </Text>
                  </View>
                )}
              </View>

              {/* Transfer panel */}
              {isTransferring && (
                <View
                  style={{
                    padding: '24rpx',
                    borderTop: `1rpx solid ${C.border}`,
                    background: C.bgDeep,
                  }}
                >
                  <Text
                    style={{
                      color: C.text3,
                      fontSize: '24rpx',
                      display: 'block',
                      marginBottom: '12rpx',
                    }}
                  >
                    输入对方手机号
                  </Text>
                  <View
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      gap: '16rpx',
                    }}
                  >
                    <View
                      style={{
                        flex: 1,
                        background: C.bgCard,
                        borderRadius: '12rpx',
                        border: `1rpx solid ${C.border}`,
                        padding: '16rpx 20rpx',
                      }}
                    >
                      <Input
                        type='number'
                        placeholder='手机号'
                        placeholderStyle={`color: ${C.text3}; font-size: 26rpx;`}
                        value={transferPhone}
                        onInput={(e) => setTransferPhone(e.detail.value)}
                        maxlength={11}
                        style={{ color: C.text1, fontSize: '26rpx' }}
                      />
                    </View>
                    <View
                      onClick={() => handleTransfer(card.cardId)}
                      style={{
                        background: C.primary,
                        borderRadius: '12rpx',
                        padding: '16rpx 28rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <Text style={{ color: C.white, fontSize: '26rpx', fontWeight: '600' }}>
                        确认
                      </Text>
                    </View>
                  </View>
                </View>
              )}
            </View>
          )
        })}
      </View>
    </ScrollView>
  )
}

// ─── Redeem tab ───────────────────────────────────────────────────────────────

function RedeemTab() {
  const [cardNumber, setCardNumber] = useState('')
  const [redeeming, setRedeeming] = useState(false)
  const [result, setResult] = useState<RedeemResult | null>(null)

  const handleInput = (e: any) => {
    // Only digits, up to 16
    const clean = (e.detail.value as string).replace(/\D/g, '').slice(0, 16)
    setCardNumber(clean)
    setResult(null)
  }

  const handleRedeem = useCallback(async () => {
    if (cardNumber.length !== 16) {
      Taro.showToast({ title: '请输入完整的16位卡号', icon: 'none', duration: 2000 })
      return
    }
    setRedeeming(true)
    try {
      const res = await txRequest<RedeemResult>('/api/v1/gift-cards/redeem', 'POST', {
        cardNumber,
      })
      setResult(res)
      Taro.showToast({ title: '兑换成功！', icon: 'success', duration: 1500 })
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '兑换失败', icon: 'none', duration: 2000 })
    } finally {
      setRedeeming(false)
    }
  }, [cardNumber])

  // Format display with spaces every 4 digits
  const displayNumber = cardNumber
    .split('')
    .reduce((acc, ch, i) => (i > 0 && i % 4 === 0 ? acc + ' ' + ch : acc + ch), '')

  return (
    <View style={{ flex: 1, padding: '32rpx 24rpx' }}>
      {/* Input section */}
      <View
        style={{
          background: C.bgCard,
          borderRadius: '24rpx',
          border: `1rpx solid ${C.border}`,
          padding: '32rpx',
          marginBottom: '32rpx',
        }}
      >
        <Text
          style={{
            color: C.text2,
            fontSize: '28rpx',
            fontWeight: '600',
            display: 'block',
            marginBottom: '20rpx',
          }}
        >
          输入礼品卡号
        </Text>

        {/* Card number display */}
        <View
          style={{
            background: C.bgDeep,
            borderRadius: '16rpx',
            padding: '24rpx',
            marginBottom: '20rpx',
            border: `2rpx solid ${cardNumber.length === 16 ? C.primary : C.border}`,
          }}
        >
          <Text
            style={{
              color: cardNumber ? C.text1 : C.text3,
              fontSize: '36rpx',
              fontFamily: 'monospace',
              letterSpacing: '6rpx',
              display: 'block',
              textAlign: 'center',
            }}
          >
            {displayNumber || '**** **** **** ****'}
          </Text>
        </View>

        {/* Hidden real input */}
        <Input
          type='number'
          placeholder='点击输入16位卡号'
          placeholderStyle={`color: ${C.text3}; font-size: 26rpx; text-align: center;`}
          value={cardNumber}
          onInput={handleInput}
          maxlength={16}
          style={{
            color: C.text1,
            fontSize: '28rpx',
            textAlign: 'center',
            background: C.bgHover,
            borderRadius: '12rpx',
            padding: '16rpx',
          }}
        />

        <Text
          style={{
            color: C.text3,
            fontSize: '22rpx',
            display: 'block',
            textAlign: 'center',
            marginTop: '12rpx',
          }}
        >
          {cardNumber.length}/16 位
        </Text>
      </View>

      {/* Redeem button */}
      <View
        onClick={redeeming ? undefined : handleRedeem}
        style={{
          background: redeeming || cardNumber.length !== 16 ? C.disabled : C.primary,
          borderRadius: '48rpx',
          padding: '28rpx 0',
          textAlign: 'center',
          marginBottom: '32rpx',
          opacity: cardNumber.length !== 16 && !redeeming ? 0.7 : 1,
        }}
      >
        <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
          {redeeming ? '兑换中…' : '立即兑换'}
        </Text>
      </View>

      {/* Success result */}
      {result && (
        <View
          style={{
            background: 'rgba(76,175,80,0.08)',
            borderRadius: '24rpx',
            border: `1rpx solid ${C.success}`,
            padding: '32rpx',
            textAlign: 'center',
          }}
        >
          <Text style={{ fontSize: '56rpx', display: 'block', marginBottom: '16rpx' }}>🎉</Text>
          <Text
            style={{
              color: C.success,
              fontSize: '32rpx',
              fontWeight: '700',
              display: 'block',
              marginBottom: '8rpx',
            }}
          >
            兑换成功！
          </Text>
          <Text style={{ color: C.text2, fontSize: '28rpx', display: 'block', marginBottom: '4rpx' }}>
            已充值{' '}
            <Text style={{ color: C.primary, fontWeight: '700' }}>
              {fenToYuanDisplay(result.creditedFen)}
            </Text>{' '}
            到您的账户
          </Text>
          <Text style={{ color: C.text3, fontSize: '24rpx' }}>
            账户余额：{fenToYuanDisplay(result.newBalanceFen)}
          </Text>
        </View>
      )}

      {/* Instructions */}
      {!result && (
        <View
          style={{
            background: C.bgCard,
            borderRadius: '20rpx',
            padding: '24rpx 28rpx',
            border: `1rpx solid ${C.border}`,
          }}
        >
          <Text
            style={{
              color: C.text3,
              fontSize: '24rpx',
              display: 'block',
              marginBottom: '8rpx',
            }}
          >
            使用说明：
          </Text>
          {[
            '礼品卡号共16位纯数字',
            '兑换成功后余额立即到账，可在下单时使用',
            '每张礼品卡仅可兑换一次',
            '礼品卡有效期以卡面标注为准',
          ].map((tip, i) => (
            <Text key={i} style={{ color: C.text3, fontSize: '24rpx', display: 'block', marginTop: '6rpx' }}>
              · {tip}
            </Text>
          ))}
        </View>
      )}
    </View>
  )
}

// ─── Shared section header ────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return (
    <Text
      style={{
        color: C.text2,
        fontSize: '26rpx',
        fontWeight: '600',
        display: 'block',
        margin: '24rpx 24rpx 12rpx',
      }}
    >
      {title}
    </Text>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function GiftCardPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('buy')

  return (
    <View
      style={{
        height: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Page title */}
      <View
        style={{
          padding: '40rpx 32rpx 8rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
        }}
      >
        <View
          style={{
            width: '8rpx',
            height: '40rpx',
            background: C.primary,
            borderRadius: '4rpx',
            marginRight: '16rpx',
          }}
        />
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          礼品卡
        </Text>
      </View>

      {/* Tab bar */}
      <TabBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Tab content */}
      <View style={{ flex: 1, overflow: 'hidden' }}>
        {activeTab === 'buy'    && <BuyTab />}
        {activeTab === 'mine'   && <MyCardsTab />}
        {activeTab === 'redeem' && <RedeemTab />}
      </View>
    </View>
  )
}
