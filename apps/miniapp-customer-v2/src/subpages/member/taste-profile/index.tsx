/**
 * taste-profile — 口味档案 + 过敏原管理
 *
 * 辣度偏好 / 过敏原声明 / 饮食限制 / 口味标签
 * 跨门店跨品牌通用，点餐时自动过滤+预警
 *
 * API: PATCH /api/v1/member/preferences (tx-member已有)
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, Switch } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../../utils/request'
import { useUserStore } from '../../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  danger: '#FF3B30',
  dangerBg: 'rgba(255,59,48,0.08)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  success: '#34C759',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Options ──────────────────────────────────────────────────────────────────

const SPICY_LEVELS = [
  { value: 0, label: '不辣', emoji: '🫑' },
  { value: 1, label: '微辣', emoji: '🌶' },
  { value: 2, label: '中辣', emoji: '🌶🌶' },
  { value: 3, label: '重辣', emoji: '🌶🌶🌶' },
]

const ALLERGENS = [
  { id: 'seafood', label: '海鲜/甲壳类', emoji: '🦐' },
  { id: 'peanut', label: '花生/坚果', emoji: '🥜' },
  { id: 'dairy', label: '乳制品', emoji: '🥛' },
  { id: 'gluten', label: '麸质/小麦', emoji: '🌾' },
  { id: 'egg', label: '鸡蛋', emoji: '🥚' },
  { id: 'soy', label: '大豆', emoji: '🫘' },
  { id: 'sesame', label: '芝麻', emoji: '⚪' },
  { id: 'alcohol', label: '酒精', emoji: '🍷' },
]

const DIETARY = [
  { id: 'vegetarian', label: '素食', emoji: '🥬' },
  { id: 'vegan', label: '纯素', emoji: '🌱' },
  { id: 'halal', label: '清真', emoji: '☪️' },
  { id: 'low_carb', label: '低碳水', emoji: '🥩' },
  { id: 'sugar_free', label: '无糖', emoji: '🚫🍬' },
  { id: 'low_sodium', label: '少盐', emoji: '🧂' },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function TasteProfilePage() {
  const { preferences, updatePreferences } = useUserStore()
  const [spicyLevel, setSpicyLevel] = useState(preferences?.spicy || 0)
  const [allergens, setAllergens] = useState<string[]>(preferences?.allergies || [])
  const [dietary, setDietary] = useState<string[]>([])
  const [autoFilter, setAutoFilter] = useState(true)
  const [saving, setSaving] = useState(false)

  const toggleAllergen = (id: string) => {
    setAllergens(prev => prev.includes(id) ? prev.filter(a => a !== id) : [...prev, id])
  }

  const toggleDietary = (id: string) => {
    setDietary(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id])
  }

  const handleSave = useCallback(async () => {
    setSaving(true)
    const prefs = {
      spicy: spicyLevel,
      allergies: allergens,
      dietary,
      auto_filter: autoFilter,
    }
    try {
      await txRequest('/member/preferences', 'PUT', prefs as unknown as Record<string, unknown>)
      updatePreferences({ spicy: spicyLevel, allergies: allergens })
      Taro.showToast({ title: '保存成功', icon: 'success' })
      setTimeout(() => Taro.navigateBack(), 1000)
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' })
    }
    setSaving(false)
  }, [spicyLevel, allergens, dietary, autoFilter, updatePreferences])

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block' }}>口味档案</Text>
      <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx', marginBottom: '32rpx' }}>
        设置后跨门店跨品牌通用，点餐时自动提醒
      </Text>

      {/* 辣度 */}
      <Section title="辣度偏好">
        <View style={{ display: 'flex', gap: '16rpx' }}>
          {SPICY_LEVELS.map(level => (
            <View
              key={level.value}
              onClick={() => setSpicyLevel(level.value)}
              style={{
                flex: 1,
                padding: '20rpx 8rpx',
                borderRadius: '12rpx',
                textAlign: 'center',
                background: spicyLevel === level.value ? `${C.primary}20` : C.bgCard,
                border: spicyLevel === level.value ? `2rpx solid ${C.primary}` : `2rpx solid ${C.border}`,
              }}
            >
              <Text style={{ fontSize: '32rpx', display: 'block' }}>{level.emoji}</Text>
              <Text style={{
                fontSize: '24rpx', display: 'block', marginTop: '4rpx',
                color: spicyLevel === level.value ? C.primary : C.text2,
                fontWeight: spicyLevel === level.value ? '600' : '400',
              }}>{level.label}</Text>
            </View>
          ))}
        </View>
      </Section>

      {/* 过敏原 */}
      <Section title="过敏原声明" subtitle="选中的食材在点餐时会自动预警">
        {allergens.length > 0 && (
          <View style={{
            padding: '16rpx 20rpx', borderRadius: '12rpx', marginBottom: '16rpx',
            background: C.dangerBg, border: `1rpx solid ${C.danger}30`,
          }}>
            <Text style={{ fontSize: '24rpx', color: C.danger }}>
              ⚠️ 已标记 {allergens.length} 种过敏原，含相关食材的菜品会显示预警
            </Text>
          </View>
        )}
        <View style={{ display: 'flex', flexWrap: 'wrap', gap: '12rpx' }}>
          {ALLERGENS.map(a => {
            const selected = allergens.includes(a.id)
            return (
              <View
                key={a.id}
                onClick={() => toggleAllergen(a.id)}
                style={{
                  padding: '14rpx 24rpx',
                  borderRadius: '32rpx',
                  background: selected ? C.dangerBg : C.bgCard,
                  border: selected ? `2rpx solid ${C.danger}` : `2rpx solid ${C.border}`,
                  display: 'flex', alignItems: 'center', gap: '8rpx',
                }}
              >
                <Text style={{ fontSize: '24rpx' }}>{a.emoji}</Text>
                <Text style={{
                  fontSize: '26rpx',
                  color: selected ? C.danger : C.text2,
                  fontWeight: selected ? '600' : '400',
                }}>{a.label}</Text>
              </View>
            )
          })}
        </View>
      </Section>

      {/* 饮食限制 */}
      <Section title="饮食限制">
        <View style={{ display: 'flex', flexWrap: 'wrap', gap: '12rpx' }}>
          {DIETARY.map(d => {
            const selected = dietary.includes(d.id)
            return (
              <View
                key={d.id}
                onClick={() => toggleDietary(d.id)}
                style={{
                  padding: '14rpx 24rpx',
                  borderRadius: '32rpx',
                  background: selected ? `${C.success}15` : C.bgCard,
                  border: selected ? `2rpx solid ${C.success}` : `2rpx solid ${C.border}`,
                  display: 'flex', alignItems: 'center', gap: '8rpx',
                }}
              >
                <Text style={{ fontSize: '24rpx' }}>{d.emoji}</Text>
                <Text style={{
                  fontSize: '26rpx',
                  color: selected ? C.success : C.text2,
                  fontWeight: selected ? '600' : '400',
                }}>{d.label}</Text>
              </View>
            )
          })}
        </View>
      </Section>

      {/* 自动过滤 */}
      <View style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '24rpx', borderRadius: '16rpx', background: C.bgCard, marginTop: '24rpx',
      }}>
        <View>
          <Text style={{ fontSize: '28rpx', color: C.text1, display: 'block' }}>自动过滤</Text>
          <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>
            菜单中自动隐藏含过敏原的菜品
          </Text>
        </View>
        <Switch checked={autoFilter} onChange={(e) => setAutoFilter(e.detail.value)} color={C.primary} />
      </View>

      {/* 保存 */}
      <View
        onClick={handleSave}
        style={{
          marginTop: '48rpx',
          padding: '28rpx 0',
          borderRadius: '16rpx',
          background: saving ? C.bgCard : C.primary,
          textAlign: 'center',
          opacity: saving ? 0.6 : 1,
        }}
      >
        <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>
          {saving ? '保存中...' : '保存口味档案'}
        </Text>
      </View>
    </View>
  )
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: '32rpx' }}>
      <Text style={{ fontSize: '30rpx', fontWeight: '600', color: '#E8F4F8', display: 'block', marginBottom: '8rpx' }}>{title}</Text>
      {subtitle && <Text style={{ fontSize: '22rpx', color: '#5A7A88', display: 'block', marginBottom: '16rpx' }}>{subtitle}</Text>}
      {children}
    </View>
  )
}
