/**
 * AiChatAssistant — AI点餐助手（对标海底捞"小捞捞"）
 *
 * 菜单页底部悬浮按钮 → 展开对话式点餐面板
 * "4个人吃饭预算500有人海鲜过敏" → AI推荐菜单 → 一键加入购物车
 *
 * API: POST /api/v1/agent/chat (tx-agent MasterAgent)
 */

import React, { useState, useCallback, useRef } from 'react'
import { View, Text, Input, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../utils/request'
import { useCartStore } from '../../store/useCartStore'
import { useUserStore } from '../../store/useUserStore'

// ─── Colors ───────────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B2C',
  primaryBg: 'rgba(255,107,44,0.12)',
  aiBlue: '#185FA5',
  aiBlueBg: 'rgba(24,95,165,0.08)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgPanel: '#0E1820',
  border: '#1E3340',
  success: '#34C759',
  danger: '#FF3B30',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  dishes?: RecommendedDish[]
  allergenWarning?: string
}

interface RecommendedDish {
  id: string
  name: string
  price_fen: number
  reason: string
  allergens?: string[]
}

interface AiChatAssistantProps {
  storeId: string
}

// ─── Quick prompts ────────────────────────────────────────────────────────────

const QUICK_PROMPTS = [
  '4人聚餐推荐',
  '预算300选菜',
  '有人海鲜过敏',
  '适合小朋友的菜',
  '今日招牌菜',
  '低卡健康餐',
]

// ─── Component ────────────────────────────────────────────────────────────────

export function AiChatAssistant({ storeId }: AiChatAssistantProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '你好！我是AI点餐助手。告诉我用餐人数、预算和口味偏好，我来帮你推荐菜品。',
    },
  ])
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<string>('')
  const { addItem } = useCartStore()
  const { preferences } = useUserStore()

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return

    const userMsg: ChatMessage = {
      id: `u_${Date.now()}`,
      role: 'user',
      content: text.trim(),
    }
    setMessages(prev => [...prev, userMsg])
    setInputText('')
    setLoading(true)

    // 构建上下文（包含用户偏好和过敏信息）
    const context = {
      store_id: storeId,
      message: text.trim(),
      user_context: {
        allergies: preferences?.allergies || [],
        spicy_level: preferences?.spicy || 0,
        dietary: preferences?.sweet || '',
      },
    }

    try {
      const data = await txRequest<{
        reply: string
        recommended_dishes?: RecommendedDish[]
        allergen_warning?: string
      }>('/agent/chat', 'POST', context as unknown as Record<string, unknown>)

      const aiMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        role: 'assistant',
        content: data.reply || '让我为您推荐几道菜...',
        dishes: data.recommended_dishes,
        allergenWarning: data.allergen_warning,
      }
      setMessages(prev => [...prev, aiMsg])
    } catch {
      // 降级：本地推荐
      const aiMsg: ChatMessage = {
        id: `a_${Date.now()}`,
        role: 'assistant',
        content: '网络暂时不稳定，为您推荐我们的招牌菜品：',
        dishes: [
          { id: 'd01', name: '剁椒鱼头', price_fen: 8800, reason: '招牌必点，鲜辣开胃' },
          { id: 'd03', name: '口味虾', price_fen: 12800, reason: '季节限定，肉质鲜嫩' },
          { id: 'd02', name: '农家小炒肉', price_fen: 4200, reason: '下饭经典，老少皆宜' },
        ],
      }
      setMessages(prev => [...prev, aiMsg])
    }

    setLoading(false)
    scrollRef.current = `msg_${Date.now()}`
  }, [loading, storeId, preferences])

  const handleAddDish = (dish: RecommendedDish) => {
    addItem({
      id: dish.id,
      name: dish.name,
      priceFen: dish.price_fen,
      quantity: 1,
      specs: '',
      remark: '',
    })
    Taro.showToast({ title: `已加入 ${dish.name}`, icon: 'none', duration: 1500 })
  }

  const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(0)}`

  // ─── FAB Button ─────────────────────────────────────────────────────────────

  if (!isOpen) {
    return (
      <View
        onClick={() => setIsOpen(true)}
        style={{
          position: 'fixed',
          right: '32rpx',
          bottom: '200rpx',
          width: '96rpx',
          height: '96rpx',
          borderRadius: '50%',
          background: `linear-gradient(135deg, ${C.primary}, #FF8F5E)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 8rpx 24rpx rgba(255,107,44,0.4)',
          zIndex: 100,
        }}
      >
        <Text style={{ fontSize: '40rpx' }}>AI</Text>
      </View>
    )
  }

  // ─── Chat Panel ─────────────────────────────────────────────────────────────

  return (
    <View style={{
      position: 'fixed',
      left: 0, right: 0, bottom: 0,
      height: '70vh',
      background: C.bgPanel,
      borderRadius: '32rpx 32rpx 0 0',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 200,
      boxShadow: '0 -8rpx 32rpx rgba(0,0,0,0.3)',
    }}>
      {/* Header */}
      <View style={{
        padding: '24rpx 32rpx',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: `1rpx solid ${C.border}`,
      }}>
        <View style={{ display: 'flex', alignItems: 'center', gap: '12rpx' }}>
          <View style={{
            width: '48rpx', height: '48rpx', borderRadius: '50%',
            background: `linear-gradient(135deg, ${C.primary}, #FF8F5E)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Text style={{ fontSize: '24rpx', color: C.white }}>AI</Text>
          </View>
          <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1 }}>AI 点餐助手</Text>
        </View>
        <Text onClick={() => setIsOpen(false)} style={{ fontSize: '32rpx', color: C.text3, padding: '16rpx' }}>✕</Text>
      </View>

      {/* Messages */}
      <ScrollView
        scrollY
        scrollIntoView={scrollRef.current}
        style={{ flex: 1, padding: '16rpx 24rpx' }}
      >
        {messages.map(msg => (
          <View key={msg.id} id={`msg_${msg.id}`} style={{
            marginBottom: '20rpx',
            display: 'flex',
            flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
          }}>
            <View style={{
              maxWidth: '85%',
              padding: '20rpx 24rpx',
              borderRadius: msg.role === 'user' ? '20rpx 4rpx 20rpx 20rpx' : '4rpx 20rpx 20rpx 20rpx',
              background: msg.role === 'user' ? C.primary : C.bgCard,
            }}>
              <Text style={{ fontSize: '28rpx', color: C.text1, lineHeight: '40rpx' }}>{msg.content}</Text>

              {/* 过敏预警 */}
              {msg.allergenWarning && (
                <View style={{
                  marginTop: '12rpx', padding: '12rpx 16rpx', borderRadius: '12rpx',
                  background: 'rgba(255,59,48,0.1)', border: `1rpx solid ${C.danger}40`,
                }}>
                  <Text style={{ fontSize: '24rpx', color: C.danger }}>⚠️ {msg.allergenWarning}</Text>
                </View>
              )}

              {/* 推荐菜品卡片 */}
              {msg.dishes?.map(dish => (
                <View key={dish.id} style={{
                  marginTop: '12rpx', padding: '16rpx', borderRadius: '12rpx',
                  background: C.bgDeep, border: `1rpx solid ${C.border}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <View style={{ flex: 1 }}>
                    <View style={{ display: 'flex', alignItems: 'center', gap: '8rpx' }}>
                      <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1 }}>{dish.name}</Text>
                      <Text style={{ fontSize: '26rpx', color: C.primary, fontWeight: '600' }}>{fenToYuan(dish.price_fen)}</Text>
                    </View>
                    <Text style={{ fontSize: '22rpx', color: C.aiBlue, marginTop: '4rpx' }}>💡 {dish.reason}</Text>
                    {dish.allergens?.length ? (
                      <Text style={{ fontSize: '22rpx', color: C.danger, marginTop: '4rpx' }}>
                        ⚠️ 含: {dish.allergens.join('、')}
                      </Text>
                    ) : null}
                  </View>
                  <View
                    onClick={() => handleAddDish(dish)}
                    style={{
                      padding: '10rpx 20rpx', borderRadius: '8rpx', background: C.primary,
                      marginLeft: '12rpx', flexShrink: 0,
                    }}
                  >
                    <Text style={{ fontSize: '24rpx', color: C.white, fontWeight: '500' }}>+ 加入</Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        ))}

        {loading && (
          <View style={{ padding: '16rpx 24rpx' }}>
            <Text style={{ fontSize: '26rpx', color: C.text3 }}>AI 正在思考...</Text>
          </View>
        )}
      </ScrollView>

      {/* Quick prompts */}
      <ScrollView scrollX style={{ padding: '8rpx 24rpx', whiteSpace: 'nowrap' }}>
        {QUICK_PROMPTS.map(p => (
          <View
            key={p}
            onClick={() => sendMessage(p)}
            style={{
              display: 'inline-block',
              padding: '10rpx 20rpx', borderRadius: '24rpx', marginRight: '12rpx',
              background: C.aiBlueBg, border: `1rpx solid ${C.aiBlue}30`,
            }}
          >
            <Text style={{ fontSize: '24rpx', color: C.aiBlue }}>{p}</Text>
          </View>
        ))}
      </ScrollView>

      {/* Input */}
      <View style={{
        padding: '16rpx 24rpx 32rpx',
        display: 'flex', gap: '12rpx', alignItems: 'center',
        borderTop: `1rpx solid ${C.border}`,
      }}>
        <Input
          value={inputText}
          onInput={(e) => setInputText(e.detail.value)}
          onConfirm={() => sendMessage(inputText)}
          placeholder="描述用餐需求..."
          placeholderStyle={`color: ${C.text3}`}
          confirmType="send"
          style={{
            flex: 1, padding: '16rpx 24rpx', borderRadius: '32rpx',
            background: C.bgCard, border: `1rpx solid ${C.border}`,
            color: C.text1, fontSize: '28rpx',
          }}
        />
        <View
          onClick={() => sendMessage(inputText)}
          style={{
            width: '72rpx', height: '72rpx', borderRadius: '50%',
            background: inputText.trim() ? C.primary : C.bgCard,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Text style={{ fontSize: '28rpx', color: C.white }}>↑</Text>
        </View>
      </View>
    </View>
  )
}
