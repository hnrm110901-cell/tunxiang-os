/**
 * banquet/index.tsx — 宴会预订
 *
 * 4-step wizard:
 *  Step 1 — 宴会类型: 6 type cards
 *  Step 2 — 基本信息: guest count / date / time / budget
 *  Step 3 — 套餐选择: banquet packages matching budget, expandable dish list
 *  Step 4 — 确认与定金: summary + deposit payment → POST /api/v1/banquet/bookings
 */

import React, { useState, useEffect, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, ScrollView, Input } from '@tarojs/components'
import { fenToYuanDisplay } from '../../../utils/format'
import { useUserStore } from '../../../store/useUserStore'
import { txRequest } from '../../../utils/request'
import PaymentSheet from '../../../components/PaymentSheet'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B2C',
  primaryDark: '#E55A1F',
  primaryFaint: 'rgba(255,107,44,0.12)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  redFaint: 'rgba(229,57,53,0.1)',
  success: '#4CAF50',
  successFaint: 'rgba(76,175,80,0.12)',
  warning: '#F5A623',
  warningFaint: 'rgba(245,166,35,0.12)',
  white: '#FFFFFF',
  disabled: '#2A4050',
  gold: '#F5A623',
  goldFaint: 'rgba(245,166,35,0.1)',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type BanquetType =
  | 'wedding'
  | 'birthday_elder'
  | 'business'
  | 'birthday'
  | 'fullmoon'
  | 'family'

type MealTime = 'lunch' | 'dinner' | 'allday'

interface BanquetTypeDef {
  value: BanquetType
  label: string
  icon: string
  desc: string
}

interface BudgetPreset {
  label: string
  fen: number
}

interface BanquetDish {
  name: string
  category: string
}

interface BanquetPackage {
  packageId: string
  name: string
  pricePerPersonFen: number
  dishCount: number
  featuredDishes: string[]
  allDishes?: BanquetDish[]
  description: string
  minGuests: number
  maxGuests: number
}

interface ContactForm {
  name: string
  phone: string
}

interface BookingPayload {
  banquetType: BanquetType
  guestCount: number
  date: string
  mealTime: MealTime
  budgetPerPersonFen: number
  packageId: string
  contactName: string
  contactPhone: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const BANQUET_TYPES: BanquetTypeDef[] = [
  { value: 'wedding', label: '婚宴', icon: '💒', desc: '浪漫婚礼答谢宴' },
  { value: 'birthday_elder', label: '寿宴', icon: '🎎', desc: '长辈寿诞庆典' },
  { value: 'business', label: '商务宴', icon: '🤝', desc: '商务接待与洽谈' },
  { value: 'birthday', label: '生日宴', icon: '🎂', desc: '生日派对庆典' },
  { value: 'fullmoon', label: '满月宴', icon: '🌕', desc: '宝宝满月之喜' },
  { value: 'family', label: '家庭聚餐', icon: '🏠', desc: '家族团聚欢宴' },
]

const MEAL_TIMES: { value: MealTime; label: string; sub: string }[] = [
  { value: 'lunch', label: '午宴', sub: '11:30 开席' },
  { value: 'dinner', label: '晚宴', sub: '17:30 开席' },
  { value: 'allday', label: '全天', sub: '全天包场' },
]

const BUDGET_PRESETS: BudgetPreset[] = [
  { label: '¥188/人', fen: 18800 },
  { label: '¥288/人', fen: 28800 },
  { label: '¥388/人', fen: 38800 },
  { label: '¥488/人', fen: 48800 },
  { label: '¥688+/人', fen: 68800 },
]

const DEPOSIT_RATE = 0.2   // 20% deposit

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getNext60Days(): string[] {
  const dates: string[] = []
  const today = new Date()
  for (let i = 1; i <= 60; i++) {
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
  return `${d.getMonth() + 1}月${d.getDate()}日 周${weekdays[d.getDay()]}`
}

// ─── Shared UI Atoms ──────────────────────────────────────────────────────────

function ProgressBar({ step }: { step: 1 | 2 | 3 | 4 }) {
  const steps = ['宴会类型', '基本信息', '套餐选择', '确认定金']
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        padding: '20rpx 24rpx 16rpx',
        background: C.bgCard,
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      {steps.map((label, idx) => {
        const s = (idx + 1) as 1 | 2 | 3 | 4
        const active = s === step
        const done = s < step
        return (
          <React.Fragment key={s}>
            <View style={{ alignItems: 'center', flex: 1 }}>
              <View
                style={{
                  width: '44rpx',
                  height: '44rpx',
                  borderRadius: '22rpx',
                  background: done ? C.success : active ? C.primary : C.bgDeep,
                  border: `2rpx solid ${done ? C.success : active ? C.primary : C.border}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: '6rpx',
                }}
              >
                <Text
                  style={{
                    color: done || active ? C.white : C.text3,
                    fontSize: '20rpx',
                    fontWeight: '700',
                  }}
                >
                  {done ? '✓' : String(s)}
                </Text>
              </View>
              <Text
                style={{
                  color: active ? C.primary : done ? C.success : C.text3,
                  fontSize: '20rpx',
                  fontWeight: active ? '600' : '400',
                }}
              >
                {label}
              </Text>
            </View>
            {idx < steps.length - 1 && (
              <View
                style={{
                  flex: 1,
                  height: '2rpx',
                  background: s < step ? C.success : C.border,
                  marginBottom: '24rpx',
                  marginHorizontal: '4rpx',
                }}
              />
            )}
          </React.Fragment>
        )
      })}
    </View>
  )
}

function NavBar({
  onBack,
  onNext,
  nextLabel,
  nextDisabled,
  loading,
}: {
  onBack?: () => void
  onNext: () => void
  nextLabel: string
  nextDisabled?: boolean
  loading?: boolean
}) {
  return (
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
      {onBack && (
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
      )}
      <View
        style={{
          flex: onBack ? 2 : 1,
          height: '88rpx',
          borderRadius: '44rpx',
          background: nextDisabled || loading ? C.disabled : C.primary,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: nextDisabled || loading ? 0.6 : 1,
        }}
        onClick={nextDisabled || loading ? undefined : onNext}
      >
        <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
          {loading ? '处理中...' : nextLabel}
        </Text>
      </View>
    </View>
  )
}

function Section({
  title,
  children,
}: {
  title?: string
  children: React.ReactNode
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
          <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600' }}>{title}</Text>
        </View>
      )}
      <View style={{ padding: '16rpx 24rpx 20rpx' }}>{children}</View>
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
          fontSize: large ? '40rpx' : '26rpx',
          fontWeight: large || accent ? '700' : '400',
          marginLeft: '24rpx',
        }}
      >
        {value}
      </Text>
    </View>
  )
}

// ─── Step 1: Banquet Type ─────────────────────────────────────────────────────

function Step1TypeSelect({
  selected,
  onSelect,
  onNext,
}: {
  selected: BanquetType | null
  onSelect: (t: BanquetType) => void
  onNext: () => void
}) {
  return (
    <View style={{ flex: 1, display: 'flex', flexDirection: 'column', paddingBottom: '160rpx' }}>
      <View style={{ padding: '24rpx 24rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', marginBottom: '8rpx' }}>
          请选择宴会类型
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>
          我们将为您推荐最合适的方案
        </Text>
      </View>

      {/* 3 × 2 grid */}
      <View
        style={{
          padding: '0 24rpx',
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: '16rpx',
        }}
      >
        {BANQUET_TYPES.map((bt) => {
          const isSelected = selected === bt.value
          return (
            <View
              key={bt.value}
              style={{
                width: 'calc(50% - 8rpx)',
                background: isSelected ? C.primaryFaint : C.bgCard,
                borderRadius: '20rpx',
                border: `2rpx solid ${isSelected ? C.primary : C.border}`,
                padding: '28rpx 24rpx',
                alignItems: 'flex-start',
              }}
              onClick={() => onSelect(bt.value)}
            >
              {/* Selection indicator */}
              <View
                style={{
                  width: '100%',
                  display: 'flex',
                  flexDirection: 'row',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  marginBottom: '16rpx',
                }}
              >
                <Text style={{ fontSize: '52rpx', lineHeight: '1' }}>{bt.icon}</Text>
                <View
                  style={{
                    width: '36rpx',
                    height: '36rpx',
                    borderRadius: '18rpx',
                    border: `2rpx solid ${isSelected ? C.primary : C.border}`,
                    background: isSelected ? C.primary : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {isSelected && (
                    <Text style={{ color: C.white, fontSize: '20rpx', fontWeight: '700' }}>✓</Text>
                  )}
                </View>
              </View>
              <Text
                style={{
                  color: isSelected ? C.primary : C.text1,
                  fontSize: '30rpx',
                  fontWeight: '700',
                  marginBottom: '6rpx',
                }}
              >
                {bt.label}
              </Text>
              <Text style={{ color: C.text3, fontSize: '24rpx' }}>{bt.desc}</Text>
            </View>
          )
        })}
      </View>

      <NavBar
        onNext={onNext}
        nextLabel="下一步：基本信息"
        nextDisabled={selected === null}
      />
    </View>
  )
}

// ─── Step 2: Basic Info ───────────────────────────────────────────────────────

function Step2BasicInfo({
  guestCount,
  date,
  mealTime,
  budgetPerPersonFen,
  onGuestCount,
  onDate,
  onMealTime,
  onBudget,
  onBack,
  onNext,
}: {
  guestCount: number
  date: string
  mealTime: MealTime
  budgetPerPersonFen: number
  onGuestCount: (v: number) => void
  onDate: (v: string) => void
  onMealTime: (v: MealTime) => void
  onBudget: (v: number) => void
  onBack: () => void
  onNext: () => void
}) {
  const dates = getNext60Days()
  const canProceed = guestCount >= 10 && date !== '' && budgetPerPersonFen > 0

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '180rpx' }}>
      {/* Guest count */}
      <Section title="用餐人数">
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '16rpx',
          }}
        >
          <View>
            <Text style={{ color: C.text1, fontSize: '48rpx', fontWeight: '800' }}>
              {guestCount}
            </Text>
            <Text style={{ color: C.text3, fontSize: '22rpx' }}>人（10–500人）</Text>
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '0rpx' }}>
            {[
              { label: '−10', delta: -10, disabled: guestCount <= 10 },
              { label: '−1', delta: -1, disabled: guestCount <= 10 },
              { label: '+1', delta: 1, disabled: guestCount >= 500 },
              { label: '+10', delta: 10, disabled: guestCount >= 500 },
            ].map((btn) => (
              <View
                key={btn.label}
                style={{
                  width: '72rpx',
                  height: '72rpx',
                  borderRadius: '12rpx',
                  border: `2rpx solid ${btn.disabled ? C.border : C.primary}`,
                  background: btn.disabled ? C.bgDeep : C.primaryFaint,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginLeft: '8rpx',
                  opacity: btn.disabled ? 0.5 : 1,
                }}
                onClick={() => {
                  if (btn.disabled) return
                  const next = Math.max(10, Math.min(500, guestCount + btn.delta))
                  onGuestCount(next)
                }}
              >
                <Text
                  style={{
                    color: btn.disabled ? C.text3 : C.primary,
                    fontSize: '24rpx',
                    fontWeight: '700',
                  }}
                >
                  {btn.label}
                </Text>
              </View>
            ))}
          </View>
        </View>
        <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '12rpx' }}>
          {[10, 20, 30, 50, 80, 100, 150, 200].map((n) => (
            <View
              key={n}
              style={{
                paddingHorizontal: '20rpx',
                paddingVertical: '10rpx',
                borderRadius: '32rpx',
                border: `2rpx solid ${guestCount === n ? C.primary : C.border}`,
                background: guestCount === n ? C.primaryFaint : C.bgDeep,
              }}
              onClick={() => onGuestCount(n)}
            >
              <Text
                style={{
                  color: guestCount === n ? C.primary : C.text2,
                  fontSize: '24rpx',
                  fontWeight: guestCount === n ? '700' : '400',
                }}
              >
                {n}人
              </Text>
            </View>
          ))}
        </View>
      </Section>

      {/* Date picker */}
      <Section title="宴会日期（最近60天）">
        <ScrollView scrollX style={{ whiteSpace: 'nowrap' }}>
          <View style={{ display: 'flex', flexDirection: 'row', gap: '12rpx' }}>
            {dates.map((d) => {
              const selected = date === d
              const dt = new Date(d + 'T00:00:00')
              const days = ['日', '一', '二', '三', '四', '五', '六']
              const isWeekend = dt.getDay() === 0 || dt.getDay() === 6
              return (
                <View
                  key={d}
                  style={{
                    minWidth: '100rpx',
                    padding: '14rpx 16rpx',
                    borderRadius: '12rpx',
                    border: `2rpx solid ${selected ? C.primary : isWeekend ? C.gold : C.border}`,
                    background: selected
                      ? C.primaryFaint
                      : isWeekend
                      ? C.goldFaint
                      : C.bgDeep,
                    alignItems: 'center',
                    flexShrink: 0,
                  }}
                  onClick={() => onDate(d)}
                >
                  <Text
                    style={{
                      color: selected ? C.primary : isWeekend ? C.gold : C.text2,
                      fontSize: '22rpx',
                      fontWeight: selected ? '700' : '400',
                    }}
                  >
                    {d.slice(5).replace('-', '/')}
                  </Text>
                  <Text
                    style={{
                      color: selected ? C.primary : isWeekend ? C.gold : C.text3,
                      fontSize: '20rpx',
                      marginTop: '4rpx',
                    }}
                  >
                    周{days[dt.getDay()]}
                  </Text>
                </View>
              )
            })}
          </View>
        </ScrollView>
        {date && (
          <Text style={{ color: C.text2, fontSize: '24rpx', marginTop: '12rpx' }}>
            已选：{formatDateDisplay(date)}
          </Text>
        )}
      </Section>

      {/* Meal time */}
      <Section title="用餐时间">
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          {MEAL_TIMES.map((mt) => {
            const selected = mealTime === mt.value
            return (
              <View
                key={mt.value}
                style={{
                  flex: 1,
                  padding: '20rpx 8rpx',
                  borderRadius: '12rpx',
                  border: `2rpx solid ${selected ? C.primary : C.border}`,
                  background: selected ? C.primaryFaint : C.bgDeep,
                  alignItems: 'center',
                }}
                onClick={() => onMealTime(mt.value)}
              >
                <Text
                  style={{
                    color: selected ? C.primary : C.text2,
                    fontSize: '28rpx',
                    fontWeight: selected ? '700' : '400',
                    marginBottom: '4rpx',
                  }}
                >
                  {mt.label}
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx' }}>{mt.sub}</Text>
              </View>
            )
          })}
        </View>
      </Section>

      {/* Budget */}
      <Section title="人均预算">
        <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '12rpx' }}>
          {BUDGET_PRESETS.map((bp) => {
            const selected = budgetPerPersonFen === bp.fen
            return (
              <View
                key={bp.fen}
                style={{
                  paddingHorizontal: '28rpx',
                  paddingVertical: '14rpx',
                  borderRadius: '32rpx',
                  border: `2rpx solid ${selected ? C.primary : C.border}`,
                  background: selected ? C.primaryFaint : C.bgDeep,
                }}
                onClick={() => onBudget(bp.fen)}
              >
                <Text
                  style={{
                    color: selected ? C.primary : C.text2,
                    fontSize: '26rpx',
                    fontWeight: selected ? '700' : '400',
                  }}
                >
                  {bp.label}
                </Text>
              </View>
            )
          })}
        </View>

        {budgetPerPersonFen > 0 && (
          <View
            style={{
              marginTop: '16rpx',
              background: C.bgDeep,
              borderRadius: '12rpx',
              padding: '16rpx 20rpx',
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>
              {guestCount}人预估总额
            </Text>
            <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '700' }}>
              {fenToYuanDisplay(budgetPerPersonFen * guestCount)}
            </Text>
          </View>
        )}
      </Section>

      <NavBar
        onBack={onBack}
        onNext={onNext}
        nextLabel="下一步：选择套餐"
        nextDisabled={!canProceed}
      />
    </ScrollView>
  )
}

// ─── Step 3: Package Selection ────────────────────────────────────────────────

function Step3PackageSelect({
  budgetPerPersonFen,
  guestCount,
  selectedPackageId,
  onSelect,
  onBack,
  onNext,
}: {
  budgetPerPersonFen: number
  guestCount: number
  selectedPackageId: string | null
  onSelect: (pkg: BanquetPackage) => void
  onBack: () => void
  onNext: () => void
}) {
  const [packages, setPackages] = useState<BanquetPackage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    txRequest<BanquetPackage[]>('/banquet/packages', 'GET', {
      budgetFen: budgetPerPersonFen,
      guestCount,
    })
      .then((data) => setPackages(data))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '加载失败')
      })
      .finally(() => setLoading(false))
  }, [budgetPerPersonFen, guestCount])

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '180rpx' }}>
      <View style={{ padding: '20rpx 24rpx 12rpx' }}>
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>
          人均预算：{fenToYuanDisplay(budgetPerPersonFen)} · 共{guestCount}人
        </Text>
      </View>

      {loading ? (
        <View style={{ padding: '80rpx', alignItems: 'center' }}>
          <Text style={{ color: C.text2, fontSize: '28rpx' }}>正在匹配套餐...</Text>
        </View>
      ) : error ? (
        <View style={{ padding: '80rpx', alignItems: 'center' }}>
          <Text style={{ color: C.red, fontSize: '28rpx', marginBottom: '24rpx' }}>{error}</Text>
        </View>
      ) : packages.length === 0 ? (
        <View style={{ padding: '64rpx 32rpx', alignItems: 'center' }}>
          <Text style={{ fontSize: '64rpx', marginBottom: '20rpx' }}>🍽</Text>
          <Text style={{ color: C.text2, fontSize: '28rpx', textAlign: 'center' }}>
            当前预算暂无精确匹配套餐，请联系我们定制方案
          </Text>
        </View>
      ) : (
        packages.map((pkg) => {
          const isSelected = selectedPackageId === pkg.packageId
          const isExpanded = expandedId === pkg.packageId
          const totalFen = pkg.pricePerPersonFen * guestCount

          return (
            <View
              key={pkg.packageId}
              style={{
                background: C.bgCard,
                borderRadius: '16rpx',
                margin: '0 24rpx 16rpx',
                border: `2rpx solid ${isSelected ? C.primary : C.border}`,
                overflow: 'hidden',
              }}
            >
              {/* Package header */}
              <View style={{ padding: '24rpx' }}>
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    marginBottom: '12rpx',
                  }}
                >
                  <View style={{ flex: 1 }}>
                    <Text
                      style={{
                        color: C.text1,
                        fontSize: '30rpx',
                        fontWeight: '700',
                        marginBottom: '6rpx',
                      }}
                    >
                      {pkg.name}
                    </Text>
                    <Text style={{ color: C.text3, fontSize: '24rpx', lineHeight: '1.5' }}>
                      {pkg.description}
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end', marginLeft: '16rpx', flexShrink: 0 }}>
                    <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '800' }}>
                      {fenToYuanDisplay(pkg.pricePerPersonFen)}
                    </Text>
                    <Text style={{ color: C.text3, fontSize: '22rpx' }}>/人</Text>
                  </View>
                </View>

                <Text style={{ color: C.text2, fontSize: '24rpx', marginBottom: '12rpx' }}>
                  共{pkg.dishCount}道菜 · {guestCount}桌约{fenToYuanDisplay(totalFen)}
                </Text>

                {/* Featured dishes */}
                <Text style={{ color: C.text2, fontSize: '24rpx' }} numberOfLines={2}>
                  {pkg.featuredDishes.join(' · ')}
                </Text>
              </View>

              {/* Action row */}
              <View
                style={{
                  borderTop: `1rpx solid ${C.border}`,
                  display: 'flex',
                  flexDirection: 'row',
                }}
              >
                <View
                  style={{
                    flex: 1,
                    height: '80rpx',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRight: `1rpx solid ${C.border}`,
                  }}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : pkg.packageId)
                  }
                >
                  <Text style={{ color: C.text2, fontSize: '26rpx' }}>
                    {isExpanded ? '收起菜单 ▲' : '查看详情 ▼'}
                  </Text>
                </View>
                <View
                  style={{
                    flex: 1,
                    height: '80rpx',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: isSelected ? C.primaryFaint : 'transparent',
                  }}
                  onClick={() => onSelect(pkg)}
                >
                  <Text
                    style={{
                      color: isSelected ? C.primary : C.text2,
                      fontSize: '26rpx',
                      fontWeight: isSelected ? '700' : '400',
                    }}
                  >
                    {isSelected ? '✓ 已选择' : '选择此套餐'}
                  </Text>
                </View>
              </View>

              {/* Dish list expansion */}
              {isExpanded && (
                <View
                  style={{
                    borderTop: `1rpx solid ${C.border}`,
                    padding: '16rpx 24rpx',
                  }}
                >
                  {pkg.allDishes && pkg.allDishes.length > 0 ? (
                    (() => {
                      // Group by category
                      const categoryMap: Record<string, string[]> = {}
                      pkg.allDishes.forEach((d) => {
                        if (!categoryMap[d.category]) categoryMap[d.category] = []
                        categoryMap[d.category].push(d.name)
                      })
                      return Object.entries(categoryMap).map(([cat, dishes]) => (
                        <View key={cat} style={{ marginBottom: '12rpx' }}>
                          <Text
                            style={{
                              color: C.text3,
                              fontSize: '22rpx',
                              fontWeight: '600',
                              marginBottom: '6rpx',
                            }}
                          >
                            {cat}
                          </Text>
                          <Text style={{ color: C.text2, fontSize: '26rpx', lineHeight: '1.6' }}>
                            {dishes.join('、')}
                          </Text>
                        </View>
                      ))
                    })()
                  ) : (
                    pkg.featuredDishes.map((name, i) => (
                      <View
                        key={i}
                        style={{
                          display: 'flex',
                          flexDirection: 'row',
                          alignItems: 'center',
                          paddingVertical: '8rpx',
                          borderBottom: i < pkg.featuredDishes.length - 1
                            ? `1rpx solid ${C.border}`
                            : 'none',
                        }}
                      >
                        <View
                          style={{
                            width: '8rpx',
                            height: '8rpx',
                            borderRadius: '4rpx',
                            background: C.primary,
                            marginRight: '16rpx',
                            flexShrink: 0,
                          }}
                        />
                        <Text style={{ color: C.text1, fontSize: '26rpx' }}>{name}</Text>
                      </View>
                    ))
                  )}
                </View>
              )}
            </View>
          )
        })
      )}

      <NavBar
        onBack={onBack}
        onNext={onNext}
        nextLabel="下一步：确认定金"
        nextDisabled={selectedPackageId === null}
      />
    </ScrollView>
  )
}

// ─── Step 4: Confirm & Deposit ────────────────────────────────────────────────

function Step4Confirm({
  banquetType,
  guestCount,
  date,
  mealTime,
  budgetPerPersonFen,
  selectedPackage,
  onBack,
  onSuccess,
}: {
  banquetType: BanquetType
  guestCount: number
  date: string
  mealTime: MealTime
  budgetPerPersonFen: number
  selectedPackage: BanquetPackage
  onBack: () => void
  onSuccess: (bookingId: string) => void
}) {
  const { isLoggedIn, storedValueFen } = useUserStore()
  const [contact, setContact] = useState<ContactForm>({ name: '', phone: '' })
  const [errors, setErrors] = useState<Partial<ContactForm>>({})
  const [paySheetVisible, setPaySheetVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const typeDef = BANQUET_TYPES.find((bt) => bt.value === banquetType)!
  const mealTimeDef = MEAL_TIMES.find((mt) => mt.value === mealTime)!

  const totalFen = selectedPackage.pricePerPersonFen * guestCount
  const depositFen = Math.round(totalFen * DEPOSIT_RATE)
  const remainFen = totalFen - depositFen

  function validate(): boolean {
    const errs: Partial<ContactForm> = {}
    if (!contact.name.trim()) errs.name = '请输入联系人姓名'
    if (!/^1[3-9]\d{9}$/.test(contact.phone)) errs.phone = '请输入正确的手机号'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  function handlePay() {
    if (!isLoggedIn) {
      Taro.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    if (!validate()) return
    setPaySheetVisible(true)
  }

  const handlePayConfirm = useCallback(
    async (method: 'wechat' | 'stored_value' | 'mixed', mixedStoredFen?: number) => {
      setPaySheetVisible(false)
      setSubmitting(true)
      try {
        // 1. Create booking
        const booking = await txRequest<{ bookingId: string; paymentParams: Record<string, unknown> }>(
          '/banquet/bookings',
          'POST',
          {
            banquetType,
            guestCount,
            date,
            mealTime,
            budgetPerPersonFen,
            packageId: selectedPackage.packageId,
            contactName: contact.name.trim(),
            contactPhone: contact.phone,
            depositFen,
            paymentMethod: method,
          } as BookingPayload & {
            depositFen: number
            paymentMethod: string
          },
        )

        // 2. Launch payment for deposit
        if (method === 'wechat' || method === 'mixed') {
          await Taro.requestPayment(booking.paymentParams as Parameters<typeof Taro.requestPayment>[0])
        }

        onSuccess(booking.bookingId)
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : '支付失败，请重试'
        Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
      } finally {
        setSubmitting(false)
      }
    },
    [banquetType, guestCount, date, mealTime, budgetPerPersonFen, selectedPackage, contact, depositFen, onSuccess],
  )

  return (
    <>
      <ScrollView scrollY style={{ flex: 1, paddingBottom: '200rpx' }}>
        {/* Booking summary */}
        <Section title="预订摘要">
          {[
            { label: '宴会类型', value: `${typeDef.icon} ${typeDef.label}` },
            { label: '日期时间', value: `${formatDateDisplay(date)} · ${mealTimeDef.label}（${mealTimeDef.sub}）` },
            { label: '用餐人数', value: `${guestCount}人` },
            { label: '套餐名称', value: selectedPackage.name },
            { label: '人均标准', value: fenToYuanDisplay(selectedPackage.pricePerPersonFen) },
          ].map(({ label, value }) => (
            <View
              key={label}
              style={{
                display: 'flex',
                flexDirection: 'row',
                paddingVertical: '12rpx',
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
              <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1, lineHeight: '1.5' }}>
                {value}
              </Text>
            </View>
          ))}
        </Section>

        {/* Price & deposit */}
        <Section title="费用说明">
          <PriceLine
            label="套餐总价"
            value={fenToYuanDisplay(totalFen)}
            sub={`${fenToYuanDisplay(selectedPackage.pricePerPersonFen)}/人 × ${guestCount}人`}
          />
          <PriceLine
            label="今日支付定金（20%）"
            value={fenToYuanDisplay(depositFen)}
            accent
            large
          />
          <View style={{ height: '1rpx', background: C.border, margin: '8rpx 0 12rpx' }} />
          <PriceLine
            label="余款到场结清"
            value={fenToYuanDisplay(remainFen)}
          />

          <View
            style={{
              background: C.warningFaint,
              borderRadius: '12rpx',
              padding: '16rpx',
              marginTop: '8rpx',
              border: `1rpx solid rgba(245,166,35,0.3)`,
            }}
          >
            <Text style={{ color: C.warning, fontSize: '24rpx', lineHeight: '1.6' }}>
              定金支付后预订即时确认。余款 {fenToYuanDisplay(remainFen)} 请在宴会当天结清。如需取消，请提前7天联系我们。
            </Text>
          </View>
        </Section>

        {/* Contact */}
        <Section title="联系人信息">
          <View style={{ marginBottom: '16rpx' }}>
            <Text
              style={{
                color: C.text2,
                fontSize: '26rpx',
                marginBottom: '10rpx',
              }}
            >
              <Text style={{ color: C.red }}>* </Text>联系人姓名
            </Text>
            <Input
              value={contact.name}
              placeholder="请输入联系人姓名"
              placeholderStyle={`color:${C.text3}`}
              onInput={(e) => setContact((c) => ({ ...c, name: e.detail.value }))}
              style={{
                background: C.bgDeep,
                color: C.text1,
                fontSize: '28rpx',
                borderRadius: '12rpx',
                padding: '20rpx',
                border: `1rpx solid ${errors.name ? C.red : C.border}`,
              }}
            />
            {errors.name && (
              <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
                {errors.name}
              </Text>
            )}
          </View>

          <View>
            <Text
              style={{
                color: C.text2,
                fontSize: '26rpx',
                marginBottom: '10rpx',
              }}
            >
              <Text style={{ color: C.red }}>* </Text>联系电话
            </Text>
            <Input
              value={contact.phone}
              placeholder="请输入手机号"
              placeholderStyle={`color:${C.text3}`}
              type="number"
              maxlength={11}
              onInput={(e) => setContact((c) => ({ ...c, phone: e.detail.value }))}
              style={{
                background: C.bgDeep,
                color: C.text1,
                fontSize: '28rpx',
                borderRadius: '12rpx',
                padding: '20rpx',
                border: `1rpx solid ${errors.phone ? C.red : C.border}`,
              }}
            />
            {errors.phone && (
              <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
                {errors.phone}
              </Text>
            )}
          </View>
        </Section>

        <NavBar
          onBack={onBack}
          onNext={handlePay}
          nextLabel={`支付定金 ${fenToYuanDisplay(depositFen)}`}
          loading={submitting}
        />
      </ScrollView>

      {/* Payment sheet */}
      <PaymentSheet
        visible={paySheetVisible}
        totalFen={depositFen}
        storedValueFen={storedValueFen}
        onClose={() => setPaySheetVisible(false)}
        onConfirm={handlePayConfirm}
      />
    </>
  )
}

// ─── Success Screen ───────────────────────────────────────────────────────────

function SuccessScreen({
  bookingId,
  depositFen,
}: {
  bookingId: string
  depositFen: number
}) {
  return (
    <View
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48rpx',
      }}
    >
      <View
        style={{
          width: '160rpx',
          height: '160rpx',
          borderRadius: '80rpx',
          background: C.successFaint,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '32rpx',
        }}
      >
        <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>🎉</Text>
      </View>
      <Text
        style={{
          color: C.text1,
          fontSize: '40rpx',
          fontWeight: '800',
          marginBottom: '16rpx',
        }}
      >
        预订成功！
      </Text>
      <Text
        style={{
          color: C.text2,
          fontSize: '28rpx',
          textAlign: 'center',
          lineHeight: '1.6',
          marginBottom: '8rpx',
        }}
      >
        定金 {fenToYuanDisplay(depositFen)} 已支付
      </Text>
      <Text
        style={{
          color: C.text3,
          fontSize: '24rpx',
          textAlign: 'center',
          lineHeight: '1.6',
          marginBottom: '48rpx',
        }}
      >
        预订编号：{bookingId}
        {'\n'}我们将在24小时内与您确认详情
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
          marginBottom: '16rpx',
        }}
        onClick={() => Taro.switchTab({ url: '/pages/index/index' })}
      >
        <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>返回首页</Text>
      </View>
      <View
        style={{
          height: '88rpx',
          width: '400rpx',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: `2rpx solid ${C.border}`,
          borderRadius: '44rpx',
        }}
        onClick={() =>
          Taro.navigateTo({ url: '/pages/order/index' })
        }
      >
        <Text style={{ color: C.text2, fontSize: '32rpx', fontWeight: '600' }}>查看预订记录</Text>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function BanquetPage() {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1)

  // Step 1 state
  const [banquetType, setBanquetType] = useState<BanquetType | null>(null)

  // Step 2 state
  const [guestCount, setGuestCount] = useState(20)
  const [date, setDate] = useState('')
  const [mealTime, setMealTime] = useState<MealTime>('dinner')
  const [budgetPerPersonFen, setBudgetPerPersonFen] = useState(28800)

  // Step 3 state
  const [selectedPackage, setSelectedPackage] = useState<BanquetPackage | null>(null)

  // Step 4 / success state
  const [bookingId, setBookingId] = useState<string | null>(null)
  const [depositFen, setDepositFen] = useState(0)

  const goNext = useCallback(() => {
    if (step < 4) setStep((s) => (s + 1) as 1 | 2 | 3 | 4)
  }, [step])

  const goBack = useCallback(() => {
    if (step > 1) setStep((s) => (s - 1) as 1 | 2 | 3 | 4)
  }, [step])

  const handleSuccess = useCallback(
    (id: string) => {
      setBookingId(id)
      if (selectedPackage) {
        const total = selectedPackage.pricePerPersonFen * guestCount
        setDepositFen(Math.round(total * DEPOSIT_RATE))
      }
    },
    [selectedPackage, guestCount],
  )

  // Success screen (replaces wizard)
  if (bookingId !== null) {
    return (
      <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
        <SuccessScreen bookingId={bookingId} depositFen={depositFen} />
      </View>
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
      <View
        style={{
          padding: '24rpx 32rpx 0',
          background: C.bgDeep,
        }}
      >
        <Text style={{ color: C.text1, fontSize: '40rpx', fontWeight: '800' }}>宴会预订</Text>
        <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '8rpx' }}>
          专业宴会策划，一站式预订服务
        </Text>
      </View>

      {/* Progress */}
      <ProgressBar step={step} />

      {/* Steps */}
      {step === 1 && (
        <Step1TypeSelect
          selected={banquetType}
          onSelect={setBanquetType}
          onNext={goNext}
        />
      )}

      {step === 2 && (
        <Step2BasicInfo
          guestCount={guestCount}
          date={date}
          mealTime={mealTime}
          budgetPerPersonFen={budgetPerPersonFen}
          onGuestCount={setGuestCount}
          onDate={setDate}
          onMealTime={setMealTime}
          onBudget={setBudgetPerPersonFen}
          onBack={goBack}
          onNext={goNext}
        />
      )}

      {step === 3 && (
        <Step3PackageSelect
          budgetPerPersonFen={budgetPerPersonFen}
          guestCount={guestCount}
          selectedPackageId={selectedPackage?.packageId ?? null}
          onSelect={(pkg) => setSelectedPackage(pkg)}
          onBack={goBack}
          onNext={goNext}
        />
      )}

      {step === 4 && banquetType !== null && selectedPackage !== null && (
        <Step4Confirm
          banquetType={banquetType}
          guestCount={guestCount}
          date={date}
          mealTime={mealTime}
          budgetPerPersonFen={budgetPerPersonFen}
          selectedPackage={selectedPackage}
          onBack={goBack}
          onSuccess={handleSuccess}
        />
      )}
    </View>
  )
}
