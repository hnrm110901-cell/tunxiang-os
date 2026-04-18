/**
 * order-detail/invoice/index.tsx — 电子发票申请页
 *
 * URL params: ?orderId=xxx
 *
 * Features:
 *  - Invoice type selector: 个人 / 企业
 *  - 个人: 邮箱 only
 *  - 企业: 公司名称 / 税号 / 邮箱 (optional: 开户行 / 账号 / 地址 / 电话)
 *  - Order amount display
 *  - Save as template toggle
 *  - History: 已开发票列表
 *  - Submit → POST /api/v1/orders/{id}/invoice
 *  - Success state with download link
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { getOrder, Order } from '../../../api/trade'
import { txRequest } from '../../../utils/request'
import { fenToYuanDisplay } from '../../../utils/format'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B35',
  primaryDim: 'rgba(255,107,53,0.15)',
  bgDeep:     '#0B1A20',
  bgCard:     '#132029',
  bgHover:    '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  red:        '#E53935',
  success:    '#4CAF50',
  successDim: 'rgba(76,175,80,0.15)',
  white:      '#fff',
  disabled:   '#2A4050',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type InvoiceType = 'personal' | 'enterprise'

interface InvoiceTemplate {
  id: string
  type: InvoiceType
  companyName?: string
  taxId?: string
  email: string
  bankName?: string
  bankAccount?: string
  companyAddress?: string
  companyPhone?: string
}

interface InvoiceSubmitResult {
  invoiceId: string
  invoiceNo: string
  status: 'issuing' | 'issued'
  downloadUrl?: string
}

const STORAGE_TEMPLATE_KEY = 'tx_invoice_template'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

function isValidTaxId(taxId: string): boolean {
  // China tax ID: 15 or 18-20 alphanumeric characters
  return /^[A-Za-z0-9]{15,20}$/.test(taxId)
}

function loadTemplate(): InvoiceTemplate | null {
  try {
    const saved = Taro.getStorageSync<InvoiceTemplate>(STORAGE_TEMPLATE_KEY)
    return saved || null
  } catch {
    return null
  }
}

function saveTemplate(template: InvoiceTemplate): void {
  try {
    Taro.setStorageSync(STORAGE_TEMPLATE_KEY, template)
  } catch {
    // ignore
  }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionCard({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        background:   C.bgCard,
        borderRadius: '20rpx',
        marginBottom: '20rpx',
        overflow:     'hidden',
      }}
    >
      {title && (
        <View style={{ padding: '24rpx 32rpx 16rpx', borderBottom: `1rpx solid ${C.border}` }}>
          <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '700' }}>{title}</Text>
        </View>
      )}
      {children}
    </View>
  )
}

function FormField({
  label,
  required,
  value,
  placeholder,
  onInput,
  type,
  maxlength,
  error,
}: {
  label: string
  required?: boolean
  value: string
  placeholder: string
  onInput: (val: string) => void
  type?: 'text' | 'number'
  maxlength?: number
  error?: string
}) {
  return (
    <View style={{ padding: '16rpx 32rpx' }}>
      <Text style={{ color: C.text2, fontSize: '24rpx', marginBottom: '8rpx', display: 'block' }}>
        {label}{required ? ' *' : ''}
      </Text>
      <Input
        value={value}
        placeholder={placeholder}
        placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
        type={type || 'text'}
        maxlength={maxlength}
        style={{
          background:   C.bgDeep,
          color:        C.text1,
          fontSize:     '28rpx',
          borderRadius: '12rpx',
          padding:      '20rpx 24rpx',
          border:       `1rpx solid ${error ? C.red : C.border}`,
          height:       '88rpx',
          boxSizing:    'border-box',
        }}
        onInput={(e) => onInput(e.detail.value)}
      />
      {error && (
        <Text style={{ color: C.red, fontSize: '22rpx', marginTop: '6rpx', display: 'block' }}>
          {error}
        </Text>
      )}
    </View>
  )
}

// ─── Spinner ──────────────────────────────────────────────────────────────────

function Spinner() {
  const [angle, setAngle] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setAngle((a) => (a + 30) % 360), 80)
    return () => clearInterval(id)
  }, [])
  return (
    <View
      style={{
        width: '48rpx', height: '48rpx', borderRadius: '50%',
        border: `4rpx solid ${C.border}`, borderTop: `4rpx solid ${C.primary}`,
        transform: `rotate(${angle}deg)`,
      }}
    />
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function InvoicePage() {
  const { orderId } = (() => {
    const params = Taro.getCurrentInstance().router?.params ?? {}
    return { orderId: (params.orderId as string | undefined) ?? '' }
  })()

  // ── Remote data ────────────────────────────────────────────────────────────
  const [order,   setOrder]   = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  // ── Form state ─────────────────────────────────────────────────────────────
  const [invoiceType,    setInvoiceType]    = useState<InvoiceType>('personal')
  const [email,          setEmail]          = useState('')
  const [companyName,    setCompanyName]    = useState('')
  const [taxId,          setTaxId]          = useState('')
  const [bankName,       setBankName]       = useState('')
  const [bankAccount,    setBankAccount]    = useState('')
  const [companyAddress, setCompanyAddress] = useState('')
  const [companyPhone,   setCompanyPhone]   = useState('')
  const [saveAsTemplate, setSaveAsTemplate] = useState(true)
  const [submitting,     setSubmitting]     = useState(false)

  // ── Validation errors ──────────────────────────────────────────────────────
  const [errors, setErrors] = useState<Record<string, string>>({})

  // ── Success state ──────────────────────────────────────────────────────────
  const [result, setResult] = useState<InvoiceSubmitResult | null>(null)

  // ── Load order + template ──────────────────────────────────────────────────

  const fetchOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setError('')
    try {
      const data = await getOrder(orderId)
      setOrder(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    void fetchOrder()

    // Load saved template
    const tmpl = loadTemplate()
    if (tmpl) {
      setInvoiceType(tmpl.type)
      setEmail(tmpl.email)
      if (tmpl.companyName)    setCompanyName(tmpl.companyName)
      if (tmpl.taxId)          setTaxId(tmpl.taxId)
      if (tmpl.bankName)       setBankName(tmpl.bankName)
      if (tmpl.bankAccount)    setBankAccount(tmpl.bankAccount)
      if (tmpl.companyAddress) setCompanyAddress(tmpl.companyAddress)
      if (tmpl.companyPhone)   setCompanyPhone(tmpl.companyPhone)
    }
  }, [fetchOrder])

  // ── Validation ─────────────────────────────────────────────────────────────

  function validate(): boolean {
    const errs: Record<string, string> = {}

    if (!email.trim()) {
      errs.email = '请输入邮箱地址'
    } else if (!isValidEmail(email.trim())) {
      errs.email = '邮箱格式不正确'
    }

    if (invoiceType === 'enterprise') {
      if (!companyName.trim()) errs.companyName = '请输入公司名称'
      if (!taxId.trim()) {
        errs.taxId = '请输入纳税人识别号'
      } else if (!isValidTaxId(taxId.trim())) {
        errs.taxId = '纳税人识别号格式不正确'
      }
    }

    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  // ── Submit ─────────────────────────────────────────────────────────────────

  async function handleSubmit() {
    if (!validate() || !orderId) return

    setSubmitting(true)
    try {
      const payload: Record<string, unknown> = {
        type:  invoiceType,
        email: email.trim(),
      }

      if (invoiceType === 'enterprise') {
        payload.companyName    = companyName.trim()
        payload.taxId          = taxId.trim()
        if (bankName.trim())       payload.bankName       = bankName.trim()
        if (bankAccount.trim())    payload.bankAccount    = bankAccount.trim()
        if (companyAddress.trim()) payload.companyAddress = companyAddress.trim()
        if (companyPhone.trim())   payload.companyPhone   = companyPhone.trim()
      }

      const res = await txRequest<InvoiceSubmitResult>(
        `/api/v1/orders/${encodeURIComponent(orderId)}/invoice`,
        'POST',
        payload,
      )

      // Save template if requested
      if (saveAsTemplate) {
        saveTemplate({
          id:             `tmpl_${Date.now()}`,
          type:           invoiceType,
          email:          email.trim(),
          companyName:    invoiceType === 'enterprise' ? companyName.trim() : undefined,
          taxId:          invoiceType === 'enterprise' ? taxId.trim() : undefined,
          bankName:       bankName.trim() || undefined,
          bankAccount:    bankAccount.trim() || undefined,
          companyAddress: companyAddress.trim() || undefined,
          companyPhone:   companyPhone.trim() || undefined,
        })
      }

      setResult(res)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '提交失败，请重试'
      Taro.showToast({ title: msg, icon: 'none' })
    } finally {
      setSubmitting(false)
    }
  }

  // ── Loading / error states ─────────────────────────────────────────────────

  if (loading) {
    return (
      <View
        style={{
          minHeight: '100vh', background: C.bgDeep,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: '24rpx',
        }}
      >
        <Spinner />
        <Text style={{ color: C.text2, fontSize: '26rpx' }}>加载订单中...</Text>
      </View>
    )
  }

  if (error || !order) {
    return (
      <View
        style={{
          minHeight: '100vh', background: C.bgDeep,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: '24rpx', padding: '48rpx',
        }}
      >
        <Text style={{ fontSize: '64rpx' }}>😕</Text>
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>
          {error || '订单不存在'}
        </Text>
        <View
          onClick={() => void fetchOrder()}
          style={{ background: C.primary, borderRadius: '40rpx', padding: '16rpx 48rpx' }}
        >
          <Text style={{ color: C.white, fontSize: '28rpx' }}>重试</Text>
        </View>
      </View>
    )
  }

  // ── Success state ──────────────────────────────────────────────────────────

  if (result) {
    return (
      <View
        style={{
          minHeight: '100vh', background: C.bgDeep,
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', padding: '48rpx', gap: '32rpx',
        }}
      >
        <View
          style={{
            width: '160rpx', height: '160rpx', borderRadius: '80rpx',
            background: C.successDim, border: `2rpx solid ${C.success}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Text style={{ color: C.success, fontSize: '80rpx', lineHeight: '1' }}>✓</Text>
        </View>

        <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
          发票申请成功
        </Text>

        <View
          style={{
            background: C.bgCard, borderRadius: '20rpx',
            padding: '24rpx 32rpx', width: '100%',
          }}
        >
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '16rpx' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>发票编号</Text>
            <Text style={{ color: C.text1, fontSize: '26rpx', fontWeight: '600' }}>
              #{result.invoiceNo}
            </Text>
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '16rpx' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>开票金额</Text>
            <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
              {fenToYuanDisplay(order.payableFen)}
            </Text>
          </View>
          <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>接收邮箱</Text>
            <Text style={{ color: C.text1, fontSize: '26rpx' }}>{email}</Text>
          </View>
        </View>

        <Text style={{ color: C.text2, fontSize: '24rpx', textAlign: 'center', lineHeight: '36rpx' }}>
          {result.status === 'issued'
            ? '电子发票已发送至您的邮箱，请查收'
            : '电子发票正在开具中，预计10分钟内发送至邮箱'}
        </Text>

        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx', width: '100%', marginTop: '16rpx' }}>
          <View
            style={{
              flex: 1, height: '88rpx', border: `2rpx solid ${C.border}`,
              borderRadius: '44rpx', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            onClick={() => Taro.navigateBack({ delta: 1 })}
          >
            <Text style={{ color: C.text1, fontSize: '28rpx' }}>返回订单</Text>
          </View>
          {result.downloadUrl && (
            <View
              style={{
                flex: 1, height: '88rpx', background: C.primary,
                borderRadius: '44rpx', display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
              onClick={() => {
                Taro.setClipboardData({ data: result.downloadUrl! })
                  .then(() => Taro.showToast({ title: '下载链接已复制', icon: 'success' }))
                  .catch(() => {})
              }}
            >
              <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '600' }}>复制下载链接</Text>
            </View>
          )}
        </View>
      </View>
    )
  }

  // ── Main form ──────────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '24rpx 24rpx 200rpx' }}>

          {/* ── Order info ──────────────────────────────────────────────────── */}
          <SectionCard title="开票订单">
            <View style={{ padding: '20rpx 32rpx' }}>
              <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '12rpx' }}>
                <Text style={{ color: C.text2, fontSize: '26rpx' }}>订单号</Text>
                <Text style={{ color: C.text1, fontSize: '26rpx' }}>{order.orderNo}</Text>
              </View>
              <View style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', marginBottom: '12rpx' }}>
                <Text style={{ color: C.text2, fontSize: '26rpx' }}>门店名称</Text>
                <Text style={{ color: C.text1, fontSize: '26rpx' }}>{order.storeName}</Text>
              </View>
              <View
                style={{
                  display: 'flex', flexDirection: 'row', justifyContent: 'space-between',
                  paddingTop: '12rpx', borderTop: `1rpx solid ${C.border}`,
                }}
              >
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>开票金额</Text>
                <Text style={{ color: C.primary, fontSize: '36rpx', fontWeight: '700' }}>
                  {fenToYuanDisplay(order.payableFen)}
                </Text>
              </View>
            </View>
          </SectionCard>

          {/* ── Invoice type ────────────────────────────────────────────────── */}
          <SectionCard title="发票类型">
            <View style={{ display: 'flex', flexDirection: 'row', padding: '20rpx 32rpx', gap: '16rpx' }}>
              {(['personal', 'enterprise'] as InvoiceType[]).map((type) => {
                const selected = invoiceType === type
                const label = type === 'personal' ? '个人' : '企业'
                return (
                  <View
                    key={type}
                    style={{
                      flex:           1,
                      height:         '88rpx',
                      borderRadius:   '16rpx',
                      border:         `2rpx solid ${selected ? C.primary : C.border}`,
                      background:     selected ? C.primaryDim : C.bgDeep,
                      display:        'flex',
                      alignItems:     'center',
                      justifyContent: 'center',
                    }}
                    onClick={() => { setInvoiceType(type); setErrors({}) }}
                  >
                    <Text
                      style={{
                        color:      selected ? C.primary : C.text2,
                        fontSize:   '28rpx',
                        fontWeight: selected ? '600' : '400',
                      }}
                    >
                      {label}
                    </Text>
                  </View>
                )
              })}
            </View>
          </SectionCard>

          {/* ── Invoice form ────────────────────────────────────────────────── */}
          <SectionCard title="发票信息">
            {invoiceType === 'enterprise' && (
              <>
                <FormField
                  label="公司名称"
                  required
                  value={companyName}
                  placeholder="请输入公司全称"
                  onInput={setCompanyName}
                  error={errors.companyName}
                />
                <FormField
                  label="纳税人识别号"
                  required
                  value={taxId}
                  placeholder="15-20位数字/字母"
                  onInput={setTaxId}
                  maxlength={20}
                  error={errors.taxId}
                />
              </>
            )}

            <FormField
              label="接收邮箱"
              required
              value={email}
              placeholder="example@email.com"
              onInput={setEmail}
              error={errors.email}
            />

            {invoiceType === 'enterprise' && (
              <>
                {/* Optional enterprise fields */}
                <View style={{ padding: '16rpx 32rpx 8rpx' }}>
                  <Text style={{ color: C.text3, fontSize: '22rpx' }}>以下为选填信息</Text>
                </View>
                <FormField
                  label="开户银行"
                  value={bankName}
                  placeholder="选填"
                  onInput={setBankName}
                />
                <FormField
                  label="银行账号"
                  value={bankAccount}
                  placeholder="选填"
                  onInput={setBankAccount}
                />
                <FormField
                  label="公司地址"
                  value={companyAddress}
                  placeholder="选填"
                  onInput={setCompanyAddress}
                />
                <FormField
                  label="公司电话"
                  value={companyPhone}
                  placeholder="选填"
                  onInput={setCompanyPhone}
                />
              </>
            )}

            {/* Padding at bottom of form */}
            <View style={{ height: '16rpx' }} />
          </SectionCard>

          {/* ── Save template toggle ─────────────────────────────────────────── */}
          <SectionCard>
            <View
              style={{
                display: 'flex', flexDirection: 'row', alignItems: 'center',
                padding: '24rpx 32rpx',
              }}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '500', display: 'block' }}>
                  保存为模板
                </Text>
                <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                  下次开票自动填充
                </Text>
              </View>
              <View
                onClick={() => setSaveAsTemplate((v) => !v)}
                style={{
                  width:        '96rpx',
                  height:       '52rpx',
                  borderRadius: '26rpx',
                  background:   saveAsTemplate ? C.primary : C.disabled,
                  position:     'relative',
                  transition:   'background 0.2s',
                  flexShrink:   0,
                }}
              >
                <View
                  style={{
                    position:     'absolute',
                    top:          '6rpx',
                    left:         saveAsTemplate ? '48rpx' : '6rpx',
                    width:        '40rpx',
                    height:       '40rpx',
                    borderRadius: '50%',
                    background:   C.white,
                    transition:   'left 0.2s',
                    boxShadow:    '0 1rpx 4rpx rgba(0,0,0,0.3)',
                  }}
                />
              </View>
            </View>
          </SectionCard>

          {/* ── Notice ──────────────────────────────────────────────────────── */}
          <View
            style={{
              background: C.bgCard, borderRadius: '16rpx',
              padding: '20rpx 24rpx',
            }}
          >
            <Text style={{ color: C.text2, fontSize: '24rpx', fontWeight: '600', marginBottom: '8rpx', display: 'block' }}>
              开票须知
            </Text>
            <Text style={{ color: C.text3, fontSize: '22rpx', lineHeight: '34rpx' }}>
              1. 电子发票与纸质发票具有同等法律效力{'\n'}
              2. 发票将在提交后10分钟内发送至邮箱{'\n'}
              3. 每笔订单仅可开具一次发票{'\n'}
              4. 发票内容为"餐饮服务"{'\n'}
              5. 如需修改信息，请联系客服 400-000-0000
            </Text>
          </View>

        </View>
      </ScrollView>

      {/* ── Sticky submit button ───────────────────────────────────────────── */}
      <View
        style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          background: C.bgCard, borderTop: `1rpx solid ${C.border}`,
          padding: '20rpx 32rpx', paddingBottom: 'calc(20rpx + env(safe-area-inset-bottom))',
          backdropFilter: 'blur(12px)',
        }}
      >
        <View
          onClick={submitting ? undefined : handleSubmit}
          style={{
            height:         '88rpx',
            background:     submitting ? C.disabled : C.primary,
            borderRadius:   '44rpx',
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'center',
            opacity:        submitting ? 0.7 : 1,
          }}
        >
          <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
            {submitting ? '提交中...' : '申请开票'}
          </Text>
        </View>
      </View>
    </View>
  )
}
