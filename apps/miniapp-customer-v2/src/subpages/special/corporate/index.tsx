/**
 * corporate/index.tsx — 企业团餐
 *
 * Two top-level states:
 *  A. Unbound — show benefits + bind-account form
 *  B. Bound   — company status card + quick actions
 *
 * Sub-flows inside Bound:
 *  1. 发起团餐 — event name / headcount / budget / date+time / menu prefs → submit
 *  2. 消费记录 — paginated list of past corporate orders
 *  3. 申请发票 — company info pre-filled + order selection + invoice type
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, ScrollView, Input, Textarea } from '@tarojs/components'
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
  successFaint: 'rgba(76,175,80,0.12)',
  warning: '#F5A623',
  warningFaint: 'rgba(245,166,35,0.12)',
  white: '#FFFFFF',
  disabled: '#2A4050',
  info: '#3B9EFF',
  infoFaint: 'rgba(59,158,255,0.12)',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type CorporateView = 'main' | 'order' | 'records' | 'invoice'
type InvoiceType = 'general' | 'special'
type MenuPref = '海鲜' | '红肉' | '素食' | '儿童友好' | '清真' | '低卡'

interface CorporateAccount {
  companyName: string
  taxId: string
  contactName: string
  contactPhone: string
  creditLimitFen: number
  usedAmountFen: number
  discount: number   // e.g. 0.88 means 88 折
}

interface CorporateOrder {
  orderId: string
  eventName: string
  headCount: number
  date: string
  totalFen: number
  status: 'pending' | 'confirmed' | 'completed' | 'cancelled'
  invoiceApplied: boolean
}

interface RecommendedPackage {
  packageId: string
  name: string
  pricePerPersonFen: number
  dishCount: number
  featuredDishes: string[]
}

interface BindForm {
  companyName: string
  taxId: string
  contactName: string
  contactPhone: string
}

interface OrderForm {
  eventName: string
  headCount: number
  budgetPerPersonFen: number
  date: string
  time: string
  menuPrefs: MenuPref[]
}

interface InvoiceForm {
  selectedOrderIds: string[]
  invoiceType: InvoiceType
}

// ─── Constants ────────────────────────────────────────────────────────────────

const BENEFITS = [
  { icon: '🏷', title: '专属折扣', desc: '最高享受88折企业优惠' },
  { icon: '📅', title: '月结账期', desc: '每月底统一结算，无需每次付款' },
  { icon: '🧾', title: '电子发票', desc: '一键申请增值税专票/普票' },
  { icon: '👥', title: '多人协同', desc: '团队成员共享账户，一起点餐' },
]

const MENU_PREFS: MenuPref[] = ['海鲜', '红肉', '素食', '儿童友好', '清真', '低卡']

const BUDGET_PRESETS = [
  { label: '¥188/人', fen: 18800 },
  { label: '¥288/人', fen: 28800 },
  { label: '¥388/人', fen: 38800 },
  { label: '¥488/人', fen: 48800 },
  { label: '¥688+/人', fen: 68800 },
]

const STATUS_LABELS: Record<CorporateOrder['status'], { label: string; color: string }> = {
  pending: { label: '待确认', color: C.warning },
  confirmed: { label: '已确认', color: C.info },
  completed: { label: '已完成', color: C.success },
  cancelled: { label: '已取消', color: C.text3 },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getNext14Days(): string[] {
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

function validateTaxId(id: string): boolean {
  // 18位统一社会信用代码简单格式校验
  return /^[0-9A-Z]{18}$/.test(id.toUpperCase())
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function Section({
  title,
  children,
  action,
}: {
  title?: string
  children: React.ReactNode
  action?: React.ReactNode
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
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600' }}>{title}</Text>
          {action}
        </View>
      )}
      <View style={{ padding: '16rpx 24rpx 20rpx' }}>{children}</View>
    </View>
  )
}

function FormField({
  label,
  required,
  children,
}: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <View style={{ marginBottom: '20rpx' }}>
      <Text
        style={{
          color: C.text2,
          fontSize: '26rpx',
          marginBottom: '10rpx',
          display: 'block',
        }}
      >
        {required && (
          <Text style={{ color: C.red }}>* </Text>
        )}
        {label}
      </Text>
      {children}
    </View>
  )
}

function StyledInput({
  value,
  placeholder,
  onInput,
  type,
  maxlength,
}: {
  value: string
  placeholder: string
  onInput: (val: string) => void
  type?: 'text' | 'number' | 'digit' | 'idcard'
  maxlength?: number
}) {
  return (
    <Input
      value={value}
      placeholder={placeholder}
      placeholderStyle={`color:${C.text3}`}
      type={type ?? 'text'}
      maxlength={maxlength}
      onInput={(e) => onInput(e.detail.value)}
      style={{
        background: C.bgDeep,
        color: C.text1,
        fontSize: '28rpx',
        borderRadius: '12rpx',
        padding: '20rpx',
        border: `1rpx solid ${C.border}`,
      }}
    />
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

function Stepper({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
}) {
  const s = step ?? 1
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: '0rpx',
      }}
    >
      <View
        style={{
          width: '64rpx',
          height: '64rpx',
          borderRadius: '32rpx',
          border: `2rpx solid ${value <= min ? C.border : C.primary}`,
          background: value <= min ? C.bgDeep : C.primaryFaint,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onClick={() => value > min && onChange(value - s)}
      >
        <Text
          style={{
            color: value <= min ? C.text3 : C.primary,
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
        {value}
      </Text>
      <View
        style={{
          width: '64rpx',
          height: '64rpx',
          borderRadius: '32rpx',
          border: `2rpx solid ${value >= max ? C.border : C.primary}`,
          background: value >= max ? C.bgDeep : C.primaryFaint,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onClick={() => value < max && onChange(value + s)}
      >
        <Text
          style={{
            color: value >= max ? C.text3 : C.primary,
            fontSize: '36rpx',
            fontWeight: '700',
            lineHeight: '1',
          }}
        >
          +
        </Text>
      </View>
    </View>
  )
}

function FixedBar({ children }: { children: React.ReactNode }) {
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
        zIndex: 100,
      }}
    >
      {children}
    </View>
  )
}

// ─── A: Unbound State ─────────────────────────────────────────────────────────

function UnboundView({ onBound }: { onBound: (account: CorporateAccount) => void }) {
  const [form, setForm] = useState<BindForm>({
    companyName: '',
    taxId: '',
    contactName: '',
    contactPhone: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<Partial<BindForm>>({})

  function validate(): boolean {
    const errs: Partial<BindForm> = {}
    if (!form.companyName.trim()) errs.companyName = '请输入公司名称'
    if (!validateTaxId(form.taxId)) errs.taxId = '请输入正确的18位统一社会信用代码'
    if (!form.contactName.trim()) errs.contactName = '请输入联系人姓名'
    if (!/^1[3-9]\d{9}$/.test(form.contactPhone)) errs.contactPhone = '请输入正确的手机号'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  async function handleBind() {
    if (!validate()) return
    setSubmitting(true)
    try {
      const account = await txRequest<CorporateAccount>('/corporate/accounts/bind', 'POST', {
        companyName: form.companyName.trim(),
        taxId: form.taxId.toUpperCase(),
        contactName: form.contactName.trim(),
        contactPhone: form.contactPhone,
      })
      Taro.showToast({ title: '绑定成功', icon: 'success' })
      onBound(account)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '绑定失败，请重试'
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '180rpx' }}>
      {/* Benefits */}
      <View style={{ padding: '32rpx 24rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '800', marginBottom: '8rpx' }}>
          开通企业账户
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>享受企业专属权益</Text>
      </View>

      <View
        style={{
          display: 'grid' as any,
          gridTemplateColumns: '1fr 1fr',
          gap: '16rpx',
          margin: '0 24rpx 24rpx',
        }}
      >
        {BENEFITS.map((b) => (
          <View
            key={b.title}
            style={{
              background: C.bgCard,
              borderRadius: '16rpx',
              padding: '24rpx',
              border: `1rpx solid ${C.border}`,
            }}
          >
            <Text style={{ fontSize: '40rpx', marginBottom: '12rpx', display: 'block' }}>
              {b.icon}
            </Text>
            <Text
              style={{
                color: C.text1,
                fontSize: '28rpx',
                fontWeight: '600',
                marginBottom: '6rpx',
                display: 'block',
              }}
            >
              {b.title}
            </Text>
            <Text style={{ color: C.text3, fontSize: '24rpx', lineHeight: '1.5' }}>
              {b.desc}
            </Text>
          </View>
        ))}
      </View>

      {/* Bind form */}
      <Section title="绑定企业账户">
        <FormField label="公司名称" required>
          <StyledInput
            value={form.companyName}
            placeholder="请输入营业执照上的公司全称"
            onInput={(v) => setForm((f) => ({ ...f, companyName: v }))}
          />
          {errors.companyName && (
            <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
              {errors.companyName}
            </Text>
          )}
        </FormField>

        <FormField label="统一社会信用代码" required>
          <StyledInput
            value={form.taxId}
            placeholder="18位统一社会信用代码"
            onInput={(v) => setForm((f) => ({ ...f, taxId: v }))}
            maxlength={18}
          />
          {errors.taxId && (
            <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
              {errors.taxId}
            </Text>
          )}
        </FormField>

        <FormField label="联系人姓名" required>
          <StyledInput
            value={form.contactName}
            placeholder="请输入企业联系人姓名"
            onInput={(v) => setForm((f) => ({ ...f, contactName: v }))}
          />
          {errors.contactName && (
            <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
              {errors.contactName}
            </Text>
          )}
        </FormField>

        <FormField label="联系人手机号" required>
          <StyledInput
            value={form.contactPhone}
            placeholder="请输入手机号"
            onInput={(v) => setForm((f) => ({ ...f, contactPhone: v }))}
            type="number"
            maxlength={11}
          />
          {errors.contactPhone && (
            <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx' }}>
              {errors.contactPhone}
            </Text>
          )}
        </FormField>
      </Section>

      <FixedBar>
        <View
          style={{
            background: submitting ? C.disabled : C.primary,
            borderRadius: '44rpx',
            height: '88rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: submitting ? 0.7 : 1,
          }}
          onClick={submitting ? undefined : handleBind}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '绑定中...' : '绑定企业账户'}
          </Text>
        </View>
      </FixedBar>
    </ScrollView>
  )
}

// ─── B: Bound main card ───────────────────────────────────────────────────────

function AccountCard({ account }: { account: CorporateAccount }) {
  const usedRatio = account.creditLimitFen > 0
    ? Math.min(1, account.usedAmountFen / account.creditLimitFen)
    : 0
  const remainFen = account.creditLimitFen - account.usedAmountFen

  return (
    <View
      style={{
        margin: '16rpx 24rpx',
        background: 'linear-gradient(135deg, #1A3040 0%, #132029 100%)',
        borderRadius: '24rpx',
        padding: '32rpx',
        border: `1rpx solid ${C.primary}`,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* Decorative top-right glow */}
      <View
        style={{
          position: 'absolute',
          top: '-40rpx',
          right: '-40rpx',
          width: '160rpx',
          height: '160rpx',
          borderRadius: '80rpx',
          background: C.primaryFaint,
        }}
      />

      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: '24rpx',
        }}
      >
        <View>
          <Text style={{ color: C.text3, fontSize: '22rpx', marginBottom: '6rpx' }}>
            企业账户
          </Text>
          <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700' }}>
            {account.companyName}
          </Text>
        </View>
        <View
          style={{
            background: C.primaryFaint,
            borderRadius: '10rpx',
            paddingHorizontal: '16rpx',
            paddingVertical: '6rpx',
            border: `1rpx solid ${C.primary}`,
          }}
        >
          <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '600' }}>
            {Math.round((1 - account.discount) * 100)}折优惠
          </Text>
        </View>
      </View>

      {/* Credit usage */}
      <View style={{ marginBottom: '8rpx' }}>
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'space-between',
            marginBottom: '10rpx',
          }}
        >
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>
            已用 {fenToYuanDisplay(account.usedAmountFen)}
          </Text>
          <Text style={{ color: C.text2, fontSize: '24rpx' }}>
            授信 {fenToYuanDisplay(account.creditLimitFen)}
          </Text>
        </View>
        {/* Progress bar */}
        <View
          style={{
            height: '12rpx',
            background: C.bgDeep,
            borderRadius: '6rpx',
            overflow: 'hidden',
          }}
        >
          <View
            style={{
              height: '100%',
              width: `${(usedRatio * 100).toFixed(1)}%`,
              background: usedRatio > 0.85 ? C.red : C.primary,
              borderRadius: '6rpx',
            }}
          />
        </View>
        <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '8rpx' }}>
          剩余可用 {fenToYuanDisplay(remainFen)}
        </Text>
      </View>
    </View>
  )
}

// ─── Corporate Order Form ─────────────────────────────────────────────────────

function CorporateOrderView({
  account,
  onBack,
  onSuccess,
}: {
  account: CorporateAccount
  onBack: () => void
  onSuccess: () => void
}) {
  const dates = getNext14Days()
  const [form, setForm] = useState<OrderForm>({
    eventName: '',
    headCount: 10,
    budgetPerPersonFen: 28800,
    date: dates[0],
    time: '12:00',
    menuPrefs: [],
  })
  const [packages, setPackages] = useState<RecommendedPackage[]>([])
  const [pkgLoading, setPkgLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load recommended packages when budget changes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      if (form.budgetPerPersonFen <= 0) return
      setPkgLoading(true)
      try {
        const data = await txRequest<RecommendedPackage[]>('/corporate/packages', 'GET', {
          budgetFen: form.budgetPerPersonFen,
        })
        setPackages(data)
      } catch {
        setPackages([])
      } finally {
        setPkgLoading(false)
      }
    }, 600)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [form.budgetPerPersonFen])

  const canSubmit =
    form.eventName.trim().length >= 2 &&
    form.headCount >= 2 &&
    form.budgetPerPersonFen > 0 &&
    form.date !== ''

  const totalEstFen = form.headCount * form.budgetPerPersonFen
  const discountedFen = Math.round(totalEstFen * account.discount)

  async function handleSubmit() {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      await txRequest('/corporate/orders', 'POST', {
        eventName: form.eventName.trim(),
        headCount: form.headCount,
        budgetPerPersonFen: form.budgetPerPersonFen,
        date: form.date,
        time: form.time,
        menuPrefs: form.menuPrefs,
      })
      Taro.showToast({ title: '团餐下单成功', icon: 'success' })
      onSuccess()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '下单失败，请重试'
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '200rpx' }}>
      {/* Back row */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '20rpx 24rpx',
        }}
        onClick={onBack}
      >
        <Text style={{ color: C.primary, fontSize: '28rpx' }}>← 返回</Text>
      </View>

      <View style={{ padding: '0 24rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>发起团餐</Text>
      </View>

      <Section title="活动信息">
        <FormField label="活动名称" required>
          <StyledInput
            value={form.eventName}
            placeholder="如：Q2团建午餐、销售季度表彰宴"
            onInput={(v) => setForm((f) => ({ ...f, eventName: v }))}
            maxlength={50}
          />
        </FormField>

        <FormField label="用餐人数" required>
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>{form.headCount}人</Text>
            <Stepper
              value={form.headCount}
              min={2}
              max={500}
              step={5}
              onChange={(v) => setForm((f) => ({ ...f, headCount: v }))}
            />
          </View>
        </FormField>

        <FormField label="人均预算" required>
          <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', marginBottom: '12rpx' }}>
            {BUDGET_PRESETS.map((bp) => {
              const selected = form.budgetPerPersonFen === bp.fen
              return (
                <Chip
                  key={bp.fen}
                  label={bp.label}
                  selected={selected}
                  onTap={() => setForm((f) => ({ ...f, budgetPerPersonFen: bp.fen }))}
                />
              )
            })}
          </View>
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>
            当前：{fenToYuanDisplay(form.budgetPerPersonFen)}/人，预计总额 {fenToYuanDisplay(totalEstFen)}
          </Text>
          {account.discount < 1 && (
            <Text style={{ color: C.primary, fontSize: '22rpx', marginTop: '4rpx' }}>
              企业折扣后约 {fenToYuanDisplay(discountedFen)}
            </Text>
          )}
        </FormField>
      </Section>

      <Section title="时间安排">
        <FormField label="用餐日期" required>
          <ScrollView scrollX style={{ whiteSpace: 'nowrap' }}>
            <View style={{ display: 'flex', flexDirection: 'row', gap: '12rpx' }}>
              {dates.slice(0, 7).map((d) => {
                const selected = form.date === d
                const dt = new Date(d + 'T00:00:00')
                const days = ['日', '一', '二', '三', '四', '五', '六']
                return (
                  <View
                    key={d}
                    style={{
                      minWidth: '100rpx',
                      padding: '14rpx 16rpx',
                      borderRadius: '12rpx',
                      border: `2rpx solid ${selected ? C.primary : C.border}`,
                      background: selected ? C.primaryFaint : C.bgDeep,
                      alignItems: 'center',
                      flexShrink: 0,
                    }}
                    onClick={() => setForm((f) => ({ ...f, date: d }))}
                  >
                    <Text style={{ color: selected ? C.primary : C.text2, fontSize: '22rpx', fontWeight: selected ? '700' : '400' }}>
                      {d.slice(5).replace('-', '/')}
                    </Text>
                    <Text style={{ color: selected ? C.primary : C.text3, fontSize: '20rpx', marginTop: '4rpx' }}>
                      周{days[dt.getDay()]}
                    </Text>
                  </View>
                )
              })}
            </View>
          </ScrollView>
        </FormField>

        <FormField label="用餐时间">
          <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
            {['12:00', '13:00', '18:00', '19:00'].map((t) => {
              const selected = form.time === t
              return (
                <View
                  key={t}
                  style={{
                    flex: 1,
                    height: '72rpx',
                    borderRadius: '12rpx',
                    border: `2rpx solid ${selected ? C.primary : C.border}`,
                    background: selected ? C.primaryFaint : C.bgDeep,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                  onClick={() => setForm((f) => ({ ...f, time: t }))}
                >
                  <Text style={{ color: selected ? C.primary : C.text2, fontSize: '26rpx', fontWeight: selected ? '600' : '400' }}>
                    {t}
                  </Text>
                </View>
              )
            })}
          </View>
        </FormField>
      </Section>

      <Section title="餐饮偏好（选填）">
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
                  setForm((f) => ({ ...f, menuPrefs: next }))
                }}
              />
            )
          })}
        </View>
      </Section>

      {/* Recommended packages */}
      <Section title={`人均预算内推荐套餐（${fenToYuanDisplay(form.budgetPerPersonFen)}/人）`}>
        {pkgLoading ? (
          <Text style={{ color: C.text2, fontSize: '26rpx' }}>加载推荐中...</Text>
        ) : packages.length === 0 ? (
          <Text style={{ color: C.text3, fontSize: '26rpx' }}>暂无匹配套餐，可直接提交需求</Text>
        ) : (
          packages.map((pkg) => (
            <View
              key={pkg.packageId}
              style={{
                background: C.bgDeep,
                borderRadius: '12rpx',
                padding: '20rpx',
                marginBottom: '12rpx',
                border: `1rpx solid ${C.border}`,
              }}
            >
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  justifyContent: 'space-between',
                  marginBottom: '8rpx',
                }}
              >
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
                  {pkg.name}
                </Text>
                <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '700' }}>
                  {fenToYuanDisplay(pkg.pricePerPersonFen)}/人
                </Text>
              </View>
              <Text style={{ color: C.text3, fontSize: '24rpx', marginBottom: '8rpx' }}>
                共{pkg.dishCount}道菜
              </Text>
              <Text style={{ color: C.text2, fontSize: '24rpx' }} numberOfLines={2}>
                {pkg.featuredDishes.join(' · ')}
              </Text>
            </View>
          ))
        )}
      </Section>

      <FixedBar>
        <View
          style={{
            background: canSubmit && !submitting ? C.primary : C.disabled,
            borderRadius: '44rpx',
            height: '88rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: canSubmit && !submitting ? 1 : 0.6,
          }}
          onClick={canSubmit && !submitting ? handleSubmit : undefined}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : `提交团餐 · 预估${fenToYuanDisplay(discountedFen)}`}
          </Text>
        </View>
      </FixedBar>
    </ScrollView>
  )
}

// ─── Consumption Records ──────────────────────────────────────────────────────

function RecordsView({ onBack }: { onBack: () => void }) {
  const [orders, setOrders] = useState<CorporateOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  async function loadOrders(p: number, append = false) {
    if (p === 1) setLoading(true)
    else setLoadingMore(true)
    try {
      const data = await txRequest<{ items: CorporateOrder[]; total: number }>(
        '/corporate/orders',
        'GET',
        { page: p, size: 10 },
      )
      if (append) {
        setOrders((prev) => [...prev, ...data.items])
      } else {
        setOrders(data.items)
      }
      setHasMore(data.items.length === 10)
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    loadOrders(1)
  }, [])

  function handleLoadMore() {
    if (loadingMore || !hasMore) return
    const nextPage = page + 1
    setPage(nextPage)
    loadOrders(nextPage, true)
  }

  return (
    <ScrollView
      scrollY
      style={{ flex: 1 }}
      onScrollToLower={handleLoadMore}
    >
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '20rpx 24rpx',
        }}
        onClick={onBack}
      >
        <Text style={{ color: C.primary, fontSize: '28rpx' }}>← 返回</Text>
      </View>
      <View style={{ padding: '0 24rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>消费记录</Text>
      </View>

      {loading ? (
        <View style={{ padding: '80rpx', alignItems: 'center' }}>
          <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
        </View>
      ) : orders.length === 0 ? (
        <View style={{ padding: '80rpx', alignItems: 'center' }}>
          <Text style={{ color: C.text2, fontSize: '28rpx' }}>暂无消费记录</Text>
        </View>
      ) : (
        <View style={{ padding: '0 24rpx' }}>
          {orders.map((order) => {
            const st = STATUS_LABELS[order.status]
            return (
              <View
                key={order.orderId}
                style={{
                  background: C.bgCard,
                  borderRadius: '16rpx',
                  padding: '20rpx 24rpx',
                  marginBottom: '12rpx',
                  border: `1rpx solid ${C.border}`,
                }}
              >
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    marginBottom: '8rpx',
                  }}
                >
                  <Text
                    style={{
                      color: C.text1,
                      fontSize: '28rpx',
                      fontWeight: '600',
                      flex: 1,
                    }}
                    numberOfLines={1}
                  >
                    {order.eventName}
                  </Text>
                  <Text
                    style={{
                      color: st.color,
                      fontSize: '24rpx',
                      fontWeight: '600',
                      marginLeft: '12rpx',
                    }}
                  >
                    {st.label}
                  </Text>
                </View>
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'row',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <Text style={{ color: C.text3, fontSize: '24rpx' }}>
                    {order.date} · {order.headCount}人
                  </Text>
                  <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>
                    {fenToYuanDisplay(order.totalFen)}
                  </Text>
                </View>
                {order.invoiceApplied && (
                  <View
                    style={{
                      marginTop: '8rpx',
                      display: 'flex',
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: '6rpx',
                    }}
                  >
                    <Text style={{ color: C.success, fontSize: '22rpx' }}>✓ 已申请发票</Text>
                  </View>
                )}
              </View>
            )
          })}
          {loadingMore && (
            <View style={{ padding: '24rpx', alignItems: 'center' }}>
              <Text style={{ color: C.text2, fontSize: '24rpx' }}>加载中...</Text>
            </View>
          )}
          {!hasMore && orders.length > 0 && (
            <View style={{ padding: '24rpx', alignItems: 'center' }}>
              <Text style={{ color: C.text3, fontSize: '24rpx' }}>已加载全部记录</Text>
            </View>
          )}
        </View>
      )}
    </ScrollView>
  )
}

// ─── Invoice Application ──────────────────────────────────────────────────────

function InvoiceView({
  account,
  onBack,
}: {
  account: CorporateAccount
  onBack: () => void
}) {
  const [orders, setOrders] = useState<CorporateOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState<InvoiceForm>({
    selectedOrderIds: [],
    invoiceType: 'general',
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    txRequest<{ items: CorporateOrder[] }>('/corporate/orders', 'GET', {
      status: 'completed',
      invoiceApplied: false,
    })
      .then((d) => setOrders(d.items))
      .catch(() => setOrders([]))
      .finally(() => setLoading(false))
  }, [])

  const selectedOrders = orders.filter((o) => form.selectedOrderIds.includes(o.orderId))
  const totalFen = selectedOrders.reduce((s, o) => s + o.totalFen, 0)
  const canSubmit = form.selectedOrderIds.length > 0

  async function handleApply() {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      await txRequest('/corporate/invoices', 'POST', {
        orderIds: form.selectedOrderIds,
        invoiceType: form.invoiceType,
        companyName: account.companyName,
        taxId: account.taxId,
        contactName: account.contactName,
        contactPhone: account.contactPhone,
      })
      Taro.showToast({ title: '发票申请已提交', icon: 'success' })
      onBack()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '申请失败，请重试'
      Taro.showToast({ title: msg, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ScrollView scrollY style={{ flex: 1, paddingBottom: '200rpx' }}>
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '20rpx 24rpx',
        }}
        onClick={onBack}
      >
        <Text style={{ color: C.primary, fontSize: '28rpx' }}>← 返回</Text>
      </View>
      <View style={{ padding: '0 24rpx 16rpx' }}>
        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>申请发票</Text>
      </View>

      {/* Company info (pre-filled) */}
      <Section title="开票信息（自动填入）">
        {[
          { label: '公司名称', value: account.companyName },
          { label: '税号', value: account.taxId },
          { label: '联系人', value: account.contactName },
          { label: '联系电话', value: account.contactPhone },
        ].map(({ label, value }) => (
          <View
            key={label}
            style={{
              display: 'flex',
              flexDirection: 'row',
              paddingVertical: '10rpx',
              borderBottom: `1rpx solid ${C.border}`,
            }}
          >
            <Text style={{ color: C.text3, fontSize: '26rpx', width: '140rpx', flexShrink: 0 }}>
              {label}
            </Text>
            <Text style={{ color: C.text1, fontSize: '26rpx', flex: 1 }}>{value}</Text>
          </View>
        ))}
      </Section>

      {/* Invoice type */}
      <Section title="发票类型">
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          {[
            { value: 'general' as InvoiceType, label: '增值税普票' },
            { value: 'special' as InvoiceType, label: '增值税专票' },
          ].map((t) => {
            const selected = form.invoiceType === t.value
            return (
              <View
                key={t.value}
                style={{
                  flex: 1,
                  height: '80rpx',
                  borderRadius: '12rpx',
                  border: `2rpx solid ${selected ? C.primary : C.border}`,
                  background: selected ? C.primaryFaint : C.bgDeep,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                onClick={() => setForm((f) => ({ ...f, invoiceType: t.value }))}
              >
                <Text
                  style={{
                    color: selected ? C.primary : C.text2,
                    fontSize: '26rpx',
                    fontWeight: selected ? '600' : '400',
                  }}
                >
                  {t.label}
                </Text>
              </View>
            )
          })}
        </View>
      </Section>

      {/* Order selection */}
      <Section title="选择开票订单">
        {loading ? (
          <Text style={{ color: C.text2, fontSize: '26rpx' }}>加载中...</Text>
        ) : orders.length === 0 ? (
          <Text style={{ color: C.text3, fontSize: '26rpx' }}>暂无可开票订单</Text>
        ) : (
          orders.map((order) => {
            const checked = form.selectedOrderIds.includes(order.orderId)
            return (
              <View
                key={order.orderId}
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  padding: '16rpx 0',
                  borderBottom: `1rpx solid ${C.border}`,
                }}
                onClick={() => {
                  const next = checked
                    ? form.selectedOrderIds.filter((id) => id !== order.orderId)
                    : [...form.selectedOrderIds, order.orderId]
                  setForm((f) => ({ ...f, selectedOrderIds: next }))
                }}
              >
                <View
                  style={{
                    width: '40rpx',
                    height: '40rpx',
                    borderRadius: '8rpx',
                    border: `2rpx solid ${checked ? C.primary : C.text3}`,
                    background: checked ? C.primary : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginRight: '20rpx',
                    flexShrink: 0,
                  }}
                >
                  {checked && (
                    <Text style={{ color: C.white, fontSize: '24rpx', fontWeight: '700' }}>✓</Text>
                  )}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '500' }} numberOfLines={1}>
                    {order.eventName}
                  </Text>
                  <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx' }}>
                    {order.date} · {order.headCount}人
                  </Text>
                </View>
                <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600', marginLeft: '12rpx' }}>
                  {fenToYuanDisplay(order.totalFen)}
                </Text>
              </View>
            )
          })
        )}

        {selectedOrders.length > 0 && (
          <View
            style={{
              background: C.primaryFaint,
              borderRadius: '12rpx',
              padding: '16rpx',
              marginTop: '12rpx',
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
            }}
          >
            <Text style={{ color: C.primary, fontSize: '26rpx' }}>
              已选 {selectedOrders.length} 单
            </Text>
            <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '700' }}>
              合计 {fenToYuanDisplay(totalFen)}
            </Text>
          </View>
        )}
      </Section>

      <FixedBar>
        <View
          style={{
            background: canSubmit && !submitting ? C.primary : C.disabled,
            borderRadius: '44rpx',
            height: '88rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            opacity: canSubmit && !submitting ? 1 : 0.6,
          }}
          onClick={canSubmit && !submitting ? handleApply : undefined}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : `申请开票${totalFen > 0 ? ` · ${fenToYuanDisplay(totalFen)}` : ''}`}
          </Text>
        </View>
      </FixedBar>
    </ScrollView>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CorporatePage() {
  const [account, setAccount] = useState<CorporateAccount | null>(null)
  const [accountLoading, setAccountLoading] = useState(true)
  const [view, setView] = useState<CorporateView>('main')

  const { isLoggedIn } = useUserStore()

  useEffect(() => {
    if (!isLoggedIn) {
      setAccountLoading(false)
      return
    }
    txRequest<CorporateAccount | null>('/corporate/accounts/me')
      .then((data) => setAccount(data))
      .catch(() => setAccount(null))
      .finally(() => setAccountLoading(false))
  }, [isLoggedIn])

  if (!isLoggedIn) {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx', marginBottom: '24rpx' }}>🏢</Text>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '700', marginBottom: '12rpx' }}>
          企业团餐
        </Text>
        <Text style={{ color: C.text2, fontSize: '26rpx', textAlign: 'center', lineHeight: '1.6' }}>
          请先登录后使用企业团餐服务
        </Text>
      </View>
    )
  }

  if (accountLoading) {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.text2, fontSize: '28rpx' }}>加载中...</Text>
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
      {/* Page title — only show on main */}
      {view === 'main' && (
        <View style={{ padding: '24rpx 32rpx 0' }}>
          <Text style={{ color: C.text1, fontSize: '40rpx', fontWeight: '800' }}>企业团餐</Text>
          <Text style={{ color: C.text2, fontSize: '26rpx', marginTop: '8rpx' }}>
            专属企业用餐解决方案
          </Text>
        </View>
      )}

      {/* Unbound state */}
      {!account && view === 'main' && (
        <UnboundView onBound={(acc) => setAccount(acc)} />
      )}

      {/* Bound — main */}
      {account && view === 'main' && (
        <ScrollView scrollY style={{ flex: 1 }}>
          {/* Account status card */}
          <AccountCard account={account} />

          {/* Quick actions */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              gap: '16rpx',
              margin: '0 24rpx 16rpx',
            }}
          >
            {[
              { icon: '🍽', label: '发起团餐', view: 'order' as CorporateView },
              { icon: '📋', label: '消费记录', view: 'records' as CorporateView },
              { icon: '🧾', label: '申请发票', view: 'invoice' as CorporateView },
            ].map((action) => (
              <View
                key={action.label}
                style={{
                  flex: 1,
                  background: C.bgCard,
                  borderRadius: '16rpx',
                  padding: '24rpx 16rpx',
                  border: `1rpx solid ${C.border}`,
                  alignItems: 'center',
                  gap: '8rpx',
                }}
                onClick={() => setView(action.view)}
              >
                <Text style={{ fontSize: '40rpx', lineHeight: '1', marginBottom: '8rpx' }}>
                  {action.icon}
                </Text>
                <Text style={{ color: C.text1, fontSize: '24rpx', fontWeight: '600', textAlign: 'center' }}>
                  {action.label}
                </Text>
              </View>
            ))}
          </View>

          <View style={{ height: '40rpx' }} />
        </ScrollView>
      )}

      {/* Sub-views */}
      {account && view === 'order' && (
        <CorporateOrderView
          account={account}
          onBack={() => setView('main')}
          onSuccess={() => setView('main')}
        />
      )}
      {view === 'records' && (
        <RecordsView onBack={() => setView('main')} />
      )}
      {account && view === 'invoice' && (
        <InvoiceView account={account} onBack={() => setView('main')} />
      )}
    </View>
  )
}
