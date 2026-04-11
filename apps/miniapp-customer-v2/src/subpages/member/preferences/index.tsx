/**
 * preferences/index.tsx — 口味偏好页
 *
 * Features:
 *  - Header subtitle: "记住您的口味，每次推荐更精准"
 *  - Preference groups (single-select chips): 辣度 / 甜度 / 温度
 *  - Multi-select chip groups: 口味偏好 / 忌口
 *  - Save button → PUT /api/v1/members/me/preferences
 *  - Success toast with AI hint message
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { updatePreferences } from '../../../api/member'
import { useUserStore } from '../../../store/useUserStore'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B35',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#4A6572',
  white: '#FFFFFF',
} as const

// ─── Preference group definitions ─────────────────────────────────────────────

interface SingleGroup {
  type: 'single'
  key: 'spicy' | 'sweet' | 'temperature'
  label: string
  icon: string
  options: string[]
}

interface MultiGroup {
  type: 'multi'
  key: 'flavors' | 'avoidances'
  label: string
  icon: string
  options: string[]
}

type PrefGroup = SingleGroup | MultiGroup

const PREF_GROUPS: PrefGroup[] = [
  {
    type: 'single',
    key: 'spicy',
    label: '辣度',
    icon: '🌶',
    options: ['不辣', '微辣', '中辣', '重辣'],
  },
  {
    type: 'single',
    key: 'sweet',
    label: '甜度',
    icon: '🍯',
    options: ['不甜', '微甜', '适中', '较甜'],
  },
  {
    type: 'single',
    key: 'temperature',
    label: '温度',
    icon: '🌡',
    options: ['冷饮', '常温', '温热', '热饮'],
  },
  {
    type: 'multi',
    key: 'flavors',
    label: '口味偏好',
    icon: '✨',
    options: ['清淡', '鲜香', '浓郁', '酸爽', '咸鲜'],
  },
  {
    type: 'multi',
    key: 'avoidances',
    label: '忌口',
    icon: '🚫',
    options: ['无特殊', '不吃葱', '不吃蒜', '不吃香菜', '不吃辣椒', '不吃海鲜', '素食'],
  },
]

// ─── State shape ──────────────────────────────────────────────────────────────

interface PrefsState {
  spicy: string
  sweet: string
  temperature: string
  flavors: string[]
  avoidances: string[]
}

const DEFAULT_STATE: PrefsState = {
  spicy: '',
  sweet: '',
  temperature: '',
  flavors: [],
  avoidances: [],
}

// ─── Chip component ───────────────────────────────────────────────────────────

interface ChipProps {
  label: string
  selected: boolean
  onSelect: () => void
}

const Chip: React.FC<ChipProps> = ({ label, selected, onSelect }) => (
  <View
    style={{
      padding: '14rpx 32rpx',
      borderRadius: '40rpx',
      background: selected ? C.primary : C.bgCard,
      border: `2rpx solid ${selected ? C.primary : C.border}`,
      transition: 'background 0.15s, border 0.15s',
    }}
    onClick={onSelect}
  >
    <Text
      style={{
        color: selected ? C.white : C.text2,
        fontSize: '28rpx',
        fontWeight: selected ? '700' : '400',
      }}
    >
      {label}
    </Text>
  </View>
)

// ─── Group card ───────────────────────────────────────────────────────────────

interface GroupCardProps {
  group: PrefGroup
  prefs: PrefsState
  onSingleChange: (key: SingleGroup['key'], value: string) => void
  onMultiToggle: (key: MultiGroup['key'], value: string) => void
}

const GroupCard: React.FC<GroupCardProps> = ({ group, prefs, onSingleChange, onMultiToggle }) => (
  <View
    style={{
      background: C.bgCard,
      borderRadius: '24rpx',
      border: `2rpx solid ${C.border}`,
      padding: '28rpx 28rpx 24rpx',
      marginBottom: '20rpx',
    }}
  >
    {/* Group header */}
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: '12rpx',
        marginBottom: '20rpx',
      }}
    >
      <Text style={{ fontSize: '32rpx', lineHeight: '1' }}>{group.icon}</Text>
      <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>
        {group.label}
      </Text>
      {group.type === 'multi' && (
        <Text style={{ color: C.text3, fontSize: '22rpx', marginLeft: '4rpx' }}>(可多选)</Text>
      )}
    </View>

    {/* Chips */}
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: '16rpx',
      }}
    >
      {group.options.map((opt) => {
        let selected = false
        if (group.type === 'single') {
          selected = prefs[group.key] === opt
        } else {
          selected = prefs[group.key].includes(opt)
        }
        return (
          <Chip
            key={opt}
            label={opt}
            selected={selected}
            onSelect={() => {
              if (group.type === 'single') {
                onSingleChange(group.key as SingleGroup['key'], opt)
              } else {
                onMultiToggle(group.key as MultiGroup['key'], opt)
              }
            }}
          />
        )
      })}
    </View>
  </View>
)

// ─── Page ─────────────────────────────────────────────────────────────────────

const PreferencesPage: React.FC = () => {
  const { preferences, updatePreferences: updateStorePrefs } = useUserStore()
  const [prefs, setPrefs] = useState<PrefsState>(DEFAULT_STATE)
  const [saving, setSaving] = useState(false)

  // Hydrate from store on mount
  useEffect(() => {
    Taro.setNavigationBarTitle({ title: '口味偏好' })
    setPrefs({
      spicy: preferences.spicy ?? '',
      sweet: preferences.sweet ?? '',
      temperature: '',
      flavors: [],
      avoidances: preferences.allergies ?? [],
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSingleChange = useCallback((key: SingleGroup['key'], value: string) => {
    setPrefs((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleMultiToggle = useCallback((key: MultiGroup['key'], value: string) => {
    setPrefs((prev) => {
      const current = prev[key]
      const next = current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value]
      return { ...prev, [key]: next }
    })
  }, [])

  const handleSave = useCallback(async () => {
    if (saving) return
    setSaving(true)
    try {
      // Map local state to API shape
      const spicyMap: Record<string, 0 | 1 | 2 | 3> = {
        '不辣': 0,
        '微辣': 1,
        '中辣': 2,
        '重辣': 3,
      }
      const payload = {
        spicyLevel: spicyMap[prefs.spicy] ?? undefined,
        dietaryRestrictions: prefs.avoidances,
        favoriteCuisines: prefs.flavors,
        receivePromotions: true,
      }
      await updatePreferences(payload)
      // Update local store
      updateStorePrefs({
        spicy: prefs.spicy,
        sweet: prefs.sweet,
        allergies: prefs.avoidances,
      })
      Taro.showToast({
        title: '偏好已保存，将影响AI推荐结果',
        icon: 'success',
        duration: 2500,
      })
    } catch (_e) {
      Taro.showToast({ title: '保存失败，请重试', icon: 'none', duration: 2000 })
    } finally {
      setSaving(false)
    }
  }, [saving, prefs, updateStorePrefs])

  return (
    <ScrollView scrollY style={{ minHeight: '100vh', background: C.bgDeep }}>
      <View style={{ padding: '32rpx 32rpx 0' }}>

        {/* Header */}
        <View style={{ marginBottom: '36rpx' }}>
          <Text
            style={{
              color: C.text1,
              fontSize: '36rpx',
              fontWeight: '800',
              display: 'block',
              marginBottom: '10rpx',
            }}
          >
            口味偏好
          </Text>
          <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.6' }}>
            记住您的口味，每次推荐更精准
          </Text>
        </View>

        {/* Preference groups */}
        {PREF_GROUPS.map((group) => (
          <GroupCard
            key={group.key}
            group={group}
            prefs={prefs}
            onSingleChange={handleSingleChange}
            onMultiToggle={handleMultiToggle}
          />
        ))}

        {/* AI hint banner */}
        <View
          style={{
            background: 'rgba(255,107,53,0.1)',
            border: '2rpx solid rgba(255,107,53,0.25)',
            borderRadius: '20rpx',
            padding: '24rpx 28rpx',
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'flex-start',
            gap: '16rpx',
            marginBottom: '32rpx',
          }}
        >
          <Text style={{ fontSize: '32rpx', lineHeight: '1', flexShrink: 0 }}>🤖</Text>
          <Text style={{ color: C.text2, fontSize: '24rpx', lineHeight: '1.6' }}>
            AI 推荐系统将根据您的偏好，实时优化菜品推荐顺序，让每次点餐都更合口味。
          </Text>
        </View>

        {/* Save button */}
        <View
          style={{
            height: '96rpx',
            background: saving ? '#B34E1F' : C.primary,
            borderRadius: '48rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: saving ? 'none' : '0 4rpx 24rpx rgba(255,107,53,0.4)',
            marginBottom: '60rpx',
            opacity: saving ? 0.75 : 1,
          }}
          onClick={handleSave}
        >
          <Text style={{ color: C.white, fontSize: '34rpx', fontWeight: '700' }}>
            {saving ? '保存中…' : '保存偏好'}
          </Text>
        </View>
      </View>
    </ScrollView>
  )
}

export default PreferencesPage
