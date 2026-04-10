/**
 * pre-order/index.tsx — 预点餐 + 到店取餐
 *
 * 流程: 选门店 → 选取餐时段(15分钟粒度) → 跳转菜单点餐 → 支付 → 生成取餐码
 * 后厨在预定时间前15分钟开始制作
 *
 * 对标: 瑞幸到店取/喜茶先点后取
 *
 * API: GET  /api/v1/trade/stores (门店列表)
 *      GET  /api/v1/trade/time-slots?store_id=&date= (可选时段)
 *      POST /api/v1/trade/orders (order_type='pre_order')
 */

import React, { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useStoreInfo } from '../../store/useStoreInfo'
import { txRequest } from '../../utils/request'

// ─── Colors ───────────────────────────────────────────────────────────────────

const C = {
  primary: '#FF6B2C',
  primaryBg: 'rgba(255,107,44,0.12)',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3340',
  success: '#34C759',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

interface NearbyStore {
  id: string
  name: string
  address: string
  distance_m: number
  is_open: boolean
  avg_wait_minutes: number
}

interface TimeSlot {
  time: string        // "11:00"
  available: boolean
  label: string       // "11:00 - 11:15"
}

type Step = 'store' | 'time' | 'confirm'

// ─── Fallback data ────────────────────────────────────────────────────────────

const FALLBACK_STORES: NearbyStore[] = [
  { id: 's1', name: '徐记海鲜·芙蓉店', address: '芙蓉区五一大道168号', distance_m: 850, is_open: true, avg_wait_minutes: 5 },
  { id: 's2', name: '徐记海鲜·梅溪湖店', address: '梅溪湖环湖路1号', distance_m: 3200, is_open: true, avg_wait_minutes: 10 },
  { id: 's3', name: '徐记海鲜·IFS店', address: 'IFS国金中心B1层', distance_m: 1500, is_open: true, avg_wait_minutes: 3 },
]

function generateTimeSlots(): TimeSlot[] {
  const now = new Date()
  const currentHour = now.getHours()
  const currentMinute = now.getMinutes()
  const slots: TimeSlot[] = []

  // 营业时段: 10:30-14:00, 17:00-21:30
  const periods = [
    { start: 10.5, end: 14 },
    { start: 17, end: 21.5 },
  ]

  for (const period of periods) {
    for (let h = period.start; h < period.end; h += 0.25) {
      const hour = Math.floor(h)
      const minute = (h % 1) * 60
      const timeStr = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
      const endMinute = minute + 15
      const endHour = endMinute >= 60 ? hour + 1 : hour
      const endMin = endMinute >= 60 ? endMinute - 60 : endMinute
      const endStr = `${String(endHour).padStart(2, '0')}:${String(endMin).padStart(2, '0')}`

      // 过去的时段不可选（需要提前30分钟）
      const slotMinutes = hour * 60 + minute
      const nowMinutes = currentHour * 60 + currentMinute + 30
      const available = slotMinutes >= nowMinutes

      slots.push({ time: timeStr, available, label: `${timeStr} - ${endStr}` })
    }
  }
  return slots
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PreOrderPage() {
  const { storeId, setStore } = useStoreInfo()
  const [step, setStep] = useState<Step>('store')
  const [stores, setStores] = useState<NearbyStore[]>(FALLBACK_STORES)
  const [selectedStore, setSelectedStore] = useState<NearbyStore | null>(null)
  const [timeSlots, setTimeSlots] = useState<TimeSlot[]>(generateTimeSlots)
  const [selectedTime, setSelectedTime] = useState('')
  const [loading, setLoading] = useState(false)

  // ─── Load stores ────────────────────────────────────────────────────────────

  useEffect(() => {
    txRequest<{ items: NearbyStore[] }>('/trade/stores?page=1&size=20')
      .then(data => { if (data?.items?.length) setStores(data.items) })
      .catch(() => {})
  }, [])

  // ─── Handlers ───────────────────────────────────────────────────────────────

  const handleSelectStore = (store: NearbyStore) => {
    setSelectedStore(store)
    setStore(store.id, store.name)
    setStep('time')
  }

  const handleSelectTime = (slot: TimeSlot) => {
    if (!slot.available) return
    setSelectedTime(slot.time)
    setStep('confirm')
  }

  const handleConfirm = () => {
    if (!selectedStore || !selectedTime) return
    // 跳转到菜单页点餐，携带预点餐标记
    Taro.navigateTo({
      url: `/pages/menu/index?pre_order=1&pickup_time=${selectedTime}&store_id=${selectedStore.id}`,
    })
  }

  // ─── Render: Step 1 — 选门店 ────────────────────────────────────────────────

  const renderStoreStep = () => (
    <View>
      <Text style={styles.stepTitle}>选择取餐门店</Text>
      <Text style={styles.stepSub}>按距离排序，显示预计等待时间</Text>

      {stores.map(store => (
        <View
          key={store.id}
          onClick={() => store.is_open && handleSelectStore(store)}
          style={{
            ...styles.card,
            opacity: store.is_open ? 1 : 0.5,
            border: selectedStore?.id === store.id ? `2rpx solid ${C.primary}` : `2rpx solid ${C.border}`,
          }}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.storeName}>{store.name}</Text>
            <Text style={styles.storeAddr}>{store.address}</Text>
            <View style={{ display: 'flex', alignItems: 'center', gap: '16rpx', marginTop: '8rpx' }}>
              <Text style={{ fontSize: '24rpx', color: C.primary }}>
                {store.distance_m < 1000 ? `${store.distance_m}m` : `${(store.distance_m / 1000).toFixed(1)}km`}
              </Text>
              {store.is_open ? (
                <Text style={{ fontSize: '24rpx', color: C.success }}>
                  营业中 · 预计{store.avg_wait_minutes}分钟
                </Text>
              ) : (
                <Text style={{ fontSize: '24rpx', color: C.text3 }}>已打烊</Text>
              )}
            </View>
          </View>
          <Text style={{ fontSize: '28rpx', color: C.text3 }}>›</Text>
        </View>
      ))}
    </View>
  )

  // ─── Render: Step 2 — 选时段 ────────────────────────────────────────────────

  const renderTimeStep = () => (
    <View>
      <View style={{ display: 'flex', alignItems: 'center', marginBottom: '24rpx' }}>
        <Text onClick={() => setStep('store')} style={{ fontSize: '28rpx', color: C.primary, marginRight: '16rpx' }}>← 换门店</Text>
        <Text style={styles.stepTitle}>{selectedStore?.name}</Text>
      </View>
      <Text style={styles.stepSub}>选择取餐时间（需提前30分钟下单）</Text>

      <View style={{ display: 'flex', flexWrap: 'wrap', gap: '16rpx', marginTop: '24rpx' }}>
        {timeSlots.map(slot => (
          <View
            key={slot.time}
            onClick={() => handleSelectTime(slot)}
            style={{
              padding: '20rpx 24rpx',
              borderRadius: '12rpx',
              background: selectedTime === slot.time ? C.primary : slot.available ? C.bgCard : C.bgDeep,
              border: selectedTime === slot.time ? 'none' : `2rpx solid ${C.border}`,
              opacity: slot.available ? 1 : 0.35,
              minWidth: '160rpx',
              textAlign: 'center',
            }}
          >
            <Text style={{
              fontSize: '28rpx',
              fontWeight: selectedTime === slot.time ? '600' : '400',
              color: selectedTime === slot.time ? C.white : slot.available ? C.text1 : C.text3,
            }}>
              {slot.label}
            </Text>
          </View>
        ))}
      </View>
    </View>
  )

  // ─── Render: Step 3 — 确认 ──────────────────────────────────────────────────

  const renderConfirmStep = () => (
    <View>
      <Text onClick={() => setStep('time')} style={{ fontSize: '28rpx', color: C.primary, marginBottom: '24rpx', display: 'block' }}>← 改时间</Text>
      <Text style={styles.stepTitle}>确认预点餐信息</Text>

      <View style={{ ...styles.card, marginTop: '32rpx' }}>
        <View style={{ marginBottom: '20rpx' }}>
          <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block' }}>取餐门店</Text>
          <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.text1, display: 'block', marginTop: '8rpx' }}>{selectedStore?.name}</Text>
          <Text style={{ fontSize: '24rpx', color: C.text2, display: 'block', marginTop: '4rpx' }}>{selectedStore?.address}</Text>
        </View>
        <View style={{ borderTop: `1rpx solid ${C.border}`, paddingTop: '20rpx' }}>
          <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block' }}>取餐时间</Text>
          <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.primary, display: 'block', marginTop: '8rpx' }}>{selectedTime}</Text>
          <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>后厨将在取餐前15分钟开始制作</Text>
        </View>
      </View>

      <View
        onClick={handleConfirm}
        style={{
          marginTop: '48rpx',
          padding: '28rpx 0',
          borderRadius: '16rpx',
          background: C.primary,
          textAlign: 'center',
        }}
      >
        <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.white }}>
          开始点餐
        </Text>
      </View>

      <Text style={{ fontSize: '24rpx', color: C.text3, textAlign: 'center', display: 'block', marginTop: '16rpx' }}>
        点餐后支付即可获得取餐码
      </Text>
    </View>
  )

  // ─── Main render ────────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      {/* Progress indicator */}
      <View style={{ display: 'flex', alignItems: 'center', marginBottom: '40rpx', gap: '12rpx' }}>
        {(['store', 'time', 'confirm'] as Step[]).map((s, i) => (
          <React.Fragment key={s}>
            <View style={{
              width: '48rpx', height: '48rpx', borderRadius: '50%',
              background: step === s ? C.primary : i < ['store', 'time', 'confirm'].indexOf(step) ? C.success : C.bgCard,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Text style={{ fontSize: '24rpx', color: C.white, fontWeight: '600' }}>{i + 1}</Text>
            </View>
            {i < 2 && (
              <View style={{
                flex: 1, height: '4rpx',
                background: i < ['store', 'time', 'confirm'].indexOf(step) ? C.success : C.border,
              }} />
            )}
          </React.Fragment>
        ))}
      </View>

      {step === 'store' && renderStoreStep()}
      {step === 'time' && renderTimeStep()}
      {step === 'confirm' && renderConfirmStep()}
    </View>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = {
  stepTitle: { fontSize: '36rpx', fontWeight: '700' as const, color: '#E8F4F8', display: 'block' as const },
  stepSub: { fontSize: '26rpx', color: '#5A7A88', display: 'block' as const, marginTop: '8rpx' },
  card: {
    padding: '28rpx',
    borderRadius: '16rpx',
    background: '#132029',
    border: '2rpx solid #1E3340',
    display: 'flex' as const,
    alignItems: 'center' as const,
    marginTop: '20rpx',
  },
  storeName: { fontSize: '30rpx', fontWeight: '600' as const, color: '#E8F4F8', display: 'block' as const },
  storeAddr: { fontSize: '24rpx', color: '#9EB5C0', display: 'block' as const, marginTop: '4rpx' },
}
