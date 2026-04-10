/**
 * brand-picker/index.tsx — 集团多品牌选择器
 *
 * 集团级客户（如九毛九集团）旗下多个品牌共享一个小程序入口。
 * 用户选择品牌后，门店列表/菜单/会员权益联动切换。
 *
 * API: GET /api/v1/org/brands (tx-org)
 */

import React, { useCallback, useEffect, useState } from 'react'
import { View, Text, Image, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useStoreInfo, type BrandInfo } from '../../store/useStoreInfo'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Fallback brands ──────────────────────────────────────────────────────────

const FALLBACK_BRANDS: BrandInfo[] = [
  { id: 'brand-xj', name: '徐记海鲜', logo_url: '', theme_color: '#FF6B35' },
  { id: 'brand-xc', name: '湘厨小馆', logo_url: '', theme_color: '#0F6E56' },
  { id: 'brand-hw', name: '海味外卖', logo_url: '', theme_color: '#185FA5' },
]

// ─── Component ────────────────────────────────────────────────────────────────

export default function BrandPickerPage() {
  const { brandId, setBrand, setBrands } = useStoreInfo()
  const [brands, setLocalBrands] = useState<BrandInfo[]>(FALLBACK_BRANDS)
  const [loading, setLoading] = useState(false)

  const loadBrands = useCallback(async () => {
    setLoading(true)
    try {
      const data = await txRequest<{ items: BrandInfo[] }>('/org/brands')
      if (data?.items?.length) {
        setLocalBrands(data.items)
        setBrands(data.items)
      }
    } catch {
      // fallback
    }
    setLoading(false)
  }, [setBrands])

  useEffect(() => { loadBrands() }, [loadBrands])

  const handleSelect = (brand: BrandInfo) => {
    setBrand(brand.id, brand.name)
    // 返回首页，首页会根据 brandId 加载对应门店
    Taro.navigateBack({ delta: 1 }).catch(() => {
      Taro.switchTab({ url: '/pages/index/index' })
    })
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginBottom: '16rpx' }}>
        选择品牌
      </Text>
      <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginBottom: '48rpx' }}>
        集团旗下品牌，会员积分/储值通用
      </Text>

      {loading && (
        <Text style={{ fontSize: '28rpx', color: C.text3, textAlign: 'center', display: 'block', padding: '40rpx 0' }}>
          加载中...
        </Text>
      )}

      <ScrollView scrollY style={{ flex: 1 }}>
        {brands.map((brand) => {
          const isActive = brandId === brand.id
          return (
            <View
              key={brand.id}
              onClick={() => handleSelect(brand)}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '32rpx',
                marginBottom: '20rpx',
                borderRadius: '20rpx',
                background: isActive ? `${brand.theme_color}15` : C.bgCard,
                border: isActive ? `2rpx solid ${brand.theme_color}` : `2rpx solid ${C.border}`,
              }}
            >
              {/* Logo */}
              <View
                style={{
                  width: '96rpx',
                  height: '96rpx',
                  borderRadius: '20rpx',
                  background: brand.theme_color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: '0',
                  marginRight: '24rpx',
                }}
              >
                {brand.logo_url ? (
                  <Image src={brand.logo_url} style={{ width: '64rpx', height: '64rpx' }} mode="aspectFit" />
                ) : (
                  <Text style={{ fontSize: '36rpx', color: C.white, fontWeight: '700' }}>
                    {brand.name.charAt(0)}
                  </Text>
                )}
              </View>

              {/* Info */}
              <View style={{ flex: 1 }}>
                <Text style={{
                  fontSize: '32rpx',
                  fontWeight: '600',
                  color: isActive ? brand.theme_color : C.text1,
                  display: 'block',
                }}>
                  {brand.name}
                </Text>
                {isActive && (
                  <Text style={{ fontSize: '24rpx', color: brand.theme_color, marginTop: '4rpx', display: 'block' }}>
                    当前选择
                  </Text>
                )}
              </View>

              {/* Check mark */}
              {isActive && (
                <View style={{
                  width: '48rpx',
                  height: '48rpx',
                  borderRadius: '50%',
                  background: brand.theme_color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <Text style={{ color: C.white, fontSize: '28rpx', fontWeight: '700' }}>✓</Text>
                </View>
              )}
            </View>
          )
        })}
      </ScrollView>
    </View>
  )
}
