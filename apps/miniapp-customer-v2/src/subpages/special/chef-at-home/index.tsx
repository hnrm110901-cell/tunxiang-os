/**
 * chef-at-home/index.tsx — 大厨到家
 *
 * 3-step booking flow:
 *  Step 1 — 选择大厨: filterable chef cards with expandable detail
 *  Step 2 — 预约信息: date / time slot / guests / address / preferences
 *  Step 3 — 确认订单: summary + price breakdown + submit
 */

import React, { useState, useEffect, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, ScrollView, Input, Textarea } from '@tarojs/components'
import { fenToYuanDisplay } from '../../../utils/format'
import { useUserStore } from '../../../store/useUserStore'
import { txRequest } from '../../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  primaryDark: '#E55A1F',
  primaryFaint: 'rgba(255,107,53,0.12)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  success: '#4CAF50',
  white: '#FFFFFF',
  disabled: '#2A4050',
  gold: '#F5A623',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type CuisineFilter = 'all' | '川菜' | '粤菜' | '湘菜' | '本帮菜' | '西餐'
type TimeSlot = 'morning' | 'afternoon' | 'evening'
type MenuPref = '海鲜' | '红肉' | '素食' | '儿童友好'

interface ChefReview {
  userName: string
  rating: number
  content: string
  createdAt: string
}

interface ChefMenuSample {
  name: string
  description: string
}

interface Chef {
  chefId: string
  name: string
  avatarUrl: string
  specialties: string[]         // cuisine tags
  cuisineTypes: CuisineFilter[]
  rating: number                // 0-5
  pricePerHourFen: number
  serviceCount: number
  bio: string
  menuSamples: ChefMenuSample[]
  reviews: ChefReview[]
}

interface BookingForm {
  date: string          // "YYYY-MM-DD"
  timeSlot: TimeSlot
  guestCount: number
  address: string
  specialRequests: string
  menuPrefs: MenuPref[]
}

// ─── Constants ────────────────────────────────────────────────────────────────

const CUISINE_FILTERS: { value: CuisineFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: '川菜', label: '川菜' },
  { value: '粤菜', label: '粤菜' },
  { value: '湘菜', label: '湘菜' },
  { value: '本帮菜', label: '本帮菜' },
  { value: '西餐', label: '西餐' },
]

const TIME_SLOTS: { value: TimeSlot; label: string; sub: string }[] = [
  { value: 'morning', label: '上午', sub: '10:00–12:00' },
  { value: 'afternoon', label: '下午', sub: '14:00–18:00' },
  { value: 'evening', label: '晚上', sub: '18:00–21:00' },
]

const MENU_PREFS: MenuPref[] = ['海鲜', '红肉', '素食', '儿童友好']

const SERVICE_FEE_RATE = 0.05   // 5%
const INGREDIENT_PER_GUEST_FEN = 8000  // ¥80 estimated per person

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Generate the next 14 days starting from tomorrow */
function getBookableDates(): string[] {
  const dates: string[] = []
  const today = new Date()
  for (let i = 1; i <= 14; i++) {
    const d = new Date(today)
    d.setDate(today.getDate() + i)
    const yyyy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    dates.push(`${yyyy}-${mm}-${dd}`)
  }
  return dates
}

function formatDateDisplay(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  const weekdays = ['日', '一', '二', '三', '四', '五', '六']
  const mm = d.getMonth() + 1
  const dd = d.getDate()
  return `${mm}月${dd}日 周${weekdays[d.getDay()]}`
}

function renderStars(rating: number, size = '24rpx'): React.ReactNode {
  return (
    <View style={{ display: 'flex', flexDirection: 'row', gap: '4rpx' }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Text
          key={i}
          style={{ color: i <= Math.round(rating) ? C.gold : C.text3, fontSize: size }}
        >
          ★
        </Text>
      ))}
    </View>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ProgressBar({ step }: { step: 1 | 2 | 3 }) {
  const steps = ['选择大厨', '预约信息', '确认订单']
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '24rpx 32rpx 20rpx',
        background: C.bgCard,
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      {steps.map((label, idx) => {
        const s = idx + 1
        const active = s === step
        const done = s < step
        return (
          <React.Fragment key={s}>
            <View style={{ alignItems: 'center', flex: 1 }}>
              <View
                style={{
                  width: '48rpx',
                  height: '48rpx',
                  borderRadius: '24rpx',
                  background: done ? C.success : active ? C.primary : C.bgDeep,
                  border: `2rpx solid ${done ? C.success : active ? C.primary : C.border}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '8rpx',
                }}
              >
                <Text
                  style={{
                    color: done || active ? C.white : C.text3,
                    fontSize: '24rpx',
                    fontWeight: '700',
                  }}
                >
                  {done ? '✓' : String(s)}
                </Text>
              </View>
              <Text
                style={{
                  color: active ? C.primary : done ? C.success : C.text3,
                  fontSize: '22rpx',
                  fontWeight: active ? '600' : '400',
                }}
              >
                {label}
              </Text>
            </View>
            {idx < steps.length - 1 && (
              <View
                style={{
                  flex: 2,
                  height: '2rpx',
                  background: s < step ? C.success : C.border,
                  marginBottom: '28rpx',
                }}
              />
            )}
          </React.Fragment>
        )
      })}
    </View>
  )
}

function Chip({
  label,
  selected,
  onTap,
}: {
  label: string
  selected: boolean
  onTap: () => void
}) {
  return (
    <View
      style={{
        paddingHorizontal: '20rpx',
        paddingVertical: '10rpx',
        borderRadius: '32rpx',
        border: `2rpx solid ${selected ? C.primary : C.border}`,
        background: selected ? C.primaryFaint : C.bgDeep,
        marginRight: '12rpx',
        marginBottom: '12rpx',
      }}
      onClick={onTap}
    >
      <Text
        style={{
          color: selected ? C.primary : C.text2,
          fontSize: '26rpx',
          fontWeight: selected ? '600' : '400',
        }}
      >
        {label}
      </Text>
    </View>
  )
}

function Section({
  title,
  children,
  noPad,
}: {
  title?: string
  children: React.ReactNode
  noPad?: boolean
}) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '16rpx',
        margin: '0 24rpx 16rpx',
        overflow: 'hidden',
      }}
    >
      {title && (
        <View
          style={{
            padding: '20rpx 24rpx 12rpx',
            borderBottom: `1rpx solid ${C.border}`,
          }}
        >
          <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600' }}>
            {title}
          </Text>
        </View>
      )}
      <View style={noPad ? {} : { padding: '16rpx 24rpx 20rpx' }}>{children}</View>
    </View>
  )
}

function PriceLine({
  label,
  value,
  sub,
  accent,
  large,
}: {
  label: string
  value: string
  sub?: string
  accent?: boolean
  large?: boolean
}) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: '12rpx',
      }}
    >
      <View>
        <Text style={{ color: C.text2, fontSize: large ? '28rpx' : '26rpx' }}>{label}</Text>
        {sub && (
          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>{sub}</Text>
        )}
      </View>
      <Text
        style={{
          color: accent ? C.primary : C.text1,
          fontSize: large ? '36rpx' : '26rpx',
          fontWeight: large || accent ? '700' : '400',
          marginLeft: '24rpx',
        }}
      >
        {value}
      </Text>
    </View>
  )
}

// ─── Step 1: Chef List ────────────────────────────────────────────────────────

function ChefCard({
  chef,
  expanded,
  onExpand,
  onBook,
}: {
  chef: Chef
  expanded: boolean
  onExpand: () => void
  onBook: () => void
}) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '16rpx',
        margin: '0 24rpx 16rpx',
        overflow: 'hidden',
        border: `1rpx solid ${expanded ? C.primary : C.border}`,
      }}
    >
      {/* Header row */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '24rpx',
        }}
        onClick={onExpand}
      >
        <Image
          src={chef.avatarUrl || 'https://placehold.co/80x80/132029/FF6B35?text=厨'}
          style={{
            width: '96rpx',
            height: '96rpx',
            borderRadius: '48rpx',
            flexShrink: 0,
            marginRight: '20rpx',
          }}
          lazyLoad
        />
        <View style={{ flex: 1, overflow: 'hidden' }}>
          <Text
            style={{
              color: C.text1,
              fontSize: '32rpx',
              fontWeight: '700',
              marginBottom: '8rpx',
            }}
          >
            {chef.name}
          </Text>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: '8rpx',
              marginBottom: '8rpx',
            }}
          >
            {chef.specialties.map((s) => (
              <View
                key={s}
                style={{
                  background: C.primaryFaint,
                  borderRadius: '8rpx',
                  paddingHorizontal: '10rpx',
                  paddingVertical: '4rpx',
                }}
              >
                <Text style={{ color: C.primary, fontSize: '22rpx' }}>{s}</Text>
              </View>
            ))}
          </View>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '12rpx',
            }}
          >
            {renderStars(chef.rating)}
            <Text style={{ color: C.text3, fontSize: '22rpx' }}>
              已服务{chef.serviceCount}次
            </Text>
          </View>
        </View>
        <View style={{ alignItems: 'flex-end', flexShrink: 0, marginLeft: '12rpx' }}>
          <Text style={{ color: C.primary, fontSize: '32rpx', fontWeight: '700' }}>
            {fenToYuanDisplay(chef.pricePerHourFen)}
          </Text>
          <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>/小时</Text>
          <Text
            style={{
              color: expanded ? C.primary : C.text2,
              fontSize: '24rpx',
              marginTop: '12rpx',
            }}
          >
            {expanded ? '收起 ▲' : '详情 ▼'}
          </Text>
        </View>
      </View>

      {/* Expanded detail */}
      {expanded && (
        <View style={{ borderTop: `1rpx solid ${C.border}` }}>
          {/* Bio */}
          <View style={{ padding: '20rpx 24rpx' }}>
            <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600', marginBottom: '8rpx' }}>
              厨师简介
            </Text>
            <Text style={{ color: C.text1, fontSize: '26rpx', lineHeight: '1.6' }}>
              {chef.bio}
            </Text>
          </View>

          {/* Menu samples */}
          {chef.menuSamples.length > 0 && (
            <View
              style={{
                padding: '0 24rpx 20rpx',
                borderTop: `1rpx solid ${C.border}`,
              }}
            >
              <Text
                style={{
                  color: C.text2,
                  fontSize: '24rpx',
                  fontWeight: '600',
                  marginBottom: '12rpx',
                  marginTop: '16rpx',
                }}
              >
                招牌菜品
              </Text>
              {chef.menuSamples.map((m, i) => (
                <View
                  key={i}
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    alignItems: 'flex-start',
                    marginBottom: '10rpx',
                  }}
                >
                  <View
                    style={{
                      width: '8rpx',
                      height: '8rpx',
                      borderRadius: '4rpx',
                      background: C.primary,
                      marginTop: '11rpx',
                      marginRight: '16rpx',
                      flexShrink: 0,
                    }}
                  />
                  <View>
                    <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '500' }}>
                      {m.name}
                    </Text>
                    <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '2rpx' }}>
                      {m.description}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          )}

          {/* Reviews */}
          {chef.reviews.length > 0 && (
            <View
              style={{
                padding: '0 24rpx 20rpx',
                borderTop: `1rpx solid ${C.border}`,
              }}
            >
              <Text
                style={{
                  color: C.text2,
                  fontSize: '24rpx',
                  fontWeight: '600',
                  marginBottom: '12rpx',
                  marginTop: '16rpx',
                }}
              >
                用户评价
              </Text>
              {chef.reviews.slice(0, 3).map((r, i) => (
                <View
                  key={i}
                  style={{
                    background: C.bgDeep,
                    borderRadius: '12rpx',
                    padding: '16rpx',
                    marginBottom: '10rpx',
                  }}
                >
                  <View
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      alignItems: 'center',
                      marginBottom: '8rpx',
                      gap: '12rpx',
                    }}
                  >
                    <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '500' }}>
                      {r.userName}
                    </Text>
                    {renderStars(r.rating, '22rpx')}
                    <Text style={{ color: C.text3, fontSize: '22rpx', marginLeft: 'auto' }}>
                      {r.createdAt.slice(0, 10)}
                    </Text>
                  </View>
                  <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.5' }}>
                    {r.content}
                  </Text>
                </View>
              ))}
            </View>
          )}

          {/* CTA */}
          <View
            style={{
              padding: '16rpx 24rpx 24rpx',
              borderTop: `1rpx solid ${C.border}`,
            }}
          >
            <View
              style={{
                background: C.primary,
                borderRadius: '44rpx',
                height: '88rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={onBook}
            >
              <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                预约此厨师
              </Text>
            </View>
          </View>
        </View>
      )}
    </View>
  )
}

// ─── Step 2: Booking Form ─────────────────────────────────────────────────────

function BookingStep({
  chef,
  form,
  onChange,
  onNext,
  onBack,
}: {
  chef: Chef
  form: BookingForm
  onChange: (patch: Partial<BookingForm>) => void
  onNext: () => void
  onBack: () => void
}) {
  const dates = getBookableDates()
  const [datePickerVisible, setDatePickerVisible] = useState(false)
  const { phone } = useUserStore()

  const canProceed =
    form.date !== '' &&
    form.timeSlot !== ('' as TimeSlot) &&
    form.guestCount >= 2 &&
    form.address.trim().length >= 5

  const handleUsePhone = () => {
    if (phone) onChange({ address: form.address || '' })
  }

  return (
    <ScrollView
      scrollY
      style={{ flex: 1, paddingBottom: '180rpx' }}
    >
      {/* Chef mini-card */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          background: C.bgCard,
          margin: '16rpx 24rpx',
          borderRadius: '16rpx',
          padding: '20rpx 24rpx',
          gap: '16rpx',
        }}
      >
        <Image
          src={chef.avatarUrl || 'https://placehold.co/64x64/132029/FF6B35?text=厨'}
          style={{ width: '64rpx', height: '64rpx', borderRadius: '32rpx' }}
          lazyLoad
        />
        <View>
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
            {chef.name}
          </Text>
          <Text style={{ color: C.text3, fontSize: '24rpx' }}>
            {fenToYuanDisplay(chef.pricePerHourFen)}/小时
          </Text>
        </View>
      </View>

      {/* Date */}
      <Section title="预约日期">
        <ScrollView scrollX style={{ whiteSpace: 'nowrap' }}>
          <View style={{ display: 'flex', flexDirection: 'row', gap: '12rpx' }}>
            {dates.map((d) => {
              const selected = form.date === d
              return (
                <View
                  key={d}
                  style={{
                    minWidth: '110rpx',
                    padding: '16rpx 20rpx',
                    borderRadius: '12rpx',
                    border: `2rpx solid ${selected ? C.primary : C.border}`,
                    background: selected ? C.primaryFaint : C.bgDeep,
                    alignItems: 'center',
                    flexShrink: 0,
                  }}
                  onClick={() => onChange({ date: d })}
                >
                  <Text
                    style={{
                      color: selected ? C.primary : C.text2,
                      fontSize: '22rpx',
                      fontWeight: selected ? '700' : '400',
                    }}
                  >
                    {d.slice(5).replace('-', '/')}
                  </Text>
                  <Text
                    style={{
                      color: selected ? C.primary : C.text3,
                      fontSize: '20rpx',
                      marginTop: '4rpx',
                    }}
                  >
                    {(() => {
                      const dt = new Date(d + 'T00:00:00')
                      return ['日', '一', '二', '三', '四', '五', '六'][dt.getDay()]
                        ? `周${ ['日', '一', '二', '三', '四', '五', '六'][dt.getDay()]}`
                        : ''
                    })()}
                  </Text>
                </View>
              )
            })}
          </View>
        </ScrollView>
        {form.date && (
          <Text style={{ color: C.text2, fontSize: '24rpx', marginTop: '12rpx' }}>
            已选：{formatDateDisplay(form.date)}
          </Text>
        )}
      </Section>

      {/* Time slot */}
      <Section title="时间段">
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          {TIME_SLOTS.map((ts) => {
            const selected = form.timeSlot === ts.value
            return (
              <View
                key={ts.value}
                style={{
                  flex: 1,
                  padding: '16rpx 8rpx',
                  borderRadius: '12rpx',
                  border: `2rpx solid ${selected ? C.primary : C.border}`,
                  background: selected ? C.primaryFaint : C.bgDeep,
                  alignItems: 'center',
                }}
                onClick={() => onChange({ timeSlot: ts.value })}
              >
                <Text
                  style={{
                    color: selected ? C.primary : C.text2,
                    fontSize: '28rpx',
                    fontWeight: selected ? '700' : '400',
                    marginBottom: '4rpx',
                  }}
                >
                  {ts.label}
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx' }}>{ts.sub}</Text>
              </View>
            )
          })}
        </View>
      </Section>

      {/* Guest count */}
      <Section title="用餐人数">
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '26rpx' }}>
            {form.guestCount}人（最少2人，最多20人）
          </Text>
          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '0rpx' }}>
            <View
              style={{
                width: '64rpx',
                height: '64rpx',
                borderRadius: '32rpx',
                border: `2rpx solid ${form.guestCount <= 2 ? C.border : C.primary}`,
                background: form.guestCount <= 2 ? C.bgDeep : C.primaryFaint,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={() => form.guestCount > 2 && onChange({ guestCount: form.guestCount - 1 })}
            >
              <Text
                style={{
                  color: form.guestCount <= 2 ? C.text3 : C.primary,
                  fontSize: '36rpx',
                  fontWeight: '700',
                  lineHeight: '1',
                }}
              >
                −
              </Text>
            </View>
            <Text
              style={{
                color: C.text1,
                fontSize: '36rpx',
                fontWeight: '700',
                width: '80rpx',
                textAlign: 'center',
              }}
            >
              {form.guestCount}
            </Text>
            <View
              style={{
                width: '64rpx',
                height: '64rpx',
                borderRadius: '32rpx',
                border: `2rpx solid ${form.guestCount >= 20 ? C.border : C.primary}`,
                background: form.guestCount >= 20 ? C.bgDeep : C.primaryFaint,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onClick={() => form.guestCount < 20 && onChange({ guestCount: form.guestCount + 1 })}
            >
              <Text
                style={{
                  color: form.guestCount >= 20 ? C.text3 : C.primary,
                  fontSize: '36rpx',
                  fontWeight: '700',
                  lineHeight: '1',
                }}
              >
                +
              </Text>
            </View>
          </View>
        </View>
      </Section>

      {/* Address */}
      <Section title="上门地址">
        <Input
          value={form.address}
          onInput={(e) => onChange({ address: e.detail.value })}
          placeholder="请输入详细地址（如：XX路XX号XX室）"
          placeholderStyle={`color:${C.text3}`}
          style={{
            background: C.bgDeep,
            color: C.text1,
            fontSize: '28rpx',
            borderRadius: '12rpx',
            padding: '20rpx',
            border: `1rpx solid ${C.border}`,
          }}
        />
      </Section>

      {/* Special requests */}
      <Section title="特殊要求（选填）">
        <Textarea
          value={form.specialRequests}
          onInput={(e) => onChange({ specialRequests: e.detail.value })}
          placeholder="过敏食材、口味偏好、特殊场合需求..."
          placeholderStyle={`color:${C.text3}`}
          style={{
            background: C.bgDeep,
            color: C.text1,
            fontSize: '26rpx',
            borderRadius: '12rpx',
            padding: '16rpx',
            width: '100%',
            minHeight: '120rpx',
            border: `1rpx solid ${C.border}`,
          }}
          maxlength={300}
        />
      </Section>

      {/* Menu preference tags */}
      <Section title="口味偏好（可多选）">
        <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap' }}>
          {MENU_PREFS.map((p) => {
            const selected = form.menuPrefs.includes(p)
            return (
              <Chip
                key={p}
                label={p}
                selected={selected}
                onTap={() => {
                  const next = selected
                    ? form.menuPrefs.filter((x) => x !== p)
                    : [...form.menuPrefs, p]
                  onChange({ menuPrefs: next })
                }}
              />
            )
          })}
        </View>
      </Section>

      {/* Validation hint */}
      {!canProceed && (
        <View style={{ padding: '0 32rpx 8rpx' }}>
          <Text style={{ color: C.text3, fontSize: '24rpx' }}>
            请完成日期、时间段、地址后继续
          </Text>
        </View>
      )}

      {/* Nav buttons */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          background: C.bgCard,
          borderTop: `1rpx solid ${C.border}`,
          padding: '20rpx 24rpx',
          paddingBottom: 'calc(20rpx + env(safe-area-inset-bottom))',
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
          zIndex: 100,
        }}
      >
        <View
          style={{
            flex: 1,
            height: '88rpx',
            borderRadius: '44rpx',
            border: `2rpx solid ${C.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={onBack}
        >
          <Text style={{ color: C.text2, fontSize: '32rpx', fontWeight: '600' }}>返回</Text>
        </View>
        <View
          style={{
            flex: 2,
            height: '88rpx',
            borderRadius: '44rpx',
            background: canProceed ? C.primary : C.disabled,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: canProceed ? 1 : 0.6,
          }}
          onClick={canProceed ? onNext : undefined}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            下一步
          </Text>
        </View>
      </View>
    </ScrollView>
  )
}

// ─── Step 3: Confirm Order ────────────────────────────────────────────────────

function ConfirmStep({
  chef,
  form,
  onBack,
  onSubmit,
  submitting,
}: {
  chef: Chef
  form: BookingForm
  onBack: () => void
  onSubmit: () => void
  submitting: boolean
}) {
  // Price calculation: assume 3-hour service window
  const hoursMap: Record<TimeSlot, number> = {
    morning: 2,
    afternoon: 4,
    evening: 3,
  }
  const hours = hoursMap[form.timeSlot]
  const chefFeeFen = chef.pricePerHourFen * hours
  const ingredientEstFen = INGREDIENT_PER_GUEST_FEN * form.guestCount
  const subtotalFen = chefFeeFen + ingredientEstFen
  const serviceFen = Math.round(subtotalFen * SERVICE_FEE_RATE)
  const totalFen = subtotalFen + serviceFen

  const slotLabel = TIME_SLOTS.find((t) => t.value === form.timeSlot)
  const prefLabel = form.menuPrefs.length > 0 ? form.menuPrefs.join(' · ') : '无特别偏好'

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '180rpx' }}>
      {/* Chef */}
      <Section title="大厨信息">
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '20rpx' }}>
          <Image
            src={chef.avatarUrl || 'https://placehold.co/80x80/132029/FF6B35?text=厨'}
            style={{ width: '80rpx', height: '80rpx', borderRadius: '40rpx' }}
            lazyLoad
          />
          <View>
            <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>{chef.name}</Text>
            <View style={{ display: 'flex', flexDirection: 'row', gap: '8rpx', marginTop: '6rpx', flexWrap: 'wrap' }}>
              {chef.specialties.map((s) => (
                <View
                  key={s}
                  style={{
                    background: C.primaryFaint,
                    borderRadius: '6rpx',
                    paddingHorizontal: '10rpx',
                    paddingVertical: '2rpx',
                  }}
                >
                  <Text style={{ color: C.primary, fontSize: '22rpx' }}>{s}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>
      </Section>

      {/* Booking details */}
      <Section title="预约详情">
        {[
          { label: '日期', value: formatDateDisplay(form.date) },
          {
            label: '时间段',
            value: `${slotLabel?.label ?? ''} ${slotLabel?.sub ?? ''}`,
          },
          { label: '用餐人数', value: `${form.guestCount}人` },
          { label: '上门地址', value: form.address },
          { label: '口味偏好', value: prefLabel },
          ...(form.specialRequests
            ? [{ label: '特殊要求', value: form.specialRequests }]
            : []),
        ].map(({ label, value }) => (
          <View
            key={label}
            style={{
              display: 'flex',
              flexDirection: 'row',
              paddingVertical: '10rpx',
              borderBottom: `1rpx solid ${C.border}`,
              alignItems: 'flex-start',
            }}
          >
            <Text
              style={{
                color: C.text3,
                fontSize: '26rpx',
                width: '140rpx',
                flexShrink: 0,
              }}
            >
              {label}
            </Text>
            <Text
              style={{
                color: C.text1,
                fontSize: '26rpx',
                flex: 1,
                lineHeight: '1.5',
              }}
            >
              {value}
            </Text>
          </View>
        ))}
      </Section>

      {/* Price breakdown */}
      <Section title="费用明细">
        <PriceLine
          label="厨师费"
          value={fenToYuanDisplay(chefFeeFen)}
          sub={`${fenToYuanDisplay(chef.pricePerHourFen)}/小时 × ${hours}小时`}
        />
        <PriceLine
          label="食材费（估算）"
          value={fenToYuanDisplay(ingredientEstFen)}
          sub={`${fenToYuanDisplay(INGREDIENT_PER_GUEST_FEN)}/人 × ${form.guestCount}人`}
        />
        <PriceLine
          label="服务费"
          value={fenToYuanDisplay(serviceFen)}
          sub="5%服务费"
        />
        <View style={{ height: '1rpx', background: C.border, margin: '12rpx 0' }} />
        <PriceLine label="预计总费用" value={fenToYuanDisplay(totalFen)} accent large />

        {/* Note */}
        <View
          style={{
            background: 'rgba(245,166,35,0.1)',
            borderRadius: '12rpx',
            padding: '16rpx',
            marginTop: '8rpx',
          }}
        >
          <Text style={{ color: C.gold, fontSize: '24rpx', lineHeight: '1.6' }}>
            食材费用按实际采购结算，估算仅供参考。厨师费和服务费现在支付，食材费餐后按实际结清。
          </Text>
        </View>
      </Section>

      {/* CTA area */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          background: C.bgCard,
          borderTop: `1rpx solid ${C.border}`,
          padding: '20rpx 24rpx',
          paddingBottom: 'calc(20rpx + env(safe-area-inset-bottom))',
          display: 'flex',
          flexDirection: 'row',
          gap: '16rpx',
          zIndex: 100,
        }}
      >
        <View
          style={{
            flex: 1,
            height: '88rpx',
            borderRadius: '44rpx',
            border: `2rpx solid ${C.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          onClick={onBack}
        >
          <Text style={{ color: C.text2, fontSize: '32rpx', fontWeight: '600' }}>返回</Text>
        </View>
        <View
          style={{
            flex: 2,
            height: '88rpx',
            borderRadius: '44rpx',
            background: submitting ? C.disabled : C.primary,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: submitting ? 0.7 : 1,
          }}
          onClick={submitting ? undefined : onSubmit}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : `提交预约 ${fenToYuanDisplay(chefFeeFen + serviceFen)}`}
          </Text>
        </View>
      </View>
    </ScrollView>
  )
}

// ─── Success overlay ──────────────────────────────────────────────────────────

function SuccessOverlay({ onHome }: { onHome: () => void }) {
  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 999,
        padding: '48rpx',
      }}
    >
      <View
        style={{
          width: '120rpx',
          height: '120rpx',
          borderRadius: '60rpx',
          background: 'rgba(76,175,80,0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '32rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx', lineHeight: '1' }}>✓</Text>
      </View>
      <Text style={{ color: C.text1, fontSize: '40rpx', fontWeight: '700', marginBottom: '16rpx' }}>
        预约成功！
      </Text>
      <Text
        style={{
          color: C.text2,
          fontSize: '28rpx',
          textAlign: 'center',
          lineHeight: '1.6',
          marginBottom: '48rpx',
        }}
      >
        大厨将在确认后联系您，请保持手机畅通。
      </Text>
      <View
        style={{
          background: C.primary,
          borderRadius: '44rpx',
          height: '88rpx',
          width: '400rpx',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onClick={onHome}
      >
        <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>返回首页</Text>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const DEFAULT_FORM: BookingForm = {
  date: '',
  timeSlot: 'evening',
  guestCount: 4,
  address: '',
  specialRequests: '',
  menuPrefs: [],
}

export default function ChefAtHomePage() {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [cuisineFilter, setCuisineFilter] = useState<CuisineFilter>('all')
  const [chefs, setChefs] = useState<Chef[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedChefId, setExpandedChefId] = useState<string | null>(null)
  const [selectedChef, setSelectedChef] = useState<Chef | null>(null)
  const [form, setForm] = useState<BookingForm>(DEFAULT_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const { isLoggedIn } = useUserStore()

  // Load chefs
  useEffect(() => {
    setLoading(true)
    setError(null)
    txRequest<Chef[]>('/chef-at-home/chefs')
      .then((data) => setChefs(data))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '加载失败，请重试'
        setError(msg)
      })
      .finally(() => setLoading(false))
  }, [])

  const filteredChefs =
    cuisineFilter === 'all'
      ? chefs
      : chefs.filter((c) => c.cuisineTypes.includes(cuisineFilter))

  const handleBook = useCallback(
    (chef: Chef) => {
      if (!isLoggedIn) {
        Taro.showToast({ title: '请先登录', icon: 'none' })
        return
      }
      setSelectedChef(chef)
      setStep(2)
    },
    [isLoggedIn],
  )

  const handleSubmit = useCallback(async () => {
    if (!selectedChef) return
    if (!isLoggedIn) {
      Taro.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    setSubmitting(true)
    try {
      await txRequest('/chef-at-home/bookings', 'POST', {
        chefId: selectedChef.chefId,
        date: form.date,
        timeSlot: form.timeSlot,
        guestCount: form.guestCount,
        address: form.address,
        specialRequests: form.specialRequests,
        menuPrefs: form.menuPrefs,
      })
      setSubmitted(true)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '预约失败，请重试'
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }, [selectedChef, form, isLoggedIn])

  if (submitted) {
    return (
      <SuccessOverlay
        onHome={() => Taro.switchTab({ url: '/pages/index/index' })}
      />
    )
  }

  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <View style={{ padding: '24rpx 32rpx 0' }}>
        <Text style={{ color: C.text1, fontSize: '40rpx', fontWeight: '800' }}>大厨到家</Text>
        <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '8rpx' }}>
          专业厨师上门烹饪，享受私厨体验
        </Text>
      </View>

      {/* Progress */}
      <ProgressBar step={step} />

      {/* Step 1 */}
      {step === 1 && (
        <>
          {/* Cuisine filter */}
          <View
            style={{
              background: C.bgCard,
              borderBottom: `1rpx solid ${C.border}`,
              padding: '16rpx 24rpx',
            }}
          >
            <ScrollView scrollX style={{ whiteSpace: 'nowrap' }}>
              <View style={{ display: 'flex', flexDirection: 'row', gap: '12rpx' }}>
                {CUISINE_FILTERS.map((f) => {
                  const active = cuisineFilter === f.value
                  return (
                    <View
                      key={f.value}
                      style={{
                        paddingHorizontal: '24rpx',
                        paddingVertical: '12rpx',
                        borderRadius: '32rpx',
                        background: active ? C.primary : C.bgDeep,
                        border: `2rpx solid ${active ? C.primary : C.border}`,
                        flexShrink: 0,
                      }}
                      onClick={() => setCuisineFilter(f.value)}
                    >
                      <Text
                        style={{
                          color: active ? C.white : C.text2,
                          fontSize: '26rpx',
                          fontWeight: active ? '600' : '400',
                        }}
                      >
                        {f.label}
                      </Text>
                    </View>
                  )
                })}
              </View>
            </ScrollView>
          </View>

          {/* Chef list */}
          <ScrollView scrollY style={{ flex: 1, paddingTop: '16rpx' }}>
            {loading ? (
              <View
                style={{
                  padding: '80rpx',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
              </View>
            ) : error ? (
              <View style={{ padding: '80rpx', alignItems: 'center' }}>
                <Text style={{ color: C.red, fontSize: '28rpx', marginBottom: '24rpx' }}>
                  {error}
                </Text>
                <View
                  style={{
                    background: C.primary,
                    borderRadius: '32rpx',
                    padding: '16rpx 40rpx',
                  }}
                  onClick={() => {
                    setLoading(true)
                    setError(null)
                    txRequest<Chef[]>('/chef-at-home/chefs')
                      .then((data) => setChefs(data))
                      .catch((e: unknown) => {
                        setError(e instanceof Error ? e.message : '加载失败')
                      })
                      .finally(() => setLoading(false))
                  }}
                >
                  <Text style={{ color: C.white, fontSize: '28rpx' }}>重试</Text>
                </View>
              </View>
            ) : filteredChefs.length === 0 ? (
              <View style={{ padding: '80rpx', alignItems: 'center' }}>
                <Text style={{ color: C.text2, fontSize: '28rpx' }}>
                  暂无{cuisineFilter === 'all' ? '' : cuisineFilter}厨师
                </Text>
              </View>
            ) : (
              filteredChefs.map((chef) => (
                <ChefCard
                  key={chef.chefId}
                  chef={chef}
                  expanded={expandedChefId === chef.chefId}
                  onExpand={() =>
                    setExpandedChefId(
                      expandedChefId === chef.chefId ? null : chef.chefId,
                    )
                  }
                  onBook={() => handleBook(chef)}
                />
              ))
            )}
            <View style={{ height: '40rpx' }} />
          </ScrollView>
        </>
      )}

      {/* Step 2 */}
      {step === 2 && selectedChef && (
        <BookingStep
          chef={selectedChef}
          form={form}
          onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
          onNext={() => setStep(3)}
          onBack={() => setStep(1)}
        />
      )}

      {/* Step 3 */}
      {step === 3 && selectedChef && (
        <ConfirmStep
          chef={selectedChef}
          form={form}
          onBack={() => setStep(2)}
          onSubmit={handleSubmit}
          submitting={submitting}
        />
      )}
    </View>
  )
}
