/**
 * address/index.tsx — 地址管理
 *
 * 功能：地址列表、新增/编辑/删除地址、设为默认、从下单页选择地址
 *
 * Params:
 *   select — '1' 表示选择模式（从下单页进入），选中后返回上一页
 */

import React, { useState, useEffect, useCallback } from 'react'
import { View, Text, Input } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { txRequest } from '../../utils/request'
import './index.scss'

// ─── Brand tokens ────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  border:      '#1E3340',
  success:     '#34C759',
  danger:      '#FF3B30',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Types ──────────────────────────────────────────────────────────────────

interface Address {
  id: string
  name: string
  phone: string
  region: string
  detail: string
  tag: string
  is_default: boolean
}

interface AddressFormData {
  name: string
  phone: string
  region: string
  detail: string
  tag: string
}

type PageMode = 'list' | 'add' | 'edit'

const TAG_OPTIONS = ['家', '公司', '学校', '其他']

const EMPTY_FORM: AddressFormData = { name: '', phone: '', region: '', detail: '', tag: '' }

// ─── Component ──────────────────────────────────────────────────────────────

const AddressPage: React.FC = () => {
  const router = useRouter()
  const selectMode = router.params.select === '1'

  const [addresses, setAddresses] = useState<Address[]>([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<PageMode>('list')
  const [editingId, setEditingId] = useState('')
  const [form, setForm] = useState<AddressFormData>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)

  // ─── Load addresses ────────────────────────────────────────────────────────

  const loadAddresses = useCallback(async () => {
    setLoading(true)
    try {
      const data = await txRequest<{ items: Address[] } | Address[]>(
        '/api/v1/member/addresses',
      )
      const items = Array.isArray(data) ? data : (data.items || [])
      // Default address first
      items.sort((a, b) => (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0))
      setAddresses(items)
    } catch (_) {
      // Fallback mock data for dev
      setAddresses([
        {
          id: 'mock1', name: '张三', phone: '138****8888',
          region: '湖南省长沙市岳麓区', detail: '麓谷街道中电软件园1号楼',
          tag: '公司', is_default: true,
        },
        {
          id: 'mock2', name: '张三', phone: '138****8888',
          region: '湖南省长沙市天心区', detail: '芙蓉南路某某小区3栋',
          tag: '家', is_default: false,
        },
      ])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAddresses()
  }, [loadAddresses])

  // ─── Form actions ──────────────────────────────────────────────────────────

  const onFieldChange = (field: keyof AddressFormData, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const onSelectTag = (tag: string) => {
    setForm((prev) => ({ ...prev, tag: prev.tag === tag ? '' : tag }))
  }

  const openAddForm = () => {
    setForm(EMPTY_FORM)
    setEditingId('')
    setMode('add')
    Taro.setNavigationBarTitle({ title: '新增地址' })
  }

  const openEditForm = (addr: Address) => {
    setForm({
      name: addr.name,
      phone: addr.phone,
      region: addr.region,
      detail: addr.detail,
      tag: addr.tag,
    })
    setEditingId(addr.id)
    setMode('edit')
    Taro.setNavigationBarTitle({ title: '编辑地址' })
  }

  const onBackToList = () => {
    setMode('list')
    Taro.setNavigationBarTitle({ title: '收货地址' })
  }

  const validateForm = (): boolean => {
    if (!form.name.trim()) {
      Taro.showToast({ title: '请输入姓名', icon: 'none' })
      return false
    }
    if (!form.phone.trim() || form.phone.trim().length < 11) {
      Taro.showToast({ title: '请输入正确的手机号', icon: 'none' })
      return false
    }
    if (!form.region.trim()) {
      Taro.showToast({ title: '请输入所在地区', icon: 'none' })
      return false
    }
    if (!form.detail.trim()) {
      Taro.showToast({ title: '请输入详细地址', icon: 'none' })
      return false
    }
    return true
  }

  const onSubmitForm = async () => {
    if (!validateForm() || submitting) return
    setSubmitting(true)

    try {
      if (mode === 'add') {
        await txRequest('/api/v1/member/addresses', 'POST', {
          name: form.name.trim(),
          phone: form.phone.trim(),
          region: form.region.trim(),
          detail: form.detail.trim(),
          tag: form.tag,
        })
        Taro.showToast({ title: '添加成功', icon: 'success' })
      } else {
        await txRequest(`/api/v1/member/addresses/${editingId}`, 'PUT', {
          name: form.name.trim(),
          phone: form.phone.trim(),
          region: form.region.trim(),
          detail: form.detail.trim(),
          tag: form.tag,
        })
        Taro.showToast({ title: '修改成功', icon: 'success' })
      }
      onBackToList()
      loadAddresses()
    } catch (err) {
      Taro.showToast({ title: '保存失败', icon: 'none' })
    } finally {
      setSubmitting(false)
    }
  }

  // ─── Address operations ────────────────────────────────────────────────────

  const onSetDefault = async (id: string) => {
    try {
      await txRequest(`/api/v1/member/addresses/${id}/default`, 'PUT')
      Taro.showToast({ title: '已设为默认', icon: 'success' })
      loadAddresses()
    } catch (_) {
      Taro.showToast({ title: '操作失败', icon: 'none' })
    }
  }

  const onDelete = (id: string) => {
    Taro.showModal({
      title: '确认删除',
      content: '确定要删除这个地址吗？',
      confirmColor: C.primary,
      success: async (res) => {
        if (!res.confirm) return
        try {
          await txRequest(`/api/v1/member/addresses/${id}`, 'DELETE')
          Taro.showToast({ title: '已删除', icon: 'success' })
          loadAddresses()
        } catch (_) {
          Taro.showToast({ title: '删除失败', icon: 'none' })
        }
      },
    })
  }

  const onSelectAddress = (addr: Address) => {
    if (!selectMode) return
    // Pass selected address back to previous page via EventChannel
    const pages = Taro.getCurrentPages()
    const prevPage = pages[pages.length - 2] as Record<string, unknown> | undefined
    if (prevPage) {
      (prevPage as Record<string, unknown>)._selectedAddress = addr
    }
    Taro.navigateBack()
  }

  // ─── Choose region via wx ─────────────────────────────────────────────────

  const onChooseRegion = () => {
    Taro.chooseLocation({
      success: (res) => {
        if (res.address) {
          setForm((prev) => ({ ...prev, region: res.address }))
        }
      },
      fail: () => {
        // User cancelled or no permission
      },
    })
  }

  // ─── Render: Form ──────────────────────────────────────────────────────────

  if (mode === 'add' || mode === 'edit') {
    return (
      <View className="address-page">
        <View className="form-section">
          <View className="form-item">
            <Text className="form-label">姓名</Text>
            <Input
              className="form-input"
              placeholder="收货人姓名"
              placeholderClass="placeholder"
              value={form.name}
              onInput={(e) => onFieldChange('name', e.detail.value)}
            />
          </View>
          <View className="form-item">
            <Text className="form-label">手机号</Text>
            <Input
              className="form-input"
              placeholder="收货人手机号"
              placeholderClass="placeholder"
              type="number"
              maxlength={11}
              value={form.phone}
              onInput={(e) => onFieldChange('phone', e.detail.value)}
            />
          </View>
          <View className="form-item" onClick={onChooseRegion}>
            <Text className="form-label">所在地区</Text>
            <Text className={`form-value ${form.region ? '' : 'placeholder'}`}>
              {form.region || '点击选择地区'}
            </Text>
          </View>
          <View className="form-item">
            <Text className="form-label">详细地址</Text>
            <Input
              className="form-input"
              placeholder="楼栋/门牌号等详细信息"
              placeholderClass="placeholder"
              value={form.detail}
              onInput={(e) => onFieldChange('detail', e.detail.value)}
            />
          </View>
          <View className="form-item-tags">
            <Text className="form-label">标签</Text>
            <View className="tag-options">
              {TAG_OPTIONS.map((t) => (
                <View
                  key={t}
                  className={`tag-option ${form.tag === t ? 'active' : ''}`}
                  onClick={() => onSelectTag(t)}
                >
                  <Text className="tag-option-text">{t}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>

        <View className="form-actions">
          <View className="btn-cancel" onClick={onBackToList}>
            <Text className="btn-cancel-text">取消</Text>
          </View>
          <View className={`btn-save ${submitting ? 'disabled' : ''}`} onClick={onSubmitForm}>
            <Text className="btn-save-text">{submitting ? '保存中...' : '保存'}</Text>
          </View>
        </View>
      </View>
    )
  }

  // ─── Render: List ──────────────────────────────────────────────────────────

  return (
    <View className="address-page">
      {loading && (
        <View className="loading-tip">
          <Text className="loading-text">加载中...</Text>
        </View>
      )}

      {!loading && addresses.length === 0 && (
        <View className="empty-state">
          <Text className="empty-icon">📍</Text>
          <Text className="empty-text">暂无收货地址</Text>
          <Text className="empty-hint">添加一个常用地址吧</Text>
        </View>
      )}

      {addresses.length > 0 && (
        <View className="address-list">
          {addresses.map((addr) => (
            <View
              key={addr.id}
              className={`address-card ${addr.is_default ? 'is-default' : ''}`}
              onClick={() => onSelectAddress(addr)}
            >
              <View className="address-main">
                <View className="address-top">
                  <Text className="address-name">{addr.name}</Text>
                  <Text className="address-phone">{addr.phone}</Text>
                  {addr.tag && (
                    <View className="address-tag">
                      <Text className="tag-text">{addr.tag}</Text>
                    </View>
                  )}
                  {addr.is_default && (
                    <View className="default-badge">
                      <Text className="default-text">默认</Text>
                    </View>
                  )}
                </View>
                <Text className="address-detail">{addr.region}{addr.detail}</Text>
              </View>
              <View className="address-actions">
                {!addr.is_default && (
                  <View
                    className="action-btn"
                    onClick={(e) => { e.stopPropagation(); onSetDefault(addr.id) }}
                  >
                    <Text className="action-text">设为默认</Text>
                  </View>
                )}
                <View
                  className="action-btn"
                  onClick={(e) => { e.stopPropagation(); openEditForm(addr) }}
                >
                  <Text className="action-text">编辑</Text>
                </View>
                <View
                  className="action-btn action-danger"
                  onClick={(e) => { e.stopPropagation(); onDelete(addr.id) }}
                >
                  <Text className="action-text-danger">删除</Text>
                </View>
              </View>
            </View>
          ))}
        </View>
      )}

      <View className="bottom-bar">
        <View className="add-btn" onClick={openAddForm}>
          <Text className="add-btn-text">+ 新增收货地址</Text>
        </View>
      </View>
    </View>
  )
}

export default AddressPage
