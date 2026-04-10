/**
 * queue-game/index.tsx — 等位互动小游戏
 *
 * 对标海底捞等位折纸鹤换菜品：
 * - 翻牌记忆游戏（匹配菜品图片）
 * - 限时答题（美食知识问答）
 * - 幸运转盘（随机奖励）
 *
 * 奖励：积分/优惠券/菜品升级/免排队次数
 * 将等位痛点转化为品牌互动体验
 */

import React, { useState, useCallback, useEffect, useRef } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { txRequest } from '../../utils/request'
import { useUserStore } from '../../store/useUserStore'

const C = {
  primary: '#FF6B2C',
  gold: '#C5A347',
  success: '#34C759',
  danger: '#FF3B30',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
} as const

// ─── 翻牌游戏数据 ──────────────────────────────────────────────────────────

const DISH_CARDS = [
  { id: 'a1', emoji: '🐟', name: '剁椒鱼头' },
  { id: 'a2', emoji: '🦐', name: '口味虾' },
  { id: 'a3', emoji: '🥩', name: '红烧肉' },
  { id: 'a4', emoji: '🥗', name: '凉拌黄瓜' },
  { id: 'a5', emoji: '🍜', name: '蛋炒饭' },
  { id: 'a6', emoji: '🧋', name: '酸梅汤' },
]

interface Card {
  id: string
  emoji: string
  name: string
  pairId: string
  flipped: boolean
  matched: boolean
}

function shuffleCards(): Card[] {
  const pairs = DISH_CARDS.flatMap(d => [
    { ...d, pairId: d.id, flipped: false, matched: false, id: d.id + '_1' },
    { ...d, pairId: d.id, flipped: false, matched: false, id: d.id + '_2' },
  ])
  for (let i = pairs.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pairs[i], pairs[j]] = [pairs[j], pairs[i]]
  }
  return pairs
}

// ─── 问答数据 ──────────────────────────────────────────────────────────────

const QUIZ_QUESTIONS = [
  { q: '剁椒鱼头是哪个菜系的代表菜？', options: ['川菜', '湘菜', '粤菜', '鲁菜'], answer: 1 },
  { q: '活鲜鲈鱼最佳烹饪方式是？', options: ['油炸', '清蒸', '红烧', '烧烤'], answer: 1 },
  { q: '口味虾的灵魂调料是？', options: ['花椒', '辣椒', '十三香', '蒜蓉'], answer: 2 },
  { q: '正宗农家小炒肉用的是什么辣椒？', options: ['朝天椒', '螺丝椒', '灯笼椒', '小米椒'], answer: 1 },
  { q: '海鲜过敏最常见的过敏原是？', options: ['蛋白质', '脂肪', '组胺', '碳水'], answer: 0 },
]

// ─── 奖励配置 ──────────────────────────────────────────────────────────────

const REWARDS = [
  { id: 'r1', name: '50积分', emoji: '⭐', type: 'points', value: 50, probability: 0.35 },
  { id: 'r2', name: '满50减5券', emoji: '🎫', type: 'coupon', value: 500, probability: 0.25 },
  { id: 'r3', name: '菜品升级', emoji: '⬆️', type: 'upgrade', value: 0, probability: 0.15 },
  { id: 'r4', name: '100积分', emoji: '🌟', type: 'points', value: 100, probability: 0.10 },
  { id: 'r5', name: '满100减15券', emoji: '🎟', type: 'coupon', value: 1500, probability: 0.10 },
  { id: 'r6', name: '谢谢参与', emoji: '😊', type: 'none', value: 0, probability: 0.05 },
]

type GameMode = 'select' | 'memory' | 'quiz' | 'wheel' | 'result'

// ─── 主组件 ──────────────────────────────────────────────────────────────

export default function QueueGamePage() {
  const [mode, setMode] = useState<GameMode>('select')
  const [reward, setReward] = useState<typeof REWARDS[0] | null>(null)
  const { pointsBalance } = useUserStore()

  const claimReward = useCallback(async (r: typeof REWARDS[0]) => {
    setReward(r)
    setMode('result')
    if (r.type !== 'none') {
      try {
        await txRequest('/growth/queue-game/claim', 'POST', {
          reward_type: r.type, reward_value: r.value, reward_name: r.name,
        } as Record<string, unknown>)
      } catch { /* offline ok */ }
    }
  }, [])

  // ─── 游戏选择页 ──────────────────────────────────────────────────────────

  if (mode === 'select') {
    return (
      <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
        <View style={{ textAlign: 'center', padding: '40rpx 0 32rpx' }}>
          <Text style={{ fontSize: '48rpx', display: 'block' }}>🎮</Text>
          <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1, display: 'block', marginTop: '12rpx' }}>
            等位乐园
          </Text>
          <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '8rpx' }}>
            边等边玩，赢取积分和优惠券！
          </Text>
        </View>

        {[
          { id: 'memory', icon: '🃏', name: '菜品翻翻乐', desc: '翻牌匹配菜品图案，12张牌6对', time: '60秒' },
          { id: 'quiz', icon: '❓', name: '美食知识王', desc: '5道美食知识问答，答对赢积分', time: '90秒' },
          { id: 'wheel', icon: '🎡', name: '幸运大转盘', desc: '每次等位1次抽奖机会', time: '即时' },
        ].map(game => (
          <View
            key={game.id}
            onClick={() => setMode(game.id as GameMode)}
            style={{
              display: 'flex', alignItems: 'center', padding: '28rpx',
              background: C.bgCard, borderRadius: '16rpx', marginBottom: '16rpx',
              border: `2rpx solid ${C.border}`,
            }}
          >
            <Text style={{ fontSize: '48rpx', marginRight: '20rpx' }}>{game.icon}</Text>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: '30rpx', fontWeight: '600', color: C.text1, display: 'block' }}>{game.name}</Text>
              <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>{game.desc}</Text>
            </View>
            <View style={{ padding: '8rpx 16rpx', borderRadius: '8rpx', background: `${C.primary}20` }}>
              <Text style={{ fontSize: '22rpx', color: C.primary }}>{game.time}</Text>
            </View>
          </View>
        ))}

        <Text style={{ fontSize: '22rpx', color: C.text3, textAlign: 'center', display: 'block', marginTop: '24rpx' }}>
          当前积分: {pointsBalance || 0} · 每次等位可玩3次
        </Text>
      </View>
    )
  }

  // ─── 翻牌记忆游戏 ──────────────────────────────────────────────────────────

  if (mode === 'memory') {
    return <MemoryGame onWin={(score) => {
      const r = score >= 5 ? REWARDS[3] : score >= 3 ? REWARDS[0] : REWARDS[5]
      claimReward(r)
    }} onBack={() => setMode('select')} />
  }

  // ─── 问答游戏 ──────────────────────────────────────────────────────────

  if (mode === 'quiz') {
    return <QuizGame onFinish={(correct) => {
      const r = correct >= 4 ? REWARDS[4] : correct >= 2 ? REWARDS[1] : REWARDS[0]
      claimReward(r)
    }} onBack={() => setMode('select')} />
  }

  // ─── 幸运转盘 ──────────────────────────────────────────────────────────

  if (mode === 'wheel') {
    return <LuckyWheel onResult={(r) => claimReward(r)} onBack={() => setMode('select')} />
  }

  // ─── 结果页 ──────────────────────────────────────────────────────────

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32rpx' }}>
      <Text style={{ fontSize: '80rpx', display: 'block' }}>{reward?.emoji || '🎉'}</Text>
      <Text style={{ fontSize: '36rpx', fontWeight: '700', color: reward?.type === 'none' ? C.text3 : C.gold, display: 'block', marginTop: '24rpx' }}>
        {reward?.type === 'none' ? '谢谢参与' : `恭喜获得 ${reward?.name}`}
      </Text>
      <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginTop: '12rpx' }}>
        {reward?.type === 'points' ? '积分已自动到账' : reward?.type === 'coupon' ? '优惠券已放入卡包' : '下次再来！'}
      </Text>
      <View style={{ display: 'flex', gap: '16rpx', marginTop: '48rpx' }}>
        <View onClick={() => setMode('select')} style={{ padding: '20rpx 40rpx', borderRadius: '12rpx', background: C.bgCard, border: `2rpx solid ${C.border}` }}>
          <Text style={{ fontSize: '28rpx', color: C.text1 }}>再玩一次</Text>
        </View>
        <View onClick={() => Taro.navigateBack()} style={{ padding: '20rpx 40rpx', borderRadius: '12rpx', background: C.primary }}>
          <Text style={{ fontSize: '28rpx', color: C.white, fontWeight: '500' }}>返回排队</Text>
        </View>
      </View>
    </View>
  )
}

// ─── 翻牌子游戏 ──────────────────────────────────────────────────────────

function MemoryGame({ onWin, onBack }: { onWin: (score: number) => void; onBack: () => void }) {
  const [cards, setCards] = useState<Card[]>(shuffleCards)
  const [selected, setSelected] = useState<string[]>([])
  const [matches, setMatches] = useState(0)
  const [moves, setMoves] = useState(0)
  const [timeLeft, setTimeLeft] = useState(60)
  const timerRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setTimeLeft(t => {
        if (t <= 1) { clearInterval(timerRef.current); onWin(matches); return 0 }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, []) // eslint-disable-line

  useEffect(() => {
    if (matches >= 6) { clearInterval(timerRef.current); onWin(matches) }
  }, [matches, onWin])

  const handleFlip = (id: string) => {
    if (selected.length >= 2) return
    const card = cards.find(c => c.id === id)
    if (!card || card.flipped || card.matched) return

    const newCards = cards.map(c => c.id === id ? { ...c, flipped: true } : c)
    const newSelected = [...selected, id]
    setCards(newCards)
    setSelected(newSelected)
    setMoves(m => m + 1)

    if (newSelected.length === 2) {
      const [first, second] = newSelected.map(sid => newCards.find(c => c.id === sid)!)
      if (first.pairId === second.pairId) {
        setTimeout(() => {
          setCards(prev => prev.map(c => c.pairId === first.pairId ? { ...c, matched: true } : c))
          setMatches(m => m + 1)
          setSelected([])
        }, 300)
      } else {
        setTimeout(() => {
          setCards(prev => prev.map(c => newSelected.includes(c.id) ? { ...c, flipped: false } : c))
          setSelected([])
        }, 800)
      }
    }
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      <View style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24rpx' }}>
        <Text onClick={onBack} style={{ fontSize: '28rpx', color: C.primary }}>← 返回</Text>
        <Text style={{ fontSize: '28rpx', color: timeLeft < 10 ? C.danger : C.text1 }}>⏱ {timeLeft}s</Text>
        <Text style={{ fontSize: '28rpx', color: C.text2 }}>✓ {matches}/6</Text>
      </View>
      <View style={{ display: 'flex', flexWrap: 'wrap', gap: '12rpx', justifyContent: 'center' }}>
        {cards.map(card => (
          <View
            key={card.id}
            onClick={() => handleFlip(card.id)}
            style={{
              width: '150rpx', height: '150rpx', borderRadius: '16rpx',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: card.matched ? `${C.success}30` : card.flipped ? C.bgCard : C.primary,
              border: card.matched ? `2rpx solid ${C.success}` : `2rpx solid ${C.border}`,
              transition: 'all 0.3s',
            }}
          >
            <Text style={{ fontSize: card.flipped || card.matched ? '48rpx' : '32rpx' }}>
              {card.flipped || card.matched ? card.emoji : '?'}
            </Text>
          </View>
        ))}
      </View>
      <Text style={{ fontSize: '24rpx', color: C.text3, textAlign: 'center', display: 'block', marginTop: '20rpx' }}>
        翻了 {moves} 次 · 匹配所有6对菜品赢大奖
      </Text>
    </View>
  )
}

// ─── 问答游戏 ──────────────────────────────────────────────────────────

function QuizGame({ onFinish, onBack }: { onFinish: (correct: number) => void; onBack: () => void }) {
  const [qIndex, setQIndex] = useState(0)
  const [correct, setCorrect] = useState(0)
  const [answered, setAnswered] = useState<number | null>(null)

  const q = QUIZ_QUESTIONS[qIndex]

  const handleAnswer = (idx: number) => {
    if (answered !== null) return
    setAnswered(idx)
    if (idx === q.answer) setCorrect(c => c + 1)

    setTimeout(() => {
      if (qIndex + 1 >= QUIZ_QUESTIONS.length) {
        onFinish(correct + (idx === q.answer ? 1 : 0))
      } else {
        setQIndex(i => i + 1)
        setAnswered(null)
      }
    }, 1000)
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx' }}>
      <View style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '32rpx' }}>
        <Text onClick={onBack} style={{ fontSize: '28rpx', color: C.primary }}>← 返回</Text>
        <Text style={{ fontSize: '28rpx', color: C.text2 }}>第{qIndex + 1}/{QUIZ_QUESTIONS.length}题</Text>
        <Text style={{ fontSize: '28rpx', color: C.gold }}>✓ {correct}</Text>
      </View>

      <View style={{ background: C.bgCard, borderRadius: '20rpx', padding: '32rpx', marginBottom: '24rpx' }}>
        <Text style={{ fontSize: '32rpx', fontWeight: '600', color: C.text1, lineHeight: '48rpx' }}>{q.q}</Text>
      </View>

      {q.options.map((opt, idx) => {
        let bg = C.bgCard
        let borderColor = C.border
        if (answered !== null) {
          if (idx === q.answer) { bg = `${C.success}20`; borderColor = C.success }
          else if (idx === answered) { bg = `${C.danger}20`; borderColor = C.danger }
        }
        return (
          <View
            key={idx}
            onClick={() => handleAnswer(idx)}
            style={{
              padding: '24rpx', borderRadius: '12rpx', marginBottom: '12rpx',
              background: bg, border: `2rpx solid ${borderColor}`,
            }}
          >
            <Text style={{ fontSize: '28rpx', color: C.text1 }}>
              {String.fromCharCode(65 + idx)}. {opt}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

// ─── 幸运转盘 ──────────────────────────────────────────────────────────

function LuckyWheel({ onResult, onBack }: { onResult: (r: typeof REWARDS[0]) => void; onBack: () => void }) {
  const [spinning, setSpinning] = useState(false)
  const [rotation, setRotation] = useState(0)

  const handleSpin = () => {
    if (spinning) return
    setSpinning(true)

    // 按概率抽奖
    const rand = Math.random()
    let cumulative = 0
    let selected = REWARDS[REWARDS.length - 1]
    for (const r of REWARDS) {
      cumulative += r.probability
      if (rand <= cumulative) { selected = r; break }
    }

    const idx = REWARDS.indexOf(selected)
    const segAngle = 360 / REWARDS.length
    const targetAngle = 360 * 5 + (360 - idx * segAngle - segAngle / 2) // 5圈+目标位置
    setRotation(targetAngle)

    setTimeout(() => {
      setSpinning(false)
      onResult(selected)
    }, 3500)
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, padding: '32rpx', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <Text onClick={onBack} style={{ fontSize: '28rpx', color: C.primary, alignSelf: 'flex-start', marginBottom: '24rpx' }}>← 返回</Text>

      <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.gold, marginBottom: '32rpx' }}>🎡 幸运大转盘</Text>

      {/* 转盘 */}
      <View style={{
        width: '500rpx', height: '500rpx', borderRadius: '50%',
        background: `conic-gradient(${REWARDS.map((r, i) => {
          const colors = [C.primary, '#185FA5', C.gold, '#0F6E56', '#7C3AED', '#DC2626']
          return `${colors[i % colors.length]} ${i * (100 / REWARDS.length)}% ${(i + 1) * (100 / REWARDS.length)}%`
        }).join(', ')})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transform: `rotate(${rotation}deg)`,
        transition: spinning ? 'transform 3.5s cubic-bezier(0.2, 0.8, 0.3, 1)' : 'none',
        border: `6rpx solid ${C.gold}`,
        position: 'relative',
      }}>
        {/* 中心按钮 */}
        <View
          onClick={handleSpin}
          style={{
            width: '120rpx', height: '120rpx', borderRadius: '50%',
            background: spinning ? C.bgCard : C.gold,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 10, boxShadow: '0 4rpx 12rpx rgba(0,0,0,0.3)',
          }}
        >
          <Text style={{ fontSize: '24rpx', fontWeight: '700', color: spinning ? C.text3 : '#1a1a00' }}>
            {spinning ? '...' : '抽奖'}
          </Text>
        </View>
      </View>

      {/* 指针 */}
      <Text style={{ fontSize: '40rpx', marginTop: '-20rpx' }}>▼</Text>

      {/* 奖品列表 */}
      <View style={{ marginTop: '32rpx', width: '100%' }}>
        <Text style={{ fontSize: '26rpx', color: C.text3, display: 'block', marginBottom: '12rpx' }}>奖品池</Text>
        <View style={{ display: 'flex', flexWrap: 'wrap', gap: '8rpx' }}>
          {REWARDS.map(r => (
            <View key={r.id} style={{ padding: '8rpx 16rpx', borderRadius: '8rpx', background: C.bgCard }}>
              <Text style={{ fontSize: '22rpx', color: C.text2 }}>{r.emoji} {r.name}</Text>
            </View>
          ))}
        </View>
      </View>
    </View>
  )
}
