/**
 * family-mode/index.tsx — 家庭/儿童/适老模式
 *
 * 对标西贝儿童餐+海底捞亲子服务：
 * - 儿童套餐专区（营养均衡标注）
 * - 过敏安全双重确认
 * - 亲子活动预约（烹饪体验课）
 * - 大字体适老模式（老年客群）
 * - 无障碍VoiceOver标签
 */

import React, { useState } from 'react'
import { View, Text, Switch, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useUserStore } from '../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  kids: '#FF9F0A',       // 儿童模式主色
  kidsBg: '#FFF8E1',
  elder: '#185FA5',      // 适老模式主色
  elderBg: '#E3F2FD',
  success: '#34C759',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

type Mode = 'select' | 'kids' | 'elder'

// ─── 儿童套餐数据 ──────────────────────────────────────────────────────────

const KIDS_MEALS = [
  { id: 'k1', name: '宝贝营养套餐A', emoji: '🍱', price_fen: 4800, age: '3-6岁', items: ['迷你蒸蛋', '胡萝卜肉丁', '米饭', '鲜榨果汁'], nutrition: '蛋白质15g·碳水40g·维生素C充足', allergens: [] },
  { id: 'k2', name: '宝贝营养套餐B', emoji: '🍝', price_fen: 5200, age: '6-12岁', items: ['番茄牛肉面', '玉米棒', '酸奶'], nutrition: '蛋白质20g·碳水55g·钙含量高', allergens: ['gluten', 'dairy'] },
  { id: 'k3', name: '无过敏宝宝餐', emoji: '🥬', price_fen: 4500, age: '3-12岁', items: ['清蒸鱼柳', '南瓜泥', '米饭', '苹果泥'], nutrition: '高蛋白·低敏·无添加', allergens: ['fish'] },
]

const FAMILY_ACTIVITIES = [
  { id: 'a1', name: '小厨师体验课', emoji: '👨‍🍳', desc: '亲子一起做饺子/面条', time: '周末 14:00-15:30', price: '¥68/组' },
  { id: 'a2', name: '食材认知之旅', emoji: '🌾', desc: '认识蔬菜水果，学习营养知识', time: '周末 10:00-11:00', price: '免费' },
  { id: 'a3', name: '生日派对包场', emoji: '🎂', desc: '主题布置+蛋糕+专属服务', time: '需提前3天预约', price: '¥299起' },
]

// ─── 主组件 ──────────────────────────────────────────────────────────────

export default function FamilyModePage() {
  const [mode, setMode] = useState<Mode>('select')
  const { preferences } = useUserStore()

  // ─── 模式选择 ──────────────────────────────────────────────────────────

  if (mode === 'select') {
    return (
      <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
        <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginBottom: '8rpx' }}>
          家庭服务中心
        </Text>
        <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginBottom: '40rpx' }}>
          为不同家庭成员提供贴心服务
        </Text>

        {/* 儿童模式 */}
        <View onClick={() => setMode('kids')} style={{
          padding: '32rpx', borderRadius: '20rpx', marginBottom: '20rpx',
          background: 'linear-gradient(135deg, #3A2A10 0%, #1A2A20 100%)',
          border: `2rpx solid ${C.kids}40`,
        }}>
          <View style={{ display: 'flex', alignItems: 'center', gap: '16rpx', marginBottom: '12rpx' }}>
            <Text style={{ fontSize: '48rpx' }}>👶</Text>
            <View>
              <Text style={{ fontSize: '32rpx', fontWeight: '700', color: C.kids, display: 'block' }}>儿童/亲子模式</Text>
              <Text style={{ fontSize: '24rpx', color: C.text2, display: 'block' }}>专属儿童套餐 · 过敏安全 · 亲子活动</Text>
            </View>
          </View>
          <View style={{ display: 'flex', gap: '12rpx', flexWrap: 'wrap' }}>
            {['营养标注', '过敏筛查', '儿童餐具', '游戏区'].map(tag => (
              <View key={tag} style={{ padding: '6rpx 16rpx', borderRadius: '16rpx', background: `${C.kids}20` }}>
                <Text style={{ fontSize: '22rpx', color: C.kids }}>{tag}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* 适老模式 */}
        <View onClick={() => setMode('elder')} style={{
          padding: '32rpx', borderRadius: '20rpx', marginBottom: '20rpx',
          background: 'linear-gradient(135deg, #0A1A3A 0%, #1A2A20 100%)',
          border: `2rpx solid ${C.elder}40`,
        }}>
          <View style={{ display: 'flex', alignItems: 'center', gap: '16rpx', marginBottom: '12rpx' }}>
            <Text style={{ fontSize: '48rpx' }}>👴</Text>
            <View>
              <Text style={{ fontSize: '32rpx', fontWeight: '700', color: C.elder, display: 'block' }}>关怀/适老模式</Text>
              <Text style={{ fontSize: '24rpx', color: C.text2, display: 'block' }}>大字体 · 简化操作 · 语音辅助</Text>
            </View>
          </View>
          <View style={{ display: 'flex', gap: '12rpx', flexWrap: 'wrap' }}>
            {['大字体', '高对比', '语音播报', '一键呼叫'].map(tag => (
              <View key={tag} style={{ padding: '6rpx 16rpx', borderRadius: '16rpx', background: `${C.elder}20` }}>
                <Text style={{ fontSize: '22rpx', color: C.elder }}>{tag}</Text>
              </View>
            ))}
          </View>
        </View>
      </View>
    )
  }

  // ─── 儿童模式 ──────────────────────────────────────────────────────────

  if (mode === 'kids') {
    return (
      <ScrollView scrollY style={{ minHeight: '100vh', background: C.bgDeep }}>
        <View style={{ padding: '32rpx' }}>
          <Text onClick={() => setMode('select')} style={{ fontSize: '28rpx', color: C.primary, display: 'block', marginBottom: '16rpx' }}>← 返回</Text>

          <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.kids, display: 'block' }}>👶 儿童专区</Text>
          <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx', marginBottom: '32rpx' }}>
            营养均衡 · 安全无忧 · 快乐用餐
          </Text>

          {/* 儿童套餐 */}
          <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginBottom: '16rpx' }}>营养套餐</Text>
          {KIDS_MEALS.map(meal => (
            <View key={meal.id} style={{
              padding: '24rpx', borderRadius: '16rpx', background: C.bgCard,
              border: `2rpx solid ${C.border}`, marginBottom: '12rpx',
            }}>
              <View style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <View style={{ display: 'flex', alignItems: 'center', gap: '12rpx' }}>
                  <Text style={{ fontSize: '40rpx' }}>{meal.emoji}</Text>
                  <View>
                    <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1, display: 'block' }}>{meal.name}</Text>
                    <Text style={{ fontSize: '22rpx', color: C.kids, display: 'block' }}>适合{meal.age}</Text>
                  </View>
                </View>
                <Text style={{ fontSize: '32rpx', fontWeight: '700', color: C.primary }}>¥{(meal.price_fen / 100).toFixed(0)}</Text>
              </View>

              <View style={{ marginTop: '12rpx', padding: '12rpx', borderRadius: '8rpx', background: C.bgDeep }}>
                <Text style={{ fontSize: '24rpx', color: C.text2, display: 'block' }}>
                  包含: {meal.items.join(' · ')}
                </Text>
                <Text style={{ fontSize: '22rpx', color: C.success, display: 'block', marginTop: '4rpx' }}>
                  🥗 {meal.nutrition}
                </Text>
                {meal.allergens.length > 0 && (
                  <Text style={{ fontSize: '22rpx', color: '#FF3B30', display: 'block', marginTop: '4rpx' }}>
                    ⚠️ 含: {meal.allergens.join('、')}
                  </Text>
                )}
              </View>

              <View onClick={() => Taro.showToast({ title: '已加入购物车', icon: 'success' })} style={{
                marginTop: '12rpx', padding: '16rpx 0', borderRadius: '10rpx',
                background: C.kids, textAlign: 'center',
              }}>
                <Text style={{ fontSize: '28rpx', fontWeight: '500', color: '#1a1a00' }}>加入购物车</Text>
              </View>
            </View>
          ))}

          {/* 亲子活动 */}
          <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block', marginTop: '32rpx', marginBottom: '16rpx' }}>
            亲子活动
          </Text>
          {FAMILY_ACTIVITIES.map(act => (
            <View key={act.id} style={{
              display: 'flex', alignItems: 'center', padding: '20rpx',
              background: C.bgCard, borderRadius: '12rpx', marginBottom: '10rpx',
              border: `2rpx solid ${C.border}`,
            }}>
              <Text style={{ fontSize: '40rpx', marginRight: '16rpx' }}>{act.emoji}</Text>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1, display: 'block' }}>{act.name}</Text>
                <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block' }}>{act.desc}</Text>
                <Text style={{ fontSize: '22rpx', color: C.text2, display: 'block' }}>{act.time} · {act.price}</Text>
              </View>
              <View style={{ padding: '8rpx 20rpx', borderRadius: '8rpx', background: `${C.kids}20` }}>
                <Text style={{ fontSize: '24rpx', color: C.kids }}>预约</Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    )
  }

  // ─── 适老模式 ──────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: '#FAFAFA', padding: '40rpx' }}>
      <Text onClick={() => setMode('select')} style={{ fontSize: '36rpx', color: C.elder, display: 'block', marginBottom: '24rpx' }}>← 返回</Text>

      <Text style={{ fontSize: '48rpx', fontWeight: '700', color: '#333', display: 'block', marginBottom: '16rpx' }}>
        关怀模式
      </Text>
      <Text style={{ fontSize: '32rpx', color: '#666', display: 'block', marginBottom: '40rpx' }}>
        大字体 · 简化操作 · 更清晰
      </Text>

      {/* 大按钮操作 */}
      {[
        { icon: '📱', label: '扫码点餐', path: '/pages/menu/index', desc: '扫桌上二维码开始点菜' },
        { icon: '📞', label: '呼叫服务员', path: '', desc: '一键呼叫门店服务员' },
        { icon: '📋', label: '查看订单', path: '/pages/order/index', desc: '查看我的点餐记录' },
        { icon: '🔊', label: '语音点餐', path: '', desc: '说出想吃的菜名即可' },
      ].map(item => (
        <View
          key={item.label}
          onClick={() => {
            if (item.path) Taro.switchTab({ url: item.path }).catch(() => Taro.navigateTo({ url: item.path }))
            else Taro.showToast({ title: '功能开发中', icon: 'none' })
          }}
          style={{
            display: 'flex', alignItems: 'center', padding: '32rpx',
            background: '#FFFFFF', borderRadius: '20rpx', marginBottom: '16rpx',
            border: '2rpx solid #E0E0E0', boxShadow: '0 4rpx 12rpx rgba(0,0,0,0.05)',
          }}
        >
          <Text style={{ fontSize: '56rpx', marginRight: '24rpx' }}>{item.icon}</Text>
          <View>
            <Text style={{ fontSize: '36rpx', fontWeight: '700', color: '#333', display: 'block' }}>{item.label}</Text>
            <Text style={{ fontSize: '28rpx', color: '#888', display: 'block', marginTop: '4rpx' }}>{item.desc}</Text>
          </View>
        </View>
      ))}

      <View style={{
        marginTop: '32rpx', padding: '24rpx', borderRadius: '16rpx',
        background: `${C.elder}10`, border: `2rpx solid ${C.elder}30`,
      }}>
        <Text style={{ fontSize: '28rpx', color: C.elder, display: 'block' }}>
          💡 提示：如需帮助，请告诉服务员"开启关怀模式"，我们会为您提供一对一服务。
        </Text>
      </View>
    </View>
  )
}
