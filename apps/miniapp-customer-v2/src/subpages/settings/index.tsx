/**
 * settings/index.tsx — 设置页
 *
 * Sections:
 *  1. 账号设置: 头像 / 昵称 / 手机号 / 微信授权
 *  2. 消息通知: 4 switches + Taro.requestSubscribeMessage on enable
 *  3. 收货地址: list (default badge) + add/edit modal + set default API
 *  4. 隐私与安全: 数据授权 / 清缓存 / 注销账号
 *  5. 关于屯象: version / 用户协议 / 隐私政策 / 联系我们
 */

import React, { useState, useEffect } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, Input, Switch, ScrollView } from '@tarojs/components'
import { useUserStore } from '../../store/useUserStore'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  white: '#fff',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────
interface Address {
  id: string
  name: string
  phone: string
  address: string
  isDefault: boolean
}

interface NotifySettings {
  orderStatus: boolean
  marketing: boolean
  queue: boolean
  system: boolean
}

// Template IDs for Taro.requestSubscribeMessage (replace with real IDs)
const TEMPLATE_IDS: Record<keyof NotifySettings, string> = {
  orderStatus: 'ORDER_STATUS_TEMPLATE_ID',
  marketing: 'MARKETING_TEMPLATE_ID',
  queue: 'QUEUE_TEMPLATE_ID',
  system: 'SYSTEM_TEMPLATE_ID',
}

const APP_VERSION = '2.3.1'

// ─── Sub-components ──────────────────────────────────────────────────────────

function SectionTitle({ title }: { title: string }) {
  return (
    <Text
      style={{
        fontSize: '24rpx',
        color: C.text3,
        display: 'block',
        marginTop: '48rpx',
        marginBottom: '16rpx',
        paddingLeft: '8rpx',
        letterSpacing: '2rpx',
        textTransform: 'uppercase',
      }}
    >
      {title}
    </Text>
  )
}

function SettingRow({
  label,
  value,
  arrow = true,
  rightSlot,
  onTap,
  danger = false,
}: {
  label: string
  value?: string
  arrow?: boolean
  rightSlot?: React.ReactNode
  onTap?: () => void
  danger?: boolean
}) {
  return (
    <View
      onClick={onTap}
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '36rpx 32rpx',
        background: C.bgCard,
        borderBottom: `1rpx solid ${C.border}`,
        cursor: onTap ? 'pointer' : 'default',
      }}
    >
      <Text style={{ fontSize: '30rpx', color: danger ? C.red : C.text1 }}>{label}</Text>
      <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '16rpx' }}>
        {value && <Text style={{ fontSize: '28rpx', color: C.text3 }}>{value}</Text>}
        {rightSlot}
        {arrow && <Text style={{ fontSize: '28rpx', color: C.text3 }}>›</Text>}
      </View>
    </View>
  )
}

function Card({ children, style = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        overflow: 'hidden',
        border: `1rpx solid ${C.border}`,
        ...style,
      }}
    >
      {children}
    </View>
  )
}

// ─── Address Form Modal ───────────────────────────────────────────────────────
interface AddressFormModalProps {
  address?: Address | null
  onSave: (data: Omit<Address, 'id' | 'isDefault'>) => Promise<void>
  onClose: () => void
}

function AddressFormModal({ address, onSave, onClose }: AddressFormModalProps) {
  const [name, setName] = useState(address?.name || '')
  const [phone, setPhone] = useState(address?.phone || '')
  const [addr, setAddr] = useState(address?.address || '')
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    if (!name.trim() || !phone.trim() || !addr.trim()) {
      Taro.showToast({ title: '请填写完整信息', icon: 'none' })
      return
    }
    setSaving(true)
    try {
      await onSave({ name: name.trim(), phone: phone.trim(), address: addr.trim() })
      onClose()
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'error' })
    } finally {
      setSaving(false)
    }
  }

  const inputStyle = {
    fontSize: '30rpx',
    color: C.text1,
    padding: '24rpx 0',
    borderBottom: `1rpx solid ${C.border}`,
    width: '100%',
  }

  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'flex-end',
      }}
      onClick={onClose}
    >
      <View
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          background: C.bgCard,
          borderRadius: '32rpx 32rpx 0 0',
          padding: '40rpx 40rpx calc(40rpx + env(safe-area-inset-bottom))',
        }}
      >
        <View
          style={{
            width: '80rpx',
            height: '8rpx',
            background: C.border,
            borderRadius: '4rpx',
            margin: '0 auto 32rpx',
          }}
        />
        <Text style={{ fontSize: '34rpx', fontWeight: '700', color: C.text1, display: 'block', marginBottom: '32rpx' }}>
          {address ? '编辑地址' : '新增地址'}
        </Text>

        <Input
          value={name}
          placeholder="姓名"
          placeholderStyle={`color: ${C.text3}; font-size: 30rpx;`}
          style={inputStyle}
          onInput={(e) => setName(e.detail.value)}
        />
        <Input
          value={phone}
          placeholder="手机号"
          placeholderStyle={`color: ${C.text3}; font-size: 30rpx;`}
          type="number"
          maxlength={11}
          style={{ ...inputStyle, marginTop: '8rpx' }}
          onInput={(e) => setPhone(e.detail.value)}
        />
        <Input
          value={addr}
          placeholder="详细地址"
          placeholderStyle={`color: ${C.text3}; font-size: 30rpx;`}
          style={{ ...inputStyle, marginTop: '8rpx', marginBottom: '40rpx' }}
          onInput={(e) => setAddr(e.detail.value)}
        />

        <View
          onClick={saving ? undefined : handleSave}
          style={{
            height: '96rpx',
            borderRadius: '48rpx',
            background: saving ? C.text3 : C.primary,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          <Text style={{ fontSize: '34rpx', color: C.white, fontWeight: '700' }}>
            {saving ? '保存中...' : '保存'}
          </Text>
        </View>
      </View>
    </View>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { nickname, avatarUrl, phone, isLoggedIn, logout } = useUserStore()

  // Notifications
  const [notify, setNotify] = useState<NotifySettings>({
    orderStatus: true,
    marketing: false,
    queue: true,
    system: true,
  })

  // Addresses
  const [addresses, setAddresses] = useState<Address[]>([])
  const [loadingAddresses, setLoadingAddresses] = useState(false)
  const [showAddressForm, setShowAddressForm] = useState(false)
  const [editingAddress, setEditingAddress] = useState<Address | null>(null)

  // Section expanded
  const [openSection, setOpenSection] = useState<string | null>(null)

  useEffect(() => {
    if (openSection === 'address') fetchAddresses()
  }, [openSection])

  async function fetchAddresses() {
    setLoadingAddresses(true)
    try {
      const res = await txRequest<{ items: Address[] }>('/api/v1/members/me/addresses')
      setAddresses(res.items || [])
    } catch {
      setAddresses([])
    } finally {
      setLoadingAddresses(false)
    }
  }

  async function handleNotifyToggle(key: keyof NotifySettings, val: boolean) {
    if (val) {
      try {
        await Taro.requestSubscribeMessage({ tmplIds: [TEMPLATE_IDS[key]] })
      } catch {
        // user denied – still update local UI
      }
    }
    setNotify((prev) => ({ ...prev, [key]: val }))
  }

  async function handleSaveAddress(data: Omit<Address, 'id' | 'isDefault'>) {
    if (editingAddress) {
      await txRequest(`/api/v1/members/me/addresses/${editingAddress.id}`, 'PUT', data as any)
    } else {
      await txRequest('/api/v1/members/me/addresses', 'POST', data as any)
    }
    await fetchAddresses()
    setEditingAddress(null)
  }

  async function handleSetDefault(id: string) {
    try {
      await txRequest(`/api/v1/members/me/addresses/${id}/default`, 'PUT')
      await fetchAddresses()
    } catch {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  async function handleDeleteAddress(id: string) {
    const res = await Taro.showModal({ title: '确认删除', content: '删除后无法恢复', confirmText: '删除', confirmColor: C.red })
    if (!res.confirm) return
    try {
      await txRequest(`/api/v1/members/me/addresses/${id}`, 'DELETE')
      await fetchAddresses()
    } catch {
      Taro.showToast({ title: '删除失败', icon: 'error' })
    }
  }

  async function handleClearCache() {
    const res = await Taro.showModal({ title: '清除缓存', content: '将清除所有本地缓存数据（不影响账号信息）' })
    if (!res.confirm) return
    try {
      await Taro.clearStorage()
      Taro.showToast({ title: '缓存已清除', icon: 'success' })
    } catch {
      Taro.showToast({ title: '清除失败', icon: 'error' })
    }
  }

  async function handleLogout() {
    const res = await Taro.showModal({
      title: '注销账号',
      content: '注销后账号数据将被永久删除，确认继续？',
      confirmText: '确认注销',
      confirmColor: C.red,
    })
    if (!res.confirm) return
    try {
      await txRequest('/api/v1/members/me', 'DELETE')
      logout()
      Taro.reLaunch({ url: '/pages/login/index' })
    } catch {
      Taro.showToast({ title: '操作失败', icon: 'error' })
    }
  }

  function toggle(section: string) {
    setOpenSection((prev) => (prev === section ? null : section))
  }

  function navigateTo(path: string) {
    Taro.navigateTo({ url: path })
  }

  const notifyLabels: Record<keyof NotifySettings, string> = {
    orderStatus: '订单状态通知',
    marketing: '营销活动推送',
    queue: '叫号提醒',
    system: '系统公告',
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep }}>
      <ScrollView scrollY>
        <View style={{ padding: '0 0 calc(60rpx + env(safe-area-inset-bottom))' }}>

          {/* ══ 1. 账号设置 ══ */}
          <SectionTitle title="账号设置" />
          <Card>
            {/* Avatar */}
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '36rpx 32rpx',
                borderBottom: `1rpx solid ${C.border}`,
                cursor: 'pointer',
              }}
              onClick={() =>
                Taro.chooseImage({ count: 1, sizeType: ['compressed'], sourceType: ['album', 'camera'] })
              }
            >
              <Text style={{ fontSize: '30rpx', color: C.text1 }}>头像</Text>
              <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '16rpx' }}>
                <Image
                  src={avatarUrl || '/images/default-avatar.png'}
                  style={{ width: '80rpx', height: '80rpx', borderRadius: '50%', background: C.bgHover }}
                  mode="aspectFill"
                />
                <Text style={{ fontSize: '28rpx', color: C.text3 }}>›</Text>
              </View>
            </View>

            <SettingRow label="昵称" value={nickname || '未设置'} onTap={() => navigateTo('/subpages/settings/nickname/index')} />
            <SettingRow label="手机号" value={phone ? `${phone.slice(0, 3)}****${phone.slice(-4)}` : '未绑定'} onTap={() => navigateTo('/subpages/settings/phone/index')} />
            <SettingRow
              label="微信授权"
              value="已授权"
              arrow={false}
              rightSlot={
                <View
                  style={{
                    padding: '6rpx 20rpx',
                    background: 'rgba(76,175,80,0.12)',
                    borderRadius: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '22rpx', color: '#4CAF50', fontWeight: '600' }}>已授权</Text>
                </View>
              }
            />
          </Card>

          {/* ══ 2. 消息通知 ══ */}
          <SectionTitle title="消息通知" />
          <Card>
            {(Object.keys(notifyLabels) as Array<keyof NotifySettings>).map((key, idx, arr) => (
              <View
                key={key}
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '36rpx 32rpx',
                  borderBottom: idx < arr.length - 1 ? `1rpx solid ${C.border}` : 'none',
                }}
              >
                <Text style={{ fontSize: '30rpx', color: C.text1 }}>{notifyLabels[key]}</Text>
                <Switch
                  checked={notify[key]}
                  color={C.primary}
                  onChange={(e) => handleNotifyToggle(key, e.detail.value)}
                />
              </View>
            ))}
          </Card>

          {/* ══ 3. 收货地址 ══ */}
          <SectionTitle title="收货地址" />
          <Card>
            <View
              onClick={() => toggle('address')}
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '36rpx 32rpx',
                cursor: 'pointer',
              }}
            >
              <Text style={{ fontSize: '30rpx', color: C.text1 }}>管理收货地址</Text>
              <Text style={{ fontSize: '28rpx', color: C.text3 }}>
                {openSection === 'address' ? '∧' : '›'}
              </Text>
            </View>

            {openSection === 'address' && (
              <View style={{ borderTop: `1rpx solid ${C.border}` }}>
                {loadingAddresses && (
                  <View style={{ padding: '32rpx', textAlign: 'center' }}>
                    <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中...</Text>
                  </View>
                )}

                {!loadingAddresses && addresses.map((addr) => (
                  <View
                    key={addr.id}
                    style={{
                      padding: '28rpx 32rpx',
                      borderBottom: `1rpx solid ${C.border}`,
                    }}
                  >
                    <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '16rpx', marginBottom: '8rpx' }}>
                      <Text style={{ fontSize: '30rpx', color: C.text1, fontWeight: '600' }}>{addr.name}</Text>
                      <Text style={{ fontSize: '28rpx', color: C.text2 }}>{addr.phone}</Text>
                      {addr.isDefault && (
                        <View
                          style={{
                            padding: '4rpx 14rpx',
                            background: 'rgba(255,107,53,0.12)',
                            borderRadius: '8rpx',
                          }}
                        >
                          <Text style={{ fontSize: '22rpx', color: C.primary, fontWeight: '600' }}>默认</Text>
                        </View>
                      )}
                    </View>
                    <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginBottom: '16rpx' }}>
                      {addr.address}
                    </Text>
                    <View style={{ display: 'flex', flexDirection: 'row', gap: '24rpx' }}>
                      <Text
                        onClick={() => { setEditingAddress(addr); setShowAddressForm(true) }}
                        style={{ fontSize: '26rpx', color: C.primary, cursor: 'pointer' }}
                      >
                        编辑
                      </Text>
                      {!addr.isDefault && (
                        <Text
                          onClick={() => handleSetDefault(addr.id)}
                          style={{ fontSize: '26rpx', color: C.text2, cursor: 'pointer' }}
                        >
                          设为默认
                        </Text>
                      )}
                      <Text
                        onClick={() => handleDeleteAddress(addr.id)}
                        style={{ fontSize: '26rpx', color: C.red, cursor: 'pointer' }}
                      >
                        删除
                      </Text>
                    </View>
                  </View>
                ))}

                {!loadingAddresses && addresses.length === 0 && (
                  <View style={{ padding: '40rpx', textAlign: 'center' }}>
                    <Text style={{ color: C.text3, fontSize: '28rpx' }}>暂无地址</Text>
                  </View>
                )}

                {/* Add new */}
                <View
                  onClick={() => { setEditingAddress(null); setShowAddressForm(true) }}
                  style={{
                    padding: '32rpx',
                    display: 'flex',
                    flexDirection: 'row',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '12rpx',
                    cursor: 'pointer',
                  }}
                >
                  <Text style={{ fontSize: '32rpx', color: C.primary }}>+</Text>
                  <Text style={{ fontSize: '28rpx', color: C.primary }}>新增收货地址</Text>
                </View>
              </View>
            )}
          </Card>

          {/* ══ 4. 隐私与安全 ══ */}
          <SectionTitle title="隐私与安全" />
          <Card>
            <SettingRow label="数据授权说明" onTap={() => navigateTo('/subpages/settings/data-auth/index')} />
            <SettingRow label="清除缓存" arrow={false} onTap={handleClearCache} />
            <SettingRow label="注销账号" danger arrow={false} onTap={handleLogout} />
          </Card>

          {/* ══ 5. 关于屯象 ══ */}
          <SectionTitle title="关于屯象" />
          <Card>
            <SettingRow label="当前版本" value={`v${APP_VERSION}`} arrow={false} />
            <SettingRow label="用户协议" onTap={() => navigateTo('/subpages/settings/agreement/index')} />
            <SettingRow label="隐私政策" onTap={() => navigateTo('/subpages/settings/privacy/index')} />
            <SettingRow
              label="联系我们"
              onTap={() => Taro.makePhoneCall({ phoneNumber: '400-000-0000' })}
            />
          </Card>

          {/* Logout button */}
          {isLoggedIn && (
            <View
              onClick={() => {
                logout()
                Taro.reLaunch({ url: '/pages/login/index' })
              }}
              style={{
                margin: '48rpx 32rpx 0',
                height: '96rpx',
                borderRadius: '48rpx',
                background: C.bgCard,
                border: `2rpx solid ${C.border}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
              }}
            >
              <Text style={{ fontSize: '32rpx', color: C.red }}>退出登录</Text>
            </View>
          )}
        </View>
      </ScrollView>

      {/* Address form modal */}
      {showAddressForm && (
        <AddressFormModal
          address={editingAddress}
          onSave={handleSaveAddress}
          onClose={() => { setShowAddressForm(false); setEditingAddress(null) }}
        />
      )}
    </View>
  )
}
